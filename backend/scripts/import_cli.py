"""Prospect import CLI with validation.

Imports companies and contacts from a CSV or JSON file after running
ICP validation, domain dedup checks, and coverage gap analysis.

Usage:
    python -m backend.scripts.import_cli --file prospects.csv --campaign tier0-mfg-pdm-roi
    python -m backend.scripts.import_cli --file prospects.csv --dry-run
    python -m backend.scripts.import_cli --help

Expected CSV columns (all optional except name or company_name):
    company_name, domain, apollo_id (org), state, employee_count, estimated_revenue,
    first_name, last_name, full_name, title, email, phone, contact_apollo_id

Expected JSON format:
    [{"company_name": "...", "contacts": [{"full_name": "...", "title": "..."}]}]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from backend.app.core.config import get_icp_config
from backend.app.core.database import Database
from backend.app.core.icp_validator import validate_and_exit_on_error
from backend.app.agents.discovery import classify_persona

console = Console()


def load_csv(path: Path) -> list[dict]:
    """Load prospects from CSV file."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows


def load_json(path: Path) -> list[dict]:
    """Load prospects from JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_csv_row(row: dict) -> tuple[dict, dict]:
    """Split a flat CSV row into company_data and contact_data dicts."""
    company_data = {
        "name": row.get("company_name") or row.get("name", ""),
        "domain": row.get("domain") or row.get("website") or None,
        "apollo_id": row.get("org_apollo_id") or row.get("organization_id") or None,
        "state": row.get("state") or row.get("hq_state") or None,
        "employee_count": _parse_int(row.get("employee_count")),
        "estimated_revenue": _parse_int(row.get("estimated_revenue")),
        "industry": row.get("industry") or None,
    }

    contact_data = {
        "full_name": row.get("full_name") or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip() or None,
        "first_name": row.get("first_name") or None,
        "last_name": row.get("last_name") or None,
        "title": row.get("title") or None,
        "email": row.get("email") or None,
        "phone": row.get("phone") or None,
        "apollo_id": row.get("contact_apollo_id") or row.get("person_id") or None,
    }

    return company_data, contact_data


def _parse_int(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def validate_row(company_data: dict, contact_data: dict) -> list[str]:
    """Return a list of validation errors for a row."""
    errors = []

    if not company_data.get("name"):
        errors.append("Missing company name")

    apollo_id = contact_data.get("apollo_id")
    if apollo_id and len(apollo_id) < 24:
        errors.append(f"contact apollo_id '{apollo_id}' is {len(apollo_id)} chars (must be 24)")

    return errors


def run_import(
    records: list[tuple[dict, dict]],
    campaign_name: str,
    dry_run: bool,
) -> dict:
    """Import records into DB. Returns summary dict."""
    db = Database()

    companies_inserted = 0
    contacts_inserted = 0
    companies_skipped = 0
    contacts_skipped = 0
    errors = []
    domain_conflicts = []
    companies_seen: dict[str, str] = {}  # name → company_id

    for company_data, contact_data in records:
        company_name = company_data.get("name", "")

        # --- Company ---
        company_id: str | None = None

        # Check in-batch cache first
        dedup_key = (company_data.get("apollo_id") or company_data.get("domain") or company_name).lower()
        if dedup_key in companies_seen:
            company_id = companies_seen[dedup_key]
        else:
            # Check DB
            existing = None
            if company_data.get("apollo_id"):
                existing = db.get_company_by_apollo_id(company_data["apollo_id"])
            if not existing and company_data.get("domain"):
                existing = db.get_company_by_domain(company_data["domain"])
                if existing and existing.get("name", "").lower() != company_name.lower():
                    domain_conflicts.append({
                        "import_name": company_name,
                        "existing_name": existing["name"],
                        "domain": company_data["domain"],
                    })

            if existing:
                company_id = existing["id"]
                companies_skipped += 1
                companies_seen[dedup_key] = company_id
            elif dry_run:
                company_id = f"dry-run-{company_name}"
                companies_seen[dedup_key] = company_id
                companies_inserted += 1
                console.print(f"  [DRY-RUN] Would insert company: [bold]{company_name}[/bold]")
            else:
                try:
                    insert_data = {
                        **{k: v for k, v in company_data.items() if v is not None},
                        "status": "discovered",
                        "campaign_name": campaign_name,
                    }
                    new_company = db.insert_company(insert_data)
                    company_id = new_company.get("id")
                    companies_seen[dedup_key] = company_id
                    companies_inserted += 1
                    console.print(f"  [green]✓[/green] Inserted company: {company_name}")
                except Exception as e:
                    errors.append(f"Company '{company_name}': {e}")
                    console.print(f"  [red]✗ Company error: {company_name}: {e}[/red]")
                    continue

        # --- Contact ---
        if not contact_data.get("full_name") and not contact_data.get("first_name"):
            continue

        persona_type, is_dm = classify_persona(contact_data.get("title"))

        if dry_run:
            contacts_inserted += 1
            console.print(
                f"    [DRY-RUN] Would insert contact: "
                f"{contact_data.get('full_name', '?')} ({contact_data.get('title', '?')})"
            )
        else:
            # Check for existing contact
            if contact_data.get("apollo_id"):
                existing_contact = db.get_contact_by_apollo_id(contact_data["apollo_id"])
                if existing_contact:
                    contacts_skipped += 1
                    continue

            try:
                contact_insert = {
                    **{k: v for k, v in contact_data.items() if v is not None},
                    "company_id": company_id,
                    "persona_type": persona_type,
                    "is_decision_maker": is_dm,
                    "enrichment_status": "enriched" if contact_data.get("email") else "needs_enrichment",
                }
                db.insert_contact(contact_insert)
                contacts_inserted += 1
            except Exception as e:
                name = contact_data.get("full_name", "?")
                errors.append(f"Contact '{name}': {e}")
                console.print(f"  [red]✗ Contact error: {name}: {e}[/red]")

    return {
        "companies_inserted": companies_inserted,
        "contacts_inserted": contacts_inserted,
        "companies_skipped": companies_skipped,
        "contacts_skipped": contacts_skipped,
        "errors": errors,
        "domain_conflicts": domain_conflicts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import prospects from CSV or JSON with validation")
    parser.add_argument("--file", required=True, help="Path to CSV or JSON file")
    parser.add_argument("--campaign", default="prospectiq_discovery", help="Campaign name to tag records with")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without writing to DB")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        sys.exit(1)

    # Validate ICP before import
    icp = get_icp_config()
    validate_and_exit_on_error(icp)

    # Load file
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        raw_rows = load_csv(file_path)
        records = [normalize_csv_row(row) for row in raw_rows]
    elif suffix == ".json":
        raw_data = load_json(file_path)
        # Support both flat list and nested {company, contacts} format
        records = []
        for item in raw_data:
            if "contacts" in item:
                company_data = {k: v for k, v in item.items() if k != "contacts"}
                for c in item["contacts"]:
                    records.append((company_data, c))
            else:
                company_data, contact_data = normalize_csv_row(item)
                records.append((company_data, contact_data))
    else:
        console.print(f"[red]Unsupported file type: {suffix} (expected .csv or .json)[/red]")
        sys.exit(1)

    console.print(f"[cyan]Loaded {len(records)} records from {file_path.name}[/cyan]")

    # Validate rows
    validation_errors = []
    for i, (company_data, contact_data) in enumerate(records):
        errs = validate_row(company_data, contact_data)
        for err in errs:
            validation_errors.append(f"Row {i+1}: {err}")

    if validation_errors:
        console.print(f"\n[bold red]{len(validation_errors)} validation errors:[/bold red]")
        for err in validation_errors[:20]:
            console.print(f"  [red]• {err}[/red]")
        if not args.dry_run:
            console.print("[red]Fix errors before importing. Use --dry-run to preview.[/red]")
            sys.exit(1)

    if args.dry_run:
        console.print("\n[yellow][DRY-RUN] No database writes will occur.[/yellow]")

    # Run import
    console.print(f"\n[bold]Importing to campaign: [cyan]{args.campaign}[/cyan][/bold]")
    summary = run_import(records, campaign_name=args.campaign, dry_run=args.dry_run)

    # Print summary
    console.print(f"\n[bold]Import {'Preview' if args.dry_run else 'Complete'}:[/bold]")
    console.print(f"  Companies: [green]{summary['companies_inserted']} inserted[/green], "
                  f"[dim]{summary['companies_skipped']} skipped (existing)[/dim]")
    console.print(f"  Contacts:  [green]{summary['contacts_inserted']} inserted[/green], "
                  f"[dim]{summary['contacts_skipped']} skipped (existing)[/dim]")

    if summary["domain_conflicts"]:
        console.print(f"\n[bold yellow]{len(summary['domain_conflicts'])} domain conflicts (same domain, different company name):[/bold yellow]")
        for conflict in summary["domain_conflicts"]:
            console.print(
                f"  Import: [yellow]{conflict['import_name']}[/yellow] ↔ "
                f"DB: [yellow]{conflict['existing_name']}[/yellow] "
                f"(domain: {conflict['domain']})"
            )

    if summary["errors"]:
        console.print(f"\n[bold red]{len(summary['errors'])} errors:[/bold red]")
        for err in summary["errors"]:
            console.print(f"  [red]• {err}[/red]")


if __name__ == "__main__":
    main()
