"""Tests for PR C: provider_events dedup wired into Resend webhook.

Six invariants:

1. test_identical_delivered_is_deduped
   Sending the same email.delivered event twice: first returns 'processed',
   second returns 'deduplicated'.

2. test_identical_bounced_is_deduped
   Same for email.bounced.

3. test_identical_spam_complaint_is_deduped
   Same for email.complained.

4. test_repeated_opens_are_not_deduped
   email.opened events never touch provider_events. Two identical opens both
   return 'processed'.

5. test_open_without_created_at_does_not_block_later_opens
   email.opened with no created_at in payload processes normally and a
   subsequent open with the same email_id also processes normally.

6. test_provider_events_insert_failure_logs_warning_and_continues
   Non-unique DB failure on provider_events insert: _try_record_provider_event
   logs a WARNING and returns True so the event is still processed.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

CONTACT_ID = "contact-prv-001"
COMPANY_ID = "company-prv-001"
MESSAGE_ID = "re_msg001"
_TEST_WEBHOOK_SECRET = "test_resend_secret_prvc"


# ---------------------------------------------------------------------------
# Payload factories
# ---------------------------------------------------------------------------


def _resend_payload(event_type: str, email_id: str = MESSAGE_ID, include_created_at: bool = True) -> dict:
    data: dict = {
        "email_id": email_id,
        "to": ["prospect@company.com"],
        "from": "sender@digitillis.io",
    }
    if include_created_at:
        data["created_at"] = "2026-05-14T12:00:00Z"
    return {"type": event_type, "data": data}


# ---------------------------------------------------------------------------
# DB mock helpers
#
# _make_db(pe_raises) builds a Database-shaped MagicMock where:
#   pe_raises=False  → provider_events insert succeeds (new event)
#   pe_raises=True   → provider_events insert raises a unique-constraint error
#   pe_raises="other" → provider_events insert raises a non-unique error
#
# A per-table dispatch is used so only provider_events insert is affected.
# ---------------------------------------------------------------------------


def _make_db(pe_raises=False) -> MagicMock:
    db = MagicMock()
    db.workspace_id = "ws-prv-001"

    # provider_events table mock
    pe_table = MagicMock()
    if pe_raises is False:
        pe_result = MagicMock()
        pe_result.data = [{"id": "pe-uuid-001"}]
        pe_table.insert.return_value.execute.return_value = pe_result
    elif pe_raises == "unique":
        pe_table.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint"
        )
    elif pe_raises == "other":
        pe_table.insert.return_value.execute.side_effect = Exception(
            "connection pool exhausted"
        )

    # outreach_drafts table mock (update calls must not crash)
    od_table = MagicMock()
    od_table.update.return_value.eq.return_value.execute.return_value.data = []

    # contacts table mock (for signal counters on opened/clicked)
    contacts_table = MagicMock()
    contacts_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"open_count": 0, "click_count": 0}
    ]
    contacts_table.update.return_value.eq.return_value.execute.return_value.data = []

    # engagement_sequences mock (for bounce/complaint path)
    seq_table = MagicMock()
    seq_table.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = []

    def _dispatch(name: str) -> MagicMock:
        if name == "provider_events":
            return pe_table
        if name == "outreach_drafts":
            return od_table
        if name == "contacts":
            return contacts_table
        if name == "engagement_sequences":
            return seq_table
        return MagicMock()

    db.client.table.side_effect = _dispatch

    # _filter_ws chains: draft lookup returns nothing (fallback to _lookup_company_contact)
    db._filter_ws.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    db._filter_ws.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = []

    return db


def _common_patches(db: MagicMock):
    """Return the standard patch stack for the Resend webhook."""
    return [
        patch("backend.app.api.routes.webhooks._get_db_and_workspace", return_value=db),
        patch(
            "backend.app.api.routes.webhooks._lookup_company_contact",
            return_value=(COMPANY_ID, CONTACT_ID),
        ),
        patch("backend.app.api.routes.webhooks._find_thread", return_value=None),
        patch("backend.app.core.suppression.record_suppression", return_value="sup-id-1"),
        patch("backend.app.core.suppression.maybe_escalate_to_company"),
        patch(
            "backend.app.api.routes.webhooks.get_settings",
            return_value=MagicMock(resend_webhook_secret=_TEST_WEBHOOK_SECRET),
        ),
    ]


def _make_app():
    from fastapi import FastAPI
    from backend.app.api.routes.webhooks import router
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Test 1: identical email.delivered is deduped
# ---------------------------------------------------------------------------


def test_identical_delivered_is_deduped():
    from starlette.testclient import TestClient
    payload = _resend_payload("email.delivered")

    # First occurrence: provider_events insert succeeds
    db_new = _make_db(pe_raises=False)
    with _common_patches(db_new)[0], _common_patches(db_new)[1], \
         _common_patches(db_new)[2], _common_patches(db_new)[3], \
         _common_patches(db_new)[4], _common_patches(db_new)[5]:
        client = TestClient(_make_app())
        resp1 = client.post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp1.status_code == 200
    assert resp1.json().get("status") == "processed", f"First call: {resp1.json()}"

    # Second occurrence: unique-constraint violation → deduplicated
    db_dup = _make_db(pe_raises="unique")
    with _common_patches(db_dup)[0], _common_patches(db_dup)[1], \
         _common_patches(db_dup)[2], _common_patches(db_dup)[3], \
         _common_patches(db_dup)[4], _common_patches(db_dup)[5]:
        client2 = TestClient(_make_app())
        resp2 = client2.post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp2.status_code == 200
    assert resp2.json().get("status") == "deduplicated", f"Second call: {resp2.json()}"
    assert f"resend:{MESSAGE_ID}:email.delivered" in resp2.json().get("provider_event_id", "")


# ---------------------------------------------------------------------------
# Test 2: identical email.bounced is deduped
# ---------------------------------------------------------------------------


def test_identical_bounced_is_deduped():
    from starlette.testclient import TestClient
    bounce_id = "re_bounce001"
    payload = _resend_payload("email.bounced", email_id=bounce_id)

    db_new = _make_db(pe_raises=False)
    db_dup = _make_db(pe_raises="unique")

    patches_new = _common_patches(db_new)
    with patches_new[0], patches_new[1], patches_new[2], \
         patches_new[3], patches_new[4], patches_new[5]:
        resp1 = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp1.json().get("status") == "processed", f"First call: {resp1.json()}"

    patches_dup = _common_patches(db_dup)
    with patches_dup[0], patches_dup[1], patches_dup[2], \
         patches_dup[3], patches_dup[4], patches_dup[5]:
        resp2 = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp2.json().get("status") == "deduplicated", f"Second call: {resp2.json()}"
    assert f"resend:{bounce_id}:email.bounced" in resp2.json().get("provider_event_id", "")


# ---------------------------------------------------------------------------
# Test 3: identical email.complained is deduped
# ---------------------------------------------------------------------------


def test_identical_spam_complaint_is_deduped():
    from starlette.testclient import TestClient
    complaint_id = "re_complaint001"
    payload = _resend_payload("email.complained", email_id=complaint_id)

    db_new = _make_db(pe_raises=False)
    db_dup = _make_db(pe_raises="unique")

    patches_new = _common_patches(db_new)
    with patches_new[0], patches_new[1], patches_new[2], \
         patches_new[3], patches_new[4], patches_new[5]:
        resp1 = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp1.json().get("status") == "processed", f"First call: {resp1.json()}"

    patches_dup = _common_patches(db_dup)
    with patches_dup[0], patches_dup[1], patches_dup[2], \
         patches_dup[3], patches_dup[4], patches_dup[5]:
        resp2 = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp2.json().get("status") == "deduplicated", f"Second call: {resp2.json()}"
    assert f"resend:{complaint_id}:email.complained" in resp2.json().get("provider_event_id", "")


# ---------------------------------------------------------------------------
# Test 4: repeated email.opened events are not deduped
# ---------------------------------------------------------------------------


def test_repeated_opens_are_not_deduped():
    """email.opened bypasses provider_events entirely; both opens return 'processed'."""
    from starlette.testclient import TestClient
    open_id = "re_open001"
    payload = _resend_payload("email.opened", email_id=open_id)

    # Use default db — any call to provider_events.insert is unexpected
    db1 = _make_db(pe_raises=False)
    db2 = _make_db(pe_raises=False)

    patches1 = _common_patches(db1)
    with patches1[0], patches1[1], patches1[2], patches1[3], patches1[4], patches1[5]:
        resp1 = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    patches2 = _common_patches(db2)
    with patches2[0], patches2[1], patches2[2], patches2[3], patches2[4], patches2[5]:
        resp2 = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    assert resp1.json().get("status") == "processed", f"Open 1: {resp1.json()}"
    assert resp2.json().get("status") == "processed", f"Open 2: {resp2.json()}"

    # provider_events.insert must never have been called for email.opened
    pe_table_calls_1 = [
        c for c in db1.client.table.call_args_list if c.args == ("provider_events",)
    ]
    pe_table_calls_2 = [
        c for c in db2.client.table.call_args_list if c.args == ("provider_events",)
    ]
    assert not pe_table_calls_1, "provider_events.insert was called for email.opened (must not be)"
    assert not pe_table_calls_2, "provider_events.insert was called for email.opened (must not be)"


# ---------------------------------------------------------------------------
# Test 5: email.opened without created_at does not block later opens
# ---------------------------------------------------------------------------


def test_open_without_created_at_does_not_block_later_opens():
    """Opens without created_at in payload are processed normally.

    Since email.opened is excluded from dedup entirely, the presence or
    absence of created_at in the payload is irrelevant to dedup behavior.
    Both opens must return 'processed'.
    """
    from starlette.testclient import TestClient
    open_id = "re_open002"

    # First open: no created_at
    payload_no_ts = _resend_payload("email.opened", email_id=open_id, include_created_at=False)
    # Second open: has created_at
    payload_with_ts = _resend_payload("email.opened", email_id=open_id, include_created_at=True)

    for payload in (payload_no_ts, payload_with_ts):
        db = _make_db(pe_raises=False)
        patches = _common_patches(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            resp = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

        assert resp.json().get("status") == "processed", (
            f"Open with payload={payload} was not processed: {resp.json()}"
        )

        # provider_events must not have been accessed
        pe_calls = [c for c in db.client.table.call_args_list if c.args == ("provider_events",)]
        assert not pe_calls, "provider_events touched for email.opened"


# ---------------------------------------------------------------------------
# Test 6: provider_events insert failure logs WARNING and still processes
# ---------------------------------------------------------------------------


def test_provider_events_insert_failure_logs_warning_and_continues(caplog):
    """Non-unique DB error on provider_events insert: WARNING logged, event processed."""
    from starlette.testclient import TestClient

    db = _make_db(pe_raises="other")
    payload = _resend_payload("email.delivered", email_id="re_fail001")

    patches = _common_patches(db)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        with caplog.at_level(logging.WARNING, logger="backend.app.api.routes.webhooks"):
            resp = TestClient(_make_app()).post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=payload)

    # Event must still be processed — non-unique failure must not suppress the webhook
    assert resp.json().get("status") == "processed", (
        f"Expected 'processed' on insert failure, got: {resp.json()}"
    )

    # WARNING must appear in logs
    assert any(
        "provider_events" in record.message and "insert failed" in record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    ), f"Expected WARNING about provider_events insert failure. Log records: {[r.message for r in caplog.records]}"
