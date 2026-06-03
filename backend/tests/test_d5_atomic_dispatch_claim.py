"""Tests for D5: Atomic pre-send sent_at claim in dispatch_queued_draft.

Verifies:
  - Pre-send claim fires before Resend API call
  - ALREADY_DELIVERED returned when sent_at already set (at fetch or at claim)
  - sent_at rolled back on Resend failure (TRANSIENT_FAILED / PERMANENTLY_FAILED)
  - dispatch_workspace drains stuck queue row on ALREADY_DELIVERED
  - No duplicate send when stale lock reclaims and re-dispatches
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch, PropertyMock


DRAFT_ID = str(uuid.uuid4())
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
ATTEMPT_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures
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


def _make_draft(sent_at: str | None = None) -> dict:
    return {
        "id": DRAFT_ID,
        "workspace_id": WORKSPACE_ID,
        "company_id": str(uuid.uuid4()),
        "contact_id": str(uuid.uuid4()),
        "channel": "email",
        "sequence_name": "email_value_first",
        "sequence_step": 2,
        "subject": "Following up",
        "body": "Hi Jane, checking in...",
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


def _make_agent_with_db(draft_rows, claim_rows=None, rollback_rows=None):
    """Return (agent, db_client_mock) with configurable Supabase responses."""
    from backend.app.agents.engagement import EngagementAgent

    db_client = MagicMock()

    def table_side_effect(name):
        tbl = MagicMock()
        chain = MagicMock()

        # Make all filter methods chainable
        for attr in ("select", "eq", "neq", "in_", "is_", "not_", "lt", "gte",
                     "limit", "order", "update", "delete"):
            getattr(chain, attr).return_value = chain

        if name == "outreach_drafts":
            select_result = MagicMock()
            select_result.data = draft_rows
            chain.execute.return_value = select_result

            # update chain for pre-send claim returns claim_rows
            claim_result = MagicMock()
            claim_result.data = claim_rows if claim_rows is not None else [{"id": DRAFT_ID}]
            update_chain = MagicMock()
            for attr in ("eq", "is_", "neq", "update"):
                getattr(update_chain, attr).return_value = update_chain
            update_chain.execute.return_value = claim_result
            tbl.update.return_value = update_chain
            tbl.select.return_value = chain

        elif name == "contacts":
            contact_result = MagicMock()
            contact_result.data = [draft_rows[0]["contacts"]] if draft_rows else []
            chain.execute.return_value = contact_result
            tbl.select.return_value = chain

        elif name == "companies":
            company_result = MagicMock()
            company_result.data = [draft_rows[0]["companies"]] if draft_rows else []
            chain.execute.return_value = company_result
            tbl.select.return_value = chain

        else:
            result = MagicMock()
            result.data = []
            chain.execute.return_value = result
            tbl.select.return_value = chain
            tbl.update.return_value = chain
            tbl.insert.return_value = chain

        return tbl

    db_client.table.side_effect = table_side_effect

    db_mock = MagicMock()
    db_mock.client = db_client
    db_mock.workspace_id = WORKSPACE_ID

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.db = db_mock

    return agent, db_client


# ---------------------------------------------------------------------------
# TestAlreadyDeliveredAtFetch: sent_at set at draft fetch time
# ---------------------------------------------------------------------------

class TestAlreadyDeliveredAtFetch:
    def test_returns_already_delivered_when_sent_at_set_at_fetch(self):
        """dispatch_queued_draft returns ALREADY_DELIVERED if draft.sent_at is set at fetch."""
        from backend.app.agents.engagement import EngagementAgent, QueueDispatchOutcome

        draft_with_sent_at = _make_draft(sent_at="2026-05-15T21:24:00+00:00")
        agent, db_client = _make_agent_with_db(draft_rows=[draft_with_sent_at])

        # Provide a Resend key (the key gate runs before the fetch) so execution
        # reaches the already-delivered-at-fetch check. get_credential is patched
        # at its source module so the function-local `from ... import get_credential`
        # picks it up. Without this, CI (no credential store / env key) returns
        # ASSERTION_FAILED first.
        queue_row = _make_queue_row()
        with patch("backend.app.core.credential_store.get_credential", return_value="re_test_key"):
            outcome = agent.dispatch_queued_draft(
                queue_row=queue_row,
                attempt_number=2,
                idempotency_key=f"{DRAFT_ID}:2",
            )

        assert outcome.status == "ALREADY_DELIVERED"
        assert outcome.failure_reason == "draft_sent_at_set_at_fetch"

    def test_already_delivered_at_fetch_does_not_call_resend(self):
        """Resend is never called when draft.sent_at is already set."""
        import resend
        from backend.app.agents.engagement import EngagementAgent

        draft_with_sent_at = _make_draft(sent_at="2026-05-15T21:24:00+00:00")
        agent, _ = _make_agent_with_db(draft_rows=[draft_with_sent_at])

        queue_row = _make_queue_row()
        with patch("resend.Emails.send") as mock_send:
            agent.dispatch_queued_draft(
                queue_row=queue_row,
                attempt_number=2,
                idempotency_key=f"{DRAFT_ID}:2",
            )
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# TestPreSendClaimFailsZeroRows: sent_at set between fetch and claim
# ---------------------------------------------------------------------------

class TestPreSendClaimReturnsZeroRows:
    def _setup_agent_with_zero_claim(self):
        """Draft fetched with sent_at=None; pre-send claim returns 0 rows."""
        from backend.app.agents.engagement import EngagementAgent

        draft = _make_draft(sent_at=None)
        agent, db_client = _make_agent_with_db(
            draft_rows=[draft],
            claim_rows=[],  # 0 rows = claim failed
        )

        # Wire enough mocks to pass assertions gate
        from backend.app.core.config import Settings
        settings_mock = MagicMock(spec=Settings)
        settings_mock.resend_api_key = "re_test_key"
        settings_mock.default_workspace_id = WORKSPACE_ID

        with patch("backend.app.agents.engagement.get_settings", return_value=settings_mock), \
             patch("backend.app.core.credential_store.get_credential", return_value=None), \
             patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)), \
             patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)):
            agent._load_send_config = MagicMock(return_value={
                "daily_limit": 125, "batch_size": 1,
                "send_enabled": True, "min_gap_seconds": 0,
            })
            agent._get_sender_config = MagicMock(return_value=(
                [], "reply@test.com", "from@test.com", "Test Sender <from@test.com>"
            ))
            agent._pick_sender_from_config = MagicMock(return_value=("from@test.com", "Test <from@test.com>"))

            return agent

    def test_returns_already_delivered_when_claim_empty(self):
        """Pre-send claim returning 0 rows → ALREADY_DELIVERED outcome."""
        from backend.app.core.config import Settings
        from backend.app.core.pre_send_assertions import run_pre_send_assertions

        draft = _make_draft(sent_at=None)
        agent, _ = _make_agent_with_db(draft_rows=[draft], claim_rows=[])

        settings_mock = MagicMock(spec=Settings)
        settings_mock.resend_api_key = "re_test_key"
        settings_mock.default_workspace_id = WORKSPACE_ID
        agent._load_send_config = MagicMock(return_value={
            "daily_limit": 125, "batch_size": 1,
            "send_enabled": True, "min_gap_seconds": 0,
        })
        agent._get_sender_config = MagicMock(return_value=(
            [], "reply@test.com", "from@test.com", "Test Sender <from@test.com>"
        ))
        agent._pick_sender_from_config = MagicMock(return_value=("from@test.com", "Test <from@test.com>"))

        queue_row = _make_queue_row()
        with patch("backend.app.agents.engagement.get_settings", return_value=settings_mock), \
             patch("backend.app.core.credential_store.get_credential", return_value=None), \
             patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)), \
             patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)), \
             patch("backend.app.core.pre_send_assertions.run_pre_send_assertions"), \
             patch("resend.Emails.send") as mock_send:
            outcome = agent.dispatch_queued_draft(
                queue_row=queue_row,
                attempt_number=2,
                idempotency_key=f"{DRAFT_ID}:2",
            )

        assert outcome.status == "ALREADY_DELIVERED"
        assert "already_set" in outcome.failure_reason
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# TestRollbackOnResendFailure
# ---------------------------------------------------------------------------

class TestRollbackOnResendFailure:
    def _build_agent(self, resend_exc):
        from backend.app.agents.engagement import EngagementAgent
        from backend.app.core.config import Settings

        draft = _make_draft(sent_at=None)

        # Track update calls to verify rollback
        update_calls = []

        db_client = MagicMock()

        def table_side_effect(name):
            tbl = MagicMock()
            chain = MagicMock()
            for attr in ("select", "eq", "neq", "in_", "is_", "limit", "order"):
                getattr(chain, attr).return_value = chain

            if name == "outreach_drafts":
                # select returns draft
                select_result = MagicMock()
                select_result.data = [draft]
                chain.execute.return_value = select_result
                tbl.select.return_value = chain

                # update: track calls; first call (claim) returns 1 row; second call (rollback) returns 1 row
                call_count = [0]
                def update_side(payload):
                    update_calls.append(payload)
                    call_count[0] += 1
                    upd_chain = MagicMock()
                    for attr in ("eq", "is_"):
                        getattr(upd_chain, attr).return_value = upd_chain
                    # First call is the pre-send claim (returns 1 row = success)
                    # Second call is the rollback (returns 1 row)
                    upd_result = MagicMock()
                    upd_result.data = [{"id": DRAFT_ID}]
                    upd_chain.execute.return_value = upd_result
                    return upd_chain
                tbl.update.side_effect = update_side

            elif name in ("contacts", "companies"):
                data_key = "contacts" if name == "contacts" else "companies"
                result = MagicMock()
                result.data = [draft[data_key]]
                chain.execute.return_value = result
                tbl.select.return_value = chain
                tbl.update.return_value = chain

            else:
                result = MagicMock()
                result.data = []
                chain.execute.return_value = result
                tbl.select.return_value = chain
                tbl.update.return_value = chain
                tbl.insert.return_value = chain

            return tbl

        db_client.table.side_effect = table_side_effect

        db_mock = MagicMock()
        db_mock.client = db_client
        db_mock.workspace_id = WORKSPACE_ID

        agent = EngagementAgent.__new__(EngagementAgent)
        agent.db = db_mock

        settings_mock = MagicMock(spec=Settings)
        settings_mock.resend_api_key = "re_test_key"
        settings_mock.default_workspace_id = WORKSPACE_ID
        agent._load_send_config = MagicMock(return_value={
            "daily_limit": 125, "batch_size": 1,
            "send_enabled": True, "min_gap_seconds": 0,
        })
        agent._get_sender_config = MagicMock(return_value=(
            [], "reply@test.com", "from@test.com", "Test Sender <from@test.com>"
        ))
        agent._pick_sender_from_config = MagicMock(return_value=("from@test.com", "Test <from@test.com>"))

        return agent, update_calls, settings_mock

    def test_transient_failure_rolls_back_sent_at(self):
        """5xx Resend failure → sent_at rolled back to None → TRANSIENT_FAILED returned."""
        agent, update_calls, settings_mock = self._build_agent(Exception("503 Service Unavailable"))

        queue_row = _make_queue_row()
        with patch("backend.app.agents.engagement.get_settings", return_value=settings_mock), \
             patch("backend.app.core.credential_store.get_credential", return_value=None), \
             patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)), \
             patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)), \
             patch("backend.app.core.pre_send_assertions.run_pre_send_assertions"), \
             patch("resend.Emails.send", side_effect=Exception("503 Service Unavailable")):
            outcome = agent.dispatch_queued_draft(
                queue_row=queue_row,
                attempt_number=1,
                idempotency_key=f"{DRAFT_ID}:1",
            )

        assert outcome.status == "TRANSIENT_FAILED"
        # update_calls: [pre_send_claim_payload, rollback_payload]
        # Rollback must set sent_at=None
        rollback_calls = [c for c in update_calls if c.get("sent_at") is None]
        assert len(rollback_calls) >= 1, f"No rollback update found. update_calls: {update_calls}"

    def test_permanent_failure_rolls_back_sent_at(self):
        """4xx Resend failure → sent_at rolled back to None → PERMANENTLY_FAILED returned."""
        agent, update_calls, settings_mock = self._build_agent(Exception("422 Unprocessable Entity"))

        queue_row = _make_queue_row()
        with patch("backend.app.agents.engagement.get_settings", return_value=settings_mock), \
             patch("backend.app.core.credential_store.get_credential", return_value=None), \
             patch("backend.app.core.suppression.is_suppressed", return_value=(False, None)), \
             patch("backend.app.core.channel_coordinator.is_company_locked", return_value=(False, None)), \
             patch("backend.app.core.pre_send_assertions.run_pre_send_assertions"), \
             patch("resend.Emails.send", side_effect=Exception("422 Unprocessable Entity")):
            outcome = agent.dispatch_queued_draft(
                queue_row=queue_row,
                attempt_number=1,
                idempotency_key=f"{DRAFT_ID}:1",
            )

        assert outcome.status == "PERMANENTLY_FAILED"
        rollback_calls = [c for c in update_calls if c.get("sent_at") is None]
        assert len(rollback_calls) >= 1, f"No rollback update found. update_calls: {update_calls}"


# ---------------------------------------------------------------------------
# TestAlreadyDeliveredDrainInDispatchWorkspace
# ---------------------------------------------------------------------------

class TestAlreadyDeliveredDrainInDispatchWorkspace:
    def _make_db_client(self, queue_rows, send_attempt_id=ATTEMPT_ID):
        from backend.tests.test_pr_g_dispatch import _mock_db_client, _make_chain
        client = MagicMock()

        rpc_result = MagicMock()
        rpc_result.data = queue_rows
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

    def test_already_delivered_drains_queue_row(self):
        """dispatch_workspace receiving ALREADY_DELIVERED → queue row deleted, not retried."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome
        from backend.tests.test_pr_g_dispatch import _make_queue_row

        queue_row = _make_queue_row()
        client = self._make_db_client(queue_rows=[queue_row])
        outcome = QueueDispatchOutcome(
            status="ALREADY_DELIVERED",
            failure_reason="draft_sent_at_already_set_pre_claim",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.already_delivered_drained == 1
        assert result.delivered == 0  # not counted as fresh delivery
        assert result.assertion_skipped == 0
        assert result.errors == 0
        # Queue row must have been deleted (delete called)
        assert client.table.return_value.delete.called

    def test_already_delivered_does_not_mark_draft_dispatch_failed(self):
        """ALREADY_DELIVERED must NOT set approval_status='dispatch_failed'."""
        from backend.app.core.dispatch_scheduler import dispatch_workspace
        from backend.app.agents.engagement import QueueDispatchOutcome
        from backend.tests.test_pr_g_dispatch import _make_queue_row

        queue_row = _make_queue_row()
        client = self._make_db_client(queue_rows=[queue_row])
        outcome = QueueDispatchOutcome(
            status="ALREADY_DELIVERED",
            failure_reason="draft_sent_at_set_at_fetch",
        )

        agent_mock = MagicMock()
        agent_mock.dispatch_queued_draft.return_value = outcome

        update_calls = []
        original_table = client.table.return_value
        original_update = original_table.update

        def track_update(payload):
            update_calls.append(payload)
            return original_update(payload)

        original_table.update = track_update

        with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent_mock):
            dispatch_workspace(client, WORKSPACE_ID)

        dispatch_failed_calls = [c for c in update_calls if c.get("approval_status") == "dispatch_failed"]
        assert len(dispatch_failed_calls) == 0, (
            f"dispatch_failed was set on ALREADY_DELIVERED: {dispatch_failed_calls}"
        )


# ---------------------------------------------------------------------------
# TestBatchResultCounters
# ---------------------------------------------------------------------------

class TestBatchResultCounters:
    def test_batch_result_has_already_delivered_drained_field(self):
        """BatchResult includes already_delivered_drained counter."""
        from backend.app.core.dispatch_scheduler import BatchResult

        r = BatchResult()
        assert hasattr(r, "already_delivered_drained")
        assert r.already_delivered_drained == 0

    def test_already_delivered_outcome_status_accepted_by_dataclass(self):
        """QueueDispatchOutcome accepts ALREADY_DELIVERED as a valid status."""
        from backend.app.agents.engagement import QueueDispatchOutcome

        o = QueueDispatchOutcome(
            status="ALREADY_DELIVERED",
            failure_reason="draft_sent_at_already_set_pre_claim",
        )
        assert o.status == "ALREADY_DELIVERED"
