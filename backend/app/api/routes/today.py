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
# GET /api/today
# ---------------------------------------------------------------------------


@router.get("")
async def get_today_data():
    """Aggregate all daily action data into one response for the Daily Cockpit."""
    db = get_db()
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(hours=24)).isoformat()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # --- Hot signals: engaged companies + recent multi-opens ---
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

    return {
        "data": {
            "hot_signals": hot_rows,
            "pending_approvals": pending_drafts,
            "linkedin_queue": linkedin_rows,
            "pipeline_summary": pipeline_summary,
            "recent_interactions": recent_interactions,
            "progress": {
                "completed": done_count,
                "target": 20,
            },
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
            # Try inserting to suppression list table if it exists
            db.client.table("suppression_list").insert(suppress_data).execute()
        except Exception:
            # Table may not exist yet — log and continue
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
        # Table may not exist — non-fatal
        logger.debug("learning_outcomes table not found, skipping")

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

    # For LinkedIn actions — try to advance the engagement sequence
    if req.action_type in ("linkedin_connection", "linkedin_dm") and req.contact_id:
        try:
            # Find active sequence for this contact
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

    return {
        "data": {"action_type": req.action_type, "marked_done_at": now},
        "message": "Action marked as done",
    }
