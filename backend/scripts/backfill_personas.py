"""Backfill persona_type + priority_score for existing contacts.

Also removes contacts with titles that are clearly non-buyers (Sales, HR,
Finance, Engineering individual contributors) to keep the pipeline clean.

Usage:
    python -m backend.scripts.backfill_personas [--dry-run] [--campaign CAMPAIGN]
"""

from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.table import Table

from backend.app.agents.discovery import classify_persona
from backend.app.core.database import Database
from backend.app.core.queue_manager import compute_priority_score

console = Console()
logger = logging.getLogger(__name__)

# Titles / keywords that mark a contact as a definite non-buyer.
# These roles have no authority over equipment, operations, or compliance spend.
NON_BUYER_KEYWORDS = [
    "sales manager", "account manager", "account executive",
    "business development", "regional sales", "territory manager",
    "hr manager", "human resources", "talent ", "recruiting",
    "accounting", "finance manager", "controller", "bookkeeper",
    "it manager", "it network", "helpdesk",
    "marketing manager", "brand manager", "communications",
    "legal", "compliance counsel",
    "rf design", "hardware engineer", "software engineer",
    "product development engineer", "validation engineer",
    "aftermarket", "spare parts coordinator",
    "purchasing manager", "procurement coordinator",
    "facilities manager", "office manager",
]


def is_non_buyer(title: str | None) -> bool:
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in NON_BUYER_KEYWORDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill personas and remove non-buyers")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, make no changes")
    parser.add_argument("--campaign", help="Limit to one campaign (e.g. mfg_wave2)")
    args = parser.parse_args()

    db = Database()
    dry = args.dry_run

    if dry:
        console.print("[yellow]DRY RUN — no changes will be made[/yellow]\n")

    # Fetch all contacts (with company context for scoring)
    query = db.client.table("contacts").select(
        "id, title, persona_type, completeness_score, updated_at, "
        "companies(tier, campaign_name, status)"
    )
    if args.campaign:
        # Filter via company join — fetch and filter in Python
        rows = query.limit(5000).execute().data or []
        rows = [r for r in rows if (r.get("companies") or {}).get("campaign_name") == args.campaign]
    else:
        rows = query.limit(5000).execute().data or []

    removed, classified, score_only = [], [], []

    for contact in rows:
        title = contact.get("title") or ""
        company = contact.get("companies") or {}

        if is_non_buyer(title):
            removed.append(contact)
            if not dry:
                db.client.table("contacts").delete().eq("id", contact["id"]).execute()
            continue

        updates: dict = {}

        if not contact.get("persona_type"):
            persona_type, is_dm = classify_persona(title)
            updates["persona_type"] = persona_type
            updates["is_decision_maker"] = is_dm
            classified.append({**contact, **updates})

        # Always recompute priority score
        merged = {**contact, **updates}
        new_score = compute_priority_score(merged, company)
        updates["priority_score"] = new_score
        score_only.append(contact)

        if updates and not dry:
            db.client.table("contacts").update(updates).eq("id", contact["id"]).execute()

    # Summary
    console.print(f"\n[bold]Backfill complete[/bold] (campaign: {args.campaign or 'all'})")
    console.print(f"  [red]Removed non-buyers:[/red]  {len(removed)}")
    console.print(f"  [green]Persona classified:[/green] {len(classified)}")
    console.print(f"  [cyan]Scores recomputed:[/cyan]  {len(score_only)}")

    if removed:
        console.print("\n[bold red]Removed contacts:[/bold red]")
        t = Table(show_header=True)
        t.add_column("Title")
        t.add_column("Company")
        for c in removed[:30]:
            t.add_row(c.get("title", ""), (c.get("companies") or {}).get("campaign_name", ""))
        console.print(t)

    if classified:
        console.print("\n[bold green]Newly classified:[/bold green]")
        t = Table(show_header=True)
        t.add_column("Title")
        t.add_column("Persona")
        for c in classified[:20]:
            t.add_row(c.get("title", ""), c.get("persona_type") or "—")
        console.print(t)


if __name__ == "__main__":
    main()
