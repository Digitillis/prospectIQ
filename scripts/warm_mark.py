#!/usr/bin/env python3
"""Light tracking for WARM / personal outreach (hand-sent).

Records what you did by hand. Scoped to the warm workspace only.

    python3 scripts/warm_mark.py sent <draft_id|email>  # mark sent (email = newest unsent draft)
    python3 scripts/warm_mark.py replied <email>     # they replied
    python3 scripts/warm_mark.py meeting <email>     # a meeting/call is scheduled

The 'sent' command takes either a draft UUID or the recipient's email address. With an email it
resolves to that contact's lowest unsent sequence step, so you never have to copy a UUID.

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


def _resolve_sent_target(client, ws, target):
    """Resolve a 'sent' target (draft UUID or email) to a draft id + its current sent_at.

    For an email, returns the contact's LOWEST unsent sequence step (the one you just sent).
    Returns (draft_id, sent_at) or (None, None) if nothing actionable was found.
    """
    if "@" in target:
        email = target.strip().lower()
        ct = (
            client.table("contacts")
            .select("id")
            .eq("workspace_id", ws)
            .eq("email", email)
            .limit(1)
            .execute()
            .data
        )
        if not ct:
            print(f"  ! no warm contact with email {email!r}")
            return None, None
        drafts = (
            client.table("outreach_drafts")
            .select("id,sent_at,sequence_step")
            .eq("workspace_id", ws)
            .eq("contact_id", ct[0]["id"])
            .order("sequence_step")
            .execute()
            .data
            or []
        )
        unsent = [d for d in drafts if not d.get("sent_at")]
        if not unsent:
            print(f"  • all drafts for {email} are already marked sent" if drafts
                  else f"  ! no drafts for {email}")
            return None, None
        return unsent[0]["id"], None
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
        return None, None
    return rows[0]["id"], rows[0].get("sent_at")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    action, target = sys.argv[1].lower(), sys.argv[2]
    ws = get_settings().warm_workspace_id
    client = get_supabase_client()

    if action == "sent":
        draft_id, sent_at = _resolve_sent_target(client, ws, target)
        if not draft_id:
            return 1
        if sent_at:
            print(f"  • already marked sent at {sent_at}")
            return 0
        client.table("outreach_drafts").update({"sent_at": _now()}).eq("workspace_id", ws).eq(
            "id", draft_id
        ).execute()
        print(f"  ✓ marked draft {draft_id} as sent")
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
