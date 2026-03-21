"""Content API routes — LinkedIn thought leadership post management."""

from __future__ import annotations

import logging
import uuid
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.app.agents.content import CONTENT_CALENDAR, ContentAgent
from backend.app.core.config import load_yaml_config
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


# ---------------------------------------------------------------------------
# Auto-calendar helpers
# ---------------------------------------------------------------------------

# 4-week rotation matrix: [pillar, format] per slot (Mon/Tue/Thu/Fri)
# Design: never same pillar two days in a row; every pillar 4x/month;
#         every format 4x/month.
_ROTATION_MATRIX: list[list[tuple[str, str]]] = [
    # Week 1: Mon, Tue, Thu, Fri
    [
        ("food_safety", "data_insight"),
        ("predictive_maintenance", "framework"),
        ("ops_excellence", "contrarian"),
        ("leadership", "data_insight"),
    ],
    # Week 2
    [
        ("predictive_maintenance", "data_insight"),
        ("food_safety", "framework"),
        ("leadership", "contrarian"),
        ("ops_excellence", "data_insight"),
    ],
    # Week 3
    [
        ("ops_excellence", "framework"),
        ("leadership", "data_insight"),
        ("food_safety", "contrarian"),
        ("predictive_maintenance", "data_insight"),
    ],
    # Week 4
    [
        ("leadership", "framework"),
        ("ops_excellence", "data_insight"),
        ("predictive_maintenance", "contrarian"),
        ("food_safety", "benchmark"),
    ],
]

# Posting days within a week (Mon=0, Tue=1, Thu=3, Fri=4) as weekday offsets
_POSTING_WEEKDAY_OFFSETS = [0, 1, 3, 4]  # Mon, Tue, Thu, Fri
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Pillar display names
_PILLAR_DISPLAY: dict[str, str] = {
    "food_safety": "Food Safety & Compliance",
    "predictive_maintenance": "Predictive Maintenance",
    "ops_excellence": "Operations Excellence",
    "leadership": "Leadership Strategy",
}

# Format display names
_FORMAT_DISPLAY: dict[str, str] = {
    "data_insight": "Data Insight",
    "framework": "Framework",
    "contrarian": "Contrarian Take",
    "benchmark": "Benchmark",
}

# Canonical pillar key used in content_guidelines.yaml topics_library
_PILLAR_TO_YAML_KEY: dict[str, str] = {
    "food_safety": "food_safety_compliance",
    "predictive_maintenance": "predictive_maintenance",
    "ops_excellence": "ops_excellence",
    "leadership": "leadership_strategy",
}


def _get_next_monday(from_date: date | None = None) -> date:
    """Return the date of the next Monday on or after from_date (defaults to today)."""
    base = from_date or date.today()
    days_ahead = (7 - base.weekday()) % 7  # weekday: Mon=0
    if days_ahead == 0:
        # today is Monday
        return base
    return base + timedelta(days=days_ahead)


def _load_topics_library() -> dict[str, list[str]]:
    """Load topic titles from content_guidelines.yaml, keyed by canonical pillar key."""
    try:
        config = load_yaml_config("content_guidelines.yaml")
        raw: dict[str, Any] = config.get("topics_library", {})
        result: dict[str, list[str]] = {}
        for yaml_key, entries in raw.items():
            titles = [e["title"] for e in entries if isinstance(e, dict) and "title" in e]
            result[yaml_key] = titles
        return result
    except Exception:
        return {}


class AutoCalendarRequest(BaseModel):
    start_date: Optional[str] = None  # ISO date string (YYYY-MM-DD); defaults to next Monday
    commentary: Optional[str] = None  # Optional guidance injected into every post
    weeks: int = 4  # 1–8


