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
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header
from typing import Optional

# IMAP date format required by RFC 3501 SEARCH SINCE criterion.
_IMAP_DATE_FMT = "%d-%b-%Y"

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Intent keyword heuristics — used before Claude escalation
_INTERESTED_KWS = [
    "interested",
    "let's connect",
    "let's talk",
    "tell me more",
    "sounds good",
    "open to",
    "would like to",
    "schedule",
    "availability",
    "free to chat",
    "demo",
    "learn more",
    "yes",
    "absolutely",
    "great timing",
]
_NOT_INTERESTED_KWS = [
    "not interested",
    "no thanks",
    "unsubscribe",
    "remove me",
    "stop",
    "please remove",
    "take me off",
    "don't contact",
    "do not contact",
    "not a fit",
    "no longer",
    "already have a solution",
]
_QUESTION_KWS = [
    "?",
    "how does",
    "what is",
    "can you",
    "do you",
    "tell me about",
    "more information",
    "more info",
    "curious about",
    "wondering",
]
_REFERRAL_KWS = [
    "reach out to",
    "contact my",
    "talk to",
    "speak with",
    "connect with",
    "cc:",
    "forwarding",
    "loop in",
]
_OOO_KWS = [
    "out of office",
    "auto-reply",
    "on vacation",
    "annual leave",
    "away until",
    "automatic reply",
]
_DEPARTED_KWS = [
    "retired",
    "no longer with",
    "no longer works",
    "no longer employed",
    "has left",
    "left the company",
    "left our company",
    "is no longer",
    "longer part of",
    "departed",
    "i've retired",
    "i have retired",
    "no longer have access to this email",
    "will not respond",
]


_OOO_RETURN_PATTERNS = [
    # "back on June 16" / "returning June 16, 2026" / "available on 6/16"
    r"(?:back|return(?:ing)?|available again?|in the office)\s+(?:on\s+)?([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4})",
    r"(?:back|return(?:ing)?|available again?|in the office)\s+(?:on\s+)?(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)",
    # "out until June 15" / "away until 2026-06-15"
    r"(?:out|away|off|leave)\s+until\s+([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4})",
    r"(?:out|away|off|leave)\s+until\s+(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)",
    r"(?:out|away|off|leave)\s+until\s+(\d{4}-\d{2}-\d{2})",
    # "return date: June 16"
    r"return\s+date[:\s]+([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4})",
]


def _parse_ooo_return_date(body: str) -> date | None:
    """Extract the return date from an OOO reply body.

    Returns a date in the future (within 90 days), or None if not parseable.
    """
    try:
        from dateutil import parser as du_parser
    except ImportError:
        return None

    today = datetime.now(timezone.utc).date()
    text = body[:2000]  # Only scan the first 2 KB — return date is always near the top

    for pattern in _OOO_RETURN_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw = m.group(1).strip().rstrip(",")
            # Append current year if missing (e.g. "June 16" with no year)
            if not re.search(r"\d{4}", raw):
                raw = f"{raw} {today.year}"
            try:
                parsed = du_parser.parse(raw, fuzzy=True, dayfirst=False)
                candidate = parsed.date()
                # Accept only future dates within 90 days
                if today < candidate <= today + timedelta(days=90):
                    return candidate
                # If year was appended and date has passed, try next year
                if candidate < today and not re.search(r"\d{4}", m.group(1)):
                    candidate = candidate.replace(year=today.year + 1)
                    if today < candidate <= today + timedelta(days=90):
                        return candidate
            except Exception:
                continue
    return None


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
    interested | not_interested | question | referral | ooo | departed | objection | unknown
    """
    text = (body + " " + subject).lower()

    if any(kw in text for kw in _DEPARTED_KWS):
        return "departed"
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

    def fetch_since_replies(self, since_dt: datetime) -> list[dict]:
        """Fetch all messages in INBOX received on or after *since_dt* that look like
        replies (subject starts with Re:), regardless of SEEN/UNSEEN state.

        Using SINCE instead of UNSEEN means replies that the founder reads before the
        15-minute cron fires are still captured.  Deduplication is handled by the caller
        (timestamp window or raw_message_id check against thread_messages / interactions).

        Returns list of dicts with keys:
          uid, from_email, from_name, subject, body, received_at, message_id, in_reply_to
        """
        if not self._conn:
            raise RuntimeError("Not connected")

        self._conn.select("INBOX")
        since_str = since_dt.strftime(_IMAP_DATE_FMT)
        _, data = self._conn.search(None, f"SINCE {since_str}")
        uids = data[0].split() if data[0] else []
        return self._parse_uids(uids)

    def fetch_unseen_replies(self) -> list[dict]:
        """Fetch all UNSEEN messages in INBOX that look like replies (subject starts with Re:).

        Retained for backwards compatibility.  New callers should prefer fetch_since_replies()
        so replies read before the cron fires are not silently dropped.

        Returns list of dicts with keys:
          uid, from_email, from_name, subject, body, received_at, message_id, in_reply_to
        """
        if not self._conn:
            raise RuntimeError("Not connected")

        self._conn.select("INBOX")
        _, data = self._conn.search(None, "UNSEEN")
        uids = data[0].split() if data[0] else []
        return self._parse_uids(uids)

    def _parse_uids(self, uids: list) -> list[dict]:
        """Fetch and parse a list of IMAP UIDs into reply dicts."""
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

            results.append(
                {
                    "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                    "from_email": from_email,
                    "from_name": from_name,
                    "subject": subject,
                    "body": reply_text or body[:2000],
                    "received_at": received_at,
                    "message_id": msg.get("Message-ID", ""),
                    "in_reply_to": msg.get("In-Reply-To", ""),
                }
            )

        return results

    def mark_as_read(self, uid: str) -> None:
        """Mark a message as read by UID."""
        if self._conn:
            try:
                self._conn.store(uid, "+FLAGS", "\\Seen")
            except Exception as e:
                logger.warning(f"Failed to mark UID {uid} as read: {e}")
