"""Tests for PR G: Dispatch Scheduler (outbound_queue consumer).

Covers the full lifecycle: queue claim, send_attempts lifecycle, Resend call,
retry scheduling, stale lock reclaim, and permanently failed path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch


DRAFT_ID = str(uuid.uuid4())
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
INSTANCE_ID = str(uuid.uuid4())
ATTEMPT_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_queue_row(
    draft_id: str = DRAFT_ID,
    retry_count: int = 0,
    locked_by: str | None = None,
    locked_at: str | None = None,
    next_retry_at: str | None = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "draft_id": draft_id,
        "workspace_id": WORKSPACE_ID,
        "priority": 5,
        "retry_count": retry_count,
        "locked_by": locked_by,
        "locked_at": locked_at,
        "next_retry_at": next_retry_at,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_draft(sent_at: str | None = None) -> dict:
    return {
        "id": DRAFT_ID,
        "workspace_id": WORKSPACE_ID,
        "company_id": str(uuid.uuid4()),
        "contact_id": str(uuid.uuid4()),
        "channel": "email",
        "sequence_name": "email_value_first",
        "sequence_step": 1,
        "subject": "Quick question",
        "body": "Hi there, I noticed your team...",
        "edited_body": None,
        "sent_at": sent_at,
        "companies": {"name": "Acme Corp", "tier": "standard", "campaign_cluster": None},
        "contacts": {
            "full_name": "Jane Doe",
            "email": "jane@acme.com",
            "first_name": "Jane",
            "last_name": "Doe",
            "company_id": str(uuid.uuid4()),
            "persona_type": "ops",
        },
    }


def _make_chain(*extra_attrs):
    """Return a MagicMock where common filter methods return self (chainable)."""
    m = MagicMock()
    for attr in (
        "select",
        "eq",
        "neq",
        "in_",
        "is_",
        "not_",
        "lt",
        "gte",
        "order",
        "limit",
        "not_.is_",
    ):
        try:
            parts = attr.split(".")
            obj = m
            for p in parts[:-1]:
                obj = getattr(obj, p)
            getattr(obj, parts[-1]).return_value = m
        except Exception:
            pass
    return m


def _mock_db_client(claimed_rows=None, send_attempt_id=ATTEMPT_ID):
    """Build a Supabase client mock for dispatch_scheduler tests.

    Uses distinct chain objects per operation so insert/update/delete
    execute() return values do not collide.
    """
    client = MagicMock()

    rpc_result = MagicMock()
    rpc_result.data = claimed_rows or []
    client.rpc.return_value.execute.return_value = rpc_result

    # insert chain
    insert_chain = _make_chain()
    insert_result = MagicMock()
    insert_result.data = [{"id": send_attempt_id}]
    insert_chain.execute.return_value = insert_result

    # update chain
    update_chain = _make_chain()
    update_result = MagicMock()
    update_result.data = []
    update_chain.execute.return_value = update_result

    # delete chain
    delete_chain = _make_chain()
    delete_result = MagicMock()
    delete_result.data = []
    delete_chain.execute.return_value = delete_result

    # select chain (for stale-lock reads, etc.)
    select_chain = _make_chain()
    select_result = MagicMock()
    select_result.data = []
    select_chain.execute.return_value = select_result

    table = MagicMock()
    table.insert.return_value = insert_chain
    table.update.return_value = update_chain
    table.delete.return_value = delete_chain
    table.select.return_value = select_chain

    client.table.return_value = table
    return client


# ---------------------------------------------------------------------------
# TestQueueClaim
# ---------------------------------------------------------------------------


class TestQueueClaim:
    def test_claim_calls_rpc_with_correct_params(self):
        """dispatch_workspace calls claim_outbound_queue_batch RPC."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _mock_db_client(claimed_rows=[])
        with patch("backend.app.agents.engagement.EngagementAgent"):
            dispatch_workspace(client, WORKSPACE_ID, batch_size=5, max_retries=4)

        client.rpc.assert_called_once_with(
            "claim_outbound_queue_batch",
            {
                "p_workspace_id": WORKSPACE_ID,
                "p_batch_size": 5,
                "p_instance_id": client.rpc.call_args[0][1]["p_instance_id"],
            },
        )

    def test_empty_claim_returns_zero_batch(self):
        """No claimed rows → BatchResult with all zeros."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _mock_db_client(claimed_rows=[])
        with patch("backend.app.agents.engagement.EngagementAgent"):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.dispatched == 0
        assert result.delivered == 0
        assert result.errors == 0

    def test_claim_rpc_failure_increments_errors(self):
        """RPC exception → errors=1, no further processing."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = MagicMock()
        client.rpc.side_effect = Exception("connection refused")

        result = dispatch_workspace(client, WORKSPACE_ID)
        assert result.errors == 1
        assert result.dispatched == 0


