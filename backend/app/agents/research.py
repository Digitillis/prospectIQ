"""Research Agent — Deep company research.

Single Claude call per company that combines research + structured extraction.
Populates research_intelligence and updates company fields.
"""

from __future__ import annotations

import json
import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_scoring_config
from backend.app.core.models import ResearchResult

console = Console()
logger = logging.getLogger(__name__)

# Sonnet for high-PQS, Haiku for low-PQS firmographic match.
# Threshold is firmographic-only PQS (the cheap dimension). Companies whose
# firmographic match alone is strong get the full research treatment.
RESEARCH_PQS_PROMOTE_THRESHOLD = 6
SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _select_research_model(company: dict) -> tuple[str, str]:
    """Return (model_id, prompt_variant) based on firmographic score.

    Low-PQS companies get Haiku with a slim extraction prompt to save cost.
    High-PQS companies get Sonnet with the full intelligence prompt.
    """
    pqs_firmographic = (
        company.get("pqs_firmographic")
        or company.get("pqs_firm")
        or 0
    )
    try:
        pqs_firmographic = int(pqs_firmographic)
    except (TypeError, ValueError):
        pqs_firmographic = 0

    if pqs_firmographic >= RESEARCH_PQS_PROMOTE_THRESHOLD:
        return SONNET_MODEL, "full"
    return HAIKU_MODEL, "slim"


# Slim Haiku prompt — just enough fields to decide whether to promote
SLIM_RESEARCH_SYSTEM = """You are a manufacturing analyst doing a quick triage scan.
Return ONLY valid JSON. No markdown, no explanation."""

SLIM_RESEARCH_USER = """Quickly scan this manufacturing company and decide whether it
merits deep research for B2B AI manufacturing intelligence sales.

COMPANY: {company_name}
INDUSTRY: {industry}
LOCATION: {city}, {state}, {country}
WEBSITE: {website}
EMPLOYEE COUNT: {employee_count}

Output ONLY this JSON:
{{
    "manufacturing_type": "discrete" | "process" | "hybrid" | "food" | "unknown",
    "equipment_types": ["list", "of", "equipment", "types"],
    "employee_estimate": <integer or null>,
    "is_real_manufacturer": true | false,
    "confidence_level": "high" | "medium" | "low",
    "promote_to_full_research": true | false
}}

Rules:
- promote_to_full_research=true ONLY if this looks like a genuine ICP fit
  (real manufacturer with operations complex enough to need predictive maintenance
   or AI-driven plant intelligence). Default to false when in doubt.
- Output ONLY valid JSON. No markdown, no preamble."""

# Combined research + extraction system prompt
RESEARCH_SYSTEM = """You are a senior manufacturing industry analyst conducting deep research on
companies for B2B sales intelligence and prospecting.

Your job is to analyze manufacturing companies and extract structured intelligence for sales
prospecting. You must combine your knowledge of the company with structured extraction into
a single JSON output.

Research methodology:
1. Recall everything you know about the company — products, processes, facilities, leadership
2. Consider their technology landscape — ERP, CMMS, SCADA/MES, PLCs, AI/ML platforms
3. Assess their operational maturity — IoT adoption, maintenance approach, digital transformation
4. Identify pain points, challenges, and opportunities relevant to AI-powered manufacturing intelligence
5. Find personalization hooks — specific facts useful for sales outreach

Be accurate and evidence-based. If you are not confident about specific information, say so.
Do not fabricate data — use "Not found" or appropriate defaults when uncertain."""

