#!/usr/bin/env python3
"""Reconcile inbound email replies into the ISOLATED warm workspace (hand-sent channel).

WARM-ONLY. READ-ONLY on IMAP. NEVER touches the cold workspace. DEFAULT = DRY RUN.

Reads the avi@digitillis.com Gmail inbox over IMAP in READ-ONLY mode (the mailbox is
SELECTed with readonly=True — this script never deletes a message, never marks one as
seen, and never moves anything). For each recent inbound message it takes the From:
address, normalizes it, and looks up a contact ONLY in the warm workspace
(``warm_workspace_id``). It never queries and never writes the cold/default workspace.

For a matched warm contact that has not already been logged, it (with ``--commit``):
  * inserts a ``contact_events`` row (event_type='response_received', channel='email',
    direction='inbound') carrying the email Message-ID in the ``tags`` JSONB for
    idempotency, and
  * updates the ``contacts`` row to outreach_state='replied' plus a light
    keyword-heuristic ``reply_sentiment`` (clearly a heuristic, NOT an LLM call).

Idempotency: dedup is by the email Message-ID. The msgid is stored in
contact_events.tags ({"msgid": "..."}); a message whose msgid is already present on an
existing warm contact_events row for that contact is reported as a duplicate and skipped.

By DEFAULT this prints what it WOULD do and writes NOTHING. Pass ``--commit`` to write.
Safe to re-run.

Usage:
    python3 scripts/warm_reply_reconcile.py [--days 14] [--commit] [--json]
"""

from __future__ import annotations

import argparse
import imaplib
import json
import sys
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.utils import parsedate_to_datetime

from backend.app.core.config import get_settings

# Reuse the cold intake's importable header/body parsing helpers — do NOT duplicate them.
from backend.app.integrations.gmail_imap import (
    IMAP_HOST,
    IMAP_PORT,
    _decode_str,
    _get_body,
    _strip_quoted_text,
)

# IMAP date format required by RFC 3501 SEARCH SINCE criterion.
_IMAP_DATE_FMT = "%d-%b-%Y"

# --- Reply sentiment heuristic (keyword-only — explicitly NOT an LLM classification) ---
_POSITIVE_KWS = (
    "happy to",
    "let's",
    "lets ",
    "sure",
    "interested",
    "sounds good",
    "calendar",
    "available",
)
_NEGATIVE_KWS = (
    "not interested",
    "no thanks",
    "remove",
    "unsubscribe",
    "stop",
)


def heuristic_sentiment(text: str) -> str:
    """Classify reply sentiment with a SIMPLE keyword heuristic.

    Returns 'positive', 'negative', or 'neutral'. This is a heuristic only — it is not
    an LLM classification and is not meant to be authoritative. Negative phrases win over
    positive so an explicit opt-out is never read as interest.
    """
    low = (text or "").lower()
    if any(kw in low for kw in _NEGATIVE_KWS):
        return "negative"
    if any(kw in low for kw in _POSITIVE_KWS):
        return "positive"
    return "neutral"


def parse_from_address(from_header: str) -> str:
    """Extract and normalize the sender email from a raw From: header.

    Handles 'Name <addr@x.com>' and bare 'addr@x.com'. Returns a lowercased,
    stripped address, or '' when none can be parsed.
    """
    raw = _decode_str(from_header or "").strip()
    if "<" in raw and ">" in raw:
        addr = raw[raw.rfind("<") + 1 : raw.rfind(">")]
    else:
        addr = raw
    return addr.strip().strip('"').strip("'").lower()


def msgid_already_logged(existing_events: list[dict], msgid: str) -> bool:
    """Return True if any existing warm contact_events row already carries this msgid.

    The msgid lives in the row's ``tags`` JSONB, stored as {"msgid": "..."} (dict) or as
    a list of tags that may include the string itself. Empty msgid is treated as
    not-loggable (returns True so we skip rather than write a non-idempotent row).
    """
    if not msgid:
        return True
    for ev in existing_events or []:
        tags = ev.get("tags")
        if isinstance(tags, dict) and tags.get("msgid") == msgid:
            return True
        if isinstance(tags, list) and msgid in tags:
            return True
    return False


