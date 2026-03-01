"""Company routes for ProspectIQ API.

CRUD operations for companies, contacts, research, and interactions.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

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


@router.post("/{company_id}/enrich")
async def enrich_company(company_id: str):
    """Enrich contact emails via Apollo.io (consumes credits — use selectively).

    Iterates contacts that have no email but have an apollo_id or linkedin_url,
    calls Apollo People enrichment, and persists any discovered email addresses.
    """
    from backend.app.integrations.apollo import ApolloClient

    db = get_db()
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contacts = db.get_contacts_for_company(company_id)
    enriched = 0
    skipped = 0
    errors = 0

    try:
        with ApolloClient() as apollo:
            for contact in contacts:
                if contact.get("email"):
                    skipped += 1
                    continue

                apollo_id = contact.get("apollo_id")
                linkedin_url = contact.get("linkedin_url")

                if not apollo_id and not linkedin_url:
                    skipped += 1
                    continue

                try:
                    result = apollo.enrich_person(
                        person_id=apollo_id if apollo_id else None,
                        linkedin_url=linkedin_url if not apollo_id else None,
                        reveal_personal_emails=True,
                    )
                    person = result.get("person", {}) or {}
                    email = person.get("email")

                    if email:
                        db.update_contact(contact["id"], {
                            "email": email,
                            "status": "enriched",
                        })
                        enriched += 1
                    else:
                        skipped += 1

                except Exception as e:
                    logger.error(f"Apollo enrichment failed for contact {contact['id']}: {e}")
                    errors += 1
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "data": {
            "company_id": company_id,
            "contacts_enriched": enriched,
            "contacts_skipped": skipped,
            "errors": errors,
        }
    }


class OutcomeRequest(BaseModel):
    outcome: str  # "won" | "lost" | "no_response"
    notes: Optional[str] = None


@router.post("/{company_id}/outcome")
async def record_outcome(company_id: str, body: OutcomeRequest):
    """Record the final outcome for a prospect.

    Maps outcome to a company status and inserts a learning_outcome record
    so the Learning Agent can include this prospect in analysis.

    outcome values:
      - "won"         → status: converted, outcome: meeting_booked
      - "lost"        → status: not_interested, outcome: replied_negative
      - "no_response" → status: paused, outcome: no_response
    """
    if body.outcome not in ("won", "lost", "no_response"):
        raise HTTPException(
            status_code=422,
            detail="outcome must be 'won', 'lost', or 'no_response'",
        )

    db = get_db()
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    status_map = {"won": "converted", "lost": "not_interested", "no_response": "paused"}
    outcome_map = {"won": "meeting_booked", "lost": "replied_negative", "no_response": "no_response"}

    new_status = status_map[body.outcome]
    db.update_company(company_id, {"status": new_status})

    db.insert_interaction({
        "company_id": company_id,
        "type": "status_change",
        "channel": "other",
        "subject": f"Outcome recorded: {body.outcome}",
        "body": body.notes or f"Outcome marked as '{body.outcome}' via dashboard",
        "source": "manual",
    })

    contacts = db.get_contacts_for_company(company_id)
    primary = next((c for c in contacts if c.get("is_decision_maker")), contacts[0] if contacts else None)

    db.insert_learning_outcome({
        "company_id": company_id,
        "contact_id": primary["id"] if primary else None,
        "outreach_approach": "initial_outreach",
        "channel": "email",
        "outcome": outcome_map[body.outcome],
        "company_tier": company.get("tier"),
        "sub_sector": company.get("sub_sector") or company.get("industry", ""),
        "persona_type": (primary or {}).get("persona_type", ""),
        "pqs_at_time": company.get("pqs_total", 0),
    })

    return {
        "data": {
            "company_id": company_id,
            "outcome": body.outcome,
            "new_status": new_status,
        }
    }
