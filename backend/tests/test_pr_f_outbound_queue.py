"""Tests for PR F: Outbound Queue and Transactional Outbox.

Verifies that the approval endpoint atomically writes both the
approval_status and the outbound_queue row, and that rejection/
pending_second_review produce no queue row.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call


DRAFT_ID = str(uuid.uuid4())
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _make_draft(status: str = "pending") -> dict:
    return {
        "id": DRAFT_ID,
        "workspace_id": WORKSPACE_ID,
        "approval_status": status,
        "approved_at": None,
        "company_id": str(uuid.uuid4()),
        "contact_id": str(uuid.uuid4()),
        "sequence_name": "email_value_first",
        "sequence_step": 1,
        "channel": "email",
        "body": "Hi {{first_name}}, I noticed...",
        "edited_body": None,
        "subject": "Quick question about your ops",
        "sent_at": None,
        "companies": {"tier": "standard"},
    }


def _mock_db(draft: dict | None = None, rpc_result: list | None = None):
    """Build a mock Database instance."""
    db = MagicMock()
    db.workspace_id = WORKSPACE_ID

    # _filter_ws returns the query chainable
    db._filter_ws.return_value = db._filter_ws
    db._filter_ws.eq.return_value = db._filter_ws
    db._filter_ws.gte.return_value = db._filter_ws
    db._filter_ws.not_.is_.return_value = db._filter_ws
    ws_execute_result = MagicMock()
    ws_execute_result.data = [draft] if draft else []
    ws_execute_result.count = 0
    db._filter_ws.execute.return_value = ws_execute_result

    # Supabase .table().select().eq().execute() chains
    table_mock = MagicMock()
    db.client.table.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.gte.return_value = table_mock
    execute_result = MagicMock()
    execute_result.data = [draft] if draft else []
    execute_result.count = 0
    table_mock.execute.return_value = execute_result

    # RPC — returns the draft row (simulates approve_draft_and_enqueue)
    rpc_mock = MagicMock()
    db.client.rpc.return_value = rpc_mock
    rpc_mock.execute.return_value = MagicMock(
        data=rpc_result if rpc_result is not None else [draft or _make_draft("approved")]
    )

    return db


class TestApprovalAtomicEnqueue:
    """approve_draft_and_enqueue RPC is called for terminal approval states."""

    def test_approve_calls_rpc_not_direct_update(self):
        draft = _make_draft("pending")
        approved_draft = {**draft, "approval_status": "approved"}
        db = _mock_db(draft=draft, rpc_result=[approved_draft])

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
            patch("backend.app.api.routes.approvals.get_current_user", return_value={"user_id": "user-1"}),
            patch("backend.app.api.routes.approvals.require_role", return_value=lambda: None),
        ):
            from backend.app.api.routes.approvals import approve_draft
            import asyncio

            request = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                approve_draft(DRAFT_ID, request, body=None, _role=None, force=True)
            )

        # RPC must have been called for the core approval
        db.client.rpc.assert_called_once()
        rpc_call_kwargs = db.client.rpc.call_args
        assert rpc_call_kwargs[0][0] == "approve_draft_and_enqueue"
        params = rpc_call_kwargs[0][1]
        assert params["p_draft_id"] == DRAFT_ID
        assert params["p_status"] == "approved"
        assert params["p_workspace_id"] == WORKSPACE_ID

        # If update_outreach_draft was called, it must only be for reviewer fields
        # (approved_by, reviewed_at, attestation) — NOT for approval_status
        for c in db.update_outreach_draft.call_args_list:
            update_payload = c[0][1]
            assert "approval_status" not in update_payload, (
                "approval_status must not be written via direct update — use RPC"
            )

    def test_rpc_params_contain_approved_at(self):
        draft = _make_draft("pending")
        db = _mock_db(draft=draft, rpc_result=[{**draft, "approval_status": "approved"}])

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
            patch("backend.app.api.routes.approvals.get_current_user", return_value={"user_id": ""}),
            patch("backend.app.api.routes.approvals.require_role", return_value=lambda: None),
        ):
            from backend.app.api.routes.approvals import approve_draft
            import asyncio

            request = MagicMock()
            asyncio.get_event_loop().run_until_complete(
                approve_draft(DRAFT_ID, request, body=None, _role=None, force=True)
            )

        params = db.client.rpc.call_args[0][1]
        assert params["p_approved_at"] is not None

    def test_edited_body_passed_to_rpc(self):
        from backend.app.api.routes.approvals import ApproveRequest, approve_draft
        import asyncio

        draft = _make_draft("pending")
        db = _mock_db(draft=draft, rpc_result=[{**draft, "approval_status": "edited", "edited_body": "New body"}])

        body = ApproveRequest(edited_body="New body")

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
            patch("backend.app.api.routes.approvals.get_current_user", return_value={"user_id": ""}),
            patch("backend.app.api.routes.approvals.require_role", return_value=lambda: None),
        ):
            request = MagicMock()
            asyncio.get_event_loop().run_until_complete(
                approve_draft(DRAFT_ID, request, body=body, _role=None, force=True)
            )

        params = db.client.rpc.call_args[0][1]
        assert params["p_edited_body"] == "New body"
        assert params["p_status"] == "edited"


class TestRejectionNoQueueRow:
    """Rejection must not produce a queue row."""

    def test_reject_does_not_call_rpc(self):
        from backend.app.api.routes.approvals import reject_draft, RejectRequest
        import asyncio

        draft = _make_draft("pending")
        db = _mock_db(draft=draft)
        db.update_outreach_draft.return_value = {**draft, "approval_status": "rejected"}

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
        ):
            body = RejectRequest(rejection_reason="Weak opener")
            asyncio.get_event_loop().run_until_complete(
                reject_draft(DRAFT_ID, body, _role=None)
            )

        db.client.rpc.assert_not_called()
        db.update_outreach_draft.assert_called_once()
        call_args = db.update_outreach_draft.call_args[0][1]
        assert call_args["approval_status"] == "rejected"


class TestPendingSecondReviewNoQueueRow:
    """pending_second_review must not produce a queue row."""

    def test_pending_second_review_uses_direct_update_not_rpc(self):
        from backend.app.api.routes.approvals import approve_draft
        import asyncio

        # Tier-1 draft, first approval → pending_second_review
        draft = _make_draft("pending")
        draft["companies"] = {"tier": "1"}  # triggers tier-1 dual review
        db = _mock_db(
            draft=draft,
            rpc_result=[{**draft, "approval_status": "pending_second_review"}],
        )
        db.update_outreach_draft.return_value = {**draft, "approval_status": "pending_second_review"}

        passing_report = MagicMock()
        passing_report.score = 90
        passing_report.passed = True
        passing_report.issues = []

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
            patch("backend.app.api.routes.approvals.get_current_user", return_value={"user_id": "reviewer-1"}),
            patch("backend.app.api.routes.approvals.require_role", return_value=lambda: None),
            patch("backend.app.core.draft_quality.validate_draft", return_value=passing_report),
        ):
            request = MagicMock()
            asyncio.get_event_loop().run_until_complete(
                approve_draft(DRAFT_ID, request, body=None, _role=None, force=False)
            )

        # RPC must NOT have been called — no queue row for pending_second_review
        db.client.rpc.assert_not_called()
        db.update_outreach_draft.assert_called()


class TestRpcFailureHandling:
    """RPC failure raises 500 and does not silently succeed."""

    def test_rpc_exception_raises_http_500(self):
        from backend.app.api.routes.approvals import approve_draft
        from fastapi import HTTPException
        import asyncio

        draft = _make_draft("pending")
        db = _mock_db(draft=draft)
        db.client.rpc.return_value.execute.side_effect = Exception("DB connection lost")

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
            patch("backend.app.api.routes.approvals.get_current_user", return_value={"user_id": ""}),
            patch("backend.app.api.routes.approvals.require_role", return_value=lambda: None),
        ):
            request = MagicMock()
            try:
                asyncio.get_event_loop().run_until_complete(
                    approve_draft(DRAFT_ID, request, body=None, _role=None, force=True)
                )
                assert False, "Expected HTTPException"
            except HTTPException as exc:
                assert exc.status_code == 500


class TestQueueRowContents:
    """RPC is called with correct workspace_id and priority."""

    def test_queue_row_has_correct_workspace_and_priority(self):
        from backend.app.api.routes.approvals import approve_draft
        import asyncio

        draft = _make_draft("pending")
        db = _mock_db(draft=draft, rpc_result=[{**draft, "approval_status": "approved"}])

        with (
            patch("backend.app.api.routes.approvals.get_db", return_value=db),
            patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
            patch("backend.app.api.routes.approvals.get_current_user", return_value={"user_id": ""}),
            patch("backend.app.api.routes.approvals.require_role", return_value=lambda: None),
        ):
            request = MagicMock()
            asyncio.get_event_loop().run_until_complete(
                approve_draft(DRAFT_ID, request, body=None, _role=None, force=True)
            )

        params = db.client.rpc.call_args[0][1]
        assert params["p_workspace_id"] == WORKSPACE_ID
        assert params["p_priority"] == 5
