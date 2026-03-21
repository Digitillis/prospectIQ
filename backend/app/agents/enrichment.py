"""Enrichment Agent — Apollo contact enrichment.

Enriches contacts at qualified companies to reveal email addresses
and phone numbers. This is the bridge between qualification and outreach —
without enrichment, the outreach agent has no email to send to.

Consumes Apollo credits — only enriches contacts at qualified companies
to conserve budget.
"""

from __future__ import annotations

import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.integrations.apollo import ApolloClient

console = Console()
logger = logging.getLogger(__name__)

# Persona priority for selecting which contact to enrich first
_PERSONA_PRIORITY = {
    "vp_quality_food_safety": 100,
    "coo": 95,
    "vp_ops": 90,
    "plant_manager": 85,
    "director_quality_food_safety": 80,
    "maintenance_leader": 75,
    "director_ops": 70,
    "digital_transformation": 65,
    "vp_supply_chain": 60,
    "cio": 55,
}


class EnrichmentAgent(BaseAgent):
    """Enrich contacts at qualified companies via Apollo People Match.

    Only enriches the top-priority contact per company to conserve
    Apollo credits. Skips contacts that already have an email address.
    """

    agent_name = "enrichment"

    def run(
        self,
        company_ids: list[str] | None = None,
        limit: int = 25,
        include_phone: bool = False,
    ) -> AgentResult:
        """Run enrichment on qualified companies' contacts.

        Args:
            company_ids: Specific company IDs to enrich (overrides query).
            limit: Max companies to enrich in this batch.
            include_phone: Whether to request phone numbers (async webhook).

        Returns:
            AgentResult with enrichment stats.
        """
        result = AgentResult()

        # Get companies that need enrichment
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        else:
            # Enrich qualified companies that haven't been enriched yet
            companies = self.db.get_companies(status="qualified", limit=limit)

        if not companies:
            console.print("[yellow]No companies ready for enrichment.[/yellow]")
            return result

        console.print(
            f"[cyan]Enriching contacts for {len(companies)} qualified companies...[/cyan]"
        )

        with ApolloClient() as apollo:
            for company in companies:
                company_name = company["name"]
                company_id = company["id"]

                try:
                    # Get all contacts for this company
                    contacts = self.db.get_contacts_for_company(company_id)

                    if not contacts:
                        console.print(
                            f"  [yellow]{company_name}: No contacts found. Skipping.[/yellow]"
                        )
                        result.skipped += 1
                        result.add_detail(company_name, "skipped", "No contacts")
                        continue

                    # Pre-filter: skip contacts Apollo already told us have no email
                    pre_count = len(contacts)
                    contacts = [c for c in contacts if c.get("has_email", True)]  # Default True for backward compat
                    skipped_no_email = pre_count - len(contacts)
                    if skipped_no_email > 0:
                        console.print(f"  [dim]{company_name}: Skipped {skipped_no_email} contacts (Apollo reports no email)[/dim]")

                    # Find the best contact to enrich (highest persona priority, no email yet)
                    contact = self._select_contact_to_enrich(contacts)

                    if not contact:
                        console.print(
                            f"  [dim]{company_name}: All contacts already enriched. Skipping.[/dim]"
                        )
                        result.skipped += 1
                        result.add_detail(company_name, "skipped", "All contacts already have email")
                        continue

                    contact_name = contact.get("full_name") or contact.get("first_name") or "Unknown"
                    apollo_id = contact.get("apollo_id")

                    if not apollo_id:
                        console.print(
                            f"  [yellow]{company_name}: Contact {contact_name} has no Apollo ID. Skipping.[/yellow]"
                        )
                        result.skipped += 1
                        result.add_detail(company_name, "skipped", f"No Apollo ID for {contact_name}")
                        continue

                    # Domain verification — check MX records before spending credits
                    company_domain = company.get("domain")
                    if company_domain:
                        from backend.app.core.domain_verify import verify_domain
                        domain_valid, domain_reason = verify_domain(company_domain)
                        if not domain_valid:
                            console.print(
                                f"  [yellow]{company_name}: Domain {company_domain} invalid "
                                f"({domain_reason}). Skipping enrichment.[/yellow]"
                            )
                            result.skipped += 1
                            result.add_detail(
                                company_name, "domain_invalid",
                                f"{company_domain}: {domain_reason}"
                            )
                            continue

                    # Call Apollo enrichment
                    console.print(
                        f"  [dim]{company_name} → enriching {contact_name} ({contact.get('title', '')})...[/dim]"
                    )

                    enriched = apollo.enrich_person(
                        person_id=apollo_id,
                        reveal_personal_emails=True,
                        reveal_phone_number=include_phone,
                    )

                    self.track_cost(
                        provider="apollo",
                        model="people_match",
                        endpoint="/people/match",
                        company_id=company_id,
                        input_tokens=0,
                        output_tokens=0,
                    )

                    # Extract enriched data
                    person = enriched.get("person", {})
                    if not person:
                        console.print(
                            f"  [yellow]{company_name}: Enrichment returned no person data.[/yellow]"
                        )
                        result.skipped += 1
                        result.add_detail(company_name, "skipped", "Enrichment returned empty")
                        continue

                    # Update contact with enriched fields
                    update_data: dict = {}

                    email = person.get("email")
                    if email:
                        update_data["email"] = email

                    phone = person.get("phone_number") or person.get("sanitized_phone")
                    if phone:
                        update_data["phone"] = phone

                    # Update name if we only had obfuscated version
                    full_name = person.get("name")
                    if full_name and "***" not in full_name:
                        update_data["full_name"] = full_name
                        # Split into first/last
                        parts = full_name.split(" ", 1)
                        update_data["first_name"] = parts[0]
                        if len(parts) > 1:
                            update_data["last_name"] = parts[1]

                    linkedin = person.get("linkedin_url")
                    if linkedin:
                        update_data["linkedin_url"] = linkedin

                    if update_data:
                        update_data["status"] = "enriched"
                        self.db.update_contact(contact["id"], update_data)

                    if email:
                        console.print(
                            f"  [green]{company_name}: {full_name or contact_name} → {email}[/green]"
                        )
                        result.processed += 1
                        result.add_detail(
                            company_name,
                            "enriched",
                            f"{full_name or contact_name}: {email}"
                            + (f", {phone}" if phone else ""),
                        )
                    else:
                        console.print(
                            f"  [yellow]{company_name}: No email found for {contact_name}.[/yellow]"
                        )
                        result.skipped += 1
                        result.add_detail(company_name, "no_email", f"{contact_name}: no email in Apollo")

                except Exception as e:
                    logger.error(f"Error enriching {company_name}: {e}", exc_info=True)
                    result.errors += 1
                    result.add_detail(company_name, "error", str(e)[:200])

        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f"*Enrichment complete:* {result.processed} contacts enriched, "
                f"{result.skipped} skipped, {result.errors} errors. "
                f"Cost: ${result.total_cost_usd:.4f}",
                emoji=":mag_right:",
            )
        except Exception:
            pass

        return result

    def _select_contact_to_enrich(self, contacts: list[dict]) -> dict | None:
        """Select the highest-priority contact that needs enrichment.

        Prioritizes contacts without email, sorted by persona priority.
        """
        # Split into needs-enrichment vs already-enriched
        needs_enrichment = [c for c in contacts if not c.get("email")]
        if not needs_enrichment:
            return None

        # Sort by persona priority (highest first), then decision maker
        def score(c: dict) -> int:
            persona = c.get("persona_type", "")
            priority = _PERSONA_PRIORITY.get(persona, 0)
            dm_bonus = 50 if c.get("is_decision_maker") else 0
            return priority + dm_bonus

        needs_enrichment.sort(key=score, reverse=True)
        return needs_enrichment[0]