RESEARCH_USER = """Research this manufacturing company and extract structured intelligence.

COMPANY: {company_name}
INDUSTRY: {industry}
LOCATION: {city}, {state}, {country}
WEBSITE: {website}
LINKEDIN: {linkedin_url}
EMPLOYEE COUNT: {employee_count}
REVENUE ESTIMATE: {revenue}

TECHNOLOGY SYSTEMS TO LOOK FOR:
- ERP: SAP, Oracle, Epicor, Infor, Microsoft Dynamics, SYSPRO, Plex, QAD
- CMMS/APM: IBM Maximo, SAP PM, UpKeep, Fiix, eMaint, Limble, MaintainX
- SCADA/MES: Rockwell FactoryTalk, Siemens WinCC/Opcenter, GE Proficy, Honeywell, OSIsoft PI, Ignition, Wonderware/AVEVA
- PLCs: Allen-Bradley, Siemens S7, Mitsubishi, Fanuc, Omron, Beckhoff
- AI/ML Competitors: Uptake, SparkCognition, C3.ai, Sight Machine, MachineMetrics, Falkonry, Augury, Senseye

RESEARCH QUESTIONS TO ANSWER:
1. What does this company manufacture? Main products, processes, equipment?
2. What technology systems do they use?
3. What is their IoT/sensor/Industry 4.0 maturity level?
4. What is their current maintenance approach? (reactive, time-based, condition-based, predictive?)
5. Any notable recent events? (plant expansions, acquisitions, leadership changes, equipment investments)
6. Any sustainability/ESG initiatives?
7. Any digital transformation or Industry 4.0 initiatives?
8. Are they using any AI/ML platforms for manufacturing?
9. What operational challenges or pain points are likely? (quality, workforce, downtime, supply chain)
10. What specific opportunities exist for an AI manufacturing intelligence platform?

TRIGGER EVENT DETECTION (critical — affects outreach timing and messaging):
Look specifically for each of the following in the LAST 12 MONTHS:
A. Leadership change — new VP Operations, COO, Plant Manager, CDO, or CTO hired or promoted
B. M&A / PE activity — acquisition completed or announced, PE firm investment, plant purchase
C. ESG / sustainability commitment — net-zero pledge, carbon reduction target, green energy announcement
D. Operational incident — press-reported equipment failure, unplanned shutdown, product recall, safety incident
E. CapEx investment — new production line, facility expansion, major equipment purchase, MES/ERP upgrade announced
F. Growth signal — new customer win, revenue growth announcement, headcount expansion (hiring surge on LinkedIn)
G. Competitor displacement — stated dissatisfaction with or removal of a competing vendor

For each trigger found, record: what happened, when (approximate date or quarter), and why it matters for outreach timing.

OUTPUT THIS EXACT JSON SCHEMA:
{{
    "company_description": "2-3 sentence description of what they manufacture and their market position",
    "manufacturing_type": "discrete" or "process" or "hybrid",
    "equipment_types": ["list", "of", "equipment", "types"],
    "known_systems": ["list", "of", "named", "technology", "systems", "identified"],
    "iot_maturity": "none" or "basic" or "intermediate" or "advanced",
    "maintenance_approach": "reactive" or "time_based" or "condition_based" or "predictive",
    "digital_transformation_status": "brief description of digital transformation initiatives or 'No initiatives found'",
    "pain_points": ["list", "of", "identified", "pain", "points", "or", "challenges"],
    "opportunities": ["list", "of", "specific", "opportunities", "for", "AI-powered", "manufacturing", "intelligence"],
    "existing_solutions": ["list", "of", "AI/ML", "or", "predictive", "platforms", "already", "in", "use"],
    "funding_status": "recent funding info or 'Not found'",
    "funding_details": "specific details or empty string",
    "trigger_events": [
        {{
            "type": "leadership_change" or "ma_pe" or "esg_commitment" or "operational_incident" or "capex_investment" or "growth_signal" or "competitor_displacement",
            "description": "specific factual description of what happened",
            "date_approx": "YYYY-QQ or YYYY-MM or 'Unknown'",
            "outreach_relevance": "one sentence on why this creates an opening for outreach"
        }}
    ],
    "trigger_score": 0-10,
    "personalization_hooks": [
        "3-5 specific, concrete facts that can be used to personalize outreach",
        "e.g., 'Operates 3 plants across the Midwest with 500+ employees'",
        "e.g., 'Uses SAP ERP and Rockwell automation — strong technical alignment with the platform'",
        "e.g., 'New VP Ops joined from Honeywell in Q1 2025 — likely evaluating new tools'"
    ],
    "confidence_level": "high" or "medium" or "low",
    "awareness_level": "unaware" or "problem_aware" or "solution_aware"
}}

Rules:
- trigger_events must be an array (empty [] if none found — do NOT omit the field)
- trigger_score: 0=no triggers, 1-3=weak signals, 4-6=moderate, 7-10=strong/multiple triggers
- Do not fabricate events — only include triggers with factual basis
- awareness_level:
    "unaware"        — no evidence they are aware of AI manufacturing intelligence platforms
    "problem_aware"  — evidence they recognize operational problems (downtime, OEE, quality loss) but not specifically AI solutions
    "solution_aware" — evidence they are evaluating or have evaluated AI/ML manufacturing platforms (existing_solutions not empty, or digital transformation initiatives mention AI/ML)
- Output ONLY valid JSON. No markdown, no explanation, no preamble."""


