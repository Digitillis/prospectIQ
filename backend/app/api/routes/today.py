"""Daily Cockpit routes for ProspectIQ API.

Provides the /api/today aggregation endpoint and outcome logging
that power the Daily Cockpit page — Avanish's morning command center.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/today", tags=["today"])


def get_db() -> Database:
    return Database()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class OutcomeRequest(BaseModel):
    company_id: str
    contact_id: Optional[str] = None
    channel: str  # email, linkedin
    outcome: str  # interested, not_now, not_interested, wrong_person, bounce, meeting_booked
    notes: Optional[str] = None


class MarkDoneRequest(BaseModel):
    action_type: str  # linkedin_connection, linkedin_dm, comment, approval
    contact_id: Optional[str] = None
    company_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_hour_greeting() -> str:
    hour = datetime.now(timezone.utc).hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    return "Good evening"


# ---------------------------------------------------------------------------
# GET /api/today
# ---------------------------------------------------------------------------


@router.get("")
async def get_today_data():
    """Aggregate all daily action data into one response for the Daily Cockpit."""
    db = get_db()
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(hours=24)).isoformat()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_str = now.strftime("%A, %B %-d, %Y")
    greeting = f"{_get_hour_greeting()}, Avanish"

    # --- Hot signals: engaged companies ---
    try:
        hot_rows = (
            db.client.table("companies")
            .select(
                "id, name, domain, tier, pqs_total, status, "
                "contacts(id, full_name, title, email, phone, linkedin_url)"
            )
            .eq("status", "engaged")
            .order("pqs_total", desc=True)
            .limit(10)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"Failed to fetch hot signals: {e}")
        hot_rows = []

    # Enrich hot signals with last interaction
    for company in hot_rows:
        try:
            last_interaction = (
                db.client.table("interactions")
                .select("type, body, created_at, metadata")
                .eq("company_id", company["id"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
            company["last_interaction"] = last_interaction[0] if last_interaction else None
        except Exception:
            company["last_interaction"] = None

    # --- Pending approvals ---
    try:
        pending_drafts = (
            db.client.table("outreach_drafts")
            .select(
                "id, company_id, contact_id, channel, sequence_name, sequence_step, "
                "subject, body, personalization_notes, approval_status, "
                "companies(name, tier, pqs_total), "
                "contacts(full_name, title, email)"
            )
            .eq("approval_status", "pending")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"Failed to fetch pending drafts: {e}")
        pending_drafts = []

    pending_count = len(pending_drafts)

    # --- LinkedIn queue: tasks due now ---
    try:
        linkedin_rows = (
            db.client.table("engagement_sequences")
            .select(
                "id, company_id, contact_id, sequence_name, current_step, "
                "total_steps, next_action_at, next_action_type, "
                "companies(name, domain, tier, pqs_total, linkedin_url), "
                "contacts(full_name, title, linkedin_url)"
            )
            .eq("status", "active")
            .lte("next_action_at", now.isoformat())
            .like("next_action_type", "%linkedin%")
            .order("next_action_at")
            .limit(20)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"Failed to fetch linkedin queue: {e}")
        linkedin_rows = []

    # --- LinkedIn connection items (contacts ready for connection request) ---
    linkedin_connect_items: list[dict] = []
    try:
        # Contacts with LinkedIn URL and not yet sent
        connect_contacts = (
            db.client.table("contacts")
            .select(
                "id, full_name, title, linkedin_url, linkedin_status, company_id, seniority, city, state, "
                "companies(id, name, tier, pqs_total, status, domain, industry, employee_count, "
                "revenue_printed, headcount_growth_6m, is_public, parent_company_name, "
                "pain_signals, personalization_hooks, research_summary)"
            )
            .not_.is_("linkedin_url", "null")
            .in_("linkedin_status", ["not_sent", "null"])
            .limit(20)
            .execute()
            .data
        ) or []

        # Filter to only qualified/outreach_pending companies
        for contact in connect_contacts:
            company = contact.get("companies") or {}
            if company.get("status") in ("qualified", "outreach_pending", "researched"):
                # Try to find pre-generated connection draft
                draft_body = None
                draft_id = None
                try:
                    drafts = (
                        db.client.table("outreach_drafts")
                        .select("id, body, personalization_notes")
                        .eq("contact_id", contact["id"])
                        .eq("channel", "linkedin")
                        .in_("sequence_name", ["linkedin_connection", "linkedin_connect"])
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                        .data
                    ) or []
                    if drafts:
                        draft_body = drafts[0].get("body")
                        draft_id = drafts[0].get("id")
                except Exception:
                    pass

                # Build intel block for this contact
                intel_data: dict = {
                    "personalization_notes": "",
                    "company": {
                        "industry": company.get("industry"),
                        "employee_count": company.get("employee_count"),
                        "revenue_printed": company.get("revenue_printed"),
                        "headcount_growth_6m": company.get("headcount_growth_6m"),
                        "is_public": company.get("is_public"),
                        "parent_company_name": company.get("parent_company_name"),
                        "pain_signals": company.get("pain_signals", []),
                        "personalization_hooks": company.get("personalization_hooks", []),
                        "research_summary": company.get("research_summary"),
                    },
                    "research": None,
                    "contact": {
                        "title": contact.get("title"),
                        "seniority": contact.get("seniority"),
                        "city": contact.get("city") or company.get("city"),
                        "state": contact.get("state") or company.get("state"),
                    },
                }
                if drafts and drafts[0].get("personalization_notes"):
                    intel_data["personalization_notes"] = drafts[0]["personalization_notes"]
                # Fetch research
                try:
                    research_rows = (
                        db.client.table("research_intelligence")
                        .select("*")
                        .eq("company_id", contact["company_id"])
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                        .data
                    ) or []
                    if research_rows:
                        row = research_rows[0]
                        # claude_analysis is a JSONB column with structured research
                        ca = row.get("claude_analysis") or {}
                        if isinstance(ca, str):
                            try:
                                import json as _json
                                ca = _json.loads(ca)
                            except Exception:
                                ca = {}
                        intel_data["research"] = {
                            "company_description": ca.get("company_description") or row.get("company_description") or "",
                            "manufacturing_type": ca.get("manufacturing_type") or row.get("manufacturing_type") or "",
                            "equipment_types": ca.get("equipment_types") or row.get("equipment_types") or [],
                            "maintenance_approach": ca.get("maintenance_approach") or row.get("maintenance_approach") or "",
                            "iot_maturity": ca.get("iot_maturity") or row.get("iot_maturity") or "",
                            "pain_points": ca.get("pain_points") or row.get("pain_points") or [],
                            "opportunities": ca.get("opportunities") or row.get("opportunities") or [],
                            "known_systems": ca.get("known_systems") or row.get("known_systems") or [],
                            "existing_solutions": ca.get("existing_solutions") or row.get("existing_solutions") or [],
                            "confidence": row.get("confidence_level"),
                        }
                except Exception:
                    pass

                linkedin_connect_items.append({
                    "contact_id": contact["id"],
                    "company_id": contact["company_id"],
                    "full_name": contact.get("full_name"),
                    "title": contact.get("title"),
                    "linkedin_url": contact.get("linkedin_url"),
                    "linkedin_status": contact.get("linkedin_status"),
                    "company_name": company.get("name"),
                    "company_tier": company.get("tier"),
                    "company_domain": company.get("domain"),
                    "pqs_total": company.get("pqs_total", 0),
                    "draft_id": draft_id,
                    "message_text": draft_body,
                    "intel": intel_data,
                })
        # Sort by PQS descending
        linkedin_connect_items.sort(key=lambda x: x.get("pqs_total", 0), reverse=True)
        linkedin_connect_items = linkedin_connect_items[:15]
    except Exception as e:
        logger.warning(f"Failed to fetch linkedin connect items: {e}")

    # --- LinkedIn DM items (contacts who accepted connection, ready for DM) ---
    linkedin_dm_items: list[dict] = []
    try:
        accepted_contacts = (
            db.client.table("contacts")
            .select(
                "id, full_name, title, linkedin_url, linkedin_status, company_id, seniority, city, state, "
                "companies(id, name, tier, pqs_total, status, domain, industry, employee_count, "
                "revenue_printed, headcount_growth_6m, is_public, parent_company_name, "
                "pain_signals, personalization_hooks, research_summary)"
            )
            .eq("linkedin_status", "accepted")
            .limit(15)
            .execute()
            .data
        ) or []

        for contact in accepted_contacts:
            company = contact.get("companies") or {}
            draft_body = None
            draft_id = None
            try:
                drafts = (
                    db.client.table("outreach_drafts")
                    .select("id, body, personalization_notes")
                    .eq("contact_id", contact["id"])
                    .eq("channel", "linkedin")
                    .in_("sequence_name", ["linkedin_dm_opening", "linkedin_dm"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                ) or []
                if drafts:
                    draft_body = drafts[0].get("body")
                    draft_id = drafts[0].get("id")
            except Exception:
                pass

            # Build intel block for DM contact
            dm_intel_data: dict = {
                "personalization_notes": "",
                "company": {
                    "industry": company.get("industry"),
                    "employee_count": company.get("employee_count"),
                    "revenue_printed": company.get("revenue_printed"),
                    "headcount_growth_6m": company.get("headcount_growth_6m"),
                    "is_public": company.get("is_public"),
                    "parent_company_name": company.get("parent_company_name"),
                    "pain_signals": company.get("pain_signals", []),
                    "personalization_hooks": company.get("personalization_hooks", []),
                    "research_summary": company.get("research_summary"),
                },
                "research": None,
                "contact": {
                    "title": contact.get("title"),
                    "seniority": contact.get("seniority"),
                    "city": contact.get("city"),
                    "state": contact.get("state"),
                },
            }
            if drafts and drafts[0].get("personalization_notes"):
                dm_intel_data["personalization_notes"] = drafts[0]["personalization_notes"]
            try:
                dm_research_rows = (
                    db.client.table("research_intelligence")
                    .select("*")
                    .eq("company_id", contact["company_id"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                ) or []
                if dm_research_rows:
                    dm_ri = dm_research_rows[0].get("research_intelligence") or {}
                    dm_intel_data["research"] = {
                        "products_services": dm_ri.get("products_services", []),
                        "recent_news": dm_ri.get("recent_news", []),
                        "pain_points": dm_ri.get("pain_points", []) or dm_research_rows[0].get("pain_points", []),
                        "known_systems": dm_ri.get("known_systems", []) or dm_research_rows[0].get("known_systems", []),
                        "confidence": dm_research_rows[0].get("confidence_level"),
                    }
            except Exception:
                pass

            linkedin_dm_items.append({
                "contact_id": contact["id"],
                "company_id": contact["company_id"],
                "full_name": contact.get("full_name"),
                "title": contact.get("title"),
                "linkedin_url": contact.get("linkedin_url"),
                "linkedin_status": contact.get("linkedin_status"),
                "company_name": company.get("name"),
                "company_tier": company.get("tier"),
                "company_domain": company.get("domain"),
                "pqs_total": company.get("pqs_total", 0),
                "draft_id": draft_id,
                "message_text": draft_body,
                "intel": dm_intel_data,
            })
    except Exception as e:
        logger.warning(f"Failed to fetch linkedin dm items: {e}")

    # --- Content: today's thought leadership draft ---
    content_items: list[dict] = []
    try:
        content_drafts = (
            db.client.table("outreach_drafts")
            .select("id, subject, body, channel, sequence_name, approval_status, created_at")
            .eq("channel", "other")
            .in_("sequence_name", ["thought_leadership", "content"])
            .in_("approval_status", ["pending", "approved"])
            .order("created_at", desc=True)
            .limit(3)
            .execute()
            .data
        ) or []
        for d in content_drafts:
            content_items.append({
                "draft_id": d.get("id"),
                "topic": d.get("subject", "LinkedIn Post"),
                "post_text": d.get("body", ""),
                "approval_status": d.get("approval_status"),
                "created_at": d.get("created_at"),
            })
    except Exception as e:
        logger.warning(f"Failed to fetch content drafts: {e}")

    # --- Pending acceptances (connections sent, waiting for accept/ignore) ---
    pending_acceptances: list[dict] = []
    try:
        pa_result = (
            db.client.table("contacts")
            .select(
                "id, full_name, title, linkedin_url, company_id, "
                "companies(name, tier, pqs_total)"
            )
            .eq("linkedin_status", "connection_sent")
            .limit(30)
            .execute()
        )
        for c in (pa_result.data or []):
            company = c.get("companies") or {}
            if isinstance(company, list):
                company = company[0] if company else {}
            pending_acceptances.append({
                "contact_id": c["id"],
                "company_id": c.get("company_id"),
                "full_name": c.get("full_name"),
                "title": c.get("title"),
                "linkedin_url": c.get("linkedin_url"),
                "company_name": company.get("name"),
                "company_tier": company.get("tier"),
                "pqs_total": company.get("pqs_total", 0),
            })
    except Exception as e:
        logger.warning(f"Failed to fetch pending acceptances: {e}")

    # --- Pipeline summary ---
    pipeline_summary: dict[str, int] = {}
    pipeline_statuses = [
        "discovered", "researched", "qualified", "outreach_pending",
        "contacted", "engaged", "meeting_scheduled",
    ]
    for status in pipeline_statuses:
        try:
            result = (
                db.client.table("companies")
                .select("id", count="exact")
                .eq("status", status)
                .execute()
            )
            pipeline_summary[status] = result.count or 0
        except Exception:
            pipeline_summary[status] = 0

    # --- Progress: actions completed today ---
    try:
        completed_today = (
            db.client.table("interactions")
            .select("id", count="exact")
            .gte("created_at", today_start)
            .in_("source", ["daily_cockpit", "manual"])
            .execute()
        )
        done_count = completed_today.count or 0
    except Exception:
        done_count = 0

    # --- Per-type counts today ---
    connections_sent_today = 0
    linkedin_dms_today = 0
    emails_approved_today = 0
    outcomes_logged_today = 0

    try:
        conn_result = (
            db.client.table("interactions")
            .select("id", count="exact")
            .gte("created_at", today_start)
            .eq("type", "note")
            .eq("source", "daily_cockpit")
            .execute()
        )
        # We use metadata filtering approximation — count all daily_cockpit actions
        # and break down using the full done_count as proxy
        connections_sent_today = 0  # will be filled from metadata if needed
    except Exception:
        pass

    try:
        # Count interactions with action_type=linkedin_connection in metadata
        # Supabase doesn't support metadata filtering easily, so we fetch recent ones
        recent_cockpit = (
            db.client.table("interactions")
            .select("metadata")
            .gte("created_at", today_start)
            .eq("source", "daily_cockpit")
            .limit(100)
            .execute()
            .data
        ) or []
        for row in recent_cockpit:
            meta = row.get("metadata") or {}
            action_type = meta.get("action_type", "")
            if action_type == "linkedin_connection":
                connections_sent_today += 1
            elif action_type == "linkedin_dm":
                linkedin_dms_today += 1
            elif action_type in ("email_approved", "approval"):
                emails_approved_today += 1
            elif action_type in ("outcome_logged", "log_outcome"):
                outcomes_logged_today += 1
    except Exception as e:
        logger.warning(f"Failed to count daily breakdowns: {e}")

    # Count learning_outcomes as logged outcomes today
    try:
        lo_result = (
            db.client.table("learning_outcomes")
            .select("id", count="exact")
            .gte("recorded_at", today_start)
            .execute()
        )
        outcomes_logged_today = max(outcomes_logged_today, lo_result.count or 0)
    except Exception:
        pass

    # --- Recent interactions needing outcome logging (last 24h) ---
    try:
        recent_interactions = (
            db.client.table("interactions")
            .select(
                "id, type, channel, subject, body, created_at, metadata, "
                "company_id, contact_id, "
                "companies(id, name, tier, pqs_total), "
                "contacts(id, full_name, title)"
            )
            .gte("created_at", yesterday)
            .in_("type", ["email_replied", "email_opened", "linkedin_message"])
            .order("created_at", desc=True)
            .limit(10)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"Failed to fetch recent interactions: {e}")
        recent_interactions = []

    # --- Pending AI-recommended next actions ---
    try:
        today_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pending_actions_result = db.client.table("contact_events").select(
            "id, contact_id, company_id, event_type, channel, body, sentiment, "
            "next_action, next_action_date, suggested_message, action_reasoning, "
            "contacts(full_name, title, linkedin_url), "
            "companies(name, tier, industry)"
        ).eq("next_action_status", "pending").not_.is_("next_action", "null").lte(
            "next_action_date", today_date_str
        ).order("next_action_date").limit(20).execute()

        pending_next_actions = pending_actions_result.data or []
    except Exception:
        pending_next_actions = []

    # --- Build daily_plan sections ---
    daily_plan = {
        "date": today_str,
        "greeting": greeting,
        "sections": [
            {
                "id": "urgent",
                "title": "Respond Now",
                "subtitle": "Hot signals and replies that need immediate attention",
                "icon": "flame",
                "priority": 1,
                "items": hot_rows,
            },
            {
                "id": "next_actions",
                "title": "AI-Recommended Actions",
                "subtitle": f"{len(pending_next_actions)} actions due today",
                "icon": "brain",
                "priority": 2,
                "items": pending_next_actions,
            },
            {
                "id": "linkedin_connect",
                "title": "Send Connection Requests",
                "subtitle": f"Target: 10/day — {connections_sent_today} done",
                "icon": "user-plus",
                "priority": 3,
                "target": 10,
                "completed": connections_sent_today,
                "items": linkedin_connect_items,
            },
            {
                "id": "linkedin_dm",
                "title": "Send Opening DMs",
                "subtitle": "Connections who accepted — start conversations",
                "icon": "message-circle",
                "priority": 4,
                "items": linkedin_dm_items,
            },
            {
                "id": "approve_emails",
                "title": "Review & Approve Emails",
                "subtitle": f"{pending_count} draft{'s' if pending_count != 1 else ''} waiting",
                "icon": "mail-check",
                "priority": 5,
                "items": pending_drafts,
            },
            {
                "id": "content",
                "title": "Post Today's Content",
                "subtitle": "Thought leadership for LinkedIn",
                "icon": "pen-tool",
                "priority": 6,
                "items": content_items,
            },
            {
                "id": "log_outcomes",
                "title": "Log Responses",
                "subtitle": "Record outcomes from recent outreach",
                "icon": "clipboard-check",
                "priority": 7,
                "items": recent_interactions,
            },
            {
                "id": "pipeline",
                "title": "Grow Pipeline",
                "subtitle": "Run discovery, research, qualification",
                "icon": "trending-up",
                "priority": 8,
                "items": [{"summary": pipeline_summary}],
            },
        ],
    }

    total_done_today = done_count

    progress = {
        "target": 20,
        "completed": total_done_today,
        "breakdown": {
            "linkedin_connections": {"done": connections_sent_today, "target": 10},
            "linkedin_dms": {"done": linkedin_dms_today, "target": 5},
            "emails_approved": {"done": emails_approved_today, "target": 3},
            "outcomes_logged": {"done": outcomes_logged_today, "target": 2},
            "content_posted": {"done": 0, "target": 1},
        },
    }

    return {
        "data": {
            # Legacy fields (kept for backward compat)
            "hot_signals": hot_rows,
            "pending_approvals": pending_drafts,
            "linkedin_queue": linkedin_rows,
            "pipeline_summary": pipeline_summary,
            "recent_interactions": recent_interactions,
            "progress": {
                "completed": total_done_today,
                "target": 20,
            },
            # New structured fields
            "daily_plan": daily_plan,
            "progress_detail": progress,
            "pending_next_actions": pending_next_actions,
            "pending_acceptances": pending_acceptances,
        }
    }


# ---------------------------------------------------------------------------
# POST /api/today/log-outcome
# ---------------------------------------------------------------------------


_OUTCOME_STATUS_MAP = {
    "interested": "engaged",
    "meeting_booked": "meeting_scheduled",
    "not_interested": "not_interested",
    # other outcomes don't change company status
}

_OUTCOME_PQS_DELTA = {
    "interested": 5,
    "meeting_booked": 10,
    "not_now": 2,
    "not_interested": -5,
}


@router.post("/log-outcome")
async def log_outcome(req: OutcomeRequest):
    """Log an outcome for an interaction — updates company status and PQS."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Create interaction record
    interaction_data: dict = {
        "company_id": req.company_id,
        "type": "note",
        "channel": req.channel,
        "body": f"Outcome logged: {req.outcome}" + (f"\n\n{req.notes}" if req.notes else ""),
        "source": "daily_cockpit",
        "metadata": {
            "outcome": req.outcome,
            "action_type": "outcome_logged",
            "notes": req.notes,
            "logged_at": now,
        },
    }
    if req.contact_id:
        interaction_data["contact_id"] = req.contact_id

    try:
        db.client.table("interactions").insert(interaction_data).execute()
    except Exception as e:
        logger.error(f"Failed to create interaction: {e}")
        raise HTTPException(status_code=500, detail="Failed to create interaction record")

    # 2. Update company status if outcome maps to a new status
    new_status = _OUTCOME_STATUS_MAP.get(req.outcome)
    if new_status:
        try:
            db.client.table("companies").update({
                "status": new_status,
                "status_changed_at": now,
                "updated_at": now,
                "priority_flag": req.outcome in ("interested", "meeting_booked"),
            }).eq("id", req.company_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update company status: {e}")

    # 3. Update PQS engagement score
    pqs_delta = _OUTCOME_PQS_DELTA.get(req.outcome, 0)
    if pqs_delta != 0:
        try:
            company = (
                db.client.table("companies")
                .select("pqs_engagement, pqs_total")
                .eq("id", req.company_id)
                .execute()
                .data
            )
            if company:
                current_engagement = company[0].get("pqs_engagement", 0) or 0
                current_total = company[0].get("pqs_total", 0) or 0
                new_engagement = max(0, min(25, current_engagement + pqs_delta))
                new_total = max(0, current_total + pqs_delta)
                db.client.table("companies").update({
                    "pqs_engagement": new_engagement,
                    "pqs_total": new_total,
                    "updated_at": now,
                }).eq("id", req.company_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update PQS score: {e}")

    # 4. Add to suppression if not_interested
    if req.outcome == "not_interested":
        try:
            suppress_data: dict = {
                "company_id": req.company_id,
                "reason": "not_interested",
                "source": "daily_cockpit_outcome",
                "notes": req.notes,
            }
            if req.contact_id:
                suppress_data["contact_id"] = req.contact_id
            db.client.table("suppression_list").insert(suppress_data).execute()
        except Exception:
            logger.debug("suppression_list table not found, skipping")

    # 5. Insert learning outcome record
    try:
        learning_data: dict = {
            "company_id": req.company_id,
            "channel": req.channel,
            "outcome": req.outcome,
            "notes": req.notes,
            "recorded_at": now,
        }
        if req.contact_id:
            learning_data["contact_id"] = req.contact_id
        db.client.table("learning_outcomes").insert(learning_data).execute()
    except Exception:
        logger.debug("learning_outcomes table not found, skipping")

    # 6. Create contact_event for the outcome
    if req.contact_id:
        try:
            # Determine event_type and sentiment from outcome
            if req.outcome in ("interested", "not_now", "meeting_booked"):
                ce_event_type = "response_received"
            else:
                ce_event_type = "status_change"

            if req.outcome in ("interested", "meeting_booked"):
                ce_sentiment = "positive"
            elif req.outcome == "not_interested":
                ce_sentiment = "negative"
            else:
                ce_sentiment = "neutral"

            ce_payload: dict = {
                "contact_id": req.contact_id,
                "company_id": req.company_id,
                "event_type": ce_event_type,
                "channel": req.channel,
                "direction": "inbound",
                "body": req.notes,
                "sentiment": ce_sentiment,
                "pqs_delta": pqs_delta,
                "created_by": "user",
                "created_at": now,
            }
            db.client.table("contact_events").insert(ce_payload).execute()
        except Exception as e:
            logger.warning(f"Failed to create contact_event for log-outcome: {e}")

    return {
        "data": {
            "company_id": req.company_id,
            "outcome": req.outcome,
            "new_status": new_status,
            "pqs_delta": pqs_delta,
        },
        "message": f"Outcome '{req.outcome}' logged successfully",
    }


# ---------------------------------------------------------------------------
# POST /api/today/mark-done
# ---------------------------------------------------------------------------


@router.post("/mark-done")
async def mark_done(req: MarkDoneRequest):
    """Mark a daily action as done — logs an interaction and advances sequences."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Log a minimal interaction to count toward the daily progress tracker
    interaction_data: dict = {
        "type": "note",
        "body": f"Daily action completed: {req.action_type}",
        "source": "daily_cockpit",
        "metadata": {
            "action_type": req.action_type,
            "completed_at": now,
        },
    }
    if req.company_id:
        interaction_data["company_id"] = req.company_id
    if req.contact_id:
        interaction_data["contact_id"] = req.contact_id

    try:
        db.client.table("interactions").insert(interaction_data).execute()
    except Exception as e:
        logger.error(f"Failed to log mark-done interaction: {e}")
        raise HTTPException(status_code=500, detail="Failed to log action")

    # For LinkedIn connection — update contact linkedin_status
    if req.action_type == "linkedin_connection" and req.contact_id:
        try:
            db.client.table("contacts").update({
                "linkedin_status": "connection_sent",
                "updated_at": now,
            }).eq("id", req.contact_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update linkedin_status: {e}")

    # For LinkedIn DM — update contact linkedin_status
    if req.action_type == "linkedin_dm" and req.contact_id:
        try:
            db.client.table("contacts").update({
                "linkedin_status": "dm_sent",
                "updated_at": now,
            }).eq("id", req.contact_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update linkedin_status for DM: {e}")

    # For LinkedIn actions — create a contact_event in the thread
    if req.action_type in ("linkedin_connection", "linkedin_dm") and req.contact_id:
        try:
            # Find the most recent draft that was sent
            draft_rows = (
                db.client.table("outreach_drafts")
                .select("body, sequence_name")
                .eq("contact_id", req.contact_id)
                .eq("channel", "linkedin")
                .in_("sequence_name", [req.action_type, "linkedin_connection", "linkedin_connect", "linkedin_dm_opening", "linkedin_dm"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            ) or []
            draft_body = draft_rows[0]["body"] if draft_rows else None

            event_payload: dict = {
                "contact_id": req.contact_id,
                "event_type": "outreach_sent",
                "channel": "linkedin",
                "direction": "outbound",
                "body": draft_body,
                "created_by": "system",
                "created_at": now,
            }
            if req.company_id:
                event_payload["company_id"] = req.company_id
            db.client.table("contact_events").insert(event_payload).execute()
        except Exception as e:
            logger.warning(f"Failed to create contact_event for mark-done: {e}")

    # For LinkedIn actions — try to advance the engagement sequence
    if req.action_type in ("linkedin_connection", "linkedin_dm") and req.contact_id:
        try:
            seqs = (
                db.client.table("engagement_sequences")
                .select("id, current_step, total_steps, sequence_name")
                .eq("contact_id", req.contact_id)
                .eq("status", "active")
                .like("next_action_type", "%linkedin%")
                .limit(1)
                .execute()
                .data
            )
            if seqs:
                seq = seqs[0]
                next_action_at = (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat()
                new_step = seq["current_step"] + 1

                if new_step > seq["total_steps"]:
                    db.client.table("engagement_sequences").update({
                        "status": "completed",
                        "updated_at": now,
                    }).eq("id", seq["id"]).execute()
                else:
                    db.client.table("engagement_sequences").update({
                        "current_step": new_step,
                        "next_action_at": next_action_at,
                        "updated_at": now,
                    }).eq("id", seq["id"]).execute()
        except Exception as e:
            logger.warning(f"Failed to advance engagement sequence: {e}")

    # Handle connection_accepted — update status + auto-generate DM
    if req.action_type == "connection_accepted" and req.contact_id:
        try:
            db.client.table("contacts").update({
                "linkedin_status": "connection_accepted",
                "updated_at": now,
            }).eq("id", req.contact_id).execute()

            # Log the acceptance as an interaction
            db.insert_interaction({
                "company_id": req.company_id,
                "contact_id": req.contact_id,
                "type": "linkedin_connection",
                "channel": "linkedin",
                "subject": "Connection accepted",
                "source": "user",
                "metadata": {"status": "accepted"},
            })

            # Auto-generate DM for this contact (will appear in 2 days)
            try:
                from backend.app.agents.linkedin import LinkedInAgent
                agent = LinkedInAgent()
                agent.execute(
                    company_ids=[req.company_id] if req.company_id else None,
                    limit=1,
                    mode="dm_only",
                )
            except Exception as e:
                logger.warning(f"Failed to auto-generate DM on acceptance: {e}")

        except Exception as e:
            logger.warning(f"Failed to process connection_accepted: {e}")

    # Handle connection_ignored — mark and switch to email channel
    if req.action_type == "connection_ignored" and req.contact_id:
        try:
            db.client.table("contacts").update({
                "linkedin_status": "connection_ignored",
                "updated_at": now,
            }).eq("id", req.contact_id).execute()
        except Exception as e:
            logger.warning(f"Failed to process connection_ignored: {e}")

    return {
        "data": {"action_type": req.action_type, "marked_done_at": now},
        "message": "Action marked as done",
    }
