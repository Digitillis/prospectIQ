"""Company routes for ProspectIQ API.

CRUD operations for companies, contacts, research, and interactions.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/companies", tags=["companies"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


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


@router.get("/linkedin-messages")
async def get_linkedin_messages(
    status: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Return contacts that have LinkedIn drafts, joined with company and draft data.

    Each item in the response contains:
      - contact fields (id, full_name, title, linkedin_url, linkedin_status, ...)
      - company fields (id, name, tier, pqs_total, sub_sector, ...)
      - drafts: list of the 3 LinkedIn drafts keyed by sequence_name
    """
    db = get_db()

    from collections import defaultdict

    # ── Two sources: contacts with drafts + contacts with linkedin activity ──

    # Source 1: LinkedIn drafts (channel=linkedin, approved)
    all_drafts = (
        db._filter_ws(db.client.table("outreach_drafts")
        .select(
            "id, company_id, contact_id, sequence_name, sequence_step, body, "
            "personalization_notes, approval_status, created_at"
        ))
        .eq("channel", "linkedin")
        .eq("approval_status", "approved")
        .order("created_at", desc=True)
        .limit(limit * 5)
    ).execute().data

    draft_map: dict[tuple, list[dict]] = defaultdict(list)
    for draft in all_drafts:
        key = (draft["company_id"], draft["contact_id"])
        draft_map[key].append(draft)

    # Source 2: Contacts with linkedin_status != 'not_sent' (manually reached out)
    active_contacts_query = (
        db._filter_ws(db.client.table("contacts")
        .select(
            "id, company_id, full_name, first_name, last_name, title, persona_type, "
            "is_decision_maker, linkedin_url, linkedin_status, linkedin_notes, status, created_at, "
            "linkedin_connection_sent_at, linkedin_accepted_at, linkedin_dm_sent_at, "
            "linkedin_responded_at, linkedin_meeting_booked_at"
        ))
        .neq("linkedin_status", "not_sent")
        .order("created_at", desc=True)
        .limit(limit * 3)
    )
    active_contacts = active_contacts_query.execute().data

    # Merge: collect all unique (company_id, contact_id) pairs
    seen_contacts: set[str] = set()
    pairs: list[tuple[str, str]] = []
    contact_prefetch: dict[str, dict] = {}

    # From drafts
    for (company_id, contact_id), _ in draft_map.items():
        if contact_id not in seen_contacts:
            seen_contacts.add(contact_id)
            pairs.append((company_id, contact_id))

    # From active linkedin contacts (no draft required)
    for c in active_contacts:
        cid = c["id"]
        comp_id = c.get("company_id")
        if cid not in seen_contacts and comp_id:
            seen_contacts.add(cid)
            pairs.append((comp_id, cid))
            contact_prefetch[cid] = c

    if not pairs:
        return {"data": [], "count": 0}

    # Bulk fetch companies
    company_ids = list({cid for cid, _ in pairs})
    companies_result = (
        db._filter_ws(db.client.table("companies")
        .select(
            "id, name, tier, sub_sector, industry, pqs_total, city, state, domain, "
            "employee_count, revenue_printed, headcount_growth_6m, is_public, "
            "parent_company_name, pain_signals, personalization_hooks, research_summary"
        ))
        .in_("id", company_ids)
        .execute()
    )
    company_by_id = {c["id"]: c for c in companies_result.data}

    # Bulk fetch research (latest per company)
    research_by_company: dict[str, dict] = {}
    try:
        for cid in company_ids:
            research_rows = (
                db._filter_ws(db.client.table("research")
                .select("*"))
                .eq("company_id", cid)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            ) or []
            if research_rows:
                research_by_company[cid] = research_rows[0]
    except Exception:
        pass

    # Bulk fetch contacts not already prefetched
    missing_contact_ids = [cid for _, cid in pairs if cid not in contact_prefetch]
    contact_by_id = dict(contact_prefetch)
    if missing_contact_ids:
        contacts_result = (
            db._filter_ws(db.client.table("contacts")
            .select(
                "id, company_id, full_name, first_name, last_name, title, persona_type, "
                "is_decision_maker, linkedin_url, linkedin_status, linkedin_notes, status, created_at, "
                "linkedin_connection_sent_at, linkedin_accepted_at, linkedin_dm_sent_at, "
                "linkedin_responded_at, linkedin_meeting_booked_at"
            ))
            .in_("id", missing_contact_ids)
            .execute()
        )
        for c in contacts_result.data:
            contact_by_id[c["id"]] = c

    # Apply filters and build results
    results = []
    for company_id, contact_id in pairs:
        company = company_by_id.get(company_id, {})
        contact = contact_by_id.get(contact_id, {})

        # Tier filter
        if tier and company.get("tier", "") != tier:
            continue

        # Status filter (linkedin_status on the contact)
        if status and status != "all":
            contact_linkedin_status = contact.get("linkedin_status", "not_sent")
            if contact_linkedin_status != status:
                continue

        # Build drafts dict keyed by sequence_name
        drafts_for_contact = {
            d["sequence_name"]: {
                "id": d["id"],
                "body": d["body"],
                "personalization_notes": d.get("personalization_notes", ""),
                "created_at": d["created_at"],
            }
            for d in draft_map.get((company_id, contact_id), [])
        }

        # Derive personalization_notes from first available draft
        first_draft = next(iter(draft_map.get((company_id, contact_id), [])), {})
        personalization_notes = first_draft.get("personalization_notes", "") or ""

        # Build intel block
        intel: dict = {
            "personalization_notes": personalization_notes,
            "company": {
                "industry": company.get("industry"),
                "employee_count": company.get("employee_count"),
                "revenue_printed": company.get("revenue_printed"),
                "headcount_growth_6m": company.get("headcount_growth_6m"),
                "is_public": company.get("is_public"),
                "parent_company_name": company.get("parent_company_name"),
                "pain_signals": company.get("pain_signals", []),
                "personalization_hooks": company.get("personalization_hooks", []),
                "research_summary": company.get("research_summary"),
            },
            "research": None,
            "contact": {
                "title": contact.get("title"),
                "seniority": contact.get("seniority"),
                "city": contact.get("city"),
                "state": contact.get("state"),
            },
        }
        research_row = research_by_company.get(company_id)
        if research_row:
            ri = research_row.get("research_intelligence") or {}
            intel["research"] = {
                "products_services": ri.get("products_services", []),
                "recent_news": ri.get("recent_news", []),
                "pain_points": ri.get("pain_points", []) or research_row.get("pain_points", []),
                "known_systems": ri.get("known_systems", []) or research_row.get("known_systems", []),
                "confidence": research_row.get("confidence_level"),
            }

        results.append({
            "contact": contact,
            "company": company,
            "drafts": drafts_for_contact,
            "intel": intel,
        })

        if len(results) >= limit:
            break

    return {"data": results, "count": len(results)}


