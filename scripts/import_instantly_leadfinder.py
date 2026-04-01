"""Import leads from Instantly Lead Finder (SuperSearch) into ProspectIQ.

Attempts to pull lead list data directly from Instantly's API, bypassing
the broken UI export flow (Export → Apollo → CSV).

Strategy:
  1. Probe candidate Lead Finder API endpoints to find the working one.
  2. Fetch all lead lists and their leads.
  3. Map each lead → ProspectIQ company + contact records.
  4. Deduplicate by domain and email.
  5. Run initial firmographic PQS scoring.
  6. Print a full reconciliation report.

If the Instantly API does not expose Lead Finder data (all endpoints 404),
the script falls back to accepting a CSV file exported manually from the UI.

Usage:
    # Probe + import from API (attempts auto-discovery):
    python -m scripts.import_instantly_leadfinder

    # Import from a specific list ID:
    python -m scripts.import_instantly_leadfinder --list-id 6784619f-796c-4722-bc52-409058623d08

    # Import all lists:
    python -m scripts.import_instantly_leadfinder --all-lists

    # Dry run (no DB writes):
    python -m scripts.import_instantly_leadfinder --all-lists --dry-run

    # Fallback: import from a CSV exported manually from Instantly/Apollo:
    python -m scripts.import_instantly_leadfinder --csv path/to/leads.csv --industry "Mining & Metals"
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

# Resolve project root so we can import backend modules regardless of cwd
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.app.core.config import get_settings
from backend.app.core.database import Database
from backend.app.agents.discovery import classify_persona

console = Console()
logger = logging.getLogger(__name__)

INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
_RATE_DELAY = 0.5  # seconds between API calls

# ---------------------------------------------------------------------------
# ICP tier assignment based on Instantly list names
# ---------------------------------------------------------------------------

# Maps keywords in list names → ICP tier + campaign_cluster
_LIST_TIER_MAP: list[tuple[str, str, str]] = [
    # (keyword_lower, tier, campaign_cluster)
    ("mining",      "T1", "mining_metals"),
    ("metal",       "T1", "mining_metals"),
    ("chemical",    "T1", "chemicals_plastics"),
    ("plastic",     "T1", "chemicals_plastics"),
    ("machinery",   "T1", "machinery"),
    ("food",        "T2", "food_beverage"),
    ("beverage",    "T2", "food_beverage"),
    ("aviation",    "watchlist", "aerospace"),
    ("aerospace",   "watchlist", "aerospace"),
    ("mfg",        "T1", "general_manufacturing"),
]

_DEFAULT_TIER = "T1"
_DEFAULT_CLUSTER = "general_manufacturing"


def _classify_list(list_name: str) -> tuple[str, str]:
    """Return (tier, campaign_cluster) for a given list name."""
    name_lower = list_name.lower()
    for keyword, tier, cluster in _LIST_TIER_MAP:
        if keyword in name_lower:
            return tier, cluster
    return _DEFAULT_TIER, _DEFAULT_CLUSTER


# ---------------------------------------------------------------------------
# Instantly API client (Lead Finder endpoints)
# ---------------------------------------------------------------------------

class InstantlyLeadFinderClient:
    """Probes and queries Instantly Lead Finder API endpoints."""

    # Candidate endpoint patterns to try for listing lead lists
    _LIST_CANDIDATES = [
        "/lead-finder/lists",
        "/leads/lists",
        "/lists",
        "/supersearch/lists",
        "/prospect/lists",
    ]

    # Candidate patterns for getting leads within a list
    # {list_id} will be substituted
    _LEADS_CANDIDATES = [
        "/lead-finder/lists/{list_id}/leads",
        "/leads/lists/{list_id}/leads",
        "/lead-finder/leads?listId={list_id}",
        "/leads?listId={list_id}",
        "/lists/{list_id}/leads",
        "/supersearch/lists/{list_id}/leads",
    ]

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.instantly_api_key
        if not self.api_key:
            raise ValueError("INSTANTLY_API_KEY must be set in .env")
        self._client = httpx.Client(
            base_url=INSTANTLY_BASE,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._last_call = 0.0
        self._working_lists_endpoint: str | None = None
        self._working_leads_template: str | None = None

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < _RATE_DELAY:
            time.sleep(_RATE_DELAY - elapsed)
        self._last_call = time.time()

    def _get(self, path: str) -> tuple[int, Any]:
        """GET request. Returns (status_code, body_or_None)."""
        self._rate_limit()
        try:
            r = self._client.get(path)
            if r.status_code == 200:
                return 200, r.json()
            return r.status_code, None
        except Exception as e:
            logger.debug(f"Request error for {path}: {e}")
            return 0, None

    def probe_endpoints(self) -> bool:
        """Try all candidate endpoints to find which ones work.

        Returns True if a working lists endpoint was found.
        """
        console.print("\n[bold cyan]Probing Instantly Lead Finder API endpoints...[/bold cyan]")

        for endpoint in self._LIST_CANDIDATES:
            status, body = self._get(endpoint)
            if status == 200:
                console.print(f"  [green]✓ Found working lists endpoint: {endpoint}[/green]")
                self._working_lists_endpoint = endpoint
                return True
            else:
                console.print(f"  [dim]✗ {endpoint} → {status}[/dim]")

        console.print(
            "\n[yellow]No working Lead Finder lists endpoint found.[/yellow]\n"
            "[yellow]The Instantly API does not expose Lead Finder data programmatically.[/yellow]\n"
            "[dim]Use --csv to import from a manually exported file instead.[/dim]"
        )
        return False

    def probe_leads_endpoint(self, list_id: str) -> str | None:
        """Try candidate lead endpoints for a given list_id.

        Returns the working URL template or None.
        """
        for template in self._LEADS_CANDIDATES:
            path = template.replace("{list_id}", list_id)
            status, body = self._get(path)
            if status == 200:
                console.print(f"  [green]✓ Leads endpoint: {path}[/green]")
                self._working_leads_template = template
                return template
            else:
                console.print(f"  [dim]  ✗ {path} → {status}[/dim]")
        return None

    def get_lists(self) -> list[dict]:
        """Fetch all lead lists. Requires probe_endpoints() first."""
        if not self._working_lists_endpoint:
            return []
        _, body = self._get(self._working_lists_endpoint)
        if not body:
            return []
        # Handle both list and dict responses
        if isinstance(body, list):
            return body
        return body.get("data", body.get("lists", body.get("items", [])))

    def get_leads_for_list(self, list_id: str, limit: int = 500) -> list[dict]:
        """Fetch leads for a specific list ID."""
        if not self._working_leads_template:
            template = self.probe_leads_endpoint(list_id)
            if not template:
                return []

        template = self._working_leads_template
        all_leads: list[dict] = []
        skip = 0

        while True:
            # Try paginated and non-paginated variants
            base_path = template.replace("{list_id}", list_id)
            if "?" in base_path:
                path = f"{base_path}&limit={limit}&skip={skip}"
            else:
                path = f"{base_path}?limit={limit}&skip={skip}"

            _, body = self._get(path)
            if not body:
                break

            page: list[dict] = []
            if isinstance(body, list):
                page = body
            else:
                page = body.get("data", body.get("leads", body.get("items", [])))

            all_leads.extend(page)
            if len(page) < limit:
                break
            skip += limit

        return all_leads

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ---------------------------------------------------------------------------
# Lead → ProspectIQ mapper
# ---------------------------------------------------------------------------

def _extract_domain(url_or_email: str) -> str | None:
    """Extract root domain from a URL or email."""
    if not url_or_email:
        return None
    s = url_or_email.strip().lower()
    if "@" in s:
        return s.split("@")[-1].split(".")[0:2] and ".".join(s.split("@")[-1].split(".")[:2])
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.split("/")[0] or None


def _parse_revenue(value: Any) -> int | None:
    """Parse revenue from various formats to integer cents/dollars."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).replace(",", "").replace("$", "").strip().upper()
    multiplier = 1
    if s.endswith("B"):
        multiplier = 1_000_000_000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except ValueError:
        return None


