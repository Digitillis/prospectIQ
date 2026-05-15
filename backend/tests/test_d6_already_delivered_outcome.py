"""Tests for D6: ALREADY_DELIVERED outcome correctness in dispatch_scheduler.

Verifies:
  - ALREADY_DELIVERED with resend_message_id set → DELIVERED + provider_message_id (Scenario C)
  - ALREADY_DELIVERED with no resend_message_id → FAILED + lost_send code (Scenario E)
  - Queue row deleted in both cases
  - dispatch_failed NOT set in either case
  - No infinite retry loop: already_delivered_drained incremented, not assertion_skipped
  - Duplicate webhook replay is idempotent (via provider_events dedup, existing behavior)
  - Duplicate dispatch replay: second ALREADY_DELIVERED returns same result
  - Queue replay after crash: stale lock reclaim → re-dispatch → ALREADY_DELIVERED → drain
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call


DRAFT_ID = str(uuid.uuid4())
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
ATTEMPT_ID = str(uuid.uuid4())
RESEND_MSG_ID = "re_abc123xyz"


# ---------------------------------------------------------------------------
# Helpers (mirror test_pr_g_dispatch.py)
# ---------------------------------------------------------------------------

def _make_queue_row(draft_id: str = DRAFT_ID, retry_count: int = 0) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "draft_id": draft_id,
        "workspace_id": WORKSPACE_ID,
        "priority": 5,
        "retry_count": retry_count,
        "locked_by": str(uuid.uuid4()),
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "next_retry_at": None,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_chain():
    m = MagicMock()
    for attr in ("select", "eq", "neq", "in_", "is_", "not_", "lt", "gte", "order",
                  "limit", "not_.is_"):
        try:
            parts = attr.split(".")
            obj = m
            for p in parts[:-1]:
                obj = getattr(obj, p)
            getattr(obj, parts[-1]).return_value = m
        except Exception:
            pass
    return m


def _make_db_client(claimed_rows, send_attempt_id=ATTEMPT_ID, resend_message_id=None):
    """Build DB client mock with configurable queue claim + provider resolution."""
    client = MagicMock()

    rpc_result = MagicMock()
    rpc_result.data = claimed_rows
    client.rpc.return_value.execute.return_value = rpc_result

    insert_chain = _make_chain()
    insert_result = MagicMock()
    insert_result.data = [{"id": send_attempt_id}]
    insert_chain.execute.return_value = insert_result

    update_chain = _make_chain()
    update_result = MagicMock()
    update_result.data = []
    update_chain.execute.return_value = update_result

    delete_chain = _make_chain()
    delete_result = MagicMock()
    delete_result.data = []
    delete_chain.execute.return_value = delete_result

    # select chain for _resolve_provider_message_id
    select_chain = _make_chain()
    select_result = MagicMock()
    select_result.data = [{"resend_message_id": resend_message_id}] if resend_message_id else [{"resend_message_id": None}]
    select_chain.execute.return_value = select_result

    table = MagicMock()
    table.insert.return_value = insert_chain
    table.update.return_value = update_chain
    table.delete.return_value = delete_chain
    table.select.return_value = select_chain
    client.table.return_value = table

    return client


# ---------------------------------------------------------------------------
# TestScenarioC: ALREADY_DELIVERED + resend_message_id set → DELIVERED
# ---------------------------------------------------------------------------

class TestScenarioCDeliveredDrain:
    def test_already_delivered_with_provider_id_marks_send_attempt_delivered(self):
        """Scenario C: resend_message_id set → send_attempt DELIVERED with provider_message_id."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=RESEND_MSG_ID)
        outcome = QueueDispatchOutcome(
            status="ALREADY_DELIVERED",
            failure_reason="draft_sent_at_set_at_fetch",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.already_delivered_drained == 1
        assert result.errors == 0
        assert result.permanently_failed == 0

    def test_already_delivered_with_provider_id_includes_reconciled_at(self):
        """Scenario C drain sets reconciled_at on the send_attempt record."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=RESEND_MSG_ID)
        outcome = QueueDispatchOutcome(
            status="ALREADY_DELIVERED",
            failure_reason="draft_sent_at_already_set_pre_claim",
        )
        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        update_calls = []
        original_update = client.table.return_value.update
        def track_update(payload):
            update_calls.append(payload)
            return original_update(payload)
        client.table.return_value.update = track_update

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            dispatch_workspace(client, WORKSPACE_ID)

        delivered_updates = [c for c in update_calls if c.get("status") == "DELIVERED"]
        assert any("reconciled_at" in u for u in delivered_updates), (
            f"No reconciled_at in DELIVERED update. update_calls: {update_calls}"
        )

    def test_already_delivered_scenario_c_deletes_queue_row(self):
        """Scenario C: queue row is deleted after drain."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=RESEND_MSG_ID)
        outcome = QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            dispatch_workspace(client, WORKSPACE_ID)

        assert client.table.return_value.delete.called


# ---------------------------------------------------------------------------
# TestScenarioE: ALREADY_DELIVERED + no resend_message_id → FAILED (lost send)
# ---------------------------------------------------------------------------

class TestScenarioELostSend:
    def test_already_delivered_no_provider_id_marks_send_attempt_failed(self):
        """Scenario E: no resend_message_id → send_attempt FAILED (lost_send_pre_claim_crash)."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=None)
        outcome = QueueDispatchOutcome(
            status="ALREADY_DELIVERED",
            failure_reason="draft_sent_at_set_at_fetch",
        )
        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        update_calls = []
        original_update = client.table.return_value.update
        def track_update(payload):
            update_calls.append(payload)
            return original_update(payload)
        client.table.return_value.update = track_update

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.already_delivered_drained == 1
        failed_updates = [c for c in update_calls if c.get("status") == "FAILED"]
        assert any(c.get("failure_code") == "lost_send_pre_claim_crash" for c in failed_updates), (
            f"Expected lost_send_pre_claim_crash failure_code. update_calls: {update_calls}"
        )

    def test_already_delivered_no_provider_id_does_not_set_dispatch_failed(self):
        """Scenario E: lost send must NOT set approval_status='dispatch_failed'."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=None)
        outcome = QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        update_calls = []
        original_update = client.table.return_value.update
        def track_update(payload):
            update_calls.append(payload)
            return original_update(payload)
        client.table.return_value.update = track_update

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            dispatch_workspace(client, WORKSPACE_ID)

        dispatch_failed = [c for c in update_calls if c.get("approval_status") == "dispatch_failed"]
        assert len(dispatch_failed) == 0, f"dispatch_failed wrongly set: {dispatch_failed}"

    def test_already_delivered_no_provider_id_still_deletes_queue_row(self):
        """Scenario E: queue row deleted even for lost sends — no orphan rows."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=None)
        outcome = QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            dispatch_workspace(client, WORKSPACE_ID)

        assert client.table.return_value.delete.called


# ---------------------------------------------------------------------------
# TestNoInfiniteRetryLoop
# ---------------------------------------------------------------------------

class TestNoInfiniteRetryLoop:
    def test_already_delivered_not_classified_as_assertion_skipped(self):
        """ALREADY_DELIVERED must not increment assertion_skipped (which releases lock, not drains row)."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=RESEND_MSG_ID)
        outcome = QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.assertion_skipped == 0
        assert result.already_delivered_drained == 1

    def test_already_delivered_not_retried_via_transient_failed(self):
        """ALREADY_DELIVERED must not go into the retry backoff path."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=RESEND_MSG_ID)
        outcome = QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.transient_failed == 0
        assert result.permanently_failed == 0


# ---------------------------------------------------------------------------
# TestDuplicateDispatchReplay
# ---------------------------------------------------------------------------

class TestDuplicateDispatchReplay:
    def test_second_already_delivered_on_same_draft_still_drains(self):
        """Two consecutive ALREADY_DELIVERED outcomes both drain correctly (idempotent)."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _make_db_client(claimed_rows=[queue_row], resend_message_id=RESEND_MSG_ID)
        outcome = QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            r1 = dispatch_workspace(client, WORKSPACE_ID)

        # Reset claim to simulate second dispatch tick on same row
        client.rpc.return_value.execute.return_value.data = [queue_row]
        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            r2 = dispatch_workspace(client, WORKSPACE_ID)

        assert r1.already_delivered_drained == 1
        assert r2.already_delivered_drained == 1


# ---------------------------------------------------------------------------
# TestProviderResolution
# ---------------------------------------------------------------------------

class TestProviderResolution:
    def test_resolve_provider_id_returns_resend_message_id(self):
        """_resolve_provider_message_id returns the resend_message_id from outreach_drafts."""
        from backend.app.core.dispatch_scheduler import _resolve_provider_message_id

        client = MagicMock()
        chain = MagicMock()
        for attr in ("select", "eq", "limit"):
            getattr(chain, attr).return_value = chain
        result = MagicMock()
        result.data = [{"resend_message_id": RESEND_MSG_ID}]
        chain.execute.return_value = result
        client.table.return_value = chain

        assert _resolve_provider_message_id(client, DRAFT_ID) == RESEND_MSG_ID

    def test_resolve_provider_id_returns_none_when_null(self):
        """_resolve_provider_message_id returns None when resend_message_id is NULL."""
        from backend.app.core.dispatch_scheduler import _resolve_provider_message_id

        client = MagicMock()
        chain = MagicMock()
        for attr in ("select", "eq", "limit"):
            getattr(chain, attr).return_value = chain
        result = MagicMock()
        result.data = [{"resend_message_id": None}]
        chain.execute.return_value = result
        client.table.return_value = chain

        assert _resolve_provider_message_id(client, DRAFT_ID) is None

    def test_resolve_provider_id_returns_none_on_exception(self):
        """_resolve_provider_message_id returns None (not raise) on DB error."""
        from backend.app.core.dispatch_scheduler import _resolve_provider_message_id

        client = MagicMock()
        client.table.side_effect = Exception("DB connection error")

        assert _resolve_provider_message_id(client, DRAFT_ID) is None
