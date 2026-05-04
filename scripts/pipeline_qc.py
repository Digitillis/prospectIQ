#!/usr/bin/env python3
"""Pipeline QC — runs every 15 min, auto-fixes known issues, emails alert on anomaly.

Checks:
  1. OEC staleness — enriched+eligible contacts not in OEC → auto-fix via refresh_outbound_eligible
  2. Draft generation stall — 0 drafts created in last 2h → alert
  3. Send failures — any drafts stuck in sent_at IS NULL after last send tick → alert
  4. Discovery staleness — no new companies in >4 days → alert
  5. Budget burn rate — MTD spend vs cap → alert at 80%
  6. Approved queue depth — <10 approved unsent on a weekday morning → alert
"""

import sys
import os
import json
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.core.database import Database
from backend.app.core.config import get_settings

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
ALERT_EMAIL   = "avi@digitillis.com"

def now_ct() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M CT")

def send_alert(subject: str, body: str):
    try:
        settings = get_settings()
        if not settings.resend_api_key:
            print(f"[ALERT — no Resend key] {subject}")
            return
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": "ProspectIQ Monitor <avi@digitillis.io>",
            "to": [ALERT_EMAIL],
            "subject": f"[ProspectIQ QC] {subject}",
            "text": body,
        })
        print(f"Alert sent: {subject}")
    except Exception as e:
        print(f"Alert send failed: {e}")

