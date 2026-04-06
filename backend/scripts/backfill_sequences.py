"""One-time backfill: enroll all sent Step-1 contacts into engagement_sequences.

Run once after deploying the JIT follow-up feature:
    python backend/scripts/backfill_sequences.py

For each contact that received a Step 1 email, creates an engagement_sequences
row so the JIT pre-generate job can schedule and generate steps 2-4 automatically.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import yaml
from rich.console import Console
from rich.table import Table

from backend.app.core.config import get_settings
from supabase import create_client

console = Console()
logger = logging.getLogger(__name__)

SEQUENCE_NAME = "email_value_first"
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _load_step_delays() -> dict[int, int]:
    """Load delay_days per step from sequences.yaml."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "sequences.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    seq = config["sequences"].get(SEQUENCE_NAME, {})
    steps = seq.get("steps", [])
    return {s["step"]: s.get("delay_days", 0) for s in steps}


def main() -> None:
    console.print("[bold cyan]Backfilling engagement_sequences for sent Step-1 contacts...[/bold cyan]")

    settings = get_settings()
    db = create_client(settings.supabase_url, settings.supabase_service_key)

    # Load sequence step delays
    step_delays = _load_step_delays()
    total_steps = max(step_delays.keys())
    step2_delay = step_delays.get(2, 5)
    console.print(f"Sequence: {SEQUENCE_NAME} | {total_steps} steps | Step 2 delay: {step2_delay} days")

    # Fetch all sent step-1 drafts
    result = (
        db.table("outreach_drafts")
        .select("id, company_id, contact_id, sequence_name, sent_at, workspace_id")
        .eq("sequence_step", 1)
        .not_.is_("sent_at", "null")
        .execute()
    )
    drafts = result.data
    console.print(f"Found {len(drafts)} sent Step-1 drafts")

    enrolled = 0
    skipped = 0
    errors = 0

    table = Table(title="Backfill Results", show_lines=False)
    table.add_column("Contact ID", style="dim", width=12)
    table.add_column("Company ID", style="dim", width=12)
    table.add_column("Sent At", width=12)
    table.add_column("Step 2 Due", width=12)
    table.add_column("Result", width=10)

    for draft in drafts:
        company_id = draft["company_id"]
        contact_id = draft["contact_id"]
        sent_at_str = draft["sent_at"]
        ws_id = draft.get("workspace_id") or WORKSPACE_ID

        try:
            # Check if already enrolled
            existing = (
                db.table("engagement_sequences")
                .select("id")
                .eq("company_id", company_id)
                .eq("contact_id", contact_id)
                .eq("sequence_name", SEQUENCE_NAME)
                .execute()
            )
            if existing.data:
                skipped += 1
                table.add_row(
                    contact_id[:8], company_id[:8], sent_at_str[:10], "—", "[yellow]skipped[/yellow]"
                )
                continue

            # Calculate next_action_at = sent_at + step2 delay
            sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
            next_action_at = (sent_at + timedelta(days=step2_delay)).isoformat()

            db.table("engagement_sequences").insert({
                "company_id": company_id,
                "contact_id": contact_id,
                "sequence_name": SEQUENCE_NAME,
                "current_step": 1,
                "total_steps": total_steps,
                "status": "active",
                "next_action_at": next_action_at,
                "next_action_type": "generate_draft",
                "workspace_id": ws_id,
            }).execute()

            enrolled += 1
            step2_due = (sent_at + timedelta(days=step2_delay)).strftime("%b %d")
            table.add_row(
                contact_id[:8], company_id[:8], sent_at_str[:10], step2_due, "[green]enrolled[/green]"
            )

        except Exception as e:
            errors += 1
            logger.error(f"Error enrolling contact {contact_id}: {e}")
            table.add_row(contact_id[:8], company_id[:8], sent_at_str[:10], "—", "[red]error[/red]")

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] {enrolled} enrolled | {skipped} skipped (already exists) | {errors} errors"
    )

    if enrolled > 0:
        console.print(
            f"\n[green]✓ {enrolled} contacts enrolled.[/green] "
            f"The JIT pre-generate job will start creating Step 2 drafts 3 days before their due dates."
        )


if __name__ == "__main__":
    main()
