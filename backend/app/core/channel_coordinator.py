"""Cross-channel coordination — prevents double-bombing prospects.

Rule: One channel at a time per contact, with cooldown between switches.

Channel priority:
1. If contact has LinkedIn URL + no email → LinkedIn only
2. If contact has email + no LinkedIn → Email only
3. If both: Email preferred (higher response rate for mfg ops ICP)

Cooldown rules:
- LinkedIn connection sent → no email for 7 days
- LinkedIn DM sequence complete, no response → email after 14 days
- Email sequence complete → never switch back to LinkedIn
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

LINKEDIN_TO_EMAIL_COOLDOWN_DAYS = 0  # Email allowed immediately alongside LinkedIn
DM_COMPLETE_TO_EMAIL_COOLDOWN_DAYS = 14
ACTIVITY_COOLDOWN_HOURS = 48

def _company_lock_business_days() -> int:
    import os
    v = os.environ.get("COMPANY_LOCK_BUSINESS_DAYS")
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    try:
        from backend.app.core.limits import _load
        cfg = _load() or {}
        return int((cfg.get("send_limits") or {}).get("company_lock_business_days", 5))
    except Exception:
        return 5

COMPANY_LOCK_BUSINESS_DAYS: int = 5  # module-level alias; live value from _company_lock_business_days()


def get_active_channel(db: Database, contact_id: str) -> tuple[str, str | None]:
    """Determine which channel is active for a contact.

    Returns:
        Tuple of (active_channel, reason).
        active_channel: "linkedin", "email", "both", or "none"
        reason: Human-readable explanation
    """
    # Get contact data
    contact_result = (
        db.client.table("contacts").select("*").eq("id", contact_id).execute()
    )
    if not contact_result.data:
        return ("none", "contact_not_found")

    contact = contact_result.data[0]
    has_linkedin = bool(contact.get("linkedin_url"))
    has_email = bool(contact.get("email"))

    if not has_linkedin and not has_email:
        return ("none", "no_contact_channels")
    if has_linkedin and not has_email:
        return ("linkedin", "linkedin_only_channel")
    if has_email and not has_linkedin:
        return ("email", "email_only_channel")

    # Both channels available — check interaction history
    now = datetime.now(timezone.utc)

    # Check for recent LinkedIn activity
    linkedin_interactions = (
        db.client.table("interactions")
        .select("type, created_at")
        .eq("contact_id", contact_id)
        .in_("type", ["linkedin_connection", "linkedin_message"])
        .order("created_at", desc=True)
        .limit(5)
        .execute()
        .data
    )

    # Check for recent email activity
    email_interactions = (
        db.client.table("interactions")
        .select("type, created_at")
        .eq("contact_id", contact_id)
        .in_("type", ["email_sent", "email_opened", "email_replied"])
        .order("created_at", desc=True)
        .limit(5)
        .execute()
        .data
    )

    # Check completed email sequences
    completed_email_seqs = (
        db.client.table("engagement_sequences")
        .select("completed_at")
        .eq("contact_id", contact_id)
        .eq("status", "completed")
        .not_.is_("completed_at", "null")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
        .data
    )

    # Rule: If email sequence completed → never go back to LinkedIn
    if completed_email_seqs:
        return ("email", "email_sequence_completed_no_linkedin_return")

    # Rule: If LinkedIn activity in the last 7 days → block email
    if linkedin_interactions:
        last_linkedin = datetime.fromisoformat(
            linkedin_interactions[0]["created_at"].replace("Z", "+00:00")
        )
        days_since = (now - last_linkedin).days
        if days_since < LINKEDIN_TO_EMAIL_COOLDOWN_DAYS:
            remaining = LINKEDIN_TO_EMAIL_COOLDOWN_DAYS - days_since
            return (
                "linkedin",
                f"linkedin_active_email_blocked_{remaining}d_remaining",
            )

    # Rule: If email activity in last 14 days → block LinkedIn
    if email_interactions:
        last_email = datetime.fromisoformat(
            email_interactions[0]["created_at"].replace("Z", "+00:00")
        )
        days_since = (now - last_email).days
        if days_since < DM_COMPLETE_TO_EMAIL_COOLDOWN_DAYS:
            return ("email", "email_active_linkedin_blocked")

    # No recent activity on either channel — default to email (higher response
    # rate for manufacturing ops ICP; LinkedIn is supplementary)
    if has_email:
        return ("email", "both_available_email_preferred")
    return ("linkedin", "both_available_linkedin_fallback")


def can_use_channel(
    db: Database, contact_id: str, channel: str
) -> tuple[bool, str | None]:
    """Check if a specific channel can be used for a contact.

    Args:
        db: Database instance
        contact_id: Contact ID
        channel: "email" or "linkedin"

    Returns:
        Tuple of (allowed, reason_if_blocked).
    """
    # Warm intro collision detection — never send cold outreach to a contact
    # with an active warm intro in progress.
    try:
        contact_result = (
            db.client.table("contacts")
            .select("linkedin_status")
            .eq("id", contact_id)
            .execute()
        )
        if contact_result.data:
            linkedin_status = contact_result.data[0].get("linkedin_status", "") or ""
            if "warm" in linkedin_status.lower():
                return (False, f"warm_intro_in_progress:{linkedin_status}")
    except Exception:
        pass  # Graceful degradation — don't block on DB errors

    active, reason = get_active_channel(db, contact_id)

    if active == "none":
        return (False, reason)
    if active == "both":
        return (True, None)
    if active == channel:
        return (True, None)

    return (False, f"channel_blocked:{reason}")


def assign_channel(
    db: Database,
    contact_id: str,
    company: dict = None,
    contact: dict = None,
) -> tuple[str, str]:
    """Auto-assign the optimal outreach channel based on Apollo signals.

    Decision tree:
    1. No LinkedIn URL → email only
    2. No email (has_email=False) → LinkedIn only
    3. Both available:
       a. Seniority VP/C-suite + employee_count > 200 → LinkedIn
       b. Seniority Director/Manager + employee_count < 150 → email
       c. headcount_growth_6m > 0.05 → LinkedIn (growing = active LI users)
       d. headcount_growth_6m < -0.05 → email (shrinking = too busy for LI)
       e. Default → LinkedIn (warmer channel)
    """
    if contact is None:
        contact_result = db.client.table("contacts").select("*").eq("id", contact_id).execute()
        if not contact_result.data:
            return ("email", "contact_not_found_defaulting_to_email")
        contact = contact_result.data[0]

    has_linkedin = bool(contact.get("linkedin_url"))
    has_email = contact.get("has_email", bool(contact.get("email")))

    if not has_linkedin:
        return ("email", "no_linkedin_url")
    if not has_email:
        return ("linkedin", "no_email_available")

    # Both channels available — use Apollo signals to decide
    if company is None:
        company_id = contact.get("company_id")
        if company_id:
            company = db.get_company(company_id)

    employee_count = (company.get("employee_count") or 0) if company else 0
    headcount_growth = (company.get("headcount_growth_6m") or 0.0) if company else 0.0
    seniority = (contact.get("seniority") or "").lower()

    if seniority in ("vp", "c_suite", "c-suite", "owner", "founder", "partner") and employee_count > 200:
        return ("linkedin", "vp_csuite_large_company")
    if seniority in ("director", "manager") and employee_count < 150:
        return ("email", "director_manager_small_company")
    if headcount_growth > 0.05:
        return ("linkedin", "growing_company")
    if headcount_growth < -0.05:
        return ("email", "shrinking_company")

    return ("email", "default_email_higher_response_rate")


def _business_days_ago(n: int) -> datetime:
    """Return the datetime that was n business days (Mon-Fri) ago."""
    now = datetime.now(timezone.utc)
    count = 0
    d = now
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Mon=0 … Fri=4
            count += 1
    return d


def is_company_locked(
    db: Database,
    company_id: str,
    exclude_contact_id: str = None,
) -> tuple[bool, str | None]:
    """Check if any contact at this company was contacted in the last 5 business days.

    Prevents multi-contact collision (two contacts at the same company getting
    outreach in the same week). Uses business days so weekends don't eat into
    the window.
    """
    now = datetime.now(timezone.utc)
    cutoff = _business_days_ago(_company_lock_business_days()).isoformat()

    try:
        # Only count actual outreach touches — not status changes or system notes
        interactions = (
            db.client.table("interactions")
            .select("contact_id, type, created_at")
            .eq("company_id", company_id)
            .in_("type", [
                "linkedin_connection", "linkedin_message",
                "email_sent", "email_replied",
            ])
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
            .data
        )
    except Exception:
        return (False, None)  # Graceful degradation

    for interaction in interactions:
        if exclude_contact_id and interaction.get("contact_id") == exclude_contact_id:
            continue
        created_at_raw = interaction.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            days_ago = (now - created_at).days
        except (ValueError, AttributeError):
            days_ago = 0
        return (True, f"another contact reached {days_ago}d ago — retry after {_company_lock_business_days()} business days")

    return (False, None)


def get_company_traction(
    db: Database,
    company_id: str,
    exclude_contact_id: str = None,
) -> dict:
    """Check if any contact at this company has shown positive engagement signals.

    Used to surface a warning in the approval queue when a step-1 cold outreach
    is pending for a company where another contact is already warm. The reviewer
    can then decide whether to proceed (new stakeholder) or hold (duplicate effort).

    Returns:
        {
            "has_traction": bool,
            "signals": list of human-readable signal strings,
            "contact_name": str (name of the contact with traction, if any),
            "contact_id": str,
        }
    """
    result: dict = {"has_traction": False, "signals": [], "contact_name": "", "contact_id": ""}

    try:
        # Get all contact IDs at this company
        contacts_result = (
            db.client.table("contacts")
            .select("id, full_name, reply_sentiment")
            .eq("company_id", company_id)
            .execute()
        )
        contacts = contacts_result.data or []
    except Exception:
        return result

    if not contacts:
        return result

    contact_map = {c["id"]: c for c in contacts}
    all_contact_ids = [c["id"] for c in contacts]
    check_ids = [cid for cid in all_contact_ids if cid != exclude_contact_id]
    if not check_ids:
        return result

    signals: list[str] = []
    traction_contact_id = ""
    traction_contact_name = ""

    # Check 1: positive reply sentiment on any contact
    for c in contacts:
        if c["id"] == exclude_contact_id:
            continue
        sentiment = (c.get("reply_sentiment") or "").lower()
        if sentiment and sentiment not in ("auto_reply_retired", "auto_reply", "bounced", "unsubscribed", ""):
            signals.append(f"{c.get('full_name', 'A contact')} replied ({sentiment})")
            traction_contact_id = c["id"]
            traction_contact_name = c.get("full_name", "")

    # Check 2: email opens or clicks in interactions table
    try:
        eng_result = (
            db.client.table("interactions")
            .select("contact_id, type, created_at")
            .in_("contact_id", check_ids)
            .in_("type", ["email_opened", "email_clicked", "email_replied"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        eng_rows = eng_result.data or []
    except Exception:
        eng_rows = []

    # Aggregate: count opens/clicks per contact
    from collections import defaultdict
    opens_by_contact: dict[str, int] = defaultdict(int)
    clicks_by_contact: dict[str, int] = defaultdict(int)
    for row in eng_rows:
        cid = row.get("contact_id", "")
        if row["type"] == "email_opened":
            opens_by_contact[cid] += 1
        elif row["type"] == "email_clicked":
            clicks_by_contact[cid] += 1

    for cid, count in clicks_by_contact.items():
        if count >= 1:
            name = contact_map.get(cid, {}).get("full_name", "A contact")
            signals.append(f"{name} clicked a link ({count}x)")
            if not traction_contact_id:
                traction_contact_id, traction_contact_name = cid, name

    for cid, count in opens_by_contact.items():
        if count >= 2 and cid not in clicks_by_contact:
            name = contact_map.get(cid, {}).get("full_name", "A contact")
            signals.append(f"{name} opened {count}x")
            if not traction_contact_id:
                traction_contact_id, traction_contact_name = cid, name

    if signals:
        result["has_traction"] = True
        result["signals"] = signals
        result["contact_id"] = traction_contact_id
        result["contact_name"] = traction_contact_name

    return result


def has_recent_activity(
    db: Database,
    contact_id: str,
    hours: int = ACTIVITY_COOLDOWN_HOURS,
) -> tuple[bool, str | None]:
    """Check if this contact had any interaction in the last N hours.

    Prevents rapid-fire touches. If found, delay next touch by 3 days.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).isoformat()

    try:
        # Only count actual outreach touches — not status changes or system notes
        interactions = (
            db.client.table("interactions")
            .select("type, created_at")
            .eq("contact_id", contact_id)
            .in_("type", [
                "linkedin_connection", "linkedin_message",
                "email_sent", "email_replied",
            ])
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        return (False, None)

    if not interactions:
        return (False, None)

    last = interactions[0]
    try:
        created_at = datetime.fromisoformat(last["created_at"].replace("Z", "+00:00"))
        hours_ago = int((now - created_at).total_seconds() / 3600)
        return (True, f"{last['type']} {hours_ago}h ago — next touch in 3 days")
    except (ValueError, AttributeError, KeyError):
        return (True, "recent activity detected")
