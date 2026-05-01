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
    get_offer_context,
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

# Title keywords that disqualify a contact from cold outreach.
# These roles don't buy manufacturing ops AI — emailing them burns credibility.
_WRONG_PERSONA_TITLE_SIGNALS = (
    "sales", "business development", " bd ", "account manager",
    "account executive", "marketing", "advertising", "public relations",
    "human resources", "hr manager", "hr director", "hr business", "hr generalist",
    "recrui", "talent acquisition",
    "finance", "financial", "controller", "accounting", "treasurer",
    "legal", "counsel", "attorney", "compliance officer",
    "procurement", "purchasing",  # borderline — exclude; they don't sponsor AI
    "customer service", "customer success",
)

# Suffix patterns that flag Apollo data scraping artifacts embedded in title fields.
_TITLE_ARTIFACT_PATTERNS = (
    "related to search",
    "at the company",
    " at ",  # "Operations Manager at Acme" — company name leaked into title
)

_REQUIRED_OPS_SIGNALS = (
    "operation", "manufactur", "plant", "production", "maintenance",
    "reliability", "engineering", "quality", "process", "supply chain",
    "director", "vice president", "vp", "coo", "cto", "ceo", "president",
    "general manager", "gm", "site manager", "facility", "continuous improvement",
    "lean", "digital transform", "technology", "it ",
)


def _is_wrong_persona(contact: dict) -> bool:
    """Return True if this contact's title signals a non-buyer persona."""
    title = (contact.get("title") or "").lower().strip()
    if not title:
        return False  # Unknown title: give benefit of the doubt

    # Catch Apollo artifact titles (scraping noise, not real job titles)
    for artifact in _TITLE_ARTIFACT_PATTERNS:
        if artifact in title:
            return True

    # Title starts with "hr " or is exactly "hr" — handles "HR Manager", "HR Director"
    if title == "hr" or title.startswith("hr "):
        return True

    # Explicit disqualifying signals
    for signal in _WRONG_PERSONA_TITLE_SIGNALS:
        if signal in title:
            return True

    return False