# ---------------------------------------------------------------------------
# TestDispatchSuccess
# ---------------------------------------------------------------------------


class TestDispatchSuccess:
    def _setup(self):
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _mock_db_client(claimed_rows=[queue_row])

        outcome = QueueDispatchOutcome(
            status="DELIVERED",
            provider_message_id="msg_abc123",
        )
        return client, queue_row, outcome

    def test_delivered_updates_send_attempt_and_deletes_queue_row(self):
        """DELIVERED: send_attempts → DELIVERED, queue row deleted."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row()
        client = _mock_db_client(claimed_rows=[queue_row])
        outcome = QueueDispatchOutcome(status="DELIVERED", provider_message_id="msg_xyz")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.dispatched == 1
        assert result.delivered == 1
        assert result.transient_failed == 0
        assert result.permanently_failed == 0
        assert result.errors == 0

    def test_delivered_passes_correct_idempotency_key_to_agent(self):
        """dispatch_queued_draft receives idempotency_key = '{draft_id}:1' for first attempt."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row(retry_count=0)
        client = _mock_db_client(claimed_rows=[queue_row])
        outcome = QueueDispatchOutcome(status="DELIVERED", provider_message_id="msg_x")

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            dispatch_workspace(client, WORKSPACE_ID)

        call_kwargs = agent_mock.dispatch_queued_draft.call_args[1]
        assert call_kwargs["attempt_number"] == 1
        # SDP#3 fix: idempotency key is now the stable draft_id alone (not draft_id:attempt_number)
        # so Resend's 24h dedup window covers all retries for the same draft.
        assert call_kwargs["idempotency_key"] == DRAFT_ID


# ---------------------------------------------------------------------------
# TestTransientFailure
# ---------------------------------------------------------------------------


