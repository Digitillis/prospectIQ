"""Company domain inference via Apollo organization enrichment.

When a company record has no domain, this module calls Apollo's free
/organizations/enrich endpoint (no people credits) to discover it.

Usage:
    from backend.app.core.domain_inference import infer_missing_domains
    infer_missing_domains(dry_run=False)
"""

from __future__ import annotations

import logging
import time

import httpx
from rich.console import Console

from backend.app.core.config import get_settings
from backend.app.core.database import Database

console = Console()
logger = logging.getLogger(__name__)

APOLLO_ORG_ENRICH_URL = "https://api.apollo.io/v1/organizations/enrich"
RATE_LIMIT_SLEEP = 1.2  # seconds between calls (Apollo rate limit: ~50 req/min)


def _clean_domain(raw: str | None) -> str | None:
    """Strip protocol, www, and trailing slashes from a domain."""
    if not raw:
        return None
    domain = raw.strip().lower()
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.rstrip("/").split("/")[0]
    return domain if "." in domain else None


def infer_domain_for_company(
    company: dict,
    api_key: str,
    dry_run: bool = False,
) -> str | None:
    """Look up domain for one company via Apollo org enrich.

    Tries by apollo_id first, falls back to company name + state.
    Returns the discovered domain string or None.
    """
    name = company.get("name", "")
    apollo_id = company.get("apollo_id")

    if dry_run:
        console.print(f"  [DRY-RUN] Would enrich domain for: {name}")
        return None

    params: dict = {}
    if apollo_id:
        params["id"] = apollo_id
    elif name:
        params["name"] = name
        if company.get("state"):
            params["organization_location"] = company["state"]
    else:
        return None

    try:
        resp = httpx.get(
            APOLLO_ORG_ENRICH_URL,
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        org = data.get("organization") or {}
        domain = _clean_domain(org.get("primary_domain") or org.get("website_url"))
        return domain
    except httpx.HTTPStatusError as e:
        logger.warning(f"Apollo org enrich HTTP {e.response.status_code} for '{name}'")
        return None
    except Exception as e:
        logger.warning(f"Apollo org enrich error for '{name}': {e}")
        return None


def infer_missing_domains(
    dry_run: bool = False,
    campaign_name: str | None = None,
    limit: int = 200,
) -> dict:
    """Find all companies missing a domain and try to infer it via Apollo.

    Returns a summary dict with counts.
    """
    db = Database()
    settings = get_settings()

    if not settings.apollo_api_key and not dry_run:
        console.print("[red]APOLLO_API_KEY not set — cannot infer domains.[/red]")
        return {"error": "no_api_key"}

    # Fetch companies with no domain
    result = (
        db.client.table("companies")
        .select("id, name, apollo_id, state, domain")
        .or_("domain.is.null,domain.eq.")
        .order("created_at")
        .limit(limit)
        .execute()
    )
    companies = result.data

    if campaign_name:
        companies = [c for c in companies if c.get("campaign_name") == campaign_name]

    if not companies:
        console.print("[green]All companies already have a domain.[/green]")
        return {"processed": 0, "found": 0, "failed": 0}

    console.print(f"[cyan]{len(companies)} companies missing domain — inferring via Apollo...[/cyan]")

    found = 0
    failed = 0

    for company in companies:
        domain = infer_domain_for_company(company, settings.apollo_api_key or "", dry_run=dry_run)
        if domain:
            found += 1
            if not dry_run:
                # Check if another company already has this domain (avoid UNIQUE constraint violation)
                existing = db.get_company_by_domain(domain)
                if existing and existing["id"] != company["id"]:
                    console.print(
                        f"  [yellow]⚠ {company['name']}: domain '{domain}' already owned by another company — skipping[/yellow]"
                    )
                    failed += 1
                    continue
                db.update_company(company["id"], {"domain": domain})
                console.print(f"  [green]✓ {company['name']} → {domain}[/green]")
            else:
                console.print(f"  [DRY-RUN] {company['name']} → {domain}")
        else:
            failed += 1
            console.print(f"  [dim]✗ {company['name']} — not found[/dim]")

        time.sleep(RATE_LIMIT_SLEEP)

    summary = {"processed": len(companies), "found": found, "failed": failed}
    console.print(f"\n[bold]Domain inference complete:[/bold] {found} found, {failed} not resolved")
    return summary
