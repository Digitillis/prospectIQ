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

        client = get_supabase_client()
    except Exception as exc:  # noqa: BLE001 — env not configured (e.g. CI)
        pytest.skip(f"Supabase not configured: {exc}")
    # The client can construct with a placeholder URL yet fail to reach Supabase (CI / offline).
    # Probe once and skip cleanly rather than erroring every DB-touching test.
    try:
        client.table("workspaces").select("id").limit(1).execute()
    except Exception as exc:  # noqa: BLE001 — unreachable in CI / offline
        pytest.skip(f"Supabase not reachable: {exc}")
    return client


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


# ============================================================
# PROSPECT-LEVEL ISOLATION — the same PERSON must not live in both channels.
# The structural tests above prove the warm *workspace* is inert. These prove the
# warm and cold *prospect lists* do not mix: no one is hand-sent a personal note
# while also being machine-emailed by the cold pipeline (a double-touch), and warm
# messages never leak into the cold workspace.
# ============================================================

_COLD_CONTACTED_STATES = ("touch_", "contacted", "engaged", "replied", "demo", "closed")


def _chunked(seq, n=200):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _warm_contacts(client):
    return (
        client.table("contacts").select("id,email").eq("workspace_id", _warm_id()).execute().data
        or []
    )


def _cold_is_contacted(client, cold_ws, cold_contact):
    """Mirror the ingest collision rule: a cold contact counts as CONTACTED if a cold
    email was already sent to it, or its state is mid-sequence/engaged/closed."""
    state = (cold_contact.get("outreach_state") or cold_contact.get("status") or "").lower()
    if any(k in state for k in _COLD_CONTACTED_STATES):
        return True
    sent = (
        client.table("outreach_drafts")
        .select("id")
        .eq("workspace_id", cold_ws)
        .eq("contact_id", cold_contact["id"])
        .not_.is_("sent_at", "null")
        .limit(1)
        .execute()
        .data
    )
    return bool(sent)


def test_no_warm_contact_is_cold_contacted(warm_workspace):
    """STRICT no-mix canary: no warm prospect may also be a COLD-CONTACTED prospect.

    Someone already in a cold sequence (or already cold-emailed) must never also receive
    a personal warm note — that is the double-touch the channels exist to prevent. An email
    that is in the cold list but NOT yet contacted is allowed (warm may proceed, flagged);
    those are reported but do not fail.
    """
    client = _client_or_skip()
    cold_ws = get_settings().default_workspace_id
    warm = _warm_contacts(client)
    warm_emails = sorted({(c.get("email") or "").lower() for c in warm if c.get("email")})
    if not warm_emails:
        pytest.skip("no warm contacts loaded yet")

    cold_contacted = []
    cold_uncontacted = []
    for chunk in _chunked(warm_emails):
        cold = (
            client.table("contacts")
            .select("id,email,outreach_state,status")
            .eq("workspace_id", cold_ws)
            .in_("email", chunk)
            .execute()
            .data
            or []
        )
        for cc in cold:
            if _cold_is_contacted(client, cold_ws, cc):
                cold_contacted.append(cc["email"])
            else:
                cold_uncontacted.append(cc["email"])

    if cold_uncontacted:
        print(
            "\n[warm/cold overlap, ALLOWED] in cold list but not yet contacted "
            f"({len(cold_uncontacted)}): {cold_uncontacted}"
        )
    assert not cold_contacted, (
        "DOUBLE-TOUCH: these warm prospects are also COLD-CONTACTED and must be removed "
        f"from one channel: {cold_contacted}"
    )


def test_warm_messages_never_in_cold_workspace(warm_workspace):
    """STRICT message separation: every draft addressed to a warm contact lives ONLY in the
    warm workspace. No warm contact may have an outreach_draft under the cold workspace."""
    client = _client_or_skip()
    cold_ws = get_settings().default_workspace_id
    warm = _warm_contacts(client)
    warm_ids = [c["id"] for c in warm]
    if not warm_ids:
        pytest.skip("no warm contacts loaded yet")

    leaked = []
    for chunk in _chunked(warm_ids):
        rows = (
            client.table("outreach_drafts")
            .select("id,contact_id")
            .eq("workspace_id", cold_ws)
            .in_("contact_id", chunk)
            .limit(1)
            .execute()
            .data
            or []
        )
        leaked.extend(r["id"] for r in rows)
    assert not leaked, (
        f"found {len(leaked)} cold-workspace drafts targeting warm contacts — messages leaked "
        "across the channel boundary"
    )
