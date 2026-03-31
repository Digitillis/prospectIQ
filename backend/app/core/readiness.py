"""Campaign readiness gate.

Checks each company in a campaign against a set of hard blockers and
soft warnings before any outreach is enrolled in Instantly.

Hard blockers (is_ready = False):
  - No enriched contacts (completeness_score >= 60)
  - No domain set on the company

Warnings (is_ready = True but flagged):
  - Fewer than 2 enriched contacts
  - Any contacts with enrichment_status = 'failed'
  - Company has no apollo_id

Usage:
    from backend.app.core.readiness import check_campaign_readiness
    results = check_campaign_readiness("tier0-mfg-pdm-roi")
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database
from backend.app.core.models import ReadinessCheck

console = Console()

MIN_COMPLETENESS_SCORE = 60   # contact must score >= this to count as "enriched"
MIN_ENRICHED_CONTACTS = 1     # hard blocker: at least 1 send-ready contact required
WARN_ENRICHED_CONTACTS = 2    # soft warning: < 2 enriched contacts


def check_campaign_readiness(
    campaign_name: str,
    tier: str | None = None,
    print_report: bool = True,
) -> list[ReadinessCheck]:
    """Run the readiness gate for all companies in a campaign.

    Args:
        campaign_name: The campaign_name column value to filter on.
        tier: Optional tier filter (e.g. 'mfg1', 'fb1').
        print_report: If True, print a Rich table summary.

    Returns:
        List of ReadinessCheck results, one per company.
    """
    db = Database()

    # Fetch companies
    query = db.client.table("companies").select("id, name, domain, apollo_id, campaign_name, tier, status")
    query = query.eq("campaign_name", campaign_name)
    if tier:
        query = query.eq("tier", tier)
    companies = query.order("name").execute().data

    if not companies:
        console.print(f"[yellow]No companies found for campaign '{campaign_name}'.[/yellow]")
        return []

    results: list[ReadinessCheck] = []

    for company in companies:
        company_id = company["id"]
        contacts = db.get_contacts_for_company(company_id)

        enriched = [
            c for c in contacts
            if (c.get("completeness_score") or 0) >= MIN_COMPLETENESS_SCORE
            or c.get("enrichment_status") == "enriched"
        ]
        failed = [c for c in contacts if c.get("enrichment_status") == "failed"]

        blockers: list[str] = []
        warnings: list[str] = []

        # Hard blockers
        if not company.get("domain"):
            blockers.append("No domain — required for email deliverability verification")

        if len(enriched) < MIN_ENRICHED_CONTACTS:
            blockers.append(
                f"No send-ready contacts (completeness ≥ {MIN_COMPLETENESS_SCORE} or enrichment_status='enriched'). "
                f"Found {len(contacts)} total, {len(enriched)} enriched."
            )

        # Soft warnings
        if 0 < len(enriched) < WARN_ENRICHED_CONTACTS:
            warnings.append(f"Only {len(enriched)} enriched contact — aim for 2+ per company")

        if failed:
            warnings.append(f"{len(failed)} contact(s) have enrichment_status='failed' — needs manual review")

        if not company.get("apollo_id"):
            warnings.append("No company apollo_id — domain inference may be less accurate")

        check = ReadinessCheck(
            company_id=company_id,
            company_name=company["name"],
            campaign_name=campaign_name,
            is_ready=len(blockers) == 0,
            blockers=blockers,
            warnings=warnings,
            enriched_contacts=len(enriched),
            total_contacts=len(contacts),
            has_domain=bool(company.get("domain")),
        )
        results.append(check)

    if print_report:
        _print_report(results, campaign_name)

    return results


def assert_campaign_ready(campaign_name: str, tier: str | None = None) -> None:
    """Raise RuntimeError if any company in the campaign fails the readiness gate."""
    results = check_campaign_readiness(campaign_name, tier=tier, print_report=True)
    not_ready = [r for r in results if not r.is_ready]
    if not_ready:
        names = ", ".join(r.company_name for r in not_ready)
        raise RuntimeError(
            f"Campaign '{campaign_name}' is NOT ready. "
            f"{len(not_ready)} company(s) failed the gate: {names}. "
            f"Fix blockers before enrolling in Instantly."
        )


def _print_report(results: list[ReadinessCheck], campaign_name: str) -> None:
    total = len(results)
    ready = sum(1 for r in results if r.is_ready)
    not_ready = total - ready

    console.print(f"\n[bold]Campaign Readiness: {campaign_name}[/bold]")
    console.print(f"  {ready}/{total} companies ready  ·  {not_ready} blocked\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Company", min_width=28)
    table.add_column("Ready", justify="center", min_width=6)
    table.add_column("Enriched", justify="center", min_width=8)
    table.add_column("Domain", justify="center", min_width=6)
    table.add_column("Blockers / Warnings", min_width=40)

    for r in sorted(results, key=lambda x: (x.is_ready, x.company_name)):
        status = "[green]✅[/green]" if r.is_ready else "[red]❌[/red]"
        domain = "[green]✓[/green]" if r.has_domain else "[red]✗[/red]"
        enriched_str = f"{r.enriched_contacts}/{r.total_contacts}"

        issues: list[str] = []
        for b in r.blockers:
            issues.append(f"[red]BLOCK: {b[:70]}[/red]")
        for w in r.warnings:
            issues.append(f"[yellow]WARN: {w[:70]}[/yellow]")
        issues_str = "\n".join(issues) if issues else "[dim]—[/dim]"

        table.add_row(r.company_name[:30], status, enriched_str, domain, issues_str)

    console.print(table)
