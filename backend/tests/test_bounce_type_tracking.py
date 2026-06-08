"""Tests for bounce-type tracking (migration 063 + webhook changes).

Three invariants verified:

1. Hard bounce (Resend type="Permanent"):
   - draft gets bounce_type='hard', resend_status='bounced', bounce_smtp_code stored
   - contact added to DNC
   - sequences CANCELLED

2. Soft bounce (Resend type="Transient"):
   - draft gets bounce_type='soft', resend_status='bounced'
   - contact NOT added to DNC  (address is reachable; may retry)
   - sequences PAUSED (not cancelled)

3. Spam complaint:
   - no bounce_type stored on draft
   - contact added to DNC
   - sequences CANCELLED
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

CONTACT_ID = "contact-bounce-001"
COMPANY_ID = "company-bounce-001"
RECIPIENT_EMAIL = "target@prospect.com"
SENDER_EMAIL = "sender@digitillis.io"
DRAFT_ID = "draft-bounce-001"
_TEST_WEBHOOK_SECRET = "test_bounce_secret_xyz"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hard_bounce_payload(
    diagnostic_code: str = "smtp;550 5.1.10 RESOLVER.ADR.RecipientNotFound",
) -> dict:
    return {
        "type": "email.bounced",
        "data": {
            "to": [RECIPIENT_EMAIL],
            "from": SENDER_EMAIL,
            "bounce": {
                "type": "Permanent",
                "subType": "General",
                "diagnosticCode": [diagnostic_code],
            },
        },
    }


def _soft_bounce_payload() -> dict:
    return {
        "type": "email.bounced",
        "data": {
            "to": [RECIPIENT_EMAIL],
            "from": SENDER_EMAIL,
            "bounce": {
                "type": "Transient",
                "subType": "MailboxFull",
                "diagnosticCode": ["smtp;452 4.2.2 Mailbox full"],
            },
        },
    }


def _complaint_payload() -> dict:
    return {
        "type": "email.complained",
        "data": {
            "to": [RECIPIENT_EMAIL],
            "from": SENDER_EMAIL,
        },
    }


def _make_db_mock() -> MagicMock:
    """Minimal DB mock.

    The engagement_sequences query (select→eq→in_→execute) must return .data as
    a real list so iteration does not raise. All other table calls use MagicMock.
    """
    db = MagicMock()
    # Engagement sequences: return one active sequence so the status update is exercised.
    seq_result = MagicMock()
    seq_result.data = [{"id": "seq-001"}]
    (
        db.client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value
    ) = seq_result
    return db


def _make_settings_mock() -> MagicMock:
    s = MagicMock()
    s.resend_webhook_secret = _TEST_WEBHOOK_SECRET
    return s


def _build_test_client():
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from backend.app.api.routes.webhooks import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def _post(tc, payload: dict):
    return tc.post(
        f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}",
        json=payload,
    )


# ---------------------------------------------------------------------------
# Hard bounce tests
# ---------------------------------------------------------------------------


class TestHardBounce:
    def _run(self, db_mock):
        with (
            patch("backend.app.api.routes.webhooks._get_db_and_workspace", return_value=db_mock),
            patch(
                "backend.app.api.routes.webhooks._lookup_company_contact",
                return_value=(COMPANY_ID, CONTACT_ID),
            ),
            patch("backend.app.api.routes.webhooks._find_thread", return_value=None),
            patch("backend.app.core.suppression.record_suppression", return_value="sup-hard-1"),
            patch("backend.app.core.suppression.maybe_escalate_to_company"),
            patch(
                "backend.app.api.routes.webhooks.get_settings", return_value=_make_settings_mock()
            ),
        ):
            return _post(_build_test_client(), _hard_bounce_payload())

    def test_hard_bounce_returns_processed(self):
        resp = self._run(_make_db_mock())
        assert resp.status_code == 200
        assert resp.json().get("status") == "processed"

    def test_hard_bounce_stores_bounce_type_on_draft(self):
        """Draft update must include bounce_type='hard' and resend_status='bounced'."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        draft_updates = [c[0][0] for c in update_calls]
        # Find the call that stamps the draft (has bounce_type or resend_status)
        bounce_stamp = next(
            (u for u in draft_updates if "bounce_type" in u or "resend_status" in u),
            None,
        )
        assert bounce_stamp is not None, "No draft update with bounce_type found"
        assert bounce_stamp.get("bounce_type") == "hard"
        assert bounce_stamp.get("resend_status") == "bounced"

    def test_hard_bounce_stores_smtp_code(self):
        """SMTP diagnostic code is stored on the draft (max 200 chars)."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        draft_updates = [c[0][0] for c in update_calls]
        bounce_stamp = next((u for u in draft_updates if "bounce_smtp_code" in u), None)
        assert bounce_stamp is not None, "No draft update with bounce_smtp_code found"
        code = bounce_stamp["bounce_smtp_code"]
        assert "550" in code or "RecipientNotFound" in code
        assert len(code) <= 200

    def test_hard_bounce_adds_to_dnc(self):
        """Hard bounce must call add_to_dnc."""
        db = _make_db_mock()
        self._run(db)
        db.add_to_dnc.assert_called_once()
        args = db.add_to_dnc.call_args
        assert RECIPIENT_EMAIL in args[0] or args[1].get("email") == RECIPIENT_EMAIL

    def test_hard_bounce_cancels_sequences(self):
        """Sequences are CANCELLED on hard bounce."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        seq_updates = [
            c[0][0] for c in update_calls if c[0][0].get("status") in ("cancelled", "paused")
        ]
        assert any(u["status"] == "cancelled" for u in seq_updates), (
            "Expected sequences to be cancelled on hard bounce"
        )


