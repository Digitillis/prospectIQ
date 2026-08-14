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


def _settings(
    webhook_secret="test-secret-value",
    app_base_url="https://app.example.com",
    backend_public_url="https://api.example.com",
):
    s = MagicMock()
    s.webhook_secret = webhook_secret
    s.app_base_url = app_base_url
    s.backend_public_url = backend_public_url
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
    # Must use backend_public_url, NOT app_base_url — app_base_url is the
    # Next.js frontend (see workspaces.py's invite-link use of it) and has
    # no route/rewrite for this backend-only API endpoint.
    assert url.startswith("https://api.example.com/api/unsubscribe")


def test_build_unsubscribe_url_raises_when_backend_public_url_unset():
    """A wrong-host unsubscribe link is a silent CAN-SPAM failure — this
    must fail closed exactly like the missing-physical-address case, not
    fall back to app_base_url (the frontend) and produce a 404 for every
    recipient who clicks it.
    """
    from backend.app.core.unsubscribe import UnsubscribeConfigError, build_unsubscribe_url

    with patch(
        "backend.app.core.unsubscribe.get_settings",
        return_value=_settings(backend_public_url=""),
    ):
        with pytest.raises(UnsubscribeConfigError):
            build_unsubscribe_url("person@example.com", "draft-123")


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


def test_resend_headers_reraises_as_compliance_config_error():
    """resend_unsubscribe_headers() must raise ComplianceConfigError, not
    UnsubscribeConfigError, when backend_public_url is unset — callers in
    engagement.py only catch ComplianceConfigError. If this raised the
    unwrapped UnsubscribeConfigError instead, it would propagate as an
    unhandled exception and crash dispatch_queued_draft() rather than
    degrading to a graceful ASSERTION_FAILED outcome.
    """
    from backend.app.core.unsubscribe import ComplianceConfigError, resend_unsubscribe_headers

    with patch(
        "backend.app.core.unsubscribe.get_settings",
        return_value=_settings(backend_public_url=""),
    ):
        with pytest.raises(ComplianceConfigError):
            resend_unsubscribe_headers("person@example.com", "draft-123")


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


def test_compliance_footer_reraises_backend_url_error_as_compliance_config_error():
    """Same unification requirement as resend_unsubscribe_headers — a
    missing backend_public_url must surface as ComplianceConfigError, the
    one type engagement.py's dispatch callers actually catch.
    """
    from backend.app.core.unsubscribe import ComplianceConfigError, compliance_footer_text

    guidelines = {"sender": {"physical_address": "123 Main St, Chicago, IL 60601", "company": "Acme"}}
    with (
        patch(
            "backend.app.core.unsubscribe.get_settings",
            return_value=_settings(backend_public_url=""),
        ),
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


class _FakeRecordUnsubscribeDB:
    """do_not_contact.workspace_id is NOT NULL (migrations 016/017) with no
    default. A plain MagicMock() lets record_unsubscribe insert without
    workspace_id and never notices — exactly the blind spot that let this
    bug ship and pass review once already. This double models both tables
    record_unsubscribe touches precisely enough to catch a regression: a
    missing workspace_id key in the do_not_contact payload is asserted on
    directly below, not inferred from a mock accepting anything.
    """

    def __init__(self, draft_workspace_id: str | None = "ws-from-draft"):
        self.insert_calls: list[tuple[str, dict]] = []
        self._draft_workspace_id = draft_workspace_id

    def table(self, name: str):
        return _FakeRecordUnsubscribeTable(self, name)


class _FakeRecordUnsubscribeTable:
    def __init__(self, db: _FakeRecordUnsubscribeDB, name: str):
        self._db = db
        self._name = name

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, payload: dict):
        self._db.insert_calls.append((self._name, payload))
        return self

    def execute(self):
        result = MagicMock()
        if self._name == "outreach_drafts":
            result.data = (
                [{"workspace_id": self._db._draft_workspace_id}]
                if self._db._draft_workspace_id
                else []
            )
        else:
            result.data = [{"id": "dnc-row-1"}]
        return result


def test_record_unsubscribe_inserts_do_not_contact_row():
    from backend.app.core.unsubscribe import record_unsubscribe

    db_client = _FakeRecordUnsubscribeDB(draft_workspace_id="ws-from-draft")
    record_unsubscribe(db_client, email="Person@Example.com", draft_id="draft-123", source="one_click_get")

    dnc_calls = [p for name, p in db_client.insert_calls if name == "do_not_contact"]
    assert len(dnc_calls) == 1
    inserted = dnc_calls[0]
    assert inserted["email"] == "person@example.com"  # normalized lowercase
    assert inserted["reason"] == "unsubscribed"
    assert inserted["added_by"] == "one_click_get"
    assert "draft-123" in inserted["notes"]


