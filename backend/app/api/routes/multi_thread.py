# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: Avanish Mehrotra & ProspectIQ Technical Team
"""Multi-thread account campaign API routes.

Endpoints:
    POST /api/multi-thread/campaigns          — create account campaign with contact list
    GET  /api/multi-thread/campaigns          — list account campaigns for workspace
    GET  /api/multi-thread/campaigns/{id}     — campaign detail with all threads + status
    POST /api/multi-thread/campaigns/{id}/drafts   — generate coordinated drafts
    PUT  /api/multi-thread/campaigns/{id}/pause    — pause all threads
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id
from backend.app.core.thread_coordinator import ThreadCoordinator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/multi-thread", tags=["multi-thread"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


def get_coordinator() -> ThreadCoordinator:
    return ThreadCoordinator(db=get_db())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    company_id: str
    contact_ids: list[str]
    strategy: str = "parallel"  # parallel | sequential | waterfall
    campaign_name: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /api/multi-thread/campaigns
# ---------------------------------------------------------------------------

@router.post("/campaigns", status_code=201)
async def create_campaign(body: CreateCampaignRequest):
    """Create a multi-thread account campaign with an initial contact list.

    Also runs role assignment so threads are labelled immediately.
    """
    if not body.contact_ids:
        raise HTTPException(status_code=422, detail="At least one contact_id is required")

    valid_strategies = {"parallel", "sequential", "waterfall"}
    if body.strategy not in valid_strategies:
        raise HTTPException(
            status_code=422,
            detail=f"strategy must be one of: {', '.join(sorted(valid_strategies))}",
        )

    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="Workspace context not found")

    coordinator = get_coordinator()
    try:
        campaign = await coordinator.create_account_campaign(
            company_id=body.company_id,
            contact_ids=body.contact_ids,
            strategy=body.strategy,
            workspace_id=workspace_id,
            campaign_name=body.campaign_name or "",
        )
    except Exception as exc:
        logger.error(f"create_account_campaign failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    # Assign roles immediately
    try:
        roles = await coordinator.assign_roles(campaign.id, workspace_id)
    except Exception as exc:
        logger.warning(f"Role assignment failed: {exc}")
        roles = []

    return {
        "data": {
            "id": campaign.id,
            "workspace_id": campaign.workspace_id,
            "company_id": campaign.company_id,
            "campaign_name": campaign.campaign_name,
            "strategy": campaign.strategy,
            "status": campaign.status,
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
        },
        "threads_created": len(body.contact_ids),
        "roles": [
            {
                "thread_id": r.thread_id,
                "contact_id": r.contact_id,
                "contact_name": r.contact_name,
                "contact_title": r.contact_title,
                "role_label": r.role_label,
                "messaging_angle": r.messaging_angle,
            }
            for r in roles
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/multi-thread/campaigns
# ---------------------------------------------------------------------------

@router.get("/campaigns")
async def list_campaigns(
    status: Optional[str] = Query(None, description="Filter: active|paused|completed|all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List account campaigns for the current workspace, newest first."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="Workspace context not found")

    db = get_db()
    try:
        q = (
            db.client.table("account_campaigns")
            .select(
                "*, "
                "companies(id, name, domain), "
                "account_campaign_threads(id, status, role_label, contact_id, contacts(full_name, title))"
            )
            .eq("workspace_id", workspace_id)
        )
        if status and status != "all":
            q = q.eq("status", status)

        result = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        campaigns = result.data or []
    except Exception as exc:
        logger.error(f"list campaigns failed: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))

    # Annotate thread count and last_activity
    for c in campaigns:
        threads = c.get("account_campaign_threads") or []
        c["thread_count"] = len(threads)
        touches = [
            t.get("last_touch_at") for t in threads if t.get("last_touch_at")
        ]
        c["last_activity_at"] = max(touches) if touches else c.get("created_at")

    return {"data": campaigns, "count": len(campaigns)}


# ---------------------------------------------------------------------------
# GET /api/multi-thread/campaigns/{id}
# ---------------------------------------------------------------------------

@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Return campaign detail including all threads and suppression status."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="Workspace context not found")

    coordinator = get_coordinator()
    try:
        status_obj = await coordinator.get_account_campaign_status(
            account_campaign_id=campaign_id,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"get_campaign_status failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "data": {
            "campaign": status_obj.account_campaign,
            "threads": status_obj.threads,
            "drafts_generated": status_obj.drafts_generated,
            "suppressed_count": status_obj.suppressed_count,
            "next_available_at": status_obj.next_available_at,
        }
    }


# ---------------------------------------------------------------------------
# POST /api/multi-thread/campaigns/{id}/drafts
# ---------------------------------------------------------------------------

@router.post("/campaigns/{campaign_id}/drafts")
async def generate_drafts(campaign_id: str):
    """Generate coordinated drafts for all active threads in a campaign.

    Drafts are role-aware and include sibling-thread awareness notes where
    appropriate. Suppressed threads are flagged but not sent to the LLM.
    """
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="Workspace context not found")

    coordinator = get_coordinator()
    try:
        drafts = await coordinator.generate_coordinated_drafts(
            account_campaign_id=campaign_id,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"generate_coordinated_drafts failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    suppressed = [d for d in drafts if d.suppressed]
    active = [d for d in drafts if not d.suppressed]

    return {
        "data": [
            {
                "thread_id": d.thread_id,
                "contact_id": d.contact_id,
                "contact_name": d.contact_name,
                "contact_title": d.contact_title,
                "role_label": d.role_label,
                "messaging_angle": d.messaging_angle,
                "subject": d.subject,
                "body": d.body,
                "awareness_note": d.awareness_note,
                "suppressed": d.suppressed,
                "suppress_reason": d.suppress_reason,
            }
            for d in drafts
        ],
        "total": len(drafts),
        "generated": len(active),
        "suppressed": len(suppressed),
    }


# ---------------------------------------------------------------------------
# PUT /api/multi-thread/campaigns/{id}/pause
# ---------------------------------------------------------------------------

@router.put("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    """Pause all active threads in a campaign."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="Workspace context not found")

    db = get_db()
    try:
        # Verify campaign exists and belongs to workspace
        check = (
            db.client.table("account_campaigns")
            .select("id, status")
            .eq("id", campaign_id)
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Pause campaign
        db.client.table("account_campaigns").update({"status": "paused"}).eq(
            "id", campaign_id
        ).execute()

        # Pause all active threads
        result = (
            db.client.table("account_campaign_threads")
            .update({"status": "paused"})
            .eq("account_campaign_id", campaign_id)
            .eq("status", "active")
            .execute()
        )
        paused_count = len(result.data) if result.data else 0
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"pause_campaign failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "message": f"Campaign paused. {paused_count} thread(s) paused.",
        "campaign_id": campaign_id,
        "threads_paused": paused_count,
    }
