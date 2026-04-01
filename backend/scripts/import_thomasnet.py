"""Import manufacturer records from ThomasNet CSV exports into ProspectIQ.

ThomasNet (thomasnet.com) is a purpose-built US manufacturer directory with
500,000+ companies indexed by NAICS/SIC code. It has far better coverage of
small-to-mid-market manufacturers than Apollo's people index — particularly
for sectors with low LinkedIn presence (metal fabrication, job shops, foundries).

HOW TO GET THE DATA
-------------------
1. Go to https://www.thomasnet.com/
2. Search by product category or NAICS code (e.g. "metal fabrication", "injection molding")
3. Filter by: US only, employee count 100–2000, annual sales $25M+
4. Export results as CSV (requires a free ThomasNet account)
5. Run this script against the exported CSV

ThomasNet CSV columns (typical export):
    Company Name, Street, City, State, Zip, Phone, Website/URL,
    Annual Sales, Employees, SIC Code, NAICS Code, Product/Service Description,
    Years in Business, Ownership Type

IDENTIFICATION & REMOVAL
-------------------------
All records imported by this script are tagged with:
  - campaign_name = 'thomasnet_import'       (primary tag — easy to query/delete)
  - custom_tags   = {"source": "thomasnet"}   (secondary tag in JSONB)

To find all ThomasNet companies:
    SELECT * FROM companies WHERE campaign_name = 'thomasnet_import';

To remove all ThomasNet companies (if you abandon the approach):
    DELETE FROM companies WHERE campaign_name = 'thomasnet_import';
    -- Note: will fail if contacts exist. Run contacts cleanup first:
    DELETE FROM contacts WHERE company_id IN (
        SELECT id FROM companies WHERE campaign_name = 'thomasnet_import'
    );
    DELETE FROM companies WHERE campaign_name = 'thomasnet_import';

Usage:
    python -m backend.scripts.import_thomasnet --file path/to/thomasnet_export.csv
    python -m backend.scripts.import_thomasnet --file export.csv --dry-run
    python -m backend.scripts.import_thomasnet --file export.csv --tier mfg2
    python -m backend.scripts.import_thomasnet --file export.csv --min-employees 100 --min-revenue 25000000
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.database import Database
from backend.app.utils.naics import classify_sub_sector
from backend.app.utils.territory import get_territory, is_midwest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
console = Console()

CAMPAIGN_NAME = "thomasnet_import"
SOURCE_TAG = "thomasnet"

# ---------------------------------------------------------------------------
# NAICS prefix → ProspectIQ tier mapping
# Mirrors icp.yaml for classification of ThomasNet records
# ---------------------------------------------------------------------------

NAICS_TIER_MAP: dict[str, str] = {
    "333": "mfg1",   # Industrial Machinery
    "332": "mfg2",   # Metal Fabrication
    "336": "mfg3",   # Automotive / Transportation
    "335": "mfg4",   # Electrical Equipment
    "334": "mfg5",   # Electronics / Semiconductors
    "3364": "mfg6",  # Aerospace & Defense
    "331": "mfg7",   # Primary Metals
    "326": "mfg8",   # Plastics & Rubber
    "325": "pmfg1",  # Chemical
    "211": "pmfg2",  # Oil & Gas Extraction
    "324": "pmfg3",  # Petroleum Refining
    "212": "pmfg4",  # Mining
    "221": "pmfg5",  # Utilities
    "3254": "pmfg6", # Pharma / Biotech
    "322": "pmfg7",  # Paper & Pulp
    "327": "pmfg8",  # Cement / Glass / Ceramics
    "311": "fb1",    # Food Manufacturing
    "312": "fb2",    # Beverage Manufacturing
    "3116": "fb3",   # Meat & Poultry
    "3115": "fb4",   # Dairy
}

# ThomasNet export column name variants (they change slightly between exports)
COLUMN_ALIASES: dict[str, list[str]] = {
    "name":          ["Company Name", "company_name", "Company", "Name", "COMPANY NAME"],
    "street":        ["Street", "Address", "Street Address", "address_line1"],
    "city":          ["City", "CITY"],
    "state":         ["State", "STATE", "State/Province"],
    "zip":           ["Zip", "ZIP", "Postal Code", "zip_code"],
    "phone":         ["Phone", "PHONE", "Telephone", "phone_number"],
    "website":       ["Website", "URL", "Web Address", "website_url", "Domain"],
    "annual_sales":  ["Annual Sales", "Annual Revenue", "Revenue", "annual_revenue", "Sales Volume"],
    "employees":     ["Employees", "Employee Count", "# Employees", "Number of Employees", "employee_count"],
    "sic_code":      ["SIC Code", "SIC", "sic"],
    "naics_code":    ["NAICS Code", "NAICS", "naics"],
    "description":   ["Product/Service Description", "Description", "Products/Services", "Business Description"],
    "years_in_biz":  ["Years in Business", "Founded", "Year Founded", "established"],
    "ownership":     ["Ownership Type", "Ownership", "ownership_type"],
}


def _normalise_header(raw_headers: list[str]) -> dict[str, str]:
    """Map raw CSV headers to canonical field names."""
    header_map: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            for raw in raw_headers:
                if raw.strip().lower() == alias.lower():
                    header_map[raw.strip()] = canonical
                    break
    return header_map


def _parse_revenue(raw: str | None) -> Optional[int]:
    """Parse '$45.2M', '45200000', '45,200,000', '$45M-$50M' → int dollars."""
    if not raw:
        return None
    raw = raw.strip().replace(",", "").replace("$", "").upper()
    # Handle range — take midpoint
    if "-" in raw:
        parts = raw.split("-")
        vals = [_parse_revenue(p) for p in parts]
        vals = [v for v in vals if v]
        return int(sum(vals) / len(vals)) if vals else None
    multiplier = 1
    if raw.endswith("B"):
        multiplier = 1_000_000_000
        raw = raw[:-1]
    elif raw.endswith("M"):
        multiplier = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("K"):
        multiplier = 1_000
        raw = raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return None


def _parse_employees(raw: str | None) -> Optional[int]:
    """Parse '500', '200-500', '501-1000' → int (midpoint for ranges)."""
    if not raw:
        return None
    raw = raw.strip().replace(",", "")
    if "-" in raw:
        parts = raw.split("-")
        try:
            vals = [int(p.strip()) for p in parts if p.strip().isdigit()]
            return int(sum(vals) / len(vals)) if vals else None
        except ValueError:
            return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_naics(raw: str | None) -> Optional[str]:
    """Normalise NAICS code — strip hyphens/spaces, return first 6 digits."""
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9]", "", raw.strip())
    return cleaned[:6] if cleaned else None


def _infer_tier(naics_code: str | None, sic_code: str | None) -> str:
    """Infer the ProspectIQ tier from NAICS (preferred) or SIC code."""
    if naics_code:
        # Try longest prefix match first (6 → 4 → 3 digits)
        for length in (6, 4, 3):
            prefix = naics_code[:length]
            if prefix in NAICS_TIER_MAP:
                return NAICS_TIER_MAP[prefix]
    # Rough SIC → tier fallback
    if sic_code:
        sic = sic_code.strip()[:4]
        sic_int = int(sic) if sic.isdigit() else 0
        if 3310 <= sic_int <= 3399:
            return "mfg7"   # Primary metals / fabrication
        if 3400 <= sic_int <= 3499:
            return "mfg2"   # Fabricated metal products
        if 3500 <= sic_int <= 3599:
            return "mfg1"   # Industrial / commercial machinery
        if 3600 <= sic_int <= 3699:
            return "mfg4"   # Electrical equipment
        if 3700 <= sic_int <= 3799:
            return "mfg3"   # Transportation equipment
        if 2600 <= sic_int <= 2699:
            return "pmfg7"  # Paper
        if 2800 <= sic_int <= 2899:
            return "pmfg1"  # Chemicals
        if 2810 <= sic_int <= 2830:
            return "pmfg6"  # Pharma
        if 3290 <= sic_int <= 3299:
            return "pmfg8"  # Concrete / glass
        if 2000 <= sic_int <= 2099:
            return "fb1"    # Food
        if 2080 <= sic_int <= 2089:
            return "fb2"    # Beverages
    return "mfg1"  # Default — industrial machinery (most common ThomasNet category)


def _domain_from_url(url: str | None) -> Optional[str]:
    """Extract bare domain from a URL string."""
    if not url:
        return None
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    domain = url.split("/")[0].strip()
    return domain if "." in domain else None


def _revenue_range_label(revenue: int | None) -> Optional[str]:
    """Map integer revenue to a human-readable range label."""
    if not revenue:
        return None
    if revenue < 10_000_000:
        return "<$10M"
    if revenue < 25_000_000:
        return "$10M-$25M"
    if revenue < 50_000_000:
        return "$25M-$50M"
    if revenue < 100_000_000:
        return "$50M-$100M"
    if revenue < 250_000_000:
        return "$100M-$250M"
    if revenue < 500_000_000:
        return "$250M-$500M"
    return "$500M+"


def _calc_firmographic_score(
    revenue: int | None,
    employees: int | None,
    state: str | None,
    tier: str,
) -> int:
    """Quick firmographic PQS score — mirrors discovery agent logic."""
    score = 0
    if tier.startswith("mfg"):
        score += 7
    elif tier.startswith("pmfg"):
        score += 6
    elif tier.startswith("fb"):
        score += 3

    if revenue:
        if 25_000_000 <= revenue <= 500_000_000:
            score += 5

    if state:
        if is_midwest(state):
            score += 5
        elif state in {
            "Pennsylvania", "Kentucky", "Tennessee", "North Carolina",
            "Alabama", "Texas", "Georgia", "South Carolina", "Virginia",
        }:
            score += 2

    if employees:
        if 100 <= employees <= 2000:
            score += 3

    return min(score, 25)


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------

def import_thomasnet(
    filepath: Path,
    dry_run: bool = False,
    tier_override: str | None = None,
    min_employees: int = 100,
    min_revenue: int = 25_000_000,
    max_employees: int = 5000,
    max_revenue: int = 500_000_000,
) -> dict:
    """Import a ThomasNet CSV export into ProspectIQ.

    Args:
        filepath: Path to ThomasNet CSV export file.
        dry_run: Preview what would be inserted without writing to DB.
        tier_override: Force all records into this tier (e.g. 'mfg2').
        min_employees: Minimum employee count filter.
        min_revenue: Minimum revenue filter (dollars).
        max_employees: Maximum employee count filter.
        max_revenue: Maximum revenue filter (dollars).

    Returns:
        Dict with counts: inserted, skipped_duplicate, skipped_filter,
        skipped_no_name, errors.
    """
    db = None if dry_run else Database()

    stats = {
        "inserted": 0,
        "skipped_duplicate": 0,
        "skipped_filter": 0,
        "skipped_no_name": 0,
        "errors": 0,
    }
    rows_preview: list[dict] = []

    console.print(f"\n[bold cyan]ThomasNet Import — {filepath.name}[/bold cyan]")
    if dry_run:
        console.print("[yellow][DRY-RUN] No database writes will occur.[/yellow]")
    console.print(
        f"  Filters: employees {min_employees}–{max_employees}, "
        f"revenue ${min_revenue:,}–${max_revenue:,}"
    )

    # --- Read and parse CSV ---
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []
        header_map = _normalise_header(raw_headers)

        if not header_map:
            console.print("[red]ERROR: Could not map any CSV columns. Check column names match ThomasNet export format.[/red]")
            console.print(f"  Found columns: {raw_headers}")
            console.print(f"  Expected one of: {list(COLUMN_ALIASES.keys())}")
            sys.exit(1)

        console.print(f"  Mapped {len(header_map)}/{len(raw_headers)} columns from CSV")

        records = list(reader)

    console.print(f"  Total rows in CSV: {len(records)}")

    for row in records:
        # Remap columns to canonical names
        data: dict = {}
        for raw_col, canonical in header_map.items():
            data[canonical] = row.get(raw_col, "").strip() or None

        try:
            name = data.get("name")
            if not name:
                stats["skipped_no_name"] += 1
                continue

            revenue = _parse_revenue(data.get("annual_sales"))
            employees = _parse_employees(data.get("employees"))
            naics_raw = _parse_naics(data.get("naics_code"))
            sic_raw = data.get("sic_code", "").strip() if data.get("sic_code") else None
            state = data.get("state")
            website = data.get("website")
            domain = _domain_from_url(website)
            phone = data.get("phone")
            city = data.get("city")
            description = data.get("description")

            # --- Size / revenue filter ---
            emp_ok = (employees is None) or (min_employees <= employees <= max_employees)
            rev_ok = (revenue is None) or (min_revenue <= revenue <= max_revenue)
            # If both are None we can't filter — include tentatively (research will score)
            both_unknown = (employees is None and revenue is None)

            if not both_unknown and not (emp_ok and rev_ok):
                stats["skipped_filter"] += 1
                continue

            # --- Tier classification ---
            tier = tier_override or _infer_tier(naics_raw, sic_raw)
            firmographic_score = _calc_firmographic_score(revenue, employees, state, tier)

            company_payload = {
                "name": name,
                "domain": domain,
                "website": website,
                "phone": phone,
                "city": city,
                "state": state,
                "country": "United States",
                "naics_code": naics_raw,
                "tier": tier,
                "employee_count": employees,
                "estimated_revenue": revenue,
                "revenue_range": _revenue_range_label(revenue),
                "research_summary": description,
                "territory": get_territory(state) if state else None,
                "pqs_firmographic": firmographic_score,
                "pqs_total": firmographic_score,
                "status": "discovered",
                "campaign_name": CAMPAIGN_NAME,
                "custom_tags": json.dumps({"source": SOURCE_TAG, "import_date": str(date.today())}),
            }

            if dry_run:
                stats["inserted"] += 1
                rows_preview.append({
                    "name": name,
                    "state": state or "?",
                    "tier": tier,
                    "employees": str(employees) if employees else "?",
                    "revenue": f"${revenue:,}" if revenue else "?",
                    "pqs": str(firmographic_score),
                    "status": "[cyan]would insert[/cyan]",
                })
                continue

            # --- Deduplication: check by domain, then by name ---
            existing = None
            if domain:
                existing = db.get_company_by_domain(domain)
            if not existing:
                existing = db.get_company_by_name(name)

            if existing:
                stats["skipped_duplicate"] += 1
                rows_preview.append({
                    "name": name,
                    "state": state or "?",
                    "tier": tier,
                    "employees": str(employees) if employees else "?",
                    "revenue": f"${revenue:,}" if revenue else "?",
                    "pqs": str(firmographic_score),
                    "status": "[dim]duplicate — skipped[/dim]",
                })
                continue

            db.insert_company(company_payload)
            stats["inserted"] += 1
            rows_preview.append({
                "name": name,
                "state": state or "?",
                "tier": tier,
                "employees": str(employees) if employees else "?",
                "revenue": f"${revenue:,}" if revenue else "?",
                "pqs": str(firmographic_score),
                "status": "[green]inserted[/green]",
            })

        except Exception as e:
            logger.error(f"Error processing row '{data.get('name', '?')}': {e}")
            stats["errors"] += 1

    # --- Summary table (show first 50 rows) ---
    if rows_preview:
        table = Table(title=f"ThomasNet Import — {'DRY RUN ' if dry_run else ''}Results (first 50 shown)")
        table.add_column("Company", max_width=32)
        table.add_column("State", max_width=4)
        table.add_column("Tier", max_width=8)
        table.add_column("Employees", max_width=10)
        table.add_column("Revenue", max_width=14)
        table.add_column("PQS", max_width=4)
        table.add_column("Status")
        for r in rows_preview[:50]:
            table.add_row(
                r["name"], r["state"], r["tier"],
                r["employees"], r["revenue"], r["pqs"], r["status"],
            )
        console.print()
        console.print(table)

    console.print()
    console.print(
        f"[bold green]Done.[/bold green]  "
        f"Inserted: {stats['inserted']}  |  "
        f"Duplicates skipped: {stats['skipped_duplicate']}  |  "
        f"Filtered out: {stats['skipped_filter']}  |  "
        f"No name: {stats['skipped_no_name']}  |  "
        f"Errors: {stats['errors']}"
    )
    if not dry_run and stats["inserted"] > 0:
        console.print(
            f"\n[dim]All inserted records tagged with "
            f"campaign_name='thomasnet_import' and custom_tags.source='thomasnet'[/dim]"
        )
        console.print(
            "[dim]To remove: DELETE FROM contacts WHERE company_id IN "
            "(SELECT id FROM companies WHERE campaign_name='thomasnet_import'); "
            "DELETE FROM companies WHERE campaign_name='thomasnet_import';[/dim]"
        )

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import ThomasNet CSV export into ProspectIQ.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
HOW TO EXPORT FROM THOMASNET
  1. Search thomasnet.com by category (e.g. "metal fabrication", "industrial machinery")
  2. Filter: United States, 100-2000 employees, $25M+ annual sales
  3. Click Export / Download CSV (requires free ThomasNet account)
  4. Run: python -m backend.scripts.import_thomasnet --file export.csv --dry-run

TAGGING (for easy removal if needed)
  campaign_name = 'thomasnet_import'
  custom_tags   = {"source": "thomasnet"}

  To remove all ThomasNet companies:
    DELETE FROM contacts WHERE company_id IN
      (SELECT id FROM companies WHERE campaign_name='thomasnet_import');
    DELETE FROM companies WHERE campaign_name='thomasnet_import';
        """,
    )
    parser.add_argument("--file", required=True, help="Path to ThomasNet CSV export")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--tier", default=None, help="Force all records into this tier (e.g. mfg2)")
    parser.add_argument("--min-employees", type=int, default=100, help="Min employees (default 100)")
    parser.add_argument("--max-employees", type=int, default=5000, help="Max employees (default 5000)")
    parser.add_argument("--min-revenue", type=int, default=25_000_000, help="Min revenue dollars (default 25000000)")
    parser.add_argument("--max-revenue", type=int, default=500_000_000, help="Max revenue dollars (default 500000000)")
    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        console.print(f"[red]File not found: {filepath}[/red]")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()

    import_thomasnet(
        filepath=filepath,
        dry_run=args.dry_run,
        tier_override=args.tier,
        min_employees=args.min_employees,
        min_revenue=args.min_revenue,
        max_employees=args.max_employees,
        max_revenue=args.max_revenue,
    )
