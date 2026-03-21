"""Top-level contacts route for ProspectIQ API.

Provides cross-company contact listing, individual contact detail,
update (including relationship strength), and relationship summary.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def get_db() -> Database:
    return Database()


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
        db.client.table("contacts")
        .select("id, full_name, relationship_strength, is_decision_maker, company_id, companies(name, tier)")
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
    query = db.client.table("contacts").select(
        "*, companies(id, name, tier, status, pqs_total, domain)"
    )
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
        db.client.table("contacts")
        .select("*, companies(id, name, tier, status, pqs_total, domain)")
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
            db.client.table("interactions")
            .select("*")
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
        db.client.table("contacts").select("id").eq("id", contact_id).execute()
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
