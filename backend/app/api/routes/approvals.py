"""Approval routes for ProspectIQ API.

Manage outreach draft approvals and rejections.
Approved drafts log an interaction and update company status.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


class ApproveRequest(BaseModel):
    edited_body: Optional[str] = None


class RejectRequest(BaseModel):
    rejection_reason: str


class TestEmailRequest(BaseModel):
    test_email: str  # Your email address to receive the test


@router.get("/")
async def list_pending_drafts(limit: int = 50):
    """Get pending outreach drafts with company/contact info and quality scores."""
    db = get_db()
    drafts = db.get_pending_drafts(limit=limit)

    # Run quality validation on each draft
    from backend.app.core.draft_quality import validate_draft

    for draft in drafts:
        company = None
        research = None
        company_id = draft.get("company_id")
        if company_id:
            company = db.get_company(company_id)
            research = db.get_research(company_id)

        report = validate_draft(draft, company, research)
        draft["quality_score"] = report.score
        draft["quality_passed"] = report.passed
        draft["quality_issues"] = [
            {"severity": i.severity, "check": i.check_name, "message": i.message}
            for i in report.issues
        ]

    return {"data": drafts, "count": len(drafts)}


@router.post("/{draft_id}/approve")
async def approve_draft(draft_id: str, body: Optional[ApproveRequest] = None):
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


class EditRequest(BaseModel):
    edited_body: str


@router.patch("/{draft_id}/edit")
async def edit_draft(draft_id: str, body: EditRequest):
    """Save edits to a draft without approving it.

    The draft remains in the pending queue so it can be reviewed
    and approved as a separate step.
    """
    db = get_db()

    update_data = {"edited_body": body.edited_body}
    draft = db.update_outreach_draft(draft_id, update_data)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return {"data": draft, "message": "Draft updated"}


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


@router.post("/{draft_id}/test-send")
async def test_send_draft(draft_id: str, body: TestEmailRequest):
    """Send a draft to a test email address (your own inbox).

    Does NOT mark the draft as sent or change any status.
    Uses Resend to deliver the email so you can see exactly what
    the prospect would receive — subject, body, formatting.

    The email is sent from avi@digitillis.com (or your configured sender)
    to the test_email address you provide.
    """
    db = get_db()

    # Fetch the draft with company/contact info
    result = (
        db._filter_ws(
            db.client.table("outreach_drafts")
            .select("*, companies(name, tier, pqs_total), contacts(full_name, title, email)")
        )
        .eq("id", draft_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft = result.data[0]
    company = draft.get("companies") or {}
    contact = draft.get("contacts") or {}

    subject = draft.get("subject", "")
    email_body = draft.get("edited_body") or draft.get("body", "")

    # Build a test email with a clear [TEST] marker
    test_subject = f"[TEST] {subject}"
    test_body = (
        f"--- TEST EMAIL — This is how the prospect would see it ---\n"
        f"To: {contact.get('full_name', 'Unknown')} ({contact.get('email', 'N/A')})\n"
        f"Company: {company.get('name', 'Unknown')} (Tier {company.get('tier', '?')}, PQS {company.get('pqs_total', 0)})\n"
        f"Title: {contact.get('title', 'Unknown')}\n"
        f"-----------------------------------------------------------\n\n"
        f"{email_body}"
    )

    # Send via Resend
    try:
        from backend.app.core.config import get_settings
        settings = get_settings()

        if not settings.resend_api_key:
            raise HTTPException(
                status_code=400,
                detail="RESEND_API_KEY not configured. Set it in Railway Variables to enable test emails."
            )

        import resend
        resend.api_key = settings.resend_api_key

        send_result = resend.Emails.send({
            "from": "ProspectIQ Test <avi@digitillis.com>",
            "to": [body.test_email],
            "subject": test_subject,
            "text": test_body,
        })

        # Log the test send as an interaction
        db.insert_interaction({
            "company_id": draft["company_id"],
            "contact_id": draft.get("contact_id"),
            "type": "note",
            "channel": "email",
            "subject": f"Test email sent to {body.test_email}",
            "body": f"Draft {draft_id} sent as test to {body.test_email}",
            "source": "system",
            "metadata": {
                "draft_id": draft_id,
                "test_email": body.test_email,
                "resend_id": send_result.get("id") if isinstance(send_result, dict) else str(send_result),
            },
        })

        return {
            "data": {"draft_id": draft_id, "sent_to": body.test_email},
            "message": f"Test email sent to {body.test_email}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")
