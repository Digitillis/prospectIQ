#!/usr/bin/env python3
"""Ingest a warm/personal attendee list into the ISOLATED warm workspace and emit threads.

Reads an attendee CSV (e.g. symposium attendees) and creates/updates ``companies`` +
``contacts`` rows under ``WARM_WORKSPACE_ID`` ONLY. It then computes, per contact, the next
touch to write (1..max-touches) based on any warm drafts already sent/pending, and prints a
JSON ``threads`` payload that ``generate-warm-outreach.js`` turns into Opus drafts.

Everything here is scoped to the warm workspace. It never reads or writes cold data, and the
warm workspace cannot be scheduled or sent (see scripts/seed_warm_workspace.py).

CSV headers (case-insensitive; extras ignored):
    name            (required)  e.g. "Dana Whitfield"
    email           (required)  e.g. "dana@acmecast.com"
    title           (optional)  e.g. "VP Operations"
    company         (optional)  e.g. "Acme Castings"  (else inferred from email domain)
    note | session | talk       (optional, STRONGEST hook) e.g. "gave the talk on furnace uptime"

Usage:
    python3 scripts/warm_ingest_attendees.py path/to/attendees.csv [--max-touches 3]

Output (stdout): JSON {threads:[...], created_companies, created_contacts, skipped_complete}
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client

NOTE_KEYS = ("note", "session", "talk", "session_or_note", "notes")


def _norm(row: dict) -> dict:
    return {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}


def _split_name(name: str) -> tuple[str, str]:
    parts = name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _domain(email: str) -> str | None:
    if "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None


def _company_from_domain(domain: str | None) -> str:
    if not domain:
        return "Unknown"
    base = domain.split(".")[0]
    return base.replace("-", " ").title()


def _cold_collision(client, cold_ws: str, email: str) -> dict | None:
    """Detect whether this person is already a COLD prospect.

    INTENTIONALLY cross-workspace (read-only): warm and cold data are never mixed,
    but we DO check for overlap so the same person is not double-touched by cold
    automation AND a personal warm note. Returns None if not in the cold workspace,
    else {state, contacted} where contacted=True means a cold email was already sent
    (or the cold contact is mid-sequence / engaged).
    """
    rows = (
        client.table("contacts")
        .select("id,outreach_state,status")
        .eq("workspace_id", cold_ws)
        .eq("email", email)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    cc = rows[0]
    state = (cc.get("outreach_state") or cc.get("status") or "").lower()
    sent = (
        client.table("outreach_drafts")
        .select("id")
        .eq("workspace_id", cold_ws)
        .eq("contact_id", cc["id"])
        .not_.is_("sent_at", "null")
        .limit(1)
        .execute()
        .data
    )
    contacted = bool(sent) or any(
        k in state for k in ("touch_", "contacted", "engaged", "replied", "demo", "closed")
    )
    return {"state": state or "unknown", "contacted": contacted}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--max-touches", type=int, default=3)
    ap.add_argument(
        "--include-cold-contacted",
        action="store_true",
        help="also generate warm drafts for people already CONTACTED in the cold pipeline "
        "(default: skip them to avoid double-touch)",
    )
    args = ap.parse_args()

    ws = get_settings().warm_workspace_id
    cold_ws = get_settings().default_workspace_id
    if not ws or ws == cold_ws:
        print("FATAL: warm_workspace_id is unset or equals the cold workspace.", file=sys.stderr)
        return 1
    client = get_supabase_client()

    with open(args.csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = [_norm(r) for r in csv.DictReader(fh)]

    threads: list[dict] = []
    collisions: list[dict] = []
    created_companies = created_contacts = skipped_complete = 0

    for r in rows:
        email = (r.get("email") or "").lower()
        name = r.get("name") or ""
        if not email or not name:
            continue
        title = r.get("title") or ""
        note = next((r[k] for k in NOTE_KEYS if r.get(k)), "")
        domain = _domain(email)
        company_name = r.get("company") or _company_from_domain(domain)
        first, last = _split_name(name)

        # --- cross-channel collision: already a COLD prospect? (read-only) ---
        collision = _cold_collision(client, cold_ws, email)
        if collision and collision["contacted"] and not args.include_cold_contacted:
            # Already being cold-emailed → skip the warm note to avoid double-touch.
            collisions.append({"email": email, "name": name, **collision, "action": "skipped"})
            continue
        if collision:
            # In the cold list but not yet contacted → warm note is fine; flag for awareness.
            collisions.append({"email": email, "name": name, **collision, "action": "flagged"})

        # --- company (dedup by domain, else name, within the warm workspace) ---
        company = None
        if domain:
            company = (
                client.table("companies")
                .select("id,name")
                .eq("workspace_id", ws)
                .eq("domain", domain)
                .limit(1)
                .execute()
                .data
            )
        if not company:
            company = (
                client.table("companies")
                .select("id,name")
                .eq("workspace_id", ws)
                .eq("name", company_name)
                .limit(1)
                .execute()
                .data
            )
        if company:
            company_id = company[0]["id"]
        else:
            ins = (
                client.table("companies")
                .insert(
                    {
                        "workspace_id": ws,
                        "name": company_name,
                        "domain": domain,
                        "status": "discovered",
                        "research_summary": note or None,
                        "campaign_name": "warm_personal",
                    }
                )
                .execute()
                .data
            )
            company_id = ins[0]["id"]
            created_companies += 1

        # --- contact (dedup by email within the warm workspace) ---
        contact = (
            client.table("contacts")
            .select("id")
            .eq("workspace_id", ws)
            .eq("email", email)
            .limit(1)
            .execute()
            .data
        )
        if contact:
            contact_id = contact[0]["id"]
        else:
            ins = (
                client.table("contacts")
                .insert(
                    {
                        "workspace_id": ws,
                        "company_id": company_id,
                        "first_name": first,
                        "last_name": last,
                        "full_name": name,
                        "email": email,
                        "title": title,
                        "status": "identified",
                    }
                )
                .execute()
                .data
            )
            contact_id = ins[0]["id"]
            created_contacts += 1

        # --- next touch (cap at max-touches); gather priors for continuity ---
        existing = (
            client.table("outreach_drafts")
            .select("sequence_step,subject,body,sent_at,approval_status")
            .eq("workspace_id", ws)
            .eq("contact_id", contact_id)
            .execute()
            .data
            or []
        )
        steps = sorted({d["sequence_step"] for d in existing if d.get("sequence_step")})
        next_step = (max(steps) + 1) if steps else 1
        if next_step > args.max_touches:
            skipped_complete += 1
            continue
        prior_emails = [
            {
                "step": d["sequence_step"],
                "subject": d.get("subject") or "",
                "body": d.get("body") or "",
            }
            for d in sorted(existing, key=lambda d: d.get("sequence_step") or 0)
            if d.get("sent_at")
        ]

        threads.append(
            {
                "company_id": company_id,
                "company_name": company_name,
                "contact_id": contact_id,
                "contact_name": name,
                "contact_title": title,
                "contact_email": email,
                "domain": domain or "",
                "note": note,
                "cold_collision": collision,
                "pending_step": next_step,
                "prior_emails": prior_emails,
            }
        )

    cold_contacted_skipped = sum(1 for c in collisions if c["action"] == "skipped")
    cold_flagged = sum(1 for c in collisions if c["action"] == "flagged")

    # Human-readable collision summary to stderr (stdout stays pure JSON for the workflow).
    if collisions:
        print(
            f"\nCROSS-CHANNEL COLLISIONS: {len(collisions)} attendee(s) also exist as cold prospects",
            file=sys.stderr,
        )
        print(
            f"  - {cold_contacted_skipped} already COLD-CONTACTED -> skipped "
            f"(re-run with --include-cold-contacted to override)",
            file=sys.stderr,
        )
        print(
            f"  - {cold_flagged} in cold list but not yet contacted -> included, flagged",
            file=sys.stderr,
        )
        for c in collisions:
            print(
                f"      [{c['action']}] {c['name']} <{c['email']}>  cold-state={c['state']}",
                file=sys.stderr,
            )

    print(
        json.dumps(
            {
                "threads": threads,
                "created_companies": created_companies,
                "created_contacts": created_contacts,
                "skipped_complete": skipped_complete,
                "collisions": collisions,
                "cold_contacted_skipped": cold_contacted_skipped,
                "cold_flagged": cold_flagged,
                "workspace_id": ws,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
