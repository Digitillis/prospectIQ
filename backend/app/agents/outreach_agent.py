"""OutreachAgent — Hyper-personalized email draft generation.

Integrates all research context (persona, cluster, research_summary,
personalization_hooks, pain_signals, trigger_events) to produce
high-conversion outreach drafts that reference specific company intelligence.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persona-specific system prompts
# ---------------------------------------------------------------------------

PERSONA_PROMPTS: dict[str, str] = {
    "vp_ops": (
        "You are writing a cold outreach email to a VP of Operations at a manufacturing company. "
        "This executive lives in uptime, throughput, and cost-per-unit metrics. They are accountable "
        "for every unplanned stop and every quality escape that bleeds margin. They have seen countless "
        "software pitches and are deeply skeptical. They respond to specificity, operational credibility, "
        "and clear ROI tied to plant KPIs they own. Never mention 'AI' as the lead — lead with the "
        "operational outcome. Keep language blunt, plant-floor direct. No corporate buzzwords."
    ),
    "plant_manager": (
        "You are writing a cold outreach email to a Plant Manager. This person owns shift performance, "
        "quality escapes, and maintenance costs on the floor. They are measured on OEE, scrap rate, "
        "and whether production hits plan. They have limited patience for abstract value propositions — "
        "they want to know if something actually works in a plant environment. Write with operational "
        "specificity. Reference the realities of running a manufacturing shift. Short sentences. "
        "Direct ask. No fluff."
    ),
    "engineer": (
        "You are writing a cold outreach email to a Manufacturing or Reliability Engineer. This person "
        "cares about predictive maintenance, anomaly detection, and getting to root cause faster. "
        "They are technical, skeptical of vendor claims, and influenced by data and methodology. "
        "They want to understand how something works before they will champion it internally. "
        "Write with technical credibility — reference specific failure modes, sensor data, condition "
        "monitoring, or FMEA-style thinking. Avoid oversimplification. Be concrete."
    ),
    "procurement": (
        "You are writing a cold outreach email to a Procurement or Supply Chain leader at a manufacturer. "
        "This person is focused on ROI, vendor risk reduction, total cost of ownership, and implementation "
        "complexity. They gate technology decisions and need a clear business case before engaging. "
        "Lead with financial outcomes: cost reduction, risk mitigation, payback period. Avoid technical "
        "depth — focus on business value and vendor credibility. Keep it brief and boardroom-ready."
    ),
    "executive": (
        "You are writing a cold outreach email to a C-suite executive (CEO, COO, CFO, or CTO) at a "
        "manufacturing company. This person is focused on competitive edge, strategic operations, and "
        "margin improvement. They delegate to their team but will engage if the strategic framing is "
        "compelling. Lead with the market-level insight, not the product. Reference their competitive "
        "context, industry shifts, or a specific trigger event that creates urgency. Be brief, be "
        "strategic, and make the ask about a conversation, not a demo."
    ),
    "default": (
        "You are writing a cold outreach email to a manufacturing operations leader. They care about "
        "operational reliability, quality, and cost. They are skeptical of software vendors. Lead with "
        "a specific operational insight tied to their company context. Keep it under 120 words. "
        "End with one clear question or call to action."
    ),
}


# ---------------------------------------------------------------------------
# Cluster-specific context
# ---------------------------------------------------------------------------

CLUSTER_CONTEXT: dict[str, str] = {
    "machinery": (
        "This company operates in industrial machinery — equipment OEMs, CNC machining, robotics, or "
        "precision manufacturing. Key operational concerns: spindle utilization, tool wear prediction, "
        "unplanned downtime on CNC lines, preventive vs. predictive maintenance transition, and OEE "
        "on high-mix low-volume production. They likely run Allen-Bradley or Siemens PLCs with limited "
        "connectivity to their production data. Spindle hours, vibration signatures, and thermal drift "
        "are relevant technical hooks."
    ),
    "auto": (
        "This company is in automotive manufacturing — assembly, stamping, body shop, or Tier 1/2 "
        "supplier. Key concerns: press utilization, weld quality, JIT supply chain execution, and "
        "TS16949/IATF compliance. Downtime is catastrophic due to sequenced delivery commitments. "
        "They run sophisticated MES but often lack real-time anomaly detection on stamping lines or "
        "weld stations. Quality escapes that reach the OEM are existential — reference this framing."
    ),
    "chemicals": (
        "This company is in chemical or specialty chemical manufacturing. Key concerns: process safety "
        "(OSHA PSM compliance), batch-to-batch consistency, yield optimization, and environmental "
        "compliance. They run continuous or batch processes with tight regulatory oversight. "
        "Unexpected reactions, off-spec batches, and reactive maintenance on critical pumps and "
        "heat exchangers are high-consequence issues. Safety and compliance credibility must lead."
    ),
    "metals": (
        "This company is in metals manufacturing — rolling mills, foundries, heat treatment, or "
        "fabrication. Key concerns: quality yield, surface defect detection, energy cost per ton, "
        "furnace efficiency, and predictive maintenance on rolling or forming equipment. "
        "Scrap and rework rates are major margin drivers. They often lack real-time visibility into "
        "furnace performance and roll wear patterns. Metallurgical process knowledge signals credibility."
    ),
    "process": (
        "This company runs continuous process manufacturing — plastics, paper, textiles, or general "
        "process industry. Key concerns: OEE on continuous lines, tank and vessel monitoring, pump "
        "and compressor health, and unplanned stops that cause line purges and restart costs. "
        "They generate significant process data but lack the analytics layer to act on it. "
        "Reference OEE, MTBF improvement, and the cost of a single unplanned stop on a continuous line."
    ),
    "fb": (
        "This company is in food and beverage manufacturing. Key concerns: sanitation compliance "
        "(FSMA, HACCP), recipe consistency, allergen control, line changeover efficiency, and "
        "cold chain integrity. FDA 483 observations and product recalls are existential risks. "
        "They run complex multi-SKU production with aggressive changeover requirements. "
        "Food safety credibility and regulatory compliance framing will open doors with quality and ops leaders."
    ),
    "other": (
        "This is a general manufacturing company. Key concerns include operational reliability, "
        "maintenance costs, quality consistency, and production efficiency. Reference OEE, unplanned "
        "downtime costs, and the gap between reactive and predictive maintenance maturity. "
        "Keep framing broad but operationally grounded."
    ),
}


# ---------------------------------------------------------------------------
# Persona inference
# ---------------------------------------------------------------------------

_PERSONA_TITLE_MAP: list[tuple[list[str], str]] = [
    (["chief executive", "ceo", "president", "chief operating", "coo", "chief financial", "cfo",
      "chief technology", "cto", "chief digital", "chief manufacturing", "svp", "evp"], "executive"),
    (["vp operations", "vp of operations", "vice president operations", "vp manufacturing",
      "vice president manufacturing", "vp supply chain", "vice president supply", "director of operations",
      "operations director", "vp ops", "director operations"], "vp_ops"),
    (["plant manager", "plant director", "facility manager", "site manager", "production manager",
      "operations manager", "manufacturing manager", "site director"], "plant_manager"),
    (["reliability engineer", "maintenance engineer", "process engineer", "manufacturing engineer",
      "controls engineer", "automation engineer", "quality engineer", "industrial engineer",
      "engineer"], "engineer"),
    (["procurement", "purchasing", "supply chain manager", "supply chain director",
      "sourcing manager", "category manager", "vendor manager"], "procurement"),
]

_SENIORITY_EXEC = {"c_suite", "founder", "vp", "director", "partner", "owner"}
_SENIORITY_MANAGER = {"manager", "senior", "team_lead", "head"}


def _infer_persona(title: str | None, seniority: str | None) -> str:
    """Infer persona category from title and seniority level."""
    if title:
        title_lower = title.lower()
        for keywords, persona in _PERSONA_TITLE_MAP:
            if any(kw in title_lower for kw in keywords):
                return persona

    # Fall back to seniority
    if seniority:
        seniority_lower = seniority.lower()
        if any(s in seniority_lower for s in _SENIORITY_EXEC):
            return "executive"
        if any(s in seniority_lower for s in _SENIORITY_MANAGER):
            return "vp_ops"

    return "default"


# ---------------------------------------------------------------------------
# OutreachAgent
# ---------------------------------------------------------------------------

class OutreachAgent(BaseAgent):
    """Generate hyper-personalized outreach drafts using full research context."""

    agent_name = "outreach_agent"

    def run(self, **kwargs) -> AgentResult:
        """Not used directly — call generate_draft() or generate_batch()."""
        result = AgentResult()
        result.success = True
        return result

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate_draft(
        self,
        company_id: str,
        contact_id: str,
        sequence_step: str,
        workspace_id: str | None = None,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        """Generate a hyper-personalized outreach draft for a company-contact pair.

        Args:
            company_id: UUID of the company record.
            contact_id: UUID of the contact record.
            sequence_step: Sequence step name (e.g. "touch_1", "touch_2").
            workspace_id: Workspace scope (optional).
            force_regenerate: If True, skip existing draft check.

        Returns:
            The created outreach_drafts record as a dict.
        """
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set — cannot generate drafts")

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        # Load company
        company = self.db.get_company(company_id)
        if not company:
            raise ValueError(f"Company not found: {company_id}")

        # Load contacts
        contacts = self.db.get_contacts_for_company(company_id)
        contact = next((c for c in contacts if str(c.get("id")) == str(contact_id)), None)
        if not contact:
            raise ValueError(f"Contact not found: {contact_id} for company {company_id}")

        # Check for existing non-rejected draft (unless force_regenerate)
        if not force_regenerate:
            existing_drafts = self.db.client.table("outreach_drafts").select(
                "id, approval_status"
            ).eq("company_id", company_id).eq("contact_id", contact_id).eq(
                "sequence_name", "initial_outreach"
            ).neq("approval_status", "rejected").limit(1).execute().data
            if existing_drafts:
                existing_id = existing_drafts[0]["id"]
                full = self.db.client.table("outreach_drafts").select(
                    "*, companies(name, tier, pqs_total), contacts(full_name, title, email)"
                ).eq("id", existing_id).execute().data
                return full[0] if full else existing_drafts[0]

        # Resolve research context
        research_summary: dict[str, Any] = {}
        raw_research = company.get("research_summary")
        if isinstance(raw_research, dict):
            research_summary = raw_research
        elif isinstance(raw_research, str):
            try:
                research_summary = json.loads(raw_research)
            except (json.JSONDecodeError, TypeError):
                research_summary = {}

        personalization_hooks: list[str] = company.get("personalization_hooks") or []
        pain_signals: list[str] = company.get("pain_signals") or []
        campaign_cluster: str = (company.get("campaign_cluster") or "other").lower()
        manufacturing_profile: dict[str, Any] = company.get("manufacturing_profile") or {}

        # Resolve persona
        persona_type = contact.get("persona_type")
        if not persona_type:
            persona_type = _infer_persona(
                contact.get("title"),
                contact.get("seniority"),
            )

        # Select prompts
        system_prompt = PERSONA_PROMPTS.get(persona_type, PERSONA_PROMPTS["default"])
        cluster_ctx = CLUSTER_CONTEXT.get(campaign_cluster, CLUSTER_CONTEXT["other"])

        # Build rich context payload
        trigger_events: list[dict] = research_summary.get("trigger_events", [])
        equipment_profile = research_summary.get("equipment_profile") or research_summary.get("equipment_types", [])
        company_description = research_summary.get("company_description", "")
        maintenance_approach = research_summary.get("maintenance_approach", "")
        iot_maturity = research_summary.get("iot_maturity", "")
        known_systems = research_summary.get("known_systems", [])

        top_hooks = personalization_hooks[:3] if personalization_hooks else []
        top_pains = pain_signals[:2] if pain_signals else []

        contact_name = contact.get("full_name") or contact.get("first_name") or "there"
        contact_first = contact_name.split()[0] if contact_name else "there"
        contact_title = contact.get("title") or ""
        company_name = company.get("name") or ""
        company_state = company.get("state") or ""
        company_city = company.get("city") or ""

        # Confidence score based on data richness
        confidence = _compute_confidence(
            hooks=top_hooks,
            pains=top_pains,
            triggers=trigger_events,
            research=research_summary,
        )

        # Build the user prompt
        user_prompt = _build_generation_prompt(
            contact_first=contact_first,
            contact_title=contact_title,
            company_name=company_name,
            company_location=f"{company_city}, {company_state}".strip(", "),
            persona_type=persona_type,
            cluster_ctx=cluster_ctx,
            top_hooks=top_hooks,
            top_pains=top_pains,
            trigger_events=trigger_events,
            equipment_profile=equipment_profile,
            company_description=company_description,
            maintenance_approach=maintenance_approach,
            iot_maturity=iot_maturity,
            known_systems=known_systems if isinstance(known_systems, list) else [],
            manufacturing_profile=manufacturing_profile,
            sequence_step=sequence_step,
        )

        # Call Claude
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        self.track_cost(
            provider="anthropic",
            model="claude-sonnet-4-6",
            endpoint="/messages",
            company_id=company_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        raw_output = response.content[0].text.strip()

        # Parse structured output
        subject, body, personalization_notes = _parse_draft_output(raw_output)

        # Final personalization_notes: combine parsed notes with metadata
        full_notes = json.dumps({
            "parsed_notes": personalization_notes,
            "persona_type": persona_type,
            "cluster": campaign_cluster,
            "hooks_used": top_hooks,
            "pains_used": top_pains,
            "triggers_count": len(trigger_events),
            "confidence_score": confidence,
        }, separators=(",", ":"))

        # Save to DB
        draft_data = {
            "company_id": company_id,
            "contact_id": contact_id,
            "channel": "email",
            "sequence_name": "initial_outreach",
            "sequence_step": _step_to_int(sequence_step),
            "subject": subject,
            "body": body,
            "personalization_notes": full_notes,
            "approval_status": "pending",
        }

        created = self.db.insert_outreach_draft(draft_data)
        return created

    # ------------------------------------------------------------------
    # Batch generation
    # ------------------------------------------------------------------

    def generate_batch(
        self,
        company_ids: list[str],
        sequence_step: str,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate drafts for a list of companies, picking the primary contact for each.

        Args:
            company_ids: List of company UUIDs.
            sequence_step: Sequence step name to use for all drafts.
            workspace_id: Optional workspace scope.

        Returns:
            List of created outreach_drafts records.
        """
        created: list[dict[str, Any]] = []

        for company_id in company_ids:
            try:
                contacts = self.db.get_contacts_for_company(company_id)
                if not contacts:
                    logger.warning(f"No contacts found for company {company_id} — skipping")
                    continue

                # Pick primary contact: decision maker first, then highest seniority by ordering
                primary = contacts[0]
                for c in contacts:
                    if c.get("is_decision_maker"):
                        primary = c
                        break

                contact_id = str(primary["id"])
                draft = self.generate_draft(
                    company_id=company_id,
                    contact_id=contact_id,
                    sequence_step=sequence_step,
                    workspace_id=workspace_id,
                )
                created.append(draft)
                console.print(
                    f"  [green]Draft created for {company_id} / contact {contact_id}[/green]"
                )
            except Exception as e:
                logger.error(f"Batch draft failed for company {company_id}: {e}", exc_info=True)

            # Rate-limit guard between Claude calls
            time.sleep(0.5)

        return created

    # ------------------------------------------------------------------
    # Quality scoring
    # ------------------------------------------------------------------

    def score_draft_quality(
        self,
        draft_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate draft quality across four dimensions using Claude.

        Args:
            draft_id: UUID of the outreach_drafts record.
            workspace_id: Optional workspace scope.

        Returns:
            Dict with draft_id, scores (specificity/relevance/tone/cta each 1-5),
            overall (float), and suggestions (list[str]).
        """
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        # Load draft
        draft_rows = self.db.client.table("outreach_drafts").select(
            "*, companies(name, tier, campaign_cluster, personalization_hooks, pain_signals), "
            "contacts(full_name, title, persona_type, seniority)"
        ).eq("id", draft_id).execute().data

        if not draft_rows:
            raise ValueError(f"Draft not found: {draft_id}")

        draft = draft_rows[0]
        company_name = (draft.get("companies") or {}).get("name", "Unknown")
        contact_title = (draft.get("contacts") or {}).get("title", "Unknown")
        hooks = (draft.get("companies") or {}).get("personalization_hooks") or []
        pains = (draft.get("companies") or {}).get("pain_signals") or []

        scoring_prompt = _build_scoring_prompt(
            subject=draft.get("subject", ""),
            body=draft.get("body", ""),
            company_name=company_name,
            contact_title=contact_title,
            hooks=hooks[:3],
            pains=pains[:2],
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=(
                "You are a B2B outreach quality evaluator specializing in manufacturing sales. "
                "Score emails honestly. Penalize generic language and reward specific, research-backed personalization."
            ),
            messages=[{"role": "user", "content": scoring_prompt}],
        )

        self.track_cost(
            provider="anthropic",
            model="claude-sonnet-4-6",
            endpoint="/messages",
            company_id=draft.get("company_id"),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        scores_text = response.content[0].text.strip()
        scores, overall, suggestions = _parse_quality_scores(scores_text)

        return {
            "draft_id": draft_id,
            "scores": scores,
            "overall": overall,
            "suggestions": suggestions,
        }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_generation_prompt(
    contact_first: str,
    contact_title: str,
    company_name: str,
    company_location: str,
    persona_type: str,
    cluster_ctx: str,
    top_hooks: list[str],
    top_pains: list[str],
    trigger_events: list[dict],
    equipment_profile: Any,
    company_description: str,
    maintenance_approach: str,
    iot_maturity: str,
    known_systems: list[str],
    manufacturing_profile: dict,
    sequence_step: str,
) -> str:
    """Build the Claude user prompt for draft generation."""
    lines: list[str] = []

    lines.append(f"Write a cold outreach email to {contact_first}, {contact_title} at {company_name}.")
    if company_location:
        lines.append(f"Company location: {company_location}.")
    lines.append("")

    # Industry context
    lines.append("INDUSTRY CONTEXT:")
    lines.append(cluster_ctx)
    lines.append("")

    # Company intelligence
    lines.append("COMPANY INTELLIGENCE (use 1-2 of these to personalize — pick the strongest):")
    if company_description:
        lines.append(f"- Company description: {company_description[:300]}")
    if top_hooks:
        for i, hook in enumerate(top_hooks, 1):
            lines.append(f"- Personalization hook {i}: {hook}")
    if top_pains:
        for pain in top_pains:
            lines.append(f"- Pain signal: {pain}")
    if trigger_events:
        for te in trigger_events[:2]:
            if isinstance(te, dict):
                desc = te.get("description") or te.get("type", "")
                relevance = te.get("outreach_relevance", "")
                if desc:
                    lines.append(f"- Trigger event: {desc}")
                if relevance:
                    lines.append(f"  Why it matters: {relevance}")
    if equipment_profile:
        if isinstance(equipment_profile, list):
            lines.append(f"- Equipment types: {', '.join(str(e) for e in equipment_profile[:4])}")
        elif isinstance(equipment_profile, dict):
            lines.append(f"- Equipment profile: {json.dumps(equipment_profile)[:200]}")
    if maintenance_approach and maintenance_approach not in ("unknown", ""):
        lines.append(f"- Current maintenance approach: {maintenance_approach}")
    if iot_maturity and iot_maturity not in ("unknown", ""):
        lines.append(f"- IoT maturity: {iot_maturity}")
    if known_systems:
        lines.append(f"- Known systems: {', '.join(known_systems[:4])}")
    if manufacturing_profile:
        mp_str = json.dumps(manufacturing_profile)[:200]
        lines.append(f"- Manufacturing profile: {mp_str}")
    lines.append("")

    # Sequence step guidance
    step_guidance = _sequence_step_guidance(sequence_step)
    lines.append("SEQUENCE STEP GUIDANCE:")
    lines.append(step_guidance)
    lines.append("")

    # Output instructions
    lines.append("OUTPUT FORMAT (return exactly this structure):")
    lines.append("SUBJECT: <one-line subject, specific and non-generic>")
    lines.append("BODY:")
    lines.append("<email body — 4-6 sentences max, references one specific hook or trigger,")
    lines.append(" ends with a clear low-friction CTA (15-word max ask)>")
    lines.append("PERSONALIZATION_NOTES: <one sentence explaining which hook was used and why>")
    lines.append("")
    lines.append("RULES:")
    lines.append("- Never use em dashes (use commas or periods instead)")
    lines.append("- No buzzwords: 'game-changer', 'revolutionary', 'leverage', 'synergy'")
    lines.append("- Do not mention AI as the lead — lead with the operational outcome")
    lines.append("- Subject must be specific to this company, not generic")
    lines.append("- Body must feel hand-written, not templated")
    lines.append("- Do not open with 'I hope this email finds you well' or similar")
    lines.append("- Maximum 120 words in the body")
    lines.append("")
    lines.append("CRITICAL RULE — Opening sentence:")
    lines.append(
        f"The very first sentence of the email body MUST name a specific, verifiable fact about "
        f"{company_name} specifically — a recent acquisition, a specific product they make, a customer "
        f"they serve, a specific equipment class they run, or a recent business event. "
        f"Do NOT open with a category observation about the industry or equipment type in general. "
        f"The opening sentence must be something that could ONLY be written about this specific company, "
        f"not any company in their sector."
    )
    lines.append(
        "Example of WRONG opening: 'Roll forming lines running at high utilization don't give much warning.'"
    )
    lines.append(
        "Example of RIGHT opening: 'Central States ships to 3,500 dealers — a forming line going down "
        "mid-week becomes a supply commitment problem by Friday.'"
    )
    lines.append("")
    lines.append("SUBJECT LINE ROTATION RULE:")
    lines.append(
        "Do NOT use the format '[asset class] downtime at [company]' for more than 1 email in the sequence. "
        "Use one of these formulas instead:"
    )
    lines.append("  (a) Trigger event: '[Company]: [specific event implication]'")
    lines.append("      Example: 'Waupaca: post-acquisition ops scrutiny'")
    lines.append("  (b) Business consequence: '[Company] [downstream risk]'")
    lines.append("      Example: 'Central States dealer network risk'")
    lines.append("  (c) Technical hook: '[specific technical term] at [Company]'")
    lines.append("      Example: 'Spindle health at Camcraft's CNC lines'")

    return "\n".join(lines)


def _build_scoring_prompt(
    subject: str,
    body: str,
    company_name: str,
    contact_title: str,
    hooks: list[str],
    pains: list[str],
) -> str:
    """Build the prompt for quality scoring."""
    lines: list[str] = [
        f"Score this cold outreach email targeting {contact_title} at {company_name}.",
        "",
        f"SUBJECT: {subject}",
        f"BODY:\n{body}",
        "",
    ]
    if hooks:
        lines.append("AVAILABLE PERSONALIZATION HOOKS (did the email use any?):")
        for h in hooks:
            lines.append(f"- {h}")
        lines.append("")
    if pains:
        lines.append("KNOWN PAIN SIGNALS (did the email address any?):")
        for p in pains:
            lines.append(f"- {p}")
        lines.append("")

    lines += [
        "Score each dimension 1-5 (5 = excellent):",
        "SPECIFICITY (1-5): Does it reference specific facts about THIS company, not generic manufacturing?",
        "RELEVANCE (1-5): Does it connect to a real pain point or trigger this prospect cares about?",
        "TONE_MATCH (1-5): Does the tone match the recipient's seniority and function?",
        "CTA_CLARITY (1-5): Is the call to action clear, low-friction, and specific?",
        "",
        "Then provide:",
        "OVERALL: <average of 4 scores as a decimal, e.g. 3.75>",
        "SUGGESTIONS:",
        "- <specific improvement 1>",
        "- <specific improvement 2>",
        "",
        "Return in this EXACT format:",
        "SPECIFICITY: X",
        "RELEVANCE: X",
        "TONE_MATCH: X",
        "CTA_CLARITY: X",
        "OVERALL: X.X",
        "SUGGESTIONS:",
        "- suggestion 1",
        "- suggestion 2",
    ]
    return "\n".join(lines)


def _sequence_step_guidance(step: str) -> str:
    """Return tone/angle guidance per sequence step."""
    step_lower = step.lower()
    if "touch_1" in step_lower or step_lower in ("1", "touch1", "initial"):
        return (
            "This is the first touch. Lead with insight, not a pitch. "
            "Reference one specific hook or trigger. End with a single soft question "
            "('Would this be worth a quick conversation?'). Do not ask to book a call or demo."
        )
    elif "touch_2" in step_lower or step_lower in ("2", "touch2", "follow_up"):
        return (
            "This is a follow-up to a prior email. Acknowledge you reached out before. "
            "Add a new data point or operational angle they haven't seen. "
            "Slightly more direct CTA — ask for 15 minutes."
        )
    elif "touch_3" in step_lower or step_lower in ("3", "touch3"):
        return (
            "This is the third and final touch. Be honest that this is the last outreach. "
            "Make one final compelling point. Ask if the timing is wrong or if there's "
            "a better person to speak with."
        )
    else:
        return (
            "Write a professional, direct outreach email. Lead with a specific insight "
            "relevant to this company. End with a clear, low-friction CTA."
        )


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def _parse_draft_output(raw: str) -> tuple[str, str, str]:
    """Parse SUBJECT / BODY / PERSONALIZATION_NOTES from Claude output.

    Returns (subject, body, personalization_notes).
    """
    subject = ""
    body = ""
    notes = ""

    lines = raw.split("\n")
    current_section = None
    body_lines: list[str] = []
    notes_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("SUBJECT:"):
            current_section = "subject"
            subject = stripped[len("SUBJECT:"):].strip()
        elif stripped.upper().startswith("BODY:"):
            current_section = "body"
        elif stripped.upper().startswith("PERSONALIZATION_NOTES:"):
            current_section = "notes"
            rest = stripped[len("PERSONALIZATION_NOTES:"):].strip()
            if rest:
                notes_lines.append(rest)
        else:
            if current_section == "body":
                body_lines.append(line)
            elif current_section == "notes":
                notes_lines.append(line)

    body = "\n".join(body_lines).strip()
    notes = " ".join(notes_lines).strip()

    # Fallback: if parsing failed, use the entire raw output as body
    if not subject and not body:
        body = raw
        subject = "Following up on your operations"

    return subject, body, notes


def _parse_quality_scores(raw: str) -> tuple[dict[str, int], float, list[str]]:
    """Parse quality score output from Claude.

    Returns (scores_dict, overall_float, suggestions_list).
    """
    scores: dict[str, int] = {
        "specificity": 0,
        "relevance": 0,
        "tone_match": 0,
        "cta_clarity": 0,
    }
    overall: float = 0.0
    suggestions: list[str] = []

    in_suggestions = False
    for line in raw.split("\n"):
        stripped = line.strip()

        if stripped.upper().startswith("SPECIFICITY:"):
            scores["specificity"] = _parse_int(stripped.split(":", 1)[1])
        elif stripped.upper().startswith("RELEVANCE:"):
            scores["relevance"] = _parse_int(stripped.split(":", 1)[1])
        elif stripped.upper().startswith("TONE_MATCH:"):
            scores["tone_match"] = _parse_int(stripped.split(":", 1)[1])
        elif stripped.upper().startswith("CTA_CLARITY:"):
            scores["cta_clarity"] = _parse_int(stripped.split(":", 1)[1])
        elif stripped.upper().startswith("OVERALL:"):
            try:
                overall = float(stripped.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif stripped.upper().startswith("SUGGESTIONS:"):
            in_suggestions = True
        elif in_suggestions and stripped.startswith("-"):
            suggestions.append(stripped[1:].strip())

    # Compute overall if not parsed
    if overall == 0.0 and any(scores.values()):
        vals = [v for v in scores.values() if v > 0]
        overall = sum(vals) / len(vals) if vals else 0.0

    return scores, round(overall, 2), suggestions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_confidence(
    hooks: list[str],
    pains: list[str],
    triggers: list[dict],
    research: dict,
) -> float:
    """Compute a 0.0-1.0 confidence score based on data richness."""
    score = 0.0
    if hooks:
        score += min(len(hooks) * 0.15, 0.3)
    if pains:
        score += min(len(pains) * 0.1, 0.2)
    if triggers:
        score += min(len(triggers) * 0.1, 0.2)
    if research.get("company_description"):
        score += 0.15
    if research.get("equipment_types") or research.get("equipment_profile"):
        score += 0.1
    if research.get("maintenance_approach") and research["maintenance_approach"] != "unknown":
        score += 0.05
    return round(min(score, 1.0), 2)


def _step_to_int(step: str) -> int:
    """Convert sequence step string to integer."""
    try:
        return int(step)
    except (ValueError, TypeError):
        pass
    step_lower = step.lower()
    if "1" in step_lower or "initial" in step_lower:
        return 1
    if "2" in step_lower:
        return 2
    if "3" in step_lower:
        return 3
    return 1


def _parse_int(s: str) -> int:
    """Parse an integer from a string, returning 0 on failure."""
    try:
        return int(s.strip().split("/")[0].strip())
    except (ValueError, IndexError, AttributeError):
        return 0
