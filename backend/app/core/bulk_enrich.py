"""Apollo bulk match enrichment — 10x more credit-efficient than individual matches.

Uses Apollo's /people/bulk_match endpoint (up to 10 contacts per call)
instead of one credit per individual /people/match call.

Usage:
    from backend.app.core.bulk_enrich import BulkEnrichmentJob
    job = BulkEnrichmentJob(campaign_name="tier0-mfg-pdm-roi")
    job.run(dry_run=False)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from backend.app.core.config import get_settings
from backend.app.core.database import Database

console = Console()
logger = logging.getLogger(__name__)

APOLLO_BULK_MATCH_URL = "https://api.apollo.io/v1/people/bulk_match"
BATCH_SIZE = 10      # Apollo limit per call
RATE_LIMIT_SLEEP = 1.5  # seconds between API calls


@dataclass
class EnrichmentResult:
    contact_id: str
    apollo_id: str
    name: str
    matched: bool = False
    email: str | None = None
    phone: str | None = None
    error: str | None = None


@dataclass
class BulkEnrichmentRun:
    processed: int = 0
    matched: int = 0
    failed: int = 0
    credits_used: int = 0
    results: list[EnrichmentResult] = field(default_factory=list)


class BulkEnrichmentJob:
    """Batch-enrich contacts via Apollo bulk_match, 10 per API call."""

    def __init__(
        self,
        campaign_name: str | None = None,
        tier: str | None = None,
        stale_days: int = 90,
        workspace_id: str | None = None,
    ):
        self.campaign_name = campaign_name
        self.tier = tier
        self.stale_days = stale_days
        self.db = Database(workspace_id=workspace_id)
        self.settings = get_settings()

    def run(self, dry_run: bool = False, limit: int = 500) -> BulkEnrichmentRun:
        """Enrich all contacts with needs_enrichment or stale status.

        Args:
            dry_run: If True, fetch contacts and plan but don't call Apollo or write DB.
            limit: Max contacts to process in this run.

        Returns:
            BulkEnrichmentRun with stats.
        """
        run = BulkEnrichmentRun()

        # 1. Fetch contacts that need enrichment
        contacts = self.db.get_contacts_needing_enrichment(
            campaign_name=self.campaign_name,
            tier=self.tier,
            limit=limit,
        )
        # Also grab stale contacts
        stale = self.db.get_stale_contacts(stale_days=self.stale_days, limit=limit)
        stale_ids = {c["id"] for c in contacts}
        for c in stale:
            if c["id"] not in stale_ids:
                contacts.append(c)
                stale_ids.add(c["id"])

        contacts = contacts[:limit]

        if not contacts:
            console.print("[yellow]No contacts need enrichment.[/yellow]")
            return run

        console.print(f"[cyan]Found {len(contacts)} contact(s) to enrich.[/cyan]")
        if dry_run:
            console.print("[yellow][DRY-RUN] Would call Apollo bulk_match. No API calls will be made.[/yellow]")
            for c in contacts:
                name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or c.get("apollo_id", "?")
                console.print(f"  → {name} ({c.get('apollo_id', 'no-id')[:12]}...)")
            run.processed = len(contacts)
            return run

        if not self.settings.apollo_api_key:
            console.print("[red]APOLLO_API_KEY not set — cannot run enrichment.[/red]")
            return run

        # 2. Chunk into batches of BATCH_SIZE
        batches = [contacts[i:i + BATCH_SIZE] for i in range(0, len(contacts), BATCH_SIZE)]

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task(f"Enriching {len(contacts)} contacts...", total=len(batches))

            for batch in batches:
                batch_results = self._enrich_batch(batch)
                for result in batch_results:
                    run.results.append(result)
                    run.processed += 1
                    if result.matched:
                        run.matched += 1
                        run.credits_used += 1
                        # Write enrichment to DB
                        self.db.mark_contact_enriched(
                            contact_id=result.contact_id,
                            email=result.email,
                            phone=result.phone,
                            source="apollo_bulk",
                        )
                        # Log credit event
                        self.db.log_apollo_credit({
                            "operation": "people_bulk_match",
                            "credits_used": 1,
                            "contact_id": result.contact_id,
                            "campaign_name": self.campaign_name,
                            "response_status": "success",
                        })
                    else:
                        run.failed += 1
                        self.db.mark_contact_enrichment_failed(result.contact_id, result.error or "")
                        self.db.log_apollo_credit({
                            "operation": "people_bulk_match",
                            "credits_used": 1,
                            "contact_id": result.contact_id,
                            "campaign_name": self.campaign_name,
                            "response_status": "no_match" if not result.error else "failed",
                            "notes": result.error,
                        })

                progress.advance(task)
                time.sleep(RATE_LIMIT_SLEEP)

        # 3. Summary
        console.print(
            f"\n[bold]Enrichment complete:[/bold] "
            f"{run.matched}/{run.processed} matched, "
            f"{run.failed} failed, "
            f"{run.credits_used} credits used."
        )
        return run

    def _enrich_batch(self, contacts: list[dict]) -> list[EnrichmentResult]:
        """Call Apollo /people/bulk_match for a batch of up to 10 contacts."""
        results: list[EnrichmentResult] = []

        # Build the match payload — Apollo matches by apollo_id (most reliable)
        match_items = []
        for c in contacts:
            apollo_id = c.get("apollo_id")
            if apollo_id and len(apollo_id) >= 24:
                match_items.append({"id": apollo_id})
            else:
                # Fallback: match by name + title
                first = c.get("first_name", "")
                last = c.get("last_name", "")
                title = c.get("title", "")
                if first or last:
                    match_items.append({
                        "first_name": first,
                        "last_name": last,
                        "title": title,
                    })
                else:
                    results.append(EnrichmentResult(
                        contact_id=c["id"],
                        apollo_id=apollo_id or "",
                        name=c.get("full_name", "?"),
                        matched=False,
                        error="No apollo_id and no name — cannot match",
                    ))
                    continue

        if not match_items:
            return results

        try:
            resp = httpx.post(
                APOLLO_BULK_MATCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": self.settings.apollo_api_key,
                },
                json={"match_params": match_items, "reveal_personal_emails": False},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            matches = data.get("people", []) or []

            # Map results back to contacts by index position
            for i, c in enumerate(contacts[:len(match_items)]):
                person = matches[i] if i < len(matches) else None
                name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
                if person and person.get("email"):
                    results.append(EnrichmentResult(
                        contact_id=c["id"],
                        apollo_id=c.get("apollo_id", ""),
                        name=name,
                        matched=True,
                        email=person.get("email"),
                        phone=person.get("phone_numbers", [{}])[0].get("sanitized_number") if person.get("phone_numbers") else None,
                    ))
                else:
                    results.append(EnrichmentResult(
                        contact_id=c["id"],
                        apollo_id=c.get("apollo_id", ""),
                        name=name,
                        matched=False,
                        error="No email returned by Apollo",
                    ))

        except httpx.HTTPStatusError as e:
            logger.error(f"Apollo bulk_match HTTP error: {e.response.status_code} — {e.response.text[:200]}")
            for c in contacts:
                results.append(EnrichmentResult(
                    contact_id=c["id"],
                    apollo_id=c.get("apollo_id", ""),
                    name=c.get("full_name", "?"),
                    matched=False,
                    error=f"HTTP {e.response.status_code}",
                ))
        except Exception as e:
            logger.error(f"Apollo bulk_match error: {e}")
            for c in contacts:
                results.append(EnrichmentResult(
                    contact_id=c["id"],
                    apollo_id=c.get("apollo_id", ""),
                    name=c.get("full_name", "?"),
                    matched=False,
                    error=str(e)[:200],
                ))

        return results
