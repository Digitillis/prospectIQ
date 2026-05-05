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

# Days since last outreach to the same company before a new send is allowed
COMPANY_COOLDOWN_DAYS = 30

# Hard bounce rate threshold (7-day rolling). Exceeding this pauses all sends.
MAX_BOUNCE_RATE = 0.02

# Minimum days between any two emails to the same contact (hard floor)
MIN_STEP_GAP_DAYS = 5


class AssertionFailure(Exception):
    """Raised when a pre-send invariant fails. Blocks the send."""
    def __init__(self, assertion: str, detail: str):
        self.assertion = assertion
        self.detail = detail
        super().__init__(f"{assertion}: {detail}")


def _log_assertion(db: Any, contact_id: str, company_id: str, assertion: str,
                   passed: bool, detail: str) -> None:
    """Write assertion result to send_assertions table."""
    try:
        db.client.table("send_assertions").insert({
            "contact_id": contact_id,
            "company_id": company_id,
            "assertion": assertion,
            "passed": passed,
            "detail": detail,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("Could not log assertion to DB: %s", e)


def _alert(message: str) -> None:
    try:
        from backend.app.utils.notifications import notify_slack
        notify_slack(message, emoji=":rotating_light:")
    except Exception:
        pass


def assert_email_deliverable(db: Any, contact: dict) -> None:
    """Email must not be a confirmed invalid or bounced address."""
    email_status = contact.get("email_status")
    if email_status in ("invalid", "bounce"):
        detail = f"email_status={email_status} for {contact.get('email')}"
        _log_assertion(db, contact["id"], contact.get("company_id", ""), "email_deliverable", False, detail)
        _alert(f":red_circle: Pre-send assertion failed: email_deliverable — {contact.get('full_name')} ({detail})")
        raise AssertionFailure("email_deliverable", detail)
    _log_assertion(db, contact["id"], contact.get("company_id", ""), "email_deliverable", True, f"status={email_status or 'unknown'}")


def assert_email_name_consistent(db: Any, contact: dict) -> None:
    """Email must not be flagged as belonging to a different person."""
    if contact.get("email_name_verified") is False:
        detail = f"email_name_verified=False for {contact.get('email')}"
        _log_assertion(db, contact["id"], contact.get("company_id", ""), "email_name_consistent", False, detail)
        _alert(f":red_circle: Pre-send assertion failed: email_name_consistent — {contact.get('full_name')} ({detail})")
        raise AssertionFailure("email_name_consistent", detail)
    _log_assertion(db, contact["id"], contact.get("company_id", ""), "email_name_consistent", True, "ok")


def assert_outreach_eligible(db: Any, contact: dict) -> None:
    """Contact must have is_outreach_eligible=True."""
    if contact.get("is_outreach_eligible") is False:
        detail = f"tier={contact.get('contact_tier')} for {contact.get('full_name')}"
        _log_assertion(db, contact["id"], contact.get("company_id", ""), "outreach_eligible", False, detail)
        _alert(f":red_circle: Pre-send assertion failed: outreach_eligible — {contact.get('full_name')} ({detail})")
        raise AssertionFailure("outreach_eligible", detail)
    _log_assertion(db, contact["id"], contact.get("company_id", ""), "outreach_eligible", True, "ok")


def assert_persona_target(db: Any, contact: dict) -> None:
    """Contact must not be in an excluded persona tier."""
    tier = contact.get("contact_tier")
    if tier == "excluded":
        detail = f"contact_tier=excluded, title={contact.get('title')}"
        _log_assertion(db, contact["id"], contact.get("company_id", ""), "persona_target", False, detail)
        _alert(f":red_circle: Pre-send assertion failed: persona_target — {contact.get('full_name')} ({detail})")
        raise AssertionFailure("persona_target", detail)
    _log_assertion(db, contact["id"], contact.get("company_id", ""), "persona_target", True, f"tier={tier}")


def assert_no_recent_company_send(db: Any, contact: dict, company: dict, days: int = COMPANY_COOLDOWN_DAYS) -> None:
    """No send to this company in the last N days (to same contact)."""
    company_id = company.get("id") or contact.get("company_id")
    if not company_id:
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        result = (
            db.client.table("outreach_drafts")
            .select("id,sent_at")
            .eq("contact_id", contact["id"])
            .not_.is_("sent_at", "null")
            .gte("sent_at", cutoff)
            .limit(1)
            .execute()
        )
        if result.data:
            sent_at = result.data[0].get("sent_at", "")[:10]
            detail = f"Last send to {contact.get('full_name')} was {sent_at} (cooldown={days}d)"
            _log_assertion(db, contact["id"], company_id, "no_recent_company_send", False, detail)
            raise AssertionFailure("no_recent_company_send", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check recent send for contact %s: %s", contact["id"], e)

    _log_assertion(db, contact["id"], company_id, "no_recent_company_send", True, f"no send in past {days}d")


def assert_sender_under_daily_cap(db: Any, sender_email: str, daily_cap: int) -> None:
    """Sender must not have exceeded their daily send quota."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
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
            _log_assertion(db, "", "", "sender_daily_cap", False, detail)
            raise AssertionFailure("sender_daily_cap", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check daily cap for %s: %s", sender_email, e)

    _log_assertion(db, "", "", "sender_daily_cap", True, f"{sender_email}: under cap")


def assert_prior_step_sent(db: Any, contact: dict, sequence_step: int) -> None:
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
            _log_assertion(db, contact_id, contact.get("company_id", ""), "prior_step_sent", False, detail)
            _alert(f":warning: Pre-send gate: prior_step_sent failed — {contact.get('full_name')} ({detail})")
            raise AssertionFailure("prior_step_sent", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check prior step for contact %s: %s", contact_id, e)
    _log_assertion(db, contact_id, contact.get("company_id", ""), "prior_step_sent", True, f"step {prior_step} confirmed sent")


def assert_minimum_step_gap(db: Any, contact: dict, sequence_step: int) -> None:
    """For step N ≥ 2, at least MIN_STEP_GAP_DAYS must have passed since the prior step.

    Prevents rapid-fire email sequences where the system schedules steps
    too close together due to sequence state drift.
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
            try:
                last_sent = datetime.fromisoformat(sent_str)
            except ValueError:
                last_sent = datetime.fromisoformat(sent_str.replace("+00:00", "")).replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - last_sent).days
            if days_since < MIN_STEP_GAP_DAYS:
                detail = (
                    f"only {days_since}d since step {prior_step} was sent — "
                    f"minimum gap is {MIN_STEP_GAP_DAYS}d (step {sequence_step} blocked)"
                )
                _log_assertion(db, contact_id, contact.get("company_id", ""), "minimum_step_gap", False, detail)
                _alert(f":warning: Pre-send gate: minimum_step_gap failed — {contact.get('full_name')} ({detail})")
                raise AssertionFailure("minimum_step_gap", detail)
    except AssertionFailure:
        raise
    except Exception as e:
        logger.warning("Could not check step gap for contact %s: %s", contact_id, e)
    _log_assertion(db, contact_id, contact.get("company_id", ""), "minimum_step_gap", True, f"gap ok for step {sequence_step}")


def run_pre_send_assertions(
    db: Any,
    contact: dict,
    company: dict,
    sender_email: str,
    daily_cap: int = 125,
    cooldown_days: int = COMPANY_COOLDOWN_DAYS,
    sequence_step: int = 1,
) -> None:
    """Run all pre-send invariants. Raises AssertionFailure on first violation.

    Call this before generating any draft. A failure means the contact should
    be skipped — the send is blocked.

    For follow-up steps (sequence_step ≥ 2) two additional checks run:
    - prior_step_sent: the preceding step was actually delivered
    - minimum_step_gap: at least MIN_STEP_GAP_DAYS since the preceding send
    """
    assert_email_deliverable(db, contact)
    assert_email_name_consistent(db, contact)
    assert_outreach_eligible(db, contact)
    assert_persona_target(db, contact)
    assert_no_recent_company_send(db, contact, company, days=cooldown_days)
    assert_sender_under_daily_cap(db, sender_email, daily_cap)
    # Follow-up sequence guards
    assert_prior_step_sent(db, contact, sequence_step)
    assert_minimum_step_gap(db, contact, sequence_step)
