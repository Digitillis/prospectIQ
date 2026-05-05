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
from backend.app.agents.discovery import classify_persona
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


# F&B tier prefix — companies in these tiers get C1+C3 dual enrichment per cycle
_FB_TIER_PREFIX = "fb"

# C1 personas for F&B (ops/economic buyer — enriched first)
_FB_C1_PERSONAS = frozenset({"vp_ops", "coo", "director_ops", "vp_supply_chain"})
# C3 personas for F&B (plant-level champion — enriched in same cycle as C1)
_FB_C3_PERSONAS = frozenset({"plant_manager"})


class EnrichmentAgent(BaseAgent):
    """Enrich contacts at qualified companies via Apollo People Match.

    For fb* tier companies: enriches C1 (ops) + C3 (plant manager) in a single
    cycle so both contacts are email-ready before outreach routing runs.
    For all other tiers: enriches the single highest-priority contact per cycle.
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

        # Apollo credit guard — halt before the batch if buffer is low
        workspace_id = getattr(self.db, "workspace_id", None)
        from backend.app.core.workspace_scheduler import apollo_credits_ok
        if not apollo_credits_ok(workspace_id=workspace_id, min_buffer=200):
            console.print(
                "[red]Apollo credit guard: fewer than 200 credits remaining — enrichment halted.[/red]"
            )
            result.add_detail("credit_guard", "halted", "Apollo credits <= 200 — skipping this run")
            return result

        # Get companies that need enrichment
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        else:
            # Pull qualified companies that still need contact emails.
            # Fetch a large pool sorted by PQS and skip any company where every
            # known contact has already been attempted (has no email but apollo was
            # called).  This prevents cycling the same stuck top-20 forever.
            pool = self.db.get_companies(status="qualified", limit=500)
            companies = []
            for co in pool:
                if len(companies) >= limit:
                    break
                existing = self.db.get_contacts_for_company(co["id"])
                # Include if: no contacts yet (need discovery), or some contacts
                # still have no email and haven't exhausted their attempt budget.
                if not existing:
                    # No contacts yet — need Apollo People Search to discover them.
                    # That requires a domain; skip if unavailable.
                    if not co.get("domain"):
                        continue
                    companies.append(co)
                elif any(
                    not c.get("email") and int(c.get("enrichment_attempts") or 0) < 3
                    for c in existing
                ):
                    # Have contacts but missing emails. If they have apollo_id we can
                    # People Match directly — no domain needed. Only skip if no
                    # apollo_id AND no domain (name search produces poor matches).
                    needs_match = [
                        c for c in existing
                        if not c.get("email") and int(c.get("enrichment_attempts") or 0) < 3
                    ]
                    can_enrich = any(c.get("apollo_id") for c in needs_match)
                    if not can_enrich and not co.get("domain"):
                        continue
                    companies.append(co)

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
                        # Auto-discover contacts via Apollo People Search (FREE)
                        domain = company.get("domain")
                        console.print(
                            f"  [cyan]{company_name}: No contacts — discovering via Apollo...[/cyan]"
                        )
                        discovered_contacts = []
                        try:
                            search_kwargs: dict = {"per_page": 25}
                            if domain:
                                # Use organization_domains for exact company match
                                search_kwargs["organization_domains"] = [domain]
                            else:
                                # Fallback: search by company name
                                search_kwargs["q_organization_name"] = company_name
                            # Broad seniority filter only — don't filter by title
                            # (small companies may have few people in Apollo)
                            search_kwargs["person_seniorities"] = [
                                "vp", "director", "c_suite", "owner", "manager",
                            ]
                            resp = apollo.search_people(**search_kwargs)
                            people = resp.get("people", [])
                            from backend.app.core.contact_filter import screen_contact_at_import
                            for person in people[:10]:  # cap at 10 per company
                                contact_data = ApolloClient.extract_contact_data(person)
                                if not contact_data.get("apollo_id"):
                                    continue
                                # Check not already in DB
                                existing = self.db.get_contact_by_apollo_id(
                                    contact_data["apollo_id"]
                                )
                                if existing:
                                    continue
                                persona_type, is_dm = classify_persona(
                                    contact_data.get("title")
                                )
                                contact_insert = screen_contact_at_import({
                                    **contact_data,
                                    "company_id": company_id,
                                    "persona_type": persona_type,
                                    "is_decision_maker": is_dm,
                                }, db=self.db)
                                _inserted_c = self.db.insert_contact(contact_insert)
                                try:
                                    self.db.client.table("raw_contacts").insert({
                                        "source": "apollo",
                                        "source_record_id": contact_data.get("apollo_id"),
                                        "payload": contact_data,
                                        "resolved_contact_id": (_inserted_c or {}).get("id"),
                                        "workspace_id": getattr(self.db, "workspace_id", None),
                                    }).execute()
                                except Exception:
                                    pass
                                discovered_contacts.append(contact_insert)
                            console.print(
                                f"  [green]{company_name}: Discovered {len(discovered_contacts)} contacts[/green]"
                            )
                        except Exception as disc_err:
                            logger.warning(
                                f"Auto-discovery failed for {company_name}: {disc_err}"
                            )

                        # Re-fetch contacts after discovery
                        contacts = self.db.get_contacts_for_company(company_id)
                        if not contacts:
                            console.print(
                                f"  [yellow]{company_name}: Still no contacts after discovery. Skipping.[/yellow]"
                            )
                            result.skipped += 1
                            result.add_detail(company_name, "skipped", "No contacts even after discovery")
                            continue

                    # Note: has_email from People Search is unreliable — search often
                    # reports has_email=false but enrichment/match finds the email.
                    # We do NOT filter by has_email here. Always try enrichment.

                    # Domain verification — check MX records once per company before
                    # spending any credits on its contacts.
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

                    # Select which contacts to enrich this cycle.
                    # F&B tier: enrich C1 (ops) + C3 (plant manager) in one pass so both
                    # slots are email-ready before outreach routing runs.
                    # All other tiers: enrich the single highest-priority unenriched contact.
                    company_tier = company.get("tier") or ""
                    contacts_to_enrich = self._select_contacts_to_enrich(contacts, company_tier)

                    if not contacts_to_enrich:
                        # All contacts already have email — mark as enriched and move on
                        contacts_with_email = [c for c in contacts if c.get("email")]
                        if contacts_with_email:
                            for c in contacts_with_email:
                                if c.get("status") != "enriched":
                                    self.db.update_contact(c["id"], {"status": "enriched"})
                            best = contacts_with_email[0]
                            best_name = best.get("full_name") or best.get("first_name") or "Unknown"
                            console.print(
                                f"  [green]{company_name}: {len(contacts_with_email)} contact(s) already have email "
                                f"(best: {best_name} → {best.get('email')}). Ready for outreach.[/green]"
                            )
                            result.processed += 1
                            result.add_detail(
                                company_name, "ready",
                                f"{len(contacts_with_email)} contacts with email (best: {best_name})"
                            )
                        else:
                            console.print(
                                f"  [dim]{company_name}: Contacts exist but none have email. Skipping.[/dim]"
                            )
                            result.skipped += 1
                            result.add_detail(company_name, "skipped", "Contacts exist but no emails found")
                        continue

                    # Enrich each selected contact (1 credit each if Apollo returns a match)
                    for contact in contacts_to_enrich:
                        contact_name = contact.get("full_name") or contact.get("first_name") or "Unknown"
                        apollo_id = contact.get("apollo_id")

                        if not apollo_id:
                            console.print(
                                f"  [yellow]{company_name}: {contact_name} has no Apollo ID. Skipping.[/yellow]"
                            )
                            result.skipped += 1
                            result.add_detail(company_name, "skipped", f"No Apollo ID for {contact_name}")
                            continue

                        # Call Apollo enrichment (1 credit if matched, 0 if no match)
                        console.print(
                            f"  [dim]{company_name} → enriching {contact_name} "
                            f"({contact.get('title', '')}, persona={contact.get('persona_type','?')})...[/dim]"
                        )

                        enriched = apollo.enrich_person(
                            person_id=apollo_id,
                            reveal_personal_emails=True,
                            reveal_phone_number=include_phone,
                        )

                        # 1 Apollo credit per people/match call
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
                                f"  [yellow]{company_name}: No person data returned for {contact_name}.[/yellow]"
                            )
                            result.skipped += 1
                            result.add_detail(company_name, "no_match", f"{contact_name}: no Apollo record")
                            continue

                        # Build update payload
                        update_data: dict = {}

                        email = person.get("email")
                        if email:
                            update_data["email"] = email

                        phone = person.get("phone_number") or person.get("sanitized_phone")
                        if phone:
                            update_data["phone"] = phone

                        full_name = person.get("name")
                        if full_name and "***" not in full_name:
                            update_data["full_name"] = full_name
                            parts = full_name.split(" ", 1)
                            update_data["first_name"] = parts[0]
                            if len(parts) > 1:
                                update_data["last_name"] = parts[1]

                        linkedin = person.get("linkedin_url")
                        if linkedin:
                            update_data["linkedin_url"] = linkedin

                        # email_status: verified / unverified / catch_all / invalid / bounce
                        email_status = person.get("email_status")
                        if email_status:
                            update_data["email_status"] = email_status
                            if email_status in ("invalid", "bounce"):
                                update_data["is_outreach_eligible"] = False
                                console.print(
                                    f"  [red]{company_name}: {contact_name} → email_status={email_status},"
                                    f" blocking outreach[/red]"
                                )

                        # Email-name consistency check (catches false-match artifacts like Dave Horton)
                        if email and (full_name or (contact.get("first_name") and contact.get("last_name"))):
                            from backend.app.core.contact_filter import check_email_name_consistency
                            first = (update_data.get("first_name") or contact.get("first_name") or "").strip()
                            last = (update_data.get("last_name") or contact.get("last_name") or "").strip()
                            consistent, cons_reason = check_email_name_consistency(first, last, email)
                            update_data["email_name_verified"] = consistent
                            if not consistent:
                                update_data["is_outreach_eligible"] = False
                                logger.warning(
                                    "Email-name mismatch on enrichment: %s %s → %s (%s)",
                                    first, last, email, cons_reason,
                                )
                                console.print(
                                    f"  [red]{company_name}: {contact_name} → name/email mismatch,"
                                    f" blocking outreach ({cons_reason})[/red]"
                                )

                        if update_data:
                            update_data["status"] = "enriched"
                            update_data["enrichment_status"] = "enriched"
                            from backend.app.core.contact_filter import compute_ccs
                            from datetime import datetime, timezone
                            _now = datetime.now(timezone.utc).isoformat()
                            update_data["enriched_at"] = _now
                            merged = {**contact, **update_data}
                            update_data["ccs_score"] = compute_ccs(merged)
                            update_data["ccs_computed_at"] = _now
                            self.db.update_contact(contact["id"], update_data)

                        if email:
                            status_tag = f" [{email_status}]" if email_status else ""
                            console.print(
                                f"  [green]{company_name}: {full_name or contact_name} → {email}{status_tag}[/green]"
                            )
                            result.processed += 1
                            result.add_detail(
                                company_name,
                                "enriched",
                                f"{full_name or contact_name}: {email}"
                                + (f", {phone}" if phone else "")
                                + (f" [{email_status}]" if email_status else ""),
                            )
                        else:
                            # Track consecutive misses. After 3 attempts with no email
                            # returned, flip to 'failed' so this contact stops consuming
                            # Apollo credits every cycle.
                            attempts = int(contact.get("enrichment_attempts") or 0) + 1
                            if attempts >= 3:
                                self.db.mark_contact_enrichment_failed(contact["id"])
                                console.print(
                                    f"  [red]{company_name}: {contact_name} — 3 Apollo misses,"
                                    f" marked enrichment_failed (no further attempts).[/red]"
                                )
                                result.add_detail(
                                    company_name, "enrichment_failed",
                                    f"{contact_name}: 3 Apollo misses — giving up"
                                )
                            else:
                                self.db.update_contact(
                                    contact["id"], {"enrichment_attempts": attempts}
                                )
                                console.print(
                                    f"  [yellow]{company_name}: No email for {contact_name}"
                                    f" (attempt {attempts}/3).[/yellow]"
                                )
                                result.add_detail(
                                    company_name, "no_email",
                                    f"{contact_name}: no email in Apollo (attempt {attempts}/3)"
                                )
                            result.skipped += 1

                except Exception as e:
                    logger.error(f"Error enriching {company_name}: {e}", exc_info=True)
                    result.errors += 1
                    result.add_detail(company_name, "error", str(e)[:200])
                    if self._monitor:
                        self._monitor.log_error(str(e), company_id=company_id, error_type="enrichment_error", exc=e)

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

    def _select_contacts_to_enrich(
        self, contacts: list[dict], company_tier: str
    ) -> list[dict]:
        """Return the ordered list of contacts to enrich in this cycle.

        F&B tier companies: returns up to 2 contacts — the best C1 (ops persona)
        and the best C3 (plant manager), so both slots are email-ready before
        the outreach agent runs. This eliminates the 1-cycle lag where C3 was
        never enriched until the next scheduled run.

        All other tiers: returns the single highest-priority unenriched contact
        (original behaviour preserved).

        Contacts that already have an email are excluded from the selection —
        they don't need re-enrichment.
        """
        needs_enrichment = [
            c for c in contacts
            if not c.get("email") and int(c.get("enrichment_attempts") or 0) < 3
        ]
        if not needs_enrichment:
            return []

        def score(c: dict) -> int:
            persona = c.get("persona_type", "")
            priority = _PERSONA_PRIORITY.get(persona, 0)
            dm_bonus = 50 if c.get("is_decision_maker") else 0
            # Contacts without an Apollo ID can't be enriched via people/match.
            # Deprioritise them so we don't waste a cycle slot picking one.
            apollo_penalty = -200 if not c.get("apollo_id") else 0
            # LinkedIn URL signals Apollo has a confirmed profile — higher match rate.
            linkedin_bonus = 20 if c.get("linkedin_url") else 0
            return priority + dm_bonus + apollo_penalty + linkedin_bonus

        needs_enrichment.sort(key=score, reverse=True)

        is_fb = company_tier.startswith(_FB_TIER_PREFIX)
        if not is_fb:
            return [needs_enrichment[0]]

        # F&B: pick best C1 + best C3 separately so persona slots are filled optimally
        c1 = next(
            (c for c in needs_enrichment if c.get("persona_type") in _FB_C1_PERSONAS),
            None,
        )
        c3 = next(
            (c for c in needs_enrichment if c.get("persona_type") in _FB_C3_PERSONAS),
            None,
        )
        selected = [c for c in [c1, c3] if c is not None]
        # Fall back to highest-priority contact if neither persona slot has a candidate
        return selected if selected else [needs_enrichment[0]]
