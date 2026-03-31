"""Supabase database client for ProspectIQ.

Provides a thin wrapper around the Supabase Python client
with convenience methods for common operations.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from supabase import create_client, Client

from backend.app.core.config import get_settings


@lru_cache()
def get_supabase_client() -> Client:
    """Get a cached Supabase client using the service role key (full access)."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env"
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)


class Database:
    """Convenience wrapper around Supabase client."""

    def __init__(self):
        self.client = get_supabase_client()

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------

    def get_companies(
        self,
        status: str | None = None,
        tier: str | None = None,
        tiers: list[str] | None = None,
        min_pqs: int | None = None,
        batch_id: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query companies with optional filters."""
        query = self.client.table("companies").select("*")
        if status:
            query = query.eq("status", status)
        if tiers:
            query = query.in_("tier", tiers)
        elif tier:
            query = query.eq("tier", tier)
        if min_pqs is not None:
            query = query.gte("pqs_total", min_pqs)
        if batch_id:
            query = query.eq("batch_id", batch_id)
        if search:
            query = query.ilike("name", f"%{search}%")
        query = query.order("pqs_total", desc=True).range(offset, offset + limit - 1)
        return query.execute().data

    def get_company(self, company_id: str) -> dict | None:
        """Get a single company by ID."""
        result = self.client.table("companies").select("*").eq("id", company_id).execute()
        return result.data[0] if result.data else None

    def get_company_by_apollo_id(self, apollo_id: str) -> dict | None:
        """Get a company by Apollo ID (for deduplication)."""
        result = (
            self.client.table("companies")
            .select("id, apollo_id")
            .eq("apollo_id", apollo_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_company_by_domain(self, domain: str) -> dict | None:
        """Get a company by domain (fallback dedup)."""
        if not domain:
            return None
        result = (
            self.client.table("companies")
            .select("id, domain")
            .eq("domain", domain)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_company_by_name(self, name: str) -> dict | None:
        """Get a company by name (case-insensitive, for subsidiary dedup)."""
        result = self.client.table("companies").select("id, name").ilike("name", name).limit(1).execute()
        return result.data[0] if result.data else None

    def insert_company(self, data: dict) -> dict:
        """Insert a new company record."""
        result = self.client.table("companies").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_company(self, company_id: str, data: dict) -> dict:
        """Update a company record."""
        result = (
            self.client.table("companies")
            .update(data)
            .eq("id", company_id)
            .execute()
        )
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def get_contacts_for_company(self, company_id: str) -> list[dict]:
        """Get all contacts for a company."""
        result = (
            self.client.table("contacts")
            .select("*")
            .eq("company_id", company_id)
            .order("is_decision_maker", desc=True)
            .execute()
        )
        return result.data

    def get_contact_by_apollo_id(self, apollo_id: str) -> dict | None:
        """Get a contact by Apollo ID (for deduplication)."""
        result = (
            self.client.table("contacts")
            .select("id, apollo_id")
            .eq("apollo_id", apollo_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def insert_contact(self, data: dict) -> dict:
        """Insert a new contact record.

        Auto-classifies persona_type from title if not already set,
        and computes initial priority_score.
        """
        from backend.app.agents.discovery import classify_persona
        from backend.app.core.queue_manager import compute_priority_score

        if not data.get("persona_type"):
            persona_type, is_dm = classify_persona(data.get("title"))
            data["persona_type"] = persona_type
            data["is_decision_maker"] = is_dm

        # Compute initial priority score (no company context yet — will be
        # recomputed with full context on first update-scores run)
        data.setdefault("priority_score", compute_priority_score(data, {}))

        result = self.client.table("contacts").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_contact(self, contact_id: str, data: dict) -> dict:
        """Update a contact record."""
        result = (
            self.client.table("contacts").update(data).eq("id", contact_id).execute()
        )
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Research Intelligence
    # ------------------------------------------------------------------

    def get_research(self, company_id: str) -> dict | None:
        """Get research intelligence for a company."""
        result = (
            self.client.table("research_intelligence")
            .select("*")
            .eq("company_id", company_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def upsert_research(self, data: dict) -> dict:
        """Insert or update research intelligence."""
        result = (
            self.client.table("research_intelligence")
            .upsert(data, on_conflict="company_id")
            .execute()
        )
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Outreach Drafts
    # ------------------------------------------------------------------

    def get_pending_drafts(self, limit: int = 50) -> list[dict]:
        """Get outreach drafts pending approval."""
        result = (
            self.client.table("outreach_drafts")
            .select("*, companies(name, tier, pqs_total), contacts(full_name, title, email)")
            .eq("approval_status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    def insert_outreach_draft(self, data: dict) -> dict:
        """Insert a new outreach draft."""
        result = self.client.table("outreach_drafts").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_outreach_draft(self, draft_id: str, data: dict) -> dict:
        """Update an outreach draft (approve/reject/edit)."""
        result = (
            self.client.table("outreach_drafts")
            .update(data)
            .eq("id", draft_id)
            .execute()
        )
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def get_interactions(
        self, company_id: str | None = None, contact_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Get interactions, optionally filtered by company or contact."""
        query = self.client.table("interactions").select("*")
        if company_id:
            query = query.eq("company_id", company_id)
        if contact_id:
            query = query.eq("contact_id", contact_id)
        query = query.order("created_at", desc=True).limit(limit)
        return query.execute().data

    def insert_interaction(self, data: dict) -> dict:
        """Insert a new interaction record."""
        result = self.client.table("interactions").insert(data).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Engagement Sequences
    # ------------------------------------------------------------------

    def get_active_sequences(self, due_before: str | None = None) -> list[dict]:
        """Get active engagement sequences, optionally filtered by due date."""
        query = (
            self.client.table("engagement_sequences")
            .select("*, companies(name), contacts(full_name, email)")
            .eq("status", "active")
        )
        if due_before:
            query = query.lte("next_action_at", due_before)
        query = query.order("next_action_at")
        return query.execute().data

    def insert_engagement_sequence(self, data: dict) -> dict:
        """Insert a new engagement sequence."""
        result = self.client.table("engagement_sequences").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_engagement_sequence(self, sequence_id: str, data: dict) -> dict:
        """Update an engagement sequence."""
        result = (
            self.client.table("engagement_sequences")
            .update(data)
            .eq("id", sequence_id)
            .execute()
        )
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # API Costs
    # ------------------------------------------------------------------

    def log_api_cost(self, data: dict) -> dict:
        """Log an API cost record."""
        result = self.client.table("api_costs").insert(data).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Learning Outcomes
    # ------------------------------------------------------------------

    def insert_learning_outcome(self, data: dict) -> dict:
        """Insert a learning outcome record."""
        result = self.client.table("learning_outcomes").insert(data).execute()
        return result.data[0] if result.data else {}

    def get_learning_outcomes(self, limit: int = 500) -> list[dict]:
        """Get learning outcomes for analysis."""
        result = (
            self.client.table("learning_outcomes")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    
    # ------------------------------------------------------------------
    # Action Queue
    # ------------------------------------------------------------------

    def get_action_queue(self, scheduled_date=None, action_type=None, status="pending", limit=100):
        query = self.client.table("action_queue").select(
            "*, companies(id, name, domain, tier, pqs_total, status, industry), "
            "contacts(id, full_name, title, linkedin_url, linkedin_status, email)"
        )
        if scheduled_date:
            query = query.eq("scheduled_date", scheduled_date)
        if action_type:
            query = query.eq("action_type", action_type)
        query = query.eq("status", status).order("priority").order("pqs_at_queue_time", desc=True)
        return query.limit(limit).execute().data

    def insert_action_queue_item(self, data):
        result = self.client.table("action_queue").insert(data).execute()
        return result.data[0] if result.data else {}

    def insert_action_queue_batch(self, items):
        if not items: return []
        return self.client.table("action_queue").insert(items).execute().data

    def update_action_queue_item(self, item_id, data):
        result = self.client.table("action_queue").update(data).eq("id", item_id).execute()
        return result.data[0] if result.data else {}

    def count_action_queue(self, scheduled_date, action_type=None, status=None):
        query = self.client.table("action_queue").select("id", count="exact").eq("scheduled_date", scheduled_date)
        if action_type: query = query.eq("action_type", action_type)
        if status: query = query.eq("status", status)
        return query.execute().count or 0

    def get_queued_contact_ids(self, scheduled_date):
        result = self.client.table("action_queue").select("contact_id").eq("scheduled_date", scheduled_date).in_("status", ["pending", "in_progress"]).execute()
        return {r["contact_id"] for r in result.data if r.get("contact_id")}

    def insert_action_request(self, data):
        result = self.client.table("action_requests").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_action_request(self, request_id, data):
        result = self.client.table("action_requests").update(data).eq("id", request_id).execute()
        return result.data[0] if result.data else {}

    def get_action_requests(self, limit=50):
        return self.client.table("action_requests").select("*").order("created_at", desc=True).limit(limit).execute().data

    def get_daily_targets(self, effective_date=None):
        if effective_date:
            ov = self.client.table("daily_targets").select("*").eq("effective_date", effective_date).eq("is_active", True).execute().data
            if ov:
                ot = {r["action_type"] for r in ov}
                df = self.client.table("daily_targets").select("*").is_("effective_date", "null").eq("is_active", True).execute().data
                return ov + [d for d in df if d["action_type"] not in ot]
        return self.client.table("daily_targets").select("*").is_("effective_date", "null").eq("is_active", True).execute().data

    def upsert_daily_target(self, action_type, target_count, effective_date=None):
        data = {"action_type": action_type, "target_count": target_count, "effective_date": effective_date, "is_active": True}
        result = self.client.table("daily_targets").upsert(data, on_conflict="action_type,effective_date,day_of_week").execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Enrichment lifecycle
    # ------------------------------------------------------------------

    def get_contacts_needing_enrichment(
        self,
        campaign_name: str | None = None,
        tier: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return contacts with enrichment_status = 'needs_enrichment' or 'stale'."""
        query = (
            self.client.table("contacts")
            .select("*, companies(name, domain, tier, campaign_name)")
            .in_("enrichment_status", ["needs_enrichment", "stale"])
        )
        if campaign_name or tier:
            # Filter via join — fetch all then filter in Python (Supabase limitation)
            rows = query.order("created_at").limit(500).execute().data
            if campaign_name:
                rows = [r for r in rows if (r.get("companies") or {}).get("campaign_name") == campaign_name]
            if tier:
                rows = [r for r in rows if (r.get("companies") or {}).get("tier") == tier]
            return rows[:limit]
        return query.order("created_at").limit(limit).execute().data

    def get_stale_contacts(self, stale_days: int = 90, limit: int = 200) -> list[dict]:
        """Return enriched contacts whose enriched_at is older than stale_days."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        result = (
            self.client.table("contacts")
            .select("id, first_name, last_name, title, apollo_id, enriched_at, company_id")
            .eq("enrichment_status", "enriched")
            .lt("enriched_at", cutoff)
            .order("enriched_at")
            .limit(limit)
            .execute()
        )
        return result.data

    def mark_contact_enriched(
        self,
        contact_id: str,
        email: str | None = None,
        phone: str | None = None,
        source: str = "apollo",
    ) -> dict:
        """Mark a contact as successfully enriched and stamp enriched_at.

        Also ensures persona_type is classified and priority_score is current.
        """
        from datetime import datetime, timezone
        from backend.app.agents.discovery import classify_persona
        from backend.app.core.queue_manager import compute_priority_score

        data: dict = {
            "enrichment_status": "enriched",
            "enriched_at": datetime.now(timezone.utc).isoformat(),
            "enrichment_source": source,
        }
        if email:
            data["email"] = email
        if phone:
            data["phone"] = phone

        # Fetch current contact to check persona and recompute score
        existing = self.client.table("contacts").select(
            "title, persona_type, completeness_score, companies(tier)"
        ).eq("id", contact_id).execute().data
        if existing:
            row = existing[0]
            if not row.get("persona_type"):
                persona_type, is_dm = classify_persona(row.get("title"))
                data["persona_type"] = persona_type
                data["is_decision_maker"] = is_dm
            company = row.get("companies") or {}
            merged = {**row, **data}
            data["priority_score"] = compute_priority_score(merged, company)

        return self.update_contact(contact_id, data)

    def mark_contact_enrichment_failed(self, contact_id: str, notes: str = "") -> dict:
        """Mark a contact's enrichment attempt as failed."""
        return self.update_contact(contact_id, {
            "enrichment_status": "failed",
            "enrichment_source": None,
        })

    def mark_contacts_stale(self, stale_days: int = 90) -> int:
        """Flip enriched contacts older than stale_days to 'stale'. Returns count updated."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        result = (
            self.client.table("contacts")
            .update({"enrichment_status": "stale"})
            .eq("enrichment_status", "enriched")
            .lt("enriched_at", cutoff)
            .execute()
        )
        return len(result.data)

    # ------------------------------------------------------------------
    # Apollo credit events
    # ------------------------------------------------------------------

    def log_apollo_credit(self, data: dict) -> dict:
        """Record one Apollo credit spend event."""
        result = self.client.table("apollo_credit_events").insert(data).execute()
        return result.data[0] if result.data else {}

    def get_apollo_credits_used(
        self,
        campaign_name: str | None = None,
        since_days: int = 30,
    ) -> dict:
        """Summarise Apollo credit usage over the last N days."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        query = (
            self.client.table("apollo_credit_events")
            .select("operation, credits_used, response_status")
            .gte("created_at", since)
        )
        if campaign_name:
            query = query.eq("campaign_name", campaign_name)
        rows = query.execute().data
        total = sum(r.get("credits_used", 1) for r in rows)
        by_op: dict[str, int] = {}
        for r in rows:
            op = r.get("operation", "unknown")
            by_op[op] = by_op.get(op, 0) + r.get("credits_used", 1)
        return {"total_credits": total, "by_operation": by_op, "events": len(rows)}

    # ------------------------------------------------------------------
    # Seed audit events
    # ------------------------------------------------------------------

    def log_audit_event(self, data: dict) -> dict:
        """Record one seed/import audit event."""
        result = self.client.table("seed_audit_events").insert(data).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Outreach pace limiting
    # ------------------------------------------------------------------

    def count_sends_today(self, campaign_name: str) -> int:
        """Count emails sent today for a given campaign."""
        from datetime import date
        today = date.today().isoformat()
        result = (
            self.client.table("outreach_pace_log")
            .select("id", count="exact")
            .eq("send_date", today)
            .eq("campaign_name", campaign_name)
            .eq("status", "sent")
            .execute()
        )
        return result.count or 0

    def log_outreach_send(self, data: dict) -> dict:
        """Record one outreach send in the pace log."""
        result = self.client.table("outreach_pace_log").insert(data).execute()
        return result.data[0] if result.data else {}

    def is_contact_sent_today(self, contact_id: str) -> bool:
        """Return True if this contact has already been sent to today."""
        from datetime import date
        today = date.today().isoformat()
        result = (
            self.client.table("outreach_pace_log")
            .select("id", count="exact")
            .eq("contact_id", contact_id)
            .eq("send_date", today)
            .execute()
        )
        return (result.count or 0) > 0

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------

    def count_companies(
        self,
        status: str | None = None,
        tier: str | None = None,
        min_pqs: int | None = None,
        batch_id: str | None = None,
        search: str | None = None,
    ) -> int:
        """Return total count of companies matching the given filters."""
        query = self.client.table("companies").select("id", count="exact")
        if status:
            query = query.eq("status", status)
        if tier:
            query = query.eq("tier", tier)
        if min_pqs is not None:
            query = query.gte("pqs_total", min_pqs)
        if batch_id:
            query = query.eq("batch_id", batch_id)
        if search:
            query = query.ilike("name", f"%{search}%")
        result = query.execute()
        return result.count or 0

    def count_companies_by_status(self) -> list[dict]:
        """Get company counts grouped by status."""
        result = (
            self.client.table("companies")
            .select("status")
            .execute()
        )
        counts: dict[str, int] = {}
        for row in result.data:
            status = row.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        return [{"status": s, "count": c} for s, c in sorted(counts.items())]

    def get_api_costs_summary(self, batch_id: str | None = None) -> list[dict]:
        """Get API cost summary."""
        query = self.client.table("api_costs").select("*")
        if batch_id:
            query = query.eq("batch_id", batch_id)
        query = query.order("created_at", desc=True).limit(500)
        return query.execute().data