def _parse_employees(value: Any) -> int | None:
    """Parse employee count from various formats."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).replace(",", "").strip()
    # Handle ranges like "500-1000" → take midpoint
    if "-" in s:
        parts = s.split("-")
        try:
            lo = int(re.sub(r"[^\d]", "", parts[0]))
            hi = int(re.sub(r"[^\d]", "", parts[1]))
            return (lo + hi) // 2
        except (ValueError, IndexError):
            pass
    try:
        return int(re.sub(r"[^\d]", "", s))
    except ValueError:
        return None


def _assign_tier(revenue: int | None, employees: int | None) -> str:
    """Assign ICP tier based on revenue / employees."""
    if revenue:
        if 100_000_000 <= revenue <= 400_000_000:
            return "T1"
        if 400_000_000 < revenue <= 1_000_000_000:
            return "T2"
        if 1_000_000_000 < revenue <= 2_000_000_000:
            return "T3"
    # Fall back to employees if revenue unavailable
    if employees:
        if 300 <= employees <= 1_000:
            return "T1"
        if 1_000 < employees <= 3_500:
            return "T2"
    return "T1"  # default — let research / scoring refine


def map_lead_to_records(
    lead: dict,
    list_name: str,
    source_tag: str = "instantly_lead_finder",
) -> tuple[dict, dict]:
    """Map an Instantly Lead Finder lead dict to (company_data, contact_data).

    The lead dict field names vary slightly depending on whether the data
    came from the Instantly API or an Apollo/Instantly CSV export.
    """
    # --- Contact fields ---
    first_name = (
        lead.get("first_name") or lead.get("firstName") or
        lead.get("First Name") or ""
    ).strip()
    last_name = (
        lead.get("last_name") or lead.get("lastName") or
        lead.get("Last Name") or ""
    ).strip()
    full_name = (
        lead.get("full_name") or lead.get("name") or
        f"{first_name} {last_name}".strip()
    )
    title = (
        lead.get("title") or lead.get("Title") or
        lead.get("job_title") or ""
    ).strip()
    email = (
        lead.get("email") or lead.get("work_email") or
        lead.get("Work Email") or lead.get("Email") or ""
    ).strip().lower()
    linkedin_url = (
        lead.get("linkedin_url") or lead.get("LinkedIn") or
        lead.get("linkedin") or ""
    ).strip()
    phone = (lead.get("phone") or lead.get("Phone") or "").strip()

    # --- Company fields ---
    company_name = (
        lead.get("company") or lead.get("company_name") or
        lead.get("Company") or lead.get("organization_name") or ""
    ).strip()
    company_website = (
        lead.get("website") or lead.get("company_website") or
        lead.get("Website") or ""
    ).strip()
    company_linkedin = (
        lead.get("company_linkedin_url") or lead.get("Company LinkedIn") or ""
    ).strip()
    location = (
        lead.get("location") or lead.get("Location") or
        lead.get("city") or ""
    ).strip()

    # Parse state from location string (e.g. "Torrington, Connecticut, United States")
    state = ""
    if location:
        parts = [p.strip() for p in location.split(",")]
        _STATE_ABBR = {
            "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
            "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
            "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
            "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
            "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
            "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
            "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
            "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
            "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
            "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
            "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
            "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
            "wisconsin": "WI", "wyoming": "WY",
        }
        for part in parts:
            p_lower = part.lower().strip()
            if p_lower in _STATE_ABBR:
                state = _STATE_ABBR[p_lower]
                break
            # Try as abbreviation
            if len(p_lower) == 2 and p_lower.upper() in _STATE_ABBR.values():
                state = p_lower.upper()
                break

    revenue_raw = lead.get("annual_revenue") or lead.get("revenue") or lead.get("Revenue")
    employee_raw = (
        lead.get("employee_count") or lead.get("employees") or
        lead.get("num_employees") or lead.get("Employees") or
        lead.get("# Employees")
    )

    revenue = _parse_revenue(revenue_raw)
    employees = _parse_employees(employee_raw)
    domain = _extract_domain(company_website or email)

    list_tier, campaign_cluster = _classify_list(list_name)
    icp_tier = _assign_tier(revenue, employees) if (revenue or employees) else list_tier

    persona_type, is_dm = classify_persona(title)

    company_data: dict = {
        "name": company_name,
        "domain": domain,
        "website": company_website or None,
        "linkedin_url": company_linkedin or None,
        "state": state or None,
        "estimated_revenue": revenue,
        "employee_count": employees,
        "tier": icp_tier,
        "campaign_cluster": campaign_cluster,
        "status": "discovered",
        "source": source_tag,
        "batch_id": f"instantly_lf_{list_name.lower().replace(' ', '_')}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        # Start all dimensions at 0 — qualification agent will score properly
        "pqs_firmographic": 0,
        "pqs_technographic": 0,
        "pqs_timing": 0,
        "pqs_engagement": 0,
        "pqs_total": 0,
    }

    contact_data: dict = {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "title": title,
        "email": email or None,
        "phone": phone or None,
        "linkedin_url": linkedin_url or None,
        "persona_type": persona_type,
        "is_decision_maker": is_dm,
        "status": "identified",
        "outreach_state": "identified",
        "source": source_tag,
    }

    return company_data, contact_data


# ---------------------------------------------------------------------------
# CSV parser (fallback path)
# ---------------------------------------------------------------------------

def parse_csv_file(csv_path: Path) -> list[dict]:
    """Parse a CSV from Instantly/Apollo export into lead dicts."""
    leads = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(dict(row))
    return leads


# ---------------------------------------------------------------------------
# Core import logic
# ---------------------------------------------------------------------------

def import_leads(
    leads: list[dict],
    list_name: str,
    db: Database,
    dry_run: bool = False,
) -> dict:
    """Import a list of lead dicts into ProspectIQ. Returns stats dict."""
    stats = {
        "total": len(leads),
        "companies_created": 0,
        "companies_skipped_dupe": 0,
        "contacts_created": 0,
        "contacts_skipped_dupe": 0,
        "contacts_skipped_no_email": 0,
        "errors": 0,
    }

    for lead in leads:
        try:
            company_data, contact_data = map_lead_to_records(lead, list_name)

            company_name = company_data.get("name", "")
            domain = company_data.get("domain")
            email = contact_data.get("email")

            if not company_name:
                stats["errors"] += 1
                continue

            # --- Upsert company ---
            existing_company = None
            if domain:
                existing_company = db.get_company_by_domain(domain)
            if not existing_company:
                existing_company = db.get_company_by_name(company_name)

            if existing_company:
                company_id = existing_company["id"]
                stats["companies_skipped_dupe"] += 1
            else:
                if dry_run:
                    company_id = f"dry-run-{company_name}"
                    console.print(f"  [dim][DRY RUN] Would create company: {company_name}[/dim]")
                else:
                    result = db.insert_company(company_data)
                    company_id = result.get("id", "")
                stats["companies_created"] += 1

            # --- Upsert contact ---
            if not email:
                stats["contacts_skipped_no_email"] += 1
                continue

            # Check by email
            existing_contact = (
                db.client.table("contacts")
                .select("id")
                .eq("email", email)
                .execute()
                .data
            )

            if existing_contact:
                stats["contacts_skipped_dupe"] += 1
                continue

            contact_data["company_id"] = company_id

            if dry_run:
                full_name = contact_data.get("full_name", "")
                console.print(
                    f"  [dim][DRY RUN] Would create contact: {full_name} "
                    f"<{email}> @ {company_name}[/dim]"
                )
            else:
                db.insert_contact(contact_data)

            stats["contacts_created"] += 1

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Error importing lead: {e}", exc_info=True)

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Instantly Lead Finder leads into ProspectIQ"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all-lists",
        action="store_true",
        help="Fetch and import all Lead Finder lists via API",
    )
    group.add_argument(
        "--list-id",
        metavar="LIST_ID",
        help="Import a specific list by Instantly list ID (e.g. from URL)",
    )
    group.add_argument(
        "--csv",
        metavar="FILE",
        help="Import from a manually exported CSV file (fallback path)",
    )
    parser.add_argument(
        "--list-name",
        metavar="NAME",
        default="Imported",
        help="List name (used for tier assignment when using --csv or --list-id)",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Only probe API endpoints, do not import anything",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without writing to DB",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    db = Database()
    all_stats: list[tuple[str, dict]] = []

    # ------------------------------------------------------------------
    # CSV fallback path
    # ------------------------------------------------------------------
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            console.print(f"[red]File not found: {csv_path}[/red]")
            sys.exit(1)

        console.print(f"\n[bold cyan]Importing from CSV: {csv_path.name}[/bold cyan]")
        leads = parse_csv_file(csv_path)
        console.print(f"[green]Parsed {len(leads)} rows.[/green]")

        stats = import_leads(leads, args.list_name, db, dry_run=args.dry_run)
        all_stats.append((args.list_name, stats))

    # ------------------------------------------------------------------
    # API path
    # ------------------------------------------------------------------
    else:
        with InstantlyLeadFinderClient() as client:

            api_available = client.probe_endpoints()

            if args.probe_only:
                if api_available:
                    console.print("\n[green]API is available. Run without --probe-only to import.[/green]")
                else:
                    console.print("\n[red]API not available. Use --csv for manual import.[/red]")
                return

            if not api_available:
                console.print(
                    "\n[bold red]Instantly Lead Finder API is not accessible.[/bold red]\n"
                    "Export manually from Instantly UI and use:\n"
                    "  python -m scripts.import_instantly_leadfinder "
                    "--csv path/to/file.csv --list-name 'Mining & Metals'\n"
                )
                sys.exit(1)

            if args.list_id:
                # Single list by ID
                list_name = args.list_name
                console.print(f"\n[bold cyan]Fetching leads for list {args.list_id}...[/bold cyan]")
                leads = client.get_leads_for_list(args.list_id)
                console.print(f"[green]{len(leads)} leads fetched.[/green]")
                stats = import_leads(leads, list_name, db, dry_run=args.dry_run)
                all_stats.append((list_name, stats))

            else:
                # All lists
                lists = client.get_lists()
                console.print(f"\n[green]Found {len(lists)} lead lists.[/green]")

                for lst in lists:
                    list_id = lst.get("id") or lst.get("list_id") or lst.get("listId") or ""
                    list_name = lst.get("name") or lst.get("title") or "Unknown"

                    if not list_id:
                        console.print(f"[yellow]Skipping list with no ID: {list_name}[/yellow]")
                        continue

                    console.print(f"\n[bold cyan]Fetching: {list_name} ({list_id})[/bold cyan]")
                    leads = client.get_leads_for_list(list_id)
                    console.print(f"  {len(leads)} leads fetched.")

                    stats = import_leads(leads, list_name, db, dry_run=args.dry_run)
                    all_stats.append((list_name, stats))

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------
    console.print("\n")
    table = Table(title="Import Summary", show_header=True)
    table.add_column("List", style="bold")
    table.add_column("Total", justify="right")
    table.add_column("Co. Created", justify="right")
    table.add_column("Co. Dupes", justify="right")
    table.add_column("Contacts Created", justify="right")
    table.add_column("No Email", justify="right")
    table.add_column("Errors", justify="right")

    total_contacts = 0
    for list_name, s in all_stats:
        table.add_row(
            list_name,
            str(s["total"]),
            str(s["companies_created"]),
            str(s["companies_skipped_dupe"]),
            str(s["contacts_created"]),
            str(s["contacts_skipped_no_email"]),
            str(s["errors"]),
        )
        total_contacts += s["contacts_created"]

    console.print(table)

    if args.dry_run:
        console.print("\n[bold yellow]DRY RUN — no changes written to DB.[/bold yellow]")
    else:
        console.print(
            f"\n[bold green]Import complete.[/bold green] "
            f"{total_contacts} contacts created.\n"
            "Run qualification agent next to score new companies:\n"
            "  python -m backend.scripts.run_qualification\n"
        )


if __name__ == "__main__":
    main()
