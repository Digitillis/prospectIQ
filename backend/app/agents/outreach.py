"""Outreach Agent — Personalized message generation.

Uses Claude (1 call per message) to generate deeply personalized
outreach messages based on research intelligence and sequence config.
"""

from __future__ import annotations

import json
import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import (
    get_settings,
    get_sequences_config,
    get_manufacturing_ontology,
)

console = Console()
logger = logging.getLogger(__name__)

# Persona priority order — higher value = preferred primary contact
PERSONA_PRIORITY = {
    "vp_quality_food_safety": 100,     # F&B primary buyer (FSMA compliance)
    "coo": 95,
    "vp_ops": 90,
    "plant_manager": 85,
    "director_quality_food_safety": 80, # F&B secondary buyer
    "maintenance_leader": 75,
    "director_ops": 70,
    "digital_transformation": 65,
    "vp_supply_chain": 60,
    "cio": 55,
}

OUTREACH_SYSTEM = """You are an expert B2B sales copywriter for Digitillis, an AI-native manufacturing intelligence platform. You write concise, personalized outreach messages that lead with the prospect's specific challenges — not product features.

Your writing style:
- Peer-to-peer: You speak as someone who understands manufacturing, not as a vendor
- Use manufacturing language naturally (OEE, MTBF, RUL, unplanned downtime)
- Every message references at least one specific fact about the prospect
- Short, respectful of their time
- No filler phrases ("I hope this finds you well", "reaching out because")
- No false urgency, scarcity, or manipulation
- Evidence-based — never make unsupported claims
- Single clear CTA per message

Digitillis capabilities:
- 32 specialized AI agents across 7 manufacturing domains
- Predictive maintenance with 18+ day advance warning, 87% confidence
- Anomaly detection across 100+ sensors
- Quality control with defect prediction
- Energy optimization and ESG reporting
- Production optimization with OEE analytics
- Conversational AI copilot (ARIA)
- Pilot program: 6-8 weeks, no long-term commitment

Founder sending these emails: Avi, Co-Founder & MD at Digitillis
Email: avi@digitillis.io"""

OUTREACH_USER = """Generate an outreach message for this prospect.

COMPANY:
- Name: {company_name}
- Industry/Sub-sector: {sub_sector} (Tier {tier})
- Location: {city}, {state}
- Employees: {employee_count}
- Revenue: {revenue_range}

CONTACT:
- Name: {contact_name}
- Title: {contact_title}
- Persona: {persona_type}

RESEARCH INTELLIGENCE:
{research_summary}

PERSONALIZATION HOOKS:
{personalization_hooks}

TECHNOLOGY STACK:
{technology_stack}

PAIN SIGNALS:
{pain_signals}

MANUFACTURING PROFILE:
{manufacturing_profile}

EXISTING SOLUTIONS (competitors already in use):
{existing_solutions}

VALUE MESSAGING FOR THIS SUB-SECTOR:
{value_messaging}

SEQUENCE: {sequence_name}, Step {sequence_step}
CHANNEL: {channel}

STEP INSTRUCTIONS:
{step_instructions}

GLOBAL ANTI-PATTERNS:
{anti_patterns}

OUTPUT FORMAT (JSON):
{{
    "subject": "Short, relevant subject line (under 50 chars)",
    "body": "The email body. {max_words} words max. Sign off as 'Avi' with title 'Co-Founder, Digitillis'.",
    "personalization_notes": "Brief explanation of why you chose this approach and which hooks you used"
}}

Output ONLY valid JSON. No markdown, no explanation."""


