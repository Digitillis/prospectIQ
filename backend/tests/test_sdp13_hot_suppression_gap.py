"""SDP#13: dispatch_queued_draft must check engagement tier inline and block
HOT companies before calling Resend.

Previously, HOT classification only ran in the campaign_status check on a
slower cadence — not at the actual dispatch moment.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def _build_queue_row(draft_id: str = "draft-hot-1") -> dict:
    return {
        "id": "q-1",
        "draft_id": draft_id,
        "workspace_id": "ws-1",
        "retry_count": 0,
        "next_retry_at": None,
        "locked_by": "inst-1",
    }


def _build_draft_row(contact_email: str = "contact@acme.com") -> dict:
    return {
        "id": "draft-hot-1",
        "company_id": "co-hot-1",
        "contact_id": "ct-1",
        "channel": "email",
        "sequence_step": 1,
        "subject": "Hi",
        "body": "Hello",
        "edited_body": None,
        "workspace_id": "ws-1",
        "sent_at": None,
        "sequence_name": "mfg-awareness",
        "companies": {"name": "Acme", "tier": "tier2", "campaign_cluster": "mfg_ops"},
        "contacts": {
            "full_name": "Alice Smith", "email": contact_email,
            "first_name": "Alice", "last_name": "Smith",
            "company_id": "co-hot-1", "persona_type": "ops_manager",
        },
    }


def test_hot_company_is_blocked_at_dispatch():
    """dispatch_queued_draft must return ASSERTION_FAILED for HOT companies."""
    from backend.app.agents.engagement import EngagementAgent, HOT, COLD

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.workspace_id = "ws-1"

    draft_row = _build_draft_row()
    queue_row = _build_queue_row()

    # Mock DB calls
    agent.db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[draft_row])

    # Interactions with a reply → HOT
    hot_interactions = [{"type": "email_replied", "created_at": datetime.now(timezone.utc).isoformat()}]
    agent.db.client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=hot_interactions)

    with patch("backend.app.agents.engagement.classify_engagement_tier", return_value=HOT), \
         patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)), \
         patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)):

        outcome = agent.dispatch_queued_draft(
            queue_row=queue_row,
            attempt_number=1,
            idempotency_key="draft-hot-1",
        )

        assert outcome.status == "ASSERTION_FAILED", (
            f"Expected ASSERTION_FAILED for HOT company, got {outcome.status}"
        )
        assert "hot" in (outcome.failure_reason or "").lower(), (
            f"Expected HOT reason in failure_reason, got: {outcome.failure_reason}"
        )


def test_cold_company_passes_hot_check():
    """COLD companies must not be blocked by the HOT check."""
    from backend.app.agents.engagement import EngagementAgent, HOT, COLD

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.workspace_id = "ws-1"

    draft_row = _build_draft_row()
    queue_row = _build_queue_row()

    agent.db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[draft_row])
    agent.db.client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

    # COLD company — HOT check should pass
    with patch("backend.app.agents.engagement.classify_engagement_tier", return_value=COLD), \
         patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)), \
         patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)), \
         patch("backend.app.core.sequence_router.get_campaign_id_for_company", return_value=None):
        outcome = agent.dispatch_queued_draft(
            queue_row=queue_row,
            attempt_number=1,
            idempotency_key="draft-hot-1",
        )
        # Should not fail on HOT specifically — may fail on other checks
        if outcome.status == "ASSERTION_FAILED":
            assert "hot" not in (outcome.failure_reason or "").lower(), (
                f"COLD company should not fail HOT check, but got: {outcome.failure_reason}"
            )
