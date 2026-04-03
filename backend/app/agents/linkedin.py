"""LinkedIn Agent — Generate personalized LinkedIn messages.

Uses Claude (1 call per contact) to generate all 3 LinkedIn message types:
  - Connection note  (50 words max, no pitch, one company fact)
  - Opening DM       (80 words max, genuine process question, no product mention)
  - Follow-up DM     (100 words max, soft product mention, CTA)

LinkedIn messages are auto-approved on creation (they are copy-pasted manually,
so no approval workflow is needed).
"""

from __future__ import annotations

import json
import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_manufacturing_ontology
from backend.app.core.model_router import get_model

console = Console()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Config loader (graceful fallback if YAML doesn't exist yet)
# ─────────────────────────────────────────────────────────────────────────────

def get_linkedin_messages_guidelines() -> dict:
    """Load LinkedIn messages guidelines from config YAML.

    NOT cached — reads fresh from disk each call so dashboard edits are
    picked up without a server restart.
    """
    try:
        from backend.app.core.config import load_yaml_config
        return load_yaml_config("linkedin_messages_guidelines.yaml")
    except FileNotFoundError:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# System prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_system_prompt(guidelines: dict) -> str:
    """Build the LinkedIn system prompt from guidelines YAML (or sensible defaults)."""
    sender = guidelines.get("sender", {})
    sender_name = sender.get("name", "the sender")
    sender_title = sender.get("title", "")
    sender_company = sender.get("company", "the company")

    voice = guidelines.get("voice_and_tone", (
        "Direct, human, expert-to-operator. No filler. No buzzwords. "
        "Sounds like a real person, not a sales bot."
    ))
    never = guidelines.get("never_include", [
        "We help companies like yours",
        "I came across your profile",
        "Hope this message finds you well",
        "I wanted to reach out",
        "Revolutionary / game-changing / cutting-edge",
    ])
    banned_phrases = guidelines.get("banned_phrases", [])
    facts = guidelines.get("product_facts", guidelines.get("digitillis_facts", [
        "The product is purpose-built for the target industry",
        "Helps predict operational failures before they happen",
        "Reduces unplanned downtime and improves operational efficiency",
    ]))

    parts = [
        f"You are writing LinkedIn messages on behalf of {sender_name}, "
        f"{sender_title} of {sender_company}.",
        "",
        "VOICE & TONE:",
        voice,
        "",
        "CRITICAL RULES:",
        "- NEVER use em dashes or en dashes. Use commas, periods, or 'and' instead.",
        "- Write in natural spoken English. Short sentences. Vary length.",
        "- No filler openers (no 'I hope this finds you well', 'I came across your profile').",
        "- No corporate buzzwords.",
        *[f"- NEVER use: '{bp}'" for bp in banned_phrases[:8]],
        "",
        "NEVER INCLUDE:",
        *[f"- {item}" for item in never],
        "",
        "PRODUCT FACTS (use sparingly, max 1 per message):",
        *[f"- {fact}" for fact in facts],
        "",
        "## LINKEDIN MESSAGE QUALITY",
        "",
        "Every message must demonstrate that you understand their SPECIFIC world,",
        "not just their company name.",
        "",
        "BAD connection note: 'Hi Greg, I see you're at CST Industries. Would love to connect.'",
        "GOOD connection note: 'Greg, I saw CST's bulk storage work for dairy processors. I am curious how you are seeing the thermal monitoring requirements evolve.'",
        "",
        "The connection note must reference ONE specific thing about their work that",
        "shows you actually looked at what they do, not just their company name.",
        "",
        "The opening DM must ask a question so specific that only someone who",
        "understands their sub-sector would ask it.",
        "",
        "## WRITING STYLE RULES (MANDATORY)",
        "",
        "- Always use first person explicitly: 'I saw', 'I am curious', 'I have been'. NEVER drop the subject ('Saw...', 'Curious how...').",
        "- Use 'I am' not 'I'm' in connection notes (more professional first touch). Contractions OK in DMs.",
        "- No em dashes. Use commas or periods instead.",
        "- No sentence fragments. Every sentence must have a subject and verb.",
        "",
        "## CLOSING RULES (BY STAGE)",
        "",
        "- Connection note: NO closing CTA. End with a statement or observation. No 'Would love to connect'. The content IS the close.",
        "- Opening DM: End with the question itself. The question IS the close. No 'Would love to hear your thoughts' after the question.",
        "- Follow-up DM: One soft sentence that leaves a door open without pushing. Examples: 'Happy to share the framework if useful.' or 'Let me know if any of that maps to what you are seeing.' NEVER: 'Would love to set up a call' or 'Let me know when you are free.'",
        "",
        "PERSONALIZATION DEPTH SCALE:",
        "Level 1 (REJECTED): 'Hi [Name], I see you work in manufacturing.'",
        "Level 2 (ACCEPTABLE): 'Hi [Name], I see [Company] makes [product] in [state].'",
        "Level 3 (REQUIRED): '[Name], I saw [Company]'s [specific work]. I am curious how you handle [specific challenge that only someone in their sub-sector would face].'",
        "",
        "To achieve Level 3 on LinkedIn:",
        "- Connection note: name one specific thing about what they actually do (product, customer type, process)",
        "- Opening DM: ask about a challenge so specific it signals real domain knowledge",
        "- Follow-up DM: connect their challenge to what you're building with one sentence max",
    ]

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Prompt template
# ─────────────────────────────────────────────────────────────────────────────

LINKEDIN_USER = """Generate 3 LinkedIn messages for this prospect.

COMPANY:
- Name: {company_name}
- Industry/Sub-sector: {sub_sector} (Tier {tier})
- Location: {city}, {state}
- Employees: {employee_count}

CONTACT:
- Name: {contact_name}
- Title: {contact_title}
- Vertical: {vertical}

RESEARCH INTELLIGENCE:
{research_summary}

PERSONALIZATION HOOKS (pick the most specific one):
{personalization_hooks}

PAIN SIGNALS:
{pain_signals}

MANUFACTURING PROFILE:
{manufacturing_profile}

VERTICAL-SPECIFIC CONTEXT:
{vertical_context}

---

Generate exactly 3 messages. Follow these rules strictly:

HARD REJECTION RULES — if your output contains ANY of these, regenerate:
- "I noticed you work at [company]" — NEVER state the obvious.
- "Would love to connect" without a specific reason.
- "share some ideas" — vague.
- Any message that could apply to 100 different companies unchanged.
- Any message that only references the company NAME without what they DO.
- Sentence fragments like "Saw your company..." or "Curious about..." — always use complete sentences with explicit subject ("I saw...", "I am curious...").
- Em dashes (—) or en dashes (–) anywhere.

WRITING STYLE (sender's voice):
- Write in complete sentences. Never start with a fragment.
- Use explicit first person: "I saw", "I am curious", "I have been following" — not "Saw", "Curious about", "Been following".
- Do NOT use contractions in connection notes (first impression). "I am" not "I'm". "I have" not "I've". DMs can use contractions sparingly.
- Start with the name on its own, followed by a comma. Then the message body.
- End connection notes with a brief closing thought or question. Not abrupt.
- Keep the tone warm but professional. Like a peer introducing themselves at an industry conference.

EXAMPLE of correct style:
"Kyle, I saw Douglas Dynamics' fabrication work for snow and ice control attachments. I am curious how you handle the seasonal production ramp challenges with welding equipment reliability."

EXAMPLE of wrong style (REJECTED):
"Kyle, saw Douglas Dynamics' fabrication work for snow and ice control. Curious how you're handling seasonal ramp challenges with welding reliability."

1. CONNECTION NOTE (STRICT LIMIT: 200 characters max, including spaces)
   - LinkedIn enforces a 200-character limit on connection notes. You MUST stay under 200 characters.
   - Reference ONE specific company fact: what they MAKE or a recent event.
   - No pitch. No product mention. No "Would love to connect."
   - NO closing CTA. Content IS the close.
   - Complete sentences. "I am" not "I'm". Keep it tight — every word must earn its place.

2. OPENING DM (80 words max)
   - Jump straight into the question. Do NOT open with "Thanks for connecting"
     or "Thanks for accepting." Start with their name and go directly into a
     genuine question about their operations.
   - The question should demonstrate domain expertise specific to their sub-sector.
   - No product mention. Pure research and curiosity only.
   - Use "I am" not "I'm". Complete sentences with explicit subjects.

3. FOLLOW-UP DM (100 words max, send 5-7 days after opening DM if no reply)
   - You can mention what you are building (1 sentence max).
   - End with ONE soft sentence that leaves a door open without pushing.
     GOOD: "Happy to share the framework if useful." or "Let me know if any of that maps to what you are seeing."
     BAD: "Would love to set up a call." or "Let me know when you are free."
   - Complete sentences. Warm, not pushy.

OUTPUT FORMAT (JSON):
{{
    "connection_note": "MUST be under 200 characters including spaces",
    "opening_dm": "The opening DM text (80 words max)",
    "followup_dm": "The follow-up DM text (100 words max)",
    "personalization_notes": "Which specific research facts you used and why"
}}

Output ONLY valid JSON. No markdown, no explanation."""


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class LinkedInAgent(BaseAgent):
    """Generate personalized LinkedIn messages using Claude."""

    agent_name = "linkedin"

    # Sequence names used to store the 3 message types as separate drafts
    SEQUENCE_CONNECTION = "linkedin_connection"
    SEQUENCE_DM_OPENING = "linkedin_dm_opening"
    SEQUENCE_DM_FOLLOWUP = "linkedin_dm_followup"

    def run(
        self,
        company_ids: list[str] | None = None,
        limit: int = 20,
        regenerate: bool = False,
        mode: str = "all",  # "all" (generates all 3 messages) or "dm_only" (only opening + follow-up DM)
    ) -> AgentResult:
        """Generate LinkedIn message drafts for qualified contacts.

        Args:
            company_ids: Specific company IDs to process (overrides query).
            limit: Max companies to process when company_ids is not set.
            regenerate: If True, regenerate even if drafts already exist.
            mode: "all" generates connection note + opening DM + follow-up DM.
                  "dm_only" only generates opening DM + follow-up DM, for contacts
                  where a connection has already been accepted.

        Returns:
            AgentResult with draft creation stats.
        """
        result = AgentResult()
        settings = get_settings()
        ontology = get_manufacturing_ontology()
        guidelines = get_linkedin_messages_guidelines()

        # Get companies to process
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        else:
            companies = self.db.get_companies(status="qualified", limit=limit)

        if not companies:
            console.print("[yellow]No qualified companies found for LinkedIn outreach.[/yellow]")
            return result

        console.print(
            f"[cyan]Generating LinkedIn messages for {len(companies)} companies...[/cyan]"
        )

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        system_prompt = _build_system_prompt(guidelines)

        for company in companies:
            company_name = company["name"]
            company_id = company["id"]

            try:
                # Suppression check
                from backend.app.core.suppression import is_suppressed

                suppressed, reason = is_suppressed(self.db, company_id)
                if suppressed:
                    console.print(f"  [dim]{company_name}: Suppressed ({reason}). Skipping.[/dim]")
                    result.skipped += 1
                    result.add_detail(company_name, "suppressed", reason or "")
                    continue

                # Company-level send lock — prevent multi-contact collision
                from backend.app.core.channel_coordinator import is_company_locked, has_recent_activity
                locked, lock_reason = is_company_locked(self.db, company_id)
                if locked:
                    console.print(f"  [dim]{company_name}: company locked — {lock_reason}[/dim]")
                    result.skipped += 1
                    result.add_detail(company_name, "company_locked", lock_reason or "")
                    continue

                # Get contacts with a LinkedIn URL
                all_contacts = self.db.get_contacts_for_company(company_id)
                contacts = [c for c in all_contacts if c.get("linkedin_url")]

                # In dm_only mode, restrict to contacts with an accepted connection
                if mode == "dm_only":
                    contacts = [
                        c for c in contacts
                        if c.get("linkedin_status") == "connection_accepted"
                    ]

                if not contacts:
                    console.print(
                        f"  [yellow]{company_name}: No contacts with LinkedIn URL. Skipping.[/yellow]"
                    )
                    result.skipped += 1
                    result.add_detail(company_name, "skipped", "No contacts with linkedin_url")
                    continue

                # Get research intelligence
                research = self.db.get_research(company_id)

                for contact in contacts:
                    contact_id = contact["id"]
                    contact_name = contact.get("full_name") or contact.get("first_name", "Unknown")

                    # Skip if drafts already exist (unless regenerate=True)
                    if not regenerate:
                        existing = self._get_existing_linkedin_drafts(company_id, contact_id)
                        if existing:
                            console.print(
                                f"  [dim]{company_name} → {contact_name}: "
                                f"LinkedIn drafts already exist. Skipping (use regenerate=True to overwrite).[/dim]"
                            )
                            result.skipped += 1
                            continue

                    # Suppress check for the individual contact
                    contact_suppressed, contact_reason = is_suppressed(
                        self.db, company_id, contact_id
                    )
                    if contact_suppressed:
                        console.print(
                            f"  [dim]{company_name}: {contact_name} suppressed ({contact_reason})[/dim]"
                        )
                        result.skipped += 1
                        continue

                    # 48-hour activity cooldown — prevent rapid-fire touches
                    recent, activity_desc = has_recent_activity(self.db, contact_id)
                    if recent:
                        console.print(f"  [dim]{company_name}: {contact_name}: 48h cooldown — {activity_desc}[/dim]")
                        result.skipped += 1
                        continue

                    # Determine vertical (F&B vs Mfg) from tier prefix
                    tier = company.get("tier", "")
                    vertical = "food_beverage" if str(tier).startswith("fb") else "manufacturing"
                    vertical_context = self._build_vertical_context(vertical, tier, ontology)

                    # Build the prompt
                    prompt = self._build_prompt(
                        company=company,
                        contact=contact,
                        research=research,
                        vertical=vertical,
                        vertical_context=vertical_context,
                    )

                    # Call Claude
                    console.print(f"  [dim]{company_name} → {contact_name}...[/dim]")

                    _model = get_model("linkedin_msg")
                    response = client.messages.create(
                        model=_model,
                        max_tokens=1200,
                        system=system_prompt,
                        messages=[{"role": "user", "content": prompt}],
                    )

                    # Track cost
                    usage = response.usage
                    self.track_cost(
                        provider="anthropic",
                        model=_model,
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
                    personalization_notes = parsed.get("personalization_notes", "")

                    # Store message types as separate outreach_drafts.
                    # In dm_only mode, skip the connection note.
                    if mode == "dm_only":
                        message_map = [
                            (self.SEQUENCE_DM_OPENING, "opening_dm", 2),
                            (self.SEQUENCE_DM_FOLLOWUP, "followup_dm", 3),
                        ]
                    else:
                        message_map = [
                            (self.SEQUENCE_CONNECTION, "connection_note", 1),
                            (self.SEQUENCE_DM_OPENING, "opening_dm", 2),
                            (self.SEQUENCE_DM_FOLLOWUP, "followup_dm", 3),
                        ]

                    for sequence_name, key, step in message_map:
                        body_text = parsed.get(key, "")
                        if not body_text:
                            continue

                        draft_data = {
                            "company_id": company_id,
                            "contact_id": contact_id,
                            "channel": "linkedin",
                            "sequence_name": sequence_name,
                            "sequence_step": step,
                            "subject": "",  # LinkedIn messages have no subject
                            "body": body_text,
                            "personalization_notes": personalization_notes,
                            # All drafts require explicit human approval before sending
                            "approval_status": "pending",
                        }
                        self.db.insert_outreach_draft(draft_data)

                    msg_count = len(message_map)
                    console.print(
                        f"  [green]{company_name} → {contact_name}: "
                        f"{msg_count} LinkedIn message(s) created (auto-approved).[/green]"
                    )

                    result.processed += 1
                    result.add_detail(
                        company_name,
                        "linkedin_drafts_created",
                        f"Contact: {contact_name}, LinkedIn: {contact.get('linkedin_url', '')}",
                    )

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Claude response for {company_name}: {e}")
                result.errors += 1
                result.add_detail(company_name, "error", f"JSON parse error: {str(e)[:100]}")
            except Exception as e:
                logger.error(
                    f"Error generating LinkedIn messages for {company_name}: {e}", exc_info=True
                )
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_existing_linkedin_drafts(self, company_id: str, contact_id: str) -> bool:
        """Return True if LinkedIn drafts already exist for this contact."""
        try:
            result = (
                self.db.client.table("outreach_drafts")
                .select("id")
                .eq("company_id", company_id)
                .eq("contact_id", contact_id)
                .eq("channel", "linkedin")
                .limit(1)
                .execute()
            )
            return bool(result.data)
        except Exception:
            return False

    def _build_vertical_context(self, vertical: str, tier: str, ontology: dict) -> str:
        """Build vertical-specific context for the prompt."""
        value_msg = ontology.get("value_messaging", {}).get(str(tier), {})
        if not value_msg:
            # Try without tier prefix if not found
            value_msg = ontology.get("value_messaging", {}).get(tier.replace("fb_", "").replace("mfg_", ""), {})

        if vertical == "food_beverage":
            pains = value_msg.get("primary_pains", [
                "FSMA compliance burden and audit preparation",
                "Unplanned downtime on filling, mixing, and packaging lines",
                "Manual HACCP monitoring processes",
                "Food safety traceability requirements",
            ])
            context = (
                "Vertical: Food & Beverage\n"
                "Key pain areas: " + ", ".join(pains[:3])
            )
        else:
            pains = value_msg.get("primary_pains", [
                "Unplanned equipment downtime and reactive maintenance",
                "OEE improvements and bottleneck detection",
                "Quality defect root cause analysis",
                "Energy consumption optimization",
            ])
            context = (
                "Vertical: Discrete / Process Manufacturing\n"
                "Key pain areas: " + ", ".join(pains[:3])
            )

        return context

    def _build_prompt(
        self,
        company: dict,
        contact: dict,
        research: dict | None,
        vertical: str,
        vertical_context: str,
    ) -> str:
        """Build the Claude prompt with all research context.

        Merges data from both the company record AND the research table
        to maximize personalization depth.
        """
        # Pull from company record first
        research_summary = company.get("research_summary", "")
        hooks = list(company.get("personalization_hooks", []) or [])
        pain_signals = list(company.get("pain_signals", []) or [])
        mfg_profile = dict(company.get("manufacturing_profile", {}) or {})

        # Merge in research intelligence (often richer than company record)
        if research:
            ri = research.get("research_intelligence", {}) or {}
            if not research_summary:
                research_summary = research.get("summary", "") or ri.get("summary", "")
            # Merge pain points from research
            research_pains = ri.get("pain_points", []) or research.get("pain_points", []) or []
            for p in research_pains:
                if p and p not in pain_signals:
                    pain_signals.append(p)
            # Merge personalization hooks
            research_hooks = ri.get("personalization_hooks", []) or []
            for h in research_hooks:
                if h and h not in hooks:
                    hooks.append(h)
            # Merge known systems into profile
            known_systems = ri.get("known_systems", []) or research.get("known_systems", []) or []
            if known_systems:
                mfg_profile["known_systems"] = known_systems
            # Merge products/services
            products = ri.get("products_services", []) or []
            if products:
                mfg_profile["products_services"] = products
            # Recent news
            recent_news = ri.get("recent_news", []) or []
            if recent_news:
                mfg_profile["recent_news"] = recent_news[:3]
            # Confidence level
            confidence = research.get("confidence_level", "")
            if confidence:
                mfg_profile["research_confidence"] = confidence

        vertical_label = "Food & Beverage" if vertical == "food_beverage" else "Manufacturing"

        return LINKEDIN_USER.format(
            company_name=company.get("name", ""),
            sub_sector=company.get("sub_sector", company.get("industry", "Manufacturing")),
            tier=company.get("tier", "?"),
            city=company.get("city", ""),
            state=company.get("state", ""),
            employee_count=company.get("employee_count", "Unknown"),
            contact_name=contact.get("full_name") or contact.get("first_name", "Unknown"),
            contact_title=contact.get("title", "Unknown"),
            vertical=vertical_label,
            research_summary=research_summary or "No research available — use company industry and contact title to infer specific challenges",
            personalization_hooks=(
                "\n".join(f"- {h}" for h in hooks) if hooks else "None available — infer from company sub-sector and contact role"
            ),
            pain_signals=(
                "\n".join(f"- {p}" for p in pain_signals) if pain_signals else "Not identified — infer from industry and company size"
            ),
            manufacturing_profile=(
                json.dumps(mfg_profile, indent=2) if mfg_profile else "Not profiled"
            ),
            vertical_context=vertical_context,
        )
