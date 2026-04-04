"""Deals API — pipeline management and deal tracking."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_user, require_workspace_member
from backend.app.core.database import Database, get_db
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/deals", tags=["deals"])

VALID_STAGES = ["prospect", "qualified", "proposal", "negotiation", "won", "lost"]


# ============================================================================
# Models
# ============================================================================


class DealCreate(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    title: str
    amount: Optional[Decimal] = None
    currency: str = "USD"
    stage: str = Field(default="prospect")
    probability: int = Field(default=25, ge=0, le=100)
    expected_close_date: Optional[datetime] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class DealUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[Decimal] = None
    stage: Optional[str] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[datetime] = None
    close_date: Optional[datetime] = None
    reason_lost: Optional[str] = None
    notes: Optional[str] = None


class DealResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    company_id: int
    contact_id: Optional[int]
    title: str
    amount: Optional[Decimal]
    currency: str
    stage: str
    probability: int
    expected_close_date: Optional[datetime]
    close_date: Optional[datetime]
    source: Optional[str]
    reason_lost: Optional[str]
    notes: Optional[str]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class DealListResponse(BaseModel):
    total: int
    deals: list[DealResponse]
    pipeline_summary: Optional[dict] = None


class DealActivityCreate(BaseModel):
    activity_type: str
    description: Optional[str] = None


class DealActivityResponse(BaseModel):
    id: UUID
    deal_id: UUID
    activity_type: str
    description: Optional[str]
    activity_date: datetime
    created_by: UUID
    created_at: datetime


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_model=DealListResponse)
async def list_deals(
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
    stage: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    include_summary: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all deals in the current workspace with optional pipeline summary."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    query = db.client.table("deals").select("*").eq("workspace_id", workspace_id)

    if stage:
        if stage not in VALID_STAGES:
            raise HTTPException(status_code=400, detail=f"Invalid stage: {stage}")
        query = query.eq("stage", stage)

    if company_id:
        query = query.eq("company_id", company_id)

    result = query.order("expected_close_date", desc=False).range(offset, offset + limit - 1).execute()

    # Get total count
    count_query = db.client.table("deals").select("id", count="exact").eq("workspace_id", workspace_id)
    if stage:
        count_query = count_query.eq("stage", stage)
    if company_id:
        count_query = count_query.eq("company_id", company_id)
    total = count_query.execute().count or 0

    pipeline_summary = None
    if include_summary:
        pipeline_summary = await _get_pipeline_summary(db, workspace_id)

    return {
        "total": total,
        "deals": result.data or [],
        "pipeline_summary": pipeline_summary,
    }


@router.get("/{deal_id}", response_model=DealResponse)
async def get_deal(
    deal_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Get a specific deal."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    result = (
        db.client.table("deals")
        .select("*")
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    return result.data


@router.post("", response_model=DealResponse)
async def create_deal(
    deal: DealCreate,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Create a new deal."""
    if deal.stage not in VALID_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {deal.stage}")

    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    data = {
        "workspace_id": workspace_id,
        "company_id": deal.company_id,
        "contact_id": deal.contact_id,
        "title": deal.title,
        "amount": str(deal.amount) if deal.amount else None,
        "currency": deal.currency,
        "stage": deal.stage,
        "probability": deal.probability,
        "expected_close_date": deal.expected_close_date.isoformat() if deal.expected_close_date else None,
        "source": deal.source,
        "created_by": user["id"],
        "notes": deal.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.client.table("deals").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create deal")

    return result.data[0]


@router.patch("/{deal_id}", response_model=DealResponse)
async def update_deal(
    deal_id: UUID,
    update: DealUpdate,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Update a deal."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify deal belongs to workspace
    existing = (
        db.client.table("deals")
        .select("id")
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    data = update.dict(exclude_unset=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Convert datetime fields to ISO strings
    for field in ["expected_close_date", "close_date"]:
        if field in data and data[field] and isinstance(data[field], datetime):
            data[field] = data[field].isoformat()

    # Convert Decimal to string for JSON serialization
    if "amount" in data and data["amount"]:
        data["amount"] = str(data["amount"])

    # Validate stage
    if "stage" in data and data["stage"] not in VALID_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {data['stage']}")

    result = (
        db.client.table("deals")
        .update(data)
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to update deal")

    return result.data[0]


@router.post("/{deal_id}/mark-won", response_model=DealResponse)
async def mark_deal_won(
    deal_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Mark a deal as won."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    data = {
        "stage": "won",
        "probability": 100,
        "close_date": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = (
        db.client.table("deals")
        .update(data)
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    return result.data[0]


@router.post("/{deal_id}/mark-lost", response_model=DealResponse)
async def mark_deal_lost(
    deal_id: UUID,
    reason_lost: str,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Mark a deal as lost with a reason."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    data = {
        "stage": "lost",
        "probability": 0,
        "reason_lost": reason_lost,
        "close_date": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = (
        db.client.table("deals")
        .update(data)
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    return result.data[0]


@router.delete("/{deal_id}")
async def delete_deal(
    deal_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Delete a deal."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    result = (
        db.client.table("deals")
        .delete()
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    return {"status": "deleted"}


# ============================================================================
# Deal Activities
# ============================================================================


@router.post("/{deal_id}/activities", response_model=DealActivityResponse)
async def add_activity(
    deal_id: UUID,
    activity: DealActivityCreate,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Log an activity for a deal."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify deal belongs to workspace
    deal = (
        db.client.table("deals")
        .select("id")
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not deal.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    data = {
        "deal_id": str(deal_id),
        "activity_type": activity.activity_type,
        "description": activity.description,
        "activity_date": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.client.table("deal_activities").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to add activity")

    return result.data[0]


@router.get("/{deal_id}/activities")
async def get_activities(
    deal_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Get all activities for a deal."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify deal belongs to workspace
    deal = (
        db.client.table("deals")
        .select("id")
        .eq("id", str(deal_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not deal.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    result = (
        db.client.table("deal_activities")
        .select("*")
        .eq("deal_id", str(deal_id))
        .order("activity_date", desc=True)
        .execute()
    )

    return {"activities": result.data or []}


# ============================================================================
# Pipeline Summary
# ============================================================================


async def _get_pipeline_summary(db: Database, workspace_id: UUID) -> dict:
    """Get a summary of the deal pipeline by stage."""
    try:
        result = (
            db.client.table("deals")
            .select("stage, count(id)")
            .eq("workspace_id", workspace_id)
            .group_by("stage")
            .execute()
        )

        summary = {stage: 0 for stage in VALID_STAGES}
        if result.data:
            for row in result.data:
                if row["stage"] in summary:
                    summary[row["stage"]] = row["count"]

        return summary
    except Exception:
        return None
