"""Supabase database client for ProspectIQ.

Provides a thin wrapper around the Supabase Python client
with convenience methods for common operations.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from supabase import create_client, Client

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


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
    """Convenience wrapper around Supabase client.

    Pass ``workspace_id`` to scope all reads/writes to a single workspace.
    When omitted, no workspace filter is applied (pipeline/admin use).
    """

    def __init__(self, workspace_id: str | None = None):
        self.client = get_supabase_client()
        self.workspace_id = workspace_id
        logger.debug(f"Database.__init__: workspace_id={workspace_id}")

    # ------------------------------------------------------------------
    # Workspace helpers (internal)
    # ------------------------------------------------------------------

    def _filter_ws(self, query):
        """Apply workspace filter to a query when workspace_id is set."""
        if self.workspace_id:
            logger.debug(f"_filter_ws: applying workspace filter workspace_id={self.workspace_id}")
            query = query.eq("workspace_id", self.workspace_id)
        else:
            logger.warning("_filter_ws: NO workspace_id set! Returning unfiltered query!")
        return query

    def _inject_ws(self, data: dict) -> dict:
        """Add workspace_id to an insert/upsert payload when set."""
        if self.workspace_id and "workspace_id" not in data:
            logger.debug(f"_inject_ws: adding workspace_id={self.workspace_id} to payload")
            return {**data, "workspace_id": self.workspace_id}
        else:
            if not self.workspace_id:
                logger.warning("_inject_ws: NO workspace_id set! Returning data unmodified!")
        return data

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
        query = self._filter_ws(self.client.table("companies").select("*"))
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
        result = self.client.table("companies").insert(self._inject_ws(data)).execute()
        return result.data[0] if result.data else {}

    # Status rank — higher rank statuses must never be downgraded by lower ones
    _COMPANY_STATUS_RANK: dict[str, int] = {
        "discovered": 1,
        "researched": 2,
        "qualified": 3,
        "outreach_pending": 4,
        "contacted": 5,
        "engaged": 6,
        "meeting_scheduled": 7,
        "pilot_discussion": 8,
        "pilot_signed": 9,
        "active_pilot": 10,
        "converted": 11,
        # Terminal statuses — never overwrite
        "not_interested": 20,
        "disqualified": 20,
        "bounced": 20,
    }

    def update_company(self, company_id: str, data: dict, allow_downgrade: bool = False) -> dict:
        """Update a company record.

        If `data` contains a 'status' field, the update is only applied if the
        new status is an advancement (higher rank) over the current status.
        Pass allow_downgrade=True only for explicit resets (e.g. re-engagement).
        """
        new_status = data.get("status")
        if new_status and not allow_downgrade:
            # Fetch current status to guard against downgrades
            try:
                current = (
                    self.client.table("companies")
                    .select("status")
                    .eq("id", company_id)
                    .limit(1)
                    .execute()
                )
                if current.data:
                    cur_status = current.data[0].get("status", "")
                    cur_rank = self._COMPANY_STATUS_RANK.get(cur_status, 0)
                    new_rank = self._COMPANY_STATUS_RANK.get(new_status, 0)
                    if cur_rank >= new_rank:
                        import logging
                        logging.getLogger(__name__).debug(
                            f"update_company: skipping status downgrade {cur_status}→{new_status} for {company_id}"
                        )
                        return current.data[0]
            except Exception:
                pass  # If check fails, allow the update to proceed

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
        query = self._filter_ws(self.client.table("contacts").select("*"))
        result = (
            query
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

        result = self.client.table("contacts").insert(self._inject_ws(data)).execute()
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

    def get_pending_drafts(self, limit: int = 200) -> list[dict]:
        """Get outreach drafts pending approval."""
        query = self._filter_ws(
            self.client.table("outreach_drafts")
            .select("*, companies(name, tier, pqs_total), contacts(full_name, title, email)")
        )
        result = (
            query
            .eq("approval_status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    def insert_outreach_draft(self, data: dict) -> dict:
        """Insert a new outreach draft — deduplication guard included.

        Skips insert and returns the existing row if a draft already exists
        for the same (company_id, contact_id, sequence_step) with status
        'pending', 'approved', 'edited', or 'sent'. This prevents duplicate
        drafts from multiple scheduler runs or retriggers.
        """
        company_id = data.get("company_id")
        contact_id = data.get("contact_id")
        sequence_step = data.get("sequence_step")

        if company_id and contact_id and sequence_step is not None:
            existing = (
                self._filter_ws(
                    self.client.table("outreach_drafts").select("id, approval_status")
                )
                .eq("company_id", company_id)
                .eq("contact_id", contact_id)
                .eq("sequence_step", sequence_step)
                .in_("approval_status", ["pending", "approved", "edited", "sent"])
                .limit(1)
                .execute()
            )
            if existing.data:
                import logging
                logging.getLogger(__name__).debug(
                    f"insert_outreach_draft: skipping duplicate for contact={contact_id} "
                    f"step={sequence_step} (existing id={existing.data[0]['id']}, "
                    f"status={existing.data[0]['approval_status']})"
                )
                return existing.data[0]

        result = self.client.table("outreach_drafts").insert(self._inject_ws(data)).execute()
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
        query = self._filter_ws(self.client.table("interactions").select("*"))
        if company_id:
            query = query.eq("company_id", company_id)
        if contact_id:
            query = query.eq("contact_id", contact_id)
        query = query.order("created_at", desc=True).limit(limit)
        return query.execute().data

    def insert_interaction(self, data: dict) -> dict:
        """Insert a new interaction record."""
        result = self.client.table("interactions").insert(self._inject_ws(data)).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Engagement Sequences
    # ------------------------------------------------------------------

    def get_active_sequences(self, due_before: str | None = None) -> list[dict]:
        """Get active engagement sequences, optionally filtered by due date."""
        query = self._filter_ws(
            self.client.table("engagement_sequences")
            .select("*, companies(name), contacts(full_name, email)")
        ).eq("status", "active")
        if due_before:
            query = query.lte("next_action_at", due_before)
        query = query.order("next_action_at")
        return query.execute().data

    def insert_engagement_sequence(self, data: dict) -> dict:
        """Insert a new engagement sequence."""
        result = self.client.table("engagement_sequences").insert(self._inject_ws(data)).execute()
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
        result = self.client.table("api_costs").insert(self._inject_ws(data)).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------
    # Learning Outcomes
    # ------------------------------------------------------------------

    def insert_learning_outcome(self, data: dict) -> dict:
        """Insert a learning outcome record."""
        result = self.client.table("learning_outcomes").insert(self._inject_ws(data)).execute()
        return result.data[0] if result.data else {}

    def get_learning_outcomes(self, limit: int = 500) -> list[dict]:
        """Get learning outcomes for analysis."""
        result = (
            self._filter_ws(self.client.table("learning_outcomes").select("*"))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    
    # ------------------------------------------------------------------
    # Action Queue
    # ------------------------------------------------------------------

    def get_action_queue(self, scheduled_date=None, action_type=None, status="pending", limit=100):
        query = self._filter_ws(self.client.table("action_queue").select(
            "*, companies(id, name, domain, tier, pqs_total, status, industry), "
            "contacts(id, full_name, title, linkedin_url, linkedin_status, email)"
        ))
        if scheduled_date:
            query = query.eq("scheduled_date", scheduled_date)
        if action_type:
            query = query.eq("action_type", action_type)
        query = query.eq("status", status).order("priority").order("pqs_at_queue_time", desc=True)
        return query.limit(limit).execute().data

    def insert_action_queue_item(self, data):
        result = self.client.table("action_queue").insert(self._inject_ws(data)).execute()
        return result.data[0] if result.data else {}

    def insert_action_queue_batch(self, items):
        if not items: return []
        return self.client.table("action_queue").insert(
            [self._inject_ws(i) for i in items]
        ).execute().data

    def update_action_queue_item(self, item_id, data):
        result = self.client.table("action_queue").update(data).eq("id", item_id).execute()
        return result.data[0] if result.data else {}

    def count_action_queue(self, scheduled_date, action_type=None, status=None):
        query = self._filter_ws(
            self.client.table("action_queue").select("id", count="exact")
        ).eq("scheduled_date", scheduled_date)
        if action_type: query = query.eq("action_type", action_type)
        if status: query = query.eq("status", status)
        return query.execute().count or 0

    def get_queued_contact_ids(self, scheduled_date):
        result = self._filter_ws(
            self.client.table("action_queue").select("contact_id")
        ).eq("scheduled_date", scheduled_date).in_("status", ["pending", "in_progress"]).execute()
        return {r["contact_id"] for r in result.data if r.get("contact_id")}

    def insert_action_request(self, data):
        result = self.client.table("action_requests").insert(data).execute()
        return result.data[0] if result.data else {}

    def update_action_request(self, request_id, data):
        result = self.client.table("action_requests").update(data).eq("id", request_id).execute()
        return result.data[0] if result.data else {}

    def get_action_requests(self, limit=50):
        return self._filter_ws(self.client.table("action_requests").select("*")).order("created_at", desc=True).limit(limit).execute().data

    def get_daily_targets(self, effective_date=None):
        if effective_date:
            ov = self._filter_ws(self.client.table("daily_targets").select("*")).eq("effective_date", effective_date).eq("is_active", True).execute().data
            if ov:
                ot = {r["action_type"] for r in ov}
                df = self._filter_ws(self.client.table("daily_targets").select("*")).is_("effective_date", "null").eq("is_active", True).execute().data
                return ov + [d for d in df if d["action_type"] not in ot]
        return self._filter_ws(self.client.table("daily_targets").select("*")).is_("effective_date", "null").eq("is_active", True).execute().data

    def upsert_daily_target(self, action_type, target_count, effective_date=None):
        data = {"action_type": action_type, "target_count": target_count, "effective_date": effective_date, "is_active": True}
        result = self.client.table("daily_targets").upsert(self._inject_ws(data), on_conflict="action_type,effective_date,day_of_week").execute()
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
        query = self._filter_ws(
            self.client.table("contacts")
            .select("*, companies(name, domain, tier, campaign_name)")
        ).in_("enrichment_status", ["needs_enrichment", "stale"])
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
            self._filter_ws(
                self.client.table("contacts")
                .select("id, first_name, last_name, title, apollo_id, enriched_at, company_id")
            )
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
        query = self._filter_ws(self.client.table("companies").select("id", count="exact"))
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
            self._filter_ws(self.client.table("companies").select("status"))
            .execute()
        )
        counts: dict[str, int] = {}
        for row in result.data:
            status = row.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        return [{"status": s, "count": c} for s, c in sorted(counts.items())]

    # ------------------------------------------------------------------
    # Outreach state machine
    # ------------------------------------------------------------------

    def update_contact_state(
        self,
        contact_id: str,
        new_state: str,
        from_state: str | None = None,
        channel: str | None = None,
        instantly_event: str | None = None,
        metadata: dict | None = None,
        extra_updates: dict | None = None,
    ) -> None:
        """Transition a contact to a new outreach state and log the transition.

        Updates outreach_state and outreach_state_updated_at on the contact,
        merges any extra_updates fields, then appends a row to outreach_state_log
        for a complete audit trail.
        """
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        updates: dict = {
            "outreach_state": new_state,
            "outreach_state_updated_at": now_iso,
        }
        if extra_updates:
            updates.update(extra_updates)

        self.client.table("contacts").update(updates).eq("id", contact_id).execute()

        self.client.table("outreach_state_log").insert(self._inject_ws({
            "contact_id": contact_id,
            "from_state": from_state,
            "to_state": new_state,
            "channel": channel,
            "instantly_event": instantly_event,
            "metadata": metadata or {},
        })).execute()

    def get_contact_by_email(self, email: str) -> dict | None:
        """Look up a contact by email address.

        Returns the first matching contact or None if not found.
        """
        result = (
            self.client.table("contacts")
            .select(
                "id, email, outreach_state, open_count, click_count, "
                "company_id, priority_score"
            )
            .eq("email", email)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def add_to_dnc(
        self,
        email: str,
        reason: str = "bounced",
        added_by: str = "instantly_webhook",
    ) -> None:
        """Add an email address to the do_not_contact registry.

        Uses upsert so repeated bounces or unsubscribes for the same
        address are idempotent.
        """
        self.client.table("do_not_contact").upsert(
            {
                "email": email,
                "reason": reason,
                "added_by": added_by,
            },
            on_conflict="email",
        ).execute()

    def is_company_in_active_outreach(self, company_id: str) -> bool:
        """Return True if this company already has an active outreach thread.

        An active thread is any contact in an in-progress send state.
        Used as a deduplication guard before launching a new sequence.
        """
        active_states = [
            "sequenced",
            "touch_1_sent",
            "touch_2_sent",
            "touch_3_sent",
            "touch_4_sent",
            "touch_5_sent",
        ]
        result = (
            self.client.table("contacts")
            .select("id")
            .eq("company_id", company_id)
            .in_("outreach_state", active_states)
            .limit(1)
            .execute()
        )
        return bool(result.data)

    def set_company_outreach_active(
        self,
        company_id: str,
        contact_id: str,
    ) -> None:
        """Mark a company as having an active outreach thread.

        Records the primary contact and the start timestamp so the
        dashboard can surface companies currently in sequence.
        """
        from datetime import datetime, timezone

        self.client.table("companies").update({
            "outreach_active": True,
            "primary_contact_id": contact_id,
            "outreach_started_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", company_id).execute()

    # ------------------------------------------------------------------
    # API costs summary (existing method continues below)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Intent signals
    # ------------------------------------------------------------------

    def get_companies_for_intent_scan(self, campaign_name: str | None = None) -> list[dict]:
        """Fetch companies with their Apollo org ID for intent scanning."""
        query = self.client.table("companies").select(
            "id, name, domain, apollo_id, campaign_name, intent_score"
        )
        if campaign_name:
            query = query.eq("campaign_name", campaign_name)
        result = query.execute()
        return result.data or []

    def upsert_intent_signal(self, signal: dict) -> dict:
        """Insert an intent signal record.

        Note: deduplication is handled upstream in IntentEngine before calling
        this method, so we do a plain insert here.
        """
        result = self.client.table("company_intent_signals").insert(signal).execute()
        return result.data[0] if result.data else {}

    def get_active_intent_signals(self, company_id: str) -> list[dict]:
        """Get all active (non-expired) intent signals for a company."""
        result = (
            self.client.table("company_intent_signals")
            .select("*")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .order("detected_at", desc=True)
            .execute()
        )
        return result.data or []

    def update_company_intent_score(self, company_id: str, score: int) -> None:
        """Update the cached intent score on the company record."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.client.table("companies").update({
            "intent_score": score,
            "intent_score_updated_at": now,
            "last_intent_signal_at": now,
        }).eq("id", company_id).execute()

    # ------------------------------------------------------------------
    # API costs summary (existing method continues below)
    # ------------------------------------------------------------------

    def get_api_costs_summary(self, batch_id: str | None = None) -> list[dict]:
        """Get API cost summary."""
        query = self._filter_ws(self.client.table("api_costs").select("*"))
        if batch_id:
            query = query.eq("batch_id", batch_id)
        query = query.order("created_at", desc=True).limit(500)
        return query.execute().data
