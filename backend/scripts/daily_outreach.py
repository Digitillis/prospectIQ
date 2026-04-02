"""Daily outreach operations runner.

Run this each morning to execute the full daily cycle:

    python -m backend.scripts.daily_outreach
    python -m backend.scripts.daily_outreach --campaign fsma_q1
    python -m backend.scripts.daily_outreach --dry-run
    python -m backend.scripts.daily_outreach --skip-intent --skip-push

Actions (in order):
    1. Scan intent signals (job postings via Apollo) for all pipeline companies
    2. Recompute priority scores for contacts with new intent data
    3. Print today's action queue (positive replies, demo follow-ups)
    4. Report stalled contacts needing human attention
    5. Push newly enriched contacts to Instantly sequences (up to daily limit)
    6. Print daily pipeline summary

Exit codes:
    0 — Completed successfully
    1 — Fatal error (check logs)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _header(step: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {step}: {title}[/bold cyan]")
    console.print(f"[dim]{'─' * 60}[/dim]")


def _run_intent_scan(db, campaign_name: str | None, dry_run: bool) -> dict:
    """Scan all pipeline companies for new buyer-signal job postings."""
    from backend.app.core.intent_engine import IntentEngine

    engine = IntentEngine(db)
    if dry_run:
        companies = db.get_companies_for_intent_scan(campaign_name=campaign_name)
        console.print(f"  [dim][DRY RUN] Would scan {len(companies)} companies[/dim]")
        return {"scanned": len(companies), "new_signals": 0, "companies_boosted": 0}

    result = engine.run_job_posting_scan(campaign_name=campaign_name)
    console.print(
        f"  Scanned [bold]{result['scanned']}[/bold] companies — "
        f"[green]{result['new_signals']} new signals[/green], "
        f"[yellow]{result['companies_boosted']} companies boosted[/yellow]"
    )
    return result


def _run_priority_score_update(campaign_name: str | None, dry_run: bool) -> int:
    """Recompute priority scores for all enriched contacts."""
    from backend.app.core.queue_manager import QueueManager

    qm = QueueManager(campaign_name=campaign_name)
    if dry_run:
        contacts = qm.db.client.table("contacts").select("id").eq("enrichment_status", "enriched").execute()
        count = len(contacts.data or [])
        console.print(f"  [dim][DRY RUN] Would update scores for {count} contacts[/dim]")
        return count

    updated = qm.update_priority_scores()
    console.print(f"  Priority scores updated for [bold]{updated}[/bold] contacts")
    return updated


async def _print_action_queue(db, coordinator, limit: int = 20) -> None:
    """Print contacts requiring human action today."""
    queue = await coordinator.get_action_queue(limit=limit)

    if not queue:
        console.print("  [green]No contacts require immediate human action[/green]")
        return

    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Company", min_width=24)
    table.add_column("Contact", min_width=20)
    table.add_column("State", min_width=18)
    table.add_column("Action Needed", min_width=36)

    for i, c in enumerate(queue, 1):
        company_name = (c.get("companies") or {}).get("name", "—")
        table.add_row(
            str(i),
            company_name[:24],
            (c.get("full_name") or "—")[:20],
            c.get("outreach_state", "—"),
            (c.get("action_reason") or "Review")[:36],
        )

    console.print(table)
    console.print(f"\n  [bold yellow]{len(queue)} contacts need your attention today[/bold yellow]")


async def _print_stalled_contacts(coordinator, days_stalled: int = 5) -> None:
    """Print contacts stuck without progression."""
    stalled = await coordinator.get_stalled_contacts(days_stalled=days_stalled)

    if not stalled:
        console.print(f"  [green]No contacts stalled for >{days_stalled} days[/green]")
        return

    table = Table(show_header=True, header_style="bold red")
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Company", min_width=24)
    table.add_column("Contact", min_width=20)
    table.add_column("State", min_width=18)
    table.add_column("Days Stalled", justify="center", min_width=12)

    for i, c in enumerate(stalled, 1):
        company_name = (c.get("companies") or {}).get("name", "—")
        days = c.get("days_stalled")
        days_str = (
            f"[red]{days}[/red]" if days and days >= 7 else
            f"[yellow]{days}[/yellow]" if days else "—"
        )
        table.add_row(
            str(i),
            company_name[:24],
            (c.get("full_name") or "—")[:20],
            c.get("outreach_state", "—"),
            days_str,
        )

    console.print(table)
    console.print(f"\n  [bold red]{len(stalled)} contacts stalled >{days_stalled} days[/bold red]")


def _run_sequence_push(campaign_name: str | None, limit: int, dry_run: bool) -> dict:
    """Push enriched contacts to Instantly sequences."""
    from backend.scripts.push_to_sequences import push_contacts_to_sequences

    result = push_contacts_to_sequences(
        campaign_name=campaign_name,
        limit=limit,
        dry_run=dry_run,
    )
    pushed = result.get("pushed", 0)
    skipped = result.get("skipped", 0)
    errors = result.get("errors", 0)

    status_color = "green" if not errors else "yellow"
    console.print(
        f"  [{status_color}]Pushed {pushed} contacts[/{status_color}] to sequences "
        f"({skipped} skipped, {errors} errors)"
    )
    return result


def _print_pipeline_summary(coordinator, campaign_name: str | None) -> None:
    """Print full pipeline summary."""
    summary = coordinator.get_outreach_summary(campaign_name=campaign_name)

    table = Table(show_header=True, header_style="bold green", title="Pipeline Summary")
    table.add_column("State", min_width=26)
    table.add_column("Count", justify="right", min_width=8)

    priority_states = [
        ("replied_positive", "[bold yellow]Replied (Positive)[/bold yellow]"),
        ("demo_scheduled",   "[bold green]Demo Scheduled[/bold green]"),
        ("total_active",     "[cyan]Active in Sequence[/cyan]"),
        ("nurture",          "[dim]Nurture[/dim]"),
        ("not_interested",   "[dim]Not Interested[/dim]"),
    ]
    shown: set[str] = set()

    for key, label in priority_states:
        count = summary.get(key, 0)
        table.add_row(label, str(count))
        shown.add(key)

    # Add remaining states
    for state, count in sorted(summary.items()):
        if state not in shown and not state.startswith("touch_") and count > 0:
            table.add_row(state.replace("_", " ").title(), str(count))

    console.print(table)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _async_main(args: argparse.Namespace) -> int:
    from backend.app.core.database import Database
    from backend.app.core.outreach_coordinator import OutreachCoordinator

    db = Database()
    coordinator = OutreachCoordinator(db)
    campaign = args.campaign or None

    now = datetime.now(timezone.utc)
    console.print(Panel(
        f"[bold]ProspectIQ — Daily Outreach Operations[/bold]\n"
        f"[dim]{now.strftime('%A, %B %-d %Y at %-I:%M %p UTC')}[/dim]"
        + (f"\n[yellow]Campaign: {campaign}[/yellow]" if campaign else "")
        + ("\n[bold red][DRY RUN][/bold red]" if args.dry_run else ""),
        border_style="blue",
    ))

    errors = 0

    # ------------------------------------------------------------------
    # Step 1: Intent signal scan
    # ------------------------------------------------------------------
    if not args.skip_intent:
        _header(1, "Intent Signal Scan (Job Postings)")
        try:
            _run_intent_scan(db, campaign, args.dry_run)
        except Exception as exc:
            console.print(f"  [red]Intent scan failed: {exc}[/red]")
            logger.exception("[daily] Intent scan failed")
            errors += 1
    else:
        console.print("\n[dim]Step 1: Intent scan skipped (--skip-intent)[/dim]")

    # ------------------------------------------------------------------
    # Step 2: Priority score recompute
    # ------------------------------------------------------------------
    _header(2, "Recompute Priority Scores")
    try:
        _run_priority_score_update(campaign, args.dry_run)
    except Exception as exc:
        console.print(f"  [red]Priority score update failed: {exc}[/red]")
        logger.exception("[daily] Priority score update failed")
        errors += 1

    # ------------------------------------------------------------------
    # Step 3: Action queue
    # ------------------------------------------------------------------
    _header(3, "Action Queue — Contacts Needing Human Attention")
    try:
        await _print_action_queue(db, coordinator, limit=args.action_limit)
    except Exception as exc:
        console.print(f"  [red]Action queue failed: {exc}[/red]")
        logger.exception("[daily] Action queue failed")
        errors += 1

    # ------------------------------------------------------------------
    # Step 4: Stalled contacts
    # ------------------------------------------------------------------
    _header(4, f"Stalled Contacts (>{args.stall_days} days without progression)")
    try:
        await _print_stalled_contacts(coordinator, days_stalled=args.stall_days)
    except Exception as exc:
        console.print(f"  [red]Stalled contacts check failed: {exc}[/red]")
        logger.exception("[daily] Stalled contacts check failed")
        errors += 1

    # ------------------------------------------------------------------
    # Step 5: Push to sequences
    # ------------------------------------------------------------------
    if not args.skip_push:
        _header(5, f"Push to Instantly Sequences (limit={args.push_limit})")
        try:
            _run_sequence_push(campaign, args.push_limit, args.dry_run)
        except Exception as exc:
            console.print(f"  [red]Sequence push failed: {exc}[/red]")
            logger.exception("[daily] Sequence push failed")
            errors += 1
    else:
        console.print("\n[dim]Step 5: Sequence push skipped (--skip-push)[/dim]")

    # ------------------------------------------------------------------
    # Step 6: Pipeline summary
    # ------------------------------------------------------------------
    _header(6, "Pipeline Summary")
    try:
        _print_pipeline_summary(coordinator, campaign)
    except Exception as exc:
        console.print(f"  [red]Pipeline summary failed: {exc}[/red]")
        logger.exception("[daily] Pipeline summary failed")
        errors += 1

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    console.print()
    if errors == 0:
        console.print(Panel("[bold green]Daily outreach run complete — no errors[/bold green]"))
    else:
        console.print(
            Panel(
                f"[bold yellow]Daily outreach run complete — {errors} step(s) had errors[/bold yellow]\n"
                "[dim]Check logs above for details[/dim]"
            )
        )
    return 0 if errors == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily outreach operations runner for ProspectIQ.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--campaign",
        default=None,
        help="Restrict all operations to this campaign name (e.g. fsma_q1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but make no API calls and no database writes",
    )
    parser.add_argument(
        "--skip-intent",
        action="store_true",
        help="Skip job posting scan (saves Apollo credit usage)",
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="Skip pushing contacts to Instantly sequences",
    )
    parser.add_argument(
        "--push-limit",
        type=int,
        default=50,
        help="Maximum contacts to push to Instantly in this run (default: 50)",
    )
    parser.add_argument(
        "--action-limit",
        type=int,
        default=20,
        help="Maximum items to show in the action queue (default: 20)",
    )
    parser.add_argument(
        "--stall-days",
        type=int,
        default=5,
        help="Days without progression before a contact is flagged as stalled (default: 5)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    exit_code = asyncio.run(_async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
