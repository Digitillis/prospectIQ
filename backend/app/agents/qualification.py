"""Qualification Agent — PQS scoring engine.

Rule-based scoring driven by scoring.yaml configuration.
No LLM calls needed — scans research intelligence for keyword matches.
"""

from __future__ import annotations

import json
import logging
import re

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_scoring_config
from backend.app.core.models import PQSScore
from backend.app.utils.territory import is_midwest

console = Console()
logger = logging.getLogger(__name__)


class QualificationAgent(BaseAgent):
    """Score and qualify companies based on the PQS framework."""

    agent_name = "qualification"

    def run(
        self,
        company_ids: list[str] | None = None,
        limit: int = 100,
    ) -> AgentResult:
        """Run qualification scoring on researched companies.

        Args:
            company_ids: Specific company IDs to score (overrides query).
            limit: Max companies to score in this batch.

        Returns:
            AgentResult with scoring stats.
        """
        result = AgentResult()
        config = get_scoring_config()

        # Get companies to qualify
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c is not None]
        else:
            # Score both freshly-discovered and fully-researched companies.
            # Discovered companies receive firmographic scoring only (tech/timing
            # signals default to 0 until research is run).  Researched companies
            # get full four-dimension scoring.
            discovered = self.db.get_companies(status="discovered", limit=limit)
            researched = self.db.get_companies(status="researched", limit=limit)
            companies = (discovered + researched)[:limit]

        if not companies:
            console.print("[yellow]No companies to qualify.[/yellow]")
            return result

        console.print(f"[cyan]Qualifying {len(companies)} companies...[/cyan]")

        for company in companies:
            company_name = company["name"]
            company_id = company["id"]
            is_discovered = company.get("status") == "discovered"

            try:
                # Get research intelligence
                research = self.db.get_research(company_id)

                # Calculate all 4 dimensions
                pqs = PQSScore()
                pqs.firmographic = self._score_firmographic(company, config)
                pqs.technographic = self._score_technographic(company, research, config)
                pqs.timing = self._score_timing(company, research, config)
                pqs.engagement = company.get("pqs_engagement", 0)
                pqs.total = pqs.firmographic + pqs.technographic + pqs.timing + pqs.engagement

                # For discovered companies (no research yet) only apply the
                # firmographic pre-filter using pre_research_thresholds.
                # Full PQS classification uses post_research thresholds.
                if is_discovered:
                    pre_thresholds = config.get("pre_research_thresholds", {})
                    disqualify_max = pre_thresholds.get("disqualify", {}).get("max_score", 4)

                    if pqs.firmographic <= disqualify_max:
                        pqs.classification = "unqualified"
                        new_status = "disqualified"
                        priority = False
                        pqs.notes = (
                            f"Failed firmographic pre-filter (score {pqs.firmographic} "
                            f"<= {disqualify_max}). Total PQS: {pqs.total}/100."
                        )
                    else:
                        pqs.classification = "research_needed"
                        new_status = None  # keep as discovered, eligible for research
                        priority = False
                        pqs.notes = (
                            f"Firmographic pre-filter passed (score {pqs.firmographic}). "
                            f"Pending full scoring after research. Total PQS: {pqs.total}/100."
                        )
                else:
                    # Research quality gate — reject low-confidence research
                    confidence = (research or {}).get("confidence_level", "low")
                    if confidence == "low" and pqs.technographic == 0 and pqs.timing == 0:
                        # Research returned nothing useful — don't waste outreach
                        pqs.classification = "research_needed"
                        new_status = None  # keep as researched, flag for re-research
                        priority = False
                        pqs.notes = (
                            f"Low-confidence research with zero tech/timing signals. "
                            f"Re-research recommended before outreach. PQS: {pqs.total}/100."
                        )
                    else:
                        # Full classification for researched companies
                        pqs.classification, new_status, priority = self._classify(pqs.total, config)
                        pqs.notes = self._generate_notes(pqs, company, research)

                # Update database
                update_data = {
                    "pqs_firmographic": pqs.firmographic,
                    "pqs_technographic": pqs.technographic,
                    "pqs_timing": pqs.timing,
                    "pqs_engagement": pqs.engagement,
                    "pqs_total": pqs.total,
                    "qualification_notes": pqs.notes,
                }

                if new_status:
                    update_data["status"] = new_status
                if priority:
                    update_data["priority_flag"] = True

                self.db.update_company(company_id, update_data)

                # Log result
                status_emoji = {
                    "qualified": "[green]QUALIFIED[/green]",
                    "high_priority": "[bold green]HIGH PRIORITY[/bold green]",
                    "hot_prospect": "[bold magenta]HOT PROSPECT[/bold magenta]",
                    "research_needed": "[yellow]NEEDS RESEARCH[/yellow]",
                    "unqualified": "[dim]Disqualified[/dim]",
                }.get(pqs.classification, pqs.classification)

                console.print(
                    f"  {company_name}: PQS={pqs.total} "
                    f"(F={pqs.firmographic} T={pqs.technographic} Ti={pqs.timing} E={pqs.engagement}) "
                    f"→ {status_emoji}"
                )

                result.processed += 1
                result.add_detail(
                    company_name,
                    pqs.classification,
                    f"PQS={pqs.total} (F={pqs.firmographic}/T={pqs.technographic}/Ti={pqs.timing}/E={pqs.engagement})",
                )

            except Exception as e:
                logger.error(f"Error qualifying {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        # Count classification outcomes for the Slack summary
        qualified_count = sum(
            1 for d in result.details
            if d.get("status") in ("qualified", "high_priority", "hot_prospect")
        )
        disqualified_count = sum(
            1 for d in result.details
            if d.get("status") == "unqualified"
        )

        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f"*Qualification complete:* {result.processed} companies scored — "
                f"{qualified_count} qualified, {disqualified_count} disqualified, "
                f"{result.errors} errors.",
                emoji=":white_check_mark:",
            )
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    def _score_firmographic(self, company: dict, config: dict) -> int:
        """Score firmographic fit (Dimension 1).

        Dynamically evaluates all signals defined in the scoring YAML
        rather than hardcoding signal names.
        """
        signals = config["dimensions"]["firmographic"]["signals"]
        max_pts = config["dimensions"]["firmographic"]["max_points"]
        score = 0

        revenue = company.get("estimated_revenue")
        employees = company.get("employee_count")
        state = company.get("state")
        tier = company.get("tier") or ""

        for signal_name, sig in signals.items():
            eval_type = sig.get("evaluation", "")

            if eval_type == "naics_prefix_match":
                # Award if company has a tier (meaning it matched an industry filter)
                if tier:
                    score += sig["points"]

            elif eval_type == "revenue_range":
                if revenue and sig.get("min", 0) <= revenue <= sig.get("max", float("inf")):
                    score += sig["points"]

            elif eval_type == "state_match":
                qualifying = sig.get("qualifying_states", [])
                if not state or state in qualifying:
                    score += sig["points"]

            elif eval_type == "employee_range":
                if employees and sig.get("min", 0) <= employees <= sig.get("max", float("inf")):
                    score += sig["points"]

            elif eval_type == "boolean_field":
                field = sig.get("field", "")
                if company.get(field):
                    score += sig["points"]

            elif eval_type == "keyword_match":
                # Firmographic keyword signals (e.g. multi_plant) checked against research text
                search_text = self._build_search_text(company, None)
                keywords = sig.get("keywords", [])
                if search_text and self._has_keyword_match(search_text, keywords):
                    score += sig["points"]

        return min(score, max_pts)

    def _score_technographic(self, company: dict, research: dict | None, config: dict) -> int:
        """Score technographic readiness (Dimension 2)."""
        signals = config["dimensions"]["technographic"]["signals"]
        max_pts = config["dimensions"]["technographic"]["max_points"]
        score = 0

        # Build searchable text from research intelligence
        search_text = self._build_search_text(company, research)
        if not search_text:
            return 0

        for signal_name, signal_config in signals.items():
            eval_type = signal_config.get("evaluation")

            if eval_type == "keyword_match":
                keywords = signal_config.get("keywords", [])
                if self._has_keyword_match(search_text, keywords):
                    score += signal_config["points"]

            elif eval_type == "negative_keyword_match":
                # Points awarded if NONE of the negative keywords match
                neg_keywords = signal_config.get("negative_keywords", [])
                if not self._has_keyword_match(search_text, neg_keywords):
                    score += signal_config["points"]

        return min(score, max_pts)

    def _score_timing(self, company: dict, research: dict | None, config: dict) -> int:
        """Score timing & pain signals (Dimension 3)."""
        signals = config["dimensions"]["timing"]["signals"]
        max_pts = config["dimensions"]["timing"]["max_points"]
        score = 0

        search_text = self._build_search_text(company, research)
        if not search_text:
            return 0

        for signal_name, signal_config in signals.items():
            eval_type = signal_config.get("evaluation")

            if eval_type == "keyword_match":
                keywords = signal_config.get("keywords", [])
                if self._has_keyword_match(search_text, keywords):
                    score += signal_config["points"]

        return min(score, max_pts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_search_text(self, company: dict, research: dict | None) -> str:
        """Build a searchable text blob from company + research data."""
        parts = []

        # Company-level data
        parts.append(company.get("research_summary", "") or "")
        parts.append(json.dumps(company.get("technology_stack", [])))
        parts.append(json.dumps(company.get("pain_signals", [])))
        parts.append(json.dumps(company.get("manufacturing_profile", {})))
        parts.append(json.dumps(company.get("personalization_hooks", [])))

        # Research intelligence
        if research:
            parts.append(research.get("perplexity_response", "") or "")
            parts.append(research.get("claude_analysis", "") or "")
            parts.append(research.get("company_description", "") or "")
            parts.append(research.get("digital_transformation_status", "") or "")
            parts.append(json.dumps(research.get("equipment_types", [])))
            parts.append(json.dumps(research.get("known_systems", [])))
            parts.append(json.dumps(research.get("pain_points", [])))
            parts.append(json.dumps(research.get("opportunities", [])))
            parts.append(json.dumps(research.get("existing_solutions", [])))
            parts.append(research.get("funding_status", "") or "")
            parts.append(research.get("funding_details", "") or "")

        return " ".join(parts).lower()

    def _has_keyword_match(self, text: str, keywords: list[str]) -> bool:
        """Check if any keyword appears in the text (case-insensitive)."""
        text_lower = text.lower()
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return True
        return False

    def _classify(self, total_score: int, config: dict) -> tuple[str, str | None, bool]:
        """Classify a PQS score into a qualification level.

        Returns:
            Tuple of (classification_name, new_status_or_None, priority_flag).
        """
        thresholds = config["thresholds"]

        if total_score <= thresholds["unqualified"]["max_score"]:
            return "unqualified", thresholds["unqualified"].get("new_status"), False
        elif total_score <= thresholds["research_needed"]["max_score"]:
            return "research_needed", thresholds["research_needed"].get("new_status"), False
        elif total_score <= thresholds["qualified"]["max_score"]:
            return "qualified", thresholds["qualified"].get("new_status"), False
        elif total_score <= thresholds["high_priority"]["max_score"]:
            return "high_priority", thresholds["high_priority"].get("new_status"), True
        else:
            return "hot_prospect", thresholds["hot_prospect"].get("new_status"), True

    def _generate_notes(self, pqs: PQSScore, company: dict, research: dict | None) -> str:
        """Generate human-readable qualification notes."""
        notes = []

        if pqs.firmographic >= 15:
            notes.append("Strong firmographic fit")
        elif pqs.firmographic >= 10:
            notes.append("Good firmographic match")
        else:
            notes.append("Weak firmographic fit")

        if pqs.technographic >= 15:
            notes.append("strong tech stack match")
        elif pqs.technographic >= 8:
            notes.append("moderate tech readiness")
        else:
            notes.append("limited tech signals")

        if pqs.timing >= 10:
            notes.append("active timing signals")
        elif pqs.timing >= 5:
            notes.append("some timing indicators")

        if research and research.get("existing_solutions"):
            solutions = research.get("existing_solutions", [])
            if solutions:
                notes.append(f"WATCH: existing solutions: {', '.join(solutions[:3])}")

        return "; ".join(notes) + f". Total PQS: {pqs.total}/100."
