"""Contact Event Thread routes for ProspectIQ API.

Provides chronological interaction timelines per contact, manual event
logging with optional AI analysis, next-action tracking, and a
cross-contact pending-actions feed for the Daily Cockpit.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.event_analyzer import analyze_inbound_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["events"])


def get_db() -> Database:
    return Database()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateEventRequest(BaseModel):
    contact_id: str
    company_id: Optional[str] = None
    event_type: str  # outreach_sent, response_received, connection_accepted, note_added,
                     # meeting_scheduled, meeting_held, status_change, system_action
    channel: Optional[str] = None   # linkedin, email, phone, in_person, system
    direction: Optional[str] = "inbound"  # outbound, inbound, internal
    subject: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[list[str]] = None
    analyze: bool = True  # Run AI analysis for inbound events


class UpdateNextActionRequest(BaseModel):
    status: str  # done, skipped


# ---------------------------------------------------------------------------
# GET /api/events/{contact_id}
# ---------------------------------------------------------------------------


@router.get("/{contact_id}")
async def get_contact_events(
    contact_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """Return the full chronological event thread for a contact."""
    db = get_db()

    try:
        result = (
            db.client.table("contact_events")
            .select(
                "*, companies(name)"
            )
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        events = result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch contact events for {contact_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch events")

    return {"data": events}


# ---------------------------------------------------------------------------
# POST /api/events
# ---------------------------------------------------------------------------


@router.post("")
async def create_event(req: CreateEventRequest):
    """Create a new contact event with optional AI analysis."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Auto-resolve company_id from contact if not provided
    company_id = req.company_id
    if not company_id:
        try:
            contact_row = (
                db.client.table("contacts")
                .select("company_id")
                .eq("id", req.contact_id)
                .execute()
                .data
            )
            if contact_row:
                company_id = contact_row[0].get("company_id")
        except Exception as e:
            logger.warning(f"Failed to resolve company_id from contact: {e}")

    # ------------------------------------------------------------------
    # Build base event record
    # ------------------------------------------------------------------
    event_data: dict = {
        "contact_id": req.contact_id,
        "company_id": company_id,
        "event_type": req.event_type,
        "channel": req.channel,
        "direction": req.direction or "inbound",
        "subject": req.subject,
        "body": req.body,
        "tags": req.tags or [],
        "created_by": "user",
        "created_at": now,
    }

    # ------------------------------------------------------------------
    # AI analysis for inbound events
    # ------------------------------------------------------------------
    pqs_delta = 0
    if req.analyze and req.direction == "inbound" and company_id:
        try:
            analysis = await analyze_inbound_event(
                db=db,
                contact_id=req.contact_id,
                company_id=company_id,
                new_event_body=req.body or "",
                new_event_channel=req.channel or "unknown",
                new_event_type=req.event_type,
            )
            event_data["sentiment"] = analysis.get("sentiment")
            event_data["sentiment_reason"] = analysis.get("sentiment_reason")
            event_data["signals"] = analysis.get("signals") or []
            event_data["next_action"] = analysis.get("next_action")
            event_data["next_action_date"] = analysis.get("next_action_date")
            event_data["next_action_status"] = "pending"
            event_data["suggested_message"] = analysis.get("suggested_message")
            event_data["action_reasoning"] = analysis.get("action_reasoning")
            pqs_delta = analysis.get("pqs_delta") or 0
            event_data["pqs_delta"] = pqs_delta
        except Exception as e:
            logger.error(f"Event analysis failed, storing without AI fields: {e}")

    # ------------------------------------------------------------------
    # Insert the event
    # ------------------------------------------------------------------
    try:
        insert_result = (
            db.client.table("contact_events").insert(event_data).execute()
        )
        created_event = insert_result.data[0] if insert_result.data else event_data
    except Exception as e:
        logger.error(f"Failed to insert contact_event: {e}")
        raise HTTPException(status_code=500, detail="Failed to create event")

    # ------------------------------------------------------------------
    # Update PQS engagement score if AI analysis ran
    # ------------------------------------------------------------------
    if pqs_delta != 0 and company_id:
        try:
            company_row = (
                db.client.table("companies")
                .select("pqs_engagement, pqs_total")
                .eq("id", company_id)
                .execute()
                .data
            )
            if company_row:
                current_engagement = company_row[0].get("pqs_engagement") or 0
                current_total = company_row[0].get("pqs_total") or 0
                new_engagement = max(0, min(25, current_engagement + pqs_delta))
                new_total = max(0, current_total + pqs_delta)
                db.client.table("companies").update({
                    "pqs_engagement": new_engagement,
                    "pqs_total": new_total,
                    "updated_at": now,
                }).eq("id", company_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update PQS from event: {e}")

    return {"data": created_event}


# ---------------------------------------------------------------------------
# PATCH /api/events/{event_id}/next-action
# ---------------------------------------------------------------------------


@router.patch("/{event_id}/next-action")
async def update_next_action(event_id: str, req: UpdateNextActionRequest):
    """Mark a next-action as done or skipped."""
    if req.status not in ("done", "skipped"):
        raise HTTPException(status_code=422, detail="status must be 'done' or 'skipped'")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    try:
        result = (
            db.client.table("contact_events")
            .update({"next_action_status": req.status})
            .eq("id", event_id)
            .execute()
        )
        updated = result.data[0] if result.data else {}
    except Exception as e:
        logger.error(f"Failed to update next_action_status for event {event_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update next action")

    return {
        "data": updated,
        "message": f"Next action marked as {req.status}",
    }


# ---------------------------------------------------------------------------
# GET /api/events/pending-actions
# ---------------------------------------------------------------------------


@router.get("/pending-actions")
async def get_pending_actions():
    """Return all pending next actions due today or earlier, across all contacts.

    Ordered by next_action_date ascending. Joins contact and company names.
    """
    db = get_db()
    today = date.today().isoformat()

    try:
        result = (
            db.client.table("contact_events")
            .select(
                "id, contact_id, company_id, event_type, channel, next_action, "
                "next_action_date, next_action_status, suggested_message, action_reasoning, "
                "created_at, "
                "contacts(full_name, title, linkedin_url), "
                "companies(name, tier, pqs_total)"
            )
            .eq("next_action_status", "pending")
            .lte("next_action_date", today)
            .order("next_action_date")
            .limit(50)
            .execute()
        )
        actions = result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch pending actions: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch pending actions")

    return {"data": actions}
