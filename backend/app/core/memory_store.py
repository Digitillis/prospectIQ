"""Memory Store — RAG knowledge base backed by Supabase + pgvector.

Supports two modes transparently:
  vector mode     — Voyage AI embeddings + cosine similarity search
  text_search     — PostgreSQL tsvector full-text search (zero-cost fallback)

Callers don't need to know which mode is active. retrieve() works in both.

Usage:
    store = MemoryStore(db, workspace_id)
    store.ingest(item_id="uuid", title="FSMA Compliance Guide", content="...")
    results = store.retrieve("What messaging works for food safety directors?", k=5)
    # results: list of {"content": str, "source_ref": str, "relevance": float}
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.core.embedder import Embedder

logger = logging.getLogger(__name__)


class MemoryStore:
    """Ingest, retrieve, and track access of knowledge items."""

    def __init__(self, db: Any, workspace_id: str) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self._embedder = Embedder()

    @property
    def mode(self) -> str:
        return self._embedder.mode

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self, item_id: str, title: str, content: str) -> int:
        """Chunk + embed a knowledge item and upsert into memory_nodes.

        Skips chunks whose content_hash already exists (idempotent).

        Args:
            item_id: UUID of the knowledge_items row.
            title: Item title (prepended to first chunk for context).
            content: Full document text.

        Returns:
            Number of new chunks inserted.
        """
        chunks = self._embedder.chunk(content)
        if not chunks:
            return 0

        # Prepend title to first chunk for context
        chunks[0] = f"{title}\n\n{chunks[0]}"

        # Get existing hashes to skip re-embedding
        existing_hashes = self._get_existing_hashes(item_id)

        new_chunks = []
        new_texts = []
        for idx, chunk in enumerate(chunks):
            h = self._embedder.content_hash(chunk)
            if h in existing_hashes:
                continue
            new_chunks.append((idx, chunk, h))
            new_texts.append(chunk)

        if not new_chunks:
            return 0

        # Embed all new chunks in one batched call
        embeddings = self._embedder.embed(new_texts) if new_texts else None

        inserted = 0
        for i, (idx, chunk, h) in enumerate(new_chunks):
            embedding = None
            if embeddings and i < len(embeddings) and embeddings[i] is not None:
                embedding = embeddings[i]

            row: dict[str, Any] = {
                "workspace_id": self.workspace_id,
                "knowledge_item_id": item_id,
                "content": chunk,
                "content_hash": h,
                "source_ref": f"{item_id}:chunk_{idx}",
            }
            if embedding is not None:
                row["embedding"] = embedding

            try:
                self.db.client.table("memory_nodes").insert(row).execute()
                inserted += 1
            except Exception as e:
                logger.error(f"MemoryStore.ingest: insert failed for chunk {idx}: {e}")

        logger.info(
            f"MemoryStore.ingest: {item_id} — {inserted} new chunks "
            f"({len(existing_hashes)} skipped, mode={self.mode})"
        )
        return inserted

    def delete_item(self, item_id: str) -> None:
        """Delete all memory_nodes for a knowledge item (ON DELETE CASCADE handles this)."""
        try:
            self.db.client.table("knowledge_items").delete().eq("id", item_id).execute()
        except Exception as e:
            logger.error(f"MemoryStore.delete_item: {e}")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        """Retrieve the k most relevant memory nodes for a query.

        Automatically uses vector similarity when available, or full-text
        search as fallback.

        Args:
            query: Natural language query string.
            k: Number of results to return.

        Returns:
            List of dicts with keys: content, source_ref, relevance, mode
        """
        if self.mode == "vector":
            results = self._retrieve_vector(query, k)
        else:
            results = self._retrieve_text(query, k)

        # Track access counts
        if results:
            self._track_access([r.get("node_id") for r in results if r.get("node_id")])

        return results

    def _retrieve_vector(self, query: str, k: int) -> list[dict]:
        """Cosine similarity search via pgvector."""
        query_vec = self._embedder.embed_query(query)
        if query_vec is None:
            return self._retrieve_text(query, k)  # Fallback

        try:
            # Use Supabase's rpc for pgvector cosine similarity
            result = self.db.client.rpc(
                "match_memory_nodes",
                {
                    "query_embedding": query_vec,
                    "workspace_filter": self.workspace_id,
                    "match_count": k,
                },
            ).execute()
            rows = result.data or []
        except Exception as e:
            logger.warning(f"MemoryStore._retrieve_vector: pgvector query failed: {e}. Falling back to text search.")
            return self._retrieve_text(query, k)

        return [
            {
                "content": r.get("content", ""),
                "source_ref": r.get("source_ref", ""),
                "relevance": round(1 - r.get("distance", 1.0), 3),
                "mode": "vector",
                "node_id": r.get("id"),
            }
            for r in rows
        ]

    def _retrieve_text(self, query: str, k: int) -> list[dict]:
        """PostgreSQL tsvector full-text search fallback."""
        # Sanitise query for tsvector: keep only word characters
        import re
        words = re.findall(r"\w+", query)[:10]
        if not words:
            return []
        tsquery = " & ".join(words)

        try:
            result = self.db.client.rpc(
                "match_memory_nodes_text",
                {
                    "search_query": tsquery,
                    "workspace_filter": self.workspace_id,
                    "match_count": k,
                },
            ).execute()
            rows = result.data or []
        except Exception as e:
            logger.error(f"MemoryStore._retrieve_text: text search failed: {e}")
            return []

        return [
            {
                "content": r.get("content", ""),
                "source_ref": r.get("source_ref", ""),
                "relevance": round(r.get("rank", 0.0), 3),
                "mode": "text_search",
                "node_id": r.get("id"),
            }
            for r in rows
        ]

    def format_for_prompt(self, results: list[dict], max_chars: int = 2000) -> str:
        """Format retrieved results into a prompt-ready string.

        Truncates to max_chars to control token consumption.
        """
        if not results:
            return ""

        parts = ["### RELEVANT KNOWLEDGE BASE CONTEXT"]
        total = 0
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            relevance = r.get("relevance", 0)
            if total + len(content) > max_chars:
                break
            parts.append(f"\n[{i}] (relevance: {relevance:.2f})\n{content}")
            total += len(content)

        parts.append("")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_existing_hashes(self, item_id: str) -> set[str]:
        try:
            result = (
                self.db.client.table("memory_nodes")
                .select("content_hash")
                .eq("knowledge_item_id", item_id)
                .execute()
            )
            return {r["content_hash"] for r in (result.data or [])}
        except Exception:
            return set()

    def _track_access(self, node_ids: list[str | None]) -> None:
        from datetime import datetime, timezone
        ids = [nid for nid in node_ids if nid]
        if not ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            for nid in ids:
                self.db.client.rpc(
                    "increment_memory_access",
                    {"node_id": nid, "accessed_at": now},
                ).execute()
        except Exception as e:
            logger.debug(f"MemoryStore._track_access: {e}")
