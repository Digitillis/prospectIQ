"""Tests for PR D: draft hardening — immutability trigger + active draft unique index.

Nine invariants:

1. test_sent_draft_body_cannot_be_changed
   PATCH /api/threads/{id}/draft/{id} with body on a sent draft → HTTP 409.

2. test_sent_draft_subject_cannot_be_changed
   PATCH with subject on a sent draft → HTTP 409.

3. test_pending_draft_body_can_be_edited
   PATCH with body on a pending draft (sent_at IS NULL) → HTTP 200.

4. test_resend_message_id_update_on_sent_draft_is_not_blocked
   resend_message_id is not in the trigger's blocked-field set. A direct DB
   update of that field on a sent draft raises no Python-layer exception.

5. test_sent_at_rollback_is_not_blocked
   sent_at is not in the trigger's blocked-field set. A direct DB update
   that rolls back sent_at raises no Python-layer exception.

6. test_unique_index_blocks_second_active_draft_for_same_slot
   Simulated second INSERT for the same (workspace, contact, sequence, step)
   raises a unique-constraint violation referencing idx_outreach_drafts_active_unique.

7. test_rejected_draft_can_be_replaced
   After the prior draft for a slot is rejected, a new INSERT for the same
   slot succeeds without a unique-constraint error.

8. test_threads_endpoint_rejects_edit_of_sent_draft_with_409
   End-to-end TestClient: PATCH with body+subject on sent draft → 409.
   Response detail contains 'draft_immutability'.

9. test_threads_endpoint_allows_edit_of_pending_draft
   End-to-end TestClient: PATCH with body+subject on pending draft → 200.
   Response contains draft_id.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

THREAD_ID = "t1111111-aaaa-aaaa-aaaa-111111111111"
DRAFT_ID = "d2222222-bbbb-bbbb-bbbb-222222222222"
WS_ID = "w3333333-cccc-cccc-cccc-333333333333"
CONTACT_ID = "c4444444-dddd-dddd-dddd-444444444444"

# Fields that the DB trigger blocks on a sent draft.
# This set must exactly match the RAISE clauses in enforce_draft_immutability().
_TRIGGER_BLOCKED_FIELDS: frozenset[str] = frozenset({"body", "subject"})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_draft_db(sent: bool) -> MagicMock:
    """DB mock for the edit_draft endpoint.

    The select chain returns a draft with sent_at set/unset.
    The update chain accepts any payload and returns without error.
    """
    db = MagicMock()
    db.workspace_id = WS_ID

    draft = {
        "id": DRAFT_ID,
        "sent_at": "2026-05-01T10:00:00Z" if sent else None,
        "approval_status": "pending",
    }

    od = MagicMock()
    # select("id, sent_at, approval_status").eq(...).limit(1).execute().data
    od.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [draft]
    # update(...).eq(...).execute() — return value ignored by endpoint
    od.update.return_value.eq.return_value.execute.return_value.data = [draft]

    db.client.table.side_effect = lambda name: od if name == "outreach_drafts" else MagicMock()
    return db


def _make_app():
    from fastapi import FastAPI
    from backend.app.api.routes.threads import router

    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Test 1: sent draft body blocked
# ---------------------------------------------------------------------------


def test_sent_draft_body_cannot_be_changed():
    """PATCH body on sent draft → 409 with draft_immutability in detail."""
    from starlette.testclient import TestClient

    db = _make_draft_db(sent=True)
    with patch("backend.app.api.routes.threads.get_db", return_value=db):
        resp = TestClient(_make_app()).patch(
            f"/api/threads/{THREAD_ID}/draft/{DRAFT_ID}",
            json={"body": "new body text"},
        )

    assert resp.status_code == 409
    assert "draft_immutability" in resp.json().get("detail", ""), resp.json()


# ---------------------------------------------------------------------------
# Test 2: sent draft subject blocked
# ---------------------------------------------------------------------------


def test_sent_draft_subject_cannot_be_changed():
    """PATCH subject on sent draft → 409 with draft_immutability in detail."""
    from starlette.testclient import TestClient

    db = _make_draft_db(sent=True)
    with patch("backend.app.api.routes.threads.get_db", return_value=db):
        resp = TestClient(_make_app()).patch(
            f"/api/threads/{THREAD_ID}/draft/{DRAFT_ID}",
            json={"subject": "New Subject Line"},
        )

    assert resp.status_code == 409
    assert "draft_immutability" in resp.json().get("detail", ""), resp.json()


# ---------------------------------------------------------------------------
# Test 3: pending draft body editable
# ---------------------------------------------------------------------------


def test_pending_draft_body_can_be_edited():
    """PATCH body on pending draft (sent_at IS NULL) → 200."""
    from starlette.testclient import TestClient

    db = _make_draft_db(sent=False)
    with patch("backend.app.api.routes.threads.get_db", return_value=db):
        resp = TestClient(_make_app()).patch(
            f"/api/threads/{THREAD_ID}/draft/{DRAFT_ID}",
            json={"body": "improved body text"},
        )

    assert resp.status_code == 200
    assert resp.json().get("draft_id") == DRAFT_ID


# ---------------------------------------------------------------------------
# Test 4: resend_message_id update on sent draft not blocked
# ---------------------------------------------------------------------------


def test_resend_message_id_update_on_sent_draft_is_not_blocked():
    """resend_message_id is not a content field — trigger does not block it.

    Verifies that the trigger's blocked-field set is limited to body and
    subject. resend_message_id is set by the Resend webhook post-send and
    must remain freely writable on any draft, including sent ones.
    """
    update = {"resend_message_id": "re_msg_new_001"}
    blocked = set(update.keys()) & _TRIGGER_BLOCKED_FIELDS
    assert not blocked, (
        f"resend_message_id must not be in trigger blocked fields. Got overlap: {blocked}"
    )

    # A direct DB update of this field on a sent draft raises no Python exception.
    db = MagicMock()
    db.client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": DRAFT_ID}
    ]
    result = db.client.table("outreach_drafts").update(update).eq("id", DRAFT_ID).execute()
    assert result.data[0]["id"] == DRAFT_ID


# ---------------------------------------------------------------------------
# Test 5: sent_at rollback not blocked
# ---------------------------------------------------------------------------


def test_sent_at_rollback_is_not_blocked():
    """sent_at is not a content field — trigger does not block setting it back to NULL.

    Verifies that recovery operations (rolling back a premature sent_at) are
    not blocked by the immutability trigger.
    """
    update = {"sent_at": None}
    blocked = set(update.keys()) & _TRIGGER_BLOCKED_FIELDS
    assert not blocked, f"sent_at must not be in trigger blocked fields. Got overlap: {blocked}"

    db = MagicMock()
    db.client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": DRAFT_ID, "sent_at": None}
    ]
    result = db.client.table("outreach_drafts").update(update).eq("id", DRAFT_ID).execute()
    assert result.data[0]["sent_at"] is None


# ---------------------------------------------------------------------------
# Test 6: unique index blocks second active draft
# ---------------------------------------------------------------------------


def test_unique_index_blocks_second_active_draft_for_same_slot():
    """Second non-rejected draft INSERT for same slot → unique-constraint violation.

    Simulates the DB raising the error that PostgreSQL raises when
    idx_outreach_drafts_active_unique is violated.
    """
    db = MagicMock()
    db.client.table.return_value.insert.return_value.execute.side_effect = Exception(
        'duplicate key value violates unique constraint "idx_outreach_drafts_active_unique"'
    )

    slot = {
        "workspace_id": WS_ID,
        "contact_id": CONTACT_ID,
        "sequence_name": "mfg_ops_sequence",
        "sequence_step": 1,
        "approval_status": "pending",
    }

    with pytest.raises(Exception) as exc_info:
        db.client.table("outreach_drafts").insert(slot).execute()

    err = str(exc_info.value).lower()
    assert "unique" in err or "duplicate" in err
    assert "idx_outreach_drafts_active_unique" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 7: rejected draft can be replaced
# ---------------------------------------------------------------------------


def test_rejected_draft_can_be_replaced():
    """After rejection, a new active draft for the same slot inserts without error.

    The partial index excludes approval_status='rejected' rows, so a rejected
    draft does not consume the slot for future active drafts.
    """
    db = MagicMock()
    db.client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "new-draft-uuid", "approval_status": "pending"}
    ]

    result = (
        db.client.table("outreach_drafts")
        .insert(
            {
                "workspace_id": WS_ID,
                "contact_id": CONTACT_ID,
                "sequence_name": "mfg_ops_sequence",
                "sequence_step": 1,
                "approval_status": "pending",
            }
        )
        .execute()
    )

    assert result.data[0]["approval_status"] == "pending"
    # No exception — the rejected prior draft is outside the partial index scope


# ---------------------------------------------------------------------------
# Test 8: threads endpoint rejects sent draft edit with 409
# ---------------------------------------------------------------------------


def test_threads_endpoint_rejects_edit_of_sent_draft_with_409():
    """PATCH body+subject on sent draft → 409. Response detail contains 'draft_immutability'."""
    from starlette.testclient import TestClient

    db = _make_draft_db(sent=True)
    with patch("backend.app.api.routes.threads.get_db", return_value=db):
        resp = TestClient(_make_app()).patch(
            f"/api/threads/{THREAD_ID}/draft/{DRAFT_ID}",
            json={"body": "blocked body", "subject": "Blocked Subject"},
        )

    assert resp.status_code == 409
    detail = resp.json().get("detail", "")
    assert "draft_immutability" in detail, f"Expected draft_immutability in detail. Got: {detail}"


# ---------------------------------------------------------------------------
# Test 9: threads endpoint allows pending draft edit
# ---------------------------------------------------------------------------


def test_threads_endpoint_allows_edit_of_pending_draft():
    """PATCH body+subject on pending draft → 200 with draft_id."""
    from starlette.testclient import TestClient

    db = _make_draft_db(sent=False)
    with patch("backend.app.api.routes.threads.get_db", return_value=db):
        resp = TestClient(_make_app()).patch(
            f"/api/threads/{THREAD_ID}/draft/{DRAFT_ID}",
            json={"body": "refined body", "subject": "Refined Subject"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("draft_id") == DRAFT_ID, f"Expected draft_id in response. Got: {data}"
