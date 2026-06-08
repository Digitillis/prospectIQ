"""Pre-send invariant library — hard checks before any draft is generated.

Every check in this module runs before an outreach draft is created. Failures
are logged to the send_assertions table and block the send. A Slack alert fires
on any failure.

Usage (in outreach agent, before _build_prompt):
    from backend.app.core.pre_send_assertions import run_pre_send_assertions, AssertionFailure
    try:
        run_pre_send_assertions(db, contact, company, sender_email, step)
    except AssertionFailure as e:
        # skip this contact
        result.add_detail(company_name, "assertion_failed", str(e))
        continue
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _get_send_limits() -> dict:
    """Load send limits from limits.yaml, with env var overrides."""
    import os

    try:
        from backend.app.core.limits import _load

        cfg = _load() or {}
        return cfg.get("send_limits") or {}
    except Exception:
        return {}


def _int_limit(key: str, env_var: str, default: int) -> int:
    import os

    v = os.environ.get(env_var)
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    try:
        return int(_get_send_limits().get(key, default))
    except Exception:
        return default


def _float_limit(key: str, env_var: str, default: float) -> float:
    import os

    v = os.environ.get(env_var)
    if v:
        try:
            return float(v)
        except ValueError:
            pass
    try:
        return float(_get_send_limits().get(key, default))
    except Exception:
        return default


# Days since last outreach to the same company before a new send is allowed
def _company_cooldown_days() -> int:
    return _int_limit("company_cooldown_days", "COMPANY_COOLDOWN_DAYS", 14)


# Hard bounce rate threshold (7-day rolling). Exceeding this pauses all sends.
def _max_bounce_rate() -> float:
    return _float_limit("max_bounce_rate", "MAX_BOUNCE_RATE", 0.02)


# Minimum days between any two emails to the same contact (hard floor).
# Step 2 (first follow-up) requires 3 days since step 1.
# Step 3+ requires 2 days since the prior step.
def _step_gap_days(sequence_step: int) -> int:
    """Return the minimum gap (days) required before sending `sequence_step`.

    Step 2 (first follow-up): 3 days — longer window gives the cold open time to land.
    Step 3+: 2 days — sequence is already warm; shorter gap keeps momentum.
    """
    if sequence_step <= 2:
        return _int_limit("step_gap_days_step_2", "STEP_GAP_DAYS_STEP_2", 3)
    return _int_limit("step_gap_days_step_3_plus", "STEP_GAP_DAYS_STEP_3_PLUS", 2)


# Keep module-level aliases for callers that reference these directly
COMPANY_COOLDOWN_DAYS: int = 14
MAX_BOUNCE_RATE: float = 0.02
MIN_STEP_GAP_DAYS: int = 3  # legacy alias — use _step_gap_days(step) for new code

# Email statuses that are safe to send to. NULL/unverified statuses block the send.
# - "verified": ZeroBounce/Apollo confirmed deliverable
# - "catch_all": domain accepts all mail; individual address unverifiable — allowed with caution
SENDABLE_EMAIL_STATUSES = frozenset({"verified", "catch_all"})


class AssertionFailure(Exception):
    """Raised when a pre-send invariant fails. Blocks the send."""

    def __init__(self, assertion: str, detail: str):
        self.assertion = assertion
        self.detail = detail
        super().__init__(f"{assertion}: {detail}")


def _log_assertion(
    db: Any,
    contact_id: str,
    company_id: str,
    assertion: str,
    passed: bool,
    detail: str,
    assertion_context: str = "draft_gen",
) -> None:
    """Write assertion result to send_assertions table.

    assertion_context distinguishes where in the pipeline the check ran:
    - 'draft_gen'  — outreach.py, before draft creation (advisory)
    - 'send_path'  — engagement.py, before delivery (authoritative)

    Column added by migration 047. If not yet applied, the insert degrades
    gracefully via the except handler below.
    """
    try:
        db.client.table("send_assertions").insert(
            {
                "contact_id": contact_id,
                "company_id": company_id or None,
                "assertion": assertion,
                "passed": passed,
                "detail": detail,
                "assertion_context": assertion_context,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as e:
        logger.warning("Could not log assertion to DB: %s", e)


def _alert(message: str) -> None:
    # Slack is optional — failures are durably stored in send_assertions
    # and surfaced on the dashboard via /api/approvals/alerts.
    try:
        from backend.app.utils.notifications import notify_slack

        notify_slack(message, emoji=":rotating_light:")
    except Exception:
        pass


def assert_not_rejected(db: Any, draft_id: str, assertion_context: str = "send_path") -> None:
    """Draft must not carry approval_status='rejected' or 'dispatch_failed'.

    Blocks the send path so a rejected draft can never be dispatched regardless
    of what is in the outbound_queue.  This closes the gap where 46 already-rejected
    drafts were sent (R2 remediation).
    """
    try:
        row = (
            db.client.table("outreach_drafts")
            .select("id, approval_status")
            .eq("id", draft_id)
            .limit(1)
            .execute()
        ).data
    except Exception as e:
        logger.warning(
            "assert_not_rejected: DB lookup failed (%s) — passing to avoid false block", e
        )
        return

    if not row:
        return  # draft not found; let downstream handle it

    status = row[0].get("approval_status", "")
    if status in ("rejected", "dispatch_failed"):
        detail = f"draft {draft_id} has approval_status={status!r} — cannot dispatch"
        _log_assertion(db, None, None, "not_rejected", False, detail, assertion_context)
        raise AssertionFailure("not_rejected", detail)

    _log_assertion(
        db,
        None,
        None,
        "not_rejected",
        True,
        f"draft {draft_id} approval_status={status!r}",
        assertion_context,
    )


def assert_email_deliverable(db: Any, contact: dict, assertion_context: str = "draft_gen") -> None:
    """Email must not be a confirmed invalid or bounced address."""
    email_status = contact.get("email_status")
    if email_status in ("invalid", "bounce"):
        detail = f"email_status={email_status} for {contact.get('email')}"
        _log_assertion(
            db,
            contact["id"],
            contact.get("company_id", ""),
            "email_deliverable",
            False,
            detail,
            assertion_context,
        )
        _alert(
            f":red_circle: Pre-send assertion failed: email_deliverable — {contact.get('full_name')} ({detail})"
        )
        raise AssertionFailure("email_deliverable", detail)
    _log_assertion(
        db,
        contact["id"],
        contact.get("company_id", ""),
        "email_deliverable",
        True,
        f"status={email_status or 'unknown'}",
        assertion_context,
    )


def assert_email_status_verified(
    db: Any, contact: dict, assertion_context: str = "draft_gen"
) -> None:
    """Email must have a known-safe verification status before entering the send queue.

    Blocks: NULL (never verified), 'unverified' (verification attempted but unresolved).
    Allows: 'verified' (confirmed deliverable), 'catch_all' (domain accepts all — allowed
    with caution because individual verification is impossible on catch-all domains).

    This is the primary gate against unverified contacts reaching delivery.
    """
    email_status = contact.get("email_status")
    if email_status not in SENDABLE_EMAIL_STATUSES:
        detail = (
            f"email_status={email_status!r} for {contact.get('email')} — "
            f"must be one of {sorted(SENDABLE_EMAIL_STATUSES)}"
        )
        _log_assertion(
            db,
            contact["id"],
            contact.get("company_id", ""),
            "email_status_verified",
            False,
            detail,
            assertion_context,
        )
        _alert(
            f":red_circle: Pre-send assertion failed: email_status_verified — "
            f"{contact.get('full_name')} ({detail})"
        )
        raise AssertionFailure("email_status_verified", detail)
    _log_assertion(
        db,
        contact["id"],
        contact.get("company_id", ""),
        "email_status_verified",
        True,
        f"status={email_status}",
        assertion_context,
    )


def assert_email_name_consistent(
    db: Any, contact: dict, assertion_context: str = "draft_gen"
) -> None:
    """Email must not be flagged as belonging to a different person."""
    if contact.get("email_name_verified") is False:
        detail = f"email_name_verified=False for {contact.get('email')}"
        _log_assertion(
            db,
            contact["id"],
            contact.get("company_id", ""),
            "email_name_consistent",
            False,
            detail,
            assertion_context,
        )
        _alert(
            f":red_circle: Pre-send assertion failed: email_name_consistent — {contact.get('full_name')} ({detail})"
        )
        raise AssertionFailure("email_name_consistent", detail)
    _log_assertion(
        db,
        contact["id"],
        contact.get("company_id", ""),
        "email_name_consistent",
        True,
        "ok",
        assertion_context,
    )


def assert_outreach_eligible(db: Any, contact: dict, assertion_context: str = "draft_gen") -> None:
    """Contact must have is_outreach_eligible=True."""
    if contact.get("is_outreach_eligible") is False:
        detail = f"tier={contact.get('contact_tier')} for {contact.get('full_name')}"
        _log_assertion(
            db,
            contact["id"],
            contact.get("company_id", ""),
            "outreach_eligible",
            False,
            detail,
            assertion_context,
        )
        _alert(
            f":red_circle: Pre-send assertion failed: outreach_eligible — {contact.get('full_name')} ({detail})"
        )
        raise AssertionFailure("outreach_eligible", detail)
    _log_assertion(
        db,
        contact["id"],
        contact.get("company_id", ""),
        "outreach_eligible",
        True,
        "ok",
        assertion_context,
    )


def assert_persona_target(db: Any, contact: dict, assertion_context: str = "draft_gen") -> None:
    """Contact must not be in an excluded persona tier."""
    tier = contact.get("contact_tier")
    if tier == "excluded":
        detail = f"contact_tier=excluded, title={contact.get('title')}"
        _log_assertion(
            db,
            contact["id"],
            contact.get("company_id", ""),
            "persona_target",
            False,
            detail,
            assertion_context,
        )
        _alert(
            f":red_circle: Pre-send assertion failed: persona_target — {contact.get('full_name')} ({detail})"
        )
        raise AssertionFailure("persona_target", detail)
    _log_assertion(
        db,
        contact["id"],
        contact.get("company_id", ""),
        "persona_target",
        True,
        f"tier={tier}",
        assertion_context,
    )


def assert_no_recent_company_send(
    db: Any,
    contact: dict,
    company: dict,
    days: int | None = None,
    assertion_context: str = "draft_gen",
    current_draft_id: str | None = None,
) -> None:
    """No send to this company in the last N days (to same contact)."""
    if days is None:
        days = _company_cooldown_days()
    company_id = company.get("id") or contact.get("company_id")
    if not company_id:
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        q = (
            db.client.table("outreach_drafts")
            .select("id,sent_at")
            .eq("contact_id", contact["id"])
            .not_.is_("sent_at", "null")
            .gte("sent_at", cutoff)
        )
        # Exclude the draft being processed: its sent_at was set by the atomic
        # claim before this assertion runs and must not be treated as a prior send.
        if current_draft_id:
            q = q.neq("id", current_draft_id)
        result = q.limit(1).execute()
        if result.data:
            sent_at = result.data[0].get("sent_at", "")[:10]
            detail = f"Last send to {contact.get('full_name')} was {sent_at} (cooldown={days}d)"
            _log_assertion(
                db,
                contact["id"],
                company_id,
                "no_recent_company_send",
                False,
                detail,
                assertion_context,
            )
            raise AssertionFailure("no_recent_company_send", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check recent send for contact %s: %s", contact["id"], e)

    _log_assertion(
        db,
        contact["id"],
        company_id,
        "no_recent_company_send",
        True,
        f"no send in past {days}d",
        assertion_context,
    )


def assert_sender_under_daily_cap(
    db: Any, sender_email: str, daily_cap: int, assertion_context: str = "draft_gen"
) -> None:
    """Sender must not have exceeded their daily send quota."""
    today_start = (
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    )
    try:
        result = (
            db.client.table("outreach_drafts")
            .select("id", count="exact")
            .eq("sender_email", sender_email)
            .not_.is_("sent_at", "null")
            .gte("sent_at", today_start)
            .execute()
        )
        count = result.count or 0
        if count >= daily_cap:
            detail = f"{sender_email} has sent {count}/{daily_cap} today"
            _log_assertion(db, None, None, "sender_daily_cap", False, detail, assertion_context)
            raise AssertionFailure("sender_daily_cap", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check daily cap for %s: %s", sender_email, e)

    _log_assertion(
        db, None, None, "sender_daily_cap", True, f"{sender_email}: under cap", assertion_context
    )


def assert_prior_step_sent(
    db: Any, contact: dict, sequence_step: int, assertion_context: str = "draft_gen"
) -> None:
    """For step N ≥ 2, step N-1 must have been sent (sent_at IS NOT NULL).

    Prevents step-3 from being drafted/sent when step-2 is still pending review,
    and catches sequences whose current_step counter ran ahead of actual sends.
    """
    if sequence_step < 2:
        return
    contact_id = contact.get("id") or contact.get("contact_id")
    if not contact_id:
        return
    prior_step = sequence_step - 1
    try:
        result = (
            db.client.table("outreach_drafts")
            .select("id, sent_at")
            .eq("contact_id", contact_id)
            .eq("sequence_step", prior_step)
            .not_.is_("sent_at", "null")
            .limit(1)
            .execute()
        )
        if not result.data:
            detail = (
                f"step {prior_step} has not been sent for contact {contact_id} — "
                f"cannot send step {sequence_step}"
            )
            _log_assertion(
                db,
                contact_id,
                contact.get("company_id", ""),
                "prior_step_sent",
                False,
                detail,
                assertion_context,
            )
            _alert(
                f":warning: Pre-send gate: prior_step_sent failed — {contact.get('full_name')} ({detail})"
            )
            raise AssertionFailure("prior_step_sent", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check prior step for contact %s: %s", contact_id, e)
    _log_assertion(
        db,
        contact_id,
        contact.get("company_id", ""),
        "prior_step_sent",
        True,
        f"step {prior_step} confirmed sent",
        assertion_context,
    )


def assert_minimum_step_gap(
    db: Any, contact: dict, sequence_step: int, assertion_context: str = "draft_gen"
) -> None:
    """For step N >= 2, the required gap since the prior step must have passed.

    Gap is step-selective:
    - Step 2: 3 days (cold open needs time to land before follow-up)
    - Step 3+: 2 days (sequence is warm; shorter gap maintains momentum)
    """
    if sequence_step < 2:
        return
    contact_id = contact.get("id") or contact.get("contact_id")
    if not contact_id:
        return
    prior_step = sequence_step - 1
    try:
        result = (
            db.client.table("outreach_drafts")
            .select("sent_at")
            .eq("contact_id", contact_id)
            .eq("sequence_step", prior_step)
            .not_.is_("sent_at", "null")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data and result.data[0].get("sent_at"):
            sent_str = result.data[0]["sent_at"].replace("Z", "+00:00")
            # Normalize fractional seconds to 6 digits — Supabase occasionally
            # returns truncated microseconds (e.g. .11174 instead of .111740).
            import re as _re

            sent_str = _re.sub(
                r"(\.\d{1,5})(?=[+-]|$)", lambda m: m.group(1).ljust(7, "0"), sent_str
            )
            try:
                last_sent = datetime.fromisoformat(sent_str)
            except ValueError:
                last_sent = datetime.fromisoformat(sent_str.replace("+00:00", "")).replace(
                    tzinfo=timezone.utc
                )
            # Compare calendar dates, not datetimes. The scheduler plans at date
            # granularity; timedelta.days truncates fractional days and fires
            # spuriously when dispatch runs early morning after a late-afternoon send.
            # Root cause of June 3 batch failure (429 sends blocked incorrectly).
            today_date = datetime.now(timezone.utc).date()
            last_sent_date = last_sent.date()
            days_since = (today_date - last_sent_date).days
            gap = _step_gap_days(sequence_step)
            if days_since < gap:
                detail = (
                    f"only {days_since}d since step {prior_step} was sent — "
                    f"minimum gap is {gap}d (step {sequence_step} blocked)"
                )
                _log_assertion(
                    db,
                    contact_id,
                    contact.get("company_id", ""),
                    "minimum_step_gap",
                    False,
                    detail,
                    assertion_context,
                )
                _alert(
                    f":warning: Pre-send gate: minimum_step_gap failed — {contact.get('full_name')} ({detail})"
                )
                raise AssertionFailure("minimum_step_gap", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check step gap for contact %s: %s", contact_id, e)
    _log_assertion(
        db,
        contact_id,
        contact.get("company_id", ""),
        "minimum_step_gap",
        True,
        f"gap ok for step {sequence_step}",
        assertion_context,
    )


def assert_bounce_rate_ok(db: Any, assertion_context: str = "send_path") -> None:
    """7-day rolling hard bounce rate must not exceed MAX_BOUNCE_RATE (2%).

    True bounce rate definition (per docs/reports/remediation/crm_state_remediation.md):
    contact-scoped — what fraction of contacts we tried to reach were undeliverable.

    Numerator   : COUNT(DISTINCT contact_id) from outreach_drafts where bounced_at
                  is set and sent_at within last 7 days. Uses bounced_at, not
                  resend_status, because bounced_at is the canonical signal that
                  any bounce path (Resend webhook, suppression sweep, manual entry)
                  has classified the contact as undeliverable.
    Denominator : COUNT(DISTINCT contact_id) from outreach_drafts where sent_at
                  is within last 7 days. Dedupes follow-up sends so a contact who
                  received Steps 1, 2, and 3 contributes 1 to denominator, not 3.

    Companion warning: an all-time contact-scoped deliverability snapshot is
    logged at WARNING when it exceeds 5%. This surfaces chronic list-quality
    debt without blocking forward sends (the 7d window is the enforcing gate).

    Safe to call even if no sends exist: empty window => passes.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        # 7d window — dedupe by contact_id
        sends_rows = (
            db.client.table("outreach_drafts")
            .select("contact_id")
            .not_.is_("sent_at", "null")
            .gte("sent_at", cutoff)
            .execute()
            .data
        )
        # Only count hard bounces (bounce_type='hard' or NULL for pre-063 rows).
        # Soft/Transient bounces are not permanent delivery failures and must not
        # inflate the gate — they suppress sequences temporarily, not addresses.
        bounces_rows = (
            db.client.table("outreach_drafts")
            .select("contact_id")
            .not_.is_("bounced_at", "null")
            .gte("sent_at", cutoff)
            .or_("bounce_type.is.null,bounce_type.eq.hard")
            .execute()
            .data
        )
        send_contacts = {r["contact_id"] for r in sends_rows if r.get("contact_id")}
        bounce_contacts = {r["contact_id"] for r in bounces_rows if r.get("contact_id")}

        # All-time deliverability snapshot — informational, non-blocking
        try:
            all_bounced = (
                db.client.table("contacts")
                .select("id", count="exact")
                .eq("outreach_state", "bounced")
                .execute()
                .count
                or 0
            )
            all_sent = (
                db.client.table("contacts")
                .select("id", count="exact")
                .in_(
                    "outreach_state",
                    [
                        "touch_1_sent",
                        "touch_2_sent",
                        "touch_3_sent",
                        "bounced",
                        "replied",
                        "opted_out",
                    ],
                )
                .execute()
                .count
                or 0
            )
            if all_sent:
                all_time_rate = all_bounced / all_sent
                if all_time_rate > 0.05:
                    logger.warning(
                        "DELIVERABILITY SNAPSHOT (all-time, contact-scoped): "
                        "%d bounced / %d sent = %.2f%% — exceeds 5%% advisory threshold. "
                        "List hygiene work indicated.",
                        all_bounced,
                        all_sent,
                        all_time_rate * 100,
                    )
        except Exception as e:
            logger.warning("All-time deliverability snapshot failed: %s", e)

        send_count = len(send_contacts)
        bounce_count = len(bounce_contacts)

        if send_count == 0:
            _log_assertion(
                db,
                None,
                None,
                "bounce_rate_ok",
                True,
                "no contacts sent in 7d window — rate undefined, passing",
                assertion_context,
            )
            return

        rate = bounce_count / send_count
        threshold = _max_bounce_rate()
        detail = (
            f"7d contact-scoped: {bounce_count} bounced / {send_count} sent = {rate:.2%} "
            f"(threshold {threshold:.0%})"
        )
        if rate > threshold:
            _log_assertion(db, None, None, "bounce_rate_ok", False, detail, assertion_context)
            _alert(
                f":rotating_light: BOUNCE RATE GATE TRIGGERED — {detail}. "
                f"All sends blocked until rate drops below {threshold:.0%}."
            )
            raise AssertionFailure("bounce_rate_ok", detail)

        _log_assertion(db, None, None, "bounce_rate_ok", True, detail, assertion_context)

    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning(
            "assert_bounce_rate_ok could not compute rate: %s — passing to avoid false block", e
        )


