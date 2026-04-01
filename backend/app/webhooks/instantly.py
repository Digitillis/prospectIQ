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

from fastapi import APIRouter, BackgroundTasks, Request, Response

from backend.app.core.database import Database
from backend.app.analytics.ab_tracker import ABTracker
from backend.app.core.notifications import notify_reply_received

# ---------------------------------------------------------------------------
# Phase 2 background tasks — thread management on email events
# ---------------------------------------------------------------------------

async def _bg_create_thread_on_send(contact: dict, payload: dict) -> None:
    """Background task: ensure a campaign thread exists when first email is sent.

    Stores the Instantly campaign_id on the thread for use in Phase 3 replies.
    Non-fatal — any failure is logged and swallowed.
    """
    try:
        from backend.app.core.thread_manager import ThreadManager
        db = Database()
        tm = ThreadManager(db)

        company_id = contact.get("company_id")
        contact_id = contact.get("id")
        if not company_id or not contact_id:
            return

        thread = tm.get_or_create_thread(
            company_id=company_id,
            contact_id=contact_id,
            sequence_name="email_value_first",
        )

        campaign_id: str | None = payload.get("campaign_id")
        if campaign_id and not thread.get("instantly_campaign_id"):
            db.client.table("campaign_threads").update({
                "instantly_campaign_id": campaign_id,
            }).eq("id", thread["id"]).execute()

        logger.info(
            f"Thread ensured on send: thread={thread['id']} "
            f"contact={contact_id} campaign={campaign_id}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"_bg_create_thread_on_send failed (non-fatal): {exc}")


async def _bg_classify_reply(
    lead_email: str,
    reply_subject: str,
    reply_body: str,
    sent_at: str | None,
    campaign_id: str | None,
    raw_payload: dict,
) -> None:
    """Background task: classify an incoming reply with Claude Sonnet and pause the lead.

    Calls ThreadAgent.process_webhook_reply() to record the inbound message and
    run AI classification.  Immediately pauses the Instantly sequence so no
    further automated follow-ups fire while the reply is handled.
    Non-fatal — any failure is logged and swallowed.
    """
    try:
        from backend.app.agents.thread import ThreadAgent
        from backend.app.integrations.instantly import InstantlyClient

        db = Database()
        agent = ThreadAgent(batch_id="webhook_auto")

        result = agent.process_webhook_reply(
            sender_email=lead_email,
            reply_subject=reply_subject,
            reply_body=reply_body,
            sent_at=sent_at,
            raw_payload=raw_payload,
        )

        # Pause automated sequence regardless of classification so no
        # follow-up email fires before we handle the reply.
        if campaign_id:
            try:
                instantly = InstantlyClient()
                instantly.pause_lead_sequence(campaign_id, lead_email)
                logger.info(
                    f"Instantly sequence paused for {lead_email} in campaign {campaign_id}"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"pause_lead_sequence failed (non-fatal): {exc}")

        if result:
            logger.info(
                f"Reply auto-classified: thread={result['thread']['id']} "
                f"classification={result.get('classification')} "
                f"auto_confirmed={result.get('auto_confirmed')} "
                f"needs_review={result.get('needs_review')}"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"_bg_classify_reply failed (non-fatal): {exc}", exc_info=True)

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

    # --- A/B tracking ---
    sequence_id: str | None = (
        contact.get("instantly_sequence_id")
        or data.get("sequence_id")
        or payload.get("sequence_id")
        or payload.get("campaign_id")
    )
    subject_line: str | None = (
        data.get("subject")
        or payload.get("subject")
        or data.get("subject_line")
        or payload.get("subject_line")
    )
    variant: str | None = (
        data.get("ab_variant")
        or payload.get("ab_variant")
        or data.get("variant")
        or payload.get("variant")
    )
    if sequence_id and variant:
        try:
            ABTracker(db).record_send(
                contact_id=contact["id"],
                variant=variant,
                subject_line=subject_line or "",
                sequence_id=sequence_id,
            )
        except Exception as exc:
            logger.warning(f"ABTracker.record_send failed (non-fatal): {exc}")


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

    # --- A/B tracking ---
    variant: str | None = (
        data.get("ab_variant")
        or payload.get("ab_variant")
        or data.get("variant")
        or payload.get("variant")
    )
    if variant:
        try:
            ABTracker(db).record_open(contact_id=contact["id"], variant=variant)
        except Exception as exc:
            logger.warning(f"ABTracker.record_open failed (non-fatal): {exc}")


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
async def instantly_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
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
    # Use unscoped DB for initial lookup — webhooks arrive without auth context.
    # After finding the contact, re-scope the DB to that contact's workspace.
    _lookup_db = Database()
    contact = _lookup_db.get_contact_by_email(lead_email)

    if not contact:
        logger.warning(
            f"Instantly webhook event={event_type!r} for unknown email={lead_email!r}; ignoring"
        )
        return {"status": "ignored", "reason": "contact_not_found", "email": lead_email}

    # Re-scope all subsequent DB operations to the contact's workspace
    db = Database(workspace_id=contact.get("workspace_id"))

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

    # --- Phase 2: Thread management background tasks ----------------------
    if event_type == "email_sent":
        background_tasks.add_task(
            _bg_create_thread_on_send,
            contact=contact,
            payload=payload,
        )
    elif event_type in {"email_replied", "reply_received"}:
        _reply_body: str = (
            data.get("reply_text")
            or payload.get("reply_text")
            or payload.get("body")
            or ""
        )
        _reply_subject: str = (
            data.get("subject")
            or payload.get("subject")
            or ""
        )
        _campaign_id: str | None = data.get("campaign_id") or payload.get("campaign_id")
        _sent_at: str | None = (
            data.get("sent_at")
            or data.get("timestamp")
            or payload.get("timestamp")
            or None
        )
        background_tasks.add_task(
            _bg_classify_reply,
            lead_email=lead_email,
            reply_subject=_reply_subject,
            reply_body=_reply_body,
            sent_at=_sent_at,
            campaign_id=_campaign_id,
            raw_payload=payload,
        )

    # --- Fire email notification for reply events -------------------------
    if event_type in {"email_replied", "reply_received"}:
        reply_text: str = (
            data.get("reply_text")
            or payload.get("reply_text")
            or payload.get("body")
            or ""
        )
        contact_name: str = (
            contact.get("full_name")
            or contact.get("name")
            or lead_email
        )
        company_name: str = contact.get("company_name") or contact.get("company") or ""
        workspace_email: str = contact.get("workspace_email") or ""

        if workspace_email:
            background_tasks.add_task(
                notify_reply_received,
                company_name=company_name,
                contact_name=contact_name,
                reply_preview=reply_text[:300],
                workspace_email=workspace_email,
            )
        else:
            logger.warning(
                f"Reply notification skipped for contact={contact['id']}: "
                "no workspace_email found on contact record"
            )

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
