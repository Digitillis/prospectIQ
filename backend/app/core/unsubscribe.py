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
    """
    settings = get_settings()
    token = generate_unsubscribe_token(email, draft_id)
    from urllib.parse import quote

    return (
        f"{settings.app_base_url}/api/unsubscribe"
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
    """
    url = build_unsubscribe_url(email, draft_id)
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def compliance_footer_text(email: str, draft_id: str) -> str:
    """Plain-text footer appended to every outbound message: physical
    address (CAN-SPAM §7704(a)(5)) + a visible unsubscribe link, for mail
    clients that don't surface the List-Unsubscribe header UI.

    Raises ComplianceConfigError if sender.physical_address is unset in
    config/outreach_guidelines.yaml — callers must not send without it.
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
    unsub_url = build_unsubscribe_url(email, draft_id)
    company = sender.get("company", "")
    return f"\n\n---\n{company}\n{address}\n\nDon't want these emails? Unsubscribe: {unsub_url}"


def record_unsubscribe(db_client, *, email: str, draft_id: str | None, source: str) -> None:
    """Write a permanent do_not_contact row for an unsubscribe request.

    Mirrors the shape used elsewhere for manual/bounce DNC entries
    (do_not_contact.reason, added_by — see supabase_migrations/migrations/
    003_dnc_priority_queue.sql). Idempotent in effect: repeated unsubscribe
    clicks each insert a row, which is harmless since is_suppressed() checks
    for *any* matching row, not uniqueness.
    """
    db_client.table("do_not_contact").insert(
        {
            "email": email.strip().lower(),
            "reason": "unsubscribed",
            "added_by": source,
            "notes": f"one-click unsubscribe, draft_id={draft_id}" if draft_id else "one-click unsubscribe",
        }
    ).execute()
    logger.info("unsubscribe.recorded email_domain=%s source=%s", email.split("@")[-1], source)
