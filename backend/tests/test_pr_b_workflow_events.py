"""Tests for PR B: workflow_events foundation.

Five invariants:

1. test_approve_emits_workflow_event
   approve_draft calls emit_workflow_event with entity_type='draft',
   entity_id=draft_id, event_type='draft.approved', actor_type='human'.

2. test_reject_emits_workflow_event
   reject_draft calls emit_workflow_event with event_type='draft.rejected',
   to_state='rejected'.

3. test_approve_succeeds_when_workflow_event_insert_fails
   If the workflow_events DB insert raises, approve_draft still returns
   {"message": "Draft approved"} — the event failure is non-fatal.

4. test_reject_succeeds_when_workflow_event_insert_fails
   Same guarantee for reject_draft.

5. test_emit_workflow_event_is_append_only
   emit_workflow_event calls .insert() exactly once and never calls
   .update() or .delete() on the workflow_events table.

Tests 1-4 call the route handler coroutines directly with _role=None and
force=True (approve only) to bypass FastAPI DI and the quality/tier gates.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

DRAFT_ID = "draft-abc-001"
WORKSPACE_ID = "ws-test-001"


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


def _run(coro):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


def _mock_db_for_approve() -> MagicMock:
    """Database mock shaped for approve_draft(force=True).

    With force=True the handler still executes the draft_lookup
    (db._filter_ws(...).eq("id", draft_id).execute().data) and then
    db.update_outreach_draft(). Both must succeed.
    """
    db = MagicMock()
    draft_row = {
        "id": DRAFT_ID,
        "approval_status": "pending",
        "approved_by": None,
        "companies": {"tier": 2},
    }
    db._filter_ws.return_value.eq.return_value.execute.return_value.data = [draft_row]
    db.update_outreach_draft.return_value = {
        "id": DRAFT_ID,
        "approval_status": "approved",
        "sequence_name": "email_value",
        "channel": "email",
    }
    return db


def _mock_db_for_reject() -> MagicMock:
    db = MagicMock()
    db.update_outreach_draft.return_value = {
        "id": DRAFT_ID,
        "approval_status": "rejected",
    }
    return db


def _approvals_patches(mock_db: MagicMock, extra: dict | None = None):
    """Context manager stack for approve_draft / reject_draft tests."""
    patches = {
        "backend.app.api.routes.approvals.get_db": mock_db,
        "backend.app.api.routes.approvals.get_workspace_id": WORKSPACE_ID,
        "backend.app.api.routes.approvals.log_audit_event_from_ctx": MagicMock(),
    }
    if extra:
        patches.update(extra)
    return patches


# ---------------------------------------------------------------------------
# Test 1: approve emits a workflow_event
# ---------------------------------------------------------------------------


def test_approve_emits_workflow_event():
    from backend.app.api.routes.approvals import approve_draft

    mock_db = _mock_db_for_approve()
    mock_emit = MagicMock(return_value="event-uuid-001")

    with (
        patch("backend.app.api.routes.approvals.get_db", return_value=mock_db),
        patch(
            "backend.app.api.routes.approvals.get_current_user",
            return_value={"user_id": "reviewer-1"},
        ),
        patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
        patch("backend.app.api.routes.approvals.log_audit_event_from_ctx"),
        patch("backend.app.api.routes.approvals.emit_workflow_event", mock_emit),
    ):
        result = _run(
            approve_draft(DRAFT_ID, request=MagicMock(), body=None, _role=None, force=True)
        )

    assert result.get("message") == "Draft approved"
    mock_emit.assert_called_once()

    kwargs = mock_emit.call_args.kwargs
    assert kwargs["entity_type"] == "draft"
    assert kwargs["entity_id"] == DRAFT_ID
    assert kwargs["event_type"] in ("draft.approved", "draft.edited")
    assert kwargs["actor_type"] == "human"
    assert kwargs["workspace_id"] == WORKSPACE_ID


# ---------------------------------------------------------------------------
# Test 2: reject emits a workflow_event
# ---------------------------------------------------------------------------


def test_reject_emits_workflow_event():
    from backend.app.api.routes.approvals import reject_draft, RejectRequest

    mock_db = _mock_db_for_reject()
    mock_emit = MagicMock(return_value="event-uuid-002")

    with (
        patch("backend.app.api.routes.approvals.get_db", return_value=mock_db),
        patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
        patch("backend.app.api.routes.approvals.log_audit_event_from_ctx"),
        patch("backend.app.api.routes.approvals.emit_workflow_event", mock_emit),
    ):
        result = _run(
            reject_draft(DRAFT_ID, body=RejectRequest(rejection_reason="off-brand"), _role=None)
        )

    assert result.get("message") == "Draft rejected"
    mock_emit.assert_called_once()

    kwargs = mock_emit.call_args.kwargs
    assert kwargs["entity_type"] == "draft"
    assert kwargs["entity_id"] == DRAFT_ID
    assert kwargs["event_type"] == "draft.rejected"
    assert kwargs["to_state"] == "rejected"
    assert kwargs["workspace_id"] == WORKSPACE_ID


# ---------------------------------------------------------------------------
# Test 3: Approval still succeeds when workflow_events DB insert raises
# ---------------------------------------------------------------------------


def test_approve_succeeds_when_workflow_event_insert_fails():
    """Verify non-fatal: DB error on workflow_events insert must not crash the endpoint."""
    from backend.app.api.routes.approvals import approve_draft

    mock_db = _mock_db_for_approve()
    # Make db.client.table("workflow_events").insert(...).execute() raise
    mock_db.client.table.return_value.insert.return_value.execute.side_effect = Exception(
        "workflow_events: connection pool exhausted"
    )

    with (
        patch("backend.app.api.routes.approvals.get_db", return_value=mock_db),
        patch(
            "backend.app.api.routes.approvals.get_current_user",
            return_value={"user_id": "reviewer-1"},
        ),
        patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
        patch("backend.app.api.routes.approvals.log_audit_event_from_ctx"),
    ):
        # Must not raise — emit_workflow_event swallows its own exceptions
        result = _run(
            approve_draft(DRAFT_ID, request=MagicMock(), body=None, _role=None, force=True)
        )

    assert result.get("message") == "Draft approved", f"Expected 'Draft approved', got: {result}"


# ---------------------------------------------------------------------------
# Test 4: Rejection still succeeds when workflow_events DB insert raises
# ---------------------------------------------------------------------------


def test_reject_succeeds_when_workflow_event_insert_fails():
    """Verify non-fatal: DB error on workflow_events insert must not crash the endpoint."""
    from backend.app.api.routes.approvals import reject_draft, RejectRequest

    mock_db = _mock_db_for_reject()
    mock_db.client.table.return_value.insert.return_value.execute.side_effect = Exception(
        "workflow_events: table does not exist"
    )

    with (
        patch("backend.app.api.routes.approvals.get_db", return_value=mock_db),
        patch("backend.app.api.routes.approvals.get_workspace_id", return_value=WORKSPACE_ID),
        patch("backend.app.api.routes.approvals.log_audit_event_from_ctx"),
    ):
        result = _run(
            reject_draft(DRAFT_ID, body=RejectRequest(rejection_reason="test"), _role=None)
        )

    assert result.get("message") == "Draft rejected", f"Expected 'Draft rejected', got: {result}"


# ---------------------------------------------------------------------------
# Test 5: emit_workflow_event only ever calls .insert() — append-only
# ---------------------------------------------------------------------------


def test_emit_workflow_event_is_append_only():
    """emit_workflow_event inserts exactly one row and never calls .update() or .delete()."""
    from backend.app.core.audit_events import emit_workflow_event

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.data = [{"id": "event-uuid-001"}]
    mock_db.client.table.return_value.insert.return_value.execute.return_value = mock_result

    returned_id = emit_workflow_event(
        mock_db,
        workspace_id=WORKSPACE_ID,
        entity_type="draft",
        entity_id=DRAFT_ID,
        event_type="draft.approved",
        to_state="approved",
        actor_type="human",
        actor_id="reviewer-1",
        triggered_by="/api/approvals/draft-abc-001/approve",
    )

    # Returns the event UUID from DB
    assert returned_id == "event-uuid-001"

    # Called db.client.table("workflow_events") exactly once
    mock_db.client.table.assert_called_once_with("workflow_events")

    # .insert() called exactly once
    mock_db.client.table.return_value.insert.assert_called_once()

    # .update() and .delete() must never be called — append-only invariant
    mock_db.client.table.return_value.update.assert_not_called()
    mock_db.client.table.return_value.delete.assert_not_called()