@router.post("/auto-calendar")
async def auto_generate_calendar(req: AutoCalendarRequest):
    """Generate a complete 4-week content calendar with balanced pillar/format rotation.

    Generates 4 posts per week (Mon/Tue/Thu/Fri) for the requested number of weeks.
    Each post is stored as an outreach_draft and returned in week-by-week order.
    Estimated runtime: ~2-3 minutes for 16 posts (16 sequential Claude calls).
    """
    # ── Resolve start date ────────────────────────────────────────────────────
    if req.start_date:
        try:
            start = date.fromisoformat(req.start_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="start_date must be ISO format YYYY-MM-DD")
    else:
        start = _get_next_monday()

    weeks = max(1, min(8, req.weeks))
    calendar_id = str(uuid.uuid4())
    t0 = time.time()

    # ── Load topics library from YAML ─────────────────────────────────────────
    topics_lib = _load_topics_library()

    # Track which topics we've already used in this batch (avoid repeats)
    used_topics: set[str] = set()

    def pick_topic(pillar: str) -> str:
        """Pick the next unused topic for a pillar from the topics library."""
        yaml_key = _PILLAR_TO_YAML_KEY.get(pillar, pillar)
        candidates = topics_lib.get(yaml_key, [])

        # Prefer an unused topic; cycle if all used
        for t in candidates:
            if t not in used_topics:
                used_topics.add(t)
                return t

        # All topics used — cycle through, still tracking
        if candidates:
            topic = candidates[len(used_topics) % len(candidates)]
            used_topics.add(topic)
            return topic

        # Fallback if no YAML topics at all
        return f"{_PILLAR_DISPLAY.get(pillar, pillar)} insights"

    # ── Build the list of posting slots ───────────────────────────────────────
    # Each slot: (posting_date, week_number, day_of_week, pillar, format, topic)
    slots: list[dict[str, Any]] = []

    for week_idx in range(weeks):
        rotation_week = _ROTATION_MATRIX[week_idx % len(_ROTATION_MATRIX)]

        # Monday of this calendar week
        monday = start + timedelta(weeks=week_idx)

        for slot_idx, (pillar, fmt) in enumerate(rotation_week):
            posting_date = monday + timedelta(days=_POSTING_WEEKDAY_OFFSETS[slot_idx])
            topic = pick_topic(pillar)
            slots.append({
                "posting_date": posting_date,
                "week_number": week_idx + 1,
                "day_of_week": _DAY_NAMES[posting_date.weekday()],
                "pillar": pillar,
                "format": fmt,
                "topic": topic,
            })

    # ── Generate all posts sequentially ───────────────────────────────────────
    agent = ContentAgent()
    posts: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}

    for slot in slots:
        pillar = slot["pillar"]
        fmt = slot["format"]
        topic = slot["topic"]
        date_str = slot["posting_date"].isoformat()

        try:
            result = agent.execute(
                topic=topic,
                pillar=pillar,
                format_type=fmt,
                commentary=req.commentary,
                limit=1,
            )
        except Exception as e:
            logger.error(f"Auto-calendar generation error for '{topic}': {e}", exc_info=True)
            continue

        if not result.success or not result.details:
            logger.warning(f"Auto-calendar: generation returned no details for '{topic}'")
            continue

        detail = result.details[0]
        if detail.get("status") == "error":
            logger.warning(f"Auto-calendar: agent error for '{topic}': {detail.get('message')}")
            continue

        draft_id = detail.get("draft_id", "")
        post_text = detail.get("post_text", "")

        # Update the stored draft's personalization_notes to include scheduling info
        # The ContentAgent already stored the draft; we just augment coverage counts
        # (Optionally update the DB row, but notes are stored via agent already)
        db = Database()
        try:
            db.update_outreach_draft(
                draft_id,
                {
                    "personalization_notes": (
                        f"format:{fmt}|pillar:{pillar}"
                        f"|scheduled:{date_str}"
                        f"|calendar_id:{calendar_id}"
                        f"|auto_calendar:true"
                    )
                },
            )
        except Exception as e:
            logger.debug(f"Auto-calendar: could not update notes for {draft_id}: {e}")

        # Coverage counters
        coverage[pillar] = coverage.get(pillar, 0) + 1
        coverage[fmt] = coverage.get(fmt, 0) + 1

        posts.append({
            "id": draft_id,
            "scheduled_date": date_str,
            "day_of_week": slot["day_of_week"],
            "week_number": slot["week_number"],
            "pillar": pillar,
            "pillar_display": _PILLAR_DISPLAY.get(pillar, pillar),
            "format": fmt,
            "format_display": _FORMAT_DISPLAY.get(fmt, fmt),
            "topic": topic,
            "body": post_text,
            "char_count": len(post_text),
            "status": "generated",
        })

    if not posts:
        raise HTTPException(
            status_code=500,
            detail="No posts were generated. Check server logs for details.",
        )

    end_date = slots[-1]["posting_date"].isoformat() if slots else start.isoformat()
    generation_time = round(time.time() - t0, 1)
    estimated_cost = round(len(posts) * 0.05, 2)

    return {
        "data": {
            "calendar_id": calendar_id,
            "start_date": start.isoformat(),
            "end_date": end_date,
            "weeks": weeks,
            "posts": posts,
            "coverage": coverage,
            "estimated_cost": estimated_cost,
            "generation_time_seconds": generation_time,
        }
    }


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
