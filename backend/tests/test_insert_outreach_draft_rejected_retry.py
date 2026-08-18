"""insert_outreach_draft() must actually persist a retry over a rejected draft.

Previously a 'rejected' existing row was treated identically to
'pending'/'approved'/'edited' by the dedup guard: the method returned the
stale existing row untouched and never wrote the new (corrected) content.
Callers like scripts/piq_write_drafts.py build their own local row object
and report success/failure from that object's approval_status, not from
what this method actually returns — so a retry with fixed content reported
"written" while the DB kept the original rejected body and rejection_reason
forever. Observed directly 2026-08-17/18 during a real test batch: two
drafts rejected for a fabrication-gate false positive were "fixed" and
rewritten, the writer script reported success, and a direct DB read-back
showed both drafts still rejected with the original content.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.core.database import Database


def _make_db(existing_row: dict, updated_row: dict) -> tuple[Database, MagicMock]:
    db = Database.__new__(Database)
    db.workspace_id = "ws-1"
    db.client = MagicMock()

    # SELECT chain: table().select().eq(workspace_id).eq(company_id)
    #   .eq(contact_id).eq(sequence_step).in_(...).limit(1).execute()
    # _filter_ws() applies the workspace_id .eq() BEFORE the three explicit
    # .eq() calls in insert_outreach_draft, so this is 4 .eq() hops total.
    select_mock = db.client.table.return_value.select.return_value
    eq1 = select_mock.eq.return_value  # workspace_id (_filter_ws)
    eq2 = eq1.eq.return_value  # company_id
    eq3 = eq2.eq.return_value  # contact_id
    eq4 = eq3.eq.return_value  # sequence_step
    eq4.in_.return_value.limit.return_value.execute.return_value.data = [existing_row]

    # UPDATE chain: table().update(data).eq(id).eq(workspace_id).execute()
    update_mock = db.client.table.return_value.update.return_value
    update_mock.eq.return_value.eq.return_value.execute.return_value.data = [updated_row]

    return db, db.client


def test_rejected_existing_draft_is_updated_not_returned_stale():
    existing_row = {
        "id": "draft-1",
        "approval_status": "rejected",
        "rejection_reason": "auto_rejected|fabricated_anecdote:'a customer complaint'",
    }
    new_body = "Hi Marcus, corrected body with no fabrication trigger."
    updated_row = {
        "id": "draft-1",
        "approval_status": "pending",
        "body": new_body,
        "rejection_reason": None,
    }
    db, mock_client = _make_db(existing_row, updated_row)

    new_data = {
        "company_id": "co-1",
        "contact_id": "ct-1",
        "sequence_step": 2,
        "subject": "Consistent roast profile across plants",
        "body": new_body,
        "approval_status": "pending",
        # No rejection_reason key -- a clean retry doesn't carry one.
    }

    result = db.insert_outreach_draft(new_data)

    assert mock_client.table.return_value.update.called, (
        "expected an UPDATE call against outreach_drafts when the existing row is rejected — "
        "returning the stale row untouched silently discards the retry"
    )
    update_call_args = mock_client.table.return_value.update.call_args[0][0]
    assert update_call_args["body"] == new_body, "update payload must carry the corrected content"
    assert update_call_args["rejection_reason"] is None, (
        "rejection_reason must be explicitly cleared on a clean retry, or the stale reason "
        "survives next to approval_status='pending'"
    )
    assert result["id"] == "draft-1"
    assert result["approval_status"] == "pending"


def test_rejected_existing_draft_update_preserves_new_rejection_reason_if_still_rejected():
    """If the retried content STILL trips the integrity gate, the caller's own
    rejection_reason must survive into the update payload, not get silently
    cleared by the setdefault."""
    existing_row = {
        "id": "draft-1",
        "approval_status": "rejected",
        "rejection_reason": "auto_rejected|fabricated_anecdote:'a customer complaint'",
    }
    updated_row = {"id": "draft-1", "approval_status": "rejected"}
    db, mock_client = _make_db(existing_row, updated_row)

    new_data = {
        "company_id": "co-1",
        "contact_id": "ct-1",
        "sequence_step": 2,
        "subject": "s",
        "body": "still bad body",
        "approval_status": "rejected",
        "rejection_reason": "auto_rejected|recycled_stat:'23-41%'",
    }

    db.insert_outreach_draft(new_data)

    update_call_args = mock_client.table.return_value.update.call_args[0][0]
    assert update_call_args["rejection_reason"] == "auto_rejected|recycled_stat:'23-41%'"


def test_pending_existing_draft_is_still_returned_untouched():
    """Non-rejected statuses keep the original dedup-skip behavior — this
    guard must not start overwriting live pending/approved/edited drafts."""
    existing_row = {"id": "draft-1", "approval_status": "pending"}
    db, mock_client = _make_db(existing_row, {})

    new_data = {
        "company_id": "co-1",
        "contact_id": "ct-1",
        "sequence_step": 2,
        "subject": "s",
        "body": "b",
        "approval_status": "pending",
    }

    result = db.insert_outreach_draft(new_data)

    assert not mock_client.table.return_value.update.called
    assert result == existing_row