class ResearchAgent(BaseAgent):
    """Research companies using a single Claude call per company."""

    agent_name = "research"

    def run(
        self,
        company_ids: list[str] | None = None,
        batch_id: str | None = None,
        min_firmographic_score: int | None = None,
        tier: str | None = None,
        tiers: list[str] | None = None,
        limit: int | None = None,
    ) -> AgentResult:
        """Run research on discovered companies.

        Args:
            company_ids: Specific company IDs to research (highest priority).
            batch_id: Research all companies tagged with this batch ID (from select_batch).
            min_firmographic_score: Minimum firmographic PQS to research (default from config).
            tier: Single tier to filter by (e.g. "fb1", "1a").
            tiers: Multiple tiers to filter by (e.g. ["fb1", "fb2"]).
            limit: Max companies to research in this batch.

        Returns:
            AgentResult with processing stats.
        """
        result = AgentResult()
        settings = get_settings()
        scoring_config = get_scoring_config()

        min_score = min_firmographic_score if min_firmographic_score is not None else scoring_config.get("min_firmographic_for_research", 0)
        batch_limit = limit or settings.batch_size

        # Merge tier / tiers into a single list
        tier_list = list(tiers) if tiers else []
        if tier and tier not in tier_list:
            tier_list.append(tier)

        # Get companies to research — explicit IDs > batch_id > default query
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        elif batch_id:
            companies = self.db.get_companies(batch_id=batch_id, status="discovered", limit=batch_limit)
        elif tier_list:
            # Fetch per tier and merge (respecting overall limit)
            companies = []
            for t in tier_list:
                remaining = batch_limit - len(companies)
                if remaining <= 0:
                    break
                companies.extend(
                    self.db.get_companies(status="discovered", tier=t, min_pqs=min_score, limit=remaining)
                )
        else:
            companies = self.db.get_companies(status="discovered", min_pqs=min_score, limit=batch_limit)

        if not companies:
            console.print("[yellow]No companies to research.[/yellow]")
            return result

        console.print(f"[cyan]Researching {len(companies)} companies (min PQS_firm={min_score})...[/cyan]")

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        for company in companies:
            company_name = company["name"]
            company_id = company["id"]
            console.print(f"\n  [bold]{company_name}[/bold]")

            try:
                # Tier model by firmographic PQS — Haiku for low-PQS, Sonnet for >=6
                model_id, prompt_variant = _select_research_model(company)

                if prompt_variant == "slim":
                    console.print(f"    [dim]Quick scan via Haiku (low PQS)...[/dim]")
                    slim = self._slim_research(client=client, company=company)

                    if slim is None:
                        console.print("    [red]Slim research failed. Skipping.[/red]")
                        result.errors += 1
                        result.add_detail(company_name, "error", "Haiku slim returned no valid JSON")
                        if self._monitor:
                            self._monitor.log_error(
                                "Haiku slim research failed",
                                company_id=company_id,
                                error_type="parse_error",
                            )
                        continue

                    if not slim.get("promote_to_full_research"):
                        # Mark as researched with low-confidence flag — saves a Sonnet call
                        existing_tags = company.get("custom_tags") or {}
                        if isinstance(existing_tags, str):
                            try:
                                existing_tags = json.loads(existing_tags)
                            except (json.JSONDecodeError, TypeError):
                                existing_tags = {}
                        existing_tags["research_path"] = "haiku_only"
                        existing_tags["promote_to_full_research"] = False

                        self.db.update_company(company_id, {
                            "status": "researched",
                            "manufacturing_profile": {
                                "type": slim.get("manufacturing_type", "unknown"),
                                "equipment": slim.get("equipment_types", []),
                                "is_real_manufacturer": slim.get("is_real_manufacturer", False),
                            },
                            "custom_tags": existing_tags,
                        })
                        confidence = slim.get("confidence_level", "low")
                        console.print(
                            f"    [yellow]Haiku-only path: {confidence} confidence, "
                            f"not promoted to full research.[/yellow]"
                        )
                        result.processed += 1
                        result.add_detail(company_name, "haiku_only", f"confidence={confidence}")
                        continue

                    # Promoted — fall through to Sonnet research
                    console.print("    [dim]Haiku promoted to full research → Sonnet...[/dim]")

                console.print("    [dim]Researching via Claude...[/dim]")
                structured = self._research_with_claude(
                    client=client,
                    company=company,
                )

                if structured is None:
                    console.print("    [red]Research failed. Skipping.[/red]")
                    result.errors += 1
                    result.add_detail(company_name, "error", "Claude research returned no valid JSON")
                    if self._monitor:
                        self._monitor.log_error(
                            "Claude research returned no valid JSON",
                            company_id=company_id,
                            error_type="parse_error",
                        )
                    continue

                # Upsert research_intelligence
                self.db.upsert_research({
                    "company_id": company_id,
                    "perplexity_response": "",  # No longer used
                    "claude_analysis": json.dumps(structured),
                    "company_description": structured.get("company_description", ""),
                    "manufacturing_type": structured.get("manufacturing_type", "unknown"),
                    "equipment_types": structured.get("equipment_types", []),
                    "known_systems": structured.get("known_systems", []),
                    "iot_maturity": structured.get("iot_maturity", "unknown"),
                    "maintenance_approach": structured.get("maintenance_approach", "unknown"),
                    "digital_transformation_status": structured.get("digital_transformation_status", ""),
                    "pain_points": structured.get("pain_points", []),
                    "opportunities": structured.get("opportunities", []),
                    "existing_solutions": structured.get("existing_solutions", []),
                    "funding_status": structured.get("funding_status", ""),
                    "funding_details": structured.get("funding_details", ""),
                    "confidence_level": structured.get("confidence_level", "low"),
                    # trigger_events + trigger_score are stored in claude_analysis JSONB above.
                    # Dedicated columns require migration 014 to be run in Supabase dashboard first.
                })

                # Update company record with key intelligence fields
                trigger_events = structured.get("trigger_events", [])
                trigger_score = structured.get("trigger_score", 0)

                # Promote high-trigger companies in custom_tags for prioritization
                existing_tags = company.get("custom_tags") or {}
                if isinstance(existing_tags, str):
                    try:
                        existing_tags = json.loads(existing_tags)
                    except (json.JSONDecodeError, TypeError):
                        existing_tags = {}

                updated_tags = {
                    **existing_tags,
                    "trigger_score": trigger_score,
                    "trigger_count": len(trigger_events),
                    **({"trigger_types": [e.get("type") for e in trigger_events]} if trigger_events else {}),
                }

                self.db.update_company(company_id, {
                    "research_summary": structured.get("company_description", ""),
                    "technology_stack": structured.get("known_systems", []),
                    "pain_signals": structured.get("pain_points", []),
                    "manufacturing_profile": {
                        "type": structured.get("manufacturing_type", "unknown"),
                        "equipment": structured.get("equipment_types", []),
                        "iot_maturity": structured.get("iot_maturity", "unknown"),
                        "maintenance_approach": structured.get("maintenance_approach", "unknown"),
                    },
                    "personalization_hooks": structured.get("personalization_hooks", []),
                    "custom_tags": updated_tags,
                    "status": "researched",
                })

                confidence = structured.get("confidence_level", "low")
                console.print(f"    [green]Done. Confidence: {confidence}[/green]")
                result.processed += 1
                result.add_detail(company_name, "researched", f"confidence={confidence}")

            except Exception as e:
                logger.error(f"Error researching {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])
                if self._monitor:
                    self._monitor.log_error(str(e), company_id=company_id, error_type="research_error", exc=e)

        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f"*Research complete:* {result.processed} companies researched, "
                f"{result.skipped} skipped, {result.errors} errors. "
                f"Cost: ${result.total_cost_usd:.4f}",
                emoji=":mag:",
            )
        except Exception:
            pass

        return result

    def _slim_research(self, client, company: dict) -> dict | None:
        """Quick Haiku triage call. Returns a dict with `promote_to_full_research`.

        Used for low-PQS companies to decide whether they're worth a full
        Sonnet research call. ~10x cheaper than Sonnet research.
        """
        prompt = SLIM_RESEARCH_USER.format(
            company_name=company.get("name", ""),
            industry=company.get("industry", "Manufacturing"),
            city=company.get("city", ""),
            state=company.get("state", ""),
            country=company.get("country", "US"),
            website=company.get("website", "Not available"),
            employee_count=company.get("employee_count", "Not available"),
        )

        try:
            response = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=400,
                system=SLIM_RESEARCH_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            usage = response.usage
            self.track_cost(
                provider="anthropic",
                model=HAIKU_MODEL,
                endpoint="/messages",
                company_id=company.get("id"),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Slim research JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Slim research error: {e}")
            return None

    def _research_with_claude(
        self, client, company: dict,
    ) -> dict | None:
        """Research a company and extract structured intelligence in a single Claude call.

        Returns:
            Parsed dict or None if research fails.
        """
        location = ", ".join(filter(None, [
            company.get("city"), company.get("state"), company.get("country")
        ]))

        prompt = RESEARCH_USER.format(
            company_name=company.get("name", ""),
            industry=company.get("industry", "Manufacturing"),
            city=company.get("city", ""),
            state=company.get("state", ""),
            country=company.get("country", "US"),
            website=company.get("website", "Not available"),
            linkedin_url=company.get("linkedin_url", "Not available"),
            employee_count=company.get("employee_count", "Not available"),
            revenue=company.get("estimated_revenue", "Not available"),
        )

        try:
            response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=2000,
                system=RESEARCH_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            # Track cost
            usage = response.usage
            self.track_cost(
                provider="anthropic",
                model=SONNET_MODEL,
                endpoint="/messages",
                company_id=company.get("id"),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            # Parse JSON response
            content = response.content[0].text.strip()
            # Handle potential markdown wrapping
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            parsed = json.loads(content)

            # Validate against our model
            validated = ResearchResult(**parsed)
            return validated.model_dump()

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude JSON response: {e}")
            logger.debug(f"Raw response: {content[:500]}")
            return None
        except Exception as e:
            logger.error(f"Claude research error: {e}")
            return None
