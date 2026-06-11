#!/usr/bin/env python3
"""Review WARM / personal drafts (copy-paste send surface).

Lists drafts in the ISOLATED warm workspace, grouped by contact, ready to copy into your own
Gmail and send by hand. Read-only. Nothing here sends anything.

    python3 scripts/warm_review.py                 # pending warm drafts
    python3 scripts/warm_review.py --all           # include already-sent
    python3 scripts/warm_review.py --event warm_symposium   # filter by sequence_name

After you send one by hand, record it with:  python3 scripts/warm_mark.py sent <draft_id>
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="include already-sent drafts")
    ap.add_argument("--event", default=None, help="filter by sequence_name (e.g. warm_symposium)")
    args = ap.parse_args()

    ws = get_settings().warm_workspace_id
    client = get_supabase_client()

    q = (
        client.table("outreach_drafts")
        .select(
            "id,company_id,contact_id,sequence_name,sequence_step,subject,body,personalization_notes,approval_status,sent_at"
        )
        .eq("workspace_id", ws)
    )
    if args.event:
        q = q.eq("sequence_name", args.event)
    if not args.all:
        q = q.is_("sent_at", "null")
    drafts = q.order("sequence_step").execute().data or []

    if not drafts:
        print("No warm drafts found (run generate-warm-outreach first, or drop --all).")
        return 0

    # contact + company lookups (warm-scoped)
    contact_ids = list({d["contact_id"] for d in drafts if d.get("contact_id")})
    contacts = {}
    if contact_ids:
        rows = (
            client.table("contacts")
            .select("id,full_name,email,title,company_id,status,outreach_state")
            .eq("workspace_id", ws)
            .in_("id", contact_ids)
            .execute()
            .data
            or []
        )
        contacts = {r["id"]: r for r in rows}

    by_contact = defaultdict(list)
    for d in drafts:
        by_contact[d.get("contact_id")].append(d)

    print(f"WARM drafts in workspace {ws}  ({len(drafts)} draft(s), {len(by_contact)} contact(s))")
    print("=" * 78)
    for cid, items in by_contact.items():
        c = contacts.get(cid, {})
        who = f"{c.get('full_name', '?')}  <{c.get('email', '?')}>"
        title = c.get("title") or ""
        state = c.get("outreach_state") or c.get("status") or "—"
        print(f"\n### {who}{('  — ' + title) if title else ''}   [status: {state}]")
        for d in sorted(items, key=lambda x: x.get("sequence_step") or 0):
            sent = (
                f"SENT {d['sent_at']}"
                if d.get("sent_at")
                else f"{d.get('approval_status', 'pending').upper()}"
            )
            print(f"\n  — Step {d.get('sequence_step')}  ({sent})  draft_id={d['id']}")
            print(f"    Subject: {d.get('subject', '')}")
            body = (d.get("body") or "").strip()
            for line in body.splitlines():
                print(f"    | {line}")
            if d.get("personalization_notes"):
                print(f"    hook: {d['personalization_notes']}")
    print("\n" + "=" * 78)
    print(
        "Send each by hand from your own Gmail, then: python3 scripts/warm_mark.py sent <draft_id>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
