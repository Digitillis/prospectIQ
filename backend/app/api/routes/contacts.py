"""Top-level contacts route for ProspectIQ API.

Provides cross-company contact listing, individual contact detail,
update (including relationship strength), relationship summary,
and per-contact event thread with optional AI analysis.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ContactUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    seniority: Optional[str] = None
    department: Optional[str] = None
    persona_type: Optional[str] = None
    is_decision_maker: Optional[bool] = None
    linkedin_url: Optional[str] = None
    relationship_strength: Optional[int] = None  # 0-100
    last_interaction_note: Optional[str] = None


class ContactEventCreate(BaseModel):
    event_type: str  # response_received | connection_accepted | note_added | meeting_scheduled | meeting_held | phone_call | email_reply
    channel: Optional[str] = None  # linkedin | email | phone | in_person
    body: Optional[str] = None
    tags: Optional[list[str]] = None
    analyze: bool = False  # if True, run Claude AI analysis on the event


class NextActionUpdate(BaseModel):
    status: str  # done | skipped


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/relationship-summary")
async def relationship_summary():
    """Get relationship strength distribution across all contacts.

    NOTE: this route must be declared BEFORE /{contact_id} so FastAPI doesn't
    treat the literal path segment 'relationship-summary' as an ID.
    """
    db = get_db()
    contacts_result = (
        db._filter_ws(db.client.table("contacts")
        .select("id, full_name, relationship_strength, is_decision_maker, company_id, companies(name, tier)"))
        .not_.is_("relationship_strength", "null")
        .execute()
    )
    all_contacts = contacts_result.data or []

    strong = [c for c in all_contacts if (c.get("relationship_strength") or 0) >= 70]
    warm   = [c for c in all_contacts if 30 <= (c.get("relationship_strength") or 0) < 70]
    cold   = [c for c in all_contacts if (c.get("relationship_strength") or 0) < 30]

    return {
        "data": {
            "strong": {"count": len(strong), "contacts": strong[:10]},
            "warm":   {"count": len(warm),   "contacts": warm[:10]},
            "cold":   {"count": len(cold),   "contacts": cold[:10]},
            "total_tracked": len(all_contacts),
        }
    }


@router.get("/")
async def list_contacts(
    persona_type: Optional[str] = None,
    seniority: Optional[str] = None,
    department: Optional[str] = None,
    is_decision_maker: Optional[bool] = None,
    search: Optional[str] = None,
    min_relationship: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all contacts across companies with optional filters."""
    db = get_db()
    query = db._filter_ws(db.client.table("contacts").select(
        "*, companies(id, name, tier, status, pqs_total, domain)"
    ))
    if persona_type:
        query = query.eq("persona_type", persona_type)
    if seniority:
        query = query.eq("seniority", seniority)
    if department:
        query = query.eq("department", department)
    if is_decision_maker is not None:
        query = query.eq("is_decision_maker", is_decision_maker)
    if search:
        query = query.ilike("full_name", f"%{search}%")
    if min_relationship is not None:
        query = query.gte("relationship_strength", min_relationship)

    result = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"data": result.data, "count": len(result.data)}


