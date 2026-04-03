"""HITL (Human-in-the-Loop) review queue API routes.

Provides a dedicated interface for reviewing classified prospect replies
and taking action on them (continue sequence, draft reply, mark converted,
snooze, archive, or unsubscribe).

Endpoints:
    GET  /api/hitl/queue                  — list pending queue items
    GET  /api/hitl/queue/{id}             — full detail (thread + message + company)
    PATCH /api/hitl/queue/{id}/action     — take action on a queue item
    GET  /api/hitl/stats                  — queue statistics
    POST /api/hitl/queue/{id}/suggest-response — AI-drafted reply suggestion
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hitl", tags=["hitl"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_workspace(db: Database) -> str:
    if not db.workspace_id:
        raise HTTPException(status_code=400, detail="Workspace context required")
    return db.workspace_id


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ActionRequest(BaseModel):
    action: str  # continue_sequence | manual_reply | mark_converted | unsubscribe | archive | snooze
    notes: Optional[str] = None
    snooze_until: Optional[str] = None  # ISO datetime string


class SuggestResponseRequest(BaseModel):
    tone: Optional[str] = "professional"  # professional | warm | direct


VALID_ACTIONS = {
    "continue_sequence", "manual_reply", "mark_converted",
    "unsubscribe", "archive", "snooze",
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/queue")
async def list_hitl_queue(
    status: Optional[str] = Query(default="pending", description="pending|reviewing|actioned|snoozed"),
    priority_max: Optional[int] = Query(default=None, description="Only items with priority <= this value"),
    classification: Optional[str] = Query(default=None, description="Filter by classification intent"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List HITL queue items sorted by priority then age.

    Returns items joined with their thread, message, company, and contact.
    """
    db = get_db()
    workspace_id = _require_workspace(db)

    try:
        q = (
            db.client.table("hitl_queue")
            .select("*, campaign_threads(id, status, current_step, company_id, contact_id, instantly_campaign_id)")
            .eq("workspace_id", workspace_id)
        )
        if status:
            q = q.eq("status", status)
        if priority_max is not None:
            q = q.lte("priority", priority_max)
        if classification:
            q = q.eq("classification", classification)

        q = q.order("priority", desc=False).order("created_at", desc=False).limit(limit)
        result = q.execute()
        items = result.data or []
    except Exception as exc:
        logger.warning("hitl_queue query failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Queue unavailable: {exc}")

    # Enrich with message + company + contact
    enriched = []
    for item in items:
        thread = item.get("campaign_threads") or {}
        company_id = thread.get("company_id")
        contact_id = thread.get("contact_id")

        # Fetch message preview
        message = None
        if item.get("message_id"):
            try:
                msg_res = (
                    db.client.table("thread_messages")
                    .select("id, direction, subject, body, classification, classification_confidence, summary, sent_at, extracted_entities")
                    .eq("id", item["message_id"])
                    .limit(1)
                    .execute()
                )
                message = msg_res.data[0] if msg_res.data else None
            except Exception:
                pass

        # Fetch company (basic)
        company = None
        if company_id:
            try:
                c_res = (
                    db.client.table("companies")
                    .select("id, name, tier, pqs_total, status, research_summary, personalization_hooks")
                    .eq("id", company_id)
                    .limit(1)
                    .execute()
                )
                company = c_res.data[0] if c_res.data else None
            except Exception:
                pass

        # Fetch contact (basic)
        contact = None
        if contact_id:
            try:
                ct_res = (
                    db.client.table("contacts")
                    .select("id, full_name, title, email, persona_type")
                    .eq("id", contact_id)
                    .limit(1)
                    .execute()
                )
                contact = ct_res.data[0] if ct_res.data else None
            except Exception:
                pass

        enriched.append({
            **item,
            "message": message,
            "company": company,
            "contact": contact,
        })

    return {
        "data": enriched,
        "count": len(enriched),
        "status_filter": status,
    }


