"""Suppression and DNC (Do Not Contact) enforcement — tiered architecture.

Suppression operates at three scopes:

  contact  — a specific email address or person is blocked (e.g. hard bounce,
             unsubscribe). Other contacts at the same company remain eligible.

  company  — the entire company is blocked. Only set by explicit escalation:
             multiple hard bounces across distinct contacts, spam complaint,
             company opt-out, manual block, legal hold. A single contact bounce
             never escalates automatically to company scope.

  domain   — all addresses at a domain are blocked (reserved for domain-level
             bounces or reputation signals from the mail provider).

Escalation thresholds:
  COMPANY_ESCALATION_BOUNCE_COUNT = 2   (distinct contacts with hard bounces)

Company-level statuses that independently block outreach:
  not_interested, disqualified, converted
  (NOT 'bounced' — that status no longer drives suppression; use suppression_log)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

SEQUENCE_COOLDOWN_DAYS = 90
COMPANY_ESCALATION_BOUNCE_COUNT = 2  # distinct bounced contacts before company block

# Company statuses that block outreach regardless of suppression_log.
# 'bounced' is intentionally excluded — bounce suppression now lives in
# suppression_log at contact scope.
_COMPANY_BLOCK_STATUSES = {"not_interested", "disqualified", "converted"}


# ---------------------------------------------------------------------------
# Public: record a suppression event
# ---------------------------------------------------------------------------

def record_suppression(
    db: Database,
    scope: str,
    reason: str,
    contact_id: str | None = None,
    company_id: str | None = None,
    email: str | None = None,
    domain: str | None = None,
    bounce_classification: str | None = None,
    provider_code: str | None = None,
    provider_message: str | None = None,
    triggered_by_contact_id: str | None = None,
    escalated_from: str | None = None,
    metadata: dict | None = None,
) -> str | None:
    """Write a suppression_log entry and return its ID.

    Does not modify contacts or companies directly — callers are responsible
    for updating those records (e.g. setting contact.status = 'bounced').
    """
    try:
        row = {
            "workspace_id": db.workspace_id or "00000000-0000-0000-0000-000000000001",
            "scope": scope,
            "reason": reason,
            "metadata": metadata or {},
        }
        if contact_id:
            row["contact_id"] = contact_id
        if company_id:
            row["company_id"] = company_id
        if email:
            row["email"] = email
        if domain:
            row["domain"] = domain
        if bounce_classification:
            row["bounce_classification"] = bounce_classification
        if provider_code:
            row["provider_code"] = provider_code
        if provider_message:
            row["provider_message"] = provider_message
        if triggered_by_contact_id:
            row["triggered_by_contact_id"] = triggered_by_contact_id
        if escalated_from:
            row["escalated_from"] = escalated_from

        result = db.client.table("suppression_log").insert(row).execute()
        return (result.data[0]["id"] if result.data else None)
    except Exception as exc:
        logger.warning("record_suppression failed (non-fatal): %s", exc)
        return None


def maybe_escalate_to_company(
    db: Database,
    company_id: str,
    triggering_suppression_id: str | None = None,
) -> bool:
    """Check if bounce count at this company warrants escalation to company scope.

    Returns True if a company-scope suppression entry was created.
    """
    try:
        bounced = (
            db.client.table("suppression_log")
            .select("id, contact_id", count="exact")
            .eq("company_id", company_id)
            .eq("scope", "contact")
            .eq("reason", "hard_bounce_contact")
            .execute()
        )
        distinct_contacts = {r["contact_id"] for r in (bounced.data or []) if r.get("contact_id")}
        if len(distinct_contacts) < COMPANY_ESCALATION_BOUNCE_COUNT:
            return False

        # Check if a company-scope entry already exists
        existing = (
            db.client.table("suppression_log")
            .select("id")
            .eq("company_id", company_id)
            .eq("scope", "company")
            .eq("reason", "hard_bounce_domain")
            .limit(1)
            .execute()
        )
        if existing.data:
            return False

        entry_id = record_suppression(
            db,
            scope="company",
            reason="hard_bounce_domain",
            company_id=company_id,
            bounce_classification="hard",
            escalated_from=triggering_suppression_id,
            metadata={
                "escalated_from_contact_count": len(distinct_contacts),
                "threshold": COMPANY_ESCALATION_BOUNCE_COUNT,
            },
        )
        if entry_id:
            logger.warning(
                "suppression: company %s escalated to company scope after %d distinct bounces",
                company_id, len(distinct_contacts),
            )
        return bool(entry_id)
    except Exception as exc:
        logger.warning("maybe_escalate_to_company failed (non-fatal): %s", exc)
        return False


# ---------------------------------------------------------------------------
# Public: check suppression
# ---------------------------------------------------------------------------

def is_suppressed(
    db: Database,
    company_id: str,
    contact_id: str | None = None,
    skip_duplicate_check: bool = False,
) -> tuple[bool, str | None]:
    """Check whether a company or contact is suppressed.

    Tiered logic:
      1. Company status — terminal non-bounce statuses block immediately
      2. Company-scope suppression_log entry — explicit escalations
      3. Contact status — bounced / not_interested / unsubscribed
      4. Competitor research check
      5. Sequence cooldown
      6. Duplicate draft guard (skipped in send path)
      7. Cross-company email dedup

    Returns (is_suppressed, reason_string | None).
    """
    # 1. Company status — explicit terminal states (not 'bounced')
    company = db.get_company(company_id)
    if not company:
        return True, "company_not_found"

    if company.get("status") in _COMPANY_BLOCK_STATUSES:
        return True, f"company_status:{company['status']}"

    # 2. Company-scope suppression_log — escalated bounces, spam, opt-outs
    try:
        company_suppression = (
            db.client.table("suppression_log")
            .select("reason, scope")
            .eq("company_id", company_id)
            .eq("scope", "company")
            .limit(1)
            .execute()
        )
        if company_suppression.data:
            entry = company_suppression.data[0]
            return True, f"suppression_log:{entry['reason']}"
    except Exception:
        pass

    # 3. Contact-level suppression
    if contact_id:
        try:
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
        except Exception:
            pass

    # 4. Competitor check
    research = db.get_research(company_id)
    if research:
        existing = research.get("existing_solutions") or []
        if existing and isinstance(existing, list):
            direct_competitors = {
                "uptake", "sparkcognition", "c3.ai", "c3 ai",
                "sight machine", "machinemetrics", "augury", "senseye",
            }
            for solution in existing:
                if str(solution).lower().strip() in direct_competitors:
                    return True, f"competitor:{solution}"

    # 5. Sequence cooldown
    if contact_id:
        try:
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
                        cooldown_end = (
                            datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                            + timedelta(days=SEQUENCE_COOLDOWN_DAYS)
                        )
                        if datetime.now(timezone.utc) < cooldown_end:
                            days_left = (cooldown_end - datetime.now(timezone.utc)).days
                            return True, f"cooldown:{days_left}d_remaining"
        except Exception:
            pass

    # 6. Duplicate draft guard (skipped in send path)
    if contact_id and not skip_duplicate_check:
        try:
            pending = (
                db.client.table("outreach_drafts")
                .select("id")
                .eq("contact_id", contact_id)
                .in_("approval_status", ["pending", "approved"])
                .is_("sent_at", "null")
                .limit(1)
                .execute()
            )
            if pending.data:
                return True, "duplicate_draft_pending"
        except Exception:
            pass

    # 7. Cross-company email dedup (same address under duplicate company records)
    if contact_id:
        try:
            contact_row = (
                db.client.table("contacts")
                .select("email")
                .eq("id", contact_id)
                .limit(1)
                .execute()
            )
            email = (contact_row.data[0].get("email") or "") if contact_row.data else ""
            if email:
                sibling_rows = (
                    db.client.table("contacts")
                    .select("id")
                    .ilike("email", email)
                    .execute()
                )
                sibling_ids = [r["id"] for r in sibling_rows.data if r["id"] != contact_id]
                if sibling_ids:
                    already_sent = (
                        db.client.table("outreach_drafts")
                        .select("id")
                        .in_("contact_id", sibling_ids)
                        .not_.is_("sent_at", "null")
                        .limit(1)
                        .execute()
                    )
                    if already_sent.data:
                        return True, f"email_already_contacted:{email}"
        except Exception as exc:
            logger.warning("Email dedup check failed (non-fatal): %s", exc)

    return False, None


def get_suppression_summary(db: Database) -> dict:
    """Return suppression counts by scope and reason."""
    summary: dict[str, Any] = {
        "contact_bounced": 0,
        "contact_unsubscribed": 0,
        "contact_not_interested": 0,
        "company_escalated": 0,
        "company_status_blocked": 0,
    }
    try:
        for status in ["bounced", "unsubscribed", "not_interested"]:
            r = (
                db.client.table("contacts")
                .select("id", count="exact")
                .eq("status", status)
                .execute()
            )
            summary[f"contact_{status}"] = r.count or 0

        for status in list(_COMPANY_BLOCK_STATUSES):
            r = (
                db.client.table("companies")
                .select("id", count="exact")
                .eq("status", status)
                .execute()
            )
            summary[f"company_status_{status}"] = r.count or 0

        company_escalated = (
            db.client.table("suppression_log")
            .select("id", count="exact")
            .eq("scope", "company")
            .execute()
        )
        summary["company_escalated"] = company_escalated.count or 0
    except Exception as exc:
        logger.warning("get_suppression_summary failed: %s", exc)
    return summary