# ---------------------------------------------------------------------------
# Soft bounce tests
# ---------------------------------------------------------------------------


class TestSoftBounce:
    def _run(self, db_mock):
        with (
            patch("backend.app.api.routes.webhooks._get_db_and_workspace", return_value=db_mock),
            patch(
                "backend.app.api.routes.webhooks._lookup_company_contact",
                return_value=(COMPANY_ID, CONTACT_ID),
            ),
            patch("backend.app.api.routes.webhooks._find_thread", return_value=None),
            patch("backend.app.core.suppression.record_suppression", return_value="sup-soft-1"),
            patch("backend.app.core.suppression.maybe_escalate_to_company"),
            patch(
                "backend.app.api.routes.webhooks.get_settings", return_value=_make_settings_mock()
            ),
        ):
            return _post(_build_test_client(), _soft_bounce_payload())

    def test_soft_bounce_returns_processed(self):
        resp = self._run(_make_db_mock())
        assert resp.status_code == 200
        assert resp.json().get("status") == "processed"

    def test_soft_bounce_stores_soft_type_on_draft(self):
        """Draft update must include bounce_type='soft'."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        draft_updates = [c[0][0] for c in update_calls]
        bounce_stamp = next((u for u in draft_updates if "bounce_type" in u), None)
        assert bounce_stamp is not None, "No draft update with bounce_type found"
        assert bounce_stamp.get("bounce_type") == "soft"
        assert bounce_stamp.get("resend_status") == "bounced"

    def test_soft_bounce_does_not_add_to_dnc(self):
        """Soft bounce must NOT call add_to_dnc — address is still reachable."""
        db = _make_db_mock()
        self._run(db)
        db.add_to_dnc.assert_not_called()

    def test_soft_bounce_pauses_sequences(self):
        """Sequences are PAUSED (not cancelled) on soft bounce."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        seq_updates = [
            c[0][0] for c in update_calls if c[0][0].get("status") in ("cancelled", "paused")
        ]
        assert seq_updates, "Expected a sequence status update"
        assert all(u["status"] == "paused" for u in seq_updates), (
            f"Expected paused, got: {[u['status'] for u in seq_updates]}"
        )
        assert not any(u["status"] == "cancelled" for u in seq_updates), (
            "Soft bounce must not cancel sequences"
        )


# ---------------------------------------------------------------------------
# Complaint tests
# ---------------------------------------------------------------------------


class TestComplaint:
    def _run(self, db_mock):
        with (
            patch("backend.app.api.routes.webhooks._get_db_and_workspace", return_value=db_mock),
            patch(
                "backend.app.api.routes.webhooks._lookup_company_contact",
                return_value=(COMPANY_ID, CONTACT_ID),
            ),
            patch("backend.app.api.routes.webhooks._find_thread", return_value=None),
            patch("backend.app.core.suppression.record_suppression", return_value="sup-cmp-1"),
            patch(
                "backend.app.api.routes.webhooks.get_settings", return_value=_make_settings_mock()
            ),
        ):
            return _post(_build_test_client(), _complaint_payload())

    def test_complaint_returns_processed(self):
        resp = self._run(_make_db_mock())
        assert resp.status_code == 200
        assert resp.json().get("status") == "processed"

    def test_complaint_adds_to_dnc(self):
        """Complaint must add recipient to DNC."""
        db = _make_db_mock()
        self._run(db)
        db.add_to_dnc.assert_called_once()

    def test_complaint_cancels_sequences(self):
        """Sequences are CANCELLED on complaint."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        seq_updates = [
            c[0][0] for c in update_calls if c[0][0].get("status") in ("cancelled", "paused")
        ]
        assert any(u["status"] == "cancelled" for u in seq_updates), (
            "Expected sequences to be cancelled on complaint"
        )

    def test_complaint_does_not_store_bounce_type(self):
        """Complaints are not bounces — bounce_type should not be set."""
        db = _make_db_mock()
        self._run(db)

        update_calls = db.client.table.return_value.update.call_args_list
        draft_updates = [c[0][0] for c in update_calls]
        assert not any("bounce_type" in u for u in draft_updates), (
            "bounce_type must not be stored for complaints (not a bounce)"
        )
