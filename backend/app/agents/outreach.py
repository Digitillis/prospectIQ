"""Outreach Agent — Personalized message generation.

Uses Claude (1 call per message) to generate deeply personalized
outreach messages based on research intelligence and sequence config.
"""

from __future__ import annotations

import json
import logging
import random

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import (
    get_settings,
    get_sequences_config,
    get_manufacturing_ontology,
    get_outreach_guidelines,
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

def _build_system_prompt() -> str:
    """Build the outreach system prompt from outreach_guidelines.yaml.

    Reads the YAML every time so dashboard edits are picked up
    immediately without restarting the server.
    """
    try:
        g = get_outreach_guidelines()
    except FileNotFoundError:
        # Fallback if YAML doesn't exist
        return (
            "You are writing cold outreach emails for Digitillis, an AI manufacturing platform. "
            "Write in a direct, conversational, founder-to-operator tone. No filler. No buzzwords."
        )

    sender = g.get("sender", {})
    voice = g.get("voice_and_tone", "")
    structure = g.get("email_structure", "")
    must_include = g.get("must_include", [])
    never_include = g.get("never_include", [])
    banned_phrases = g.get("banned_phrases", [])
    banned_chars = g.get("banned_characters", [])
    facts = g.get("digitillis_facts", [])
    subject_rules = g.get("subject_line_rules", "")
    signature = sender.get("signature", "")

    parts = [
        f"You are writing cold outreach emails on behalf of {sender.get('name', 'Avanish Mehrotra')}, "
        f"{sender.get('title', 'Founder & CEO')} of {sender.get('company', 'Digitillis')}.",
        "",
        "VOICE & TONE:",
        voice,
        "",
        "STRUCTURE (every email must follow this):",
        structure,
        "",
        "WHAT TO INCLUDE:",
        *[f"- {item}" for item in must_include],
        "",
        "CRITICAL FORMATTING RULES:",
        "- NEVER use em dashes or en dashes. Use commas, periods, or 'and' instead.",
        "- Write in natural spoken English. If it sounds like AI wrote it, rewrite it.",
        "- Use contractions naturally. Vary sentence length.",
        *[f"- NEVER use the phrase: '{bp}'" for bp in banned_phrases[:10]],  # Top 10 to save tokens
        *[f"- NEVER use this character: {bc}" for bc in banned_chars],
        "",
        "WHAT TO NEVER INCLUDE:",
        *[f"- {item}" for item in never_include],
        "",
        "SUBJECT LINE RULES:",
        subject_rules,
        "",
        "DIGITILLIS FACTS (use selectively, not as a list):",
        *[f"- {fact}" for fact in facts],
        "",
        "## PERSONALIZATION DEPTH",
        "",
        "You MUST achieve Level 3 personalization. Here's the scale:",
        "",
        "Level 1 (REJECTED): 'I noticed {company} is in manufacturing.'",
        "Level 2 (ACCEPTABLE): 'I noticed {company} makes {product} and has {N} employees in {state}.'",
        "Level 3 (REQUIRED): 'I've been thinking about how {specific_equipment_type} OEMs like {company} handle {specific_operational_challenge} -- especially given {recent_context}.'",
        "",
        "To achieve Level 3:",
        "- Reference their SPECIFIC sub-sector challenge, not just their industry",
        "- Use the research intelligence to identify what operational problem they likely face",
        "- Frame the challenge in terms that show you understand their world",
        "- If research found pain_points, weave one into the opening naturally",
        "- If research found technology_stack, reference how their current systems create gaps",
        "",
        "## WHAT MAKES THIS EMAIL WORTH READING",
        "",
        "The recipient gets 50+ cold emails per week. Yours must pass the 'screenshot test':",
        "Would they screenshot this email and forward it to a colleague? If not, rewrite.",
        "",
        "Ways to pass the screenshot test:",
        "- Share a specific, surprising data point they didn't know",
        "- Name a regulatory change that affects their specific operation",
        "- Reference a benchmark from their sub-sector (not generic 'manufacturing')",
        "- Ask a question so specific it proves you understand their daily work",
        "",
        "SIGNATURE (use exactly this, on every email):",
        signature,
    ]

    return "\n".join(parts)

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
    "subject": "Short, specific subject line referencing their company or situation (under 50 chars, no generic subjects)",
    "body": "The email body. {max_words} words max. Must end with the exact signature block from the system prompt.",
    "personalization_notes": "Which specific research facts you used and why you chose this angle for this prospect"
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

                # Company-level send lock — prevent multi-contact collision
                from backend.app.core.channel_coordinator import is_company_locked, has_recent_activity
                locked, lock_reason = is_company_locked(self.db, company_id)
                if locked:
                    console.print(f"  [dim]{company_name}: company locked — {lock_reason}[/dim]")
                    result.skipped += 1
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
                    # Warm intro collision detection — skip cold outreach if a warm
                    # intro is in progress for this contact
                    contact_status = contact.get("linkedin_status", "") or ""
                    if "warm" in contact_status.lower():
                        console.print(
                            f"  [dim]{company_name}: {contact.get('full_name', '?')} "
                            f"— warm intro in progress ({contact_status}). Skipping cold outreach.[/dim]"
                        )
                        continue

                    # Cross-channel check — block email if LinkedIn is active
                    from backend.app.core.channel_coordinator import can_use_channel
                    channel_ok, channel_reason = can_use_channel(self.db, contact["id"], "email")
                    if not channel_ok:
                        console.print(
                            f"  [dim]{company_name}: {contact.get('full_name', '?')} — email blocked ({channel_reason})[/dim]"
                        )
                        # Don't skip the company, just skip this contact
                        continue

                    # 48-hour activity cooldown — prevent rapid-fire touches
                    recent, activity_desc = has_recent_activity(self.db, contact["id"])
                    if recent:
                        console.print(f"  [dim]{company_name}: {contact.get('full_name', '?')}: 48h cooldown — {activity_desc}[/dim]")
                        continue

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
                        system=_build_system_prompt(),
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

                    # Add jitter to prevent all approved drafts from sending at the same time.
                    # Instantly.ai uses this field to stagger sends when drafts are queued.
                    suggested_delay_minutes = random.randint(0, 30)

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
                        "suggested_delay_minutes": suggested_delay_minutes,
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
        """Build the Claude prompt with all context.

        Merges data from both the company record AND the research table
        to maximize personalization depth.
        """
        # Pull from company record first
        research_summary = company.get("research_summary", "")
        hooks = list(company.get("personalization_hooks", []) or [])
        tech_stack = list(company.get("technology_stack", []) or [])
        pain_signals = list(company.get("pain_signals", []) or [])
        mfg_profile = dict(company.get("manufacturing_profile", {}) or {})
        existing = []

        # Merge in research intelligence (often richer than company record)
        if research:
            ri = research.get("research_intelligence", {}) or {}
            existing = research.get("existing_solutions", []) or ri.get("existing_solutions", []) or []
            if not research_summary:
                research_summary = research.get("summary", "") or ri.get("summary", "")
            # Merge pain points
            for p in (ri.get("pain_points", []) or research.get("pain_points", []) or []):
                if p and p not in pain_signals:
                    pain_signals.append(p)
            # Merge personalization hooks
            for h in (ri.get("personalization_hooks", []) or []):
                if h and h not in hooks:
                    hooks.append(h)
            # Merge known systems into tech stack
            for s in (ri.get("known_systems", []) or research.get("known_systems", []) or []):
                if s and s not in tech_stack:
                    tech_stack.append(s)
            # Merge products/services into profile
            products = ri.get("products_services", []) or []
            if products:
                mfg_profile["products_services"] = products
            # Recent news
            recent_news = ri.get("recent_news", []) or []
            if recent_news:
                mfg_profile["recent_news"] = recent_news[:3]

        if not research_summary:
            research_summary = "No research available — use company industry and contact title to infer specific challenges"

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
