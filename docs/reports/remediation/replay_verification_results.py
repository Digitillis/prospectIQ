"""Phase 1 — ZeroBounce Replay Script (dry-run by default).

Identifies the contacts that still have null email_status and would be
submitted to ZeroBounce in the next verification pass. Does NOT call the
ZeroBounce API unless --execute is passed.

Usage:
    # Dry run: show what would be submitted
    python3 docs/reports/remediation/replay_verification_results.py

    # Live run: actually call ZeroBounce API and write results
    python3 docs/reports/remediation/replay_verification_results.py --execute

Output in dry-run:
    - Count of contacts to be verified
    - Estimated credit cost
    - First 20 emails that would be submitted
"""

import os
import sys
import argparse
import requests
from collections import Counter
from datetime import datetime, timezone

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_KEY)

BATCH_SIZE = 200
COST_PER_CREDIT = 0.008

STATUS_MAP = {
    "valid": "verified",
    "invalid": "invalid",
    "catch-all": "catch_all",
    "unknown": "unverified",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}


def fetch_null_status_contacts():
    """Return all contacts with email but null email_status."""
    rows = []
    offset = 0
    while True:
        r = (
            client.table("contacts")
            .select("id,email,full_name")
            .not_.is_("email", "null")
            .neq("email", "")
            .is_("email_status", "null")
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


def check_zb_credits(api_key: str) -> int:
    """Return available ZeroBounce credits."""
    r = requests.get(
        "https://api.zerobounce.net/v2/getcredits",
        params={"api_key": api_key},
        timeout=10,
    )
    r.raise_for_status()
    return int(r.json().get("Credits", 0))


def run_batch(api_key: str, contacts: list, dry_run: bool) -> dict:
    """Process one batch of up to BATCH_SIZE contacts. Returns counts."""
    counts = Counter()

    if dry_run:
        print(f"  [DRY RUN] Would submit {len(contacts)} contacts to ZeroBounce API")
        for c in contacts[:5]:
            print(f"    {c['email']}")
        if len(contacts) > 5:
            print(f"    ... and {len(contacts) - 5} more")
        return counts

    email_list = [{"email_address": c["email"], "ip_address": ""} for c in contacts]
    try:
        resp = requests.post(
            "https://api.zerobounce.net/v2/validatebatch",
            json={"api_key": api_key, "email_batch": email_list},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  API error: {e}")
        counts["errors"] += len(contacts)
        return counts

    results = data.get("email_batch", [])
    contact_by_email = {c["email"].lower(): c for c in contacts}

    for r in results:
        email = (r.get("address") or "").lower()
        zb_status = (r.get("status") or "unknown").lower()
        new_status = STATUS_MAP.get(zb_status, "unverified")

        contact = contact_by_email.get(email)
        if not contact:
            counts["unmatched"] += 1
            continue

        try:
            client.table("contacts").update({
                "email_status": new_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", contact["id"]).execute()
            counts[new_status] += 1
        except Exception as e:
            print(f"  Write error for {email}: {e}")
            counts["write_errors"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(description="ZeroBounce replay verification")
    parser.add_argument("--execute", action="store_true",
                        help="Actually call ZeroBounce API and write results (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.execute

    print("=" * 70)
    print(f"ZEROBOUNCE REPLAY {'(DRY RUN)' if dry_run else '(LIVE - WRITING TO DB)'}")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M CDT')}")
    print("=" * 70)

    contacts = fetch_null_status_contacts()
    print(f"\nContacts with null email_status: {len(contacts)}")
    print(f"Estimated cost: ${len(contacts) * COST_PER_CREDIT:.2f} ({len(contacts)} credits at $0.008/credit)")

    if not contacts:
        print("No contacts to verify — all caught up!")
        return

    api_key = os.environ.get("ZEROBOUNCE_API_KEY", "")
    if not api_key:
        # Try via settings
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
            from backend.app.core.config import get_settings
            api_key = get_settings().zerobounce_api_key
        except Exception:
            pass

    if not api_key:
        print("\nERROR: ZEROBOUNCE_API_KEY not set — cannot check credits or run live")
        if dry_run:
            print("\nDRY RUN OUTPUT:")
            print(f"  Would submit {len(contacts)} contacts in {len(contacts) // BATCH_SIZE + 1} batches")
            print("  First 20 emails:")
            for c in contacts[:20]:
                print(f"    {c.get('email', '?')}")
            return
        sys.exit(1)

    if not dry_run:
        credits = check_zb_credits(api_key)
        print(f"ZeroBounce credits available: {credits}")
        if credits < len(contacts):
            print(f"WARNING: Only {credits} credits available for {len(contacts)} contacts")
            print(f"         Will process first {credits} contacts only")
            contacts = contacts[:credits]

    total_counts = Counter()

    for batch_start in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[batch_start:batch_start + BATCH_SIZE]
        print(f"\nBatch {batch_start // BATCH_SIZE + 1}: contacts {batch_start+1}-{batch_start+len(batch)}")
        counts = run_batch(api_key, batch, dry_run)
        total_counts.update(counts)

    print("\n" + "=" * 70)
    if dry_run:
        print(f"DRY RUN COMPLETE — {len(contacts)} contacts identified, no changes made")
        print(f"Estimated cost to run live: ${len(contacts) * COST_PER_CREDIT:.2f}")
        print("\nTo execute: python3 replay_verification_results.py --execute")
    else:
        print("LIVE RUN COMPLETE")
        print(f"  verified:    {total_counts['verified']}")
        print(f"  catch_all:   {total_counts['catch_all']}")
        print(f"  invalid:     {total_counts['invalid']}")
        print(f"  unverified:  {total_counts['unverified']}")
        print(f"  write_errors:{total_counts['write_errors']}")
        print(f"  sendable:    {total_counts['verified'] + total_counts['catch_all']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
