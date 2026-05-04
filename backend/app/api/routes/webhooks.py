"""Webhook routes for ProspectIQ API.

Handles inbound events from Instantly.ai:
  email.reply        — prospect replied → classify → thread → HITL queue
  email.opened       — tracking open event
  email.clicked      — link click tracking
  email.bounced      — hard/soft bounce
  email.unsubscribed — prospect opted out

Also preserves the legacy reply_received / email_opened / email_bounced
event_type keys that EngagementAgent uses, for backwards compatibility.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Unipile (LinkedIn) webhook handler
# ---------------------------------------------------------------------------

@router.post("/unipile")
async def unipile_webhook(request: Request):
    """Receive webhook events from Unipile for LinkedIn automation.

    Handled event types:
      - connection_accepted  → mark contact linkedin_accepted_at,
                               opening DM becomes eligible for next send cycle
      - message_received     → route LinkedIn DM reply to reply classifier (future)

    Unipile sends a shared secret in the X-Unipile-Signature header.
    Set UNIPILE_WEBHOOK_SECRET in env vars and configure the same value
    in the Unipile dashboard webhook settings.
    """
    settings = get_settings()

    # Validate webhook signature if secret is configured
    webhook_secret = getattr(settings, "unipile_webhook_secret", "") or ""
    if webhook_secret:
        signature = request.headers.get("X-Unipile-Signature", "")
        if signature != webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid Unipile webhook signature")

    payload: dict[Any, Any] = await request.json()
    event_type: str = (payload.get("event_type") or payload.get("type") or "").lower().strip()

    logger.info("Unipile webhook received: event_type=%s", event_type)

    if event_type == "connection_accepted":
        return await _handle_linkedin_connection_accepted(payload)
    elif event_type == "message_received":
        return await _handle_linkedin_message_received(payload)
    else:
        return {"status": "ignored", "reason": f"unhandled event_type: {event_type}"}


async def _handle_linkedin_connection_accepted(payload: dict) -> dict:
    """Handle Unipile connection_accepted event.

    Payload expected fields:
      - account_id: Unipile account ID
      - profile_url or linkedin_profile_url: prospect's LinkedIn URL
      - contact_id (optional): if ProspectIQ contact_id stored in Unipile metadata
    """
    linkedin_url: str = (
        payload.get("linkedin_profile_url")
        or payload.get("profile_url")
        or ""
    )

    if not linkedin_url:
        return {"status": "ignored", "reason": "no linkedin_profile_url in payload"}

    try:
        from backend.app.core.database import Database
        from backend.app.core.workspace import get_workspace_id
        from backend.app.agents.linkedin_sender import LinkedInSenderAgent
        from datetime import datetime, timezone

        db = Database(workspace_id=get_workspace_id())

        # Find contact by LinkedIn URL
        result = (
            db.client.table("contacts")
            .select("id, full_name, workspace_id")
            .eq("linkedin_url", linkedin_url)
            .limit(1)
            .execute()
        )

        if not result.data:
            logger.warning(
                "Unipile connection_accepted: no contact found for linkedin_url=%s",
                linkedin_url,
            )
            return {"status": "ignored", "reason": f"no contact found for {linkedin_url}"}

        contact = result.data[0]
        contact_id = contact["id"]

        # Mark connection accepted
        db.client.table("contacts").update({
            "linkedin_accepted_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", contact_id).execute()

        logger.info(
            "Unipile: connection accepted — contact %s (%s)",
            contact.get("full_name", contact_id), linkedin_url,
        )

        return {
            "status": "processed",
            "action": "connection_accepted",
            "contact_id": contact_id,
            "note": "Opening DM eligible for next LinkedInSenderAgent cycle",
        }

    except Exception as exc:
        logger.error("Unipile connection_accepted handling failed: %s", exc, exc_info=True)
        return {"status": "error", "reason": str(exc)[:200]}


async def _handle_linkedin_message_received(payload: dict) -> dict:
    """Handle inbound LinkedIn DM via Unipile.

    Routes through the reply classifier the same way email replies do.
    Future: full thread management for LinkedIn DMs.
    """
    linkedin_url: str = (
        payload.get("sender_linkedin_profile_url")
        or payload.get("profile_url")
        or ""
    )
    message_text: str = payload.get("message_text") or payload.get("body") or ""

    if not linkedin_url or not message_text:
        return {"status": "ignored", "reason": "missing linkedin_url or message_text"}

    try:
        from backend.app.core.database import Database
        from backend.app.core.workspace import get_workspace_id

        db = Database(workspace_id=get_workspace_id())

        result = (
            db.client.table("contacts")
            .select("id, company_id, full_name")
            .eq("linkedin_url", linkedin_url)
            .limit(1)
            .execute()
        )

        if not result.data:
            return {"status": "ignored", "reason": f"no contact found for {linkedin_url}"}

        contact = result.data[0]

        # Log the LinkedIn reply as an interaction
        db.insert_interaction({
            "company_id": contact["company_id"],
            "contact_id": contact["id"],
            "type": "linkedin_message",
            "channel": "linkedin",
            "body": message_text,
            "source": "unipile_webhook",
            "metadata": {
                "event_type": "message_received",
                "linkedin_url": linkedin_url,
            },
        })

        # Mark contact as responded
        from datetime import datetime, timezone
        db.client.table("contacts").update({
            "linkedin_responded_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", contact["id"]).execute()

        return {
            "status": "processed",
            "action": "linkedin_reply_logged",
            "contact_id": contact["id"],
        }

    except Exception as exc:
        logger.error("Unipile message_received handling failed: %s", exc, exc_info=True)
        return {"status": "error", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_db_and_workspace():
    from backend.app.core.database import Database
    from backend.app.core.workspace import get_workspace_id
    from backend.app.core.config import get_settings
    ws_id = get_workspace_id() or get_settings().default_workspace_id
    return Database(workspace_id=ws_id)


def _find_thread(db, contact_id: str, company_id: str, instantly_campaign_id: Optional[str] = None):
    """Find the most recent active/paused/replied thread for a contact."""
    try:
        q = (
            db.client.table("campaign_threads")
            .select("*")
            .eq("contact_id", contact_id)
            .in_("status", ["active", "paused", "replied", "awaiting_review"])
            .order("updated_at", desc=True)
            .limit(1)
        )
        result = q.execute()
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.warning("_find_thread failed: %s", exc)
        return None


def _find_or_create_thread(db, company_id: str, contact_id: str, instantly_campaign_id: Optional[str] = None) -> dict:
    """Find existing thread or create a new one for this company/contact pair."""
    thread = _find_thread(db, contact_id, company_id, instantly_campaign_id)
    if thread:
        return thread

    # Create a new thread
    data: dict = {
        "company_id": company_id,
        "contact_id": contact_id,
        "status": "active",
        "current_step": 1,
    }
    if db.workspace_id:
        data["workspace_id"] = db.workspace_id
    if instantly_campaign_id:
        data["instantly_campaign_id"] = instantly_campaign_id

    result = db.client.table("campaign_threads").insert(data).execute()
    return result.data[0] if result.data else data


def _lookup_company_contact(db, from_email: str, instantly_campaign_id: Optional[str] = None):
    """Look up company_id and contact_id from an inbound sender email.

    Strategy:
    1. contacts.email == from_email
    2. outreach_drafts.instantly_campaign_id (if provided)
    Returns (company_id, contact_id) or (None, None).
    """
    # Strategy 1: direct email match
    try:
        result = (
            db.client.table("contacts")
            .select("id, company_id")
            .eq("email", from_email)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]
            return row["company_id"], row["id"]
    except Exception:
        pass

    # Strategy 2: outreach_drafts by campaign_id
    if instantly_campaign_id:
        try:
            result = (
                db.client.table("outreach_drafts")
                .select("company_id, contact_id")
                .eq("instantly_campaign_id", instantly_campaign_id)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return row.get("company_id"), row.get("contact_id")
        except Exception:
            pass

    return None, None


def _create_hitl_queue_entry(
    db,
    thread_id: str,
    message_id: str,
    workspace_id: str,
    classification: str,
    confidence: float,
    priority: int,
) -> Optional[dict]:
    """Insert a row into hitl_queue. Returns the row or None on failure."""
    try:
        result = db.client.table("hitl_queue").insert({
            "thread_id": thread_id,
            "message_id": message_id,
            "workspace_id": workspace_id,
            "classification": classification,
            "classification_confidence": confidence,
            "priority": priority,
            "status": "pending",
        }).execute()
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.error("Failed to create hitl_queue entry: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_email_reply(db, payload: dict) -> dict:
    """Process email.reply event — the primary HITL trigger."""
    from backend.app.core.reply_classifier import ReplyClassifier

    from_email: str = payload.get("from_email") or payload.get("from", "") or ""
    to_email: str = payload.get("to_email") or payload.get("to", "") or ""
    subject: str = payload.get("subject", "")
    body_text: str = payload.get("body_text") or payload.get("body", "")
    instantly_campaign_id: Optional[str] = payload.get("campaign_id") or payload.get("instantly_campaign_id")
    lead_id: Optional[str] = payload.get("lead_id")
    sent_at: str = payload.get("timestamp") or payload.get("sent_at") or _now_iso()

    if not from_email:
        return {"status": "ignored", "reason": "no from_email in payload"}

    if not body_text:
        body_text = payload.get("body_html", "") or ""

    # 1. Find company + contact
    company_id, contact_id = _lookup_company_contact(db, from_email, instantly_campaign_id)
    if not company_id or not contact_id:
        logger.warning("email.reply: no company/contact found for %s", from_email)
        return {"status": "ignored", "reason": f"no contact found for {from_email}"}

    # 2. Find or create thread
    thread = _find_or_create_thread(db, company_id, contact_id, instantly_campaign_id)
    thread_id = thread["id"]

    # 3. Gather thread context for classification
    company = db.get_company(company_id) or {}
    contacts_list = db.get_contacts_for_company(company_id)
    contact = next((c for c in contacts_list if c.get("id") == contact_id), {})

    thread_context = {
        "company_name": company.get("name", "Unknown"),
        "contact_name": contact.get("full_name", contact.get("first_name", "Unknown")),
        "sequence_step": thread.get("current_step", 1),
        "previous_messages": 0,  # filled below
    }

    # Count existing messages for context
    try:
        msg_count_result = (
            db.client.table("thread_messages")
            .select("id", count="exact")
            .eq("thread_id", thread_id)
            .execute()
        )
        thread_context["previous_messages"] = msg_count_result.count or 0
    except Exception:
        pass

    # 4. Classify
    clf = ReplyClassifier()
    try:
        classification = clf.classify(body_text, thread_context)
    except Exception as exc:
        logger.error("ReplyClassifier failed: %s", exc)
        # Fallback classification — don't drop the reply
        from backend.app.core.reply_classifier import ReplyClassification
        classification = ReplyClassification(
            intent="other",
            confidence=0.0,
            extracted_entities={"competitors": [], "pain_points": [], "timeline": ""},
            summary="Classification failed — please review manually.",
            next_action_suggestion="Review reply manually.",
            auto_actionable=False,
        )

    # 5. Insert thread_message
    msg_data = {
        "thread_id": thread_id,
        "direction": "inbound",
        "subject": subject,
        "body": body_text,
        "sent_at": sent_at,
        "classification": classification.intent,
        "classification_confidence": classification.confidence,
        "classification_reasoning": classification.summary,
        "extracted_entities": classification.extracted_entities,
        "summary": classification.summary,
        "next_action_suggestion": classification.next_action_suggestion,
        "source": "instantly_webhook",
        "raw_webhook_payload": payload,
    }
    try:
        msg_result = db.client.table("thread_messages").insert(msg_data).execute()
        message_id = msg_result.data[0]["id"] if msg_result.data else None
    except Exception as exc:
        logger.error("Failed to insert thread_message: %s", exc)
        message_id = None

    # 6. Update thread status
    thread_update = {
        "status": "replied",
        "last_replied_at": _now_iso(),
    }
    try:
        db.client.table("campaign_threads").update(thread_update).eq("id", thread_id).execute()
    except Exception as exc:
        logger.error("Failed to update thread status: %s", exc)

    # 7. Auto-action or create HITL queue entry
    hitl_id = None
    workspace_id = db.workspace_id or "default"

    if classification.auto_actionable:
        # Auto-handle unsubscribe / bounce without HITL
        if classification.intent == "unsubscribe":
            try:
                db.client.table("campaign_threads").update({"status": "unsubscribed"}).eq("id", thread_id).execute()
                db.update_contact(contact_id, {"outreach_state": "unsubscribed"})
                db.add_to_dnc(from_email, reason="unsubscribed", added_by="instantly_webhook")
            except Exception as exc:
                logger.error("Unsubscribe auto-action failed: %s", exc)
        elif classification.intent == "bounce":
            try:
                db.client.table("campaign_threads").update({"status": "bounced"}).eq("id", thread_id).execute()
                db.update_contact(contact_id, {"outreach_state": "bounced"})
                db.update_company(company_id, {"status": "bounced"})
            except Exception as exc:
                logger.error("Bounce auto-action failed: %s", exc)
    else:
        # Queue for human review
        if message_id:
            priority = clf.priority_for(classification.intent)
            hitl_entry = _create_hitl_queue_entry(
                db=db,
                thread_id=thread_id,
                message_id=message_id,
                workspace_id=workspace_id,
                classification=classification.intent,
                confidence=classification.confidence,
                priority=priority,
            )
            hitl_id = hitl_entry["id"] if hitl_entry else None

    # 8. Update thread status to awaiting_review if not auto-actioned
    if not classification.auto_actionable:
        try:
            db.client.table("campaign_threads").update(
                {"status": "awaiting_review"}
            ).eq("id", thread_id).execute()
        except Exception:
            pass

    return {
        "status": "processed",
        "thread_id": thread_id,
        "message_id": message_id,
        "classification": classification.intent,
        "confidence": classification.confidence,
        "auto_actioned": classification.auto_actionable,
        "hitl_queue_id": hitl_id,
        "company_id": company_id,
        "contact_id": contact_id,
    }


def _handle_email_bounced(db, payload: dict) -> dict:
    """Handle hard/soft bounce events."""
    from_email: str = payload.get("from_email") or payload.get("to", "") or ""
    company_id, contact_id = _lookup_company_contact(db, from_email)

    if not company_id or not contact_id:
        return {"status": "ignored", "reason": f"no contact found for {from_email}"}

    try:
        db.update_contact(contact_id, {"outreach_state": "bounced"})
        db.update_company(company_id, {"status": "bounced"})
        db.add_to_dnc(from_email, reason="bounced", added_by="instantly_webhook")

        # Update thread if one exists
        thread = _find_thread(db, contact_id, company_id)
        if thread:
            db.client.table("campaign_threads").update({"status": "bounced"}).eq("id", thread["id"]).execute()
    except Exception as exc:
        logger.error("Bounce handling failed: %s", exc)

    return {"status": "processed", "action": "bounced", "email": from_email}


def _handle_email_unsubscribed(db, payload: dict) -> dict:
    """Handle unsubscribe events."""
    from_email: str = payload.get("from_email") or payload.get("email", "") or ""
    company_id, contact_id = _lookup_company_contact(db, from_email)

    if not company_id or not contact_id:
        return {"status": "ignored", "reason": f"no contact found for {from_email}"}

    try:
        db.update_contact(contact_id, {"outreach_state": "unsubscribed"})
        db.add_to_dnc(from_email, reason="unsubscribed", added_by="instantly_webhook")

        thread = _find_thread(db, contact_id, company_id)
        if thread:
            db.client.table("campaign_threads").update({"status": "unsubscribed"}).eq("id", thread["id"]).execute()
    except Exception as exc:
        logger.error("Unsubscribe handling failed: %s", exc)

    return {"status": "processed", "action": "unsubscribed", "email": from_email}


def _handle_email_opened(db, payload: dict) -> dict:
    """Handle email open events — update engagement signal."""
    to_email: str = payload.get("to_email") or payload.get("email", "") or ""
    company_id, contact_id = _lookup_company_contact(db, to_email)

    if not contact_id:
        return {"status": "ignored", "reason": "contact not found"}

    try:
        # Increment open_count on contact
        contact = db.client.table("contacts").select("open_count").eq("id", contact_id).limit(1).execute()
        current = contact.data[0].get("open_count", 0) if contact.data else 0
        db.client.table("contacts").update({
            "open_count": (current or 0) + 1,
            "last_opened_at": _now_iso(),
        }).eq("id", contact_id).execute()
    except Exception as exc:
        logger.debug("open_count update failed (column may not exist): %s", exc)

    return {"status": "processed", "action": "opened"}


def _handle_email_clicked(db, payload: dict) -> dict:
    """Handle link click events — update engagement signal."""
    to_email: str = payload.get("to_email") or payload.get("email", "") or ""
    company_id, contact_id = _lookup_company_contact(db, to_email)

    if not contact_id:
        return {"status": "ignored", "reason": "contact not found"}

    try:
        contact = db.client.table("contacts").select("click_count").eq("id", contact_id).limit(1).execute()
        current = contact.data[0].get("click_count", 0) if contact.data else 0
        db.client.table("contacts").update({
            "click_count": (current or 0) + 1,
            "last_clicked_at": _now_iso(),
        }).eq("id", contact_id).execute()
    except Exception as exc:
        logger.debug("click_count update failed: %s", exc)

    return {"status": "processed", "action": "clicked"}


# ---------------------------------------------------------------------------
# Main webhook endpoint
# ---------------------------------------------------------------------------

@router.post("/instantly")
async def instantly_webhook(
    request: Request,
    secret: Optional[str] = Query(default=None),
):
    """Receive webhook events from Instantly.ai.

    Validates via URL query param ?secret=... (configured in Instantly dashboard).

    Handled event types:
      - email.reply          → classify → thread → HITL queue
      - email.bounced        → mark bounced + DNC
      - email.unsubscribed   → mark unsubscribed + DNC
      - email.opened         → increment open_count
      - email.clicked        → increment click_count

    Legacy event_type keys (reply_received, email_bounced, etc.) are mapped
    to the new handlers for backwards compatibility.
    """
    settings = get_settings()

    if settings.webhook_secret and secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload: dict[str, Any] = await request.json()

    # Normalise event type — Instantly uses both dot-notation and underscore styles
    event_type: str = (
        payload.get("event_type")
        or payload.get("type")
        or ""
    ).lower().strip()

    if not event_type:
        return {"status": "ignored", "reason": "no event_type"}

    # Map legacy keys to canonical names
    _LEGACY_MAP = {
        "reply_received": "email.reply",
        "email_reply": "email.reply",
        "email_opened": "email.opened",
        "email_open": "email.opened",
        "email_clicked": "email.clicked",
        "email_click": "email.clicked",
        "email_bounced": "email.bounced",
        "email_bounce": "email.bounced",
        "email_unsubscribed": "email.unsubscribed",
        "email_unsubscribe": "email.unsubscribed",
    }
    event_type = _LEGACY_MAP.get(event_type, event_type)

    try:
        db = _get_db_and_workspace()

        if event_type == "email.reply":
            result = _handle_email_reply(db, payload)
        elif event_type == "email.bounced":
            result = _handle_email_bounced(db, payload)
        elif event_type == "email.unsubscribed":
            result = _handle_email_unsubscribed(db, payload)
        elif event_type == "email.opened":
            result = _handle_email_opened(db, payload)
        elif event_type == "email.clicked":
            result = _handle_email_clicked(db, payload)
        else:
            # Unknown event — pass through to EngagementAgent for legacy handling
            try:
                from backend.app.agents.engagement import EngagementAgent
                result = EngagementAgent.process_webhook_event(event_type, payload)
            except Exception:
                result = {"status": "ignored", "reason": f"unknown event_type: {event_type}"}

        # Slack notification for high-priority replies
        if event_type == "email.reply" and result.get("status") == "processed":
            classification = result.get("classification", "")
            if classification in ("interested", "referral"):
                try:
                    from backend.app.utils.notifications import notify_slack
                    company_id = result.get("company_id")
                    company = db.get_company(company_id) if company_id else None
                    company_name = company.get("name", "Unknown") if company else "Unknown"
                    priority_label = "P1 HOT" if classification == "interested" else "P2 REFERRAL"
                    notify_slack(
                        f"*[{priority_label}] Reply from {company_name}* — "
                        f"classified as *{classification}* "
                        f"(confidence: {result.get('confidence', 0):.0%}). "
                        "Review in the HITL queue.",
                        emoji=":fire:" if classification == "interested" else ":handshake:",
                    )
                except Exception:
                    pass

        return result

    except Exception as exc:
        logger.error("Webhook processing error for %s: %s", event_type, exc, exc_info=True)
        return {"status": "error", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Resend webhook — email delivery, open, click, bounce, complaint events
# ---------------------------------------------------------------------------

@router.post("/resend")
async def resend_webhook(
    request: Request,
    secret: Optional[str] = Query(default=None),
):
    """Receive delivery events from Resend.

    Configure in Resend dashboard → Webhooks → add endpoint:
      https://prospectiq-production-4848.up.railway.app/api/webhooks/resend?secret=YOUR_SECRET

    Handled event types:
      email.delivered   → confirm delivery
      email.opened      → advance company status to 'engaged', update contact signal
      email.clicked     → same as opened + higher engagement signal
      email.bounced     → DNC, pause sequence, mark contact bounced
      email.complained  → DNC, pause sequence (spam complaint)

    Resend payload shape:
      {
        "type": "email.opened",
        "data": {
          "email_id": "re_abc123",      ← matches resend_message_id on outreach_drafts
          "from": "avi@digitillis.io",
          "to": ["prospect@company.com"],
          "subject": "...",
          "created_at": "2026-04-06T..."
        }
      }
    """
    settings = get_settings()

    # Simple shared-secret validation (same pattern as Instantly webhook)
    if settings.resend_webhook_secret and secret != settings.resend_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload: dict[str, Any] = await request.json()
    event_type: str = (payload.get("type") or "").lower().strip()
    data: dict[str, Any] = payload.get("data") or {}

    resend_message_id: str = data.get("email_id") or data.get("id") or ""
    # Resend sends "to" as a list
    to_field = data.get("to") or []
    recipient_email: str = to_field[0] if isinstance(to_field, list) and to_field else str(to_field)

    if not event_type:
        return {"status": "ignored", "reason": "no event type"}

    try:
        db = _get_db_and_workspace()

        # --- Resolve draft → contact/company ---
        draft_row: dict | None = None
        contact_id: str | None = None
        company_id: str | None = None

        # Primary: look up by resend_message_id stored at send time
        if resend_message_id:
            try:
                r = (
                    db._filter_ws(
                        db.client.table("outreach_drafts")
                        .select("id, company_id, contact_id, sequence_name")
                    )
                    .eq("resend_message_id", resend_message_id)
                    .limit(1)
                    .execute()
                )
                if r.data:
                    draft_row = r.data[0]
                    contact_id = draft_row["contact_id"]
                    company_id = draft_row["company_id"]
            except Exception as exc:
                logger.debug("resend_message_id lookup failed: %s", exc)

        # Fallback: look up by recipient email
        if not contact_id and recipient_email:
            company_id, contact_id = _lookup_company_contact(db, recipient_email)

        if not contact_id:
            return {"status": "ignored", "reason": f"no contact found for {recipient_email or resend_message_id}"}

        now_iso = _now_iso()

        # --- Handle each event type ---

        # sender_email is in data.from for all Resend events
        sender_email: str = data.get("from") or ""

        if event_type == "email.delivered":
            try:
                update = {"resend_status": "delivered"}
                if sender_email:
                    update["sender_email"] = sender_email
                q = db._filter_ws(
                    db.client.table("outreach_drafts").update(update)
                )
                if draft_row:
                    q = q.eq("id", draft_row["id"])
                elif contact_id:
                    q = q.eq("contact_id", contact_id).not_.is_("sent_at", "null")
                q.execute()
            except Exception as exc:
                logger.debug("delivered status update failed: %s", exc)
            return {"status": "processed", "action": "delivered", "contact_id": contact_id}

        elif event_type in ("email.opened", "email.clicked"):
            action = "opened" if event_type == "email.opened" else "clicked"
            count_col = "open_count" if action == "opened" else "click_count"
            time_col = "last_opened_at" if action == "opened" else "last_clicked_at"
            draft_time_col = "opened_at" if action == "opened" else "clicked_at"

            # Stamp timestamp on draft
            try:
                draft_update = {draft_time_col: now_iso}
                if sender_email:
                    draft_update["sender_email"] = sender_email
                q = db._filter_ws(db.client.table("outreach_drafts").update(draft_update))
                if draft_row:
                    q = q.eq("id", draft_row["id"])
                elif contact_id:
                    q = q.eq("contact_id", contact_id).not_.is_("sent_at", "null")
                q.execute()
            except Exception as exc:
                logger.debug("Draft timestamp update failed: %s", exc)

            # Increment signal counter on contact
            try:
                contact_r = db.client.table("contacts").select(count_col).eq("id", contact_id).limit(1).execute()
                current = contact_r.data[0].get(count_col, 0) if contact_r.data else 0
                db.client.table("contacts").update({
                    count_col: (current or 0) + 1,
                    time_col: now_iso,
                }).eq("id", contact_id).execute()
            except Exception as exc:
                logger.debug("Signal counter update failed: %s", exc)

            # Advance company status to 'engaged' (guarded — won't downgrade)
            if company_id:
                db.update_company(company_id, {"status": "engaged"})

            # Update campaign_thread status
            try:
                thread = _find_thread(db, contact_id, company_id)
                if thread:
                    db.client.table("campaign_threads").update({
                        "status": "opened" if action == "opened" else "clicked",
                        "last_opened_at": now_iso,
                    }).eq("id", thread["id"]).execute()
            except Exception as exc:
                logger.debug("Thread update failed: %s", exc)

            # Log as an interaction
            try:
                db.insert_interaction({
                    "company_id": company_id,
                    "contact_id": contact_id,
                    "type": f"email_{action}",
                    "channel": "email",
                    "source": "resend_webhook",
                    "metadata": {
                        "resend_message_id": resend_message_id,
                        "sender_email": sender_email,
                        "subject": data.get("subject"),
                    },
                })
            except Exception:
                pass

            return {"status": "processed", "action": action, "contact_id": contact_id, "company_id": company_id}

        elif event_type in ("email.bounced", "email.complained"):
            action = "bounced" if event_type == "email.bounced" else "complained"
            dnc_reason = "bounced" if action == "bounced" else "spam_complaint"
            draft_time_col = "bounced_at" if action == "bounced" else "complained_at"

            try:
                # Stamp draft with bounce/complaint time + sender
                try:
                    draft_update = {draft_time_col: now_iso}
                    if sender_email:
                        draft_update["sender_email"] = sender_email
                    q = db._filter_ws(db.client.table("outreach_drafts").update(draft_update))
                    if draft_row:
                        q = q.eq("id", draft_row["id"])
                    elif contact_id:
                        q = q.eq("contact_id", contact_id).not_.is_("sent_at", "null")
                    q.execute()
                except Exception as exc:
                    logger.debug("Draft bounce stamp failed: %s", exc)

                contact_update: dict = {"outreach_state": action}
                if action in ("bounced", "not_interested"):
                    contact_update["status"] = action
                db.update_contact(contact_id, contact_update)
                if company_id:
                    db.update_company(company_id, {"status": "bounced"}, allow_downgrade=True)
                if recipient_email:
                    db.add_to_dnc(recipient_email, reason=dnc_reason, added_by="resend_webhook")

                # Pause active engagement sequences for this contact
                active_seqs = (
                    db.client.table("engagement_sequences")
                    .select("id")
                    .eq("contact_id", contact_id)
                    .in_("status", ["active", "paused"])
                    .execute()
                )
                for seq in (active_seqs.data or []):
                    db.client.table("engagement_sequences").update({
                        "status": "cancelled",
                        "updated_at": now_iso,
                    }).eq("id", seq["id"]).execute()

                # Update thread
                thread = _find_thread(db, contact_id, company_id)
                if thread:
                    db.client.table("campaign_threads").update({"status": action}).eq("id", thread["id"]).execute()

            except Exception as exc:
                logger.error("Bounce/complaint handling failed: %s", exc)

            return {"status": "processed", "action": action, "contact_id": contact_id}

        else:
            return {"status": "ignored", "reason": f"unhandled event type: {event_type}"}

    except Exception as exc:
        logger.error("Resend webhook error for %s: %s", event_type, exc, exc_info=True)
        return {"status": "error", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Trigify webhook — competitor engagement signals
# ---------------------------------------------------------------------------

@router.post("/trigify")
async def trigify_webhook(request: Request):
    """Receive competitor engagement signals from Trigify.

    Fired when a prospect company employee engages with a configured
    competitor's LinkedIn post (like, comment, share, follow).

    Expected payload (Trigify standard format):
    {
        "event": "engagement",
        "engagement_type": "liked|commented|shared|followed",
        "actor": {
            "linkedin_profile_url": "...",
            "name": "...",
            "company_name": "...",
            "company_linkedin_url": "..."
        },
        "target": {
            "company_name": "...",  # the competitor
            "linkedin_url": "..."
        },
        "timestamp": "ISO8601"
    }

    Maps to signal_weights.yaml competitor_engagement weights.
    """
    payload: dict[Any, Any] = await request.json()

    engagement_type = payload.get("engagement_type", "liked_competitor_post")
    actor = payload.get("actor", {})
    target = payload.get("target", {})

    company_name = actor.get("company_name", "")
    company_li_url = actor.get("company_linkedin_url", "")
    actor_name = actor.get("name", "")
    competitor_name = target.get("company_name", "")

    if not company_name and not company_li_url:
        return {"status": "ignored", "reason": "no company info in actor payload"}

    logger.info(
        "Trigify: %s engagement by %s at %s with competitor %s",
        engagement_type, actor_name, company_name, competitor_name,
    )

    try:
        from backend.app.core.database import Database
        from backend.app.core.workspace import get_workspace_id
        from backend.app.agents.signal_monitor import _upsert_intent_signal, _get_signal_weight, _recalculate_pqs_timing
        from backend.app.core.config import load_yaml_config
        from datetime import datetime, timezone

        db = Database(workspace_id=get_workspace_id())

        # Find company by name or LinkedIn URL
        company = None
        if company_li_url:
            result = (
                db.client.table("companies")
                .select("*")
                .eq("linkedin_url", company_li_url)
                .limit(1)
                .execute()
            )
            company = result.data[0] if result.data else None

        if not company and company_name:
            result = (
                db.client.table("companies")
                .select("*")
                .ilike("name", f"%{company_name}%")
                .limit(1)
                .execute()
            )
            company = result.data[0] if result.data else None

        if not company:
            return {"status": "ignored", "reason": f"company '{company_name}' not found in ProspectIQ"}

        company_id = company["id"]

        # Map engagement type to signal key
        signal_type_map = {
            "liked": "liked_competitor_post",
            "commented": "commented_competitor_post",
            "shared": "shared_competitor_post",
            "followed": "followed_competitor",
        }
        signal_key = signal_type_map.get(engagement_type.lower(), "liked_competitor_post")

        try:
            signal_config = load_yaml_config("signal_weights.yaml")
        except FileNotFoundError:
            signal_config = {}

        signal_data = {
            "signal_type": signal_key,
            "description": (
                f"{actor_name} at {company_name} {engagement_type} "
                f"content from competitor {competitor_name}"
            ),
            "date_approx": datetime.now(timezone.utc).strftime("%Y-%m"),
            "source": "trigify",
            "confidence": "high",
            "outreach_angle": (
                f"{company_name} is actively engaging with {competitor_name} content — "
                "likely in active evaluation mode. Reach out with differentiation message."
            ),
        }

        _upsert_intent_signal(db=db, company_id=company_id, signal_type=signal_key, signal_data=signal_data)

        weight = _get_signal_weight(signal_config, signal_key)
        _recalculate_pqs_timing(db, company, weight)

        # Log interaction
        db.insert_interaction({
            "company_id": company_id,
            "type": "note",
            "channel": "linkedin",
            "subject": f"Trigify signal: {signal_key}",
            "body": signal_data["description"],
            "source": "trigify_webhook",
            "metadata": {"payload": payload},
        })

        # Notify Slack for high-value signals
        if engagement_type.lower() in ("commented", "shared"):
            try:
                from backend.app.utils.notifications import notify_slack
                notify_slack(
                    f"*Trigify signal: {company_name}* — employee {engagement_type} "
                    f"{competitor_name} content. +{weight} PQS timing.",
                    emoji=":competition:",
                )
            except Exception:
                pass

        return {
            "status": "processed",
            "company": company_name,
            "signal": signal_key,
            "pqs_delta": weight,
        }

    except Exception as exc:
        logger.error("Trigify webhook error: %s", exc, exc_info=True)
        return {"status": "error", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Meeting transcript webhook — Fathom / Fireflies
# ---------------------------------------------------------------------------

@router.post("/meeting-transcript")
async def meeting_transcript_webhook(request: Request):
    """Receive meeting transcripts from Fathom or Fireflies.

    Fathom format: {"event": "meeting.completed", "meeting": {...}, "transcript": "..."}
    Fireflies format: {"event_type": "Transcription completed", "meeting_id": "...", "transcript_text": "..."}
    Manual format: {"company_id": "...", "contact_id": "...", "transcript": "...", "meeting_date": "..."}

    Extracts structured intelligence, updates company status,
    and queues follow-up draft for HITL approval.
    """
    settings = get_settings()

    # Validate webhook secret if configured
    webhook_secret = getattr(settings, "webhook_secret", "") or ""
    if webhook_secret:
        signature = request.headers.get("X-Webhook-Secret", "")
        if signature != webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload: dict[Any, Any] = await request.json()

    # Normalise across Fathom, Fireflies, and manual formats
    event_type = (payload.get("event") or payload.get("event_type") or "").lower()

    transcript: str = (
        payload.get("transcript")
        or payload.get("transcript_text")
        or (payload.get("meeting", {}) or {}).get("transcript", "")
        or ""
    )

    company_id: str = payload.get("company_id", "")
    contact_id: str | None = payload.get("contact_id")
    meeting_date: str | None = payload.get("meeting_date")
    source: str = "fathom" if "fathom" in event_type else (
        "fireflies" if "fireflies" in event_type else "manual"
    )

    # Fathom/Fireflies: try to match company from meeting title or attendees
    if not company_id and payload.get("meeting"):
        meeting = payload["meeting"]
        title = meeting.get("title", "")
        if title:
            try:
                from backend.app.core.database import Database
                from backend.app.core.workspace import get_workspace_id
                db = Database(workspace_id=get_workspace_id())
                result = (
                    db.client.table("companies")
                    .select("id")
                    .ilike("name", f"%{title.split()[0]}%")
                    .limit(1)
                    .execute()
                )
                if result.data:
                    company_id = result.data[0]["id"]
            except Exception:
                pass

    if not company_id:
        return {
            "status": "ignored",
            "reason": "company_id could not be determined — pass company_id explicitly",
        }

    if not transcript:
        return {"status": "ignored", "reason": "no transcript content in payload"}

    try:
        from backend.app.agents.post_meeting import PostMeetingAgent
        agent = PostMeetingAgent()
        result = agent.execute(
            company_id=company_id,
            contact_id=contact_id,
            transcript=transcript,
            meeting_date=meeting_date,
            meeting_source=source,
        )
        return {
            "status": "processed",
            "processed": result.processed,
            "errors": result.errors,
            "details": result.details[:3],
        }
    except Exception as exc:
        logger.error("Meeting transcript webhook error: %s", exc, exc_info=True)
        return {"status": "error", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Apollo async phone webhook
# ---------------------------------------------------------------------------

@router.post("/apollo/phone")
async def apollo_phone_webhook(request: Request):
    """Receive async phone results from Apollo People Match.

    Apollo delivers phone numbers asynchronously when reveal_phone_number=True
    in the people/match request. Configure this URL in Apollo webhook settings.

    Expected payload structure (Apollo webhook format):
        { "person": { "id": "...", "phone_number": "...", ... } }
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid json"}

    person = body.get("person") or body  # tolerate bare payload
    apollo_id = person.get("id") or person.get("apollo_id")
    phone = person.get("phone_number") or person.get("sanitized_phone")

    if not apollo_id or not phone:
        return {"status": "ignored", "reason": "missing apollo_id or phone"}

    try:
        from backend.app.core.database import get_supabase_client
        db = get_supabase_client()
        rows = (
            db.table("contacts")
            .select("id")
            .eq("apollo_id", apollo_id)
            .limit(1)
            .execute()
            .data or []
        )
        if not rows:
            return {"status": "not_found", "apollo_id": apollo_id}

        contact_id = rows[0]["id"]
        db.table("contacts").update({
            "phone": phone,
        }).eq("id", contact_id).execute()

        logger.info("Apollo phone webhook: updated contact %s with phone", contact_id)
        return {"status": "updated", "contact_id": contact_id}
    except Exception as exc:
        logger.error("Apollo phone webhook error: %s", exc)
        return {"status": "error", "reason": str(exc)[:200]}