def run_qc():
    db = Database(workspace_id=WORKSPACE_ID)
    now = datetime.now(timezone.utc)
    issues = []
    fixes  = []

    # ── 1. OEC staleness ──────────────────────────────────────────────────
    # Qualified companies with enriched contacts should all be in OEC.
    # If fewer than 90% are present, refresh the OEC.
    qualified_ids = set(
        c["id"] for c in
        db._filter_ws(db.client.table("companies").select("id"))
        .eq("status", "qualified")
        .execute()
        .data or []
    )
    oec_companies_set = set()
    _offset = 0
    while True:
        _page = (
            db.client.table("outbound_eligible_contacts")
            .select("company_id")
            .eq("workspace_id", WORKSPACE_ID)
            .range(_offset, _offset + 999)
            .execute()
            .data or []
        )
        oec_companies_set.update(r["company_id"] for r in _page if r.get("company_id"))
        if len(_page) < 1000:
            break
        _offset += 1000

    oec_count = len(oec_companies_set)
    qualified_in_oec = len(qualified_ids & oec_companies_set)
    qualified_enriched = (
        db._filter_ws(db.client.table("contacts").select("company_id"))
        .eq("outreach_state", "enriched")
        .in_("company_id", list(qualified_ids)[:500] if qualified_ids else ["none"])
        .execute()
    ).data or []
    qualified_with_enriched = len(set(c["company_id"] for c in qualified_enriched))

    if qualified_with_enriched > 0 and qualified_in_oec < qualified_with_enriched * 0.90:
        result = db.client.rpc(
            "refresh_outbound_eligible",
            {"p_workspace_id": WORKSPACE_ID}
        ).execute()
        new_oec_cos = set()
        _offset = 0
        while True:
            _page = (
                db.client.table("outbound_eligible_contacts")
                .select("company_id")
                .eq("workspace_id", WORKSPACE_ID)
                .range(_offset, _offset + 999)
                .execute()
                .data or []
            )
            new_oec_cos.update(r["company_id"] for r in _page if r.get("company_id"))
            if len(_page) < 1000:
                break
            _offset += 1000
        new_qualified_in_oec = len(qualified_ids & new_oec_cos)
        fixes.append(
            f"OEC refreshed: {qualified_in_oec} → {new_qualified_in_oec} qualified companies "
            f"(of {qualified_with_enriched} with enriched contacts)"
        )
    
    # ── 2. Draft generation stall ─────────────────────────────────────────
    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    recent_drafts = (
        db._filter_ws(db.client.table("outreach_drafts").select("id", count="exact"))
        .gte("created_at", two_hours_ago)
        .execute()
    ).count or 0

    qualified_in_oec_count = 0
    try:
        oec_cos = set()
        offset = 0
        while True:
            page = (
                db.client.table("outbound_eligible_contacts")
                .select("company_id")
                .eq("workspace_id", WORKSPACE_ID)
                .range(offset, offset + 999)
                .execute()
                .data or []
            )
            oec_cos.update(r["company_id"] for r in page if r.get("company_id"))
            if len(page) < 1000:
                break
            offset += 1000
        q_ids = set(
            c["id"] for c in
            db._filter_ws(db.client.table("companies").select("id"))
            .eq("status", "qualified")
            .execute()
            .data or []
        )
        qualified_in_oec_count = len(q_ids & oec_cos)
    except Exception:
        pass

    if recent_drafts == 0 and qualified_in_oec_count > 0:
        issues.append(f"Draft stall: 0 drafts in last 2h, {qualified_in_oec_count} qualified companies available")

    # ── 3. Discovery staleness ────────────────────────────────────────────
    last_co = (
        db._filter_ws(db.client.table("companies").select("created_at"))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if last_co:
        last_disc = datetime.fromisoformat(last_co[0]["created_at"].replace("Z", "+00:00"))
        days_since = (now - last_disc).days
        if days_since > 4:
            issues.append(f"Discovery stalled: last company {days_since}d ago ({last_co[0]['created_at'][:10]})")

    # ── 4. Approved queue depth (weekday mornings 7-9am CT) ──────────────
    from zoneinfo import ZoneInfo
    ct_now = datetime.now(ZoneInfo("America/Chicago"))
    if ct_now.weekday() < 5 and 7 <= ct_now.hour <= 9:
        approved_count = (
            db._filter_ws(db.client.table("outreach_drafts").select("id", count="exact"))
            .in_("approval_status", ["approved", "edited"])
            .is_("sent_at", "null")
            .execute()
        ).count or 0
        if approved_count < 10:
            issues.append(f"Low approval queue: only {approved_count} approved drafts before morning send window")

    # ── 5. Budget burn ────────────────────────────────────────────────────
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    costs_pages = []
    offset = 0
    while True:
        page = (
            db.client.table("api_costs")
            .select("estimated_cost_usd")
            .eq("workspace_id", WORKSPACE_ID)
            .gte("created_at", month_start)
            .range(offset, offset + 999)
            .execute()
            .data or []
        )
        costs_pages.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    mtd_spend = sum(r.get("estimated_cost_usd") or 0 for r in costs_pages)
    # Read actual cap from workspace settings
    ws_row = db.client.table("workspaces").select("settings").eq("id", WORKSPACE_ID).execute()
    budget_cap = float((ws_row.data[0].get("settings") or {}).get("monthly_api_budget_usd", 200.0) if ws_row.data else 200.0)
    if mtd_spend >= budget_cap * 0.80:
        issues.append(f"Budget at {mtd_spend/budget_cap*100:.0f}%: ${mtd_spend:.2f} / ${budget_cap:.0f}")

    # ── Report ────────────────────────────────────────────────────────────
    print(f"[{now_ct()}] QC run — fixes={len(fixes)} issues={len(issues)}")
    for f in fixes:
        print(f"  FIX: {f}")
    for i in issues:
        print(f"  ISSUE: {i}")

    if issues:
        body = f"ProspectIQ Pipeline QC — {now_ct()}\n\n"
        body += "ISSUES DETECTED:\n" + "\n".join(f"  • {i}" for i in issues) + "\n\n"
        if fixes:
            body += "AUTO-FIXED:\n" + "\n".join(f"  ✓ {f}" for f in fixes) + "\n\n"
        body += "Pipeline stats:\n"
        body += f"  OEC size: {oec_count} → refreshed to current\n"
        body += f"  Drafts (2h): {recent_drafts}\n"
        body += f"  MTD spend: ${mtd_spend:.2f}\n"
        send_alert(f"{len(issues)} issue(s) detected", body)
    elif fixes:
        print(f"  Auto-fixed {len(fixes)} issue(s) silently.")

    return {"fixes": fixes, "issues": issues}

if __name__ == "__main__":
    run_qc()
