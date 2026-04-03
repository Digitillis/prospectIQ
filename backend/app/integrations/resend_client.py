"""Resend email client for ProspectIQ.

Handles transactional emails ONLY — NOT cold outreach.
Used for internal notifications: hot-reply alerts, daily digests, system alerts.
"""

import logging
from datetime import datetime, timezone

import resend

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# Load from config — fallback to generic defaults if not set
def _get_sender_email() -> str:
    """Get primary sender email from config."""
    try:
        from backend.app.core.config import get_outreach_guidelines
        guidelines = get_outreach_guidelines()
        sender = guidelines.get("sender", {})
        email = sender.get("email")
        if email:
            return email
    except Exception:
        pass
    return "noreply@example.com"

FOUNDER_EMAIL = _get_sender_email()  # Primary contact email for alerts
DEFAULT_FROM_EMAIL = "notifications@example.com"  # Default transactional email


class ResendClient:
    """Resend transactional email client.

    This client is strictly for internal/transactional emails:
    - Hot reply alerts to the founder
    - Daily action digests
    - System notifications

    All cold outreach is handled by Instantly.ai.
    """

    def __init__(self):
        settings = get_settings()
        if not settings.resend_api_key:
            raise ValueError("RESEND_API_KEY must be set in .env")
        resend.api_key = settings.resend_api_key

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        html: str,
        from_email: str = DEFAULT_FROM_EMAIL,
    ) -> dict:
        """Send a single transactional email.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            html: Email body as HTML.
            from_email: Sender address (must be verified in Resend).

        Returns:
            Resend API response dict with 'id' of the sent email.
        """
        try:
            response = resend.Emails.send(
                {
                    "from": from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                }
            )
            logger.info(f"Email sent to {to}: subject='{subject}'")
            return response
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            raise

    # ------------------------------------------------------------------
    # Notification templates
    # ------------------------------------------------------------------

    def send_hot_reply_alert(
        self,
        prospect_name: str,
        reply_snippet: str,
    ) -> dict:
        """Notify the founder of a hot reply from a prospect.

        Args:
            prospect_name: Name of the prospect who replied.
            reply_snippet: First ~200 chars of the reply for quick context.

        Returns:
            Resend API response dict.
        """
        subject = f"Hot Reply from {prospect_name}"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #e74c3c;">Hot Reply Detected</h2>
            <p><strong>Prospect:</strong> {prospect_name}</p>
            <div style="background: #f8f9fa; border-left: 4px solid #e74c3c; padding: 12px 16px; margin: 16px 0;">
                <p style="margin: 0; color: #333; white-space: pre-wrap;">{reply_snippet}</p>
            </div>
            <p style="color: #666; font-size: 14px;">
                Check your Instantly dashboard for the full conversation and respond promptly.
            </p>
        </div>
        """

        logger.info(f"Sending hot reply alert for prospect: {prospect_name}")
        return self.send_email(
            to=FOUNDER_EMAIL,
            subject=subject,
            html=html,
        )

    def send_daily_action_digest(self, actions: list[dict]) -> dict:
        """Send a daily summary of actions and pipeline activity.

        Each action dict should contain:
            - type (str): Action type (e.g., 'reply', 'lead_added', 'campaign_sent').
            - description (str): Human-readable summary.
            - priority (str, optional): 'high', 'medium', 'low'.

        Args:
            actions: List of action dicts for the digest.

        Returns:
            Resend API response dict.
        """
        today = datetime.now(timezone.utc).strftime("%B %d, %Y")
        subject = f"ProspectIQ Daily Digest - {today}"

        if not actions:
            action_rows = """
            <tr>
                <td colspan="3" style="padding: 12px; text-align: center; color: #999;">
                    No actions today. Pipeline is quiet.
                </td>
            </tr>
            """
        else:
            action_rows = ""
            for action in actions:
                priority = action.get("priority", "low")
                priority_color = {
                    "high": "#e74c3c",
                    "medium": "#f39c12",
                    "low": "#27ae60",
                }.get(priority, "#27ae60")

                action_rows += f"""
                <tr>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #eee;">
                        <span style="background: {priority_color}; color: white; padding: 2px 8px;
                               border-radius: 3px; font-size: 12px;">{priority.upper()}</span>
                    </td>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #eee; font-weight: 600;">
                        {action.get("type", "action")}
                    </td>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #eee;">
                        {action.get("description", "")}
                    </td>
                </tr>
                """

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;">
            <h2 style="color: #2c3e50;">ProspectIQ Daily Digest</h2>
            <p style="color: #666;">{today} &middot; {len(actions)} action(s)</p>
            <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 8px 12px; text-align: left; width: 80px;">Priority</th>
                        <th style="padding: 8px 12px; text-align: left; width: 120px;">Type</th>
                        <th style="padding: 8px 12px; text-align: left;">Description</th>
                    </tr>
                </thead>
                <tbody>
                    {action_rows}
                </tbody>
            </table>
            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
            <p style="color: #999; font-size: 12px;">
                Sent by ProspectIQ &middot; AI-powered outreach intelligence
            </p>
        </div>
        """

        logger.info(f"Sending daily digest with {len(actions)} actions")
        return self.send_email(
            to=FOUNDER_EMAIL,
            subject=subject,
            html=html,
        )
