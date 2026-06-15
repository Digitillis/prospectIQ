#!/usr/bin/env python3
"""Seed the isolated WARM / PERSONAL outreach workspace.

The warm workspace holds hand-sent, 1:1 personal outreach (e.g. symposium attendees).
It is structurally isolated from the cold automated pipeline by riding the multi-tenant
``workspace_id`` boundary that every query already enforces (``database._filter_ws`` is
fail-closed). On top of that boundary this seed sets two independent guarantees:

  1. ``workspaces.subscription_status = 'internal'`` — NOT in ('active','trialing'), so the
     warm workspace is excluded from ``get_active_workspaces()`` and therefore never enters
     ANY scheduler job (schedule_recompute, enqueue_schedule, dispatch_loop, gmail_intake,
     process_due, jit_pregenerate). It is never scheduled, enqueued, dispatched, or polled.
  2. ``outreach_send_config.send_enabled = false`` + ``daily_limit = 0`` + ``sender_pool = []``
     — a second, independent gate: even if dispatch were invoked by hand, the warm workspace
     has no sending identity and sending is disabled.

This script is idempotent and additive. It creates rows only; it never enables sending and
never touches cold data. Run it once; it is safe to re-run.

    python3 scripts/seed_warm_workspace.py            # seed + verify
    python3 scripts/seed_warm_workspace.py --verify   # verify only, no writes
"""

from __future__ import annotations

import sys

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client

WARM_NAME = "Warm / Personal Outreach"
WARM_SLUG = "warm-personal"
# Excluded from get_active_workspaces() which selects status IN ('active','trialing').
WARM_STATUS = "internal"


def _active_set(client) -> set[str]:
    rows = (
        client.table("workspaces")
        .select("id")
        .in_("subscription_status", ["active", "trialing"])
        .execute()
        .data
        or []
    )
    return {r["id"] for r in rows}


def verify(client, warm_id: str, default_id: str) -> bool:
    """Assert the warm workspace is inert. Returns True if all guarantees hold."""
    ok = True

    ws = client.table("workspaces").select("*").eq("id", warm_id).limit(1).execute().data
    if not ws:
        print(f"  ✗ workspace {warm_id} does not exist")
        return False
    ws = ws[0]
    status = ws.get("subscription_status")
    if status in ("active", "trialing"):
        print(
            f"  ✗ subscription_status={status!r} would be SCHEDULED — must not be active/trialing"
        )
        ok = False
    else:
        print(f"  ✓ subscription_status={status!r} (excluded from get_active_workspaces)")

    if warm_id in _active_set(client):
        print("  ✗ warm workspace appears in the ACTIVE set — scheduler would touch it")
        ok = False
    else:
        print("  ✓ warm workspace is NOT in the active set (scheduler skips it)")

    cfg = (
        client.table("outreach_send_config")
        .select("*")
        .eq("workspace_id", warm_id)
        .limit(1)
        .execute()
        .data
    )
    if not cfg:
        print(
            "  ✗ no outreach_send_config row — send_enabled would DEFAULT TO TRUE. Must seed explicit row."
        )
        ok = False
    else:
        cfg = cfg[0]
        send_enabled = cfg.get("send_enabled")
        daily_limit = cfg.get("daily_limit")
        sender_pool = cfg.get("sender_pool") or []
        if send_enabled:
            print(f"  ✗ send_enabled={send_enabled!r} — MUST be false")
            ok = False
        else:
            print(
                f"  ✓ send_enabled={send_enabled!r}, daily_limit={daily_limit}, sender_pool={sender_pool}"
            )

    if warm_id == default_id:
        print(f"  ✗ warm workspace id equals the cold/default workspace id — fatal")
        ok = False
    return ok


def seed(client, warm_id: str, default_id: str) -> None:
    if warm_id == default_id:
        raise SystemExit("FATAL: WARM_WORKSPACE_ID equals DEFAULT_WORKSPACE_ID. Refusing to seed.")

    # Reuse the cold/default workspace owner for membership + owner_email.
    default_ws = (
        client.table("workspaces")
        .select("owner_email")
        .eq("id", default_id)
        .limit(1)
        .execute()
        .data
    )
    owner_email = default_ws[0]["owner_email"] if default_ws else "avi@digitillis.com"

    owner_member = (
        client.table("workspace_members")
        .select("user_id, email")
        .eq("workspace_id", default_id)
        .order("joined_at")
        .limit(1)
        .execute()
        .data
    )

    # 1) workspace row (inert: status 'internal', no automation)
    client.table("workspaces").upsert(
        {
            "id": warm_id,
            "name": WARM_NAME,
            "slug": WARM_SLUG,
            "owner_email": owner_email,
            "tier": "scale",
            "subscription_status": WARM_STATUS,
            "settings": {
                "is_warm": True,
                "automation": "disabled",
                "note": "Hand-sent personal outreach (e.g. symposium attendees). "
                "NEVER on the automated send/scheduler pipeline. Isolated workspace.",
            },
        },
        on_conflict="id",
    ).execute()
    print(f"  • upserted workspace {warm_id} ({WARM_NAME!r}, status={WARM_STATUS!r})")

    # 2) outreach_send_config — sending permanently disabled (defense in depth)
    client.table("outreach_send_config").upsert(
        {
            "workspace_id": warm_id,
            "daily_limit": 0,
            "batch_size": 0,
            "min_gap_minutes": 4,
            "send_enabled": False,
            "sender_pool": [],
            "notes": "WARM / PERSONAL — sending permanently disabled; hand-sent only. Do NOT enable.",
        },
        on_conflict="workspace_id",
    ).execute()
    print("  • upserted outreach_send_config (send_enabled=false, daily_limit=0, sender_pool=[])")

    # 3) membership so the founder's dashboard session can scope to the warm workspace
    if owner_member:
        m = owner_member[0]
        client.table("workspace_members").upsert(
            {
                "workspace_id": warm_id,
                "user_id": m["user_id"],
                "email": m.get("email") or owner_email,
                "role": "owner",
            },
            on_conflict="workspace_id,user_id",
        ).execute()
        print(f"  • upserted workspace_members (owner={m.get('email') or owner_email})")
    else:
        print("  ! no owner member found on the default workspace — skipped membership insert.")
        print(
            "    (Add the founder to workspace_members for the warm workspace to review in the dashboard.)"
        )


def main() -> int:
    settings = get_settings()
    warm_id = settings.warm_workspace_id
    default_id = settings.default_workspace_id
    client = get_supabase_client()

    verify_only = "--verify" in sys.argv

    print(f"Warm workspace : {warm_id}")
    print(f"Cold workspace : {default_id}")
    print()

    if not verify_only:
        print("Seeding (idempotent)...")
        seed(client, warm_id, default_id)
        print()

    print("Verifying isolation guarantees...")
    ok = verify(client, warm_id, default_id)
    print()
    if ok:
        print("✅ Warm workspace is seeded and INERT (cannot be scheduled or sent).")
        print(f"   Ensure your .env has:  WARM_WORKSPACE_ID={warm_id}")
        return 0
    print("❌ Isolation guarantees NOT satisfied — see above. Do not generate warm drafts yet.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