class TestTransientFailure:
    def test_transient_failure_schedules_retry(self):
        """5xx path: send_attempts FAILED, retry_count+1, next_retry_at set, lock released."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row(retry_count=0)
        client = _mock_db_client(claimed_rows=[queue_row])
        outcome = QueueDispatchOutcome(
            status="TRANSIENT_FAILED",
            failure_code="503_server_error",
            failure_reason="Service unavailable",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID, max_retries=4)

        assert result.transient_failed == 1
        assert result.permanently_failed == 0
        assert result.delivered == 0

    def test_transient_failure_retry_count_increments(self):
        """retry_count on the queue row increments by 1 after transient failure."""
        from backend.app.core.dispatch_scheduler import _schedule_retry
        from unittest.mock import MagicMock

        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.update.return_value = table
        table.eq.return_value = table
        table.execute.return_value = MagicMock(data=[])

        queue_row = _make_queue_row(retry_count=1)
        _schedule_retry(client, queue_row, new_retry_count=2)

        update_call = table.update.call_args[0][0]
        assert update_call["retry_count"] == 2
        assert update_call["locked_by"] is None
        assert update_call["locked_at"] is None
        assert "next_retry_at" in update_call

    def test_backoff_schedule(self):
        """_backoff_for returns correct delays per retry index."""
        from backend.app.core.dispatch_scheduler import _backoff_for

        assert _backoff_for(0) == 300  # 5 min
        assert _backoff_for(1) == 900  # 15 min
        assert _backoff_for(2) == 3600  # 1 h
        assert _backoff_for(3) == 14400  # 4 h
        assert _backoff_for(99) == 14400  # clamped


# ---------------------------------------------------------------------------
# TestPermanentFailure
# ---------------------------------------------------------------------------


class TestPermanentFailure:
    def test_permanent_failure_deletes_queue_row_and_marks_draft(self):
        """4xx path: send_attempts PERMANENTLY_FAILED, queue row deleted, draft marked."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row(retry_count=0)
        client = _mock_db_client(claimed_rows=[queue_row])
        outcome = QueueDispatchOutcome(
            status="PERMANENTLY_FAILED",
            failure_code="422_client_error",
            failure_reason="Invalid recipient address",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.permanently_failed == 1
        assert result.delivered == 0
        assert result.transient_failed == 0


# ---------------------------------------------------------------------------
# TestMaxRetries
# ---------------------------------------------------------------------------


class TestMaxRetries:
    def test_transient_failure_at_max_retries_becomes_permanent(self):
        """At retry_count == max_retries - 1, transient failure → permanently failed."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        # retry_count=3 means attempt 4 (the last allowed with max_retries=4)
        queue_row = _make_queue_row(retry_count=3)
        client = _mock_db_client(claimed_rows=[queue_row])
        outcome = QueueDispatchOutcome(
            status="TRANSIENT_FAILED",
            failure_code="503_server_error",
            failure_reason="Service unavailable",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID, max_retries=4)

        assert result.permanently_failed == 1
        assert result.transient_failed == 0


# ---------------------------------------------------------------------------
# TestStaleLockReclaim
# ---------------------------------------------------------------------------


class TestStaleLockReclaim:
    def test_reclaim_returns_count_of_cleared_rows(self):
        """reclaim_stale_locks returns the number of rows updated."""
        from backend.app.core.dispatch_scheduler import reclaim_stale_locks

        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.update.return_value = table
        table.eq.return_value = table
        table.not_.return_value = table
        table.not_.is_.return_value = table
        table.lt.return_value = table
        update_result = MagicMock()
        update_result.data = [{"id": "row1"}, {"id": "row2"}]
        table.execute.return_value = update_result

        count = reclaim_stale_locks(client, WORKSPACE_ID)
        assert count == 2

    def test_reclaim_no_stale_returns_zero(self):
        """reclaim_stale_locks returns 0 when no stale locks exist."""
        from backend.app.core.dispatch_scheduler import reclaim_stale_locks

        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.update.return_value = table
        table.eq.return_value = table
        table.not_.return_value = table
        table.not_.is_.return_value = table
        table.lt.return_value = table
        update_result = MagicMock()
        update_result.data = []
        table.execute.return_value = update_result

        count = reclaim_stale_locks(client, WORKSPACE_ID)
        assert count == 0

    def test_reclaim_clears_locked_by_and_locked_at(self):
        """reclaim_stale_locks updates locked_by=None and locked_at=None."""
        from backend.app.core.dispatch_scheduler import reclaim_stale_locks

        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.update.return_value = table
        table.eq.return_value = table
        table.not_.return_value = table
        table.not_.is_.return_value = table
        table.lt.return_value = table
        update_result = MagicMock()
        update_result.data = []
        table.execute.return_value = update_result

        reclaim_stale_locks(client, WORKSPACE_ID)
        update_payload = table.update.call_args[0][0]
        assert update_payload["locked_by"] is None
        assert update_payload["locked_at"] is None


# ---------------------------------------------------------------------------
# TestAssertionFailure
# ---------------------------------------------------------------------------


class TestAssertionFailure:
    def test_assertion_failure_releases_lock_no_retry_at(self):
        """ASSERTION_FAILED: lock released, next_retry_at NOT set."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome

        queue_row = _make_queue_row(retry_count=0)
        client = _mock_db_client(claimed_rows=[queue_row])
        outcome = QueueDispatchOutcome(
            status="ASSERTION_FAILED",
            failure_reason="suppressed: previous_bounce",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.assertion_skipped == 1
        assert result.delivered == 0
        assert result.transient_failed == 0
        assert result.permanently_failed == 0


# ---------------------------------------------------------------------------
# TestSendAttemptInvariant
# ---------------------------------------------------------------------------


class TestSendAttemptInvariant:
    def test_send_attempt_insert_failure_releases_lock_and_skips(self):
        """If send_attempts insert fails, lock is released and Resend is NOT called."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        queue_row = _make_queue_row(retry_count=0)

        # Use _mock_db_client but override insert to return empty (simulate failure)
        client = _mock_db_client(claimed_rows=[queue_row], send_attempt_id=None)
        # Override insert chain to return empty data
        failed_insert_chain = _make_chain()
        failed_insert_result = MagicMock()
        failed_insert_result.data = []
        failed_insert_chain.execute.return_value = failed_insert_result
        client.table.return_value.insert.return_value = failed_insert_chain

        agent_mock = MagicMock()

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        # Agent must NOT have been called (no Resend call without send_attempts)
        agent_mock.dispatch_queued_draft.assert_not_called()
        assert result.errors == 1
        assert result.dispatched == 0


# ---------------------------------------------------------------------------
# TestResendErrorClassification
# ---------------------------------------------------------------------------


class TestResendErrorClassification:
    def test_429_classified_as_transient(self):
        from backend.app.agents.engagement import _classify_resend_error

        status, code = _classify_resend_error(Exception("429 Too Many Requests"))
        assert status == "TRANSIENT_FAILED"
        assert "429" in code

    def test_503_classified_as_transient(self):
        from backend.app.agents.engagement import _classify_resend_error

        status, code = _classify_resend_error(Exception("503 Service Unavailable"))
        assert status == "TRANSIENT_FAILED"
        assert "503" in code

    def test_network_error_classified_as_transient(self):
        from backend.app.agents.engagement import _classify_resend_error

        status, code = _classify_resend_error(Exception("connection timeout"))
        assert status == "TRANSIENT_FAILED"
        assert code == "network_error"

    def test_422_classified_as_permanent(self):
        from backend.app.agents.engagement import _classify_resend_error

        status, code = _classify_resend_error(Exception("422 Unprocessable Entity"))
        assert status == "PERMANENTLY_FAILED"
        assert "422" in code

    def test_400_classified_as_permanent(self):
        from backend.app.agents.engagement import _classify_resend_error

        status, code = _classify_resend_error(Exception("400 Bad Request"))
        assert status == "PERMANENTLY_FAILED"

    def test_unknown_error_classified_as_permanent(self):
        from backend.app.agents.engagement import _classify_resend_error

        status, code = _classify_resend_error(Exception("something unexpected"))
        assert status == "PERMANENTLY_FAILED"
        assert code == "unknown_client_error"


# ---------------------------------------------------------------------------
# TestQueueDispatchOutcome dataclass
# ---------------------------------------------------------------------------


class TestQueueDispatchOutcome:
    def test_outcome_fields(self):
        from backend.app.agents.engagement import QueueDispatchOutcome

        o = QueueDispatchOutcome(
            status="DELIVERED",
            provider_message_id="msg_123",
        )
        assert o.status == "DELIVERED"
        assert o.provider_message_id == "msg_123"
        assert o.failure_code is None
        assert o.failure_reason is None

    def test_outcome_failure_fields(self):
        from backend.app.agents.engagement import QueueDispatchOutcome

        o = QueueDispatchOutcome(
            status="TRANSIENT_FAILED",
            failure_code="503_server_error",
            failure_reason="Gateway timeout",
        )
        assert o.status == "TRANSIENT_FAILED"
        assert o.failure_code == "503_server_error"
        assert o.failure_reason == "Gateway timeout"
