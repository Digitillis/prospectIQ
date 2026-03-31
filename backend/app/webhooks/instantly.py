"""Instantly.ai webhook handler for ProspectIQ.

Receives email lifecycle events from Instantly (sent, opened, clicked,
replied, bounced, unsubscribed) and updates the contact state machine
and related tables in Supabase.

Registration: POST /webhooks/instantly
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks-instantly"])

# ---------------------------------------------------------------------------
# Sentiment keyword sets
# ---------------------------------------------------------------------------

_POSITIVE_KEYWORDS = {
    "interested",
    "yes",
    "sounds good",
    "tell me more",
    "call",
    "schedule",
    "demo",
    "love to",
    "would like",
    "let's connect",
    "let's chat",
    "happy to",
    "open to",
    "absolutely",
    "definitely",
}

_NEGATIVE_KEYWORDS = {
    "not interested",
    "remove",
    "unsubscribe",
    "stop",
    "no thanks",
    "not now",
    "don't contact",
    "do not contact",
    "opt out",
    "opt-out",
    "leave me alone",
    "no longer",
}


def _classify_sentiment(text: str) -> str:
    """Simple keyword-based reply sentiment classifier.

    Returns 'positive', 'negative', or 'neutral'.
    """
    if not text:
        return "neutral"
    lower = text.lower()
    # Check negative first (unsubscribe beats curiosity)
    for kw in _NEGATIVE_KEYWORDS:
        if kw in lower:
            return "negative"
    for kw in _POSITIVE_KEYWORDS:
        if kw in lower:
            return "positive"
    return "neutral"


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Verify Instantly HMAC-SHA256 webhook signature.

    Expected header: X-Instantly-Signature: <hex-digest>
    Returns True if valid or if INSTANTLY_WEBHOOK_SECRET is not configured
    (development mode).
    """
    secret = os.environ.get("INSTANTLY_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning(
            "INSTANTLY_WEBHOOK_SECRET not set — skipping signature verification "
            "(set this env var in production)"
        )
        return True

    if not signature_header:
        logger.warning("Missing X-Instantly-Signature header on webhook request")
        return False

    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Payload field extraction helpers
# ---------------------------------------------------------------------------

def _get_field(payload: dict[str, Any], *keys: str) -> Any:
    """Return the first non-None value found among the given keys."""
    for key in keys:
        val = payload.get(key)
        if val is not None:
            return val
    return None


def _parse_event(payload: dict[str, Any]) -> tuple[str, str, dict]:
    """Extract (event_type, lead_email, data) from the payload defensively."""
    event_type = _get_field(payload, "event_type", "event") or ""
    lead_email = _get_field(payload, "lead_email", "email", "contact_email") or ""
    data: dict = payload.get("data") or {}
    return event_type.lower().strip(), lead_email.lower().strip(), data


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_email_sent(
    db: Database,
    contact: dict,
    data: dict,
    payload: dict[str, Any],
) -> None:
    """Transition state to touch_N_sent and stamp last-touch fields."""
    step: int = data.get("sequence_step") or payload.get("sequence_step") or 1
    try:
        step = int(step)
    except (TypeError, ValueError):
        step = 1

    # Clamp to valid touch range
    step = max(1, min(step, 5))
    new_state = f"touch_{step}_sent"

    now_iso = datetime.now(timezone.utc).isoformat()
    db.update_contact_state(
        contact_id=contact["id"],
        new_state=new_state,
        from_state=contact.get("outreach_state"),
        channel="email",
        instantly_event="email_sent",
        metadata={"sequence_step": step, "campaign_id": payload.get("campaign_id")},
        extra_updates={
            "last_touch_channel": "email",
            "last_touch_at": now_iso,
        },
    )


def _handle_email_opened(
    db: Database,
    contact: dict,
    data: dict,
    payload: dict[str, Any],
) -> None:
    """Increment open_count and log the event."""
    current_opens: int = contact.get("open_count") or 0
    db.update_contact_state(
        contact_id=contact["id"],
        new_state=contact.get("outreach_state") or "enriched",  # state unchanged
        from_state=contact.get("outreach_state"),
        channel="email",
        instantly_event="email_opened",
        metadata={"campaign_id": payload.get("campaign_id")},
        extra_updates={
            "open_count": current_opens + 1,
        },
    )


def _handle_email_clicked(
    db: Database,
    contact: dict,
    data: dict,
    payload: dict[str, Any],
) -> None:
    """Increment click_count and log the event."""
    current_clicks: int = contact.get("click_count") or 0
    db.update_contact_state(
        contact_id=contact["id"],
        new_state=contact.get("outreach_state") or "enriched",  # state unchanged
        from_state=contact.get("outreach_state"),
        channel="email",
        instantly_event="email_clicked",
        metadata={"campaign_id": payload.get("campaign_id")},
        extra_updates={
            "click_count": current_clicks + 1,
        },
    )


