"""Content API routes — LinkedIn thought leadership post management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.agents.content import CONTENT_CALENDAR, ContentAgent
from backend.app.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/content", tags=["content"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ContentRequest(BaseModel):
    topic: Optional[str] = None
    pillar: Optional[str] = None          # food_safety | predictive_maintenance | ops_excellence | leadership
    format_type: Optional[str] = None     # data_insight | framework | contrarian | benchmark


class ContentDraft(BaseModel):
    id: str
    topic: str
    pillar: str
    format: str
    post_text: str
    char_count: int
    generated_at: str
    approval_status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_draft(row: dict) -> dict:
    """Convert an outreach_drafts DB row to a ContentDraft-shaped dict."""
    notes = row.get("personalization_notes", "") or ""
    pillar = ""
    fmt = ""
    for part in notes.split("|"):
        if part.startswith("format:"):
            fmt = part[len("format:"):]
        elif part.startswith("pillar:"):
            pillar = part[len("pillar:"):]

    body = row.get("body", "") or ""
    return {
        "id": row.get("id", ""),
        "topic": row.get("subject", ""),
        "pillar": pillar,
        "format": fmt,
        "post_text": body,
        "char_count": len(body),
        "generated_at": row.get("created_at", datetime.now(timezone.utc).isoformat()),
        "approval_status": row.get("approval_status", "pending"),
    }


def _get_content_drafts(db: Database) -> list[dict]:
    """Fetch all thought_leadership drafts from outreach_drafts."""
    try:
        result = (
            db.client.table("outreach_drafts")
            .select("*")
            .eq("sequence_name", "thought_leadership")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Error fetching content drafts: {e}")
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/calendar")
async def get_content_calendar():
    """Return the full 4-week content calendar."""
    return {"data": CONTENT_CALENDAR}


@router.post("/generate")
async def generate_content(req: ContentRequest):
    """Generate a LinkedIn post draft using Claude.

    - If topic is provided, generates a post for that topic.
    - If pillar + format_type, picks the matching calendar entry.
    - If nothing provided, generates the next post from the calendar.
    """
    agent = ContentAgent()

    try:
        result = agent.execute(
            topic=req.topic,
            pillar=req.pillar,
            format_type=req.format_type,
            limit=1,
        )
    except Exception as e:
        logger.error(f"ContentAgent failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    if not result.success or result.errors > 0:
        raise HTTPException(
            status_code=500,
            detail="Content generation failed. Check server logs for details.",
        )

    if not result.details:
        raise HTTPException(status_code=500, detail="No draft was generated.")

    detail = result.details[0]

    if detail.get("status") == "error":
        raise HTTPException(status_code=500, detail=detail.get("message", "Unknown error"))

    return {
        "data": {
            "id": detail.get("draft_id", ""),
            "topic": detail.get("company", ""),
            "pillar": detail.get("pillar", ""),
            "format": detail.get("format", ""),
            "post_text": detail.get("post_text", ""),
            "char_count": detail.get("char_count", 0),
            "generated_at": detail.get("generated_at", datetime.now(timezone.utc).isoformat()),
            "approval_status": "pending",
        }
    }


@router.get("/drafts")
async def get_content_drafts():
    """List generated but not-yet-posted content drafts."""
    db = Database()
    rows = _get_content_drafts(db)
    drafts = [_parse_draft(r) for r in rows if r.get("approval_status") != "approved"]
    return {"data": drafts, "count": len(drafts)}


@router.post("/{draft_id}/mark-posted")
async def mark_content_posted(draft_id: str):
    """Mark a content draft as posted (approval_status = 'approved')."""
    db = Database()
    try:
        updated = db.update_outreach_draft(draft_id, {"approval_status": "approved"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB update failed: {str(e)}")

    if not updated:
        raise HTTPException(status_code=404, detail="Draft not found")

    return {"message": "Marked as posted", "data": _parse_draft(updated)}
