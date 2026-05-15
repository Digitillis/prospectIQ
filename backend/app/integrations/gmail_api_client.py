"""Gmail API client using OAuth2 refresh token.

Replaces IMAP UNSEEN polling. Searches all messages in a lookback window
(read or unread) and deduplicates on Gmail message-id, so replies read
manually in Gmail are captured on the next cron tick.

Required env vars (set in Railway):
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN
  GMAIL_ACCOUNT  (e.g. avi@digitillis.io)
"""
from __future__ import annotations

import base64
import email as email_lib
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_LOOKBACK_HOURS = 48


def _build_service():
    """Return an authenticated Gmail API service or None if creds are missing."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning("gmail_api: google-api-python-client not installed")
        return None

    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "")

    if not (client_id and client_secret and refresh_token):
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    try:
        creds.refresh(Request())
    except Exception as e:
        logger.error("gmail_api: token refresh failed: %s", e)
        return None

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    parts = payload.get("parts") or []
    if not parts:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        return ""

    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in parts:
        if part.get("mimeType", "").startswith("multipart/"):
            result = _decode_body(part)
            if result:
                return result

    return ""


def fetch_recent_replies(gmail_account: str) -> list[dict]:
    """Return inbound replies from the last LOOKBACK_HOURS hours.

    Each item: {from_email, subject, body, received_at (ISO), message_id (Gmail ID),
                raw_message_id (RFC 2822 Message-ID header for dedup)}
    """
    service = _build_service()
    if not service:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_HOURS)
    # Gmail search query — all mail in inbox after cutoff, not sent by us
    query = f"in:inbox after:{cutoff.strftime('%Y/%m/%d')} -from:{gmail_account}"

    try:
        list_result = service.users().messages().list(
            userId="me", q=query, maxResults=100
        ).execute()
    except Exception as e:
        logger.error("gmail_api: messages.list failed: %s", e)
        return []

    messages = list_result.get("messages", [])
    if not messages:
        return []

    replies = []
    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="full"
            ).execute()
        except Exception as e:
            logger.warning("gmail_api: message.get failed for %s: %s", msg_ref["id"], e)
            continue

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "")
        from_raw = headers.get("from", "")
        raw_message_id = headers.get("message-id", "")
        date_str = headers.get("date", "")

        # Extract email address from "Name <email>" format
        m = re.search(r"<([^>]+)>", from_raw)
        from_email = m.group(1).strip().lower() if m else from_raw.strip().lower()

        # Skip if this looks like a system/bounce/notification email
        if any(skip in from_email for skip in ["noreply", "no-reply", "mailer-daemon", "postmaster"]):
            continue

        # Parse received timestamp
        try:
            internal_date_ms = int(msg.get("internalDate", 0))
            received_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc).isoformat()
        except Exception:
            received_at = datetime.now(timezone.utc).isoformat()

        body = _decode_body(msg.get("payload", {}))

        replies.append({
            "from_email": from_email,
            "subject": subject,
            "body": body,
            "received_at": received_at,
            "message_id": msg_ref["id"],
            "raw_message_id": raw_message_id,
        })

    logger.info("gmail_api: fetched %d inbound messages for %s (last %dh)",
                len(replies), gmail_account, _LOOKBACK_HOURS)
    return replies
