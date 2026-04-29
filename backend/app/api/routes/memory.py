"""Memory / Knowledge Base API routes.

Endpoints:
    POST   /api/memory/items        — upload knowledge item + ingest into RAG
    GET    /api/memory/items        — list knowledge items
    DELETE /api/memory/items/{id}   — delete item + all associated nodes
    POST   /api/memory/retrieve     — semantic/text search query
    GET    /api/memory/status       — RAG mode (vector vs text_search) + stats
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.memory_store import MemoryStore
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class KnowledgeItemCreate(BaseModel):
    title: str
    type: str  # icp | template | competitor | case_study | offer | general
    content: str
    metadata: dict = {}


class RetrieveRequest(BaseModel):
    query: str
    k: int = 5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/items", status_code=201)
async def upload_knowledge_item(payload: KnowledgeItemCreate):
    """Upload a knowledge item and ingest it into the RAG memory store."""
    valid_types = {"icp", "template", "competitor", "case_study", "offer", "general"}
    if payload.type not in valid_types:
        raise HTTPException(400, f"Invalid type. Must be one of: {', '.join(valid_types)}")

    if len(payload.content) < 10:
        raise HTTPException(400, "Content too short (minimum 10 characters).")

    db = get_db()
    workspace_id = get_workspace_id()

    # Insert knowledge item row
    try:
        result = db.client.table("knowledge_items").insert({
            "workspace_id": workspace_id,
            "title": payload.title,
            "type": payload.type,
            "content": payload.content,
            "metadata": payload.metadata,
        }).execute()
        item = result.data[0]
        item_id = item["id"]
    except Exception as e:
        logger.error(f"memory.upload: insert failed: {e}")
        raise HTTPException(500, "Failed to create knowledge item.")

    # Ingest into memory store (chunk + embed)
    try:
        store = MemoryStore(db, workspace_id)
        chunks_inserted = store.ingest(
            item_id=item_id,
            title=payload.title,
            content=payload.content,
        )
    except Exception as e:
        logger.error(f"memory.upload: ingest failed: {e}")
        chunks_inserted = 0

    return {
        "id": item_id,
        "title": payload.title,
        "type": payload.type,
        "char_count": len(payload.content),
        "chunks_inserted": chunks_inserted,
        "rag_mode": MemoryStore(db, workspace_id).mode,
    }


@router.get("/items")
async def list_knowledge_items(type: Optional[str] = None):
    """List all knowledge items for this workspace."""
    db = get_db()
    workspace_id = get_workspace_id()
    try:
        query = (
            db.client.table("knowledge_items")
            .select("id, title, type, char_count, metadata, created_at, updated_at")
            .eq("workspace_id", workspace_id)
            .order("created_at", desc=True)
        )
        if type:
            query = query.eq("type", type)
        result = query.execute()

        # Annotate each item with its chunk count
        items = result.data or []
        for item in items:
            try:
                count_result = (
                    db.client.table("memory_nodes")
                    .select("id", count="exact")
                    .eq("knowledge_item_id", item["id"])
                    .execute()
                )
                item["chunk_count"] = count_result.count or 0
            except Exception:
                item["chunk_count"] = 0

        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"memory.list: {e}")
        raise HTTPException(500, "Failed to list knowledge items.")


@router.delete("/items/{item_id}")
async def delete_knowledge_item(item_id: str):
    """Delete a knowledge item and all its associated memory nodes."""
    db = get_db()
    workspace_id = get_workspace_id()
    try:
        # Verify ownership
        check = (
            db.client.table("knowledge_items")
            .select("id")
            .eq("id", item_id)
            .eq("workspace_id", workspace_id)
            .single()
            .execute()
        )
        if not check.data:
            raise HTTPException(404, "Knowledge item not found.")

        # ON DELETE CASCADE removes memory_nodes automatically
        db.client.table("knowledge_items").delete().eq("id", item_id).execute()
        return {"deleted": True, "id": item_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"memory.delete: {e}")
        raise HTTPException(500, "Failed to delete knowledge item.")


@router.post("/retrieve")
async def retrieve_context(payload: RetrieveRequest):
    """Run a semantic or full-text search against the knowledge base."""
    if not payload.query.strip():
        raise HTTPException(400, "Query cannot be empty.")

    k = max(1, min(payload.k, 10))
    db = get_db()
    workspace_id = get_workspace_id()
    store = MemoryStore(db, workspace_id)

    results = store.retrieve(payload.query, k=k)
    return {
        "query": payload.query,
        "results": results,
        "mode": store.mode,
        "count": len(results),
    }


@router.get("/status")
async def memory_status():
    """Return RAG mode and knowledge base statistics."""
    db = get_db()
    workspace_id = get_workspace_id()
    store = MemoryStore(db, workspace_id)

    try:
        items_result = (
            db.client.table("knowledge_items")
            .select("id", count="exact")
            .eq("workspace_id", workspace_id)
            .execute()
        )
        nodes_result = (
            db.client.table("memory_nodes")
            .select("id", count="exact")
            .eq("workspace_id", workspace_id)
            .execute()
        )
        top_accessed = (
            db.client.table("memory_nodes")
            .select("content, source_ref, access_count, last_accessed_at")
            .eq("workspace_id", workspace_id)
            .order("access_count", desc=True)
            .limit(5)
            .execute()
        )
        return {
            "mode": store.mode,
            "mode_description": (
                "Semantic vector search (Voyage AI)" if store.mode == "vector"
                else "PostgreSQL full-text search (no Voyage AI key set)"
            ),
            "knowledge_items": items_result.count or 0,
            "memory_nodes": nodes_result.count or 0,
            "top_accessed": top_accessed.data or [],
        }
    except Exception as e:
        logger.error(f"memory.status: {e}")
        return {"mode": store.mode, "error": str(e)}
