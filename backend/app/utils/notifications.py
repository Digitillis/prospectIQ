"""Slack notification utility for ProspectIQ.

Sends messages to a Slack webhook URL configured via SLACK_WEBHOOK_URL env var.
All functions are fire-and-forget — failures are logged but never raised.
"""

from __future__ import annotations

import logging

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


def notify_slack(text: str, emoji: str = ":robot_face:") -> bool:
    """Send a Slack notification via webhook.

    Args:
        text: Message text (supports Slack mrkdwn formatting).
        emoji: Emoji prefix for the message.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    settings = get_settings()
    webhook_url = settings.slack_webhook_url

    if not webhook_url:
        return False  # Silently skip — Slack not configured

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                webhook_url,
                json={"text": f"{emoji} {text}"},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.warning(f"Slack notification failed: {e}")
        return False
