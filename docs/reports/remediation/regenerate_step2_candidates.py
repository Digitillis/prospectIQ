"""Phase 3 — Step-2 Candidate Identification Script (dry-run).

Identifies contacts eligible for step-2 draft generation:
- Step-1 sent (sent_at IS NOT NULL, sequence_step = 1)
- No step-2 draft in ANY state (pending/approved/rejected/sent)
- email_status IN ('verified', 'catch_all')
- contact.status NOT IN ('bounced', 'unsubscribed', 'not_interested')
- Not in suppression_log
- Minimum step gap elapsed (step-1 sent_at > MIN_STEP_GAP_DAYS ago)

Does NOT generate drafts. Outputs the list of eligible contact IDs for
review. Pass --export to write a CSV for inspection.

Usage:
    python3 docs/reports/remediation/regenerate_step2_candidates.py
    python3 docs/reports/remediation/regenerate_step2_candidates.py --export eligible_step2.csv
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone, timedelta

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")
MIN_STEP_GAP_DAYS = 5  # Must match pre_send_assertions.py

BLOCKED_STATUSES = {"bounced", "unsubscribed", "not_interested"}
SENDABLE_STATUSES = {"verified", "catch_all"}


def fetch_all(table, cols, range_start=0):
    """Paginate through full table."""
    rows = []
    offset = range_start
    while True:
        r = (
            create_client(SUPABASE_URL, SUPABASE_KEY)
            .table(table)
            .select(cols)
            .range(offset, offset + 999)
            .execute()
        )
        if not r.data:
            break
        rows.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", metavar="FILE", help="Export results to CSV")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("=" * 70)
    print("STEP-2 CANDIDATE IDENTIFICATION (DRY RUN)")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # 1. Get all sent step-1 drafts
    print("\n[1] Fetching sent step-1 drafts...")
    sent_drafts = []
    offset = 0
    while True:
        r = (
            client.table("outreach_drafts")
            .select("contact_id,sequence_step,sent_at,company_id")
            .not_.is_("sent_at", "null")
            .range(offset, offset + 999)
            .execute()
        )
        if not r.data:
            break
        sent_drafts.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000

    step1_sent = {d["contact_id"]: d for d in sent_drafts if d.get("sequence_step") == 1}
    step2_sent = {d["contact_id"] for d in sent_drafts if d.get("sequence_step") == 2}
    print(f"   Step-1 sent contacts: {len(step1_sent)}")

    # 2. Get all contacts with any step-2 draft
    print("[2] Fetching all step-2 drafts (any status)...")
    all_drafts = []
    offset = 0
    while True:
        r = (
            client.table("outreach_drafts")
            .select("contact_id,sequence_step,approval_status")
            .eq("sequence_step", 2)
            .range(offset, offset + 999)
            .execute()
        )
        if not r.data:
            break
        all_drafts.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000

    step2_any = {d["contact_id"] for d in all_drafts}
    truly_stalled = [cid for cid in step1_sent if cid not in step2_any]
    print(f"   Truly stalled (no step-2 draft): {len(truly_stalled)}")

    # 3. Fetch contact details for stalled contacts
    print("[3] Fetching contact details...")
    contacts_map = {}
    for i in range(0, len(truly_stalled), 100):
        batch = truly_stalled[i:i + 100]
        r = (
            client.table("contacts")
            .select("id,email,email_status,status,full_name,title,company_id")
            .in_("id", batch)
            .execute()
        )
        for c in (r.data or []):
            contacts_map[c["id"]] = c

    # 4. Check suppression_log
    print("[4] Checking suppression log...")
    suppressed_ids = set()
    stalled_ids = list(contacts_map.keys())
    for i in range(0, len(stalled_ids), 100):
        batch = stalled_ids[i:i + 100]
        r = (
            client.table("suppression_log")
            .select("contact_id")
            .in_("contact_id", batch)
            .execute()
        )
        suppressed_ids.update(s["contact_id"] for s in (r.data or []))

    # 5. Apply eligibility filters
    cutoff_gap = (datetime.now(timezone.utc) - timedelta(days=MIN_STEP_GAP_DAYS)).isoformat()

    eligible = []
    stats = {
        "null_status": 0,
        "bad_email": 0,
        "bounced": 0,
        "unsubscribed": 0,
        "suppressed": 0,
        "cooldown": 0,
        "eligible": 0,
    }

    for cid in truly_stalled:
        contact = contacts_map.get(cid)
        if not contact:
            continue

        email_status = contact.get("email_status")
        contact_status = contact.get("status", "")

        if not email_status:
            stats["null_status"] += 1
            continue
        if email_status not in SENDABLE_STATUSES:
            stats["bad_email"] += 1
            continue
        if contact_status in BLOCKED_STATUSES:
            stats["bounced" if contact_status == "bounced" else "unsubscribed"] += 1
            continue
        if cid in suppressed_ids:
            stats["suppressed"] += 1
            continue

        # Check cooldown
        step1 = step1_sent.get(cid, {})
        sent_at = step1.get("sent_at", "")
        if sent_at and sent_at > cutoff_gap:
            stats["cooldown"] += 1
            continue

        eligible.append({
            "contact_id": cid,
            "contact_name": contact.get("full_name", ""),
            "title": contact.get("title", ""),
            "email": contact.get("email", ""),
            "email_status": email_status,
            "company_id": contact.get("company_id", ""),
            "step1_sent_at": sent_at[:10] if sent_at else "",
        })
        stats["eligible"] += 1

    # Output
    print("\n" + "=" * 70)
    print("SEGMENTATION RESULTS")
    print(f"  Total truly stalled:           {len(truly_stalled)}")
    print(f"  Blocked — null email_status:   {stats['null_status']}")
    print(f"  Blocked — bad email status:    {stats['bad_email']}")
    print(f"  Blocked — bounced:             {stats['bounced']}")
    print(f"  Blocked — unsubscribed/NI:     {stats['unsubscribed']}")
    print(f"  Blocked — suppressed:          {stats['suppressed']}")
    print(f"  Blocked — cooldown (<{MIN_STEP_GAP_DAYS}d):       {stats['cooldown']}")
    print(f"  ELIGIBLE FOR STEP-2 NOW:       {stats['eligible']}")
    print("=" * 70)

    if eligible:
        print(f"\nFirst 20 eligible contacts:")
        for c in eligible[:20]:
            print(f"  {c['contact_id'][:12]} | {c['contact_name']:30s} | {c['email_status']:10s} | sent1={c['step1_sent_at']}")

    if args.export and eligible:
        with open(args.export, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=eligible[0].keys())
            writer.writeheader()
            writer.writerows(eligible)
        print(f"\nExported {len(eligible)} eligible contacts to: {args.export}")

    print(f"\nACTION: The {stats['eligible']} eligible contacts above should have")
    print("        step-2 drafts generated by the next _run_draft_generation tick.")
    print("        If they do not, investigate the draft_generation cron logic.")


if __name__ == "__main__":
    main()
