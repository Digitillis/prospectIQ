"""ProspectIQ health dashboard.

Rich CLI showing pipeline health at a glance:
total companies by tier, enrichment coverage, contacts ready to send,
Apollo credits used, pace limiter status, and unresolved contacts.

Usage:
    python -m backend.scripts.dashboard
    python -m backend.scripts.dashboard --campaign tier0-mfg-pdm-roi
"""

from __future__ import annotations

import argparse
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich import box

from backend.app.core.database import Database
from backend.app.core.pace_limiter import check_all_campaigns, CAMPAIGN_DEFAULTS

console = Console()


def fetch_company_stats(db: Database, campaign_name: str | None) -> dict:
    """Aggregate company-level stats."""
    query = db.client.table("companies").select(
        "id, tier, status, campaign_name, domain"
    )
    if campaign_name:
        query = query.eq("campaign_name", campaign_name)
    companies = query.execute().data

    total = len(companies)
    by_tier: dict[str, int] = {}
    statuses: dict[str, int] = {}
    missing_domain = 0

    for c in companies:
        tier = str(c.get("tier") or "?")
        by_tier[tier] = by_tier.get(tier, 0) + 1
        status = c.get("status") or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
        if not c.get("domain"):
            missing_domain += 1

    return {
        "total": total,
        "by_tier": dict(sorted(by_tier.items())),
        "statuses": statuses,
        "missing_domain": missing_domain,
    }


def fetch_contact_stats(db: Database, campaign_name: str | None) -> dict:
    """Aggregate contact-level stats."""
    # Get companies in campaign
    company_query = db.client.table("companies").select("id")
    if campaign_name:
        company_query = company_query.eq("campaign_name", campaign_name)
    company_ids = [c["id"] for c in company_query.execute().data]

    if not company_ids:
        return {
            "total": 0,
            "enriched": 0,
            "needs_enrichment": 0,
            "failed": 0,
            "stale": 0,
            "ready_to_send": 0,
            "missing_email": 0,
            "missing_phone": 0,
            "avg_score": 0,
        }

    contacts_result = db.client.table("contacts").select(
        "id, enrichment_status, completeness_score, email, phone"
    ).in_("company_id", company_ids).execute()
    contacts = contacts_result.data

    total = len(contacts)
    enriched = sum(1 for c in contacts if c.get("enrichment_status") == "enriched" or (c.get("completeness_score") or 0) >= 60)
    needs_enrichment = sum(1 for c in contacts if c.get("enrichment_status") == "needs_enrichment")
    failed = sum(1 for c in contacts if c.get("enrichment_status") == "failed")
    stale = sum(1 for c in contacts if c.get("enrichment_status") == "stale")
    ready_to_send = sum(
        1 for c in contacts
        if c.get("email") and (c.get("completeness_score") or 0) >= 60
    )
    missing_email = sum(1 for c in contacts if not c.get("email"))
    missing_phone = sum(1 for c in contacts if not c.get("phone"))
    scores = [c.get("completeness_score") or 0 for c in contacts]
    avg_score = round(sum(scores) / max(len(scores), 1), 1)

    return {
        "total": total,
        "enriched": enriched,
        "needs_enrichment": needs_enrichment,
        "failed": failed,
        "stale": stale,
        "ready_to_send": ready_to_send,
        "missing_email": missing_email,
        "missing_phone": missing_phone,
        "avg_score": avg_score,
    }


def fetch_credit_stats(db: Database, campaign_name: str | None) -> dict:
    """Fetch Apollo credit usage."""
    try:
        total_credits = db.get_apollo_credits_used(campaign_name=campaign_name)
    except Exception:
        total_credits = 0

    try:
        today_result = db.client.table("apollo_credit_events").select(
            "credits_used"
        ).gte("created_at", date.today().isoformat()).execute()
        credits_today = sum(r.get("credits_used", 0) for r in today_result.data)
    except Exception:
        credits_today = 0

    return {
        "total": total_credits,
        "today": credits_today,
    }


def fetch_pace_stats() -> dict:
    """Fetch pace limiter status for all campaigns."""
    try:
        return check_all_campaigns()
    except Exception:
        return {}


