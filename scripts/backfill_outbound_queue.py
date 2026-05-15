"""One-time backfill: insert pre-PR F approved drafts into outbound_queue.

Usage:
    python scripts/backfill_outbound_queue.py           # dry-run (default, safe)
    python scripts/backfill_outbound_queue.py --execute  # actually insert rows

Targets drafts that:
  - approval_status IN ('approved', 'edited')
  - sent_at IS NULL
  - have NO existing outbound_queue row (ON CONFLICT DO NOTHING handles races)

These drafts were approved before PR F deployed approve_draft_and_enqueue().
Without this script, the dispatch loop (PR G) will never see them because it
reads outbound_queue exclusively.

IMPORTANT:
  - This script is NOT run automatically on deploy.
  - It must be reviewed and run manually by Avanish after PR G merges and
    before SEND_ENABLED is set to true.
  - Default mode is dry-run — pass --execute to write rows.
  - A confirmation prompt is shown before execution even with --execute.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone


def _get_client():
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL") or os.environ.get("DATABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        sys.exit(
            "ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment. "
            "Do not hardcode credentials."
        )
    return create_client(url, key)


def _find_eligible_drafts(client) -> list[dict]:
    """Return approved/edited drafts with sent_at IS NULL."""
    rows = (
        client.table("outreach_drafts")
        .select("id, workspace_id, approval_status, created_at")
        .in_("approval_status", ["approved", "edited"])
        .is_("sent_at", "null")
        .order("created_at")
        .execute()
        .data or []
    )
    return rows


def _find_already_queued(client, draft_ids: list[str]) -> set[str]:
    """Return draft_ids that already have an outbound_queue row."""
    if not draft_ids:
        return set()
    rows = (
        client.table("outbound_queue")
        .select("draft_id")
        .in_("draft_id", draft_ids)
        .execute()
        .data or []
    )
    return {r["draft_id"] for r in rows}


def run(execute: bool = False) -> None:
    client = _get_client()

    print("Scanning outreach_drafts for pre-PR F approved drafts with sent_at IS NULL...")
    eligible = _find_eligible_drafts(client)

    if not eligible:
        print("No eligible drafts found. Nothing to backfill.")
        return

    draft_ids = [d["id"] for d in eligible]
    already_queued = _find_already_queued(client, draft_ids)
    to_insert = [d for d in eligible if d["id"] not in already_queued]

    print(f"\nEligible drafts:     {len(eligible)}")
    print(f"Already in queue:    {len(already_queued)}")
    print(f"To insert:           {len(to_insert)}")

    if not to_insert:
        print("\nAll eligible drafts are already in outbound_queue. Nothing to do.")
        return

    print("\nDraft IDs to backfill:")
    for d in to_insert:
        print(f"  {d['id']}  workspace={d['workspace_id']}  status={d['approval_status']}  created={d['created_at']}")

    if not execute:
        print(
            "\nDRY-RUN MODE: No rows written. "
            "Pass --execute to insert these rows after reviewing the list above."
        )
        return

    confirm = input(
        f"\nAbout to insert {len(to_insert)} row(s) into outbound_queue. "
        "Type 'yes' to proceed: "
    ).strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    rows_to_insert = [
        {
            "draft_id": d["id"],
            "workspace_id": d["workspace_id"],
            "priority": 5,
        }
        for d in to_insert
    ]

    inserted = 0
    skipped = 0
    for row in rows_to_insert:
        try:
            result = (
                client.table("outbound_queue")
                .insert(row, count="exact")
                .execute()
            )
            if result.data:
                inserted += 1
            else:
                skipped += 1
        except Exception as exc:
            err_str = str(exc).lower()
            if "duplicate" in err_str or "unique" in err_str or "conflict" in err_str:
                skipped += 1
            else:
                print(f"  ERROR inserting draft_id={row['draft_id']}: {exc}")
                skipped += 1

    print(f"\nBackfill complete: inserted={inserted} skipped={skipped}")
    print("Review outbound_queue to confirm rows are present before enabling SEND_ENABLED.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually insert rows (default is dry-run)",
    )
    args = parser.parse_args()
    run(execute=args.execute)
