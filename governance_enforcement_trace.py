"""Governance Enforcement Trace — per-send coverage for the last 30 days.

Queries send_assertions to show which sent drafts had authoritative send_path
assertion coverage and which did not. Run at any time for a governance audit.

Usage:
    python governance_enforcement_trace.py [--days 30] [--csv]

Output:
    - Coverage summary (send_path vs draft_gen vs uncovered)
    - Per-contact breakdown
    - Any assertion failures at send_path context
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
    sys.exit(1)


def main(days: int = 30, csv_mode: bool = False) -> None:
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Fetch all sent drafts in window
    sent_result = (
        client.table("outreach_drafts")
        .select("id, contact_id, company_id, sent_at, sequence_step, subject")
        .not_.is_("sent_at", "null")
        .gte("sent_at", cutoff)
        .execute()
    )
    sent_drafts = sent_result.data or []
    total_sends = len(sent_drafts)

    if total_sends == 0:
        print(f"No sent drafts in the last {days} days.")
        return

    # Fetch all send_path assertions in window
    sa_result = (
        client.table("send_assertions")
        .select("contact_id, assertion_context, passed, assertion, evaluated_at")
        .eq("assertion_context", "send_path")
        .gte("evaluated_at", cutoff)
        .execute()
    )
    sp_records = sa_result.data or []

    # Build set of contact_ids with at least one send_path assertion
    sp_contact_ids: set[str] = set()
    sp_failures: list[dict] = []
    for r in sp_records:
        cid = r.get("contact_id")
        if cid:
            sp_contact_ids.add(cid)
        if not r.get("passed"):
            sp_failures.append(r)

    # Compute coverage per sent draft
    covered = 0
    uncovered = 0
    uncovered_list: list[dict] = []

    for draft in sent_drafts:
        cid = draft.get("contact_id")
        if cid and cid in sp_contact_ids:
            covered += 1
        else:
            uncovered += 1
            uncovered_list.append(draft)

    coverage_pct = (covered / total_sends * 100) if total_sends > 0 else 0

    # Summary
    print("=" * 65)
    print(f"GOVERNANCE ENFORCEMENT TRACE — last {days} days")
    print(f"  Window: {cutoff[:10]} → today")
    print("=" * 65)
    print(f"  Total sent drafts (window):      {total_sends:>6}")
    print(f"  Covered by send_path assertions: {covered:>6}  ({coverage_pct:.1f}%)")
    print(f"  NOT covered (no send_path):      {uncovered:>6}  ({100-coverage_pct:.1f}%)")
    print(f"  send_path assertion failures:    {len(sp_failures):>6}")
    print()

    if sp_failures:
        print("  SEND-PATH ASSERTION FAILURES:")
        for f in sp_failures:
            print(f"    contact={f.get('contact_id','')[:8]} assertion={f.get('assertion')} evaluated_at={f.get('evaluated_at','')[:19]}")
        print()

    if uncovered_list:
        print(f"  UNCOVERED SENDS (no send_path assertion — first 20 of {len(uncovered_list)}):")
        if csv_mode:
            print("  draft_id,contact_id,company_id,sent_at,sequence_step")
        for d in uncovered_list[:20]:
            if csv_mode:
                print(f"  {d.get('id','')},{d.get('contact_id','')},{d.get('company_id','')},{d.get('sent_at','')[:19]},{d.get('sequence_step','')}")
            else:
                print(f"    draft_id={d.get('id','')[:8]} contact={d.get('contact_id','')[:8]} sent_at={d.get('sent_at','')[:19]} step={d.get('sequence_step','')}")

    # Draft-gen context summary for reference
    dg_result = (
        client.table("send_assertions")
        .select("assertion_context", count="exact")
        .eq("assertion_context", "draft_gen")
        .gte("evaluated_at", cutoff)
        .execute()
    )
    dg_count = dg_result.count or 0
    print()
    print(f"  Advisory draft_gen assertions (window): {dg_count}")
    print()
    print("  Governance status: ", end="")
    if coverage_pct >= 95:
        print("HEALTHY (>= 95% coverage)")
    elif coverage_pct >= 50:
        print(f"DEGRADED ({coverage_pct:.1f}% coverage — review uncovered sends)")
    else:
        print(f"CRITICAL ({coverage_pct:.1f}% coverage — most sends lack authoritative governance)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show per-send governance coverage")
    parser.add_argument("--days", type=int, default=30, help="Look-back window in days (default 30)")
    parser.add_argument("--csv", action="store_true", help="Emit uncovered sends as CSV")
    args = parser.parse_args()
    main(days=args.days, csv_mode=args.csv)
