"""Outreach Coordinator — orchestrates state transitions and multi-channel coordination.

The coordinator is the single authority on advancing a contact through the outreach
pipeline.  It handles:

  - Positive reply → flag for SDR, update company status
  - Demo scheduled → lock company as pending
  - Nurture graduation → contacts that exhausted 6 touches with no reply
  - Stalled contact detection → for human review
  - Action queue → what the SDR needs to act on today

State machine (simplified):
    new → sequenced → touch_1_sent → … → touch_6_sent
                                              │
                                  ┌───────────┼──────────────┐
                                  ▼           ▼              ▼
                               replied     nurture     not_interested

Usage:
    from backend.app.core.database import Database
    from backend.app.core.outreach_coordinator import OutreachCoordinator

    db = Database()
    coordinator = OutreachCoordinator(db)

    # Move a contact to the next logical state
    result = await coordinator.advance_contact(contact_id)

    # Handle an inbound positive reply
    result = await coordinator.handle_positive_reply(contact_id, reply_text="Yes, let's chat")

    # Morning review
    queue   = await coordinator.get_action_queue(limit=20)
    stalled = await coordinator.get_stalled_contacts(days_stalled=5)
    summary = coordinator.get_outreach_summary()
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.app.core.database import Database

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


# Contact states used in the state machine
_TOUCH_STATES = [
    "touch_1_sent",
    "touch_2_sent",
    "touch_3_sent",
    "touch_4_sent",
    "touch_5_sent",
    "touch_6_sent",
]

_TERMINAL_STATES = {
    "replied",
    "replied_positive",
    "replied_negative",
    "demo_scheduled",
    "not_interested",
    "bounced",
    "unsubscribed",
    "disqualified",
    "nurture",
}


class OutreachCoordinator:
    """Orchestrates multi-channel outreach state transitions."""

    def __init__(
        self,
        db: Database,
        instantly_client=None,   # optional — pass when you need to call Instantly API
        linkedin_tracker=None,   # optional LinkedInTracker instance
        sequence_router=None,    # optional SequenceRouter / SequenceTemplateManager
    ):
        self.db = db
        self.instantly_client = instantly_client
        self.linkedin_tracker = linkedin_tracker
        self.sequence_router = sequence_router

    # ------------------------------------------------------------------
    # Core state transitions
    # ------------------------------------------------------------------

    async def advance_contact(self, contact_id: str) -> dict:
        """Move a contact to the next appropriate action based on current state.

        Decision logic:
          - Currently in a touch state, no reply after N days → queue next touch
          - Currently in final touch (touch_6_sent), no reply → move to nurture
          - Replied positive → flag for human follow-up (no automated action)
          - Terminal state → no-op, return current state

        Args:
            contact_id: Contact UUID.

        Returns:
            Dict with 'contact_id', 'action', 'from_state', 'to_state'.
        """
        contact = self._get_contact(contact_id)
        if not contact:
            return {"contact_id": contact_id, "action": "not_found", "error": "Contact not found"}

        current_state = contact.get("outreach_state") or "new"

        # Terminal states — nothing to do
        if current_state in _TERMINAL_STATES:
            return {
                "contact_id": contact_id,
                "action": "no_op",
                "from_state": current_state,
                "to_state": current_state,
                "reason": "Contact is in terminal state",
            }

        # Exhausted all touches with no reply → nurture
        if current_state == "touch_6_sent":
            self.db.update_contact_state(
                contact_id=contact_id,
                new_state="nurture",
                from_state=current_state,
                channel="email",
                metadata={"reason": "6 touches sent, no reply"},
            )
            logger.info(f"[coordinator] {contact_id[:8]} → nurture (6 touches exhausted)")
            return {
                "contact_id": contact_id,
                "action": "moved_to_nurture",
                "from_state": current_state,
                "to_state": "nurture",
            }

        # In a mid-sequence touch state — nothing automated to do here
        # (Instantly handles the touch schedule; this method is for edge cases)
        if current_state in _TOUCH_STATES:
            return {
                "contact_id": contact_id,
                "action": "in_sequence",
                "from_state": current_state,
                "to_state": current_state,
                "reason": "Sequence active — Instantly manages next touch",
            }

        return {
            "contact_id": contact_id,
            "action": "no_op",
            "from_state": current_state,
            "to_state": current_state,
        }

    async def handle_positive_reply(
        self,
        contact_id: str,
        reply_text: str,
    ) -> dict:
        """Mark a contact as replied positive and flag for SDR follow-up.

        Updates the contact's outreach_state to 'replied_positive',
        updates the parent company's status to 'replied', and logs
        the reply interaction.

        Args:
            contact_id: Contact UUID.
            reply_text: The reply content (stored for context).

        Returns:
            Dict with transition details.
        """
        contact = self._get_contact(contact_id)
        if not contact:
            return {"contact_id": contact_id, "error": "Contact not found"}

        from_state = contact.get("outreach_state") or "unknown"
        company_id = contact.get("company_id")

        # Transition contact state
        self.db.update_contact_state(
            contact_id=contact_id,
            new_state="replied_positive",
            from_state=from_state,
            channel="email",
            instantly_event="reply",
            metadata={"reply_snippet": reply_text[:500]},
            extra_updates={
                "last_reply_at": _now_iso(),
                "reply_count": (contact.get("reply_count") or 0) + 1,
            },
        )

        # Log the interaction
        self.db.insert_interaction({
            "contact_id": contact_id,
            "company_id": company_id,
            "interaction_type": "email_reply",
            "channel": "email",
            "direction": "inbound",
            "notes": reply_text[:1000],
            "outcome": "positive",
            "created_at": _now_iso(),
        })

        # Bump company status to replied if it's in an earlier state
        if company_id:
            company = self.db.get_company(company_id)
            if company:
                company_status = company.get("status", "")
                if company_status not in {"replied", "demo_scheduled", "customer", "closed_won"}:
                    self.db.update_company(company_id, {"status": "replied"})
                    logger.info(f"[coordinator] Company {company_id[:8]} status → replied")

        logger.info(f"[coordinator] {contact_id[:8]} → replied_positive (flagged for SDR)")
        return {
            "contact_id": contact_id,
            "action": "flagged_for_sdr",
            "from_state": from_state,
            "to_state": "replied_positive",
        }

    async def handle_demo_scheduled(
        self,
        contact_id: str,
        demo_date: str,
    ) -> dict:
        """Update a contact and their company when a demo is confirmed.

        Args:
            contact_id: Contact UUID.
            demo_date: ISO date string of the scheduled demo.

        Returns:
            Dict with transition details.
        """
        contact = self._get_contact(contact_id)
        if not contact:
            return {"contact_id": contact_id, "error": "Contact not found"}

        from_state = contact.get("outreach_state") or "unknown"
        company_id = contact.get("company_id")

        self.db.update_contact_state(
            contact_id=contact_id,
            new_state="demo_scheduled",
            from_state=from_state,
            channel="email",
            metadata={"demo_date": demo_date},
            extra_updates={"demo_scheduled_at": demo_date},
        )

        self.db.insert_interaction({
            "contact_id": contact_id,
            "company_id": company_id,
            "interaction_type": "demo_scheduled",
            "channel": "email",
            "direction": "inbound",
            "notes": f"Demo scheduled for {demo_date}",
            "outcome": "demo_booked",
            "created_at": _now_iso(),
        })

        if company_id:
            self.db.update_company(company_id, {"status": "demo_scheduled"})
            logger.info(f"[coordinator] Company {company_id[:8]} status → demo_scheduled")

        logger.info(f"[coordinator] {contact_id[:8]} → demo_scheduled ({demo_date})")
        return {
            "contact_id": contact_id,
            "action": "demo_confirmed",
            "from_state": from_state,
            "to_state": "demo_scheduled",
            "demo_date": demo_date,
        }

    async def handle_negative_reply(
        self,
        contact_id: str,
        reply_text: str = "",
    ) -> dict:
        """Mark a contact as not interested and log the reply.

        Args:
            contact_id: Contact UUID.
            reply_text: The reply content for context.

        Returns:
            Dict with transition details.
        """
        contact = self._get_contact(contact_id)
        if not contact:
            return {"contact_id": contact_id, "error": "Contact not found"}

        from_state = contact.get("outreach_state") or "unknown"
        company_id = contact.get("company_id")

        self.db.update_contact_state(
            contact_id=contact_id,
            new_state="not_interested",
            from_state=from_state,
            channel="email",
            instantly_event="reply_negative",
            metadata={"reply_snippet": reply_text[:500]},
        )

        self.db.insert_interaction({
            "contact_id": contact_id,
            "company_id": company_id,
            "interaction_type": "email_reply",
            "channel": "email",
            "direction": "inbound",
            "notes": reply_text[:1000],
            "outcome": "negative",
            "created_at": _now_iso(),
        })

        logger.info(f"[coordinator] {contact_id[:8]} → not_interested")
        return {
            "contact_id": contact_id,
            "action": "marked_not_interested",
            "from_state": from_state,
            "to_state": "not_interested",
        }

    # ------------------------------------------------------------------
    # Action queue & stalled contacts
    # ------------------------------------------------------------------

    async def get_action_queue(self, limit: int = 20) -> list[dict]:
        """Return contacts requiring human action today.

        Surfaces:
          - Positive replies not yet followed up
          - Demo scheduled but no outcome logged (within 48h)
          - High-priority contacts (score >= 70) in any touch state

        Args:
            limit: Maximum number of contacts to return.

        Returns:
            List of contact dicts enriched with 'action_reason'.
        """
        queue: list[dict] = []

        # 1. Positive replies awaiting SDR follow-up
        try:
            result = (
                self.db.client.table("contacts")
                .select("*, companies(name, domain, tier, status)")
                .eq("outreach_state", "replied_positive")
                .order("last_reply_at", desc=True)
                .limit(limit)
                .execute()
            )
            for c in result.data or []:
                c["action_reason"] = "Positive reply — needs SDR follow-up"
                queue.append(c)
        except Exception as exc:
            logger.warning(f"[coordinator] Could not fetch positive replies: {exc}")

        # 2. Demos scheduled without next step logged
        try:
            result = (
                self.db.client.table("contacts")
                .select("*, companies(name, domain, tier, status)")
                .eq("outreach_state", "demo_scheduled")
                .order("outreach_state_updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            for c in result.data or []:
                c["action_reason"] = "Demo scheduled — confirm prep / post-demo follow-up"
                queue.append(c)
        except Exception as exc:
            logger.warning(f"[coordinator] Could not fetch demo_scheduled contacts: {exc}")

        # Deduplicate and cap
        seen: set[str] = set()
        deduped = []
        for c in queue:
            if c["id"] not in seen:
                seen.add(c["id"])
                deduped.append(c)
        return deduped[:limit]

    async def get_stalled_contacts(self, days_stalled: int = 5) -> list[dict]:
        """Return contacts stuck in a touch state without progression.

        A contact is considered stalled if their outreach_state_updated_at is
        older than days_stalled AND they are still in an active touch state.
        This usually means a Instantly sync issue or a missed state transition.

        Args:
            days_stalled: Number of days without a state update to consider stalled.

        Returns:
            List of contact dicts with 'days_stalled' field appended.
        """
        cutoff = (_now_utc() - timedelta(days=days_stalled)).isoformat()
        stalled: list[dict] = []

        try:
            result = (
                self.db.client.table("contacts")
                .select(
                    "id, full_name, email, outreach_state, outreach_state_updated_at, "
                    "priority_score, company_id, companies(name)"
                )
                .in_("outreach_state", _TOUCH_STATES + ["sequenced"])
                .lt("outreach_state_updated_at", cutoff)
                .order("outreach_state_updated_at")
                .limit(100)
                .execute()
            )
            rows = result.data or []
        except Exception as exc:
            logger.warning(f"[coordinator] Could not fetch stalled contacts: {exc}")
            return []

        now = _now_utc()
        for row in rows:
            updated_at_raw = row.get("outreach_state_updated_at")
            if updated_at_raw:
                try:
                    updated_at = datetime.fromisoformat(
                        updated_at_raw.replace("Z", "+00:00")
                    )
                    days_since = (now - updated_at).days
                    row["days_stalled"] = days_since
                except Exception:
                    row["days_stalled"] = None
            else:
                row["days_stalled"] = None
            stalled.append(row)

        return stalled

    # ------------------------------------------------------------------
    # Pipeline summary
    # ------------------------------------------------------------------

    def get_outreach_summary(self, campaign_name: Optional[str] = None) -> dict:
        """Return pipeline counts by outreach state.

        Args:
            campaign_name: Optional filter to limit to one campaign.

        Returns:
            Dict with state counts and a 'total_active' key.
        """
        try:
            query = self.db.client.table("contacts").select(
                "outreach_state, companies(campaign_name)"
            )
            result = query.execute()
            rows = result.data or []
        except Exception as exc:
            logger.warning(f"[coordinator] Could not fetch outreach summary: {exc}")
            return {}

        if campaign_name:
            rows = [
                r for r in rows
                if (r.get("companies") or {}).get("campaign_name") == campaign_name
            ]

        counts: dict[str, int] = {}
        for row in rows:
            state = row.get("outreach_state") or "unknown"
            counts[state] = counts.get(state, 0) + 1

        active_states = set(_TOUCH_STATES) | {"sequenced"}
        total_active = sum(v for k, v in counts.items() if k in active_states)
        counts["total_active"] = total_active
        counts["replied_positive"] = counts.get("replied_positive", 0)
        counts["demo_scheduled"] = counts.get("demo_scheduled", 0)
        counts["nurture"] = counts.get("nurture", 0)

        return counts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_contact(self, contact_id: str) -> Optional[dict]:
        try:
            result = (
                self.db.client.table("contacts")
                .select(
                    "id, full_name, email, outreach_state, outreach_state_updated_at, "
                    "company_id, priority_score, reply_count, open_count, click_count, "
                    "last_reply_at, demo_scheduled_at"
                )
                .eq("id", contact_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            logger.warning(f"[coordinator] Failed to fetch contact {contact_id[:8]}: {exc}")
            return None
