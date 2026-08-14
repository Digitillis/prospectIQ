"""send-trace must report would_send accurately — including the compliance
gate the real dispatch path enforces.

Before this fix, /api/admin/send-trace checked suppression and company-lock
but never called compliance_footer_text()/resend_unsubscribe_headers(), so a
draft blocked at send time by a missing backend_public_url or
sender_physical_address (failure_code=compliance_config_missing, see
dispatch_scheduler.py) was reported as would_send=True — the diagnostic's
core promise ("identifies exactly where it stops") was false for this case.
See backend/app/core/send_trace.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.app.core.send_trace import trace_draft_would_send
from backend.app.core.unsubscribe import ComplianceConfigError

_DRAFT = {
    "id": "draft-1234567890",
    "company_id": "company-1",
    "contact_id": "contact-1",
    "contacts": {"full_name": "Jane Doe", "email": "jane@acme.com"},
    "companies": {"name": "Acme Corp"},
}


def _patched(*, suppressed=(False, None), locked=(False, None), compliance_error=None):
    """Context manager stack patching the three gates trace_draft_would_send calls."""
    footer_patch = patch("backend.app.core.send_trace.compliance_footer_text")
    headers_patch = patch("backend.app.core.send_trace.resend_unsubscribe_headers")
    suppressed_patch = patch("backend.app.core.send_trace.is_suppressed", return_value=suppressed)
    locked_patch = patch("backend.app.core.send_trace.is_company_locked", return_value=locked)

    class _Stack:
        def __enter__(self):
            self.footer = footer_patch.__enter__()
            self.headers = headers_patch.__enter__()
            suppressed_patch.__enter__()
            locked_patch.__enter__()
            if compliance_error is not None:
                self.footer.side_effect = compliance_error
            return self

        def __exit__(self, *a):
            footer_patch.__exit__(*a)
            headers_patch.__exit__(*a)
            suppressed_patch.__exit__(*a)
            locked_patch.__exit__(*a)

    return _Stack()


def test_missing_compliance_config_blocks_would_send():
    """A draft that clears suppression and lock checks, but whose compliance
    config is missing, must NOT report would_send=True."""
    db = MagicMock()
    with _patched(compliance_error=ComplianceConfigError("backend_public_url is not set")):
        info = trace_draft_would_send(db, _DRAFT)

    assert "would_send" not in info
    assert info["skip_reason"].startswith("compliance_config_missing:")
    assert "backend_public_url" in info["skip_reason"]


def test_clean_draft_reports_would_send_true():
    """Sanity check: with every gate clear, would_send=True is still reachable
    (i.e. this fix didn't make the endpoint permanently report false)."""
    db = MagicMock()
    with _patched():
        info = trace_draft_would_send(db, _DRAFT)

    assert info.get("would_send") is True
    assert "skip_reason" not in info


def test_suppressed_draft_reports_suppressed_not_compliance():
    """Suppression is checked before compliance — a suppressed contact's skip
    reason should say suppressed, not silently pass through to would_send."""
    db = MagicMock()
    with _patched(suppressed=(True, "do_not_contact:email:unsubscribe")):
        info = trace_draft_would_send(db, _DRAFT)

    assert "would_send" not in info
    assert info["skip_reason"] == "suppressed:do_not_contact:email:unsubscribe"


def test_no_email_short_circuits_before_any_gate():
    db = MagicMock()
    draft_no_email = dict(_DRAFT, contacts={"full_name": "Jane Doe", "email": None})
    with _patched(compliance_error=ComplianceConfigError("should never be reached")):
        info = trace_draft_would_send(db, draft_no_email)

    assert info["skip_reason"] == "no_email"