def resolve_workspaces() -> tuple[str, str]:
    """Return (warm_ws, cold_ws), asserting warm is set and distinct from cold.

    Exits the process nonzero (via SystemExit) if the warm workspace is unset or equals
    the cold/default workspace — that would mean a reply could land in the cold pipeline.
    """
    settings = get_settings()
    ws = settings.warm_workspace_id
    cold = settings.default_workspace_id
    if not ws or ws == cold:
        print(
            "FATAL: warm_workspace_id is unset or equals the cold/default workspace "
            f"(warm={ws!r}, cold={cold!r}). Refusing to run.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return ws, cold


def fetch_inbound_readonly(user: str, app_password: str, since_dt: datetime) -> list[dict]:
    """Fetch INBOX messages since *since_dt* over IMAP in READ-ONLY mode.

    The mailbox is opened with readonly=True, so the server never sets \\Seen and nothing
    is deleted or moved. Returns dicts: from_email, from_name, subject, body, received_at,
    message_id.
    """
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        conn.login(user, app_password)
        # READ-ONLY select — the server will not flag messages as seen.
        conn.select("INBOX", readonly=True)
        since_str = since_dt.strftime(_IMAP_DATE_FMT)
        _, data = conn.search(None, f"SINCE {since_str}")
        uids = data[0].split() if data and data[0] else []
        results: list[dict] = []
        for uid in uids:
            # BODY.PEEK[] fetches the full message WITHOUT setting the \\Seen flag,
            # belt-and-suspenders on top of the read-only SELECT.
            _, msg_data = conn.fetch(uid, "(BODY.PEEK[])")
            if not msg_data or not msg_data[0]:
                continue
            msg = message_from_bytes(msg_data[0][1])
            from_header = msg.get("From", "")
            subject = _decode_str(msg.get("Subject", ""))
            body = _strip_quoted_text(_get_body(msg)) or _get_body(msg)
            try:
                received_at = (
                    parsedate_to_datetime(msg.get("Date", "")).astimezone(timezone.utc).isoformat()
                )
            except Exception:
                received_at = datetime.now(timezone.utc).isoformat()
            results.append(
                {
                    "from_email": parse_from_address(from_header),
                    "from_name": _decode_str(from_header).split("<")[0].strip().strip('"'),
                    "subject": subject,
                    "body": body or "",
                    "received_at": received_at,
                    "message_id": (msg.get("Message-ID", "") or "").strip(),
                }
            )
        return results
    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:
            pass


def find_warm_contact(client, ws: str, from_email: str) -> dict | None:
    """Look up a contact by email in the WARM workspace ONLY.

    Every query is scoped with .eq("workspace_id", ws). The cold workspace is never
    queried. Returns the contact row or None.
    """
    if not from_email:
        return None
    rows = (
        client.table("contacts")
        .select("id, company_id, email, full_name, outreach_state")
        .eq("workspace_id", ws)
        .eq("email", from_email)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def existing_reply_events(client, ws: str, contact_id: str) -> list[dict]:
    """Fetch existing inbound reply events for a contact in the WARM workspace only.

    contact_events has no workspace_id column, so it is scoped transitively: contact_id
    comes from a warm-scoped contacts lookup. Returns rows carrying their ``tags`` so the
    caller can dedup by msgid.
    """
    return (
        client.table("contact_events")
        .select("id, tags")
        .eq("contact_id", contact_id)
        .eq("event_type", "response_received")
        .eq("direction", "inbound")
        .execute()
        .data
        or []
    )


def build_event_payload(contact: dict, msg: dict, sentiment: str) -> dict:
    """Build the contact_events insert payload for a matched warm reply."""
    return {
        "contact_id": contact["id"],
        "company_id": contact.get("company_id"),
        "event_type": "response_received",
        "channel": "email",
        "direction": "inbound",
        "subject": msg.get("subject") or "",
        "body": (msg.get("body") or "")[:2000],
        "sentiment": sentiment,
        "sentiment_reason": "keyword heuristic (warm_reply_reconcile, not an LLM)",
        "tags": {"msgid": msg.get("message_id", ""), "source": "warm_reply_reconcile"},
        "created_by": "system",
    }


def reconcile(client, ws: str, messages: list[dict], commit: bool) -> dict:
    """Reconcile fetched inbound messages against warm contacts.

    Read-only by default. Only writes when ``commit`` is True, and only ever to the warm
    workspace. Returns a summary dict with a per-row ``planned`` list.
    """
    planned: list[dict] = []
    matched = new = duplicates = written = 0

    for msg in messages:
        from_email = msg.get("from_email", "")
        contact = find_warm_contact(client, ws, from_email)
        if not contact:
            continue  # not a warm contact — ignore entirely
        matched += 1

        msgid = msg.get("message_id", "")
        events = existing_reply_events(client, ws, contact["id"])
        is_dup = msgid_already_logged(events, msgid)
        sentiment = heuristic_sentiment(f"{msg.get('subject', '')} {msg.get('body', '')}")

        row = {
            "contact": contact.get("full_name") or from_email,
            "email": from_email,
            "subject": (msg.get("subject") or "")[:80],
            "sentiment": sentiment,
            "status": "duplicate" if is_dup else "new",
        }

        if is_dup:
            duplicates += 1
            planned.append(row)
            continue

        new += 1
        planned.append(row)
        if commit:
            client.table("contact_events").insert(
                build_event_payload(contact, msg, sentiment)
            ).execute()
            updates = {"outreach_state": "replied", "reply_sentiment": sentiment}
            # last_touch metadata columns may not exist in every deployment — best effort.
            try:
                client.table("contacts").update(
                    {**updates, "last_touch_at": msg.get("received_at")}
                ).eq("workspace_id", ws).eq("id", contact["id"]).execute()
            except Exception:  # noqa: BLE001
                client.table("contacts").update(updates).eq("workspace_id", ws).eq(
                    "id", contact["id"]
                ).execute()
            written += 1

    return {
        "workspace_id": ws,
        "fetched": len(messages),
        "matched": matched,
        "new": new,
        "duplicates": duplicates,
        "written": written,
        "committed": commit,
        "planned": planned,
    }


def print_summary(summary: dict, as_json: bool) -> None:
    """Print the human/JSON summary to stdout; commentary already went to stderr."""
    if as_json:
        print(json.dumps(summary, indent=2))
        return
    mode = "COMMIT" if summary["committed"] else "DRY RUN (nothing written)"
    print(f"[{mode}] warm workspace {summary['workspace_id']}")
    print(
        f"fetched={summary['fetched']} matched_warm={summary['matched']} "
        f"new={summary['new']} duplicate={summary['duplicates']} written={summary['written']}"
    )
    if summary["planned"]:
        print(f"{'STATUS':<10} {'SENTIMENT':<9} {'CONTACT':<28} SUBJECT")
        for r in summary["planned"]:
            print(
                f"{r['status']:<10} {r['sentiment']:<9} "
                f"{(r['contact'] or '')[:28]:<28} {r['subject']}"
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Reconcile warm-workspace email replies (read-only IMAP)."
    )
    ap.add_argument("--days", type=int, default=14, help="how many days back to scan (default 14)")
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--json", action="store_true", help="emit JSON summary to stdout")
    args = ap.parse_args(argv)

    ws, cold = resolve_workspaces()
    print(
        f"Operating on WARM workspace {ws} (cold workspace {cold} is never touched).",
        file=sys.stderr,
    )

    settings = get_settings()
    user, pw = settings.gmail_user, settings.gmail_app_password
    if not user or not pw:
        print("FATAL: GMAIL_USER / GMAIL_APP_PASSWORD not set in .env.", file=sys.stderr)
        return 1

    since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"Fetching INBOX since {since_dt.date()} over IMAP (READ-ONLY)...", file=sys.stderr)
    messages = fetch_inbound_readonly(user, pw, since_dt)

    from backend.app.core.database import get_supabase_client

    client = get_supabase_client()
    summary = reconcile(client, ws, messages, commit=args.commit)
    print_summary(summary, as_json=args.json)
    if not args.commit and summary["new"]:
        print(
            f"\nDRY RUN: {summary['new']} new reply event(s) would be logged. "
            "Re-run with --commit to write.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