def _handle_email_replied(
    db: Database,
    contact: dict,
    data: dict,
    payload: dict[str, Any],
) -> None:
    """Transition to 'replied', classify sentiment, stamp last-touch."""
    reply_text: str = (
        data.get("reply_text")
        or payload.get("reply_text")
        or payload.get("body")
        or ""
    )
    sentiment = _classify_sentiment(reply_text)
    now_iso = datetime.now(timezone.utc).isoformat()

    db.update_contact_state(
        contact_id=contact["id"],
        new_state="replied",
        from_state=contact.get("outreach_state"),
        channel="email",
        instantly_event="email_replied",
        metadata={
            "sentiment": sentiment,
            "reply_snippet": reply_text[:300] if reply_text else "",
            "campaign_id": payload.get("campaign_id"),
        },
        extra_updates={
            "reply_sentiment": sentiment,
            "last_touch_channel": "email",
            "last_touch_at": now_iso,
        },
    )


def _handle_email_bounced(
    db: Database,
    contact: dict,
    data: dict,
    payload: dict[str, Any],
) -> None:
    """Transition to 'dnc', add email to do_not_contact."""
    bounce_reason: str = data.get("bounce_reason") or payload.get("bounce_reason") or "bounced"

    db.update_contact_state(
        contact_id=contact["id"],
        new_state="dnc",
        from_state=contact.get("outreach_state"),
        channel="email",
        instantly_event="email_bounced",
        metadata={
            "bounce_reason": bounce_reason,
            "campaign_id": payload.get("campaign_id"),
        },
    )

    email = contact.get("email", "")
    if email:
        db.add_to_dnc(email, reason="bounced", added_by="instantly_webhook")


def _handle_email_unsubscribed(
    db: Database,
    contact: dict,
    data: dict,
    payload: dict[str, Any],
) -> None:
    """Transition to 'dnc', add email to do_not_contact."""
    db.update_contact_state(
        contact_id=contact["id"],
        new_state="dnc",
        from_state=contact.get("outreach_state"),
        channel="email",
        instantly_event="email_unsubscribed",
        metadata={"campaign_id": payload.get("campaign_id")},
    )

    email = contact.get("email", "")
    if email:
        db.add_to_dnc(email, reason="unsubscribed", added_by="instantly_webhook")


# Map event_type strings to handler functions
_HANDLERS = {
    "email_sent": _handle_email_sent,
    "email_opened": _handle_email_opened,
    "email_clicked": _handle_email_clicked,
    "email_replied": _handle_email_replied,
    "reply_received": _handle_email_replied,   # alias Instantly sometimes uses
    "email_bounced": _handle_email_bounced,
    "email_unsubscribed": _handle_email_unsubscribed,
}


# ---------------------------------------------------------------------------
# FastAPI route
# ---------------------------------------------------------------------------

@router.post("/instantly")
async def instantly_webhook(request: Request) -> dict[str, Any]:
    """Receive and process webhook events from Instantly.ai.

    Verifies the HMAC signature when INSTANTLY_WEBHOOK_SECRET is set,
    looks up the contact by email, then dispatches to the appropriate
    event handler to update the contact state machine.

    Always returns HTTP 200 so Instantly does not retry on non-fatal
    issues (unknown contact, unrecognised event).
    """
    raw_body: bytes = await request.body()

    # --- Signature verification -----------------------------------------
    sig_header = request.headers.get("X-Instantly-Signature")
    if not _verify_signature(raw_body, sig_header):
        logger.warning("Instantly webhook signature verification failed — rejecting")
        # Return 200 to avoid infinite Instantly retries; log for alerting
        return {"status": "rejected", "reason": "invalid_signature"}

    # --- Parse payload ---------------------------------------------------
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        logger.error(f"Failed to parse Instantly webhook JSON: {exc}")
        return {"status": "error", "reason": "invalid_json"}

    event_type, lead_email, data = _parse_event(payload)

    if not event_type:
        return {"status": "ignored", "reason": "missing_event_type"}

    if not lead_email:
        logger.warning(f"Instantly webhook event={event_type!r} has no lead email; skipping")
        return {"status": "ignored", "reason": "missing_lead_email"}

    # --- Look up contact -------------------------------------------------
    db = Database()
    contact = db.get_contact_by_email(lead_email)

    if not contact:
        logger.warning(
            f"Instantly webhook event={event_type!r} for unknown email={lead_email!r}; ignoring"
        )
        return {"status": "ignored", "reason": "contact_not_found", "email": lead_email}

    # --- Dispatch to handler ---------------------------------------------
    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.info(f"No handler for Instantly event={event_type!r}; logging and skipping")
        return {"status": "ignored", "reason": "unknown_event_type", "event_type": event_type}

    try:
        handler(db, contact, data, payload)
    except Exception as exc:
        logger.error(
            f"Error processing Instantly event={event_type!r} for contact={contact['id']}: {exc}",
            exc_info=True,
        )
        return {"status": "error", "reason": str(exc)[:200]}

    # --- Update parent company last-touch --------------------------------
    company_id: str | None = contact.get("company_id")
    if company_id:
        try:
            db.update_company(
                company_id,
                {"outreach_last_touch_at": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as exc:
            # Non-fatal — don't fail the whole webhook over a company update
            logger.warning(f"Failed to update company outreach_last_touch_at: {exc}")

    logger.info(
        f"Instantly webhook processed: event={event_type!r} "
        f"contact={contact['id']} email={lead_email!r}"
    )
    return {
        "status": "processed",
        "event_type": event_type,
        "contact_id": contact["id"],
    }
