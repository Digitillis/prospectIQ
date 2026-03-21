"""Cross-channel coordination — prevents double-bombing prospects.

Rule: One channel at a time per contact, with cooldown between switches.

Channel priority:
1. If contact has LinkedIn URL + no email → LinkedIn only
2. If contact has email + no LinkedIn → Email only
3. If both: Start with LinkedIn → fallback to email after cooldown

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

LINKEDIN_TO_EMAIL_COOLDOWN_DAYS = 7
DM_COMPLETE_TO_EMAIL_COOLDOWN_DAYS = 14


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

    # No recent activity on either channel — default to LinkedIn (warmer)
    if has_linkedin:
        return ("linkedin", "both_available_linkedin_preferred")
    return ("email", "both_available_email_fallback")


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
    active, reason = get_active_channel(db, contact_id)

    if active == "none":
        return (False, reason)
    if active == "both":
        return (True, None)
    if active == channel:
        return (True, None)

    return (False, f"channel_blocked:{reason}")
