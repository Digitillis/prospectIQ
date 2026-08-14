"""Per-draft trace logic for /api/admin/send-trace.

Extracted from backend/app/api/main.py so the would_send decision can be
unit-tested directly, without spinning up the FastAPI app or mocking the
full Supabase query chain.
"""

from __future__ import annotations

from backend.app.core.channel_coordinator import is_company_locked
from backend.app.core.database import Database
from backend.app.core.suppression import is_suppressed
from backend.app.core.unsubscribe import (
    ComplianceConfigError,
    compliance_footer_text,
    resend_unsubscribe_headers,
)


def trace_draft_would_send(db: Database, draft: dict) -> dict:
    """Trace a single draft through every gate the real dispatch path checks,
    in the same order dispatch_scheduler.py / engagement.py apply them, and
    report exactly where it would stop.

    Returns a dict with at minimum "id", "company", "contact_email", and
    either "would_send": True or "skip_reason": "<gate>:<detail>".
    """
    info = {"id": draft["id"][:8]}
    contact = draft.get("contacts") or {}
    company = draft.get("companies") or {}
    info["company"] = company.get("name", "null")
    info["contact_email"] = contact.get("email") or None

    if not info["contact_email"]:
        info["skip_reason"] = "no_email"
        return info

    try:
        suppressed, sup_reason = is_suppressed(
            db,
            draft["company_id"],
            contact_id=draft.get("contact_id"),
            skip_duplicate_check=True,
        )
        info["suppressed"] = suppressed
        info["sup_reason"] = sup_reason
    except Exception as e:
        info["suppressed"] = f"error:{e}"

    if info.get("suppressed") is True:
        info["skip_reason"] = f"suppressed:{sup_reason}"
        return info

    try:
        locked, lock_reason = is_company_locked(
            db, draft["company_id"], exclude_contact_id=draft.get("contact_id")
        )
        info["locked"] = locked
        info["lock_reason"] = lock_reason
    except Exception as e:
        info["locked"] = f"error:{e}"

    if info.get("locked") is True:
        info["skip_reason"] = f"locked:{lock_reason}"
        return info

    # Compliance-config check — mirrors the real send path (engagement.py),
    # which computes compliance_footer_text()/resend_unsubscribe_headers()
    # and blocks with failure_code=compliance_config_missing if either
    # required setting (backend_public_url, physical_address) is unset.
    # Before this fix, send-trace reported would_send=True for drafts that
    # would actually be blocked at send time by that gate, because this
    # diagnostic never called it.
    try:
        compliance_footer_text(info["contact_email"], draft["id"])
        resend_unsubscribe_headers(info["contact_email"], draft["id"])
    except ComplianceConfigError as e:
        info["skip_reason"] = f"compliance_config_missing:{e}"
        return info
    except Exception as e:
        info["skip_reason"] = f"compliance_check_error:{e}"
        return info

    info["would_send"] = True
    return info
