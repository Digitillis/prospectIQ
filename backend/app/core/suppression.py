"""Suppression and DNC (Do Not Contact) enforcement.

Centralised guard that prevents outreach to contacts and companies
that should not be contacted. Checked before any draft is created
or any email is sent.

Suppression reasons:
- explicit_dnc: User manually added to DNC list
- bounced: Email bounced (invalid address)
- not_interested: Prospect replied "not interested"
- competitor: Company uses a competing AI/ML platform
- cooldown: Recently completed a sequence without reply (90-day cooldown)
- unsubscribed: Prospect unsubscribed via Instantly
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# Cooldown period after a sequence completes without reply
SEQUENCE_COOLDOWN_DAYS = 90


def is_suppressed(
    db: Database,
    company_id: str,
    contact_id: str | None = None,
) -> tuple[bool, str | None]:
    """Check if a company or contact is suppressed.

    Args:
        db: Database instance.
        company_id: Company ID to check.
        contact_id: Optional contact ID (checks contact-level suppression too).

    Returns:
        Tuple of (is_suppressed, reason_or_None).
    """
    # 1. Check company status — terminal states block outreach
    company = db.get_company(company_id)
    if not company:
        return True, "company_not_found"

    blocked_statuses = {"not_interested", "disqualified", "bounced", "converted"}
    if company.get("status") in blocked_statuses:
        return True, f"company_status:{company['status']}"

    # 2. Check contact-level suppression
    if contact_id:
        contact_result = (
            db.client.table("contacts")
            .select("status, email")
            .eq("id", contact_id)
            .execute()
        )
        if contact_result.data:
            contact = contact_result.data[0]
            if contact.get("status") in ("bounced", "not_interested", "unsubscribed"):
                return True, f"contact_status:{contact['status']}"

    # 3. Check for existing competitors (from research)
    research = db.get_research(company_id)
    if research:
        existing = research.get("existing_solutions") or []
        if existing and isinstance(existing, list) and len(existing) > 0:
            # Only suppress if a DIRECT competitor is found
            direct_competitors = {
                "uptake", "sparkcognition", "c3.ai", "c3 ai",
                "sight machine", "machinemetrics", "augury", "senseye",
            }
            for solution in existing:
                if solution.lower().strip() in direct_competitors:
                    return True, f"competitor:{solution}"

    # 4. Check sequence cooldown — if completed without reply, enforce cooldown
    if contact_id:
        completed_seqs = (
            db.client.table("engagement_sequences")
            .select("completed_at")
            .eq("contact_id", contact_id)
            .eq("status", "completed")
            .order("completed_at", desc=True)
            .limit(1)
            .execute()
        )
        if completed_seqs.data:
            completed_at = completed_seqs.data[0].get("completed_at")
            if completed_at:
                # Check if there was a reply after this sequence
                replies = (
                    db.client.table("interactions")
                    .select("id")
                    .eq("contact_id", contact_id)
                    .eq("type", "email_replied")
                    .gte("created_at", completed_at)
                    .limit(1)
                    .execute()
                )
                if not replies.data:
                    # No reply after sequence — check cooldown
                    cooldown_end = (
                        datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                        + timedelta(days=SEQUENCE_COOLDOWN_DAYS)
                    )
                    if datetime.now(timezone.utc) < cooldown_end:
                        days_left = (cooldown_end - datetime.now(timezone.utc)).days
                        return True, f"cooldown:{days_left}d_remaining"

    # 5. Check for duplicate outreach — already has a pending (unreviewed) draft.
    # Approved drafts are intentionally excluded: they are processed by the send
    # loop and should not suppress each other.
    if contact_id:
        pending = (
            db.client.table("outreach_drafts")
            .select("id")
            .eq("contact_id", contact_id)
            .eq("approval_status", "pending")
            .is_("sent_at", "null")
            .limit(1)
            .execute()
        )
        if pending.data:
            return True, "duplicate_draft_pending"

    # 6. Cross-channel coordination — check if the requested channel is blocked
    # This is checked by the outreach and linkedin agents before generating drafts
    # (not here, because suppression.py doesn't know which channel is being requested)

    return False, None


def get_suppression_summary(db: Database) -> dict:
    """Get a summary of all suppressed companies and contacts.

    Returns:
        Dict with counts by suppression reason.
    """
    summary = {
        "companies_not_interested": 0,
        "companies_disqualified": 0,
        "companies_bounced": 0,
        "contacts_bounced": 0,
        "contacts_not_interested": 0,
        "contacts_in_cooldown": 0,
        "companies_with_competitors": 0,
    }

    # Company-level
    for status in ["not_interested", "disqualified", "bounced"]:
        count = db.count_companies(status=status)
        summary[f"companies_{status}"] = count

    # Contact-level bounced
    bounced = (
        db.client.table("contacts")
        .select("id", count="exact")
        .eq("status", "bounced")
        .execute()
    )
    summary["contacts_bounced"] = bounced.count or 0

    return summary
