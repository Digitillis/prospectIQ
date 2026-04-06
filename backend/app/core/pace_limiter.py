"""Daily outreach pace limiter.

Enforces a per-campaign daily send cap independently of Instantly settings.
Acts as a safety net: if Instantly's limit is accidentally changed, ProspectIQ
still won't over-send.

Usage:
    from backend.app.core.pace_limiter import PaceLimiter
    limiter = PaceLimiter("tier0-mfg-pdm-roi", daily_limit=10)
    if limiter.can_send(contact_id):
        limiter.record_send(contact_id, company_id)
    else:
        print("Daily limit reached")
"""

from __future__ import annotations

import logging
from datetime import date

from rich.console import Console

from backend.app.core.database import Database
from backend.app.core.dnc_registry import DNCRegistry

console = Console()
logger = logging.getLogger(__name__)

def _get_dnc(workspace_id: str | None = None) -> DNCRegistry:
    return DNCRegistry(workspace_id=workspace_id)

# Default daily send limits per campaign type
CAMPAIGN_DEFAULTS: dict[str, int] = {
    "tier0-mfg-pdm-roi": 25,
    "tier0-fb-fsma": 25,
    "default": 25,
}


class PaceLimiter:
    """Enforces daily send caps per campaign."""

    def __init__(self, campaign_name: str, daily_limit: int | None = None, workspace_id: str | None = None):
        self.campaign_name = campaign_name
        self.daily_limit = daily_limit or CAMPAIGN_DEFAULTS.get(campaign_name, CAMPAIGN_DEFAULTS["default"])
        self.db = Database(workspace_id=workspace_id)
        self._today_count: int | None = None  # cached for this limiter instance

    @property
    def sends_today(self) -> int:
        """Current send count for today (cached after first call)."""
        if self._today_count is None:
            self._today_count = self.db.count_sends_today(self.campaign_name)
        return self._today_count

    @property
    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.sends_today)

    @property
    def is_limit_reached(self) -> bool:
        return self.sends_today >= self.daily_limit

    def can_send(self, contact_id: str, email: str | None = None) -> bool:
        """Return True if this contact can be sent to today.

        Checks:
        1. Daily campaign limit not reached
        2. This specific contact has not already been sent today
        3. Contact email/domain is not on the DNC list
        """
        if self.is_limit_reached:
            logger.info(
                f"[pace] Daily limit reached for '{self.campaign_name}' "
                f"({self.sends_today}/{self.daily_limit})"
            )
            return False

        if self.db.is_contact_sent_today(contact_id):
            logger.info(f"[pace] Contact {contact_id[:8]}... already sent today")
            return False

        if email:
            blocked, reason = _get_dnc(self.db.workspace_id).is_blocked(email=email)
            if blocked:
                logger.info(f"[pace] Contact {contact_id[:8]}... {reason}")
                return False

        return True

    def record_send(
        self,
        contact_id: str,
        company_id: str | None = None,
        channel: str = "email",
    ) -> bool:
        """Record a send in the pace log.

        Returns True if recorded successfully, False if limit was already reached.
        """
        if not self.can_send(contact_id):
            self.db.log_outreach_send({
                "send_date": date.today().isoformat(),
                "campaign_name": self.campaign_name,
                "contact_id": contact_id,
                "company_id": company_id,
                "channel": channel,
                "status": "blocked",
            })
            return False

        self.db.log_outreach_send({
            "send_date": date.today().isoformat(),
            "campaign_name": self.campaign_name,
            "contact_id": contact_id,
            "company_id": company_id,
            "channel": channel,
            "status": "sent",
        })
        self._today_count = (self._today_count or 0) + 1
        return True

    def status_line(self) -> str:
        """One-line status string for logging/display."""
        return (
            f"Campaign '{self.campaign_name}': "
            f"{self.sends_today}/{self.daily_limit} sent today, "
            f"{self.remaining_today} remaining"
        )


def check_all_campaigns(workspace_id: str | None = None) -> dict[str, dict]:
    """Return today's send count for all known campaigns."""
    db = Database(workspace_id=workspace_id)
    summary = {}
    for campaign, limit in CAMPAIGN_DEFAULTS.items():
        if campaign == "default":
            continue
        count = db.count_sends_today(campaign)
        summary[campaign] = {
            "sends_today": count,
            "daily_limit": limit,
            "remaining": max(0, limit - count),
            "limit_reached": count >= limit,
        }
    return summary
