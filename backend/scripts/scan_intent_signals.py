"""Intent signal scanner CLI.

Scans pipeline companies for new buying-intent signals via Apollo (job postings),
then recomputes intent scores for all companies and surfaces the top hot accounts.

Usage:
    python -m backend.scripts.scan_intent_signals
    python -m backend.scripts.scan_intent_signals --campaign tier0-fb-fsma
    python -m backend.scripts.scan_intent_signals --type job_postings
    python -m backend.scripts.scan_intent_signals --dry-run
    python -m backend.scripts.scan_intent_signals --hot-threshold 15
"""

from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database
from backend.app.core.intent_engine import IntentEngine, HOT_THRESHOLD

console = Console()
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ProspectIQ intent signal scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--campaign",
        metavar="CAMPAIGN",
        help="Limit scan to a specific campaign name",
    )
    parser.add_argument(
        "--type",
        dest="signal_type",
        choices=["job_postings"],
        default="job_postings",
        help="Signal type to scan for (default: job_postings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be scanned without writing to the database",
    )
    parser.add_argument(
        "--hot-threshold",
        type=int,
        default=HOT_THRESHOLD,
        metavar="SCORE",
        help=f"Min intent score to consider a company 'hot' (default: {HOT_THRESHOLD})",
    )
    args = parser.parse_args()

    db = Database()
    engine = IntentEngine(db)

    campaign_label = f"[cyan]{args.campaign}[/cyan]" if args.campaign else "[dim]all campaigns[/dim]"

    # ------------------------------------------------------------------
    # Preview companies to scan
    # ------------------------------------------------------------------
    companies = db.get_companies_for_intent_scan(campaign_name=args.campaign)
    console.print(
        f"\n[bold]Intent Signal Scanner[/bold] — {campaign_label}\n"
        f"  Companies in scope: [cyan]{len(companies)}[/cyan]\n"
        f"  Signal type:        [cyan]{args.signal_type}[/cyan]\n"
        f"  Dry run:            [cyan]{args.dry_run}[/cyan]\n"
    )

    if not companies:
        console.print("[yellow]No companies found in scope. Exiting.[/yellow]")
        return

    if args.dry_run:
        _print_dry_run_preview(companies)
        return

    # ------------------------------------------------------------------
    # Run scan
    # ------------------------------------------------------------------
    console.print("[bold cyan]Running job posting scan via Apollo...[/bold cyan]")

    summary = engine.run_job_posting_scan(campaign_name=args.campaign)

    console.print(
        f"\n[bold green]Scan complete[/bold green]\n"
        f"  Companies scanned:    [cyan]{summary['scanned']}[/cyan]\n"
        f"  New signals detected: [cyan]{summary['new_signals']}[/cyan]\n"
        f"  Companies boosted:    [cyan]{summary['companies_boosted']}[/cyan]\n"
    )

    # ------------------------------------------------------------------
    # Recompute intent scores
    # ------------------------------------------------------------------
    console.print("[bold cyan]Recomputing intent scores...[/bold cyan]")
    score_summary = engine.recompute_all_intent_scores(campaign_name=args.campaign)
    console.print(
        f"  Updated: [cyan]{score_summary['updated']}[/cyan] companies  "
        f"([dim]{score_summary['total_signals']} active signals[/dim])\n"
    )

    # ------------------------------------------------------------------
    # Show top hot companies
    # ------------------------------------------------------------------
    hot = engine.get_hot_companies(min_intent_score=args.hot_threshold)
    if hot:
        _print_hot_companies(hot, args.hot_threshold)
    else:
        console.print(
            f"[yellow]No companies with intent_score >= {args.hot_threshold}[/yellow]"
        )


def _print_dry_run_preview(companies: list[dict]) -> None:
    """Print a preview table of companies that would be scanned."""
    table = Table(show_header=True, header_style="bold blue", title="Companies to Scan (Dry Run)")
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Company", min_width=30)
    table.add_column("Domain", min_width=24)
    table.add_column("Campaign", min_width=22)
    table.add_column("Current Intent Score", justify="center", min_width=20)

    for i, c in enumerate(companies[:50], 1):
        score = c.get("intent_score", 0)
        score_str = (
            f"[green]{score}[/green]" if score >= HOT_THRESHOLD else
            f"[yellow]{score}[/yellow]" if score > 0 else
            f"[dim]{score}[/dim]"
        )
        table.add_row(
            str(i),
            (c.get("name") or "—")[:30],
            (c.get("domain") or "—")[:24],
            (c.get("campaign_name") or "—")[:22],
            score_str,
        )

    console.print(table)
    if len(companies) > 50:
        console.print(f"[dim]… and {len(companies) - 50} more[/dim]")
    console.print("\n[dim]Dry run — no data written.[/dim]")


def _print_hot_companies(companies: list[dict], threshold: int) -> None:
    """Print the top hot companies table."""
    top = companies[:10]
    table = Table(
        show_header=True,
        header_style="bold green",
        title=f"Top Hot Companies (intent_score >= {threshold})",
    )
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Company", min_width=30)
    table.add_column("Domain", min_width=24)
    table.add_column("Campaign", min_width=22)
    table.add_column("Intent Score", justify="center", min_width=12)
    table.add_column("Last Signal", min_width=20)

    for i, c in enumerate(top, 1):
        score = c.get("intent_score", 0)
        last_signal = c.get("last_intent_signal_at") or "—"
        if last_signal != "—":
            last_signal = last_signal[:10]  # date only
        table.add_row(
            str(i),
            (c.get("name") or "—")[:30],
            (c.get("domain") or "—")[:24],
            (c.get("campaign_name") or "—")[:22],
            f"[bold green]{score}[/bold green]",
            last_signal,
        )

    console.print(table)
    if len(companies) > 10:
        console.print(f"[dim]… and {len(companies) - 10} more hot companies[/dim]")


if __name__ == "__main__":
    main()
