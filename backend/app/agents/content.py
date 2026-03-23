"""Content Agent — LinkedIn thought leadership post generation.

Uses Claude to generate McKinsey-grade LinkedIn posts for the founder.
Zero product pitching. Data-driven. Pure credibility building.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, load_yaml_config

console = Console()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Content calendar — 4-week rotating schedule
# ---------------------------------------------------------------------------

CONTENT_CALENDAR: list[dict[str, Any]] = [
    # Week 1
    {"week": 1, "day": "Tuesday",  "format": "contrarian",   "pillar": "manufacturing_intelligence", "topic": "Why 85% of predictive maintenance pilots fail to scale"},
    {"week": 1, "day": "Thursday", "format": "framework",    "pillar": "manufacturing_strategy",     "topic": "The capital allocation framework for manufacturing technology"},
    {"week": 1, "day": "Saturday", "format": "data_insight", "pillar": "food_safety_compliance",     "topic": "FDA 483 patterns: what actually triggers citations"},
    # Week 2
    {"week": 2, "day": "Tuesday",  "format": "framework",    "pillar": "manufacturing_intelligence", "topic": "The maintenance maturity spectrum: where most plants actually sit"},
    {"week": 2, "day": "Thursday", "format": "contrarian",   "pillar": "manufacturing_operations",   "topic": "Quality-first vs. throughput-first"},
    {"week": 2, "day": "Saturday", "format": "data_insight", "pillar": "food_safety_compliance",     "topic": "FSMA compliance costs by food category"},
    # Week 3
    {"week": 3, "day": "Tuesday",  "format": "data_insight", "pillar": "manufacturing_intelligence", "topic": "OEE benchmarks by sub-sector: what good looks like"},
    {"week": 3, "day": "Thursday", "format": "framework",    "pillar": "manufacturing_strategy",     "topic": "How to run a 90-day technology pilot that produces a decision"},
    {"week": 3, "day": "Saturday", "format": "contrarian",   "pillar": "food_safety_compliance",     "topic": "Your HACCP plan is a compliance artifact, not a safety tool"},
    # Week 4
    {"week": 4, "day": "Tuesday",  "format": "data_insight", "pillar": "manufacturing_intelligence", "topic": "The real cost of one unplanned stop"},
    {"week": 4, "day": "Thursday", "format": "contrarian",   "pillar": "manufacturing_operations",   "topic": "Why continuous improvement programs plateau after 18 months"},
    {"week": 4, "day": "Saturday", "format": "benchmark",    "pillar": "food_safety_compliance",     "topic": "We analyzed 200+ FDA warning letters: here is what we found"},
]

# Default guidelines used if content_guidelines.yaml doesn't exist
_DEFAULT_GUIDELINES: dict[str, Any] = {
    "author": {
        "name": "Avanish Mehrotra",
        "background": "Manufacturing operations and food safety expert, founder building in this space",
    },
    "voice_and_tone": (
        "Write as a McKinsey partner sharing insight with industry peers. "
        "Authoritative but never condescending. Data-first. Occasionally contrarian. "
        "Never promotional. Never mention any product, company, or AI platform."
    ),
    "quality_standards": [
        "Lead with a specific data point, statistic, or bold claim",
        "Every number must be realistic and sourceable",
        "Provide genuine value the reader can use today",
        "End with a question that invites comments",
        "Mobile-first: short paragraphs, blank lines between thoughts",
        "Under 1300 characters (LinkedIn truncates beyond this)",
    ],
    "banned_phrases": [
        "I'm excited to share",
        "game-changer",
        "revolutionary",
        "leverage",
        "synergy",
        "paradigm shift",
        "deep dive",
        "touch base",
        "at the end of the day",
        "moreover",
        "furthermore",
        "in conclusion",
        "it's worth noting",
        "I'm thrilled",
        "incredibly",
    ],
    "never_include": [
        "Any mention of Digitillis or any AI/software product",
        "Hashtags (they reduce LinkedIn organic reach in 2026)",
        "Em dashes or en dashes — use commas, periods, or 'and' instead",
        "Stock phrases that sound AI-generated",
        "Generic advice without specific numbers",
        "Calls to action to visit a website or book a demo",
    ],
}

# Format-specific character limits and instructions
_FORMAT_SPECS: dict[str, dict[str, Any]] = {
    "data_insight": {
        "char_limit": 1200,
        "instructions": (
            "Structure: Hook stat (one line) → blank line → Context (2-3 lines) → blank line → "
            "'So what?' insight (2-3 bullet points or short paras) → blank line → Question. "
            "800-1300 characters. The hook must be a specific number, percentage, or dollar figure."
        ),
    },
    "framework": {
        "char_limit": 1400,
        "instructions": (
            "Structure: Name the framework or model (first line, give it a memorable title) → blank line → "
            "Describe 3-4 quadrants, levels, or categories with brief explanations → blank line → "
            "Where most companies sit → blank line → 'Where do you fall?' question. "
            "1000-1500 characters. Use simple ASCII art for a matrix if it fits cleanly."
        ),
    },
    "contrarian": {
        "char_limit": 900,
        "instructions": (
            "Structure: State the conventional wisdom in one line (label it 'The common belief:' or 'Unpopular opinion:') → "
            "blank line → Why it's wrong (specific evidence, 2-3 points) → blank line → "
            "The better frame → blank line → 'Agree or disagree?' or similar. "
            "600-1000 characters. Short, punchy. No hedging."
        ),
    },
    "benchmark": {
        "char_limit": 1400,
        "instructions": (
            "Structure: 'We analyzed X...' opener → blank line → 3-5 numbered key findings → "
            "blank line → The surprising/counterintuitive finding → blank line → "
            "Implications for mid-market manufacturers → blank line → Question. "
            "1200-1500 characters. Lead finding must be surprising or counterintuitive."
        ),
    },
}

_PILLAR_CONTEXT: dict[str, str] = {
    "manufacturing_intelligence": (
        "Target reader: VP Operations, VP Engineering, Plant Manager, COO at discrete manufacturers. "
        "Data sources to reference: Plant Engineering annual surveys, ARC Advisory Group research, "
        "McKinsey manufacturing operations reports, SMRP benchmarking data, Deloitte manufacturing competitiveness studies."
    ),
    "manufacturing_strategy": (
        "Target reader: COO, VP Operations, Plant Manager, Manufacturing VP, Board members. "
        "Data sources to reference: Deloitte Global Manufacturing Competitiveness Index, "
        "NAM/Manufacturers Alliance surveys, Industry Week CEO surveys, Gartner MES/MOM market analysis."
    ),
    "manufacturing_operations": (
        "Target reader: VP Operations, Reliability Manager, Continuous Improvement, Quality Director. "
        "Data sources to reference: SMRP Best Practices benchmarks, Reliable Plant survey data, "
        "ASQ quality benchmarks, ISA standards and implementation data, MESA International MES benchmarks."
    ),
    "food_safety_compliance": (
        "Target reader: VP Quality, VP Food Safety, Director QA at food manufacturers. "
        "Data sources to reference: FDA warning letter database and 483 observations, "
        "FSIS enforcement reports, SQF audit statistics, GFSI benchmarking data, CDC foodborne illness surveillance."
    ),
}


def _load_content_guidelines() -> dict[str, Any]:
    """Load content_guidelines.yaml or fall back to hardcoded defaults."""
    try:
        return load_yaml_config("content_guidelines.yaml")
    except FileNotFoundError:
        logger.debug("content_guidelines.yaml not found — using built-in defaults")
        return _DEFAULT_GUIDELINES


def _build_system_prompt(guidelines: dict[str, Any]) -> str:
    """Build the Claude system prompt from guidelines."""
    author = guidelines.get("author", _DEFAULT_GUIDELINES["author"])
    voice = guidelines.get("voice_and_tone", _DEFAULT_GUIDELINES["voice_and_tone"])
    quality = guidelines.get("quality_standards", _DEFAULT_GUIDELINES["quality_standards"])
    banned = guidelines.get("banned_phrases", _DEFAULT_GUIDELINES["banned_phrases"])
    never = guidelines.get("never_include", _DEFAULT_GUIDELINES["never_include"])

    parts = [
        f"You are writing LinkedIn thought leadership posts for {author.get('name', 'Avanish Mehrotra')}.",
        f"Background: {author.get('background', 'Manufacturing operations expert')}",
        "",
        "VOICE AND TONE:",
        voice,
        "",
        "QUALITY STANDARDS (every post must meet all of these):",
        *[f"- {q}" for q in quality],
        "",
        "BANNED PHRASES (never use any of these):",
        *[f"- \"{bp}\"" for bp in banned[:15]],
        "",
        "NEVER INCLUDE:",
        *[f"- {n}" for n in never],
        "",
        "CRITICAL FORMATTING:",
        "- NEVER use em dashes (—) or en dashes (–). Use commas, periods, colons, or rewrite the sentence.",
        "- Use contractions naturally (it's, they're, you've).",
        "- Vary sentence length. Short sentences hit hard.",
        "- Write in natural spoken English. If it reads like a press release, rewrite it.",
        "- Line breaks between every distinct thought. LinkedIn is read on phones.",
        "",
        "OUTPUT: Return ONLY the post text. No preamble, no explanation, no markdown formatting.",
        "Do not wrap the post in quotes or code blocks. Just the raw post text.",
    ]

    return "\n".join(parts)


def _build_user_prompt(
    topic: str,
    pillar: str,
    format_type: str,
    guidelines: dict[str, Any],
    commentary: str | None = None,
) -> str:
    """Build the per-generation user prompt."""
    fmt_spec = _FORMAT_SPECS.get(format_type, _FORMAT_SPECS["data_insight"])
    pillar_ctx = _PILLAR_CONTEXT.get(pillar, _PILLAR_CONTEXT["manufacturing_operations"])

    # Pull any topic-specific context from guidelines if present
    topic_briefs: dict[str, str] = guidelines.get("topic_briefs", {})
    topic_brief = topic_briefs.get(topic, "Use the best publicly available data for this topic.")

    parts = [
        f"Write a LinkedIn thought leadership post about: {topic}",
        "",
        f"FORMAT: {format_type.upper().replace('_', ' ')}",
        f"PILLAR: {pillar.replace('_', ' ').title()}",
        "",
        "FORMAT INSTRUCTIONS:",
        fmt_spec["instructions"],
        f"Maximum {fmt_spec['char_limit']} characters.",
        "",
        "PILLAR CONTEXT (reader profile and data sources):",
        pillar_ctx,
        "",
        "TOPIC CONTEXT:",
        topic_brief,
    ]

    if commentary and commentary.strip():
        parts += [
            "",
            "ADDITIONAL CONTEXT FROM THE AUTHOR:",
            commentary.strip(),
            "",
            "Use this to guide the angle, focus, or tone of the post. The commentary",
            "represents the author's current thinking and priorities.",
        ]

    parts += [
        "",
        "REMINDER: No hashtags. No product mentions. No company names. "
        "End with a question. Under 1300 characters for the final post.",
    ]

    return "\n".join(parts)


class ContentAgent(BaseAgent):
    """Generate LinkedIn thought leadership post drafts using Claude."""

    agent_name = "content"

    def run(
        self,
        topic: str | None = None,
        pillar: str | None = None,
        format_type: str | None = None,
        limit: int = 4,
        commentary: str | None = None,
        **kwargs,
    ) -> AgentResult:
        """Generate LinkedIn post drafts.

        Modes:
        - topic provided: generate a post for that specific topic.
        - pillar + format_type: pick the next matching topic from the calendar.
        - nothing provided: generate the next `limit` posts from the calendar.

        Args:
            topic: Specific topic to generate a post about.
            pillar: Content pillar (food_safety, predictive_maintenance, ops_excellence, leadership).
            format_type: Post format (data_insight, framework, contrarian, benchmark).
            limit: Number of posts to generate when no topic specified.
            commentary: Optional author guidance injected into every Claude prompt.

        Returns:
            AgentResult with generated drafts in result.details.
        """
        result = AgentResult()
        settings = get_settings()

        if not settings.anthropic_api_key:
            console.print("[red]ANTHROPIC_API_KEY not set. Cannot generate content.[/red]")
            result.success = False
            return result

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        guidelines = _load_content_guidelines()
        system_prompt = _build_system_prompt(guidelines)

        # Determine what to generate
        jobs: list[dict[str, str]] = []

        if topic:
            # Single explicit topic
            resolved_pillar = pillar or "ops_excellence"
            resolved_format = format_type or "data_insight"
            jobs.append({"topic": topic, "pillar": resolved_pillar, "format": resolved_format})
        elif pillar and format_type:
            # Find next calendar entry matching pillar + format
            match = next(
                (e for e in CONTENT_CALENDAR if e["pillar"] == pillar and e["format"] == format_type),
                None,
            )
            if match:
                jobs.append({"topic": match["topic"], "pillar": pillar, "format": format_type})
            else:
                console.print(f"[yellow]No calendar entry for pillar={pillar}, format={format_type}[/yellow]")
                result.success = False
                return result
        else:
            # Generate next N posts from calendar
            for entry in CONTENT_CALENDAR[:limit]:
                jobs.append({"topic": entry["topic"], "pillar": entry["pillar"], "format": entry["format"]})

        console.print(f"[cyan]Generating {len(jobs)} content draft(s)...[/cyan]")

        for job in jobs:
            job_topic = job["topic"]
            job_pillar = job["pillar"]
            job_format = job["format"]

            # Dedup check — skip if this topic was posted in the last 60 days
            import hashlib
            topic_hash = hashlib.sha256(job_topic.lower().strip().encode()).hexdigest()
            try:
                existing = self.db.client.table("content_archive").select(
                    "id, posted_at, topic"
                ).eq("topic_hash", topic_hash).order(
                    "posted_at", desc=True
                ).limit(1).execute().data

                if existing:
                    from datetime import datetime, timezone, timedelta
                    posted_at = datetime.fromisoformat(
                        existing[0]["posted_at"].replace("Z", "+00:00")
                    )
                    days_since = (datetime.now(timezone.utc) - posted_at).days
                    if days_since < 60:
                        console.print(
                            f"  [yellow]Skipping '{job_topic[:50]}' — posted {days_since}d ago. "
                            f"Re-post allowed after 60 days.[/yellow]"
                        )
                        result.skipped += 1
                        result.add_detail(job_topic, "dedup_skipped", f"Posted {days_since}d ago")
                        continue
            except Exception:
                pass  # If archive table doesn't exist yet, skip dedup

            try:
                user_prompt = _build_user_prompt(
                    topic=job_topic,
                    pillar=job_pillar,
                    format_type=job_format,
                    guidelines=guidelines,
                    commentary=commentary,
                )

                console.print(f"  [dim]Generating: {job_topic[:60]}...[/dim]")

                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=800,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                # Track cost
                usage = response.usage
                self.track_cost(
                    provider="anthropic",
                    model="claude-sonnet-4-6",
                    endpoint="/messages",
                    company_id=None,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )

                post_text = response.content[0].text.strip()
                char_count = len(post_text)

                # Store draft in outreach_drafts table
                # Using channel="other", sequence_name="thought_leadership" since
                # there is no "content" channel in the DB enum.
                draft_data = {
                    "channel": "other",
                    "sequence_name": "thought_leadership",
                    "sequence_step": 1,
                    "subject": job_topic,
                    "body": post_text,
                    "personalization_notes": f"format:{job_format}|pillar:{job_pillar}",
                    "approval_status": "pending",
                    # content drafts have no company/contact association
                    "company_id": None,
                    "contact_id": None,
                }

                stored: dict[str, Any] = {}
                try:
                    stored = self.db.insert_outreach_draft(draft_data)
                except Exception as db_err:
                    logger.warning(f"Could not store draft in DB: {db_err}")

                draft_id = stored.get("id", "")

                console.print(
                    f"  [green]Draft generated ({char_count} chars): {job_topic[:50]}[/green]"
                )

                result.processed += 1
                result.add_detail(
                    job_topic,
                    "draft_created",
                    f"id={draft_id} chars={char_count} format={job_format} pillar={job_pillar}",
                )

                # Attach generated text to details for API layer to surface
                result.details[-1]["post_text"] = post_text
                result.details[-1]["char_count"] = char_count
                result.details[-1]["format"] = job_format
                result.details[-1]["pillar"] = job_pillar
                result.details[-1]["draft_id"] = draft_id
                result.details[-1]["generated_at"] = datetime.now(timezone.utc).isoformat()

                # ── INTEL EXTRACTION + 3-ROUND VERIFICATION ──
                # Second Claude call: extract sources, references, and verify claims
                try:
                    intel_prompt = (
                        "You are a fact-checking editor for a thought leadership publication.\n\n"
                        f"LINKEDIN POST TO VERIFY:\n{post_text}\n\n"
                        "TASK: Analyze this post and return a structured assessment.\n\n"
                        "ROUND 1 — SOURCE EXTRACTION:\n"
                        "List every factual claim, statistic, or data point in the post.\n"
                        "For each one, provide the most likely credible source (report name, organization, year).\n"
                        "If a claim cannot be sourced, flag it as UNVERIFIABLE.\n\n"
                        "ROUND 2 — AUTHENTICITY CHECK:\n"
                        "For each claim, assess: Is this number realistic? Could it be verified by a reader?\n"
                        "Flag any claim that sounds fabricated, exaggerated, or too precise to be real.\n"
                        "Check for common AI hallucination patterns (overly round numbers, fake study citations).\n\n"
                        "ROUND 3 — CREDIBILITY ASSESSMENT:\n"
                        "Overall credibility score (1-10, where 10 = every claim is verifiable).\n"
                        "Would a McKinsey partner publish this without edits? Yes/No and why.\n"
                        "List any thought leaders, companies, or organizations referenced or relevant.\n\n"
                        "OUTPUT FORMAT:\n"
                        "SOURCES:\n"
                        "- [claim]: [source] (VERIFIED / PLAUSIBLE / UNVERIFIABLE)\n"
                        "...\n\n"
                        "FLAGGED CLAIMS:\n"
                        "- [any claims that seem fabricated or need verification]\n\n"
                        "CREDIBILITY SCORE: X/10\n"
                        "PUBLISH READY: Yes/No\n"
                        "REASON: [brief explanation]\n\n"
                        "REFERENCED ENTITIES:\n"
                        "- Organizations: [list]\n"
                        "- Reports/Studies: [list]\n"
                        "- Thought Leaders: [list if any]\n"
                        "- Regulations/Standards: [list if any]\n\n"
                        "SUGGESTED IMPROVEMENTS:\n"
                        "- [any specific edits to make claims more verifiable]"
                    )

                    intel_response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=1200,
                        system="You are a rigorous fact-checking editor. Flag anything that cannot be independently verified. No leniency.",
                        messages=[{"role": "user", "content": intel_prompt}],
                    )

                    intel_text = intel_response.content[0].text.strip()

                    # Track cost for verification call
                    self.track_cost(
                        provider="anthropic",
                        model="claude-sonnet-4-6",
                        endpoint="/messages",
                        company_id=None,
                        input_tokens=intel_response.usage.input_tokens,
                        output_tokens=intel_response.usage.output_tokens,
                    )

                    # Parse credibility score
                    credibility_score = 0
                    publish_ready = False
                    for line in intel_text.split("\n"):
                        line_stripped = line.strip()
                        if line_stripped.startswith("CREDIBILITY SCORE:"):
                            try:
                                score_part = line_stripped.split(":")[1].strip().split("/")[0].strip()
                                credibility_score = int(score_part)
                            except (ValueError, IndexError):
                                pass
                        if line_stripped.startswith("PUBLISH READY:"):
                            publish_ready = "yes" in line_stripped.lower()

                    # Store intel alongside the draft
                    intel_data = {
                        "intel_report": intel_text,
                        "credibility_score": credibility_score,
                        "publish_ready": publish_ready,
                        "verification_rounds": 3,
                    }

                    # ── QUALITY REPORT — structured self-assessment ──
                    # Third Claude call: comprehensive quality review
                    quality_report: dict[str, Any] = {}
                    try:
                        VERIFICATION_PROMPT = """You are a quality reviewer for LinkedIn thought leadership posts.