def _build_system_prompt() -> str:
    """Build the outreach system prompt from outreach_guidelines.yaml + offer_context.yaml.

    Reads both YAMLs every time so dashboard edits are picked up
    immediately without restarting the server.
    """
    try:
        g = get_outreach_guidelines()
    except FileNotFoundError:
        # Fallback if YAML doesn't exist
        return (
            "You are writing cold outreach emails on behalf of the sender. "
            "Write in a direct, conversational, expert-to-operator tone. No filler. No buzzwords."
        )

    # Load offer context — always fresh
    try:
        offer = get_offer_context()
    except FileNotFoundError:
        offer = {}

    sender = g.get("sender", {})
    voice = g.get("voice_and_tone", "")
    structure = g.get("email_structure", "")
    must_include = g.get("must_include", [])
    never_include = g.get("never_include", [])
    banned_phrases = g.get("banned_phrases", [])
    banned_chars = g.get("banned_characters", [])
    facts = g.get("product_facts", g.get("digitillis_facts", []))
    subject_rules = g.get("subject_line_rules", "")
    signature = sender.get("signature", "")

    parts = [
        f"You are writing cold outreach emails on behalf of {sender.get('name', 'the sender')}, "
        f"{sender.get('title', '')}{'of ' if sender.get('title') else ''}{sender.get('company', 'the company')}.",
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
        "- NEVER use unexplained acronyms. Write the full term first, then the acronym in parentheses on first use. Example: 'Overall Equipment Effectiveness (OEE)', not 'OEE'. Exceptions (no expansion needed): AI, CNC, ERP, ROI, KPI, CEO, CFO, VP.",
        "- NEVER fabricate client engagements, named deployments, or specific measured results from prior projects. Do not write 'we worked with [company]', 'one of our clients saw X% improvement', or any claim implying a real past engagement unless explicitly confirmed as real. Use credible industry benchmark ranges instead (e.g. 'plants running similar setups have reduced downtime 20-35%').",
        "- Write in natural spoken English. If it sounds like AI wrote it, rewrite it.",
        "- Use contractions naturally. Vary sentence length.",
        *[f"- NEVER use the phrase: '{bp}'" for bp in banned_phrases[:10]],  # Top 10 to save tokens
        *[f"- NEVER use this character: {bc}" for bc in banned_chars],
        "",
        "WHAT TO NEVER INCLUDE:",
        *[f"- {item}" for item in never_include],
        "",
        "## INTEGRITY CONSTRAINT (HARD RULE — NOT A PREFERENCE)",
        g.get("integrity_rules", (
            "NEVER fabricate client names, case studies, specific ROI numbers, or past deployments. "
            "Do not claim 'we worked with [Company]' or 'a client reduced downtime by X%' unless "
            "that is a published, verifiable industry benchmark. "
            "Industry trends, trade association statistics, regulatory data, and conservative "
            "approximations framed as estimates are acceptable. "
            "If the sender could not defend the claim in a meeting with the prospect, remove it."
        )),
        "",
        "SUBJECT LINE RULES:",
        subject_rules,
        "",
        "PRODUCT FACTS (use selectively, not as a list):",
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
        "GREETING & SIGNATURE (mandatory on every email):",
        "- The email body MUST start with: Hi [first_name],",
        "- The email body MUST end with the exact signature block below — no paraphrasing.",
        "SIGNATURE BLOCK (copy exactly):",
        signature,
    ]

    # Inject offer context if available
    if offer:
        core_vp = (offer.get("core_value_prop") or "").strip()
        capabilities = offer.get("capabilities") or []
        proof_points = offer.get("proof_points") or []
        pilot = offer.get("pilot_offer") or {}
        diff = offer.get("differentiation") or {}

        parts += [
            "",
            "## PRODUCT VALUE (use selectively — 1-2 facts max per email)",
            "",
            f"Core value proposition: {core_vp}",
            "",
            "Key capabilities (pick 1 that's most relevant to this prospect's pain):",
            *[f"- {c}" for c in capabilities],
            "",
            "Proof points (use at most ONE — make it relevant to their industry/size):",
            *[f"- {p}" for p in proof_points],
            "",
            "Pilot offer (use as CTA for step 1):",
            f"- {pilot.get('description', '')}",
            "",
            "Differentiation (use only if prospect is solution_aware and has seen competitors):",
            *[f"- {v}" for v in diff.values() if v],
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

⚠️ HOOK USAGE MANDATE — READ BEFORE WRITING:
The PERSONALIZATION HOOKS above are your most valuable asset. They are specific,
verified facts about this company that no generic email could contain.

For Step 1 (initial outreach), you MUST:
1. Select the single strongest hook — the one most likely to make this specific
   person stop scrolling. Prefer: known tech stack facts, confirmed pain signals,
   specific equipment types, or recent company news over generic sub-sector trends.
2. Open the email body with that hook as the FIRST sentence. Not as background.
   Not buried in paragraph two. The hook IS the opener.
3. The hook should read like an observation, not a compliment:
   ✓ "MEC runs Plex — most plants on Plex still track maintenance in spreadsheets."
   ✓ "Vaupell's shift to aerospace composites means your failure modes just got more expensive to ignore."
   ✗ "I noticed you work in the manufacturing space..."
   ✗ "As a leader in your industry..."
4. If no hooks are available (list is empty), fall back to the most specific fact
   from RESEARCH INTELLIGENCE. Never open with a generic sub-sector trend.

TECHNOLOGY STACK:
{technology_stack}

PAIN SIGNALS:
{pain_signals}

COMPANY SIGNALS (FDA recalls, OSHA citations, MEP grants — use as personalization hooks if relevant):
{company_signals}

MANUFACTURING PROFILE:
{manufacturing_profile}

EXISTING SOLUTIONS (competitors already in use):
{existing_solutions}

VALUE MESSAGING FOR THIS SUB-SECTOR:
{value_messaging}

PROSPECT AWARENESS LEVEL: {awareness_level}
  - unaware: Start with the problem, not the solution. Don't mention "AI platform" in your opener.
    Lead with a pain/challenge observation specific to their operation.
  - problem_aware: Acknowledge they know the problem. Position the platform as the answer.
    You can reference "predictive maintenance" or "manufacturing intelligence" early.
  - solution_aware: They've seen pitches before. Differentiate immediately — skip generic AI claims,
    go straight to what makes the platform different (speed to value, existing integration path,
    specific sub-sector benchmarks, or a competitor gap they have).

SEQUENCE: {sequence_name}, Step {sequence_step}
CHANNEL: {channel}
{reply_context_block}
STEP INSTRUCTIONS:
{step_instructions}

GLOBAL ANTI-PATTERNS:
{anti_patterns}

## HORMOZI QUALITY CHECK (run this before returning JSON)

Before returning the JSON, silently check your draft against these three questions:
1. Does the email reference a specific, believable outcome for THIS company?
   (Not "reduce downtime" — something like "based on their Plex ERP setup, the
   likely first win is work order prediction, not sensors")
2. Is there at least one concrete proof point? (a number, a timeline, a specific outcome)
3. Is the CTA low-friction? (a question or an offer — not "schedule a demo")

If any check fails, rewrite that sentence before returning.

## FORBIDDEN PHRASES (rewrite any of these if they appear)

Never use:
- "many manufacturers" → name the specific type instead
- "companies like yours" → say "plants with [their specific setup]"
- "significant downtime" → use a number or "unplanned stops on [their equipment type]"
- "improve your operations" → name the specific operation
- "cutting-edge AI" / "industry-leading" / "state-of-the-art" → delete entirely
- "we help companies" → show, don't tell
- "reach out to learn more" → make a specific offer instead
- "would love to connect" → say what specifically you want to discuss
- "leverage" / "synergy" / "game-changing" → delete entirely

OUTPUT FORMAT (JSON):
{{
    "subject": "Short, specific subject line referencing their company or situation (under 50 chars, no generic subjects)",
    "body": "The email body. MUST start with 'Hi [first_name],' (use actual first name). {max_words} words max. MUST end with the exact signature block from the system prompt.",
    "personalization_notes": "Which specific research facts you used and why you chose this angle for this prospect",
    "hormozi_check": {{
        "specific_outcome": true,
        "proof_point_present": true,
        "low_friction_cta": true
    }}
}}

Output ONLY valid JSON. No markdown, no explanation."""


class OutreachAgent(BaseAgent):
    """Generate personalized outreach messages using Claude."""

    agent_name = "outreach"

    def run(
        self,
        company_ids: list[str] | None = None,
        sequence_name: str = "email_value_first",
        sequence_step: int = 1,
        limit: int = 20,
        multi_thread: bool = True,
        max_contacts_per_company: int = 2,
        tiers: list[str] | None = None,
        reply_context: str | None = None,
    ) -> AgentResult:
        """Generate outreach drafts for qualified companies.

        Args:
            company_ids: Specific company IDs (overrides query).
            sequence_name: Which sequence to use.
            reply_context: Optional reply text from prospect to inject into prompt.
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
            companies = self.db.get_companies(status="qualified", tiers=tiers, limit=limit)

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

                # ICP exclusion check — skip companies explicitly excluded from pipeline
                from backend.app.core.icp_manager import ICPManager
                _icp_excluded, _icp_reason = ICPManager(self.db).is_company_excluded(company_id)
                if _icp_excluded:
                    console.print(
                        f"  [dim]{company_name}: ICP excluded ({_icp_reason}). Skipping.[/dim]"
                    )
                    result.skipped += 1
                    result.add_detail(company_name, "icp_excluded", _icp_reason or "")
                    continue

                # Company-level send lock — prevent multi-contact collision
                from backend.app.core.channel_coordinator import is_company_locked, has_recent_activity
                locked, lock_reason = is_company_locked(self.db, company_id)
                if locked:
                    console.print(f"  [dim]{company_name}: company locked — {lock_reason}[/dim]")
                    result.skipped += 1
                    continue

                # Threading state gate — check before any contact work
                from backend.app.core.threading_coordinator import ThreadingCoordinator
                _tc = ThreadingCoordinator(self.db)
                _tc_ok, _tc_reason = _tc.can_send_contact_1(company)
                if not _tc_ok:
                    console.print(f"  [dim]{company_name}: threading gate — {_tc_reason}[/dim]")
                    result.skipped += 1
                    continue

                # Select contacts from hard SQL gate (outbound_eligible_contacts)
                contacts = self.db.get_outbound_eligible_contacts_for_company(company_id)

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
                for _contact_idx, contact in enumerate(valid_contacts):
                    # Threading gate for second contact.
                    # F&B simultaneous mode (workspace.settings.fb_simultaneous_outreach=true):
                    # bypasses the 5-business-day sequential wait so C1+C3 go out same week.
                    # Sequential mode (default): enforces MIN_DAYS_BETWEEN_CONTACTS.
                    if _contact_idx > 0:
                        ws_settings = getattr(self.db, "_workspace_settings", None) or {}
                        fb_simultaneous = str(
                            ws_settings.get("fb_simultaneous_outreach", "false")
                        ).lower() == "true"
                        tier = company.get("tier") or ""
                        use_simultaneous = fb_simultaneous and tier.startswith("fb")

                        if use_simultaneous:
                            _tc2_ok, _tc2_reason = _tc.can_send_contact_2_fb_simultaneous(company)
                        else:
                            _tc2_ok, _tc2_reason = _tc.can_send_contact_2(company)

                        if not _tc2_ok:
                            console.print(f"  [dim]{company_name}: contact 2 threading gate — {_tc2_reason}[/dim]")
                            continue

                    # Hard gate: DB-level eligibility flag (set at import by contact_filter)
                    # This catches contacts that slipped through before the filter existed.
                    if contact.get("is_outreach_eligible") is False:
                        console.print(
                            f"  [dim]{company_name}: {contact.get('full_name', '?')} — "
                            f"is_outreach_eligible=False (tier={contact.get('contact_tier','?')}). Skipping.[/dim]"
                        )
                        continue

                    # Email-name consistency gate: block if email was flagged as belonging
                    # to a different person (email_name_verified=False from import check)
                    if contact.get("email_name_verified") is False:
                        console.print(
                            f"  [dim]{company_name}: {contact.get('full_name', '?')} — "
                            f"email_name_verified=False. Email may belong to different person. Skipping.[/dim]"
                        )
                        continue

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

                    # Pre-send invariant library — hard block before any draft generation
                    from backend.app.core.pre_send_assertions import (
                        run_pre_send_assertions, AssertionFailure,
                    )
                    _guidelines = get_outreach_guidelines()
                    _sender_email = _guidelines.get("sender", {}).get("email", "")
                    try:
                        run_pre_send_assertions(
                            self.db, contact, company, _sender_email,
                            daily_cap=getattr(settings, "daily_send_limit", 125),
                        )
                    except AssertionFailure as _af:
                        console.print(
                            f"  [red]{company_name}: {contact.get('full_name', '?')} — "
                            f"assertion failed: {_af.assertion} ({_af.detail}). Skipping.[/red]"
                        )
                        result.skipped += 1
                        result.add_detail(company_name, "assertion_failed", str(_af))
                        continue

                    # Build value messaging for this tier
                    tier = company.get("tier", "2")
                    value_msg = ontology.get("value_messaging", {}).get(tier, {})

                    # Resolve channel from step or sequence level
                    resolved_channel = step_config.get("channel") or sequence.get("channel", "email")

                    # Build the prompt
                    prompt = self._build_prompt(
                        company=company,
                        contact=contact,
                        research=research,
                        step_config=step_config,
                        sequence_name=sequence_name,
                        value_messaging=value_msg,
                        global_principles=seq_config.get("global_principles", {}),
                        channel=resolved_channel,
                        reply_context=reply_context,
                    )

                    # Call Claude
                    console.print(f"  [dim]{company_name} → {contact.get('full_name', 'Unknown')}...[/dim]")

                    response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=1000,
                        system=_build_system_prompt(),
                        messages=[{"role": "user", "content": prompt}],
                    )

                    # Track cost
                    usage = response.usage
                    self.track_cost(
                        provider="anthropic",
                        model="claude-sonnet-4-6",
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

                    # Create outreach draft — strip em dashes from all text fields
                    _clean = lambda s: (s or "").replace("—", " - ")
                    draft_data = {
                        "company_id": company_id,
                        "contact_id": contact["id"],
                        "channel": resolved_channel,
                        "sequence_name": sequence_name,
                        "sequence_step": sequence_step,
                        "subject": _clean(parsed.get("subject", "")),
                        "body": _clean(parsed.get("body", "")),
                        "personalization_notes": _clean(parsed.get("personalization_notes", "")),
                        "approval_status": "pending",
                    }

                    inserted_draft = self.db.insert_outreach_draft(draft_data)

                    # Threading state update — mark contact queued/sent
                    try:
                        if _contact_idx == 0:
                            _tc.record_contact_1_sent(
                                company_id, contact["id"],
                                pqs=company.get("priority_score"),
                            )
                        else:
                            _tc.record_contact_2_sent(company_id, contact["id"])
                    except Exception as _tc_err:
                        logger.warning("Threading record failed for %s: %s", company_name, _tc_err)

                    # Outcome record — populate static send-time context now.
                    # Reply classification, meeting, and deal data fill in later.
                    try:
                        _draft_id = (inserted_draft or {}).get("id") if isinstance(inserted_draft, dict) else None
                        _active_icp = None
                        try:
                            _icp_row = (
                                self.db.client.table("icp_definitions")
                                .select("id")
                                .eq("is_active", True)
                                .limit(1)
                                .execute()
                                .data or []
                            )
                            _active_icp = _icp_row[0]["id"] if _icp_row else None
                        except Exception:
                            pass
                        self.db.client.table("outreach_outcomes").insert({
                            "send_id":        _draft_id,
                            "contact_id":     contact["id"],
                            "company_id":     company_id,
                            "workspace_id":   getattr(self.db, "workspace_id", None),
                            "icp_version_id": _active_icp,
                            "persona":        contact.get("contact_tier"),
                            "sequence_step":  sequence_step,
                            "pqs_at_send":    company.get("priority_score"),
                            "ccs_at_send":    contact.get("ccs_score"),
                            "sender_email":   _sender_email,
                        }).execute()
                    except Exception as _oe:
                        logger.warning("Could not create outreach_outcome record: %s", _oe)

                    # A/B variant tracking — stable assignment by contact ID hash
                    try:
                        from backend.app.analytics.ab_tracker import ABTracker
                        _cid = contact["id"].replace("-", "")
                        ab_variant = "a" if int(_cid, 16) % 2 == 0 else "b"
                        ABTracker(self.db).record_send(
                            contact_id=contact["id"],
                            variant=ab_variant,
                            subject_line=parsed.get("subject", ""),
                            sequence_id=f"{sequence_name}_step_{sequence_step}",
                        )
                    except Exception:
                        pass  # A/B tracking is non-blocking

                    console.print(
                        f"  [green]{company_name} → {contact.get('full_name', 'Unknown')}: Draft created. "
                        f"Subject: \"{parsed.get('subject', '')[:50]}\"[/green]"
                    )

                    result.processed += 1
                    result.add_detail(
                        company_name,
                        "draft_created",
                        f"Contact: {contact.get('full_name')}, Channel: {step_config.get('channel', 'email')}",
                    )

                # Update company status (once per company, after all contacts processed)
                self.db.update_company(company_id, {"status": "outreach_pending"})

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Claude response for {company_name}: {e}")
                result.errors += 1
                result.add_detail(company_name, "error", f"JSON parse error: {str(e)[:100]}")
                if self._monitor:
                    self._monitor.log_error(str(e), company_id=company_id, error_type="parse_error", exc=e)
            except Exception as e:
                logger.error(f"Error generating outreach for {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])
                if self._monitor:
                    self._monitor.log_error(str(e), company_id=company_id, error_type="outreach_error", exc=e)

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

        # Filter wrong personas — return empty list if nobody qualifies.
        # Never fall back to wrong-persona contacts; callers will skip the company.
        eligible = [c for c in contacts if not _is_wrong_persona(c)]
        if not eligible:
            return []
        contacts = eligible

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

        # Filter contacts with email addresses, excluding wrong personas.
        # Do NOT fall back to wrong-persona contacts — return None so callers skip.
        emailable = [
            c for c in contacts
            if c.get("email") and not _is_wrong_persona(c)
        ]
        if not emailable:
            return None

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
        channel: str = "email",
        reply_context: str | None = None,
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

        # Awareness level — from research or company record
        awareness_level = company.get("awareness_level", "") or "unaware"

        # Merge in research intelligence (often richer than company record)
        if research:
            ri = research.get("research_intelligence", {}) or {}
            existing = research.get("existing_solutions", []) or ri.get("existing_solutions", []) or []
            if not awareness_level or awareness_level == "unaware":
                awareness_level = research.get("awareness_level", "") or ri.get("awareness_level", "") or "unaware"
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

        # Fetch company signals (FDA recalls, OSHA, MEP grants) for personalization
        try:
            _sig_rows = (
                self.db.client.table("company_signals")
                .select("signal_type,signal_text,observed_at")
                .eq("company_id", company["id"])
                .order("observed_at", desc=True)
                .limit(5)
                .execute()
                .data or []
            )
            company_signals_text = (
                "\n".join(f"- [{s['signal_type']}] {s.get('signal_text', '')}" for s in _sig_rows)
                if _sig_rows else "None available"
            )
        except Exception:
            company_signals_text = "None available"

        # Build reply context block if a prospect reply was logged
        if reply_context:
            reply_context_block = (
                "\n⚠️  PROSPECT REPLIED — THIS IS A REPLY-AWARE FOLLOW-UP:\n"
                f"{reply_context}\n"
                "Your email MUST directly address what they said. Do not re-introduce Digitillis "
                "as if they haven't heard of it. Respond to their specific point first, then "
                "advance the conversation naturally.\n"
            )
        else:
            reply_context_block = ""

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
            company_signals=company_signals_text,
            manufacturing_profile=json.dumps(mfg_profile, indent=2) if mfg_profile else "Not profiled",
            existing_solutions=", ".join(existing) if existing else "None identified",
            value_messaging=value_text or "No tier-specific messaging available",
            awareness_level=awareness_level or "unaware",
            sequence_name=sequence_name,
            sequence_step=step_config["step"],
            channel=channel,
            reply_context_block=reply_context_block,
            step_instructions=step_text,
            anti_patterns=anti_text,
            max_words=max_words,
        )
