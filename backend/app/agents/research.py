"""Research Agent — Deep company research.

Uses Perplexity (1 call) + Claude (1 call) per company.
Populates research_intelligence and updates company fields.
"""

import json
import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_scoring_config
from backend.app.core.models import ResearchResult
from backend.app.integrations.perplexity import PerplexityClient

console = Console()
logger = logging.getLogger(__name__)

# Claude structured analysis prompt
CLAUDE_ANALYSIS_SYSTEM = """You are a manufacturing intelligence analyst. Your job is to parse
research data about manufacturing companies and extract structured intelligence for a sales
prospecting system.

You must output valid JSON matching the exact schema provided. Be accurate and evidence-based.
If information is not available in the research, use appropriate defaults rather than guessing."""

CLAUDE_ANALYSIS_USER = """Analyze this manufacturing company research and extract structured intelligence.

COMPANY: {company_name}
INDUSTRY: {industry}
LOCATION: {city}, {state}, {country}
WEBSITE: {website}

RESEARCH DATA:
{research_text}

TECHNOLOGY SYSTEMS TO LOOK FOR:
- ERP: SAP, Oracle, Epicor, Infor, Microsoft Dynamics, SYSPRO, Plex, QAD
- CMMS/APM: IBM Maximo, SAP PM, UpKeep, Fiix, eMaint, Limble, MaintainX
- SCADA/MES: Rockwell FactoryTalk, Siemens WinCC/Opcenter, GE Proficy, Honeywell, OSIsoft PI, Ignition, Wonderware/AVEVA
- PLCs: Allen-Bradley, Siemens S7, Mitsubishi, Fanuc, Omron, Beckhoff
- AI/ML Competitors: Uptake, SparkCognition, C3.ai, Sight Machine, MachineMetrics, Falkonry, Augury, Senseye

EXTRACT INTO THIS EXACT JSON SCHEMA:
{{
    "company_description": "2-3 sentence description of what they manufacture and their market position",
    "manufacturing_type": "discrete" or "process" or "hybrid",
    "equipment_types": ["list", "of", "equipment", "types", "mentioned"],
    "known_systems": ["list", "of", "named", "technology", "systems", "identified"],
    "iot_maturity": "none" or "basic" or "intermediate" or "advanced",
    "maintenance_approach": "reactive" or "time_based" or "condition_based" or "predictive",
    "digital_transformation_status": "brief description of digital transformation initiatives or 'No initiatives found'",
    "pain_points": ["list", "of", "identified", "pain", "points", "or", "challenges"],
    "opportunities": ["list", "of", "specific", "opportunities", "for", "Digitillis", "AI", "platform"],
    "existing_solutions": ["list", "of", "AI/ML", "or", "predictive", "platforms", "already", "in", "use"],
    "funding_status": "recent funding info or 'Not found'",
    "funding_details": "specific details or empty string",
    "personalization_hooks": [
        "3-5 specific, concrete facts that can be used to personalize outreach",
        "e.g., 'Recently announced $50M plant expansion in Indiana'",
        "e.g., 'Hired new VP of Digital Transformation in January 2026'",
        "e.g., 'Uses SAP ERP and Rockwell automation — direct integration path for Digitillis'"
    ],
    "confidence_level": "high" or "medium" or "low"
}}

Output ONLY valid JSON. No markdown formatting, no explanation, no preamble."""


class ResearchAgent(BaseAgent):
    """Deep-research companies using Perplexity + Claude."""

    agent_name = "research"

    def run(
        self,
        company_ids: list[str] | None = None,
        min_firmographic_score: int | None = None,
        limit: int | None = None,
    ) -> AgentResult:
        """Run research on discovered companies.

        Args:
            company_ids: Specific company IDs to research (overrides query).
            min_firmographic_score: Minimum firmographic PQS to research (default from config).
            limit: Max companies to research in this batch.

        Returns:
            AgentResult with processing stats.
        """
        result = AgentResult()
        settings = get_settings()
        scoring_config = get_scoring_config()

        min_score = min_firmographic_score or scoring_config.get("min_firmographic_for_research", 10)
        batch_limit = limit or settings.batch_size

        # Get companies to research
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        else:
            companies = self.db.get_companies(status="discovered", min_pqs=min_score, limit=batch_limit)

        if not companies:
            console.print("[yellow]No companies to research.[/yellow]")
            return result

        console.print(f"[cyan]Researching {len(companies)} companies (min PQS_firm={min_score})...[/cyan]")

        perplexity = PerplexityClient()

        try:
            for company in companies:
                company_name = company["name"]
                company_id = company["id"]
                console.print(f"\n  [bold]{company_name}[/bold]")

                try:
                    # --- Step 1: Perplexity deep research ---
                    console.print("    [dim]Step 1: Perplexity research...[/dim]")
                    location = ", ".join(filter(None, [
                        company.get("city"), company.get("state"), company.get("country")
                    ]))

                    research_result = perplexity.research_company(
                        company_name=company_name,
                        website=company.get("website"),
                        industry=company.get("industry"),
                        linkedin_url=company.get("linkedin_url"),
                        location=location,
                    )

                    research_text = research_result["content"]
                    usage = research_result["usage"]

                    self.track_cost(
                        provider="perplexity",
                        model="sonar-pro",
                        endpoint="/chat/completions",
                        company_id=company_id,
                        input_tokens=usage.get("input_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0),
                    )

                    if not research_text or len(research_text) < 100:
                        console.print("    [red]Insufficient research data. Skipping.[/red]")
                        result.skipped += 1
                        result.add_detail(company_name, "skipped", "Insufficient Perplexity data")
                        continue

                    # --- Step 2: Claude structured analysis ---
                    console.print("    [dim]Step 2: Claude analysis...[/dim]")
                    structured = self._analyze_with_claude(
                        company=company,
                        research_text=research_text,
                        settings=settings,
                    )

                    if structured is None:
                        console.print("    [red]Claude analysis failed. Skipping.[/red]")
                        result.errors += 1
                        result.add_detail(company_name, "error", "Claude analysis failed")
                        continue

                    # --- Step 3: Write to database ---
                    # Upsert research_intelligence
                    self.db.upsert_research({
                        "company_id": company_id,
                        "perplexity_response": research_text,
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
                    })

                    # Update company record with key intelligence fields
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

        finally:
            perplexity.close()

        return result

    def _analyze_with_claude(
        self, company: dict, research_text: str, settings
    ) -> dict | None:
        """Analyze research text with Claude and return structured JSON.

        Returns:
            Parsed dict or None if analysis fails.
        """
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = CLAUDE_ANALYSIS_USER.format(
            company_name=company.get("name", ""),
            industry=company.get("industry", "Manufacturing"),
            city=company.get("city", ""),
            state=company.get("state", ""),
            country=company.get("country", "US"),
            website=company.get("website", "Not available"),
            research_text=research_text,
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=CLAUDE_ANALYSIS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            # Track cost
            usage = response.usage
            self.track_cost(
                provider="anthropic",
                model="claude-sonnet-4-20250514",
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
            logger.error(f"Claude analysis error: {e}")
            return None
