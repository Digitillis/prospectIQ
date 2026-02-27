"""Generate and display the daily action list.

Checks for due follow-ups, pending approvals, and surfacing
high-priority items that need founder attention.
"""

import typer
from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database

console = Console()
app = typer.Typer(help="Generate the daily action list for ProspectIQ.")


@app.command()
def main():
    """Generate today's daily action list."""
    db = Database()

    console.print("\n[bold blue]{'='*60}[/bold blue]")
    console.print("[bold blue]ProspectIQ — Daily Actions[/bold blue]")
    console.print(f"[bold blue]{'='*60}[/bold blue]\n")

    # 1. Pending approvals
    pending = db.get_pending_drafts(limit=100)
    console.print(f"[cyan]Pending Approvals: {len(pending)}[/cyan]")
    if pending:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Company")
        table.add_column("Contact")
        table.add_column("Subject")
        table.add_column("Sequence")
        for draft in pending[:20]:
            company_name = draft.get("companies", {}).get("name", "Unknown") if draft.get("companies") else "Unknown"
            contact_name = draft.get("contacts", {}).get("full_name", "Unknown") if draft.get("contacts") else "Unknown"
            table.add_row(
                company_name,
                contact_name,
                draft.get("subject", "")[:50],
                f"{draft.get('sequence_name', '')} step {draft.get('sequence_step', '')}",
            )
        console.print(table)
    console.print()

    # 2. Due follow-up sequences
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    due_sequences = db.get_active_sequences(due_before=now)
    console.print(f"[cyan]Follow-ups Due: {len(due_sequences)}[/cyan]")
    if due_sequences:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Company")
        table.add_column("Contact")
        table.add_column("Step")
        table.add_column("Action Type")
        table.add_column("Due")
        for seq in due_sequences[:20]:
            company_name = seq.get("companies", {}).get("name", "Unknown") if seq.get("companies") else "Unknown"
            contact_name = seq.get("contacts", {}).get("full_name", "Unknown") if seq.get("contacts") else "Unknown"
            table.add_row(
                company_name,
                contact_name,
                f"{seq.get('current_step', 0)}/{seq.get('total_steps', '?')}",
                seq.get("next_action_type", "unknown"),
                seq.get("next_action_at", "")[:16],
            )
        console.print(table)
    console.print()

    # 3. High-priority companies needing attention
    hot_companies = db.get_companies(status="qualified", min_pqs=61, limit=10)
    engaged = db.get_companies(status="engaged", limit=10)
    console.print(f"[cyan]High-Priority Qualified: {len(hot_companies)}[/cyan]")
    console.print(f"[cyan]Engaged (awaiting response): {len(engaged)}[/cyan]")

    if hot_companies:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Company")
        table.add_column("PQS")
        table.add_column("Tier")
        table.add_column("State")
        for c in hot_companies:
            table.add_row(
                c["name"],
                str(c.get("pqs_total", 0)),
                c.get("tier", "-"),
                c.get("state", "-"),
            )
        console.print(table)

    # Summary
    console.print(f"\n[bold green]{'-'*60}[/bold green]")
    console.print(
        f"[bold green]Summary: {len(pending)} approvals | "
        f"{len(due_sequences)} follow-ups | "
        f"{len(hot_companies)} hot prospects[/bold green]"
    )
    console.print(f"[bold green]{'-'*60}[/bold green]\n")


if __name__ == "__main__":
    app()