@router.get("/{contact_id}")
async def get_contact(contact_id: str):
    """Get a single contact with company details and recent company interactions."""
    db = get_db()
    contact_result = (
        db._filter_ws(db.client.table("contacts")
        .select("*, companies(id, name, tier, status, pqs_total, domain)"))
        .eq("id", contact_id)
        .execute()
    )
    if not contact_result.data:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact = contact_result.data[0]

    # Pull recent interactions for the contact's company so the UI can show a timeline
    company_id = contact.get("company_id")
    interactions: list = []
    if company_id:
        interactions_result = (
            db._filter_ws(db.client.table("interactions")
            .select("*"))
            .eq("company_id", company_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        interactions = interactions_result.data or []

    return {
        "data": {
            **contact,
            "interactions": interactions,
        }
    }


@router.patch("/{contact_id}")
async def update_contact(contact_id: str, body: ContactUpdate):
    """Update a contact's details including relationship strength (0-100)."""
    db = get_db()

    # Validate contact exists first
    existing_result = (
        db._filter_ws(db.client.table("contacts").select("id")).eq("id", contact_id).execute()
    )
    if not existing_result.data:
        raise HTTPException(status_code=404, detail="Contact not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return {"data": {"message": "No updates provided"}}

    # Clamp relationship_strength to 0-100
    if "relationship_strength" in updates:
        updates["relationship_strength"] = max(0, min(100, int(updates["relationship_strength"])))

    result = db.update_contact(contact_id, updates)
    return {"data": result}


# ---------------------------------------------------------------------------
# Contact Events — event thread (read / write / next-action)
# NOTE: event_analyzer.py and events.py are handled by another agent.
# These endpoints provide the minimal surface needed for the contact detail UI.
# ---------------------------------------------------------------------------

# IMPORTANT: pending-actions must be declared before /{contact_id}/events so
# the static path segment isn't captured by the dynamic route.

@router.get("/events/pending-actions")
async def get_pending_actions(contact_id: Optional[str] = None):
    """Return events that have a pending next_action for a contact (or all contacts)."""
    db = get_db()
    try:
        query = (
            db._filter_ws(db.client.table("contact_events")
            .select("*"))
            .eq("next_action_status", "pending")
            .not_.is_("next_action", "null")
        )
        if contact_id:
            query = query.eq("contact_id", contact_id)
        result = query.order("created_at", desc=True).limit(50).execute()
        return {"data": result.data or [], "count": len(result.data or [])}
    except Exception as exc:
        logger.warning("contact_events table may not exist yet: %s", exc)
        return {"data": [], "count": 0}


@router.patch("/events/{event_id}/next-action")
async def update_next_action(event_id: str, body: NextActionUpdate):
    """Mark a next_action as done or skipped."""
    if body.status not in ("done", "skipped"):
        raise HTTPException(status_code=422, detail="status must be 'done' or 'skipped'")
    db = get_db()
    try:
        result = (
            db._filter_ws(db.client.table("contact_events")
            .update({"next_action_status": body.status, "updated_at": datetime.now(timezone.utc).isoformat()}))
            .eq("id", event_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"data": result.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update next action: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{contact_id}/events")
async def list_contact_events(contact_id: str):
    """Return all events for a contact, newest first."""
    db = get_db()
    # Verify contact exists
    contact_result = (
        db._filter_ws(db.client.table("contacts").select("id")).eq("id", contact_id).execute()
    )
    if not contact_result.data:
        raise HTTPException(status_code=404, detail="Contact not found")

    try:
        result = (
            db._filter_ws(db.client.table("contact_events")
            .select("*"))
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        return {"data": result.data or [], "count": len(result.data or [])}
    except Exception as exc:
        # Table may not exist yet — return empty rather than 500
        logger.warning("contact_events table may not exist yet: %s", exc)
        return {"data": [], "count": 0}


@router.post("/{contact_id}/events")
async def create_contact_event(contact_id: str, body: ContactEventCreate):
    """Create a new event on the contact's thread.

    When analyze=True the endpoint attempts to call event_analyzer if it is
    available; if not, the event is saved without AI enrichment so the UI
    never hard-fails.
    """
    db = get_db()

    # Validate contact + get company_id
    contact_result = (
        db._filter_ws(db.client.table("contacts")
        .select("id, company_id, full_name, title"))
        .eq("id", contact_id)
        .execute()
    )
    if not contact_result.data:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact = contact_result.data[0]
    now = datetime.now(timezone.utc).isoformat()

    # Determine direction from event type
    inbound_types = {"response_received", "email_reply", "connection_accepted"}
    outbound_types = {"outreach_sent", "connection_sent", "meeting_scheduled"}
    direction: str
    if body.event_type in inbound_types:
        direction = "inbound"
    elif body.event_type in outbound_types:
        direction = "outbound"
    else:
        direction = "internal"

    event_row: dict = {
        "id": str(uuid.uuid4()),
        "contact_id": contact_id,
        "company_id": contact.get("company_id"),
        "event_type": body.event_type,
        "direction": direction,
        "channel": body.channel,
        "body": body.body,
        "tags": body.tags or [],
        "ai_analyzed": False,
        "next_action_status": "pending",
        "created_at": now,
        "updated_at": now,
    }

    # Try AI analysis when requested
    if body.analyze and body.body:
        try:
            from backend.app.agents.event_analyzer import EventAnalyzer  # type: ignore
            analyzer = EventAnalyzer()
            analysis = analyzer.analyze(
                event_type=body.event_type,
                body=body.body,
                contact=contact,
            )
            event_row.update({
                "sentiment": analysis.get("sentiment"),
                "sentiment_reason": analysis.get("sentiment_reason"),
                "signals": analysis.get("signals", []),
                "next_action": analysis.get("next_action"),
                "next_action_date": analysis.get("next_action_date"),
                "suggested_message": analysis.get("suggested_message"),
                "action_reasoning": analysis.get("action_reasoning"),
                "ai_analyzed": True,
            })
        except ImportError:
            logger.info("event_analyzer not available — saving event without AI enrichment")
        except Exception as exc:
            logger.warning("AI analysis failed — saving event without enrichment: %s", exc)

    try:
        result = db.client.table("contact_events").insert(db._inject_ws(event_row)).execute()
        saved = result.data[0] if result.data else event_row
    except Exception as exc:
        logger.error("Failed to insert contact event: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to save event: {exc}")

    return {"data": saved}
