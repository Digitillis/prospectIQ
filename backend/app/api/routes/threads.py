"""Thread management routes for ProspectIQ.

Handles listing, viewing, and acting on campaign reply threads.
Uses ThreadManager and ThreadAgent from the core layer.

Endpoints:
    GET  /api/threads                — list threads with last message + classification
    GET  /api/threads/{id}           — full thread with all messages + pending draft
    POST /api/threads/{id}/confirm   — confirm or override classification
    POST /api/threads/{id}/send      — approve draft and send reply via Resend
    POST /api/threads/{id}/regenerate — regenerate next draft with optional instruction
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["threads"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConfirmClassificationRequest(BaseModel):
    message_id: str
    classification: str  # interested|objection|referral|soft_no|out_of_office|unsubscribe|bounce|other
    override: bool = False  # True when user overrides AI classification


class SendDraftRequest(BaseModel):
    draft_id: str
    edited_body: Optional[str] = None  # If user edited in the UI


class RegenerateRequest(BaseModel):
    instruction: Optional[str] = None  # Optional free-text instruction to guide regeneration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_thread_query(db: Database, **filters) -> list[dict]:
    """Query campaign_threads gracefully — returns [] if table does not exist."""
    try:
        q = db.client.table("campaign_threads").select(
            "*, "
            "companies(id, name, tier, pqs_total, campaign_cluster, status, research_summary), "
            "contacts(id, full_name, title, email, persona_type)"
        )
        if db.workspace_id:
            q = q.eq("workspace_id", db.workspace_id)
        for key, value in filters.items():
            if value is not None:
                q = q.eq(key, value)
        result = q.order("updated_at", desc=True).limit(200).execute()
        return result.data or []
    except Exception as exc:
        logger.warning(f"campaign_threads query failed (table may not exist yet): {exc}")
        return []


def _get_last_message(db: Database, thread_id: str) -> dict | None:
    """Return the most recent message for a thread."""
    try:
        result = (
            db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def _get_pending_draft(db: Database, thread: dict) -> dict | None:
    """Find the most recent pending draft for a thread's company + contact."""
    try:
        result = (
            db.client.table("outreach_drafts")
            .select("*")
            .eq("company_id", thread["company_id"])
            .eq("contact_id", thread["contact_id"])
            .eq("approval_status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def _get_all_messages(db: Database, thread_id: str) -> list[dict]:
    """Return all messages for a thread, oldest first."""
    try:
        result = (
            db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .order("sent_at")
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def _enrich_thread(thread: dict, db: Database) -> dict:
    """Attach last_message and summary fields to a thread dict."""
    last_msg = _get_last_message(db, thread["id"])
    thread["last_message"] = last_msg

    # Compute needs_action flag
    inbound = [m for m in ([last_msg] if last_msg else []) if m.get("direction") == "inbound"]
    unclassified = [m for m in inbound if not m.get("classification")]
    thread["needs_action"] = thread["status"] == "paused" or len(unclassified) > 0

    # Derive step display
    current = thread.get("current_step") or 1
    # Approximate total from sequence — if not stored, use 6 as default
    thread["step_display"] = f"Step {current} of 6"

    return thread


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_threads(
    status: Optional[str] = Query(None, description="Filter: active|paused|closed|all"),
    needs_action: Optional[bool] = Query(None, description="Filter to threads needing action"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List campaign threads with last message and classification.

    Returns empty list gracefully when campaign_threads table does not exist.
    """
    db = get_db()

    filter_kwargs: dict[str, Any] = {}
    if status and status != "all":
        filter_kwargs["status"] = status

    threads = _safe_thread_query(db, **filter_kwargs)

    enriched = []
    for t in threads[:limit]:
        t = _enrich_thread(t, db)
        if needs_action is not None:
            if needs_action and not t.get("needs_action"):
                continue
            if not needs_action and t.get("needs_action"):
                continue
        enriched.append(t)

    needs_action_count = sum(1 for t in enriched if t.get("needs_action"))

    return {
        "data": enriched,
        "count": len(enriched),
        "needs_action_count": needs_action_count,
        "table_exists": len(threads) >= 0,  # False only on exception — we return [] on error
    }


@router.get("/{thread_id}")
async def get_thread(thread_id: str):
    """Full thread with all messages and pending draft."""
    db = get_db()

    try:
        result = (
            db.client.table("campaign_threads")
            .select(
                "*, "
                "companies(id, name, tier, pqs_total, campaign_cluster, status, "
                "          research_summary, pain_signals, intent_score, personalization_hooks), "
                "contacts(id, full_name, title, email, persona_type)"
            )
            .eq("id", thread_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        thread = result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Thread table not accessible: {exc}")

    messages = _get_all_messages(db, thread_id)
    pending_draft = _get_pending_draft(db, thread)

    # Fetch research record for richer context
    research = None
    try:
        r = (
            db.client.table("research")
            .select("*")
            .eq("company_id", thread["company_id"])
            .limit(1)
            .execute()
        )
        if r.data:
            research = r.data[0]
    except Exception:
        pass

    thread["messages"] = messages
    thread["pending_draft"] = pending_draft
    thread["research"] = research
    thread["needs_action"] = (
        thread["status"] == "paused"
        or any(
            m.get("direction") == "inbound" and not m.get("classification")
            for m in messages
        )
    )

    return {"data": thread}


@router.post("/{thread_id}/confirm")
async def confirm_classification(thread_id: str, body: ConfirmClassificationRequest):
    """Confirm or override the AI classification for a message.

    Also triggers drafting of the next message if classification warrants a reply.
    """
    db = get_db()

    # Verify thread exists
    try:
        t_result = (
            db.client.table("campaign_threads")
            .select("*")
            .eq("id", thread_id)
            .limit(1)
            .execute()
        )
        if not t_result.data:
            raise HTTPException(status_code=404, detail="Thread not found")
        thread = t_result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # Update message classification
    try:
        db.client.table("thread_messages").update({
            "classification": body.classification,
            "classification_confirmed_by": "user_override" if body.override else "user",
        }).eq("id", body.message_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update classification: {exc}")

    # Apply side effects
    company_id = thread["company_id"]
    status_map = {
        "interested": "engaged",
        "referral": "engaged",
        "soft_no": "qualified",
    }
    if body.classification in status_map:
        try:
            db.client.table("companies").update({
                "status": status_map[body.classification]
            }).eq("id", company_id).execute()
        except Exception:
            pass

    if body.classification == "unsubscribe":
        try:
            db.client.table("campaign_threads").update({"status": "unsubscribed"}).eq("id", thread_id).execute()
            db.client.table("contacts").update({"outreach_state": "unsubscribed"}).eq("id", thread["contact_id"]).execute()
        except Exception:
            pass

    # Auto-draft next message for actionable classifications
    draft_id = None
    if body.classification in ("interested", "objection", "referral", "soft_no", "other"):
        try:
            from backend.app.agents.thread import ThreadAgent
            agent = ThreadAgent()

            # Get the inbound message
            msg_result = db.client.table("thread_messages").select("*").eq("id", body.message_id).limit(1).execute()
            msg = msg_result.data[0] if msg_result.data else {}

            # Build a classification result to pass to draft_next_message
            company_result = db.client.table("companies").select("*").eq("id", company_id).limit(1).execute()
            company = company_result.data[0] if company_result.data else {}

            contacts_result = db.client.table("contacts").select("*").eq("id", thread["contact_id"]).limit(1).execute()
            contact = contacts_result.data[0] if contacts_result.data else {}

            classification_result = {
                "thread": thread,
                "company": company,
                "contact": contact,
                "research": None,
                "reply_subject": msg.get("subject", ""),
                "reply_body": msg.get("body", ""),
                "classification": body.classification,
                "confidence": 1.0,
                "reasoning": "User confirmed" if not body.override else "User override",
                "extracted_signal": "",
                "recommended_next_action": f"Reply based on {body.classification} classification",
            }

            draft = agent.draft_next_message(classification_result)
            draft_id = agent.save_draft(thread, contact, draft, body.classification)
        except Exception as exc:
            logger.warning(f"Auto-draft failed: {exc}")

    return {
        "message": f"Classification set to '{body.classification}'",
        "draft_id": draft_id,
        "draft_queued": draft_id is not None,
    }


@router.post("/{thread_id}/send")
async def send_draft(thread_id: str, body: SendDraftRequest):
    """Approve a pending draft and send via Resend."""
    db = get_db()

    # Verify thread
    try:
        t_result = db.client.table("campaign_threads").select("*").eq("id", thread_id).limit(1).execute()
        if not t_result.data:
            raise HTTPException(status_code=404, detail="Thread not found")
        thread = t_result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # Update draft if body was edited
    if body.edited_body:
        try:
            db.client.table("outreach_drafts").update({
                "body": body.edited_body,
                "edited_body": body.edited_body,
                "approval_status": "edited",
            }).eq("id", body.draft_id).execute()
        except Exception as exc:
            logger.warning(f"Could not save edited body: {exc}")

    # Approve the draft
    try:
        db.client.table("outreach_drafts").update({
            "approval_status": "approved",
        }).eq("id", body.draft_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to approve draft: {exc}")

    # Try to send immediately via EngagementAgent
    sent = False
    try:
        from backend.app.core.config import get_settings
        settings = get_settings()
        if settings.send_enabled:
            from backend.app.agents.engagement import EngagementAgent
            agent = EngagementAgent()
            agent.run(action="send_approved")
            sent = True
    except Exception as exc:
        logger.warning(f"Immediate send failed (will be picked up by scheduler): {exc}")

    # Record outbound message in the thread
    try:
        draft_result = db.client.table("outreach_drafts").select("*").eq("id", body.draft_id).limit(1).execute()
        if draft_result.data:
            draft = draft_result.data[0]
            from backend.app.core.thread_manager import ThreadManager
            tm = ThreadManager(db)
            tm.add_outbound_message(
                thread_id=thread_id,
                subject=draft.get("subject", ""),
                body=body.edited_body or draft.get("body", ""),
                outreach_draft_id=body.draft_id,
                source="user_approved",
            )
            tm.resume_thread(thread_id, advance_step=True)
    except Exception as exc:
        logger.warning(f"Could not record outbound in thread: {exc}")

    return {
        "message": "Draft approved" + (" and sent via Resend" if sent else " — queued for next scheduler run"),
        "sent_immediately": sent,
        "draft_id": body.draft_id,
    }


@router.post("/{thread_id}/regenerate")
async def regenerate_draft(thread_id: str, body: RegenerateRequest):
    """Regenerate the next draft, optionally with a specific instruction."""
    db = get_db()

    try:
        t_result = db.client.table("campaign_threads").select("*").eq("id", thread_id).limit(1).execute()
        if not t_result.data:
            raise HTTPException(status_code=404, detail="Thread not found")
        thread = t_result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # Get last inbound message with classification
    try:
        msgs = (
            db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .eq("direction", "inbound")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        last_inbound = msgs.data[0] if msgs.data else None
    except Exception:
        last_inbound = None

    if not last_inbound:
        raise HTTPException(status_code=400, detail="No inbound message found to respond to")

    classification = last_inbound.get("classification") or "other"

    try:
        from backend.app.agents.thread import ThreadAgent
        agent = ThreadAgent()

        company_result = db.client.table("companies").select("*").eq("id", thread["company_id"]).limit(1).execute()
        company = company_result.data[0] if company_result.data else {}

        contact_result = db.client.table("contacts").select("*").eq("id", thread["contact_id"]).limit(1).execute()
        contact = contact_result.data[0] if contact_result.data else {}

        classification_result = {
            "thread": thread,
            "company": company,
            "contact": contact,
            "research": None,
            "reply_subject": last_inbound.get("subject", ""),
            "reply_body": last_inbound.get("body", ""),
            "classification": classification,
            "confidence": last_inbound.get("classification_confidence", 0.8),
            "reasoning": last_inbound.get("classification_reasoning", ""),
            "extracted_signal": body.instruction or "",
            "recommended_next_action": body.instruction or f"Draft reply for {classification}",
        }

        draft = agent.draft_next_message(classification_result)
        draft_id = agent.save_draft(thread, contact, draft, classification)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {exc}")

    return {
        "message": "Draft regenerated",
        "draft_id": draft_id,
        "subject": draft.get("subject", ""),
        "body": draft.get("body", ""),
        "strategy_used": draft.get("strategy_used", ""),
    }
