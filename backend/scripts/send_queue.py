"""Send priority queue CLI.

Shows today's ranked send queue and optionally updates priority scores.

Usage:
    python -m backend.scripts.send_queue
    python -m backend.scripts.send_queue --campaign tier0-mfg-pdm-roi --limit 20
    python -m backend.scripts.send_queue --update-scores
"""

from __future__ import annotations

import argparse

from rich.console import Console

from backend.app.core.queue_manager import QueueManager

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(description="ProspectIQ send priority queue")
    parser.add_argument("--campaign", help="Filter by campaign name")
    parser.add_argument("--limit", type=int, default=20, help="Max contacts to show (default: 20)")
    parser.add_argument("--min-score", type=int, default=40,
                        help="Min completeness score to include (default: 40)")
    parser.add_argument("--update-scores", action="store_true",
                        help="Recompute and persist priority scores before showing queue")
    args = parser.parse_args()

    qm = QueueManager(campaign_name=args.campaign)

    if args.update_scores:
        console.print("[cyan]Recomputing priority scores...[/cyan]")
        updated = qm.update_priority_scores()
        console.print(f"  [dim]Updated {updated} contacts[/dim]\n")

    console.print(f"\n[bold]Today's Send Queue[/bold]"
                  + (f" — [cyan]{args.campaign}[/cyan]" if args.campaign else ""))

    contacts = qm.get_send_queue(limit=args.limit, min_completeness=args.min_score)

    if not contacts:
        console.print("[yellow]No contacts ready to send today.[/yellow]")
        console.print("[dim]Reasons: limit reached, all sent, DNC, or completeness too low[/dim]")
        return

    qm.print_queue(contacts)


if __name__ == "__main__":
    main()