Review this post against the following criteria and produce a structured assessment.

POST TO REVIEW:
{post_text}

TOPIC: {topic}
PILLAR: {pillar}

EVALUATE EACH CRITERION:

1. FACT CHECK
- Are all statistics and data points sourceable?
- Are any claims fabricated or unverifiable?
- List all data sources referenced or implied.
Result: PASS or FAIL

2. PUBLICATION STANDARD
- Would a McKinsey Senior Partner share this internally? (yes/no)
- Free of fluff or exaggeration? (yes/no)
- No unsupported claims? (yes/no)
- Worth sharing internally? (yes/no)

3. CONTENT OBJECTIVE FULFILLED
Which of these does the post accomplish (list all that apply):
- Challenge a widely accepted belief
- Reveal a hidden pattern or constraint
- Reframe a known problem with a more useful lens
- Introduce a practical framework or decision model
- Explain the underlying mechanism behind outcomes

4. POSITIONING CHECK
- Systems thinker, not commentator? (yes/no)
- Pattern recognizer, not storyteller? (yes/no)
- Builder, not observer? (yes/no)

5. DIFFERENTIATION
- Could 100 other manufacturing experts write this? (yes/no)
- Contains original insight or reframing? (yes/no)
- What makes this post distinct? (one sentence)

6. CRAFT
- Any banned phrases found? (list or "none")
- Any em dashes? (yes/no)
- Character count acceptable? (yes/no)
- Mobile formatting good? (yes/no)

