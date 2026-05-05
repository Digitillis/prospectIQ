"""Backfill engagement_sequences for contacts whose step-1 email was sent
but never got a sequence record (the record creation was added retroactively).

What this does:
  1. Pulls all outreach_drafts where sequence_step=1, sent_at IS NOT NULL
  2. Checks if an engagement_sequences row exists for that contact_id
  3. If not, creates one with current_step=1, next_action_at = sent_at + 5 days
     (step 2 delay from email_value_first sequence)

Run dry-run first (default), then pass --execute to commit changes.

Usage:
  python scripts/backfill_orphaned_sequences.py
  python scripts/backfill_orphaned_sequences.py --execute
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.core.database import Database
from backend.app.core.config import get_settings

STEP2_DELAY_DAYS = 5        # delay_days for step 2 in email_value_first
TOTAL_STEPS = 4             # email_value_first has 4 steps
SEQUENCE_NAME = "email_value_first"
WORKSPACE_ID = get_settings().default_workspace_id


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime (UTC)."""
    s = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except ValueError:
        # Fallback: strip timezone info and assume UTC
        return datetime.fromisoformat(s[:19]).replace(tzinfo=timezone.utc)


def main(execute: bool = False) -> None:
    db = Database()  # no workspace_id — pipeline-level access

    print("=== Orphaned Sequence Backfill ===")
    print(f"Mode: {'EXECUTE' if execute else 'DRY RUN'}\n")

    # Step 1: Pull all sent step-1 drafts (paginate to handle >1000 rows)
    print("Fetching sent step-1 drafts...")
    all_step1 = []
    page_size = 1000
    offset = 0
    while True:
        page = (
            db.client.table("outreach_drafts")
            .select("id, contact_id, company_id, sequence_name, sent_at, workspace_id")
            .eq("sequence_step", 1)
            .not_.is_("sent_at", "null")
            .order("sent_at")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = page.data or []
        all_step1.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    print(f"  Found {len(all_step1)} sent step-1 drafts\n")

    if not all_step1:
        print("Nothing to backfill.")
        return

    # Step 2: Pull all existing engagement_sequence contact_ids
    print("Fetching existing engagement sequence records...")
    seqs_result = (
        db.client.table("engagement_sequences")
        .select("contact_id, status")
        .execute()
    )
    existing_contacts = {r["contact_id"] for r in (seqs_result.data or [])}
    print(f"  {len(existing_contacts)} contacts already have sequence records\n")

    # Step 3: Find orphans
    orphans = [d for d in all_step1 if d["contact_id"] not in existing_contacts]
    print(f"Orphaned contacts (sent step 1, no sequence record): {len(orphans)}\n")

    if not orphans:
        print("No orphans found — nothing to backfill.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    created = 0
    skipped = 0

    for draft in orphans:
        contact_id = draft["contact_id"]
        company_id = draft["company_id"]
        sent_at_str = draft["sent_at"]
        ws_id = draft.get("workspace_id") or WORKSPACE_ID
        seq_name = draft.get("sequence_name") or SEQUENCE_NAME

        # Compute next_action_at: sent_at + 5 days
        try:
            sent_dt = _parse_ts(sent_at_str)
        except Exception as e:
            print(f"  SKIP {contact_id}: bad sent_at '{sent_at_str}' — {e}")
            skipped += 1
            continue

        next_action_dt = sent_dt + timedelta(days=STEP2_DELAY_DAYS)
        next_action_at = next_action_dt.isoformat()
        overdue = next_action_dt < datetime.now(timezone.utc)

        status_label = "OVERDUE" if overdue else "future"
        print(
            f"  [{status_label}] contact={contact_id} company={company_id} "
            f"sent={sent_at_str[:10]} next_step2={next_action_at[:10]}"
        )

        if execute:
            try:
                db.client.table("engagement_sequences").insert({
                    "contact_id": contact_id,
                    "company_id": company_id,
                    "sequence_name": seq_name,
                    "current_step": 1,
                    "total_steps": TOTAL_STEPS,
                    "status": "active",
                    "next_action_at": next_action_at,
                    "next_action_type": "send_email",
                    "started_at": sent_at_str,
                    "workspace_id": ws_id,
                }).execute()
                created += 1
            except Exception as e:
                print(f"    ERROR inserting sequence for {contact_id}: {e}")
                skipped += 1

    print(f"\n=== Summary ===")
    print(f"  Total orphans found : {len(orphans)}")
    if execute:
        print(f"  Sequences created   : {created}")
        print(f"  Skipped (errors)    : {skipped}")
        overdue_count = sum(
            1 for d in orphans
            if _parse_ts(d["sent_at"]) + timedelta(days=STEP2_DELAY_DAYS) < datetime.now(timezone.utc)
        )
        print(f"  Overdue (due now)   : {overdue_count}")
        print("\nDone. Run EngagementAgent process_due to generate step-2 drafts for overdue contacts.")
    else:
        overdue_count = sum(
            1 for d in orphans
            if _parse_ts(d["sent_at"]) + timedelta(days=STEP2_DELAY_DAYS) < datetime.now(timezone.utc)
        )
        print(f"  Would create        : {len(orphans) - skipped}")
        print(f"  Would be overdue    : {overdue_count}")
        print("\nRun with --execute to commit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Commit changes (default: dry run)")
    args = parser.parse_args()
    main(execute=args.execute)