@router.get("/linkedin-contacts")
async def get_linkedin_contacts(
    status: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return all contacts with a LinkedIn URL, sorted by company PQS descending.

    No draft generation required — shows every contact ready for manual outreach.
    Used by the LinkedIn page 'All Contacts' tab.
    """
    db = get_db()

    # Fetch contacts with linkedin_url set
    q = (
        db._filter_ws(db.client.table("contacts")
        .select(
            "id, company_id, full_name, first_name, last_name, title, persona_type, "
            "is_decision_maker, linkedin_url, linkedin_status, linkedin_notes, status, "
            "created_at, linkedin_connection_sent_at, linkedin_accepted_at, "
            "linkedin_dm_sent_at, linkedin_responded_at, linkedin_meeting_booked_at"
        ))
        .not_.is_("linkedin_url", "null")
        .neq("linkedin_url", "")
    )

    if status and status != "all":
        q = q.eq("linkedin_status", status)

    contacts = q.order("created_at", desc=False).range(offset, offset + limit - 1).execute().data or []

    if not contacts:
        return {"data": [], "count": 0, "total": 0}

    # Bulk fetch companies
    company_ids = list({c["company_id"] for c in contacts if c.get("company_id")})
    companies_result = (
        db._filter_ws(db.client.table("companies")
        .select("id, name, tier, sub_sector, pqs_total, domain"))
        .in_("id", company_ids)
        .execute()
    )
    company_by_id = {c["id"]: c for c in companies_result.data}

    # Apply tier filter + build results sorted by PQS desc
    results = []
    for contact in contacts:
        company = company_by_id.get(contact.get("company_id", ""), {})
        if tier and tier != "all" and not (company.get("tier", "") or "").startswith(tier):
            continue
        results.append({
            "contact": contact,
            "company": company,
        })

    results.sort(key=lambda x: x["company"].get("pqs_total") or 0, reverse=True)

    # Total count query (without pagination)
    total_q = (
        db._filter_ws(db.client.table("contacts").select("id", count="exact"))
        .not_.is_("linkedin_url", "null")
        .neq("linkedin_url", "")
    )
    if status and status != "all":
        total_q = total_q.eq("linkedin_status", status)
    total_result = total_q.execute()
    total = total_result.count or len(results)

    return {"data": results, "count": len(results), "total": total}


@router.post("/{contact_id}/linkedin-status")
async def update_linkedin_status(contact_id: str, body: dict):
    """Update the LinkedIn outreach status for a contact.

    Stores the status on the contact record and logs an interaction.

    Valid statuses: not_sent, connection_sent, accepted, dm_sent, responded, meeting_booked
    """
    valid_statuses = {
        "not_sent", "connection_sent", "accepted",
        "dm_sent", "responded", "meeting_booked",
    }
    new_status = body.get("status", "")
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(valid_statuses))}",
        )

    db = get_db()

    # Verify contact exists
    contact_result = (
        db.client.table("contacts")
        .select("id, company_id, full_name")
        .eq("id", contact_id)
        .execute()
    )
    if not contact_result.data:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact = contact_result.data[0]
    company_id = contact.get("company_id")

    # Extract notes before updating
    notes = body.get("notes", "")

    # Update the contact linkedin_status, notes, and timestamp for this transition
    from datetime import datetime, timezone
    update_data: dict = {"linkedin_status": new_status}
    if notes:
        update_data["linkedin_notes"] = notes

    # Record when this status transition happened
    _STATUS_TO_TIMESTAMP_COL = {
        "connection_sent": "linkedin_connection_sent_at",
        "accepted": "linkedin_accepted_at",
        "dm_sent": "linkedin_dm_sent_at",
        "responded": "linkedin_responded_at",
        "meeting_booked": "linkedin_meeting_booked_at",
    }
    ts_col = _STATUS_TO_TIMESTAMP_COL.get(new_status)
    if ts_col:
        update_data[ts_col] = datetime.now(timezone.utc).isoformat()

    db.client.table("contacts").update(update_data).eq("id", contact_id).execute()

    # Log an interaction so activity feed reflects the LinkedIn touch
    interaction_body = f"LinkedIn status updated to: {new_status}"
    if notes:
        interaction_body += f"\nNotes: {notes}"

    if company_id:
        db.insert_interaction({
            "company_id": company_id,
            "contact_id": contact_id,
            "type": "linkedin",
            "channel": "linkedin",
            "subject": f"LinkedIn: {new_status.replace('_', ' ').title()}",
            "body": interaction_body,
            "source": "manual",
        })

    return {"data": {"contact_id": contact_id, "linkedin_status": new_status, "linkedin_notes": notes}}


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

    Delegates to the EnrichmentAgent which handles auto-discovery of contacts
    when none exist, proper persona-based contact selection, domain verification,
    and richer data extraction (phone, name, LinkedIn URL).
    """
    from backend.app.agents.enrichment import EnrichmentAgent

    db = get_db()
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        agent = EnrichmentAgent()
        result = agent.execute(company_ids=[company_id], limit=1)
    except Exception as e:
        logger.error(f"Enrichment agent failed for {company_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "data": {
            "company_id": company_id,
            "contacts_enriched": result.processed,
            "contacts_skipped": result.skipped,
            "errors": result.errors,
            "details": result.details,
            "error_message": result.details[0].get("message", "") if result.errors > 0 and result.details else "",
        }
    }


