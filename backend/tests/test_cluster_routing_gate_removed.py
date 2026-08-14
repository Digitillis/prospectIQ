"""The cluster→Instantly-campaign-ID lookup must no longer block dispatch.

get_campaign_id_for_company()'s return value is written to
send_attempts.metadata["instantly_campaign_id"] for observability only — the
real send path is resend.Emails.send() (see backend/app/agents/engagement.py),
which never reads it. Previously a None result (env var unset or
misconfigured) dead-lettered the draft against a provider that sends
nothing. Diagnosed cause: ~5,691 production sends destroyed by this check,
dominated by a persona-collapsing fallback bug in
backend/app/core/sequence_router.py that this change does not need to fix,
because the gate reading its result should never have blocked in the first
place.

The cluster in ("other", "watchlist") gate immediately before it is a
DIFFERENT, legitimate manual-review control and must remain intact.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.tests.test_sdp13_hot_suppression_gap import _build_draft_row, _build_queue_row


def _agent_with_draft(draft_row: dict, queue_row: dict) -> "EngagementAgent":
    from backend.app.agents.engagement import EngagementAgent

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.workspace_id = "ws-1"

    agent.db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[draft_row]
    )
    agent.db.client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    return agent


def test_unresolved_campaign_id_no_longer_blocks_dispatch():
    """A None from get_campaign_id_for_company must NOT produce
    ASSERTION_FAILED with a cluster_routing_skip:no-Instantly-sequence
    reason — the dispatch must proceed past that check.
    """
    from backend.app.agents.engagement import COLD

    draft_row = _build_draft_row()
    # A resolvable cluster (not "other"/"watchlist") so only the
    # campaign-ID-lookup branch is under test, not the manual-review gate.
    draft_row["companies"]["campaign_cluster"] = "mfg_ops"
    queue_row = _build_queue_row()
    agent = _agent_with_draft(draft_row, queue_row)

    with (
        patch("backend.app.agents.engagement.classify_engagement_tier", return_value=COLD),
        patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)),
        patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)),
        patch("backend.app.core.sequence_router.get_campaign_id_for_company", return_value=None),
    ):
        outcome = agent.dispatch_queued_draft(
            queue_row=queue_row,
            attempt_number=1,
            idempotency_key="draft-hot-1",
        )

    reason = (outcome.failure_reason or "")
    assert "no Instantly sequence" not in reason, (
        f"Dispatch was blocked by the vestigial routing gate; got: {reason}"
    )
    assert "cluster_routing_skip" not in reason or "manual review" in reason, (
        f"Only the manual-review gate may still emit cluster_routing_skip; got: {reason}"
    )


def test_other_cluster_still_requires_manual_review():
    """The DISTINCT, legitimate gate — cluster in ('other', 'watchlist')
    requires manual review — must remain intact after removing the
    campaign-ID lookup gate.
    """
    from backend.app.agents.engagement import COLD

    draft_row = _build_draft_row()
    draft_row["companies"]["campaign_cluster"] = "other"
    queue_row = _build_queue_row()
    agent = _agent_with_draft(draft_row, queue_row)

    with (
        patch("backend.app.agents.engagement.classify_engagement_tier", return_value=COLD),
        patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)),
        patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)),
    ):
        outcome = agent.dispatch_queued_draft(
            queue_row=queue_row,
            attempt_number=1,
            idempotency_key="draft-hot-1",
        )

    assert outcome.status == "ASSERTION_FAILED"
    assert "requires manual review" in (outcome.failure_reason or "")
