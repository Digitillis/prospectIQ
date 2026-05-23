"""Phase 4 — Bounce Rate Assertion Validation Script.

Validates the newly implemented assert_bounce_rate_ok() function by:
  1. Checking the current 7-day rolling bounce rate
  2. Showing whether the assertion would PASS or FAIL right now
  3. Showing the last 7 days of send and bounce activity

This script is READ-ONLY. No writes, no sends.

Usage:
    python3 docs/reports/remediation/bounce_rate_assertion.py
"""

import os
import sys
from datetime import datetime, timezone, timedelta

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")

MAX_BOUNCE_RATE = 0.02  # Must match pre_send_assertions.py


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    now = datetime.now(timezone.utc)
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    print("=" * 70)
    print("BOUNCE RATE ASSERTION VALIDATION")
    print(f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Window: last 7 days (since {cutoff_7d[:10]})")
    print("=" * 70)

    # 7-day counts
    sends_7d = client.table("interactions").select("id", count="exact").eq("type", "email_sent").gte("created_at", cutoff_7d).execute()
    bounces_7d = client.table("interactions").select("id", count="exact").eq("type", "email_bounced").gte("created_at", cutoff_7d).execute()

    send_count = sends_7d.count or 0
    bounce_count = bounces_7d.count or 0

    print(f"\n  7-day sends:   {send_count}")
    print(f"  7-day bounces: {bounce_count}")

    if send_count == 0:
        print("  7-day rate:    UNDEFINED (no sends in window)")
        print("\n  ASSERTION RESULT: PASS (no sends = rate undefined = passes)")
    else:
        rate = bounce_count / send_count
        print(f"  7-day rate:    {rate:.2%}")
        print(f"  Threshold:     {MAX_BOUNCE_RATE:.0%}")

        if rate > MAX_BOUNCE_RATE:
            print(f"\n  ASSERTION RESULT: FAIL — rate {rate:.2%} exceeds {MAX_BOUNCE_RATE:.0%}")
            print("  IMPACT: Thursday's send batch WILL be blocked by assert_bounce_rate_ok")
            print("  ACTION: Review recent bounces before enabling SEND_ENABLED")
        else:
            print(f"\n  ASSERTION RESULT: PASS — rate {rate:.2%} is within {MAX_BOUNCE_RATE:.0%} threshold")
            print("  IMPACT: Thursday's send batch will NOT be blocked by bounce rate gate")

    # All-time counts for context
    print("\n  --- ALL-TIME CONTEXT ---")
    sends_all = client.table("interactions").select("id", count="exact").eq("type", "email_sent").execute()
    bounces_all = client.table("interactions").select("id", count="exact").eq("type", "email_bounced").execute()
    all_rate = (bounces_all.count or 0) / max(sends_all.count or 1, 1)
    print(f"  All-time sends:   {sends_all.count or 0}")
    print(f"  All-time bounces: {bounces_all.count or 0}")
    print(f"  All-time rate:    {all_rate:.2%} (note: assertion uses 7-day window, not all-time)")

    # Recent bounce detail
    print("\n  --- RECENT BOUNCES (last 7 days) ---")
    recent_bounces = (
        client.table("interactions")
        .select("contact_id,company_id,created_at,subject")
        .eq("type", "email_bounced")
        .gte("created_at", cutoff_7d)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    if recent_bounces.data:
        for b in recent_bounces.data:
            print(f"    {b.get('created_at','?')[:10]} | contact={b.get('contact_id','?')[:12]} | subj={str(b.get('subject','?'))[:40]}")
    else:
        print("    No bounces in last 7 days")

    print("\n" + "=" * 70)
    print("Implementation location: backend/app/core/pre_send_assertions.py")
    print("Function: assert_bounce_rate_ok() — wired into run_pre_send_assertions()")
    print("Context: send_path only (not advisory draft_gen)")
    print("=" * 70)


if __name__ == "__main__":
    main()
