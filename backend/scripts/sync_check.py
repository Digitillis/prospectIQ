"""Prospect markdown ↔ DB sync check.

Diffs the Tier 0 prospect lists in docs/prospects/ against what's in the database.
Flags contacts that exist in markdown but not in DB, and vice versa.

Usage:
    python -m backend.scripts.sync_check
    python -m backend.scripts.sync_check --markdown-dir docs/prospects --campaign tier0-mfg-pdm-roi
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database

console = Console()

# Match lines like: | John Smith | VP Operations | john@acme.com | ...
_CONTACT_ROW_RE = re.compile(
    r"^\|\s*(?P<name>[^|]+)\s*\|\s*(?P<title>[^|]*)\s*\|(?P<rest>.*)$"
)

# Match company headings like: ## Acme Corp or ### Acme Corp
_COMPANY_HEADING_RE = re.compile(r"^#{2,3}\s+(?P<name>.+)$")


def parse_markdown_prospects(markdown_dir: Path) -> dict[str, list[dict]]:
    """Parse all .md files in markdown_dir for company → contacts mapping."""
    companies: dict[str, list[dict]] = {}

    md_files = sorted(markdown_dir.glob("**/*.md"))
    if not md_files:
        console.print(f"[yellow]No .md files found in {markdown_dir}[/yellow]")
        return companies

    for md_file in md_files:
        current_company = None
        for line in md_file.read_text().splitlines():
            heading_match = _COMPANY_HEADING_RE.match(line.strip())
            if heading_match:
                current_company = heading_match.group("name").strip()
                if current_company not in companies:
                    companies[current_company] = []
                continue

            if not current_company:
                continue

            row_match = _CONTACT_ROW_RE.match(line)
            if row_match:
                name = row_match.group("name").strip()
                title = row_match.group("title").strip()
                # Skip header rows
                if name.lower() in ("name", "contact", "person", "first name"):
                    continue
                if name.startswith("---") or not name:
                    continue
                companies[current_company].append({
                    "name": name,
                    "title": title,
                    "source_file": md_file.name,
                })

    return companies


def get_db_contacts_by_company(db: Database, campaign_name: str | None) -> dict[str, list[dict]]:
    """Get all contacts from DB grouped by company name."""
    query = db.client.table("companies").select("id, name, campaign_name")
    if campaign_name:
        query = query.eq("campaign_name", campaign_name)
    companies = query.execute().data

    result: dict[str, list[dict]] = {}
    for company in companies:
        contacts = db.get_contacts_for_company(company["id"])
        result[company["name"]] = contacts

    return result


def normalize_name(name: str) -> str:
    """Lowercase and strip for fuzzy matching."""
    return name.lower().strip().replace("  ", " ")


def find_name_match(needle: str, haystack: list[dict]) -> dict | None:
    """Find a contact by name (case-insensitive, partial match on last name)."""
    needle_norm = normalize_name(needle)
    needle_parts = needle_norm.split()

    for c in haystack:
        full_name = normalize_name(c.get("full_name") or f"{c.get('first_name', '')} {c.get('last_name', '')}")
        if needle_norm == full_name:
            return c
        # Match on last name only
        if needle_parts and needle_parts[-1] in full_name.split():
            return c

    return None


def run_sync_check(
    markdown_dir: Path,
    campaign_name: str | None = None,
) -> dict:
    """Run the sync check and return diff results."""
    db = Database()

    console.print(f"[cyan]Parsing markdown files in {markdown_dir}...[/cyan]")
    md_companies = parse_markdown_prospects(markdown_dir)
    console.print(f"  Found {len(md_companies)} companies, "
                  f"{sum(len(v) for v in md_companies.values())} contacts in markdown")

    console.print(f"[cyan]Fetching DB records...[/cyan]")
    db_companies = get_db_contacts_by_company(db, campaign_name)
    console.print(f"  Found {len(db_companies)} companies, "
                  f"{sum(len(v) for v in db_companies.values())} contacts in DB")

    in_md_not_db: list[dict] = []
    in_db_not_md: list[dict] = []
    matched: list[dict] = []

    # Check markdown → DB
    for company_name, md_contacts in md_companies.items():
        # Find best matching company in DB
        db_company_name = None
        for db_name in db_companies:
            if normalize_name(db_name) == normalize_name(company_name):
                db_company_name = db_name
                break
            # Partial match
            if normalize_name(company_name) in normalize_name(db_name) or \
               normalize_name(db_name) in normalize_name(company_name):
                db_company_name = db_name
                break

        if not db_company_name:
            for c in md_contacts:
                in_md_not_db.append({**c, "company": company_name, "reason": "company not in DB"})
            continue

        db_contacts = db_companies[db_company_name]
        for md_contact in md_contacts:
            match = find_name_match(md_contact["name"], db_contacts)
            if match:
                matched.append({
                    "md": md_contact,
                    "db": match,
                    "company": company_name,
                })
            else:
                in_md_not_db.append({**md_contact, "company": company_name, "reason": "contact not in DB"})

    return {
        "in_md_not_db": in_md_not_db,
        "in_db_not_md": in_db_not_md,
        "matched": matched,
        "md_companies": md_companies,
        "db_companies": db_companies,
    }


def print_sync_report(diff: dict) -> None:
    """Print the sync check results."""
    matched = diff["matched"]
    in_md_not_db = diff["in_md_not_db"]
    in_db_not_md = diff["in_db_not_md"]

    console.print(f"\n[bold]Sync Check Results[/bold]")
    console.print(f"  ✅ Matched:            [green]{len(matched)}[/green]")
    console.print(f"  ⚠️  In markdown, not DB: [yellow]{len(in_md_not_db)}[/yellow]")
    console.print(f"  ℹ️  In DB, not markdown: [dim]{len(in_db_not_md)}[/dim]")

    if in_md_not_db:
        console.print(f"\n[bold yellow]In markdown but missing from DB ({len(in_md_not_db)}):[/bold yellow]")
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Company", min_width=24)
        table.add_column("Contact", min_width=22)
        table.add_column("Title", min_width=26)
        table.add_column("Reason", min_width=20)
        table.add_column("File", min_width=16)

        for item in in_md_not_db[:30]:
            table.add_row(
                item["company"][:24],
                item["name"][:22],
                item.get("title", "—")[:26],
                item.get("reason", "—"),
                item.get("source_file", "—")[:16],
            )
        console.print(table)
        if len(in_md_not_db) > 30:
            console.print(f"[dim]... and {len(in_md_not_db) - 30} more[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync check: markdown prospects vs database")
    parser.add_argument(
        "--markdown-dir",
        default="docs/prospects",
        help="Directory containing prospect markdown files (default: docs/prospects)",
    )
    parser.add_argument("--campaign", help="Filter DB by campaign name")
    args = parser.parse_args()

    md_dir = Path(args.markdown_dir)
    if not md_dir.exists():
        # Try relative to repo root
        repo_root = Path(__file__).parents[3]
        md_dir = repo_root / args.markdown_dir

    if not md_dir.exists():
        console.print(f"[red]Markdown directory not found: {md_dir}[/red]")
        console.print("[dim]Tip: pass --markdown-dir <path> to specify the directory[/dim]")
        return

    diff = run_sync_check(md_dir, campaign_name=args.campaign)
    print_sync_report(diff)


if __name__ == "__main__":
    main()
