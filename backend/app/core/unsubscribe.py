"""One-click unsubscribe: token generation, verification, and DNC recording.

Added 2026-08 to close a CAN-SPAM §7704(a)(3)/(5) gap: ProspectIQ sent
unsolicited commercial email with no unsubscribe mechanism at all. The only
prior route to opt-out was a free-text reply, and reply capture was itself
broken (see backend/app/core/gmail_reply_ingest fixes in the same change).

Token design: HMAC-SHA256(email + draft_id) using the existing
settings.webhook_secret, base64url-encoded, no expiry. An unsubscribe link
must keep working indefinitely — a recipient who opens a six-month-old email
and clicks unsubscribe must still be able to opt out. This mirrors the
verify_webhook() pattern (fail closed when unconfigured, timing-safe compare)
already established in backend/app/core/webhook_auth.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


class UnsubscribeConfigError(RuntimeError):
    """Raised when WEBHOOK_SECRET is not configured — tokens cannot be signed."""


def _signing_key() -> bytes:
    settings = get_settings()
    if not settings.webhook_secret:
        raise UnsubscribeConfigError(
            "WEBHOOK_SECRET is not configured — cannot sign or verify "
            "unsubscribe tokens. Set it before sending any outreach."
        )
    return settings.webhook_secret.encode("utf-8")


def generate_unsubscribe_token(email: str, draft_id: str) -> str:
    """Generate a stable, non-expiring unsubscribe token for (email, draft_id).

    draft_id is included so the token also identifies which send prompted
    the unsubscribe, without needing a lookup table to issue links.
    """
    payload = f"{email.strip().lower()}:{draft_id}".encode("utf-8")
    digest = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_unsubscribe_token(email: str, draft_id: str, token: str) -> bool:
    """Timing-safe verification of an unsubscribe token."""
    if not token:
        return False
    expected = generate_unsubscribe_token(email, draft_id)
    return hmac.compare_digest(expected, token)


def build_unsubscribe_url(email: str, draft_id: str) -> str:
    """Build the full one-click unsubscribe URL for List-Unsubscribe headers
    and the email footer link.

    Uses settings.backend_public_url, NOT app_base_url. app_base_url is the
    Next.js frontend (see workspaces.py's invite-link use of it); this route
    lives only on the FastAPI backend with no frontend rewrite in front of
    it. Fails closed (raises) if unset, for the same reason
    compliance_footer_text() fails closed on a missing physical address: an
    unsubscribe link resolving to the wrong host is a silent CAN-SPAM
    failure, and silent is worse than blocked.
    """
    settings = get_settings()
    if not settings.backend_public_url:
        raise UnsubscribeConfigError(
            "backend_public_url is not configured — cannot build an unsubscribe "
            "link. Do not fall back to app_base_url; that points at the frontend, "
            "not this API. Set backend_public_url to this service's own public "
            "domain before enabling sends."
        )
    token = generate_unsubscribe_token(email, draft_id)
    from urllib.parse import quote

    return (
        f"{settings.backend_public_url}/api/unsubscribe"
        f"?email={quote(email)}&draft_id={quote(draft_id)}&token={quote(token)}"
    )


class ComplianceConfigError(RuntimeError):
    """Raised when required CAN-SPAM configuration (physical address) is
    missing. Sends must not proceed without it — see the comment on
    config/outreach_guidelines.yaml's sender.physical_address field.
    """


def resend_unsubscribe_headers(email: str, draft_id: str) -> dict[str, str]:
    """List-Unsubscribe + List-Unsubscribe-Post headers (RFC 8058 one-click).

    Mail clients (Gmail, Outlook, Apple Mail) that see both headers render a
    native "Unsubscribe" affordance next to the sender name and, on click,
    POST to the URL with no page load and no user-visible redirect — which
    is why the URL must itself be enough to identify and action the request
    (see backend/app/api/routes/unsubscribe.py's POST handler).

    Raises ComplianceConfigError (not UnsubscribeConfigError) if
    backend_public_url is unset — callers (engagement.py) only catch
    ComplianceConfigError, so every send-blocking config precondition must
    surface through that one type or it propagates as an unhandled
    exception instead of a graceful ASSERTION_FAILED outcome.
    """
    try:
        url = build_unsubscribe_url(email, draft_id)
    except UnsubscribeConfigError as exc:
        raise ComplianceConfigError(str(exc)) from exc
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def compliance_footer_text(email: str, draft_id: str) -> str:
    """Plain-text footer appended to every outbound message: physical
    address (CAN-SPAM §7704(a)(5)) + a visible unsubscribe link, for mail
    clients that don't surface the List-Unsubscribe header UI.

    Raises ComplianceConfigError if sender.physical_address OR
    backend_public_url is unset — callers must not send without either.
    """
    from backend.app.core.config import get_outreach_guidelines

    sender = get_outreach_guidelines().get("sender", {})
    address = (sender.get("physical_address") or "").strip()
    if not address:
        raise ComplianceConfigError(
            "sender.physical_address is not set in config/outreach_guidelines.yaml — "
            "CAN-SPAM requires a real physical mailing address in every commercial "
            "email. Set it before enabling sends."
        )
    try:
        unsub_url = build_unsubscribe_url(email, draft_id)
    except UnsubscribeConfigError as exc:
        raise ComplianceConfigError(str(exc)) from exc
    company = sender.get("company", "")
    return f"\n\n---\n{company}\n{address}\n\nDon't want these emails? Unsubscribe: {unsub_url}"


def record_unsubscribe(db_client, *, email: str, draft_id: str | None, source: str) -> None:
    """Write a permanent do_not_contact row for an unsubscribe request.

    Mirrors the shape used elsewhere for manual/bounce DNC entries
    (do_not_contact.reason, added_by — see supabase_migrations/migrations/
    003_dnc_priority_queue.sql). Blocking is idempotent — repeated
    unsubscribe clicks each insert a row, and is_suppressed() checks for
    *any* matching row, not uniqueness, so a suppressed email stays
    suppressed regardless of duplicate rows.

    CORRECTNESS FIX (post-review, confirmed independently by two review
    lenses): this used to omit workspace_id from the insert entirely. That
    was only safe against migration 003_dnc_priority_queue.sql's original
    schema. supabase_migrations/migrations/016_workspaces_multitenant.sql
    adds workspace_id to do_not_contact, and 017_workspace_id_remaining_
    tables.sql makes it NOT NULL with no default — no later migration
    relaxes this. Every real call was throwing an unhandled Postgres 23502
    NOT NULL violation, meaning the do_not_contact row was NEVER written
    and the recipient was never actually suppressed. Confirmed by a second,
    independent source in this same codebase:
    backend/app/core/bounce_suppressor.py:190-198 documents and works
    around this exact constraint for its own do_not_contact insert.

    Resolves the correct workspace_id by looking up outreach_drafts for the
    given draft_id (also NOT NULL there per the same two migrations) rather
    than blindly defaulting, so the suppression lands in the workspace that
    actually sent the email — correct if this system is ever genuinely
    multi-workspace, and a no-op difference today since there is only one
    workspace in practice. Falls back to settings.default_workspace_id
    (the value both migrations backfilled existing rows with) only if the
    draft lookup fails or draft_id is None.

    KNOWN LIMITATION, not fixed here: do_not_contact has no unique
    constraint on email (confirmed against the migration; not attempting a
    schema change in this pass without the live table's confirmed current
    state — see this repo's convention of verifying schema against a
    running system before migrating). If a *different* reason (e.g.
    legal_hold, competitor) is ever recorded for the same email as an
    unsubscribe, .limit(1) callers with no ORDER BY (both is_suppressed()
    and dnc_registry.py do this) return a row nondeterministically — the
    contact is still correctly blocked, but the *reported reason* is not
    reliable when duplicates with different reasons exist for one email.
    """
    from backend.app.core.config import get_settings

    workspace_id = get_settings().default_workspace_id
    if draft_id:
        try:
            draft_result = (
                db_client.table("outreach_drafts")
                .select("workspace_id")
                .eq("id", draft_id)
                .limit(1)
                .execute()
            )
            if draft_result.data and draft_result.data[0].get("workspace_id"):
                workspace_id = draft_result.data[0]["workspace_id"]
        except Exception as exc:
            logger.warning(
                "record_unsubscribe: could not resolve workspace_id from draft_id=%s "
                "(falling back to default_workspace_id): %s",
                draft_id,
                exc,
            )

    db_client.table("do_not_contact").insert(
        {
            "email": email.strip().lower(),
            "reason": "unsubscribed",
            "added_by": source,
            "notes": f"one-click unsubscribe, draft_id={draft_id}" if draft_id else "one-click unsubscribe",
            "workspace_id": workspace_id,
        }
    ).execute()
    logger.info(
        "unsubscribe.recorded email_domain=%s source=%s workspace_id=%s",
        email.split("@")[-1],
        source,
        workspace_id,
    )
