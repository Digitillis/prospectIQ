"""Company routes for ProspectIQ API.

CRUD operations for companies, contacts, research, and interactions.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.database import Database

router = APIRouter(prefix="/api/companies", tags=["companies"])


def get_db() -> Database:
    return Database()


@router.get("/")
async def list_companies(
    status: Optional[str] = None,
    tier: Optional[str] = None,
    min_pqs: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List companies with optional filters."""
    db = get_db()
    companies = db.get_companies(
        status=status,
        tier=tier,
        min_pqs=min_pqs,
        limit=limit,
        offset=offset,
    )
    return {"data": companies, "count": len(companies), "limit": limit, "offset": offset}


@router.get("/{company_id}")
async def get_company(company_id: str):
    """Get a single company with contacts, research, and recent interactions."""
    db = get_db()
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contacts = db.get_contacts_for_company(company_id)
    research = db.get_research(company_id)
    interactions = db.get_interactions(company_id=company_id, limit=20)

    return {
        "data": {
            **company,
            "contacts": contacts,
            "research": research,
            "interactions": interactions,
        }
    }


@router.patch("/{company_id}")
async def update_company(company_id: str, updates: dict):
    """Update company fields (status, notes, priority_flag, etc.)."""
    db = get_db()

    existing = db.get_company(company_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Company not found")

    result = db.update_company(company_id, updates)
    return {"data": result}


@router.get("/{company_id}/contacts")
async def get_contacts(company_id: str):
    """Get all contacts for a company."""
    db = get_db()
    contacts = db.get_contacts_for_company(company_id)
    return {"data": contacts}


@router.get("/{company_id}/research")
async def get_research(company_id: str):
    """Get research intelligence for a company."""
    db = get_db()
    research = db.get_research(company_id)
    if not research:
        raise HTTPException(status_code=404, detail="No research found for this company")
    return {"data": research}


@router.get("/{company_id}/interactions")
async def get_interactions(
    company_id: str,
    limit: int = Query(default=50, ge=1, le=500),
):
    """Get interactions for a company."""
    db = get_db()
    interactions = db.get_interactions(company_id=company_id, limit=limit)
    return {"data": interactions}


@router.post("/{company_id}/interactions")
async def create_interaction(company_id: str, body: dict):
    """Create a new interaction (note, call log, etc.) for a company."""
    db = get_db()
    existing = db.get_company(company_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Company not found")

    data = {
        "company_id": company_id,
        "type": body.get("type", "note"),
        "channel": body.get("channel", "other"),
        "subject": body.get("subject"),
        "body": body.get("body"),
        "source": "manual",
    }
    result = db.insert_interaction(data)
    return {"data": result}
