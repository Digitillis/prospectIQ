"""Meetings API — scheduling, confirmation, and calendar integration."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_user, require_workspace_member
from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/meetings", tags=["meetings"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ============================================================================
# Models
# ============================================================================


class MeetingCreate(BaseModel):
    company_id: int
    contact_id: int
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=15, le=240)
    meeting_type: str = Field(default="discovery")
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    organizer_email: Optional[str] = None
    notes: Optional[str] = None


class MeetingUpdate(BaseModel):
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class MeetingResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    company_id: int
    contact_id: int
    scheduled_at: datetime
    duration_minutes: int
    status: str
    meeting_type: str
    title: Optional[str]
    description: Optional[str]
    location: Optional[str]
    organizer_email: Optional[str]
    created_by: UUID
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class MeetingListResponse(BaseModel):
    total: int
    meetings: list[MeetingResponse]


class AttendeeResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    contact_email: str
    contact_name: Optional[str]
    response_status: str
    attended: Optional[bool]
    created_at: datetime


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_model=MeetingListResponse)
async def list_meetings(
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
    status: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all meetings in the current workspace."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    query = db.client.table("meetings").select("*").eq("workspace_id", workspace_id)

    if status:
        query = query.eq("status", status)
    if company_id:
        query = query.eq("company_id", company_id)

    result = query.order("scheduled_at", desc=False).range(offset, offset + limit - 1).execute()

    total_result = db.client.table("meetings").select("id", count="exact").eq("workspace_id", workspace_id)
    if status:
        total_result = total_result.eq("status", status)
    if company_id:
        total_result = total_result.eq("company_id", company_id)
    total = total_result.execute().count or 0

    return {"total": total, "meetings": result.data or []}


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Get a specific meeting."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    result = (
        db.client.table("meetings")
        .select("*")
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return result.data


@router.post("", response_model=MeetingResponse)
async def create_meeting(
    meeting: MeetingCreate,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Schedule a new meeting."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    data = {
        "workspace_id": workspace_id,
        "company_id": meeting.company_id,
        "contact_id": meeting.contact_id,
        "scheduled_at": meeting.scheduled_at.isoformat(),
        "duration_minutes": meeting.duration_minutes,
        "meeting_type": meeting.meeting_type,
        "title": meeting.title,
        "description": meeting.description,
        "location": meeting.location,
        "organizer_email": meeting.organizer_email,
        "created_by": user["id"],
        "notes": meeting.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.client.table("meetings").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create meeting")

    return result.data[0]


@router.patch("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    meeting_id: UUID,
    update: MeetingUpdate,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Update a meeting."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify meeting belongs to workspace
    existing = (
        db.client.table("meetings")
        .select("id")
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    data = update.dict(exclude_unset=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if "scheduled_at" in data and isinstance(data["scheduled_at"], datetime):
        data["scheduled_at"] = data["scheduled_at"].isoformat()

    result = (
        db.client.table("meetings")
        .update(data)
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to update meeting")

    return result.data[0]


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Cancel a meeting."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    result = (
        db.client.table("meetings")
        .delete()
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return {"status": "deleted"}


# ============================================================================
# Meeting Confirmation & Attendees
# ============================================================================


@router.post("/{meeting_id}/attendees", response_model=AttendeeResponse)
async def add_attendee(
    meeting_id: UUID,
    contact_email: str,
    contact_name: Optional[str] = None,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Add an attendee to a meeting."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify meeting belongs to workspace
    meeting = (
        db.client.table("meetings")
        .select("id")
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not meeting.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    data = {
        "meeting_id": str(meeting_id),
        "contact_email": contact_email,
        "contact_name": contact_name,
        "response_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.client.table("meeting_attendees").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to add attendee")

    return result.data[0]


@router.get("/{meeting_id}/attendees")
async def get_attendees(
    meeting_id: UUID,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Get attendees for a meeting."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify meeting belongs to workspace
    meeting = (
        db.client.table("meetings")
        .select("id")
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not meeting.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    result = (
        db.client.table("meeting_attendees")
        .select("*")
        .eq("meeting_id", str(meeting_id))
        .execute()
    )

    return {"attendees": result.data or []}


@router.patch("/{meeting_id}/attendees/{attendee_id}")
async def update_attendee_response(
    meeting_id: UUID,
    attendee_id: UUID,
    response_status: str,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Update an attendee's response status (accepted/declined/tentative)."""
    if response_status not in ["accepted", "declined", "tentative"]:
        raise HTTPException(status_code=400, detail="Invalid response status")

    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify meeting belongs to workspace
    meeting = (
        db.client.table("meetings")
        .select("id")
        .eq("id", str(meeting_id))
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not meeting.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    result = (
        db.client.table("meeting_attendees")
        .update({"response_status": response_status, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", str(attendee_id))
        .eq("meeting_id", str(meeting_id))
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Attendee not found")

    return result.data[0]