def run_pre_send_assertions(
    db: Any,
    contact: dict,
    company: dict,
    sender_email: str,
    daily_cap: int = 125,
    cooldown_days: int = COMPANY_COOLDOWN_DAYS,
    sequence_step: int = 1,
    assertion_context: str = "draft_gen",
    current_draft_id: str | None = None,
    draft_id: str | None = None,
) -> None:
    """Run all pre-send invariants. Raises AssertionFailure on first violation.

    assertion_context must be 'draft_gen' (outreach.py, before draft creation —
    advisory) or 'send_path' (engagement.py, before delivery — authoritative).
    Draft-generation assertions advise which contacts are ready to draft.
    Send-path assertions are the authoritative runtime governance gate: a failure
    here blocks delivery and rolls back the atomic sent_at claim.

    For follow-up steps (sequence_step ≥ 2) two additional checks run:
    - prior_step_sent: the preceding step was actually delivered
    - minimum_step_gap: at least MIN_STEP_GAP_DAYS since the preceding send

    bounce_rate_ok is a system-level gate that runs once per send invocation
    in send_path context only — it checks the 7-day rolling bounce rate and
    blocks the entire send batch if the rate exceeds MAX_BOUNCE_RATE.
    """
    # Hard gate: reject drafts that were rejected/dispatch_failed — send_path only.
    # This must run first so a rejected draft can never reach Resend regardless of
    # what is in the outbound_queue.
    _draft_id = draft_id or current_draft_id
    if assertion_context == "send_path" and _draft_id:
        assert_not_rejected(db, _draft_id, assertion_context)

    # System-level gate: check rolling bounce rate before per-contact checks.
    # Only enforced in send_path — not advisory in draft_gen.
    if assertion_context == "send_path":
        assert_bounce_rate_ok(db, assertion_context)

    assert_email_deliverable(db, contact, assertion_context)
    assert_email_status_verified(db, contact, assertion_context)
    assert_email_name_consistent(db, contact, assertion_context)
    assert_outreach_eligible(db, contact, assertion_context)
    assert_persona_target(db, contact, assertion_context)
    assert_no_recent_company_send(
        db,
        contact,
        company,
        days=cooldown_days,
        assertion_context=assertion_context,
        current_draft_id=current_draft_id,
    )
    assert_sender_under_daily_cap(db, sender_email, daily_cap, assertion_context)
    # Follow-up sequence guards
    assert_prior_step_sent(db, contact, sequence_step, assertion_context)
    assert_minimum_step_gap(db, contact, sequence_step, assertion_context)
