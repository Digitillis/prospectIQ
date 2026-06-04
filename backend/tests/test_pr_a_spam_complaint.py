"""Tests for PR A: spam complaint webhook fix and governance-bypass script disabling.

Three invariants verified:

1. test_spam_complaint_updates_company_status
   The spam-complaint Resend webhook calls db.update_company with exactly
   2 args (no allow_downgrade kwarg). This guards against regression to the
   pre-PR-A behaviour where the spurious kwarg caused a silent TypeError and
   company status was never updated.

2. test_spam_complaint_records_company_suppression
   A company-scope suppression row is recorded with reason='spam_complaint'.

3. test_scripts_are_disabled
   The two governance-bypass scripts exist only as .disabled files.
   They must never exist as runnable .py files.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

CONTACT_ID = "contact-abc123"
COMPANY_ID = "company-xyz456"

# Root scripts/ directory — two levels up from backend/tests/
SCRIPT_DIR = Path(__file__).parent.parent.parent / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spam_payload(email: str = "victim@prospect.com") -> dict:
    return {
        "type": "email.complained",
        "data": {
            "to": [email],
            "from": "sender@digitillis.io",
        },
    }


def _make_db_mock() -> MagicMock:
    """Return a Database-shaped MagicMock safe for the spam-complaint handler path.

    The engagement_sequences query iterates over .data, so that attribute must
    be a real empty list — not a MagicMock — to avoid TypeError on iteration.
    """
    db = MagicMock()
    db.client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = []
    return db


_TEST_WEBHOOK_SECRET = "test_resend_secret_abc"


def _make_settings_mock() -> MagicMock:
    s = MagicMock()
    # Must be a non-empty string: SEC-004 made the endpoint fail-closed when unset.
    s.resend_webhook_secret = _TEST_WEBHOOK_SECRET
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_spam_complaint_updates_company_status():
    """db.update_company is called with (company_id, dict) — no allow_downgrade kwarg."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from backend.app.api.routes.webhooks import router  # noqa: PLC0415

    app = FastAPI()
    app.include_router(router)
    mock_db = _make_db_mock()

    with (
        patch("backend.app.api.routes.webhooks._get_db_and_workspace", return_value=mock_db),
        patch(
            "backend.app.api.routes.webhooks._lookup_company_contact",
            return_value=(COMPANY_ID, CONTACT_ID),
        ),
        patch("backend.app.api.routes.webhooks._find_thread", return_value=None),
        patch("backend.app.core.suppression.record_suppression", return_value="sup-id-1"),
        patch("backend.app.api.routes.webhooks.get_settings", return_value=_make_settings_mock()),
    ):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post(
            f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=_spam_payload()
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "processed", f"Unexpected status: {body}"

    # Core assertion: exactly 2 positional args, zero keyword args
    mock_db.update_company.assert_called_once_with(COMPANY_ID, {"status": "not_interested"})


def test_spam_complaint_records_company_suppression():
    """record_suppression is called twice; one call has scope='company', reason='spam_complaint'."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from backend.app.api.routes.webhooks import router  # noqa: PLC0415

    app = FastAPI()
    app.include_router(router)
    mock_db = _make_db_mock()

    with (
        patch("backend.app.api.routes.webhooks._get_db_and_workspace", return_value=mock_db),
        patch(
            "backend.app.api.routes.webhooks._lookup_company_contact",
            return_value=(COMPANY_ID, CONTACT_ID),
        ),
        patch("backend.app.api.routes.webhooks._find_thread", return_value=None),
        patch(
            "backend.app.core.suppression.record_suppression", return_value="sup-id-1"
        ) as mock_record,
        patch("backend.app.api.routes.webhooks.get_settings", return_value=_make_settings_mock()),
    ):
        client = TestClient(app)
        client.post(f"/api/webhooks/resend?secret={_TEST_WEBHOOK_SECRET}", json=_spam_payload())

    # Two suppression records: contact scope, then company scope
    assert mock_record.call_count == 2, (
        f"Expected 2 record_suppression calls, got {mock_record.call_count}"
    )

    # Find the company-scope call (kwargs style — handler uses keyword args throughout)
    company_calls = [c for c in mock_record.call_args_list if c.kwargs.get("scope") == "company"]
    assert company_calls, "record_suppression was not called with scope='company'"

    kwargs = company_calls[0].kwargs
    assert kwargs.get("reason") == "spam_complaint", (
        f"Expected reason='spam_complaint', got {kwargs.get('reason')!r}"
    )


def test_scripts_are_disabled():
    """Governance-bypass scripts exist only as .disabled — never as runnable .py files."""
    reconciliation_py = SCRIPT_DIR / "pending_draft_reconciliation.py"
    reconciliation_disabled = SCRIPT_DIR / "pending_draft_reconciliation.py.disabled"
    reassessment_py = SCRIPT_DIR / "rejected_draft_reassessment.py"
    reassessment_disabled = SCRIPT_DIR / "rejected_draft_reassessment.py.disabled"

    assert not reconciliation_py.exists(), (
        f"Governance-bypass script is live and executable: {reconciliation_py}"
    )
    assert reconciliation_disabled.exists(), (
        f"Disabled script reference file is missing: {reconciliation_disabled}"
    )
    assert not reassessment_py.exists(), (
        f"Governance-bypass script is live and executable: {reassessment_py}"
    )
    assert reassessment_disabled.exists(), (
        f"Disabled script reference file is missing: {reassessment_disabled}"
    )
