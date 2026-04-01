"""CLI for ProspectIQ sequence management.

Usage examples:

  # List all defined sequences
  python run_sequence.py list

  # Show active enrollments (who is mid-sequence right now)
  python run_sequence.py enrollments

  # Check send readiness (warm-up gate status + draft counts)
  python run_sequence.py status

  # Send all approved drafts to Instantly (requires SEND_ENABLED=true in .env)
  python run_sequence.py send

  # Launch a sequence for specific companies (generates Step 1 drafts → approval queue)
  python run_sequence.py launch --sequence email_value_first --company-ids uuid1 uuid2 uuid3

  # Launch for top N high-priority companies not yet in a sequence
  python run_sequence.py launch --sequence email_value_first --top 20

  # Generate follow-ups for all overdue sequence steps
  python run_sequence.py process-due

  # Create a custom sequence interactively (opens editor)
  python run_sequence.py create --name machinery_vp_ops --display "Machinery VP Operations"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

console = Console()
app = typer.Typer(help="ProspectIQ sequence management CLI.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db():
    from backend.app.core.database import Database
    return Database()


def _settings():
    from backend.app.core.config import get_settings
    return get_settings()


def _sequences_config():
    from backend.app.core.config import get_sequences_config
    return get_sequences_config()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("list")
def list_sequences():
    """List all available sequence definitions (YAML + custom DB)."""
    config = _sequences_config()
    yaml_seqs = config.get("sequences", {})

    db = _db()
    try:
        result = db.client.table("campaign_sequence_definitions").select("*").execute()
        db_seqs = {s["name"]: s for s in (result.data or [])}
    except Exception:
        db_seqs = {}

    table = Table(title="ProspectIQ Sequences")
    table.add_column("Name", style="cyan")
    table.add_column("Display Name")
    table.add_column("Channel")
    table.add_column("Steps")
    table.add_column("Source")
    table.add_column("Active")

    # YAML sequences
    for name, definition in yaml_seqs.items():
        steps = definition.get("steps", [])
        display_name = definition.get("name", name)
        channel = definition.get("channel", "email")
        source = "yaml (overridden by DB)" if name in db_seqs else "yaml"
        table.add_row(name, display_name, channel, str(len(steps)), source, "✓")

    # DB-only sequences (not in YAML)
    for name, definition in db_seqs.items():
        if name not in yaml_seqs:
            steps = definition.get("steps") or []
            table.add_row(
                name,
                definition.get("display_name", name),
                definition.get("channel", "email"),
                str(len(steps)),
                "custom (db)",
                "✓" if definition.get("is_active") else "✗",
            )

    console.print(table)


@app.command("status")
def send_status():
    """Check send readiness — warm-up gate, draft counts, scheduler config."""
    settings = _settings()
    db = _db()

    console.print(f"\n[bold]Send gate:[/bold] SEND_ENABLED = [{'green' if settings.send_enabled else 'red'}]{'true ✓ — Ready to send' if settings.send_enabled else 'false ✗ — Warm-up not complete'}[/]")

    try:
        approved = (
            db.client.table("outreach_drafts")
            .select("id", count="exact")
            .in_("approval_status", ["approved", "edited"])
            .is_("sent_at", "null")
            .execute()
        )
        staged = approved.count or 0

        sent = (
            db.client.table("outreach_drafts")
            .select("id", count="exact")
            .not_.is_("sent_at", "null")
            .execute()
        )
        already_sent = sent.count or 0

        pending = (
            db.client.table("outreach_drafts")
            .select("id", count="exact")
            .eq("approval_status", "pending")
            .execute()
        )
        pending_count = pending.count or 0

    except Exception as e:
        console.print(f"[red]DB error: {e}[/red]")
        staged = already_sent = pending_count = -1

    console.print(f"\n[bold]Draft counts:[/bold]")
    console.print(f"  Approved (staged, ready to send):  {staged}")
    console.print(f"  Pending approval:                   {pending_count}")
    console.print(f"  Already sent:                       {already_sent}")

    console.print(f"\n[bold]Scheduler jobs (running in API server):[/bold]")
    console.print(f"  send_approved   → every 30 min [{'green' if settings.send_enabled else 'dim'}](active only when SEND_ENABLED=true)[/]")
    console.print(f"  process_due     → every 1 hour")
    console.print(f"  poll_instantly  → every 6 hours")

    if not settings.send_enabled:
        console.print(
            f"\n[yellow]Action needed:[/yellow] Set SEND_ENABLED=true in .env when "
            f"mailbox warm-up completes, then restart the server. "
            f"The {staged} staged drafts will send within 30 minutes."
        )
    else:
        console.print(f"\n[green]Ready.[/green] {staged} drafts will be pushed to Instantly at the next scheduler tick (≤30 min).")
        console.print("Or run [bold]python run_sequence.py send[/bold] to flush immediately.")


@app.command("send")
def send_approved():
    """Push all approved drafts to Instantly now. Requires SEND_ENABLED=true in .env."""
    settings = _settings()

    if not settings.send_enabled:
        console.print(
            "[red]SEND_ENABLED is false.[/red]\n"
            "Set SEND_ENABLED=true in .env (and restart the server) when mailbox warm-up completes."
        )
        raise typer.Exit(code=1)

    from backend.app.agents.engagement import EngagementAgent
    agent = EngagementAgent()
    result = agent.run(action="send_approved")
    console.print(
        f"\n[bold]Send complete:[/bold] "
        f"{result.processed} sent, {result.skipped} skipped, {result.errors} errors"
    )


@app.command("enrollments")
def list_enrollments(limit: int = typer.Option(50, help="Max rows to show")):
    """Show which companies are currently enrolled in sequences."""
    db = _db()

    try:
        result = (
            db.client.table("engagement_sequences")
            .select("*, companies(name, tier), contacts(full_name, email)")
            .eq("status", "active")
            .order("next_action_at")
            .limit(limit)
            .execute()
        )
        enrollments = result.data or []
    except Exception as e:
        console.print(f"[red]DB error: {e}[/red]")
        raise typer.Exit(code=1)

    if not enrollments:
        console.print("[yellow]No active sequence enrollments.[/yellow]")
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    table = Table(title=f"Active Sequence Enrollments ({len(enrollments)})")
    table.add_column("Company", style="cyan")
    table.add_column("Contact")
    table.add_column("Sequence")
    table.add_column("Step")
    table.add_column("Next Action At")
    table.add_column("Overdue")

    for e in enrollments:
        company = (e.get("companies") or {}).get("name", e.get("company_id", "?")[:8])
        contact = (e.get("contacts") or {}).get("full_name", "—")
        next_at = e.get("next_action_at", "—")
        overdue = "⚠ YES" if next_at and next_at < now else "—"
        table.add_row(
            company,
            contact,
            e.get("sequence_name", "?"),
            f"{e.get('current_step', '?')}/{e.get('total_steps', '?')}",
            next_at[:16] if next_at and next_at != "—" else "—",
            overdue,
        )

    console.print(table)


@app.command("launch")
def launch_sequence(
    sequence: str = typer.Option(..., "--sequence", "-s", help="Sequence name (e.g. email_value_first)"),
    company_ids: list[str] = typer.Option([], "--company-ids", help="Specific company UUIDs (repeatable)"),
    top: int = typer.Option(0, "--top", help="Enroll top N high-priority companies not yet in a sequence"),
    send: bool = typer.Option(False, "--send", help="Push to Instantly immediately (requires SEND_ENABLED=true)"),
):
    """Enroll companies in a sequence. Generates Step 1 draft → approval queue.

    Examples:
      python run_sequence.py launch --sequence email_value_first --top 20
      python run_sequence.py launch --sequence linkedin_relationship --company-ids uuid1 uuid2
    """
    db = _db()
    settings = _settings()

    # Resolve company IDs if --top used
    if top > 0 and not company_ids:
        try:
            # Find top N high-priority companies that are enriched but not yet in any sequence
            already_enrolled = (
                db.client.table("engagement_sequences")
                .select("company_id")
                .in_("status", ["active", "completed"])
                .execute()
                .data
            )
            enrolled_ids = {r["company_id"] for r in already_enrolled}

            candidates = (
                db.client.table("companies")
                .select("id, name, pqs_total")
                .in_("status", ["qualified", "high_priority", "hot_prospect"])
                .order("pqs_total", desc=True)
                .limit(top * 3)  # Fetch extra to account for filtering
                .execute()
                .data
            )

            company_ids = [
                c["id"] for c in candidates
                if c["id"] not in enrolled_ids
            ][:top]

            console.print(f"[cyan]Selected {len(company_ids)} companies (top {top} by PQS not yet enrolled)[/cyan]")
        except Exception as e:
            console.print(f"[red]Error resolving top companies: {e}[/red]")
            raise typer.Exit(code=1)

    if not company_ids:
        console.print("[red]No company IDs provided. Use --company-ids or --top N.[/red]")
        raise typer.Exit(code=1)

    console.print(f"\nLaunching [bold]{sequence}[/bold] for [bold]{len(company_ids)}[/bold] companies...")

    from backend.app.agents.outreach import OutreachAgent

    launched = 0
    errors = 0

    for company_id in company_ids:
        try:
            outreach = OutreachAgent()
            result = outreach.run(
                company_ids=[company_id],
                sequence_name=sequence,
                sequence_step=1,
            )
            if result.processed > 0:
                launched += 1
                console.print(f"  [green]✓[/green] {company_id[:8]}… → draft created")
            else:
                errors += 1
                console.print(f"  [yellow]–[/yellow] {company_id[:8]}… → no draft generated")
        except Exception as e:
            errors += 1
            console.print(f"  [red]✗[/red] {company_id[:8]}… → {str(e)[:100]}")

    console.print(f"\n[bold]Launch complete:[/bold] {launched} drafts created, {errors} errors")

    if send:
        if settings.send_enabled:
            console.print("\nPushing to Instantly...")
            from backend.app.agents.engagement import EngagementAgent
            eng = EngagementAgent()
            eng.run(action="send_approved")
        else:
            console.print("[yellow]--send ignored: SEND_ENABLED=false. Set it in .env when warm-up completes.[/yellow]")
    else:
        console.print(
            f"\nNext step: Review and approve drafts at [link]https://crm.digitillis.com/approvals[/link]"
        )


@app.command("process-due")
def process_due():
    """Generate follow-up drafts for all overdue sequence steps now.

    Same as the hourly scheduler job — run manually to process immediately.
    """
    from backend.app.agents.engagement import EngagementAgent
    agent = EngagementAgent()
    result = agent.run(action="process_due")
    console.print(
        f"\n[bold]Process complete:[/bold] "
        f"{result.processed} steps processed, {result.errors} errors"
    )


@app.command("create")
def create_sequence(
    name: str = typer.Option(..., "--name", help="Unique snake_case key, e.g. machinery_vp_ops"),
    display_name: str = typer.Option(..., "--display", help="Human-readable name"),
    channel: str = typer.Option("email", "--channel", help="Primary channel: email | linkedin"),
):
    """Create a new custom sequence definition from a JSON template.

    Opens the step template in your $EDITOR (or prints the template to stdout
    so you can modify it and POST to /api/sequences/).
    """
    template = {
        "name": name,
        "display_name": display_name,
        "description": "Custom sequence for ...",
        "channel": channel,
        "steps": [
            {
                "step": 1,
                "name": "initial_outreach",
                "channel": channel,
                "delay_days": 0,
                "subject_template": "{{company_name}} — re: {{pain_hook}}",
                "instructions": {
                    "description": "Lead with a specific operational insight. Reference their equipment type and one pain signal from research.",
                    "tone": "Expert peer, not vendor",
                    "max_words": 120,
                    "anti_patterns": [
                        "No feature lists",
                        "No meeting ask in step 1 — end with a question",
                        "No generic openers like 'I noticed your company'"
                    ]
                }
            },
            {
                "step": 2,
                "name": "follow_up_insight",
                "channel": channel,
                "delay_days": 5,
                "subject_template": "{{company_name}} — {{specific_outcome}}",
                "instructions": {
                    "description": "Follow up with evidence. Reference a specific outcome from a similar plant.",
                    "tone": "Evidence-based. Specific.",
                    "max_words": 100,
                    "anti_patterns": [
                        "No fabricated case studies",
                        "Equipment type and outcome must be specific"
                    ]
                }
            },
            {
                "step": 3,
                "name": "direct_ask",
                "channel": channel,
                "delay_days": 9,
                "subject_template": "15 min — {{specific_offer}}",
                "instructions": {
                    "description": "Direct, binary ask. Offer something specific and low-friction.",
                    "tone": "Direct, respectful of their time",
                    "max_words": 60,
                    "anti_patterns": [
                        "No 'just following up'",
                        "No urgency language",
                        "Single binary offer only"
                    ]
                }
            }
        ]
    }

    console.print("\n[bold]Sequence template:[/bold]")
    console.print(json.dumps(template, indent=2))
    console.print(
        "\n[dim]To create this sequence, POST the JSON above to "
        "POST /api/sequences/ or use:\n"
        "  curl -X POST http://localhost:8000/api/sequences/ "
        "-H 'Content-Type: application/json' -d @sequence.json[/dim]"
    )


if __name__ == "__main__":
    app()
