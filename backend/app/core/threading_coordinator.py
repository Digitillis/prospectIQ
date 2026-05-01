"""Threading Coordinator — explicit state machine for multi-contact company outreach.

Replaces implicit threading state (inferred from draft queries) with a hard
company_outreach_state table. All threading decisions read and write this table.

Rules (hard limits — enforced here, not in the outreach agent heuristic):
  1. Max 2 contacts per company (with < 500 employees — single site)
  2. Min 5 business days between contact_1_sent and contact_2_queued
  3. contact_2 blocked if state is contact_1_engaged, paused, closed_*, or excluded
  4. Threading only for companies with PQS >= 65
  5. If any contact at the company replies, the company moves to paused immediately
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Hard limits
MIN_DAYS_BETWEEN_CONTACTS = 5
PQS_THREADING_THRESHOLD = 65
SMALL_COMPANY_EMPLOYEE_LIMIT = 500


def _business_days_since(dt: datetime) -> int:
    """Return number of business days (Mon-Fri) between dt and now."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    total_days = delta.days
    # Approximate: 5/7 of total days are business days
    return int(total_days * 5 / 7)


class ThreadingCoordinator:
    def __init__(self, db: Any):
        self._db = db

    def get_state(self, company_id: str) -> dict:
        """Get or create threading state for a company."""
        workspace_id = getattr(self._db, "workspace_id", None)
        try:
            q = self._db.client.table("company_outreach_state").select("*").eq("company_id", company_id)
            if workspace_id:
                q = q.eq("workspace_id", workspace_id)
            rows = q.limit(1).execute().data or []
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("Could not fetch threading state for %s: %s", company_id, e)

        # Create initial state
        return self._create_state(company_id, workspace_id)

    def _create_state(self, company_id: str, workspace_id: str | None) -> dict:
        row: dict = {"company_id": company_id, "state": "not_started"}
        if workspace_id:
            row["workspace_id"] = workspace_id
        try:
            result = self._db.client.table("company_outreach_state").insert(row).execute()
            return result.data[0] if result.data else row
        except Exception as e:
            logger.warning("Could not create threading state for %s: %s", company_id, e)
            return row

    def can_send_contact_1(self, company: dict) -> tuple[bool, str]:
        """Check if it's valid to send to a first contact at this company."""
        state = self.get_state(company["id"])
        current = state.get("state", "not_started")

        if current in ("paused", "closed_won", "closed_lost", "excluded"):
            return False, f"company state is {current}"
        if current in ("contact_1_sent", "contact_1_engaged",
                       "contact_2_queued", "contact_2_sent"):
            return False, f"contact_1 already sent (state={current})"
        return True, "ok"

    def can_send_contact_2(self, company: dict) -> tuple[bool, str]:
        """Check if it's valid to send to a second contact at this company."""
        state = self.get_state(company["id"])
        current = state.get("state", "not_started")

        # State must be contact_1_sent
        if current != "contact_1_sent":
            return False, f"state={current}, must be contact_1_sent"

        # Check employee count — no threading for small sites
        employee_count = company.get("employee_count") or 0
        if 0 < employee_count < SMALL_COMPANY_EMPLOYEE_LIMIT:
            return False, f"company too small for threading ({employee_count} employees)"

        # Check PQS threshold
        pqs = company.get("priority_score") or 0
        if pqs < PQS_THREADING_THRESHOLD:
            return False, f"PQS {pqs} below threading threshold {PQS_THREADING_THRESHOLD}"

        # Check minimum days between contacts
        sent_at_str = state.get("contact_1_sent_at")
        if sent_at_str:
            try:
                sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
                bdays = _business_days_since(sent_at)
                if bdays < MIN_DAYS_BETWEEN_CONTACTS:
                    return False, f"only {bdays} business days since contact_1 (min={MIN_DAYS_BETWEEN_CONTACTS})"
            except (ValueError, TypeError):
                pass

        return True, "ok"

    # F&B FSMA 204 tier prefixes — simultaneous dual-persona applies to these
    _FB_TIER_PREFIXES = ("fb_", "fb1", "fb2", "fb3", "fb4")

    # F&B quality/food-safety personas targeted as Contact 2 (simultaneous)
    _FB_CONTACT_2_PERSONAS = frozenset({
        "vp_food_safety", "regulatory_affairs_director",
        "vp_quality_food_safety", "director_quality_food_safety",
        "compliance_manager_fb",
    })
    # F&B operational personas targeted as Contact 1
    _FB_CONTACT_1_PERSONAS = frozenset({
        "vp_ops", "plant_manager", "coo", "director_ops", "maintenance_leader",
    })

    def assign_fb_simultaneous_contacts(
        self, company: dict, eligible_contacts: list[dict]
    ) -> tuple[str | None, str | None]:
        """For F&B FSMA 204 companies, assign ops persona as Contact 1 and
        quality/food-safety persona as Contact 2 to be sent simultaneously.

        Returns (contact_1_id, contact_2_id). Either may be None if no
        suitable contact exists for that slot.

        Only activates for fb_* tier companies. Non-F&B tiers return (None, None).
        """
        tier = str(company.get("tier") or "")
        if not any(tier.startswith(p) for p in self._FB_TIER_PREFIXES):
            return None, None

        contact_1 = next(
            (c for c in eligible_contacts
             if c.get("persona_type") in self._FB_CONTACT_1_PERSONAS),
            None,
        )
        contact_2 = next(
            (c for c in eligible_contacts
             if c.get("persona_type") in self._FB_CONTACT_2_PERSONAS),
            None,
        )
        c1_id = contact_1["id"] if contact_1 else None
        c2_id = contact_2["id"] if contact_2 else None
        logger.debug(
            "F&B simultaneous assign: company=%s tier=%s c1=%s(%s) c2=%s(%s)",
            company.get("id"), tier,
            (contact_1 or {}).get("persona_type"), c1_id,
            (contact_2 or {}).get("persona_type"), c2_id,
        )
        return c1_id, c2_id

    def record_contact_1_sent(self, company_id: str, contact_id: str, pqs: float | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        update: dict = {
            "state": "contact_1_sent",
            "contact_1_id": contact_id,
            "contact_1_sent_at": now,
            "updated_at": now,
        }
        if pqs is not None:
            update["pqs_at_start"] = pqs
        self._update_state(company_id, update)

    def record_contact_2_sent(self, company_id: str, contact_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._update_state(company_id, {
            "state": "contact_2_sent",
            "contact_2_id": contact_id,
            "contact_2_sent_at": now,
            "updated_at": now,
        })

    def record_reply(self, company_id: str, contact_id: str) -> None:
        """A contact replied — move company to engaged/paused based on thread position."""
        state = self.get_state(company_id)
        current = state.get("state", "not_started")
        now = datetime.now(timezone.utc).isoformat()

        new_state = "contact_1_engaged" if current in ("contact_1_sent",) else "paused"
        self._update_state(company_id, {
            "state": new_state,
            "last_reply_at": now,
            "last_reply_contact_id": contact_id,
            "updated_at": now,
        })
        logger.info("Company %s moved to %s after reply from %s", company_id, new_state, contact_id)

    def pause(self, company_id: str, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._update_state(company_id, {
            "state": "paused",
            "paused_reason": reason,
            "paused_at": now,
            "updated_at": now,
        })

    def close(self, company_id: str, outcome: str) -> None:
        """outcome: 'won' or 'lost'"""
        state = "closed_won" if outcome == "won" else "closed_lost"
        self._update_state(company_id, {
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def _update_state(self, company_id: str, data: dict) -> None:
        workspace_id = getattr(self._db, "workspace_id", None)
        try:
            q = self._db.client.table("company_outreach_state").update(data).eq("company_id", company_id)
            if workspace_id:
                q = q.eq("workspace_id", workspace_id)
            q.execute()
        except Exception as e:
            logger.warning("Could not update threading state for %s: %s", company_id, e)