@router.get("/queue/{hitl_id}")
async def get_hitl_detail(hitl_id: str):
    """Full HITL detail: queue item + full thread history + company research + suggested action."""
    db = get_db()
    workspace_id = _require_workspace(db)

    try:
        item_res = (
            db.client.table("hitl_queue")
            .select("*")
            .eq("id", hitl_id)
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        if not item_res.data:
            raise HTTPException(status_code=404, detail=f"HITL item {hitl_id} not found")
        item = item_res.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    thread_id = item["thread_id"]

    # Full thread
    thread = None
    try:
        t_res = (
            db.client.table("campaign_threads")
            .select("*")
            .eq("id", thread_id)
            .limit(1)
            .execute()
        )
        thread = t_res.data[0] if t_res.data else None
    except Exception:
        pass

    # All messages in thread
    messages = []
    try:
        msgs_res = (
            db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .order("sent_at", desc=False)
            .execute()
        )
        messages = msgs_res.data or []
    except Exception:
        pass

    # Company with full research
    company = None
    research = None
    if thread:
        company_id = thread.get("company_id")
        contact_id = thread.get("contact_id")

        if company_id:
            company = db.get_company(company_id)
            research = db.get_research(company_id)

        # Contact detail
        contact = None
        if contact_id:
            try:
                ct_res = (
                    db.client.table("contacts")
                    .select("*")
                    .eq("id", contact_id)
                    .limit(1)
                    .execute()
                )
                contact = ct_res.data[0] if ct_res.data else None
            except Exception:
                pass

    return {
        "data": {
            **item,
            "thread": thread,
            "messages": messages,
            "company": company,
            "research": research,
            "contact": contact,
        }
    }


@router.patch("/queue/{hitl_id}/action")
async def action_hitl_item(hitl_id: str, body: ActionRequest):
    """Take action on a HITL queue item.

    Supported actions and their side effects:
      continue_sequence  → thread status back to 'active'
      manual_reply       → mark thread awaiting outbound draft
      mark_converted     → company status = converted, thread = converted
      unsubscribe        → add to DNC, thread = unsubscribed
      archive            → thread = closed, item actioned
      snooze             → item snoozed until snooze_until
    """
    if body.action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{body.action}'. Must be one of: {', '.join(sorted(VALID_ACTIONS))}",
        )

    db = get_db()
    workspace_id = _require_workspace(db)

    # Fetch queue item
    try:
        item_res = (
            db.client.table("hitl_queue")
            .select("*")
            .eq("id", hitl_id)
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        if not item_res.data:
            raise HTTPException(status_code=404, detail=f"HITL item {hitl_id} not found")
        item = item_res.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    thread_id = item["thread_id"]

    # Fetch thread for company/contact IDs
    try:
        t_res = db.client.table("campaign_threads").select("*").eq("id", thread_id).limit(1).execute()
        thread = t_res.data[0] if t_res.data else None
    except Exception:
        thread = None

    company_id = thread.get("company_id") if thread else None
    contact_id = thread.get("contact_id") if thread else None

    # Apply side effects
    if body.action == "continue_sequence":
        if thread:
            try:
                db.client.table("campaign_threads").update({"status": "active"}).eq("id", thread_id).execute()
            except Exception as exc:
                logger.error("continue_sequence thread update failed: %s", exc)

    elif body.action == "mark_converted":
        if company_id:
            try:
                db.update_company(company_id, {"status": "converted"})
                db.client.table("campaign_threads").update({"status": "converted"}).eq("id", thread_id).execute()
            except Exception as exc:
                logger.error("mark_converted failed: %s", exc)

    elif body.action == "unsubscribe":
        if contact_id and thread:
            try:
                contact_res = (
                    db.client.table("contacts")
                    .select("email")
                    .eq("id", contact_id)
                    .limit(1)
                    .execute()
                )
                if contact_res.data:
                    email = contact_res.data[0].get("email", "")
                    if email:
                        db.add_to_dnc(email, reason="hitl_unsubscribe", added_by="hitl_action")
                db.update_contact(contact_id, {"outreach_state": "unsubscribed"})
                db.client.table("campaign_threads").update({"status": "unsubscribed"}).eq("id", thread_id).execute()
            except Exception as exc:
                logger.error("unsubscribe action failed: %s", exc)

    elif body.action == "archive":
        if thread:
            try:
                db.client.table("campaign_threads").update({"status": "closed"}).eq("id", thread_id).execute()
            except Exception as exc:
                logger.error("archive failed: %s", exc)

    elif body.action == "snooze":
        if not body.snooze_until:
            raise HTTPException(status_code=400, detail="snooze_until is required for snooze action")
        try:
            db.client.table("hitl_queue").update({
                "status": "snoozed",
                "snoozed_until": body.snooze_until,
            }).eq("id", hitl_id).execute()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Snooze failed: {exc}")

        # Update thread message with HITL action
        if item.get("message_id"):
            try:
                db.client.table("thread_messages").update({
                    "hitl_action": "snooze",
                    "hitl_notes": body.notes,
                    "hitl_actioned_at": _now_iso(),
                }).eq("id", item["message_id"]).execute()
            except Exception:
                pass

        return {"message": "Snoozed", "hitl_id": hitl_id, "snoozed_until": body.snooze_until}

    # Mark queue item as actioned (for all non-snooze actions)
    try:
        db.client.table("hitl_queue").update({
            "status": "actioned",
            "actioned_at": _now_iso(),
        }).eq("id", hitl_id).execute()
    except Exception as exc:
        logger.error("Failed to mark hitl_queue item as actioned: %s", exc)

    # Update thread message with HITL annotation
    if item.get("message_id"):
        try:
            db.client.table("thread_messages").update({
                "hitl_action": body.action,
                "hitl_notes": body.notes,
                "hitl_actioned_at": _now_iso(),
            }).eq("id", item["message_id"]).execute()
        except Exception:
            pass

    return {
        "message": f"Action '{body.action}' applied",
        "hitl_id": hitl_id,
        "action": body.action,
        "thread_id": thread_id,
    }


@router.get("/stats")
async def get_hitl_stats():
    """HITL queue statistics: pending counts, classification breakdown, avg response time."""
    db = get_db()
    workspace_id = _require_workspace(db)

    pending = 0
    reviewing = 0
    by_classification: dict[str, int] = {}
    avg_response_hours = 0.0

    try:
        # Counts by status
        for s in ("pending", "reviewing", "snoozed"):
            result = (
                db.client.table("hitl_queue")
                .select("id", count="exact")
                .eq("workspace_id", workspace_id)
                .eq("status", s)
                .execute()
            )
            count = result.count or 0
            if s == "pending":
                pending = count
            elif s == "reviewing":
                reviewing = count

        # Classification breakdown (pending only)
        clf_result = (
            db.client.table("hitl_queue")
            .select("classification")
            .eq("workspace_id", workspace_id)
            .eq("status", "pending")
            .execute()
        )
        for row in (clf_result.data or []):
            clf = row.get("classification") or "other"
            by_classification[clf] = by_classification.get(clf, 0) + 1

        # Avg response time (actioned items)
        actioned_result = (
            db.client.table("hitl_queue")
            .select("created_at, actioned_at")
            .eq("workspace_id", workspace_id)
            .eq("status", "actioned")
            .not_.is_("actioned_at", "null")
            .limit(200)
            .execute()
        )
        if actioned_result.data:
            durations = []
            for row in actioned_result.data:
                try:
                    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                    actioned = datetime.fromisoformat(row["actioned_at"].replace("Z", "+00:00"))
                    durations.append((actioned - created).total_seconds() / 3600)
                except Exception:
                    pass
            if durations:
                avg_response_hours = round(sum(durations) / len(durations), 1)

    except Exception as exc:
        logger.warning("hitl_stats failed: %s", exc)

    return {
        "pending": pending,
        "reviewing": reviewing,
        "by_classification": by_classification,
        "avg_response_time_hours": avg_response_hours,
    }


@router.post("/queue/{hitl_id}/suggest-response")
async def suggest_hitl_response(hitl_id: str):
    """Generate an AI-drafted reply suggestion for the selected HITL item.

    Uses Claude Sonnet to draft a contextual reply based on the full thread
    history, company research, and classification reasoning.
    """
    import json
    import anthropic

    db = get_db()
    workspace_id = _require_workspace(db)

    # Fetch queue item
    try:
        item_res = (
            db.client.table("hitl_queue")
            .select("*")
            .eq("id", hitl_id)
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        if not item_res.data:
            raise HTTPException(status_code=404, detail=f"HITL item {hitl_id} not found")
        item = item_res.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    thread_id = item["thread_id"]

    # Gather context
    thread = None
    messages = []
    company = None
    contact = None
    research = None

    try:
        t_res = db.client.table("campaign_threads").select("*").eq("id", thread_id).limit(1).execute()
        thread = t_res.data[0] if t_res.data else None
    except Exception:
        pass

    if thread:
        company_id = thread.get("company_id")
        contact_id = thread.get("contact_id")
        company = db.get_company(company_id) if company_id else None
        research = db.get_research(company_id) if company_id else None
        if contact_id:
            try:
                ct = db.client.table("contacts").select("*").eq("id", contact_id).limit(1).execute()
                contact = ct.data[0] if ct.data else None
            except Exception:
                pass

    try:
        msgs_res = (
            db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .order("sent_at", desc=False)
            .execute()
        )
        messages = msgs_res.data or []
    except Exception:
        pass

    # Build thread history string
    history_parts = []
    for m in messages:
        arrow = "→ OUTBOUND" if m["direction"] == "outbound" else "← INBOUND"
        snippet = (m.get("body") or "")[:500]
        history_parts.append(
            f"[{arrow}]\nSubject: {m.get('subject', '(no subject)')}\n{snippet}"
            + ("..." if len(m.get("body", "")) > 500 else "")
        )
    thread_history = "\n\n---\n\n".join(history_parts) or "(no messages yet)"

    company_name = company.get("name", "Unknown") if company else "Unknown"
    contact_name = contact.get("full_name", contact.get("first_name", "Unknown")) if contact else "Unknown"
    contact_title = contact.get("title", "Unknown") if contact else "Unknown"

    research_summary = ""
    if research:
        research_summary = research.get("company_description", "") or ""
    if not research_summary and company:
        research_summary = company.get("research_summary", "") or ""

    hooks = []
    if company:
        hooks = company.get("personalization_hooks") or []
    if research:
        hooks.extend(research.get("personalization_hooks") or [])
    hooks_text = "\n".join(f"- {h}" for h in hooks[:5]) if hooks else "None available"

    inbound_msg = next((m for m in reversed(messages) if m["direction"] == "inbound"), None)
    classification = item.get("classification") or "other"
    inbound_body = inbound_msg.get("body", "") if inbound_msg else ""
    inbound_subject = inbound_msg.get("subject", "") if inbound_msg else ""

    # Build system prompt from config
    try:
        from backend.app.core.config import get_offer_context, get_outreach_guidelines
        offer = get_offer_context()
        guidelines = get_outreach_guidelines()
        sender = guidelines.get("sender", {})
        sender_name = sender.get("name", "the sender")
        sender_title = sender.get("title", "")
        sender_company = offer.get("company", sender.get("company", "the company"))
        core_vp = offer.get("core_value_prop", "")
        pilot_details = offer.get("pilot_offer", {}).get("description", "")
    except Exception:
        sender_name = "the sender"
        sender_title = ""
        sender_company = "the company"
        core_vp = ""
        pilot_details = ""

    system_prompt = f"""You are a world-class B2B sales writer for {sender_company}, a manufacturing intelligence platform.

Core proposition: {core_vp or "AI agents that predict equipment failures in advance."}
Pilot: {pilot_details or "6-8 weeks, no long-term commitment."}

You are writing a CONTEXT-AWARE reply to a prospect who has responded to our outreach.
Sender: {sender_name}{f", {sender_title}" if sender_title else ""}

Requirements:
1. Directly acknowledge what the prospect said
2. Move the conversation forward based on the classification
3. Match the tone of someone reaching out personally
4. Be SHORT: max 120 words
5. End with a single clear next step
6. Sign off: {sender_name}{f" / {sender_title}" if sender_title else ""} / {sender_company}

Output ONLY valid JSON. No markdown."""

    user_prompt = f"""Draft a reply for this prospect conversation.

COMPANY: {company_name}
CONTACT: {contact_name}, {contact_title}

RESEARCH:
{research_summary[:400] or "Not available"}

PERSONALIZATION HOOKS:
{hooks_text}

CLASSIFICATION: {classification}
INBOUND REPLY SUBJECT: {inbound_subject}
INBOUND REPLY:
{inbound_body[:600]}

FULL THREAD HISTORY:
{thread_history[:1500]}

DRAFTING STRATEGY:
- interested: Propose 2-3 meeting slots this week
- objection: Address head-on; for incumbents explain integration; for budget offer pilot; for timing offer 15-min primer
- referral: Gracefully ask for intro or cc; keep short
- soft_no: Accept gracefully, plant seed, offer reconnect trigger
- other: Ask one clarifying question

OUTPUT FORMAT (JSON):
{{
    "subject": "Re: [keep their subject]",
    "body": "Full reply body with sign-off",
    "tone_notes": "One sentence on angle taken and why"
}}"""

    try:
        from backend.app.core.config import get_settings
        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        parsed = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Suggestion generation failed: {exc}")

    return {
        "subject": parsed.get("subject", f"Re: {inbound_subject}"),
        "body": parsed.get("body", ""),
        "tone_notes": parsed.get("tone_notes", ""),
    }
