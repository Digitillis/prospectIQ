"""Gmail IMAP reply intake for ProspectIQ.

Polls avi@digitillis.io inbox via IMAP for replies to outreach emails.
Uses App Password auth — no OAuth flow required.

Setup:
  1. Enable IMAP in Gmail settings → See all settings → Forwarding and POP/IMAP
  2. Generate App Password: myaccount.google.com/apppasswords
     (requires 2FA to be enabled)
  3. Set in .env:
       GMAIL_USER=avi@digitillis.io
       GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

The intake:
  - Fetches UNSEEN emails in INBOX since last run
  - Matches to outreach_drafts by subject (Re: <original subject>) or sender domain
  - Classifies intent using keyword heuristics (escalates to Claude if ambiguous)
  - Inserts thread_messages + interactions
  - Updates campaign_threads.status
  - Pauses/expedites engagement_sequences based on intent
  - Marks emails as READ after processing
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Intent keyword heuristics — used before Claude escalation
_INTERESTED_KWS = [
    "interested", "let's connect", "let's talk", "tell me more", "sounds good",
    "open to", "would like to", "schedule", "availability", "free to chat",
    "demo", "learn more", "yes", "absolutely", "great timing",
]
_NOT_INTERESTED_KWS = [
    "not interested", "no thanks", "unsubscribe", "remove me", "stop",
    "please remove", "take me off", "don't contact", "do not contact",
    "not a fit", "no longer", "already have a solution",
]
_QUESTION_KWS = [
    "?", "how does", "what is", "can you", "do you", "tell me about",
    "more information", "more info", "curious about", "wondering",
]
_REFERRAL_KWS = [
    "reach out to", "contact my", "talk to", "speak with", "connect with",
    "cc:", "forwarding", "loop in",
]
_OOO_KWS = [
    "out of office", "auto-reply", "on vacation", "annual leave", "away until",
    "automatic reply",
]


def _decode_str(value: str) -> str:
    """Decode RFC2047-encoded email header string."""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _classify_intent(body: str, subject: str) -> str:
    """Fast keyword-based intent classification. Returns one of:
    interested | not_interested | question | referral | ooo | objection | unknown
    """
    text = (body + " " + subject).lower()

    if any(kw in text for kw in _OOO_KWS):
        return "ooo"
    if any(kw in text for kw in _NOT_INTERESTED_KWS):
        return "not_interested"
    if any(kw in text for kw in _REFERRAL_KWS):
        return "referral"
    if any(kw in text for kw in _INTERESTED_KWS):
        return "interested"
    if any(kw in text for kw in _QUESTION_KWS):
        return "question"
    return "unknown"


def _strip_quoted_text(body: str) -> str:
    """Remove standard email quoted reply blocks (lines starting with >)."""
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        # Common header lines in quoted blocks
        if re.match(r"^On .* wrote:$", stripped):
            break
        if re.match(r"^From:\s", stripped) or re.match(r"^Sent:\s", stripped):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _get_body(msg: email.message.Message) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            pass
    return body


class GmailImapClient:
    """IMAP client for reading replies from avi@digitillis.io."""

    def __init__(self, user: str, app_password: str):
        self.user = user
        self.app_password = app_password
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> None:
        self._conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        self._conn.login(self.user, self.app_password)

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    def fetch_unseen_replies(self) -> list[dict]:
        """Fetch all UNSEEN messages in INBOX that look like replies (subject starts with Re:).

        Returns list of dicts with keys:
          uid, from_email, from_name, subject, body, received_at, message_id, in_reply_to
        """
        if not self._conn:
            raise RuntimeError("Not connected")

        self._conn.select("INBOX")
        # Search for unseen emails — we only mark as READ after successful processing
        _, data = self._conn.search(None, "UNSEEN")
        uids = data[0].split() if data[0] else []

        results = []
        for uid in uids:
            _, msg_data = self._conn.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = _decode_str(msg.get("Subject", ""))
            # Only process replies (subject starts with Re:)
            if not re.match(r"^re:", subject.strip(), re.IGNORECASE):
                continue

            from_raw = _decode_str(msg.get("From", ""))
            # Parse "Name <email>" format
            m = re.match(r"^(.*?)\s*<(.+?)>$", from_raw.strip())
            if m:
                from_name = m.group(1).strip().strip('"')
                from_email = m.group(2).strip().lower()
            else:
                from_name = ""
                from_email = from_raw.strip().lower()

            date_str = msg.get("Date", "")
            try:
                from email.utils import parsedate_to_datetime
                received_at = parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
            except Exception:
                received_at = datetime.now(timezone.utc).isoformat()

            body = _get_body(msg)
            reply_text = _strip_quoted_text(body)

            results.append({
                "uid": uid.decode(),
                "from_email": from_email,
                "from_name": from_name,
                "subject": subject,
                "body": reply_text or body[:2000],
                "received_at": received_at,
                "message_id": msg.get("Message-ID", ""),
                "in_reply_to": msg.get("In-Reply-To", ""),
            })

        return results

    def mark_as_read(self, uid: str) -> None:
        """Mark a message as read by UID."""
        if self._conn:
            try:
                self._conn.store(uid, "+FLAGS", "\\Seen")
            except Exception as e:
                logger.warning(f"Failed to mark UID {uid} as read: {e}")
