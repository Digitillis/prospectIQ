"""Supabase database client for ProspectIQ.

Provides a thin wrapper around the Supabase Python client
with convenience methods for common operations.
"""

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
        min_pqs: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query companies with optional filters."""
        query = self.client.table("companies").select("*")
        if status:
            query = query.eq("status", status)
        if tier:
            query = query.eq("tier", tier)
        if min_pqs is not None:
            query = query.gte("pqs_total", min_pqs)
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

    def insert_company(self, data: dict) -> dict:
        """Insert a new company record."""
        result = self.client.table("companies").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_company(self, company_id: str, data: dict) -> dict:
        """Update a company record."""
        result = (
            self.client.table("companies").update(data).eq("id", company_id).execute()
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
        """Insert a new contact record."""
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
    # Analytics helpers
    # ------------------------------------------------------------------

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
