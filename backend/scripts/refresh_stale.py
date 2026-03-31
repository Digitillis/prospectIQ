"""Stale contact detection and re-enrichment scheduler.

Marks contacts as stale if enriched_at is older than N days,
then queues them for re-enrichment via the bulk match pipeline.

Usage:
    python -m backend.scripts.refresh_stale --dry-run
    python -m backend.scripts.refresh_stale --stale-days 90 --limit 50
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone

from rich.console import Console
from rich.table import Table

from backend.app.core.bulk_enrich import BulkEnrichmentJob
from backend.app.core.database import Database

console = Console()
logger = logging.getLogger(__name__)


def mark_stale_contacts(db: Database, stale_days: int, dry_run: bool = False) -> list[dict]:
    """Mark contacts as stale if enriched_at is older than stale_days."""
    stale = db.get_stale_contacts(stale_days=stale_days, limit=1000)

    if not stale:
        console.print(f"[green]No contacts stale after {stale_days} days.[/green]")
        return []

    console.print(f"[cyan]{len(stale)} contacts are stale (enriched > {stale_days} days ago)[/cyan]")

    if dry_run:
        for c in stale[:10]:
            name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or "?"
            enriched_at = c.get("enriched_at", "unknown")
            console.print(f"  [DRY-RUN] Would mark stale: {name} (enriched: {enriched_at})")
        if len(stale) > 10:
            console.print(f"  ... and {len(stale) - 10} more")
        return stale

    stale_ids = [c["id"] for c in stale]
    marked = db.mark_contacts_stale(stale_ids)
    console.print(f"[yellow]Marked {marked} contacts as stale[/yellow]")
    return stale


def print_stale_summary(stale: list[dict]) -> None:
    """Print a summary table of stale contacts."""
    if not stale:
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Contact", min_width=24)
    table.add_column("Title", min_width=28)
    table.add_column("Company", min_width=22)
    table.add_column("Enriched At", min_width=12)
    table.add_column("Score", justify="center", min_width=6)

    db = Database()
    for c in stale[:25]:
        name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or "?"
        enriched_at = c.get("enriched_at", "")
        if enriched_at:
            try:
                enriched_at = enriched_at[:10]
            except Exception:
                pass

        # Get company name
        company_id = c.get("company_id")
        company_name = "?"
        if company_id:
            result = db.client.table("companies").select("name").eq("id", company_id).execute()
            if result.data:
                company_name = result.data[0]["name"][:22]

        score = c.get("completeness_score") or 0
        score_str = f"[green]{score}[/green]" if score >= 60 else f"[yellow]{score}[/yellow]"

        table.add_row(
            name[:24],
            (c.get("title") or "—")[:28],
            company_name,
            enriched_at or "—",
            score_str,
        )

    console.print(table)
    if len(stale) > 25:
        console.print(f"[dim]... and {len(stale) - 25} more[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark stale contacts and re-enrich via Apollo")
    parser.add_argument("--stale-days", type=int, default=90, help="Days before contact is considered stale (default: 90)")
    parser.add_argument("--limit", type=int, default=100, help="Max contacts to re-enrich in one run (default: 100)")
    parser.add_argument("--campaign", help="Filter by campaign name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument("--mark-only", action="store_true", help="Mark stale but skip re-enrichment")
    args = parser.parse_args()

    console.print(f"\n[bold]Stale Contact Refresh[/bold]")
    console.print(f"Stale threshold: [cyan]{args.stale_days} days[/cyan]")
    if args.dry_run:
        console.print("[yellow]DRY-RUN mode — no changes will be made[/yellow]")

    db = Database()

    # Step 1: Mark stale contacts
    stale = mark_stale_contacts(db, stale_days=args.stale_days, dry_run=args.dry_run)

    if stale:
        print_stale_summary(stale)

    if args.mark_only or args.dry_run:
        if args.mark_only:
            console.print("\n[dim]--mark-only: skipping re-enrichment[/dim]")
        return

    if not stale:
        return

    # Step 2: Re-enrich via bulk match
    console.print(f"\n[bold]Starting re-enrichment for up to {args.limit} contacts...[/bold]")
    job = BulkEnrichmentJob(campaign_name=args.campaign, stale_days=args.stale_days)
    run = job.run(dry_run=False, limit=args.limit)

    console.print(
        f"\n[bold]Refresh complete:[/bold] "
        f"{run.matched} re-enriched, {run.failed} failed, "
        f"{run.credits_used} Apollo credits used"
    )


if __name__ == "__main__":
    main()
