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


@router.post("/")
async def create_company(body: dict):
    """Manually create a new company with an optional contact."""
    if not body.get("name", "").strip():
        raise HTTPException(status_code=422, detail="Company name is required")

    db = get_db()

    # Deduplicate by domain
    raw_domain = body.get("domain", "") or ""
    domain = raw_domain.strip().lower() or None
    if domain:
        existing = db.get_company_by_domain(domain)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"A company with domain '{domain}' already exists",
            )

    company_data: dict = {
        "name": body["name"].strip(),
        "status": "discovered",
        "pqs_total": 0,
        "pqs_firmographic": 0,
        "pqs_technographic": 0,
        "pqs_timing": 0,
        "pqs_engagement": 0,
    }
    for field in ("domain", "website", "industry", "sub_sector", "tier", "state",
                  "employee_count", "revenue_range", "phone", "linkedin_url"):
        val = body.get(field)
        if val not in (None, ""):
            company_data[field] = val
    if domain:
        company_data["domain"] = domain

    company = db.insert_company(company_data)

    contact = None
    contact_body = body.get("contact") or {}
    if contact_body.get("full_name") or contact_body.get("email"):
        contact_row: dict = {
            "company_id": company["id"],
            "status": "identified",
            "is_decision_maker": bool(contact_body.get("is_decision_maker", False)),
        }
        for cf in ("full_name", "first_name", "last_name", "email", "title", "phone"):
            v = contact_body.get(cf)
            if v not in (None, ""):
                contact_row[cf] = v
        contact = db.insert_contact(contact_row)

    return {"data": {**company, "contact": contact}}


@router.get("/")
async def list_companies(
    status: Optional[str] = None,
    tier: Optional[str] = None,
    min_pqs: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List companies with optional filters."""
    db = get_db()
    companies = db.get_companies(
        status=status,
        tier=tier,
        min_pqs=min_pqs,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = db.count_companies(status=status, tier=tier, min_pqs=min_pqs, search=search)
    return {"data": companies, "count": total, "limit": limit, "offset": offset}


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


@router.post("/{company_id}/contacts")
async def create_contact(company_id: str, body: dict):
    """Manually create a new contact for a company."""
    db = get_db()
    existing = db.get_company(company_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Company not found")

    contact_data: dict = {
        "company_id": company_id,
        "status": "identified",
        "is_decision_maker": bool(body.get("is_decision_maker", False)),
    }
    for field in ("full_name", "first_name", "last_name", "email", "title",
                  "phone", "linkedin_url", "seniority", "department", "persona_type"):
        val = body.get(field)
        if val not in (None, ""):
            contact_data[field] = val

    # Derive full_name from first/last if not explicitly provided
    if not contact_data.get("full_name"):
        first = contact_data.get("first_name", "")
        last = contact_data.get("last_name", "")
        combined = f"{first} {last}".strip()
        if combined:
            contact_data["full_name"] = combined

    contact = db.insert_contact(contact_data)
    return {"data": contact}


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
