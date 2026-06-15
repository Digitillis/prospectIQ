#!/usr/bin/env python3
"""Light tracking for WARM / personal outreach (hand-sent).

Records what you did by hand. Scoped to the warm workspace only.

    python3 scripts/warm_mark.py sent <draft_id>     # you sent this draft from your Gmail
    python3 scripts/warm_mark.py replied <email>     # they replied
    python3 scripts/warm_mark.py meeting <email>     # a meeting/call is scheduled

'sent' sets outreach_drafts.sent_at; 'replied'/'meeting' update the contact's state so the
warm list shows progress at a glance in scripts/warm_review.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_contact_state(client, ws, email, *, status, outreach_state) -> bool:
    rows = (
        client.table("contacts")
        .select("id")
        .eq("workspace_id", ws)
        .eq("email", email.lower())
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        print(f"  ! no warm contact with email {email!r}")
        return False
    cid = rows[0]["id"]
    payload = {"status": status}
    # outreach_state column may not exist in every deployment — set it best-effort.
    try:
        client.table("contacts").update({**payload, "outreach_state": outreach_state}).eq(
            "workspace_id", ws
        ).eq("id", cid).execute()
    except Exception:  # noqa: BLE001
        client.table("contacts").update(payload).eq("workspace_id", ws).eq("id", cid).execute()
    return True


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    action, target = sys.argv[1].lower(), sys.argv[2]
    ws = get_settings().warm_workspace_id
    client = get_supabase_client()

    if action == "sent":
        rows = (
            client.table("outreach_drafts")
            .select("id,sent_at")
            .eq("workspace_id", ws)
            .eq("id", target)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            print(f"  ! no warm draft with id {target!r} (is it in the warm workspace?)")
            return 1
        if rows[0].get("sent_at"):
            print(f"  • already marked sent at {rows[0]['sent_at']}")
            return 0
        client.table("outreach_drafts").update({"sent_at": _now()}).eq("workspace_id", ws).eq(
            "id", target
        ).execute()
        print(f"  ✓ marked draft {target} as sent")
        return 0

    if action == "replied":
        ok = _update_contact_state(client, ws, target, status="engaged", outreach_state="replied")
        print("  ✓ marked replied" if ok else "  ✗ not updated")
        return 0 if ok else 1

    if action == "meeting":
        ok = _update_contact_state(
            client, ws, target, status="engaged", outreach_state="demo_scheduled"
        )
        print("  ✓ marked meeting scheduled" if ok else "  ✗ not updated")
        return 0 if ok else 1

    print(f"Unknown action {action!r}. Use: sent <draft_id> | replied <email> | meeting <email>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
