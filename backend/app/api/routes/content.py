"""Content API routes — LinkedIn thought leadership post management."""

from __future__ import annotations

import hashlib
import logging
import uuid
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
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
_PILLAR_ALIAS: dict[str, str] = {}

# How many posts each time_horizon maps to (4 posts/week = 1 week baseline)
_TIME_HORIZON_COUNTS: dict[str, int] = {
    "1_week": 3,
    "30_days": 12,
    "60_days": 24,
}

_ALL_PILLARS = ["manufacturing_intelligence", "manufacturing_strategy", "manufacturing_operations", "food_safety_compliance"]
_ALL_FORMATS = ["data_insight", "framework", "contrarian", "benchmark"]


class ContentRequest(BaseModel):
    topic: Optional[str] = None
    pillar: Optional[str] = None          # manufacturing_intelligence | manufacturing_strategy | manufacturing_operations | food_safety_compliance
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

def _parse_quality_report(notes: str) -> Optional[dict]:
    """Extract and parse a quality_report JSON from personalization_notes."""
    import json as _json
    import re
    match = re.search(r"quality_report::(.+)", notes, re.DOTALL)
    if match:
        try:
            return _json.loads(match.group(1))
        except Exception:
            return None
    return None


def _parse_intel_report(notes: str) -> Optional[str]:
    """Extract the raw intel report text from personalization_notes."""
    import re
    # intel_report:: comes before quality_report:: (if present)
    match = re.search(r"intel_report::(.+?)(?:\|quality_report::|$)", notes, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _parse_draft(row: dict) -> dict:
    """Convert an outreach_drafts DB row to a ContentDraft-shaped dict."""
    notes = row.get("personalization_notes", "") or ""

    # Extract intel report and quality report FIRST (they contain pipes/newlines)
    # then strip them from notes before pipe-splitting the simple key:value fields
    quality_report = _parse_quality_report(notes)
    intel_report = _parse_intel_report(notes)

    # Strip intel_report:: and quality_report:: sections for clean pipe-split
    import re
    clean_notes = re.sub(r"\|intel_report::.*?(?=\|quality_report::|$)", "", notes, flags=re.DOTALL)
    clean_notes = re.sub(r"\|quality_report::.*", "", clean_notes, flags=re.DOTALL)

    pillar = ""
    fmt = ""
    credibility_score = None
    publish_ready = None
    for part in clean_notes.split("|"):
        if part.startswith("format:"):
            fmt = part[len("format:"):]
        elif part.startswith("pillar:"):
            pillar = part[len("pillar:"):]
        elif part.startswith("credibility:"):
            try:
                credibility_score = int(part[len("credibility:"):].split("/")[0])
            except (ValueError, IndexError):
                pass
        elif part.startswith("publish_ready:"):
            val = part[len("publish_ready:"):]
            publish_ready = val.lower() == "true"

    body = row.get("body", "") or ""

    intel = None
    if intel_report or credibility_score is not None:
        intel = {
            "report": intel_report,
            "credibility_score": credibility_score,
            "publish_ready": publish_ready,
            "verification_rounds": 3 if intel_report else None,
            "error": None,
        }

    return {
        "id": row.get("id", ""),
        "topic": row.get("subject", ""),
        "pillar": pillar,
        "format": fmt,
        "post_text": body,
        "char_count": len(body),
        "generated_at": row.get("created_at", datetime.now(timezone.utc).isoformat()),
        "approval_status": row.get("approval_status", "pending"),
        "credibility_score": credibility_score,
        "publish_ready": publish_ready,
        "quality_report": quality_report,
        "intel": intel,
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
    intel = detail.get("intel")
    return {
        "id": detail.get("draft_id", ""),
        "topic": detail.get("company", ""),
        "pillar": detail.get("pillar", ""),
        "format": detail.get("format", ""),
        "post_text": detail.get("post_text", ""),
        "char_count": detail.get("char_count", 0),
        "generated_at": detail.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "approval_status": "pending",
        "credibility_score": detail.get("credibility_score"),
        "publish_ready": detail.get("publish_ready"),
        "quality_report": detail.get("quality_report") or None,
        "intel": {
            "report": intel.get("intel_report", "") if intel and not intel.get("error") else None,
            "credibility_score": intel.get("credibility_score", 0) if intel else None,
            "publish_ready": intel.get("publish_ready", False) if intel else None,
            "verification_rounds": intel.get("verification_rounds", 0) if intel else None,
            "error": intel.get("error") if intel and intel.get("error") else None,
        } if intel else None,
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
        # Surface actual error details instead of a generic message
        error_detail = "Content generation failed."
        if result.details:
            first = result.details[0]
            msg = first.get("message", "")
            if msg:
                error_detail = f"Content generation failed: {msg}"
        raise HTTPException(status_code=500, detail=error_detail)

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

# 4-week rotation matrix: [pillar, format] per slot (Tue/Thu/Sat)
# Design: Tue = manufacturing_intelligence, Thu = alternating strategy/operations,
#         Sat = food_safety_compliance. 3 posts/week.
_ROTATION_MATRIX: list[list[tuple[str, str]]] = [
    # Week 1: Tue, Thu, Sat
    [
        ("manufacturing_intelligence", "contrarian"),
        ("manufacturing_strategy", "framework"),
        ("food_safety_compliance", "data_insight"),
    ],
    # Week 2
    [
        ("manufacturing_intelligence", "framework"),
        ("manufacturing_operations", "contrarian"),
        ("food_safety_compliance", "data_insight"),
    ],
    # Week 3
    [
        ("manufacturing_intelligence", "data_insight"),
        ("manufacturing_strategy", "framework"),
        ("food_safety_compliance", "contrarian"),
    ],
    # Week 4
    [
        ("manufacturing_intelligence", "data_insight"),
        ("manufacturing_operations", "contrarian"),
        ("food_safety_compliance", "benchmark"),
    ],
]

# Posting days within a week (Mon=0, Tue=1, Thu=3, Fri=4) as weekday offsets
_POSTING_WEEKDAY_OFFSETS = [1, 3, 5]  # Tue, Thu, Sat
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Pillar display names
_PILLAR_DISPLAY: dict[str, str] = {
    "manufacturing_intelligence": "Manufacturing Intelligence & AI",
    "manufacturing_strategy": "Manufacturing Strategy & Leadership",
    "manufacturing_operations": "Operations Excellence & Performance",
    "food_safety_compliance": "Food Safety & Compliance",
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
    "manufacturing_intelligence": "manufacturing_intelligence",
    "manufacturing_strategy": "manufacturing_strategy",
    "manufacturing_operations": "manufacturing_operations",
    "food_safety_compliance": "food_safety_compliance",
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
    """Generate a content calendar with balanced pillar/format rotation.

    Generates 3 posts per week (Tue/Thu/Sat) for the requested number of weeks.
    Each post is stored as an outreach_draft and returned in week-by-week order.
    Estimated runtime: ~2-3 minutes for 12 posts (12 sequential Claude calls).
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


# ---------------------------------------------------------------------------
# Content Archive
# ---------------------------------------------------------------------------

class ArchiveRequest(BaseModel):
    linkedin_post_url: Optional[str] = None
    posted_at: Optional[str] = None  # ISO date/datetime, defaults to now


class EngagementUpdate(BaseModel):
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    linkedin_post_url: Optional[str] = None


def _topic_hash(topic: str) -> str:
    """SHA-256 of the lowercased, stripped topic string."""
    return hashlib.sha256(topic.lower().strip().encode()).hexdigest()


@router.get("/archive")
async def get_content_archive(
    pillar: Optional[str] = Query(default=None),
    format: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all archived (posted) content, ordered by posted_at DESC."""
    db = Database()
    try:
        query = (
            db.client.table("content_archive")
            .select("*")
            .order("posted_at", desc=True)
        )
        if pillar:
            query = query.eq("pillar", pillar)
        if format:
            query = query.eq("format", format)
        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        return {"data": result.data or []}
    except Exception as e:
        logger.error(f"Error fetching content archive: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch archive: {str(e)}")


@router.post("/{draft_id}/archive")
async def archive_content(draft_id: str, req: ArchiveRequest):
    """Archive a posted draft into content_archive and mark it as approved."""
    db = Database()

    # Fetch the source draft
    try:
        drafts_res = (
            db.client.table("outreach_drafts")
            .select("*")
            .eq("id", draft_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not drafts_res.data:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft_row = drafts_res.data[0]

    # Parse pillar/format from personalization_notes
    notes = draft_row.get("personalization_notes", "") or ""
    pillar = ""
    fmt = ""
    for part in notes.split("|"):
        if part.startswith("format:"):
            fmt = part[len("format:"):]
        elif part.startswith("pillar:"):
            pillar = part[len("pillar:"):]

    # Resolve posted_at
    if req.posted_at:
        try:
            posted_dt = datetime.fromisoformat(req.posted_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="posted_at must be ISO format")
    else:
        posted_dt = datetime.now(timezone.utc)

    post_text = draft_row.get("body", "") or ""
    topic = draft_row.get("subject", "") or ""

    # Build archive row
    archive_row: dict[str, Any] = {
        "topic": topic,
        "pillar": pillar or None,
        "format": fmt or None,
        "post_text": post_text,
        "char_count": len(post_text),
        "posted_at": posted_dt.isoformat(),
        "linkedin_post_url": req.linkedin_post_url,
        "draft_id": draft_id,
        "topic_hash": _topic_hash(topic),
        "last_posted_topic_at": posted_dt.isoformat(),
    }

    # Try to pull credibility / intel from notes
    credibility_score = None
    publish_ready = None
    for part in notes.split("|"):
        if part.startswith("credibility:"):
            try:
                credibility_score = int(part[len("credibility:"):].split("/")[0])
            except (ValueError, IndexError):
                pass
        elif part.startswith("publish_ready:"):
            val = part[len("publish_ready:"):]
            publish_ready = val.lower() == "true"

    if credibility_score is not None:
        archive_row["credibility_score"] = credibility_score
    if publish_ready is not None:
        archive_row["publish_ready"] = publish_ready

    try:
        insert_res = db.client.table("content_archive").insert(archive_row).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive: {str(e)}")

    if not insert_res.data:
        raise HTTPException(status_code=500, detail="Archive insert returned no data")

    # Mark the source draft as approved
    try:
        db.update_outreach_draft(draft_id, {"approval_status": "approved"})
    except Exception as e:
        logger.warning(f"Could not mark draft {draft_id} as approved: {e}")

    return {"data": insert_res.data[0]}


@router.patch("/archive/{archive_id}/engagement")
async def update_engagement(archive_id: str, req: EngagementUpdate):
    """Update engagement metrics for an archived post and auto-compute engagement_rate."""
    db = Database()

    # Fetch existing row to merge
    try:
        existing_res = (
            db.client.table("content_archive")
            .select("impressions, likes, comments, shares")
            .eq("id", archive_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not existing_res.data:
        raise HTTPException(status_code=404, detail="Archive entry not found")

    row = existing_res.data[0]

    # Merge with request values
    impressions = req.impressions if req.impressions is not None else (row.get("impressions") or 0)
    likes = req.likes if req.likes is not None else (row.get("likes") or 0)
    comments = req.comments if req.comments is not None else (row.get("comments") or 0)
    shares = req.shares if req.shares is not None else (row.get("shares") or 0)

    engagement_rate: Optional[float] = None
    if impressions and impressions > 0:
        engagement_rate = (likes + comments + shares) / impressions

    update_data: dict[str, Any] = {
        "impressions": impressions,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "engagement_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if engagement_rate is not None:
        update_data["engagement_rate"] = engagement_rate
    if req.linkedin_post_url is not None:
        update_data["linkedin_post_url"] = req.linkedin_post_url

    try:
        update_res = (
            db.client.table("content_archive")
            .update(update_data)
            .eq("id", archive_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update engagement: {str(e)}")

    data = update_res.data[0] if update_res.data else {"id": archive_id, **update_data}
    return {"data": data}


@router.get("/archive/analytics")
async def get_archive_analytics():
    """Return engagement analytics across all archived posts."""
    db = Database()
    try:
        result = db.client.table("content_archive").select("*").execute()
        rows = result.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch analytics: {str(e)}")

    total_posts = len(rows)
    credibility_scores = [r["credibility_score"] for r in rows if r.get("credibility_score") is not None]
    avg_credibility = round(sum(credibility_scores) / len(credibility_scores), 1) if credibility_scores else 0.0

    # Aggregate by pillar
    by_pillar: dict[str, dict[str, Any]] = {}
    by_format: dict[str, dict[str, Any]] = {}

    for row in rows:
        rate = row.get("engagement_rate")
        pillar = row.get("pillar") or "unknown"
        fmt = row.get("format") or "unknown"

        if rate is not None:
            for key, bucket in [(pillar, by_pillar), (fmt, by_format)]:
                if key not in bucket:
                    bucket[key] = {"sum": 0.0, "count": 0}
                bucket[key]["sum"] += rate
                bucket[key]["count"] += 1

    by_pillar_out = {
        k: {"avg_rate": round(v["sum"] / v["count"], 4), "count": v["count"]}
        for k, v in by_pillar.items()
    }
    by_format_out = {
        k: {"avg_rate": round(v["sum"] / v["count"], 4), "count": v["count"]}
        for k, v in by_format.items()
    }

    # Top 5 by engagement_rate
    sorted_rows = sorted(
        [r for r in rows if r.get("engagement_rate") is not None],
        key=lambda r: r["engagement_rate"],
        reverse=True,
    )
    top_posts = sorted_rows[:5]

    return {
        "data": {
            "by_pillar": by_pillar_out,
            "by_format": by_format_out,
            "top_posts": top_posts,
            "total_posts": total_posts,
            "avg_credibility": avg_credibility,
        }
    }


# ---------------------------------------------------------------------------
# Delete & Intel endpoints
# ---------------------------------------------------------------------------


@router.delete("/drafts/all")
async def delete_all_drafts():
    """Delete all thought_leadership drafts (not archived posts)."""
    db = Database()
    try:
        result = db.client.table("outreach_drafts").select("id").eq(
            "draft_type", "thought_leadership"
        ).execute()
        ids = [r["id"] for r in (result.data or [])]
        if ids:
            for draft_id in ids:
                db.client.table("outreach_drafts").delete().eq("id", draft_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear drafts: {str(e)}")
    return {"data": {"deleted_count": len(ids)}}


@router.delete("/{draft_id}")
async def delete_draft(draft_id: str):
    """Delete a single content draft."""
    db = Database()
    try:
        db.client.table("outreach_drafts").delete().eq("id", draft_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete draft: {str(e)}")
    return {"data": {"deleted": draft_id}}


@router.post("/{draft_id}/run-intel")
async def run_intel_on_draft(draft_id: str):
    """Run the 3-round intel verification on an existing draft that has no intel data."""
    db = Database()

    # Fetch draft
    try:
        res = db.client.table("outreach_drafts").select("*").eq("id", draft_id).limit(1).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not res.data:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft_row = res.data[0]
    post_text = draft_row.get("body", "") or ""
    if not post_text.strip():
        raise HTTPException(status_code=422, detail="Draft has no text to verify")

    # Run the intel verification using a ContentAgent instance
    agent = ContentAgent()

    intel_prompt = (
        "You are a fact-checking editor for a thought leadership publication.\n\n"
        f"LINKEDIN POST TO VERIFY:\n{post_text}\n\n"
        "Perform 3 rounds of verification:\n\n"
        "ROUND 1 — SOURCE VERIFICATION:\n"
        "For each statistical claim, industry reference, or factual statement:\n"
        "- Identify the claim\n"
        "- Find the most likely real-world source\n"
        "- Rate: VERIFIED (source found) / PLAUSIBLE (reasonable but unverified) / UNVERIFIABLE\n\n"
        "ROUND 2 — AUTHENTICITY CHECK:\n"
        "For each claim, assess: Is this number realistic? Could it be verified by a reader?\n"
        "Flag any claim that sounds fabricated, exaggerated, or too precise to be real.\n"
        "Check for common AI hallucination patterns (overly round numbers, fake study citations).\n\n"
        "ROUND 3 — CREDIBILITY ASSESSMENT:\n"
        "Overall credibility score (1-10, where 10 = every claim is verifiable).\n"
        "Would a McKinsey partner publish this without edits? Yes/No and why.\n"
        "List any thought leaders, companies, or organizations referenced or relevant.\n\n"
        "OUTPUT FORMAT:\n"
        "SOURCES:\n"
        "- [claim]: [source] (VERIFIED / PLAUSIBLE / UNVERIFIABLE)\n"
        "FLAGGED CLAIMS:\n"
        "- [any suspicious or unverifiable claims]\n"
        "CREDIBILITY SCORE: [X]/10\n"
        "PUBLISH READY: [Yes/No]\n"
        "REASON: [one-line reason]\n"
        "REFERENCED ENTITIES:\n"
        "- Organizations: ...\n"
        "- Reports/Studies: ...\n"
        "- Regulations/Standards: ...\n"
        "SUGGESTED IMPROVEMENTS:\n"
        "- [actionable edits to increase verifiability]\n"
    )

    try:
        import anthropic
        client = anthropic.Anthropic()
        intel_response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system="You are a rigorous fact-checking editor. Flag anything that cannot be independently verified. No leniency.",
            messages=[{"role": "user", "content": intel_prompt}],
        )
        intel_text = intel_response.content[0].text.strip()

        # Track cost
        agent.track_cost(
            provider="anthropic",
            model="claude-sonnet-4-6",
            endpoint="/messages",
            company_id=None,
            input_tokens=intel_response.usage.input_tokens,
            output_tokens=intel_response.usage.output_tokens,
        )
    except Exception as e:
        logger.error(f"Intel verification failed for draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Intel verification failed: {str(e)}")

    # Parse credibility score
    credibility_score = 0
    publish_ready = False
    for line in intel_text.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("CREDIBILITY SCORE:"):
            try:
                score_part = line_stripped.split(":")[1].strip().split("/")[0].strip()
                credibility_score = int(score_part)
            except (ValueError, IndexError):
                pass
        if line_stripped.startswith("PUBLISH READY:"):
            publish_ready = "yes" in line_stripped.lower()

    # Update persisted notes with intel report
    import json as _json
    notes = draft_row.get("personalization_notes", "") or ""

    # Strip any existing intel/quality sections
    import re
    clean_notes = re.sub(r"\|intel_report::.*?(?=\|quality_report::|$)", "", notes, flags=re.DOTALL)
    clean_notes = re.sub(r"\|quality_report::.*", "", clean_notes, flags=re.DOTALL)

    # Re-add credibility + publish_ready + intel report
    # Remove old credibility/publish_ready
    parts = [p for p in clean_notes.split("|") if p and not p.startswith("credibility:") and not p.startswith("publish_ready:")]
    parts.append(f"credibility:{credibility_score}/10")
    parts.append(f"publish_ready:{publish_ready}")
    updated_notes = "|".join(parts)
    updated_notes += f"|intel_report::{intel_text}"

    # Re-attach quality_report if it existed
    quality_report_text = ""
    qr_match = re.search(r"quality_report::(.+)", notes, flags=re.DOTALL)
    if qr_match:
        updated_notes += f"|quality_report::{qr_match.group(1)}"

    try:
        db.client.table("outreach_drafts").update({
            "personalization_notes": updated_notes,
        }).eq("id", draft_id).execute()
    except Exception:
        pass  # Non-critical — intel is still returned

    intel = {
        "report": intel_text,
        "credibility_score": credibility_score,
        "publish_ready": publish_ready,
        "verification_rounds": 3,
        "error": None,
    }

    return {
        "data": {
            "draft_id": draft_id,
            "credibility_score": credibility_score,
            "publish_ready": publish_ready,
            "intel": intel,
        }
    }


@router.get("/archive/dedup-check")
async def check_dedup(topic: str = Query(..., description="Topic to check for duplicate posts")):
    """Check whether a topic was recently posted (within 60 days)."""
    db = Database()
    th = _topic_hash(topic)

    try:
        result = (
            db.client.table("content_archive")
            .select("id, posted_at, topic")
            .eq("topic_hash", th)
            .order("posted_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if not result.data:
        return {"data": {"duplicate": False, "last_posted": None, "days_since": None}}

    row = result.data[0]
    last_posted = row["posted_at"]
    try:
        posted_dt = datetime.fromisoformat(last_posted.replace("Z", "+00:00"))
        days_since = (datetime.now(timezone.utc) - posted_dt).days
    except Exception:
        days_since = None

    return {
        "data": {
            "duplicate": True,
            "last_posted": last_posted,
            "days_since": days_since,
        }
    }