def print_dashboard(
    company_stats: dict,
    contact_stats: dict,
    credit_stats: dict,
    pace_stats: dict,
    campaign_name: str | None,
) -> None:
    today = date.today().strftime("%A, %B %d %Y")

    title = f"ProspectIQ Dashboard — {today}"
    if campaign_name:
        title += f"  [dim]({campaign_name})[/dim]"

    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    console.print()

    # --- Companies panel ---
    company_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    company_table.add_column("Metric", style="dim", min_width=20)
    company_table.add_column("Value", min_width=10)
    company_table.add_row("Total companies", f"[bold]{company_stats['total']}[/bold]")
    company_table.add_row("Missing domain", f"[yellow]{company_stats['missing_domain']}[/yellow]")
    company_table.add_row("", "")
    for tier, count in company_stats["by_tier"].items():
        company_table.add_row(f"  Tier {tier}", str(count))

    # --- Contacts panel ---
    contact_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    contact_table.add_column("Metric", style="dim", min_width=22)
    contact_table.add_column("Value", min_width=10)

    cs = contact_stats
    enriched_pct = round(cs["enriched"] / max(cs["total"], 1) * 100)
    ready_pct = round(cs["ready_to_send"] / max(cs["total"], 1) * 100)

    contact_table.add_row("Total contacts", f"[bold]{cs['total']}[/bold]")
    contact_table.add_row("Enriched", f"[green]{cs['enriched']}[/green] [dim]({enriched_pct}%)[/dim]")
    contact_table.add_row("Ready to send", f"[green]{cs['ready_to_send']}[/green] [dim]({ready_pct}%)[/dim]")
    contact_table.add_row("Needs enrichment", f"[yellow]{cs['needs_enrichment']}[/yellow]")
    contact_table.add_row("Failed enrichment", f"[red]{cs['failed']}[/red]" if cs['failed'] else "0")
    contact_table.add_row("Stale", f"[dim]{cs['stale']}[/dim]")
    contact_table.add_row("Missing email", f"[dim]{cs['missing_email']}[/dim]")
    contact_table.add_row("Avg completeness", f"{cs['avg_score']}/100")

    # --- Credits panel ---
    credits_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    credits_table.add_column("Metric", style="dim", min_width=20)
    credits_table.add_column("Value", min_width=10)
    credits_table.add_row("Total credits used", f"[bold]{credit_stats['total']}[/bold]")
    credits_table.add_row("Credits today", str(credit_stats["today"]))

    # --- Pace panel ---
    pace_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    pace_table.add_column("Campaign", style="dim", min_width=24)
    pace_table.add_column("Sent / Limit", min_width=12)
    pace_table.add_column("Remaining", min_width=10)

    if pace_stats:
        for camp, info in pace_stats.items():
            sent = info.get("sends_today", 0)
            limit = info.get("daily_limit", 10)
            remaining = info.get("remaining", limit - sent)
            limit_reached = info.get("limit_reached", False)
            remaining_str = (
                f"[red]{remaining}[/red]" if limit_reached else
                f"[green]{remaining}[/green]" if remaining > 3 else
                f"[yellow]{remaining}[/yellow]"
            )
            pace_table.add_row(camp, f"{sent}/{limit}", remaining_str)
    else:
        pace_table.add_row("[dim]No outreach recorded yet[/dim]", "", "")

    # Render panels side by side
    panels = [
        Panel(company_table, title="[bold]Companies[/bold]", border_style="cyan"),
        Panel(contact_table, title="[bold]Contacts[/bold]", border_style="cyan"),
        Panel(credits_table, title="[bold]Apollo Credits[/bold]", border_style="cyan"),
    ]
    console.print(Columns(panels, equal=False, expand=False))

    console.print(Panel(pace_table, title="[bold]Daily Pace (Today)[/bold]", border_style="green"))

    # Quick health indicators
    issues = []
    if company_stats["missing_domain"] > 0:
        issues.append(f"[yellow]⚠ {company_stats['missing_domain']} companies missing domain[/yellow]")
    if contact_stats["failed"] > 0:
        issues.append(f"[red]✗ {contact_stats['failed']} contacts with failed enrichment[/red]")
    if contact_stats["needs_enrichment"] > 10:
        issues.append(f"[yellow]⚠ {contact_stats['needs_enrichment']} contacts need enrichment[/yellow]")
    if contact_stats["total"] > 0 and contact_stats["ready_to_send"] == 0:
        issues.append("[red]✗ Zero contacts are ready to send[/red]")

    if issues:
        console.print("\n[bold]Action Items:[/bold]")
        for issue in issues:
            console.print(f"  {issue}")
    else:
        console.print("\n[green]✅ All systems healthy[/green]")

    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="ProspectIQ health dashboard")
    parser.add_argument("--campaign", help="Filter by campaign name")
    args = parser.parse_args()

    db = Database()

    company_stats = fetch_company_stats(db, args.campaign)
    contact_stats = fetch_contact_stats(db, args.campaign)
    credit_stats = fetch_credit_stats(db, args.campaign)
    pace_stats = fetch_pace_stats()

    print_dashboard(company_stats, contact_stats, credit_stats, pace_stats, args.campaign)


if __name__ == "__main__":
    main()
