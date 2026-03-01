"""Webhook routes for ProspectIQ API.

Receives events from Instantly.ai (email_sent, email_opened,
email_clicked, reply_received, email_bounced) and delegates
processing to the EngagementAgent.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/instantly")
async def instantly_webhook(
    request: Request,
    secret: Optional[str] = Query(default=None),
):
    """Receive webhook events from Instantly.ai.

    Validates via URL query param ?secret=... (baked into the webhook URL
    configured in Instantly dashboard). Delegates all processing to
    EngagementAgent.process_webhook_event which handles:
    - Interaction logging
    - PQS engagement score updates
    - Status transitions (bounced, engaged)
    - Reply classification (via ReplyAgent)
    """
    settings = get_settings()

    # Validate webhook secret passed as query param
    if settings.webhook_secret and secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload: dict[str, Any] = await request.json()
    event_type = payload.get("event_type", "")

    if not event_type:
        return {"status": "ignored", "reason": "no event_type"}

    try:
        from backend.app.agents.engagement import EngagementAgent

        result = EngagementAgent.process_webhook_event(event_type, payload)

        # If it was a reply, also trigger classification and notify Slack
        if event_type == "reply_received" and result.get("status") == "processed":
            try:
                from backend.app.agents.reply import ReplyAgent
                from backend.app.core.database import Database

                db = Database()
                drafts = (
                    db.client.table("outreach_drafts")
                    .select("id")
                    .eq("company_id", result["company_id"])
                    .eq("contact_id", result["contact_id"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                )
                outreach_draft_id = drafts[0]["id"] if drafts else ""

                reply_agent = ReplyAgent()
                reply_result = reply_agent.execute(reply_data={
                    "company_id": result["company_id"],
                    "contact_id": result["contact_id"],
                    "subject": payload.get("subject", ""),
                    "body": payload.get("body", ""),
                    "outreach_draft_id": outreach_draft_id,
                })

                # Notify Slack for positive or question replies
                try:
                    from backend.app.utils.notifications import notify_slack
                    company = db.get_company(result["company_id"])
                    company_name = company.get("name", "Unknown") if company else "Unknown"

                    if reply_result and reply_result.details:
                        detail = reply_result.details[0] if reply_result.details else {}
                        classification = detail.get("status", "unknown")
                        if classification in ("positive", "question"):
                            notify_slack(
                                f"*Hot reply from {company_name}* — "
                                f"classified as *{classification}*. "
                                f"Response draft waiting in Approvals.",
                                emoji=":fire:",
                            )
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"Reply classification failed: {e}")

        return result

    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)[:200]}
