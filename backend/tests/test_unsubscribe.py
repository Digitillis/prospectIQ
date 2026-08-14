"""Unsubscribe mechanism: token generation/verification, DNC recording,
compliance footer, and the two send sites that must never send without it.

CAN-SPAM §7704(a)(3)/(5) gap this closes: ProspectIQ previously sent
unsolicited commercial email with no unsubscribe mechanism and no physical
address. See backend/app/core/unsubscribe.py and
backend/app/api/routes/unsubscribe.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Token generation / verification
# ---------------------------------------------------------------------------


def _settings(webhook_secret="test-secret-value", app_base_url="https://app.example.com"):
    s = MagicMock()
    s.webhook_secret = webhook_secret
    s.app_base_url = app_base_url
    return s


def test_token_is_deterministic_for_same_inputs():
    from backend.app.core.unsubscribe import generate_unsubscribe_token

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        t1 = generate_unsubscribe_token("person@example.com", "draft-123")
        t2 = generate_unsubscribe_token("person@example.com", "draft-123")
    assert t1 == t2


def test_token_differs_for_different_email():
    from backend.app.core.unsubscribe import generate_unsubscribe_token

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        t1 = generate_unsubscribe_token("a@example.com", "draft-123")
        t2 = generate_unsubscribe_token("b@example.com", "draft-123")
    assert t1 != t2


def test_token_verifies_correctly():
    from backend.app.core.unsubscribe import generate_unsubscribe_token, verify_unsubscribe_token

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        token = generate_unsubscribe_token("person@example.com", "draft-123")
        assert verify_unsubscribe_token("person@example.com", "draft-123", token) is True


def test_tampered_token_fails_verification():
    from backend.app.core.unsubscribe import generate_unsubscribe_token, verify_unsubscribe_token

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        token = generate_unsubscribe_token("person@example.com", "draft-123")
        tampered = token[:-4] + "abcd"
        assert verify_unsubscribe_token("person@example.com", "draft-123", tampered) is False


def test_token_for_different_draft_does_not_verify():
    """A token issued for draft-123 must not verify against draft-456 — this
    is what stops one leaked link from unsubscribing a different send.
    """
    from backend.app.core.unsubscribe import generate_unsubscribe_token, verify_unsubscribe_token

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        token = generate_unsubscribe_token("person@example.com", "draft-123")
        assert verify_unsubscribe_token("person@example.com", "draft-456", token) is False


def test_generate_token_raises_when_secret_unconfigured():
    from backend.app.core.unsubscribe import UnsubscribeConfigError, generate_unsubscribe_token

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings(webhook_secret="")):
        with pytest.raises(UnsubscribeConfigError):
            generate_unsubscribe_token("person@example.com", "draft-123")


def test_build_unsubscribe_url_contains_email_and_token():
    from backend.app.core.unsubscribe import build_unsubscribe_url

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        url = build_unsubscribe_url("person@example.com", "draft-123")
    assert "email=person%40example.com" in url
    assert "draft_id=draft-123" in url
    assert "token=" in url
    assert url.startswith("https://app.example.com/api/unsubscribe")


# ---------------------------------------------------------------------------
# resend_unsubscribe_headers — the headers that must be on every send
# ---------------------------------------------------------------------------


def test_resend_headers_include_list_unsubscribe_and_one_click():
    from backend.app.core.unsubscribe import resend_unsubscribe_headers

    with patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()):
        headers = resend_unsubscribe_headers("person@example.com", "draft-123")
    assert "List-Unsubscribe" in headers
    assert headers["List-Unsubscribe"].startswith("<") and headers["List-Unsubscribe"].endswith(">")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


# ---------------------------------------------------------------------------
# compliance_footer_text — fails closed without a physical address
# ---------------------------------------------------------------------------


def test_compliance_footer_raises_without_physical_address():
    from backend.app.core.unsubscribe import ComplianceConfigError, compliance_footer_text

    guidelines = {"sender": {"physical_address": "", "company": "Acme"}}
    with (
        patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()),
        patch("backend.app.core.config.get_outreach_guidelines", return_value=guidelines),
    ):
        with pytest.raises(ComplianceConfigError):
            compliance_footer_text("person@example.com", "draft-123")


def test_compliance_footer_includes_address_and_link_when_configured():
    from backend.app.core.unsubscribe import compliance_footer_text

    guidelines = {
        "sender": {"physical_address": "123 Main St, Chicago, IL 60601", "company": "Acme"}
    }
    with (
        patch("backend.app.core.unsubscribe.get_settings", return_value=_settings()),
        patch("backend.app.core.config.get_outreach_guidelines", return_value=guidelines),
    ):
        footer = compliance_footer_text("person@example.com", "draft-123")
    assert "123 Main St, Chicago, IL 60601" in footer
    assert "Unsubscribe:" in footer
    assert "/api/unsubscribe" in footer


# ---------------------------------------------------------------------------
# record_unsubscribe — writes do_not_contact
# ---------------------------------------------------------------------------


def test_record_unsubscribe_inserts_do_not_contact_row():
    from backend.app.core.unsubscribe import record_unsubscribe

    db_client = MagicMock()
    record_unsubscribe(db_client, email="Person@Example.com", draft_id="draft-123", source="one_click_get")

    db_client.table.assert_called_with("do_not_contact")
    inserted = db_client.table.return_value.insert.call_args[0][0]
    assert inserted["email"] == "person@example.com"  # normalized lowercase
    assert inserted["reason"] == "unsubscribed"
    assert inserted["added_by"] == "one_click_get"
    assert "draft-123" in inserted["notes"]


# ---------------------------------------------------------------------------
# The unsubscribe route
# ---------------------------------------------------------------------------


def test_route_get_valid_token_records_and_confirms():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.app.api.routes.unsubscribe import router
    from backend.app.core.unsubscribe import generate_unsubscribe_token

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with (
        patch("backend.app.api.routes.unsubscribe.verify_unsubscribe_token", return_value=True),
        patch("backend.app.api.routes.unsubscribe.Database") as mock_db_cls,
        patch("backend.app.api.routes.unsubscribe.record_unsubscribe") as mock_record,
    ):
        mock_db_cls.return_value.client = MagicMock()
        resp = client.get(
            "/api/unsubscribe",
            params={"email": "person@example.com", "draft_id": "draft-123", "token": "anything"},
        )

    assert resp.status_code == 200
    assert "unsubscribed" in resp.text.lower()
    mock_record.assert_called_once()


def test_route_get_invalid_token_returns_400_and_does_not_record():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.app.api.routes.unsubscribe import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with (
        patch("backend.app.api.routes.unsubscribe.verify_unsubscribe_token", return_value=False),
        patch("backend.app.api.routes.unsubscribe.record_unsubscribe") as mock_record,
    ):
        resp = client.get(
            "/api/unsubscribe",
            params={"email": "person@example.com", "draft_id": "draft-123", "token": "bad"},
        )

    assert resp.status_code == 400
    mock_record.assert_not_called()


def test_route_post_one_click_returns_bare_200_ok():
    """RFC 8058: the One-Click POST target must return a bare 2xx, no HTML,
    since mail clients call this automatically with no user watching.
    """
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.app.api.routes.unsubscribe import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with (
        patch("backend.app.api.routes.unsubscribe.verify_unsubscribe_token", return_value=True),
        patch("backend.app.api.routes.unsubscribe.Database") as mock_db_cls,
        patch("backend.app.api.routes.unsubscribe.record_unsubscribe") as mock_record,
    ):
        mock_db_cls.return_value.client = MagicMock()
        resp = client.post(
            "/api/unsubscribe",
            params={"email": "person@example.com", "draft_id": "draft-123", "token": "anything"},
        )

    assert resp.status_code == 200
    assert resp.text == "OK"
    mock_record.assert_called_once()


def test_route_post_invalid_token_returns_400():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.app.api.routes.unsubscribe import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with patch("backend.app.api.routes.unsubscribe.verify_unsubscribe_token", return_value=False):
        resp = client.post(
            "/api/unsubscribe",
            params={"email": "person@example.com", "draft_id": "draft-123", "token": "bad"},
        )

    assert resp.status_code == 400
