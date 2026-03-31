"""Role coverage matrix for Tier 0 companies.

Shows which decision-maker personas are present or missing per company,
helping prioritize manual outreach to fill gaps.

Usage:
    python -m backend.scripts.role_coverage
    python -m backend.scripts.role_coverage --campaign tier0-mfg-pdm-roi --min-score 60
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database

console = Console()

# Personas in priority order (highest = most valuable)
PERSONA_PRIORITY: dict[str, int] = {
    "coo": 95,
    "vp_ops": 100,
    "plant_manager": 90,
    "digital_transformation": 85,
    "vp_supply_chain": 80,
    "director_ops": 75,
    "cio": 70,
}

PERSONA_LABELS: dict[str, str] = {
    "coo": "COO",
    "vp_ops": "VP Ops/Mfg/Eng",
    "plant_manager": "Plant/GM",
    "digital_transformation": "Dig. Transform.",
    "vp_supply_chain": "VP Supply Chain",
    "director_ops": "Dir. Ops/Mfg/Eng",
    "cio": "CIO/CTO",
}

CORE_PERSONAS = ["vp_ops", "coo", "plant_manager", "director_ops"]


def build_coverage_matrix(
    campaign_name: str | None = None,
    min_completeness: int = 0,
) -> list[dict]:
    """Return per-company coverage data."""
    db = Database()

    query = db.client.table("companies").select("id, name, domain, tier, campaign_name, status")
    if campaign_name:
        query = query.eq("campaign_name", campaign_name)
    companies = query.order("name").execute().data

    rows = []
    for company in companies:
        contacts = db.get_contacts_for_company(company["id"])

        # Build persona → contacts mapping
        persona_map: dict[str, list[dict]] = {p: [] for p in PERSONA_PRIORITY}
        uncategorised = []

        for c in contacts:
            score = c.get("completeness_score") or 0
            if min_completeness and score < min_completeness:
                continue
            persona = c.get("persona_type")
            if persona and persona in persona_map:
                persona_map[persona].append(c)
            else:
                uncategorised.append(c)

        enriched_total = sum(
            1 for c in contacts
            if (c.get("completeness_score") or 0) >= 60 or c.get("enrichment_status") == "enriched"
        )

        covered_core = [p for p in CORE_PERSONAS if persona_map[p]]
        missing_core = [p for p in CORE_PERSONAS if not persona_map[p]]

        rows.append({
            "company": company,
            "persona_map": persona_map,
            "uncategorised": uncategorised,
            "total_contacts": len(contacts),
            "enriched_total": enriched_total,
            "covered_core": covered_core,
            "missing_core": missing_core,
            "gap_count": len(missing_core),
        })

    # Sort by gap count desc (most gaps first), then name
    rows.sort(key=lambda r: (-r["gap_count"], r["company"]["name"]))
    return rows


def print_coverage_matrix(rows: list[dict]) -> None:
    """Print the coverage matrix as a Rich table."""
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Company", min_width=26)
    table.add_column("Tier", justify="center", min_width=5)
    table.add_column("Contacts", justify="center", min_width=8)
    table.add_column("Enriched", justify="center", min_width=8)

    for persona in PERSONA_PRIORITY:
        table.add_column(PERSONA_LABELS[persona], justify="center", min_width=10)

    table.add_column("Core Gaps", justify="center", min_width=9)

    for row in rows:
        company = row["company"]
        cells = [
            company["name"][:28],
            str(company.get("tier") or "—"),
            str(row["total_contacts"]),
            str(row["enriched_total"]),
        ]

        for persona in PERSONA_PRIORITY:
            contacts = row["persona_map"][persona]
            if contacts:
                names = ", ".join(
                    c.get("full_name", "?").split()[0] for c in contacts[:2]
                )
                cells.append(f"[green]✓ {names}[/green]")
            else:
                cells.append("[dim]—[/dim]")

        gap_count = row["gap_count"]
        if gap_count == 0:
            cells.append("[green]0[/green]")
        elif gap_count <= 2:
            cells.append(f"[yellow]{gap_count}[/yellow]")
        else:
            cells.append(f"[red]{gap_count}[/red]")

        table.add_row(*cells)

    console.print(table)

    # Summary
    total_gaps = sum(r["gap_count"] for r in rows)
    fully_covered = sum(1 for r in rows if r["gap_count"] == 0)
    console.print(
        f"\n[bold]Summary:[/bold] {len(rows)} companies · "
        f"{fully_covered} fully covered · {total_gaps} core persona gaps total"
    )

    # Missing personas ranking
    missing_counts: dict[str, int] = {p: 0 for p in CORE_PERSONAS}
    for row in rows:
        for p in row["missing_core"]:
            missing_counts[p] += 1

    if any(missing_counts.values()):
        console.print("\n[bold]Most missing personas:[/bold]")
        for persona, count in sorted(missing_counts.items(), key=lambda x: -x[1]):
            if count:
                console.print(f"  {PERSONA_LABELS[persona]}: missing at {count} companies")


def main() -> None:
    parser = argparse.ArgumentParser(description="Role coverage matrix for ProspectIQ campaigns")
    parser.add_argument("--campaign", help="Filter by campaign name")
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Only count contacts with completeness_score >= this value (default: 0 = all)",
    )
    args = parser.parse_args()

    console.print(f"\n[bold]Role Coverage Matrix[/bold]")
    if args.campaign:
        console.print(f"Campaign: [cyan]{args.campaign}[/cyan]")
    if args.min_score:
        console.print(f"Min completeness score: [cyan]{args.min_score}[/cyan]")

    rows = build_coverage_matrix(
        campaign_name=args.campaign,
        min_completeness=args.min_score,
    )

    if not rows:
        console.print("[yellow]No companies found.[/yellow]")
        return

    print_coverage_matrix(rows)


if __name__ == "__main__":
    main()
