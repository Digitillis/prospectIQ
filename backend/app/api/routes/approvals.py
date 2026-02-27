"""Approval routes for ProspectIQ API.

Manage outreach draft approvals and rejections.
Approved drafts log an interaction and update company status.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def get_db() -> Database:
    return Database()


class ApproveRequest(BaseModel):
    edited_body: Optional[str] = None


class RejectRequest(BaseModel):
    rejection_reason: str


@router.get("/")
async def list_pending_drafts(limit: int = 50):
    """Get pending outreach drafts with company/contact info."""
    db = get_db()
    drafts = db.get_pending_drafts(limit=limit)
    return {"data": drafts, "count": len(drafts)}


@router.post("/{draft_id}/approve")
async def approve_draft(draft_id: str, body: ApproveRequest | None = None):
    """Approve an outreach draft.

    Optionally provide an edited body. Logs an email_sent interaction
    and updates the company status to 'contacted'.
    """
    db = get_db()

    update_data: dict = {
        "approval_status": "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    if body and body.edited_body:
        update_data["edited_body"] = body.edited_body
        update_data["approval_status"] = "edited"

    draft = db.update_outreach_draft(draft_id, update_data)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Log an interaction for the sent email (use edited body if available)
    sent_body = draft.get("edited_body") or draft.get("body", "")
    db.insert_interaction({
        "company_id": draft["company_id"],
        "contact_id": draft.get("contact_id"),
        "type": "email_sent",
        "channel": "email",
        "subject": draft.get("subject", ""),
        "body": sent_body,
        "source": "approval",
        "metadata": {"draft_id": draft_id},
    })

    # Update company status to contacted
    db.update_company(draft["company_id"], {"status": "contacted"})

    return {"data": draft, "message": "Draft approved"}


@router.post("/{draft_id}/reject")
async def reject_draft(draft_id: str, body: RejectRequest):
    """Reject an outreach draft with a reason."""
    db = get_db()

    update_data = {
        "approval_status": "rejected",
        "rejection_reason": body.rejection_reason,
    }

    draft = db.update_outreach_draft(draft_id, update_data)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return {"data": draft, "message": "Draft rejected"}