7. READER VALUE
- Can the reader act or think differently after reading? (yes/no)
- Explains WHY not just WHAT? (yes/no)

8. OVERALL SCORE: X/10
9. VERDICT: "Ready to Publish" or "Needs Revision"
10. FLAGS: Any specific issues to address (or "None")

Respond in this EXACT format (parseable):
FACT_CHECK: PASS|FAIL
FACT_CHECK_SOURCES: source1, source2, ...
FACT_CHECK_NOTE: any note about fact check
PUB_STANDARD_MCKINSEY: YES|NO
PUB_STANDARD_FLUFF: YES|NO
PUB_STANDARD_CLAIMS: YES|NO
PUB_STANDARD_SHAREABLE: YES|NO
OBJECTIVE: objective1, objective2
POSITIONING_THINKER: YES|NO
POSITIONING_PATTERN: YES|NO
POSITIONING_BUILDER: YES|NO
DIFFERENTIATION_100: YES|NO
DIFFERENTIATION_ORIGINAL: YES|NO
DIFFERENTIATION_NOTE: what makes it distinct
CRAFT_BANNED: none|phrase1, phrase2
CRAFT_EMDASH: YES|NO
CRAFT_CHARS: OK|OVER
CRAFT_MOBILE: YES|NO
READER_ACTION: YES|NO
READER_WHY: YES|NO
SCORE: 8
VERDICT: Ready to Publish
FLAGS: None"""

                        quality_prompt = VERIFICATION_PROMPT.format(
                            post_text=post_text,
                            topic=job_topic,
                            pillar=job_pillar,
                        )

                        quality_response = client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=1000,
                            system="You are a rigorous quality reviewer. Evaluate posts honestly against all criteria. Be specific with flags.",
                            messages=[{"role": "user", "content": quality_prompt}],
                        )

                        self.track_cost(
                            provider="anthropic",
                            model="claude-sonnet-4-6",
                            endpoint="/messages",
                            company_id=None,
                            input_tokens=quality_response.usage.input_tokens,
                            output_tokens=quality_response.usage.output_tokens,
                        )

                        quality_text = quality_response.content[0].text.strip()

                        # Parse the structured response into a dict
                        def _parse_quality_line(text: str, key: str) -> str:
                            for line in text.split("\n"):
                                stripped = line.strip()
                                if stripped.startswith(f"{key}:"):
                                    return stripped[len(f"{key}:"):].strip()
                            return ""

                        def _yes(val: str) -> bool:
                            return val.strip().upper() in ("YES", "Y", "TRUE")

                        qr_score_raw = _parse_quality_line(quality_text, "SCORE")
                        try:
                            qr_score = int(qr_score_raw.split("/")[0].strip())
                        except (ValueError, IndexError):
                            qr_score = 0

                        qr_verdict = _parse_quality_line(quality_text, "VERDICT") or "Needs Revision"

                        qr_fact_check = _parse_quality_line(quality_text, "FACT_CHECK")
                        qr_fc_sources_raw = _parse_quality_line(quality_text, "FACT_CHECK_SOURCES")
                        qr_fc_sources = [s.strip() for s in qr_fc_sources_raw.split(",") if s.strip() and s.strip().lower() != "none"]
                        qr_fc_note = _parse_quality_line(quality_text, "FACT_CHECK_NOTE")

                        qr_objectives_raw = _parse_quality_line(quality_text, "OBJECTIVE")
                        qr_objectives = [o.strip() for o in qr_objectives_raw.split(",") if o.strip()]

                        qr_banned_raw = _parse_quality_line(quality_text, "CRAFT_BANNED")
                        if qr_banned_raw.lower() in ("none", "none found", ""):
                            qr_banned: list[str] = []
                        else:
                            qr_banned = [p.strip() for p in qr_banned_raw.split(",") if p.strip()]

                        qr_flags_raw = _parse_quality_line(quality_text, "FLAGS")
                        if qr_flags_raw.lower() in ("none", "none found", ""):
                            qr_flags: list[str] = []
                        else:
                            qr_flags = [f.strip() for f in qr_flags_raw.split(",") if f.strip()]

                        quality_report = {
                            "score": qr_score,
                            "verdict": qr_verdict,
                            "fact_check": {
                                "result": qr_fact_check.upper() if qr_fact_check else "FAIL",
                                "sources": qr_fc_sources,
                                "note": qr_fc_note,
                            },
                            "publication_standard": {
                                "mckinsey_share": _yes(_parse_quality_line(quality_text, "PUB_STANDARD_MCKINSEY")),
                                "fluff_free": _yes(_parse_quality_line(quality_text, "PUB_STANDARD_FLUFF")),
                                "claims_supported": _yes(_parse_quality_line(quality_text, "PUB_STANDARD_CLAIMS")),
                                "worth_sharing": _yes(_parse_quality_line(quality_text, "PUB_STANDARD_SHAREABLE")),
                            },
                            "content_objective": qr_objectives,
                            "positioning": {
                                "systems_thinker": _yes(_parse_quality_line(quality_text, "POSITIONING_THINKER")),
                                "pattern_recognizer": _yes(_parse_quality_line(quality_text, "POSITIONING_PATTERN")),
                                "builder": _yes(_parse_quality_line(quality_text, "POSITIONING_BUILDER")),
                            },
                            "differentiation": {
                                "could_100_write": _yes(_parse_quality_line(quality_text, "DIFFERENTIATION_100")),
                                "original_insight": _yes(_parse_quality_line(quality_text, "DIFFERENTIATION_ORIGINAL")),
                                "note": _parse_quality_line(quality_text, "DIFFERENTIATION_NOTE"),
                            },
                            "craft": {
                                "banned_phrases": qr_banned,
                                "em_dashes": _yes(_parse_quality_line(quality_text, "CRAFT_EMDASH")),
                                "char_count_ok": _parse_quality_line(quality_text, "CRAFT_CHARS").upper() != "OVER",
                                "mobile_format": _yes(_parse_quality_line(quality_text, "CRAFT_MOBILE")),
                            },
                            "reader_value": {
                                "actionable": _yes(_parse_quality_line(quality_text, "READER_ACTION")),
                                "explains_why": _yes(_parse_quality_line(quality_text, "READER_WHY")),
                            },
                            "flags": qr_flags,
                        }

                        console.print(
                            f"  Quality Report: {qr_verdict} — {qr_score}/10"
                        )

                    except Exception as qr_err:
                        logger.warning(f"Quality report generation failed for '{job_topic}': {qr_err}")
                        quality_report = {}

                    # Update the draft's personalization_notes to include intel + quality report
                    import json as _json
                    updated_notes = (
                        f"format:{job_format}|pillar:{job_pillar}"
                        f"|credibility:{credibility_score}/10"
                        f"|publish_ready:{publish_ready}"
                    )
                    # Store the full intel report so it survives page reload
                    updated_notes += f"|intel_report::{intel_text}"
                    if quality_report:
                        updated_notes += f"|quality_report::{_json.dumps(quality_report, separators=(',', ':'))}"

                    if draft_id:
                        try:
                            self.db.update_outreach_draft(draft_id, {
                                "personalization_notes": updated_notes,
                            })
                        except Exception:
                            pass

                    result.details[-1]["intel"] = intel_data
                    result.details[-1]["credibility_score"] = credibility_score
                    result.details[-1]["publish_ready"] = publish_ready
                    result.details[-1]["quality_report"] = quality_report

                    # Log verification result
                    status_icon = "[green]PASS[/green]" if publish_ready else "[yellow]REVIEW[/yellow]"
                    console.print(
                        f"  Verification: {status_icon} — Credibility {credibility_score}/10"
                    )

                    # If credibility is below 6, flag it prominently
                    if credibility_score < 6:
                        console.print(
                            f"  [red]WARNING: Low credibility score ({credibility_score}/10). "
                            f"Review intel report before posting.[/red]"
                        )

                except Exception as intel_err:
                    logger.warning(f"Intel verification failed for '{job_topic}': {intel_err}")
                    result.details[-1]["intel"] = {"error": str(intel_err)}

            except Exception as e:
                logger.error(f"Error generating content for '{job_topic}': {e}", exc_info=True)
                result.errors += 1
                result.add_detail(job_topic, "error", str(e)[:200])

        return result
