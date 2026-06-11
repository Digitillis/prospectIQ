"""Isolation canary for the WARM / personal outreach workspace.

Asserts the structural guarantees that keep warm (hand-sent) data off the cold automated
pipeline. The DB-touching checks run against the live Supabase project (read-only) and SKIP
cleanly when Supabase is not configured (e.g. in CI) or when the warm workspace has not been
seeded yet (run scripts/seed_warm_workspace.py first).

If any of these FAIL, the warm workspace could be scheduled or sent — do not generate or send
warm drafts until they pass.
"""

from __future__ import annotations

import pytest

from backend.app.core.config import get_settings


def _client_or_skip():
    try:
        from backend.app.core.database import get_supabase_client

        return get_supabase_client()
    except Exception as exc:  # noqa: BLE001 — env not configured (e.g. CI)
        pytest.skip(f"Supabase not configured: {exc}")


def _warm_id() -> str:
    wid = get_settings().warm_workspace_id
    if not wid:
        pytest.skip("warm_workspace_id is not set")
    return wid


@pytest.fixture(scope="module")
def warm_workspace():
    client = _client_or_skip()
    rows = client.table("workspaces").select("*").eq("id", _warm_id()).limit(1).execute().data
    if not rows:
        pytest.skip("warm workspace not seeded — run scripts/seed_warm_workspace.py")
    return rows[0]


def test_warm_distinct_from_cold():
    # Pure config check — runs everywhere, including CI.
    assert _warm_id() != get_settings().default_workspace_id, (
        "warm workspace id must differ from the cold/default workspace id"
    )


def test_warm_status_not_active(warm_workspace):
    status = warm_workspace.get("subscription_status")
    assert status not in ("active", "trialing"), (
        f"warm subscription_status={status!r} would be picked up by get_active_workspaces() "
        f"and scheduled — must be a non-active status (e.g. 'internal')"
    )


def test_warm_excluded_from_active_workspaces(warm_workspace):
    _client_or_skip()  # skip in CI without creds
    from backend.app.core.workspace_scheduler import get_active_workspaces

    active_ids = {w["id"] for w in get_active_workspaces()}
    assert _warm_id() not in active_ids, (
        "warm workspace appears in get_active_workspaces() — every scheduler job would touch it"
    )


def test_warm_send_disabled(warm_workspace):
    client = _client_or_skip()
    cfg = (
        client.table("outreach_send_config")
        .select("*")
        .eq("workspace_id", _warm_id())
        .limit(1)
        .execute()
        .data
    )
    assert cfg, (
        "no outreach_send_config row for the warm workspace — send_enabled would DEFAULT TO TRUE. "
        "Seed an explicit row with send_enabled=false."
    )
    cfg = cfg[0]
    assert cfg.get("send_enabled") is False, (
        f"warm send_enabled={cfg.get('send_enabled')!r} must be False"
    )
    assert (cfg.get("daily_limit") or 0) == 0, (
        f"warm daily_limit={cfg.get('daily_limit')!r} must be 0"
    )
    assert not (cfg.get("sender_pool") or []), "warm sender_pool must be empty"


def test_no_warm_schedule_or_queue_rows(warm_workspace):
    """Warm is never scheduled/enqueued — there must be zero schedule/queue rows for it."""
    client = _client_or_skip()
    for table in ("send_schedule", "outbound_queue"):
        try:
            rows = (
                client.table(table)
                .select("id")
                .eq("workspace_id", _warm_id())
                .limit(1)
                .execute()
                .data
            )
        except Exception:  # noqa: BLE001 — table/column may differ across deployments
            continue
        assert not rows, (
            f"found {table} rows for the warm workspace — it must never be scheduled/enqueued"
        )