def test_record_unsubscribe_includes_workspace_id_from_draft():
    """The bug this regression-tests: do_not_contact.workspace_id is NOT
    NULL with no default (migrations 016_workspaces_multitenant.sql,
    017_workspace_id_remaining_tables.sql) — an insert omitting it throws
    an unhandled Postgres 23502 violation, meaning the unsubscribe was
    never actually recorded. Confirmed independently by two review lenses;
    the same hazard is already documented and worked around in
    backend/app/core/bounce_suppressor.py:190-198 for its own insert.
    """
    from backend.app.core.unsubscribe import record_unsubscribe

    db_client = _FakeRecordUnsubscribeDB(draft_workspace_id="ws-real-workspace")
    record_unsubscribe(db_client, email="person@example.com", draft_id="draft-123", source="one_click_post")

    dnc_calls = [p for name, p in db_client.insert_calls if name == "do_not_contact"]
    assert dnc_calls[0]["workspace_id"] == "ws-real-workspace"


def test_record_unsubscribe_falls_back_to_default_workspace_when_draft_lookup_empty():
    """draft_id resolves to no row (deleted draft, stale link) — must still
    write a non-null workspace_id rather than omitting the key or writing
    None, which would hit the same NOT NULL violation this fix exists to
    prevent.
    """
    from backend.app.core.unsubscribe import record_unsubscribe
    from backend.app.core.config import get_settings

    db_client = _FakeRecordUnsubscribeDB(draft_workspace_id=None)
    record_unsubscribe(db_client, email="person@example.com", draft_id="draft-does-not-exist", source="one_click_post")

    dnc_calls = [p for name, p in db_client.insert_calls if name == "do_not_contact"]
    assert dnc_calls[0]["workspace_id"] == get_settings().default_workspace_id


def test_record_unsubscribe_falls_back_to_default_workspace_when_draft_id_is_none():
    """No draft_id at all (e.g. a manually-triggered unsubscribe with no
    associated send) must still write a valid workspace_id.
    """
    from backend.app.core.unsubscribe import record_unsubscribe
    from backend.app.core.config import get_settings

    db_client = _FakeRecordUnsubscribeDB()
    record_unsubscribe(db_client, email="person@example.com", draft_id=None, source="manual")

    dnc_calls = [p for name, p in db_client.insert_calls if name == "do_not_contact"]
    assert dnc_calls[0]["workspace_id"] == get_settings().default_workspace_id


# ---------------------------------------------------------------------------
# The unsubscribe route
# ---------------------------------------------------------------------------


def test_route_get_valid_token_shows_confirmation_form():
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
    assert "confirm" in resp.text.lower()
    # GET must NEVER record the unsubscribe — see module docstring: email
    # security gateways (Microsoft Defender/Safe Links, Proofpoint,
    # Mimecast) auto-fetch every link in an inbound email via GET before a
    # human ever sees it. If GET mutated state, that automated scan would
    # silently unsubscribe the recipient with zero human intent.
    mock_record.assert_not_called()
    assert 'method="POST"' in resp.text


def test_route_get_renders_form_targeting_post_with_same_credentials():
    """The confirm-page form must POST back to the SAME (email, draft_id,
    token) — a human clicking "Confirm" is what actually triggers the
    action, not the initial GET.
    """
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.app.api.routes.unsubscribe import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with patch("backend.app.api.routes.unsubscribe.verify_unsubscribe_token", return_value=True):
        resp = client.get(
            "/api/unsubscribe",
            params={"email": "person@example.com", "draft_id": "draft-123", "token": "tok-abc"},
        )

    assert "email=person%40example.com" in resp.text
    assert "draft_id=draft-123" in resp.text
    assert "token=tok-abc" in resp.text


def test_route_get_escapes_email_in_html_display_context():
    """email is unvalidated, scraped/imported contact data with no
    EmailStr/regex enforcement on contacts.email — an email value
    containing HTML/script must not be rendered unescaped into the
    confirmation page. Regression test for a found-in-review injection gap.
    """
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.app.api.routes.unsubscribe import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    malicious_email = '<script>alert(1)</script>@example.com'
    with patch("backend.app.api.routes.unsubscribe.verify_unsubscribe_token", return_value=True):
        resp = client.get(
            "/api/unsubscribe",
            params={"email": malicious_email, "draft_id": "draft-123", "token": "tok-abc"},
        )

    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


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
