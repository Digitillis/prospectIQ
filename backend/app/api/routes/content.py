"""Content API routes — LinkedIn thought leadership post management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.app.agents.content import CONTENT_CALENDAR, ContentAgent
from backend.app.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/content", tags=["content"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

# Pillar name normalisation: the agent uses short keys but the YAML uses
# longer display names. Map both conventions to the short canonical form.
_PILLAR_ALIAS: dict[str, str] = {
    "food_safety_compliance": "food_safety",
    "leadership_strategy": "leadership",
}

# How many posts each time_horizon maps to (4 posts/week = 1 week baseline)
_TIME_HORIZON_COUNTS: dict[str, int] = {
    "1_week": 4,
    "30_days": 16,
    "60_days": 32,
}

_ALL_PILLARS = ["food_safety", "predictive_maintenance", "ops_excellence", "leadership"]
_ALL_FORMATS = ["data_insight", "framework", "contrarian", "benchmark"]


class ContentRequest(BaseModel):
    topic: Optional[str] = None
    pillar: Optional[str] = None          # food_safety | predictive_maintenance | ops_excellence | leadership
    format_type: Optional[str] = None     # data_insight | framework | contrarian | benchmark
    # Batch generation fields
    time_horizon: Optional[str] = None    # "1_week" (4 posts) | "30_days" (16) | "60_days" (32)
    commentary: Optional[str] = None      # Free-text author guidance injected into each prompt
    batch: bool = False                   # If True, generate multiple posts based on time_horizon


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


def _detail_to_draft(detail: dict) -> dict:
    """Convert an agent result detail dict into a ContentDraft-shaped response dict."""
    return {
        "id": detail.get("draft_id", ""),
        "topic": detail.get("company", ""),
        "pillar": detail.get("pillar", ""),
        "format": detail.get("format", ""),
        "post_text": detail.get("post_text", ""),
        "char_count": detail.get("char_count", 0),
        "generated_at": detail.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "approval_status": "pending",
    }


def _normalise_pillar(pillar: Optional[str]) -> Optional[str]:
    """Normalise pillar names from YAML long form to the short canonical form."""
    if not pillar:
        return pillar
    return _PILLAR_ALIAS.get(pillar, pillar)


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
            pillar=_normalise_pillar(req.pillar),
            format_type=req.format_type,
            commentary=req.commentary,
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

    return {"data": _detail_to_draft(detail)}


@router.post("/generate-batch")
async def generate_batch(req: ContentRequest, background_tasks: BackgroundTasks):  # noqa: ARG001
    """Generate a batch of content posts for a time period.

    Post count is derived from time_horizon:
      1_week  →  4 posts
      30_days → 16 posts
      60_days → 32 posts

    If pillar is specified, all posts are for that pillar.
    Otherwise posts are distributed evenly across all 4 pillars.
    Format types rotate in order: data_insight, framework, contrarian, benchmark.
    Commentary (if provided) is injected into every Claude prompt.
    """
    pillar = _normalise_pillar(req.pillar)
    post_count = _TIME_HORIZON_COUNTS.get(req.time_horizon or "1_week", 4)

    # Build the list of (pillar, format, topic) jobs --------------------------
    jobs: list[dict[str, str]] = []

    # Build a pool of topics from CONTENT_CALENDAR, filtered by pillar if given
    calendar_pool = [
        e for e in CONTENT_CALENDAR
        if (pillar is None or e["pillar"] == pillar)
    ]

    # If pillar filter gives us no entries fall back to full calendar
    if not calendar_pool:
        calendar_pool = list(CONTENT_CALENDAR)

    pillars_to_use = [pillar] if pillar else _ALL_PILLARS

    for i in range(post_count):
        # Rotate format types
        fmt = _ALL_FORMATS[i % len(_ALL_FORMATS)]
        # Rotate through target pillars
        target_pillar = pillars_to_use[i % len(pillars_to_use)]

        # Try to find a matching calendar entry for this pillar+format combo
        pillar_entries = [e for e in calendar_pool if e["pillar"] == target_pillar]
        fmt_entries = [e for e in pillar_entries if e["format"] == fmt]

        if fmt_entries:
            entry = fmt_entries[i % len(fmt_entries)]
        elif pillar_entries:
            entry = pillar_entries[i % len(pillar_entries)]
            fmt = entry["format"]
        else:
            entry = calendar_pool[i % len(calendar_pool)]
            target_pillar = entry["pillar"]
            fmt = entry["format"]

        jobs.append({
            "topic": entry["topic"],
            "pillar": target_pillar,
            "format": fmt,
        })

    # Generate all posts sequentially, collecting drafts ----------------------
    agent = ContentAgent()
    generated_drafts: list[dict] = []
    errors: list[str] = []

    for job in jobs:
        try:
            result = agent.execute(
                topic=job["topic"],
                pillar=job["pillar"],
                format_type=job["format"],
                commentary=req.commentary,
                limit=1,
            )
            if result.success and result.details:
                detail = result.details[0]
                if detail.get("status") != "error":
                    generated_drafts.append(_detail_to_draft(detail))
                else:
                    errors.append(f"{job['topic']}: {detail.get('message', 'unknown error')}")
            else:
                errors.append(f"{job['topic']}: generation failed")
        except Exception as e:
            logger.error(f"Batch generation error for '{job['topic']}': {e}", exc_info=True)
            errors.append(f"{job['topic']}: {str(e)[:120]}")

    if not generated_drafts and errors:
        raise HTTPException(
            status_code=500,
            detail=f"All {len(errors)} posts failed to generate. First error: {errors[0]}",
        )

    return {
        "data": generated_drafts,
        "count": len(generated_drafts),
        "requested": post_count,
        "errors": errors,
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
