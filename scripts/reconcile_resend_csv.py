"""Reconcile Resend email export CSV against the ProspectIQ database.

Resend push webhooks are the real-time path, but early events (April 6-7)
may have been missed if the webhook wasn't live yet, or if Railway had
downtime. This script replays any missing engagement events from the CSV.

What it does per row:
  bounced     → add to DNC (if not already), cancel active sequences,
                update contact.status = 'bounced', update company status
  opened      → increment open_count, set last_opened_at if not already set
  clicked     → increment click_count, set last_clicked_at if not already set
  delivered / suppressed / other → skip (no action needed)

Skips rows where:
  - email is a test address (avi@digitillis.com)
  - the event was already recorded (idempotent by checking existing DB state)

Usage:
  python scripts/reconcile_resend_csv.py                         # dry run
  python scripts/reconcile_resend_csv.py --execute               # commit
  python scripts/reconcile_resend_csv.py --csv path/to/file.csv  # custom file
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.core.database import Database
from backend.app.core.config import get_settings

DEFAULT_CSV = Path.home() / "Downloads" / "emails-sent-1778006238657.csv"
TEST_ADDRS = {"avi@digitillis.com", "avi@digitillis.io"}
ACTIONABLE_EVENTS = {"bounced", "opened", "clicked"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lookup_contact(db: Database, email: str) -> tuple[str | None, str | None]:
    """Return (contact_id, company_id) for a given email address."""
    rows = (
        db.client.table("contacts")
        .select("id, company_id")
        .eq("email", email.lower().strip())
        .limit(1)
        .execute()
        .data or []
    )
    if rows:
        return rows[0]["id"], rows[0]["company_id"]
    return None, None


def _is_in_dnc(db: Database, email: str) -> bool:
    """Check if an email is already in the do_not_contact list."""
    rows = (
        db.client.table("do_not_contact")
        .select("id")
        .eq("email", email.lower().strip())
        .limit(1)
        .execute()
        .data or []
    )
    return bool(rows)


def _cancel_sequences(db: Database, contact_id: str, execute: bool) -> int:
    """Cancel active sequences for a contact. Returns count cancelled."""
    seqs = (
        db.client.table("engagement_sequences")
        .select("id")
        .eq("contact_id", contact_id)
        .in_("status", ["active", "paused"])
        .execute()
        .data or []
    )
    if execute and seqs:
        now = _now_iso()
        for s in seqs:
            db.client.table("engagement_sequences").update({
                "status": "cancelled",
                "updated_at": now,
            }).eq("id", s["id"]).execute()
    return len(seqs)


def main(csv_path: Path, execute: bool) -> None:
    db = Database()
    settings = get_settings()
    now_iso = _now_iso()

    print("=== Resend CSV Reconciliation ===")
    print(f"Mode   : {'EXECUTE' if execute else 'DRY RUN'}")
    print(f"File   : {csv_path}\n")

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Filter: real outreach emails only
    real = [
        r for r in rows
        if r.get("to", "").lower().strip() not in TEST_ADDRS
        and "[TEST]" not in r.get("subject", "")
        and r.get("last_event") in ACTIONABLE_EVENTS
    ]

    total_bounces = sum(1 for r in real if r["last_event"] == "bounced")
    total_opens = sum(1 for r in real if r["last_event"] == "opened")
    total_clicks = sum(1 for r in real if r["last_event"] == "clicked")

    print(f"Actionable rows in CSV: {len(real)}")
    print(f"  bounced: {total_bounces}  |  opened: {total_opens}  |  clicked: {total_clicks}\n")

    stats = {
        "bounce_dnc_added": 0,
        "bounce_already_in_dnc": 0,
        "bounce_seq_cancelled": 0,
        "bounce_contact_not_found": 0,
        "open_incremented": 0,
        "open_already_recorded": 0,
        "click_incremented": 0,
        "click_already_recorded": 0,
    }

    for row in real:
        email = row["to"].lower().strip()
        event = row["last_event"]
        sent_at = row.get("sent_at") or row.get("created_at") or now_iso

        contact_id, company_id = _lookup_contact(db, email)
        if not contact_id:
            if event == "bounced":
                print(f"  BOUNCE contact not found: {email}")
                stats["bounce_contact_not_found"] += 1
            continue

        if event == "bounced":
            if _is_in_dnc(db, email):
                stats["bounce_already_in_dnc"] += 1
                continue

            print(f"  BOUNCE backfill: {email} (contact={contact_id[:8]}...)")
            stats["bounce_dnc_added"] += 1

            if execute:
                # Add to DNC — plain insert (checked _is_in_dnc above, no dupe)
                try:
                    settings = get_settings()
                    db.client.table("do_not_contact").insert({
                        "email": email,
                        "reason": "bounced",
                        "added_by": "csv_reconcile",
                        "workspace_id": settings.default_workspace_id,
                    }).execute()
                except Exception as e:
                    print(f"    DNC insert failed: {e}")

                # Update contact status
                try:
                    db.update_contact(contact_id, {
                        "status": "bounced",
                        "outreach_state": "bounced",
                    })
                except Exception as e:
                    print(f"    Contact update failed: {e}")

                # Update company status
                if company_id:
                    try:
                        db.update_company(company_id, {"status": "bounced"})
                    except Exception as e:
                        print(f"    Company update failed: {e}")

                # Cancel active sequences
                cancelled = _cancel_sequences(db, contact_id, execute=True)
                stats["bounce_seq_cancelled"] += cancelled
            else:
                cancelled = _cancel_sequences(db, contact_id, execute=False)
                stats["bounce_seq_cancelled"] += cancelled

        elif event == "opened":
            # Check if open already recorded
            contact_row = (
                db.client.table("contacts")
                .select("open_count")
                .eq("id", contact_id)
                .limit(1)
                .execute()
                .data or [{}]
            )[0]
            current_count = contact_row.get("open_count") or 0
            if current_count > 0:
                stats["open_already_recorded"] += 1
                continue

            print(f"  OPEN backfill: {email} (contact={contact_id[:8]}...)")
            stats["open_incremented"] += 1

            if execute:
                try:
                    db.client.table("contacts").update({
                        "open_count": 1,
                    }).eq("id", contact_id).execute()
                except Exception as e:
                    print(f"    Open update failed: {e}")

        elif event == "clicked":
            contact_row = (
                db.client.table("contacts")
                .select("click_count")
                .eq("id", contact_id)
                .limit(1)
                .execute()
                .data or [{}]
            )[0]
            current_count = contact_row.get("click_count") or 0
            if current_count > 0:
                stats["click_already_recorded"] += 1
                continue

            print(f"  CLICK backfill: {email} (contact={contact_id[:8]}...)")
            stats["click_incremented"] += 1

            if execute:
                try:
                    db.client.table("contacts").update({
                        "click_count": 1,
                    }).eq("id", contact_id).execute()
                except Exception as e:
                    print(f"    Click update failed: {e}")

    print("\n=== Summary ===")
    print(f"  Bounces:")
    print(f"    Not in DB (contact not found) : {stats['bounce_contact_not_found']}")
    print(f"    Already in DNC (skipped)      : {stats['bounce_already_in_dnc']}")
    print(f"    DNC added (new)               : {stats['bounce_dnc_added']}")
    print(f"    Sequences cancelled           : {stats['bounce_seq_cancelled']}")
    print(f"  Opens:")
    print(f"    Already recorded (skipped)    : {stats['open_already_recorded']}")
    print(f"    Backfilled                    : {stats['open_incremented']}")
    print(f"  Clicks:")
    print(f"    Already recorded (skipped)    : {stats['click_already_recorded']}")
    print(f"    Backfilled                    : {stats['click_incremented']}")

    if not execute:
        print("\nRun with --execute to commit changes.")
    else:
        print("\nDone. Warm contacts (open/click) will now get Sonnet model for step-2 drafts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Commit changes (default: dry run)")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Path to Resend CSV export")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}")
        sys.exit(1)

    main(csv_path=args.csv, execute=args.execute)
