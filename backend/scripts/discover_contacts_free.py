"""Free contact discovery via Apollo People Search (no enrichment credits used).

For each qualified company with no contacts, runs Apollo People Search to find
VP Ops, COO, Plant Manager, Director Quality contacts and stores them with
LinkedIn URLs. No email enrichment is triggered — contacts are inserted with
status 'identified' and enriched when credits renew (Apr 27).

Run:
    python backend/scripts/discover_contacts_free.py --limit 200
    python backend/scripts/discover_contacts_free.py --limit 200 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rich.console import Console
from rich.table import Table

from backend.app.core.config import get_settings
from backend.app.integrations.apollo import ApolloClient
from backend.app.agents.discovery import classify_persona
from supabase import create_client

console = Console()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)

# Seniority filter for People Search (free)
SENIORITY_FILTER = ["vp", "c_suite", "director", "owner"]
HIGH_VALUE_PERSONAS = {"vp_ops", "coo", "plant_manager", "vp_quality_food_safety",
                       "maintenance_leader", "director_quality_food_safety"}
CAP_PER_COMPANY = 8  # Max contacts to store per company from People Search


def get_companies_needing_contacts(db, limit: int) -> list[dict]:
    """Return qualified companies missing high-value persona contacts, ordered by PQS desc."""
    companies = []
    offset = 0
    batch = 1000
    while True:
        r = (
            db.table("companies")
            .select("id, name, domain, apollo_id, pqs_total, tier, status")
            .in_("status", ["qualified", "outreach_pending", "contacted"])
            .order("pqs_total", desc=True)
            .range(offset, offset + batch - 1)
            .execute()
        )
        chunk = r.data or []
        companies.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch

    # Get contacts grouped by company
    contacts_r = (
        db.table("contacts")
        .select("company_id, persona_type")
        .execute()
    )
    company_personas: dict[str, set] = defaultdict(set)
    for c in (contacts_r.data or []):
        if c.get("persona_type"):
            company_personas[c["company_id"]].add(c["persona_type"])

    # Filter to companies missing all high-value personas
    missing = [
        co for co in companies
        if not HIGH_VALUE_PERSONAS.intersection(company_personas[co["id"]])
    ]

    return missing[:limit]


def main(limit: int = 200, dry_run: bool = False) -> None:
    if dry_run:
        console.print(f"[bold yellow]DRY RUN — Apollo search will run but NO inserts[/bold yellow]")
    else:
        console.print(f"[bold cyan]Running free contact discovery for up to {limit} companies[/bold cyan]")

    settings = get_settings()
    db = create_client(settings.supabase_url, settings.supabase_service_key)

    companies = get_companies_needing_contacts(db, limit)
    console.print(f"Companies missing high-value contacts: {len(companies)} (capped at {limit})")

    total_found = 0
    total_inserted = 0
    total_skipped_companies = 0
    results = []

    with ApolloClient() as apollo:
        for i, company in enumerate(companies, 1):
            company_id = company["id"]
            company_name = company["name"]
            domain = company.get("domain")
            pqs = company.get("pqs_total") or 0

            console.print(f"  [{i}/{len(companies)}] {company_name} (PQS {pqs})...", end=" ")

            try:
                search_kwargs: dict = {"per_page": 25}
                if domain:
                    search_kwargs["organization_domains"] = [domain]
                else:
                    search_kwargs["q_organization_name"] = company_name
                search_kwargs["person_seniorities"] = SENIORITY_FILTER

                resp = apollo.search_people(**search_kwargs)
                people = resp.get("people", [])

                if not people:
                    console.print("[dim]0 results[/dim]")
                    total_skipped_companies += 1
                    results.append((company_name, pqs, 0, 0))
                    continue

                inserted_this_company = 0
                found_this_company = 0

                for person in people[:CAP_PER_COMPANY]:
                    contact_data = ApolloClient.extract_contact_data(person)
                    if not contact_data.get("apollo_id"):
                        continue
                    found_this_company += 1

                    if dry_run:
                        inserted_this_company += 1
                        continue

                    # Skip if already in DB
                    existing = (
                        db.table("contacts")
                        .select("id")
                        .eq("apollo_id", contact_data["apollo_id"])
                        .limit(1)
                        .execute()
                    )
                    if existing.data:
                        continue

                    persona_type, is_dm = classify_persona(contact_data.get("title"))
                    contact_insert = {
                        **contact_data,
                        "company_id": company_id,
                        "persona_type": persona_type,
                        "is_decision_maker": is_dm,
                        "status": "identified",
                    }
                    db.table("contacts").insert(contact_insert).execute()
                    inserted_this_company += 1

                total_found += found_this_company
                total_inserted += inserted_this_company
                results.append((company_name, pqs, found_this_company, inserted_this_company))
                console.print(f"[green]{inserted_this_company} inserted[/green] ({found_this_company} found)")

                # Rate limit: Apollo enforces ~3.5s between requests
                time.sleep(3.6)

            except Exception as e:
                console.print(f"[red]error: {e}[/red]")
                logger.warning(f"Discovery failed for {company_name}: {e}")
                results.append((company_name, pqs, 0, 0))
                time.sleep(5)

    # Summary table
    table = Table(title="Discovery Results", show_lines=False)
    table.add_column("Company", width=40)
    table.add_column("PQS", width=5)
    table.add_column("Found", width=6)
    table.add_column("Inserted", width=8)
    for company_name, pqs, found, inserted in results:
        style = "green" if inserted > 0 else "dim"
        table.add_row(company_name[:40], str(pqs), str(found), str(inserted), style=style)

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] {total_inserted} contacts inserted across {len(companies)} companies "
        f"({total_skipped_companies} companies had no Apollo results)"
    )
    if not dry_run and total_inserted > 0:
        console.print(
            f"\n[green]✓ {total_inserted} contacts added with LinkedIn URLs.[/green] "
            f"They are ready for LinkedIn outreach now and email enrichment on Apr 27."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Free Apollo contact discovery (no enrichment credits)")
    parser.add_argument("--limit", type=int, default=200, help="Max companies to process")
    parser.add_argument("--dry-run", action="store_true", help="Search but don't insert")
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run)