class OutreachAgent(BaseAgent):
    """Generate personalized outreach messages using Claude."""

    agent_name = "outreach"

    def run(
        self,
        company_ids: list[str] | None = None,
        sequence_name: str = "initial_outreach",
        sequence_step: int = 1,
        limit: int = 20,
        multi_thread: bool = True,
        max_contacts_per_company: int = 2,
    ) -> AgentResult:
        """Generate outreach drafts for qualified companies.

        Args:
            company_ids: Specific company IDs (overrides query).
            sequence_name: Which sequence to use.
            sequence_step: Which step in the sequence.
            limit: Max companies to process.

        Returns:
            AgentResult with draft creation stats.
        """
        result = AgentResult()
        settings = get_settings()
        seq_config = get_sequences_config()
        ontology = get_manufacturing_ontology()

        sequence = seq_config["sequences"].get(sequence_name)
        if not sequence:
            console.print(f"[red]Sequence '{sequence_name}' not found in config.[/red]")
            result.success = False
            return result

        # Get the step configuration
        step_config = None
        for step in sequence["steps"]:
            if step["step"] == sequence_step:
                step_config = step
                break

        if not step_config:
            console.print(f"[red]Step {sequence_step} not found in sequence '{sequence_name}'.[/red]")
            result.success = False
            return result

        # Get companies to generate outreach for
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        else:
            companies = self.db.get_companies(status="qualified", limit=limit)

        if not companies:
            console.print("[yellow]No companies ready for outreach.[/yellow]")
            return result

        console.print(
            f"[cyan]Generating outreach for {len(companies)} companies "
            f"(sequence={sequence_name}, step={sequence_step})...[/cyan]"
        )

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        for company in companies:
            company_name = company["name"]
            company_id = company["id"]

            try:
                # Suppression check — block outreach to suppressed companies
                from backend.app.core.suppression import is_suppressed

                suppressed, reason = is_suppressed(self.db, company_id)
                if suppressed:
                    console.print(
                        f"  [dim]{company_name}: Suppressed ({reason}). Skipping.[/dim]"
                    )
                    result.skipped += 1
                    result.add_detail(company_name, "suppressed", reason or "")
                    continue

                # Select contacts — multi-thread if enabled
                contacts = self.db.get_contacts_for_company(company_id)

                if multi_thread and max_contacts_per_company > 1:
                    target_contacts = self._select_contacts_for_threading(
                        contacts, max_contacts_per_company
                    )
                else:
                    primary = self._select_primary_contact(contacts)
                    target_contacts = [primary] if primary else []

                if not target_contacts:
                    console.print(f"  [yellow]{company_name}: No suitable contact found. Skipping.[/yellow]")
                    result.skipped += 1
                    result.add_detail(company_name, "skipped", "No suitable contact")
                    continue

                # Filter out suppressed contacts
                valid_contacts = []
                for contact in target_contacts:
                    contact_suppressed, contact_reason = is_suppressed(
                        self.db, company_id, contact["id"]
                    )
                    if contact_suppressed:
                        console.print(
                            f"  [dim]{company_name}: {contact.get('full_name', '?')} suppressed ({contact_reason})[/dim]"
                        )
                    else:
                        valid_contacts.append(contact)

                if not valid_contacts:
                    result.skipped += 1
                    result.add_detail(company_name, "all_contacts_suppressed", "")
                    continue

                # Get research intelligence
                research = self.db.get_research(company_id)

                # Generate drafts for each valid contact
                for contact in valid_contacts:
                    # Build value messaging for this tier
                    tier = company.get("tier", "2")
                    value_msg = ontology.get("value_messaging", {}).get(tier, {})

                    # Build the prompt
                    prompt = self._build_prompt(
                        company=company,
                        contact=contact,
                        research=research,
                        step_config=step_config,
                        sequence_name=sequence_name,
                        value_messaging=value_msg,
                        global_principles=seq_config.get("global_principles", {}),
                    )

                    # Call Claude
                    console.print(f"  [dim]{company_name} → {contact.get('full_name', 'Unknown')}...[/dim]")

                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=1000,
                        system=OUTREACH_SYSTEM,
                        messages=[{"role": "user", "content": prompt}],
                    )

                    # Track cost
                    usage = response.usage
                    self.track_cost(
                        provider="anthropic",
                        model="claude-sonnet-4-20250514",
                        endpoint="/messages",
                        company_id=company_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                    )

                    # Parse response
                    content = response.content[0].text.strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                        if content.endswith("```"):
                            content = content[:-3]
                        content = content.strip()

                    parsed = json.loads(content)

                    # Create outreach draft
                    draft_data = {
                        "company_id": company_id,
                        "contact_id": contact["id"],
                        "channel": step_config["channel"],
                        "sequence_name": sequence_name,
                        "sequence_step": sequence_step,
                        "subject": parsed.get("subject", ""),
                        "body": parsed.get("body", ""),
                        "personalization_notes": parsed.get("personalization_notes", ""),
                        "approval_status": "pending",
                    }

                    self.db.insert_outreach_draft(draft_data)

                    console.print(
                        f"  [green]{company_name} → {contact.get('full_name', 'Unknown')}: Draft created. "
                        f"Subject: \"{parsed.get('subject', '')[:50]}\"[/green]"
                    )

                    result.processed += 1
                    result.add_detail(
                        company_name,
                        "draft_created",
                        f"Contact: {contact.get('full_name')}, Channel: {step_config['channel']}",
                    )

                # Update company status (once per company, after all contacts processed)
                self.db.update_company(company_id, {"status": "outreach_pending"})

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Claude response for {company_name}: {e}")
                result.errors += 1
                result.add_detail(company_name, "error", f"JSON parse error: {str(e)[:100]}")
            except Exception as e:
                logger.error(f"Error generating outreach for {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        return result

    def _select_contacts_for_threading(
        self, contacts: list[dict], max_contacts: int = 2
    ) -> list[dict]:
        """Select multiple contacts for multi-threaded outreach.

        Picks the top N contacts by persona priority, preferring contacts
        with different persona types (e.g., VP Ops + VP Quality) over
        two contacts with the same role.
        """
        if not contacts:
            return []

        # Score and sort all contacts
        def contact_score(c: dict) -> int:
            persona = c.get("persona_type", "")
            priority = PERSONA_PRIORITY.get(persona, 0)
            dm_bonus = 50 if c.get("is_decision_maker") else 0
            email_bonus = 20 if c.get("email") else 0
            return priority + dm_bonus + email_bonus

        scored = sorted(contacts, key=contact_score, reverse=True)

        # Select diverse personas — avoid two contacts with the same persona_type
        selected = []
        seen_personas: set[str] = set()

        for c in scored:
            if len(selected) >= max_contacts:
                break
            persona = c.get("persona_type", "unknown")
            if persona not in seen_personas:
                selected.append(c)
                seen_personas.add(persona)

        # If we didn't fill max_contacts with unique personas, add duplicates
        if len(selected) < max_contacts:
            for c in scored:
                if len(selected) >= max_contacts:
                    break
                if c not in selected:
                    selected.append(c)

        return selected

    def _select_primary_contact(self, contacts: list[dict]) -> dict | None:
        """Select the best contact for outreach based on persona priority."""
        if not contacts:
            return None

        # Filter contacts with email addresses
        emailable = [c for c in contacts if c.get("email")]
        if not emailable:
            # Fall back to any contact
            emailable = contacts

        # Sort by persona priority (highest first), then decision_maker
        def contact_score(c):
            persona = c.get("persona_type", "")
            priority = PERSONA_PRIORITY.get(persona, 0)
            dm_bonus = 50 if c.get("is_decision_maker") else 0
            return priority + dm_bonus

        emailable.sort(key=contact_score, reverse=True)
        return emailable[0]

    def _build_prompt(
        self,
        company: dict,
        contact: dict,
        research: dict | None,
        step_config: dict,
        sequence_name: str,
        value_messaging: dict,
        global_principles: dict,
    ) -> str:
        """Build the Claude prompt with all context."""
        # Extract research fields
        research_summary = company.get("research_summary", "No research available")
        hooks = company.get("personalization_hooks", [])
        tech_stack = company.get("technology_stack", [])
        pain_signals = company.get("pain_signals", [])
        mfg_profile = company.get("manufacturing_profile", {})
        existing = []
        if research:
            existing = research.get("existing_solutions", [])

        # Format step instructions
        instructions = step_config.get("instructions", {})
        step_text = json.dumps(instructions, indent=2)

        # Format anti-patterns
        anti_patterns = global_principles.get("anti_patterns", [])
        anti_text = "\n".join(f"- {ap}" for ap in anti_patterns)

        # Format value messaging
        value_text = ""
        if value_messaging:
            pains = value_messaging.get("primary_pains", [])
            hooks_val = value_messaging.get("value_hooks", [])
            openers = value_messaging.get("opener_angles", [])
            value_text = (
                f"Primary Pains:\n" + "\n".join(f"- {p}" for p in pains) + "\n"
                f"Value Hooks:\n" + "\n".join(f"- {h}" for h in hooks_val) + "\n"
                f"Opener Angles:\n" + "\n".join(f"- {o}" for o in openers)
            )

        max_words = instructions.get("max_words", 150)

        return OUTREACH_USER.format(
            company_name=company.get("name", ""),
            sub_sector=company.get("sub_sector", company.get("industry", "Manufacturing")),
            tier=company.get("tier", "?"),
            city=company.get("city", ""),
            state=company.get("state", ""),
            employee_count=company.get("employee_count", "Unknown"),
            revenue_range=company.get("revenue_range", "Unknown"),
            contact_name=contact.get("full_name", contact.get("first_name", "Unknown")),
            contact_title=contact.get("title", "Unknown"),
            persona_type=contact.get("persona_type", "Unknown"),
            research_summary=research_summary,
            personalization_hooks="\n".join(f"- {h}" for h in hooks) if hooks else "None available",
            technology_stack=", ".join(tech_stack) if tech_stack else "Not identified",
            pain_signals="\n".join(f"- {p}" for p in pain_signals) if pain_signals else "Not identified",
            manufacturing_profile=json.dumps(mfg_profile, indent=2) if mfg_profile else "Not profiled",
            existing_solutions=", ".join(existing) if existing else "None identified",
            value_messaging=value_text or "No tier-specific messaging available",
            sequence_name=sequence_name,
            sequence_step=step_config["step"],
            channel=step_config["channel"],
            step_instructions=step_text,
            anti_patterns=anti_text,
            max_words=max_words,
        )
