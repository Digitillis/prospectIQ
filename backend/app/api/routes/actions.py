"""Actions routes for ProspectIQ API.

Provides the LinkedIn manual task queue and hot-reply surfaces
that feed the Daily Actions dashboard page.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from backend.app.core.config import get_sequences_config
from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


@router.get("/linkedin-tasks")
async def get_linkedin_tasks():
    """Return active engagement sequences with a LinkedIn action due now or overdue."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    rows = (
        db._filter_ws(
            db.client.table("engagement_sequences")
            .select(
                "*, "
                "companies(name, domain, tier, linkedin_url, pqs_total), "
                "contacts(full_name, title, linkedin_url)"
            )
        )
        .eq("status", "active")
        .lte("next_action_at", now)
        .like("next_action_type", "%linkedin%")
        .order("next_action_at")
        .limit(50)
        .execute()
        .data
    )

    return {"data": rows, "count": len(rows)}


@router.post("/linkedin-tasks/{sequence_id}/complete")
async def complete_linkedin_task(sequence_id: str):
    """Mark a LinkedIn task as done and advance the sequence to the next step."""
    db = get_db()

    seq_result = (
        db._filter_ws(db.client.table("engagement_sequences").select("*"))
        .eq("id", sequence_id)
        .execute()
    )
    if not seq_result.data:
        raise HTTPException(status_code=404, detail="Sequence not found")

    seq = seq_result.data[0]
    now = datetime.now(timezone.utc)

    # Determine what interaction type to log
    action_type = seq.get("next_action_type", "send_linkedin")
    interaction_type = (
        "linkedin_connection"
        if "connection" in action_type or seq.get("current_step", 1) <= 2
        else "linkedin_message"
    )

    # Log completed interaction
    db.insert_interaction({
        "company_id": seq["company_id"],
        "contact_id": seq["contact_id"],
        "type": interaction_type,
        "channel": "linkedin",
        "subject": f"LinkedIn touch — Step {seq['current_step'] + 1} completed",
        "body": "Manual LinkedIn action marked done via dashboard",
        "source": "manual",
        "metadata": {
            "sequence_name": seq["sequence_name"],
            "sequence_step": seq["current_step"] + 1,
        },
    })

    # Advance to next step
    next_step = seq["current_step"] + 1
    seq_config = get_sequences_config()
    sequence_def = seq_config["sequences"].get(seq["sequence_name"], {})

    further_step = next_step + 1
    next_action_at = None
    next_action_type = None

    if further_step <= seq["total_steps"]:
        for step in sequence_def.get("steps", []):
            if step["step"] == further_step:
                delay = step.get("delay_days", 3)
                next_action_at = (now + timedelta(days=delay)).isoformat()
                next_action_type = f"send_{step['channel']}"
                break

    db.update_engagement_sequence(sequence_id, {
        "current_step": next_step,
        "next_action_at": next_action_at,
        "next_action_type": next_action_type,
        "status": "active" if further_step <= seq["total_steps"] else "completed",
    })

    return {
        "data": {
            "sequence_id": sequence_id,
            "completed_step": next_step,
            "status": "advanced" if next_action_at else "completed",
        }
    }


@router.get("/hot-replies")
async def get_hot_replies():
    """Return pending response drafts for positive/question replies (need urgent attention)."""
    db = get_db()

    drafts = (
        db._filter_ws(
            db.client.table("outreach_drafts")
            .select(
                "*, "
                "companies(name, tier, pqs_total, status), "
                "contacts(full_name, title, email)"
            )
        )
        .eq("approval_status", "pending")
        .eq("sequence_name", "reply_response")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
    )

    return {"data": drafts, "count": len(drafts)}
