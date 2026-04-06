"""One-time cleanup: remove duplicate outreach_drafts rows.

A duplicate is defined as multiple rows sharing the same
(company_id, contact_id, sequence_step) where at least one is still pending.

Rules applied in order:
  1. If a 'sent' row exists for a (contact, step) → delete ALL 'pending' rows for that pair.
     (Contact already received this step — pending drafts are stale.)
  2. If multiple 'pending' rows exist for the same (contact, step) →
     keep the most recently created one, delete the rest.

Run once after deploying:
    python backend/scripts/dedup_drafts.py

Pass --dry-run to preview without deleting.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rich.console import Console
from rich.table import Table

from backend.app.core.config import get_settings
from supabase import create_client

console = Console()
logger = logging.getLogger(__name__)


def main(dry_run: bool = False) -> None:
    if dry_run:
        console.print("[bold yellow]DRY RUN — no deletes will be executed[/bold yellow]")
    else:
        console.print("[bold red]LIVE RUN — duplicates will be deleted[/bold red]")

    settings = get_settings()
    db = create_client(settings.supabase_url, settings.supabase_service_key)

    # Fetch all non-rejected drafts so we can find duplicates across all statuses
    console.print("\nFetching all non-rejected drafts...")
    result = (
        db.table("outreach_drafts")
        .select("id, company_id, contact_id, sequence_step, approval_status, created_at, subject")
        .neq("approval_status", "rejected")
        .order("created_at", desc=True)
        .execute()
    )
    all_drafts = result.data or []
    console.print(f"Total drafts fetched: {len(all_drafts)}")

    # Group by (contact_id, sequence_step)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for d in all_drafts:
        key = (d["contact_id"], d["sequence_step"])
        groups[key].append(d)

    # Identify what to delete
    to_delete: list[str] = []           # draft IDs to delete
    reasons: dict[str, str] = {}        # id -> human reason

    for (contact_id, step), drafts in groups.items():
        if len(drafts) <= 1:
            continue  # no duplicate

        sent = [d for d in drafts if d["approval_status"] == "sent"]
        pending = [d for d in drafts if d["approval_status"] == "pending"]
        others = [d for d in drafts if d["approval_status"] not in ("sent", "pending")]

        # Rule 1: already sent → all pending are stale
        if sent:
            for d in pending:
                to_delete.append(d["id"])
                reasons[d["id"]] = f"stale (step {step} already sent for this contact)"
            # Also delete duplicate sent rows (keep newest)
            if len(sent) > 1:
                sent_sorted = sorted(sent, key=lambda x: x["created_at"], reverse=True)
                for d in sent_sorted[1:]:
                    to_delete.append(d["id"])
                    reasons[d["id"]] = f"duplicate sent row (step {step}), keeping newest"
            continue

        # Rule 2: multiple pending → keep newest, delete rest
        if len(pending) > 1:
            pending_sorted = sorted(pending, key=lambda x: x["created_at"], reverse=True)
            for d in pending_sorted[1:]:  # skip [0] = newest
                to_delete.append(d["id"])
                reasons[d["id"]] = f"duplicate pending (step {step}), keeping newest"

        # Rule 3: approved/edited + pending → pending is stale
        approved = [d for d in others if d["approval_status"] in ("approved", "edited")]
        if approved:
            for d in pending:
                if d["id"] not in to_delete:
                    to_delete.append(d["id"])
                    reasons[d["id"]] = f"stale pending (step {step} already approved/edited)"

    if not to_delete:
        console.print("\n[green]No duplicates found. Database is clean.[/green]")
        return

    # Print summary table
    table = Table(title=f"Duplicates to Delete ({len(to_delete)} rows)", show_lines=False)
    table.add_column("Draft ID", style="dim", width=36)
    table.add_column("Step", width=5)
    table.add_column("Status", width=10)
    table.add_column("Subject (truncated)", width=50)
    table.add_column("Reason", width=50)

    id_to_draft = {d["id"]: d for d in all_drafts}
    for did in to_delete:
        d = id_to_draft.get(did, {})
        table.add_row(
            did,
            str(d.get("sequence_step", "?")),
            d.get("approval_status", "?"),
            (d.get("subject") or "")[:50],
            reasons.get(did, ""),
        )

    console.print(table)
    console.print(f"\n[bold]Will delete {len(to_delete)} duplicate rows.[/bold]")

    if dry_run:
        console.print("\n[yellow]Dry run complete. Re-run without --dry-run to apply.[/yellow]")
        return

    # Execute deletes in batches of 50
    deleted = 0
    errors = 0
    batch_size = 50
    for i in range(0, len(to_delete), batch_size):
        batch = to_delete[i : i + batch_size]
        try:
            db.table("outreach_drafts").delete().in_("id", batch).execute()
            deleted += len(batch)
        except Exception as e:
            logger.error(f"Delete batch failed: {e}")
            errors += len(batch)

    console.print(f"\n[bold]Done:[/bold] {deleted} deleted, {errors} errors")
    if errors == 0:
        console.print("[green]Database is now clean.[/green]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate outreach_drafts table")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no deletes")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