@router.post("/import")
async def import_companies_csv(file: UploadFile):
    """Import companies from a CSV file."""
    import csv
    import io

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    db = get_db()
    imported = 0
    skipped = 0
    errors = []

    for row in reader:
        name = row.get("name", "").strip() or row.get("Company Name", "").strip()
        if not name:
            skipped += 1
            continue

        # Check for duplicate by domain
        domain = row.get("domain", "").strip() or row.get("Domain", "").strip()
        if domain:
            existing = db.get_company_by_domain(domain)
            if existing:
                skipped += 1
                continue

        try:
            employee_raw = row.get("employee_count", "").strip() or row.get("Employee Count", "").strip()
            db.client.table("companies").insert(db._inject_ws({
                "name": name,
                "domain": domain or None,
                "website": row.get("website", "").strip() or row.get("Website", "").strip() or None,
                "industry": row.get("industry", "").strip() or row.get("Industry", "").strip() or None,
                "state": row.get("state", "").strip() or row.get("State", "").strip() or None,
                "tier": row.get("tier", "").strip() or row.get("Tier", "").strip() or None,
                "employee_count": int(employee_raw) if employee_raw.isdigit() else None,
                "revenue_range": row.get("revenue_range", "").strip() or row.get("Revenue Range", "").strip() or None,
                "status": "discovered",
                "pqs_total": 0,
                "pqs_firmographic": 0,
                "pqs_technographic": 0,
                "pqs_timing": 0,
                "pqs_engagement": 0,
            })).execute()
            imported += 1
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")

    return {"data": {"imported": imported, "skipped": skipped, "errors": errors}}


class OutcomeRequest(BaseModel):
    outcome: str  # "won" | "lost" | "no_response"
    notes: Optional[str] = None


@router.patch("/{company_id}/tags")
async def update_tags(company_id: str, body: dict):
    """Update custom tags on a company. Body: { "tags": ["trade-show", "referral"] }

    NOTE: Requires a `custom_tags` JSONB column on the companies table in Supabase.
    Run: ALTER TABLE companies ADD COLUMN IF NOT EXISTS custom_tags JSONB DEFAULT '[]'::jsonb;
    """
    db = Database(workspace_id=get_workspace_id())
    tags = body.get("tags", [])
    db._filter_ws(db.client.table("companies").update({"custom_tags": tags})).eq("id", company_id).execute()
    return {"data": {"company_id": company_id, "tags": tags}}


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
