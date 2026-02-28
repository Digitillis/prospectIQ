"""Reset disqualified companies and re-score them with corrected firmographic logic.

Disqualified companies lost the Midwest bonus because state=NULL (Apollo did
not return location data). The fix in qualification.py now awards the Midwest
bonus when state is unknown, since all companies were discovered via a
Midwest-filtered Apollo search.

This script:
  1. Resets 'disqualified' companies back to 'discovered'
  2. Re-runs the Qualification Agent on all discovered + researched companies

Usage:
  python -m backend.scripts.reset_and_requalify
  python -m backend.scripts.reset_and_requalify --tier 1a   # reset one tier only
  python -m backend.scripts.reset_and_requalify --dry-run
"""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

console = Console()
app = typer.Typer(help="Reset disqualified companies and re-run qualification scoring.")


@app.command()
def main(
    tier: Optional[str] = typer.Option(
        None,
        "--tier",
        help="Only reset companies for this tier (e.g. '1a'). Default: all tiers.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be reset without writing to the database.",
    ),
) -> None:
    """Reset disqualified companies to 'discovered' and re-run qualification."""
    from backend.app.core.database import Database
    from backend.app.agents.qualification import QualificationAgent

    db = Database()

    # ------------------------------------------------------------------
    # 1. Find all disqualified companies
    # ------------------------------------------------------------------
    console.print("[cyan]Loading disqualified companies...[/cyan]")
    all_companies = []
    offset = 0
    while True:
        page = db.get_companies(status="disqualified", limit=200, offset=offset)
        if not page:
            break
        all_companies.extend(page)
        if len(page) < 200:
            break
        offset += 200

    if tier:
        targets = [c for c in all_companies if c.get("tier") == tier]
    else:
        targets = all_companies

    console.print(
        f"  Disqualified total : [bold]{len(all_companies)}[/bold]\n"
        f"  To reset           : [bold]{len(targets)}[/bold]"
        + (f" (tier={tier})" if tier else " (all tiers)")
    )

    if not targets:
        console.print("[yellow]Nothing to reset.[/yellow]")
        return

    from collections import Counter
    tier_counts = Counter(c.get("tier") or "?" for c in targets)
    console.print("\n  Breakdown by tier:")
    for t, n in sorted(tier_counts.items()):
        console.print(f"    tier=[bold]{t}[/bold] : {n}")

    if dry_run:
        console.print("\n[yellow]DRY RUN — no changes written.[/yellow]")
        return

    # ------------------------------------------------------------------
    # 2. Reset status to 'discovered'
    # ------------------------------------------------------------------
    console.print(f"\n[cyan]Resetting {len(targets)} companies to 'discovered'...[/cyan]")
    reset = 0
    for company in targets:
        try:
            db.update_company(company["id"], {
                "status": "discovered",
                "pqs_total": 0,
                "pqs_firmographic": 0,
                "pqs_technographic": 0,
                "pqs_timing": 0,
                "qualification_notes": None,
            })
            reset += 1
        except Exception as e:
            console.print(f"  [red]Error resetting {company.get('name')}: {e}[/red]")

    console.print(f"  Reset [bold green]{reset}[/bold green] companies.")

    # ------------------------------------------------------------------
    # 3. Re-run qualification on all discovered companies
    # ------------------------------------------------------------------
    console.print("\n[cyan]Re-running qualification scoring...[/cyan]")
    agent = QualificationAgent()
    result = agent.execute(limit=500)
    console.print(f"\n[bold green]Done. {result.summary()}[/bold green]")


if __name__ == "__main__":
    app()
