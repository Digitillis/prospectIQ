"""Learning Agent -- Analyzes outcomes, surfaces insights, suggests refinements.

Uses Claude Sonnet to analyze aggregated outreach performance data
and generate actionable insights for improving engagement strategy.

When auto_apply=True, writes scoring adjustments back to scoring.yaml
and ICP refinements back to icp.yaml — closing the feedback loop.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import yaml
from rich.console import Console
from rich.table import Table

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, CONFIG_DIR

console = Console()
logger = logging.getLogger(__name__)

LEARNING_ANALYSIS_SYSTEM = """You are a B2B sales analytics expert specializing in manufacturing outreach performance. You analyze engagement data for a B2B outreach program and generate actionable insights.

Your analysis should:
- Identify patterns in what works and what doesn't
- Suggest specific, testable improvements to messaging and targeting
- Highlight sub-sectors and personas with the highest potential
- Recommend scoring adjustments based on observed engagement
- Be data-driven and avoid speculation without evidence
- Prioritize insights by potential impact

Output ONLY valid JSON. No markdown, no explanation."""

LEARNING_ANALYSIS_USER = """Analyze this B2B outreach performance data and generate actionable insights.

ANALYSIS PERIOD: Last {period_days} days
TOTAL OUTCOMES: {total_outcomes}

OVERALL METRICS:
- Total Sent: {total_sent}
- Total Opened: {total_opened} ({open_rate:.1f}%)
- Total Replied: {total_replied} ({reply_rate:.1f}%)
- Positive Replies: {positive_replies} ({positive_rate:.1f}%)
- Meetings Booked: {meetings_booked}

PERFORMANCE BY SUB-SECTOR:
{by_sub_sector}

PERFORMANCE BY PERSONA TYPE:
{by_persona}

PERFORMANCE BY PQS RANGE:
{by_pqs_range}

CLASSIFICATION BREAKDOWN:
{classification_breakdown}

OUTPUT FORMAT (JSON):
{{
    "top_insights": [
        {{
            "insight": "Clear description of the finding",
            "evidence": "Data points supporting it",
            "impact": "high|medium|low",
            "action": "Specific recommendation"
        }}
    ],
    "scoring_adjustments": [
        {{
            "dimension": "firmographic|technographic|timing|engagement",
            "signal": "Which signal to adjust",
            "current_behavior": "What's happening now",
            "suggested_change": "What to change",
            "rationale": "Why this change would help"
        }}
    ],
    "messaging_suggestions": [
        {{
            "target": "sub_sector or persona",
            "current_approach": "What we're doing",
            "suggested_change": "What to try instead",
            "expected_improvement": "What we expect to see"
        }}
    ],
    "icp_refinements": [
        {{
            "refinement": "Description of ICP adjustment",
            "evidence": "Supporting data",
            "priority": "high|medium|low"
        }}
    ]
}}

Output ONLY valid JSON. No markdown, no explanation."""


class LearningAgent(BaseAgent):
    """Analyze outreach outcomes and generate actionable insights."""

    agent_name = "learning"

    def run(self, period_days: int = 30, auto_apply: bool = False, **kwargs) -> AgentResult:
        """Analyze learning outcomes and generate insights.

        Args:
            period_days: Number of days to look back for analysis.

        Returns:
            AgentResult with analysis details.
        """
        result = AgentResult()
        settings = get_settings()

        console.print(f"[cyan]Analyzing outreach performance for the last {period_days} days...[/cyan]")

        # Fetch learning outcomes
        try:
            all_outcomes = self.db.get_learning_outcomes(limit=2000)
        except Exception as e:
            logger.error(f"Failed to fetch learning outcomes: {e}", exc_info=True)
            result.success = False
            result.errors = 1
            result.add_detail("N/A", "error", f"Failed to fetch outcomes: {str(e)[:200]}")
            return result

        # Filter to the specified period
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        cutoff_str = cutoff.isoformat()

        outcomes = [
            o for o in all_outcomes
            if o.get("created_at", "") >= cutoff_str
        ]

        console.print(f"  Found {len(outcomes)} outcomes in the last {period_days} days (of {len(all_outcomes)} total).")

        if len(outcomes) < 20:
            console.print(
                f"\n[yellow]Insufficient data for analysis. Need at least 20 outcomes, "
                f"found {len(outcomes)}. Collect more outreach data before running analysis.[/yellow]\n"
            )
            result.processed = 0
            result.skipped = len(outcomes)
            result.add_detail(
                "Learning Analysis",
                "insufficient_data",
                f"Only {len(outcomes)} outcomes in the last {period_days} days. Minimum 20 required.",
            )
            return result

        # Aggregate statistics
        stats = self._aggregate_stats(outcomes)

        # Display summary table
        self._print_summary_table(stats, period_days)

        # Call Claude Sonnet for analysis
        try:
            analysis = self._run_analysis(stats, period_days, settings)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude analysis response: {e}")
            result.errors += 1
            result.add_detail("Learning Analysis", "error", f"JSON parse error: {str(e)[:100]}")
            return result
        except Exception as e:
            logger.error(f"Error running Claude analysis: {e}", exc_info=True)
            result.errors += 1
            result.add_detail("Learning Analysis", "error", str(e)[:200])
            return result

        # Display insights
        self._print_insights(analysis)

        # Apply scoring adjustments back to config if auto_apply is set
        applied_count = 0
        if auto_apply:
            applied_count = self._apply_scoring_adjustments(analysis)
            if applied_count > 0:
                console.print(
                    f"\n  [bold green]Auto-applied {applied_count} scoring adjustment(s) "
                    f"to config/scoring.yaml[/bold green]"
                )
            icp_applied = self._apply_icp_refinements(analysis)
            if icp_applied > 0:
                console.print(
                    f"\n  [bold magenta]Applied {icp_applied} ICP refinement(s) "
                    f"to config/icp.yaml[/bold magenta]"
                )
        else:
            adjustments = analysis.get("scoring_adjustments", [])
            if adjustments:
                console.print(
                    f"\n  [dim]Tip: Run with auto_apply=True to write "
                    f"{len(adjustments)} scoring adjustment(s) to config/scoring.yaml[/dim]"
                )
            refinements = [r for r in analysis.get("icp_refinements", []) if r.get("priority") == "high"]
            if refinements:
                console.print(
                    f"\n  [dim]Tip: Run with auto_apply=True to write "
                    f"{len(refinements)} high-priority ICP refinement(s) to config/icp.yaml[/dim]"
                )

        result.processed = 1
        result.add_detail(
            "Learning Analysis",
            "completed",
            f"Period: {period_days}d | Outcomes: {len(outcomes)} | "
            f"Insights: {len(analysis.get('top_insights', []))} | "
            f"Scoring adjustments: {len(analysis.get('scoring_adjustments', []))} "
            f"({'applied' if auto_apply else 'suggested only'}) | "
            f"Messaging suggestions: {len(analysis.get('messaging_suggestions', []))}",
        )

        return result

    def _aggregate_stats(self, outcomes: list[dict]) -> dict:
        """Aggregate outcome data into analysis-ready statistics.

        Returns:
            Dictionary with aggregated stats by various dimensions.
        """
        stats = {
            "total": len(outcomes),
            "total_sent": 0,
            "total_opened": 0,
            "total_replied": 0,
            "positive_replies": 0,
            "meetings_booked": 0,
            "by_sub_sector": defaultdict(lambda: {
                "sent": 0, "opened": 0, "replied": 0, "positive": 0, "meetings": 0,
            }),
            "by_persona": defaultdict(lambda: {
                "sent": 0, "opened": 0, "replied": 0, "positive": 0, "meetings": 0,
            }),
            "by_pqs_range": defaultdict(lambda: {
                "sent": 0, "opened": 0, "replied": 0, "positive": 0, "meetings": 0,
            }),
            "by_classification": defaultdict(int),
        }

        for outcome in outcomes:
            outcome_val = outcome.get("outcome", "")
            sub_sector = outcome.get("sub_sector", "Unknown") or "Unknown"
            persona = outcome.get("persona_type", "Unknown") or "Unknown"
            pqs = outcome.get("pqs_at_time", 0) or 0

            # Determine PQS range
            if pqs >= 70:
                pqs_range = "70-100 (Hot)"
            elif pqs >= 50:
                pqs_range = "50-69 (High)"
            elif pqs >= 30:
                pqs_range = "30-49 (Medium)"
            else:
                pqs_range = "0-29 (Low)"

            # Count by outcome value
            # Outcomes follow pattern: opened, replied_positive, replied_negative,
            # replied_question, no_response, meeting_booked
            if outcome_val in ("opened",):
                stats["total_sent"] += 1
                stats["total_opened"] += 1
                stats["by_sub_sector"][sub_sector]["sent"] += 1
                stats["by_sub_sector"][sub_sector]["opened"] += 1
                stats["by_persona"][persona]["sent"] += 1
                stats["by_persona"][persona]["opened"] += 1
                stats["by_pqs_range"][pqs_range]["sent"] += 1
                stats["by_pqs_range"][pqs_range]["opened"] += 1

            elif outcome_val.startswith("replied_"):
                stats["total_sent"] += 1
                stats["total_replied"] += 1
                stats["by_sub_sector"][sub_sector]["sent"] += 1
                stats["by_sub_sector"][sub_sector]["replied"] += 1
                stats["by_persona"][persona]["sent"] += 1
                stats["by_persona"][persona]["replied"] += 1
                stats["by_pqs_range"][pqs_range]["sent"] += 1
                stats["by_pqs_range"][pqs_range]["replied"] += 1

                # Track reply classification
                classification = outcome_val.replace("replied_", "")
                stats["by_classification"][classification] += 1

                if classification == "positive":
                    stats["positive_replies"] += 1
                    stats["by_sub_sector"][sub_sector]["positive"] += 1
                    stats["by_persona"][persona]["positive"] += 1
                    stats["by_pqs_range"][pqs_range]["positive"] += 1

            elif outcome_val == "no_response":
                stats["total_sent"] += 1
                stats["by_sub_sector"][sub_sector]["sent"] += 1
                stats["by_persona"][persona]["sent"] += 1
                stats["by_pqs_range"][pqs_range]["sent"] += 1

            elif outcome_val == "meeting_booked":
                stats["total_sent"] += 1
                stats["meetings_booked"] += 1
                stats["by_sub_sector"][sub_sector]["sent"] += 1
                stats["by_sub_sector"][sub_sector]["meetings"] += 1
                stats["by_persona"][persona]["sent"] += 1
                stats["by_persona"][persona]["meetings"] += 1
                stats["by_pqs_range"][pqs_range]["sent"] += 1
                stats["by_pqs_range"][pqs_range]["meetings"] += 1

        return stats

    def _run_analysis(self, stats: dict, period_days: int, settings) -> dict:
        """Call Claude Sonnet to analyze the aggregated stats.

        Returns:
            Parsed JSON analysis from Claude.
        """
        total_sent = max(stats["total_sent"], 1)  # Avoid division by zero

        # Format sub-sector breakdown
        sector_lines = []
        for sector, data in sorted(stats["by_sub_sector"].items()):
            sent = data["sent"]
            replied = data["replied"]
            rate = (replied / sent * 100) if sent > 0 else 0.0
            sector_lines.append(
                f"  {sector}: Sent={sent}, Opened={data['opened']}, "
                f"Replied={replied} ({rate:.1f}%), Positive={data['positive']}, "
                f"Meetings={data['meetings']}"
            )

        # Format persona breakdown
        persona_lines = []
        for persona, data in sorted(stats["by_persona"].items()):
            sent = data["sent"]
            replied = data["replied"]
            rate = (replied / sent * 100) if sent > 0 else 0.0
            persona_lines.append(
                f"  {persona}: Sent={sent}, Opened={data['opened']}, "
                f"Replied={replied} ({rate:.1f}%), Positive={data['positive']}, "
                f"Meetings={data['meetings']}"
            )

        # Format PQS range breakdown
        pqs_lines = []
        for pqs_range, data in sorted(stats["by_pqs_range"].items()):
            sent = data["sent"]
            replied = data["replied"]
            rate = (replied / sent * 100) if sent > 0 else 0.0
            pqs_lines.append(
                f"  {pqs_range}: Sent={sent}, Opened={data['opened']}, "
                f"Replied={replied} ({rate:.1f}%), Positive={data['positive']}, "
                f"Meetings={data['meetings']}"
            )

        # Format classification breakdown
        class_lines = []
        for cls, count in sorted(stats["by_classification"].items()):
            class_lines.append(f"  {cls}: {count}")

        prompt = LEARNING_ANALYSIS_USER.format(
            period_days=period_days,
            total_outcomes=stats["total"],
            total_sent=stats["total_sent"],
            total_opened=stats["total_opened"],
            open_rate=(stats["total_opened"] / total_sent * 100),
            total_replied=stats["total_replied"],
            reply_rate=(stats["total_replied"] / total_sent * 100),
            positive_replies=stats["positive_replies"],
            positive_rate=(stats["positive_replies"] / total_sent * 100),
            meetings_booked=stats["meetings_booked"],
            by_sub_sector="\n".join(sector_lines) or "  No data",
            by_persona="\n".join(persona_lines) or "  No data",
            by_pqs_range="\n".join(pqs_lines) or "  No data",
            classification_breakdown="\n".join(class_lines) or "  No data",
        )

        console.print("\n  [dim]Running Claude analysis on aggregated data...[/dim]")

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=LEARNING_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        # Track cost
        usage = response.usage
        self.track_cost(
            provider="anthropic",
            model="claude-sonnet-4-6",
            endpoint="/messages",
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

        return json.loads(content)

    def _print_summary_table(self, stats: dict, period_days: int) -> None:
        """Print a rich summary table of aggregated stats."""
        total_sent = max(stats["total_sent"], 1)

        # Overall metrics table
        table = Table(title=f"Outreach Performance Summary (Last {period_days} Days)")
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Count", justify="right", style="white")
        table.add_column("Rate", justify="right", style="green")

        table.add_row("Total Outcomes", str(stats["total"]), "")
        table.add_row("Sent", str(stats["total_sent"]), "")
        table.add_row("Opened", str(stats["total_opened"]), f"{stats['total_opened'] / total_sent * 100:.1f}%")
        table.add_row("Replied", str(stats["total_replied"]), f"{stats['total_replied'] / total_sent * 100:.1f}%")
        table.add_row("Positive Replies", str(stats["positive_replies"]), f"{stats['positive_replies'] / total_sent * 100:.1f}%")
        table.add_row("Meetings Booked", str(stats["meetings_booked"]), "")

        console.print(table)

        # Sub-sector table
        if stats["by_sub_sector"]:
            sector_table = Table(title="Performance by Sub-Sector")
            sector_table.add_column("Sub-Sector", style="cyan")
            sector_table.add_column("Sent", justify="right")
            sector_table.add_column("Opened", justify="right")
            sector_table.add_column("Replied", justify="right")
            sector_table.add_column("Reply Rate", justify="right", style="green")
            sector_table.add_column("Positive", justify="right")
            sector_table.add_column("Meetings", justify="right")

            for sector, data in sorted(stats["by_sub_sector"].items(), key=lambda x: x[1]["replied"], reverse=True):
                sent = data["sent"]
                rate = f"{data['replied'] / sent * 100:.1f}%" if sent > 0 else "N/A"
                sector_table.add_row(
                    sector, str(sent), str(data["opened"]),
                    str(data["replied"]), rate,
                    str(data["positive"]), str(data["meetings"]),
                )

            console.print(sector_table)

        # Persona table
        if stats["by_persona"]:
            persona_table = Table(title="Performance by Persona Type")
            persona_table.add_column("Persona", style="cyan")
            persona_table.add_column("Sent", justify="right")
            persona_table.add_column("Opened", justify="right")
            persona_table.add_column("Replied", justify="right")
            persona_table.add_column("Reply Rate", justify="right", style="green")
            persona_table.add_column("Positive", justify="right")

            for persona, data in sorted(stats["by_persona"].items(), key=lambda x: x[1]["replied"], reverse=True):
                sent = data["sent"]
                rate = f"{data['replied'] / sent * 100:.1f}%" if sent > 0 else "N/A"
                persona_table.add_row(
                    persona, str(sent), str(data["opened"]),
                    str(data["replied"]), rate, str(data["positive"]),
                )

            console.print(persona_table)

        # PQS range table
        if stats["by_pqs_range"]:
            pqs_table = Table(title="Performance by PQS Range")
            pqs_table.add_column("PQS Range", style="cyan")
            pqs_table.add_column("Sent", justify="right")
            pqs_table.add_column("Replied", justify="right")
            pqs_table.add_column("Reply Rate", justify="right", style="green")
            pqs_table.add_column("Positive", justify="right")

            for pqs_range, data in sorted(stats["by_pqs_range"].items()):
                sent = data["sent"]
                rate = f"{data['replied'] / sent * 100:.1f}%" if sent > 0 else "N/A"
                pqs_table.add_row(
                    pqs_range, str(sent), str(data["replied"]), rate, str(data["positive"]),
                )

            console.print(pqs_table)

    def _print_insights(self, analysis: dict) -> None:
        """Print Claude's analysis insights using rich formatting."""
        # Top insights
        insights = analysis.get("top_insights", [])
        if insights:
            console.print("\n[bold green]Top Insights[/bold green]")
            insights_table = Table(show_header=True)
            insights_table.add_column("#", style="dim", width=3)
            insights_table.add_column("Impact", style="bold", width=8)
            insights_table.add_column("Insight", style="white")
            insights_table.add_column("Action", style="cyan")

            for i, insight in enumerate(insights, 1):
                impact = insight.get("impact", "medium")
                impact_style = {"high": "[bold red]HIGH[/bold red]", "medium": "[yellow]MED[/yellow]", "low": "[dim]LOW[/dim]"}.get(impact, impact)
                insights_table.add_row(
                    str(i),
                    impact_style,
                    insight.get("insight", ""),
                    insight.get("action", ""),
                )

            console.print(insights_table)

        # Scoring adjustments
        adjustments = analysis.get("scoring_adjustments", [])
        if adjustments:
            console.print("\n[bold yellow]Scoring Adjustments[/bold yellow]")
            adj_table = Table(show_header=True)
            adj_table.add_column("Dimension", style="cyan", width=15)
            adj_table.add_column("Signal", style="white")
            adj_table.add_column("Suggested Change", style="green")
            adj_table.add_column("Rationale", style="dim")

            for adj in adjustments:
                adj_table.add_row(
                    adj.get("dimension", ""),
                    adj.get("signal", ""),
                    adj.get("suggested_change", ""),
                    adj.get("rationale", ""),
                )

            console.print(adj_table)

        # Messaging suggestions
        suggestions = analysis.get("messaging_suggestions", [])
        if suggestions:
            console.print("\n[bold blue]Messaging Suggestions[/bold blue]")
            msg_table = Table(show_header=True)
            msg_table.add_column("Target", style="cyan", width=20)
            msg_table.add_column("Current Approach", style="dim")
            msg_table.add_column("Suggested Change", style="green")
            msg_table.add_column("Expected Improvement", style="white")

            for sug in suggestions:
                msg_table.add_row(
                    sug.get("target", ""),
                    sug.get("current_approach", ""),
                    sug.get("suggested_change", ""),
                    sug.get("expected_improvement", ""),
                )

            console.print(msg_table)

        # ICP refinements
        refinements = analysis.get("icp_refinements", [])
        if refinements:
            console.print("\n[bold magenta]ICP Refinements[/bold magenta]")
            icp_table = Table(show_header=True)
            icp_table.add_column("Priority", style="bold", width=8)
            icp_table.add_column("Refinement", style="white")
            icp_table.add_column("Evidence", style="dim")

            for ref in refinements:
                priority = ref.get("priority", "medium")
                priority_style = {"high": "[bold red]HIGH[/bold red]", "medium": "[yellow]MED[/yellow]", "low": "[dim]LOW[/dim]"}.get(priority, priority)
                icp_table.add_row(
                    priority_style,
                    ref.get("refinement", ""),
                    ref.get("evidence", ""),
                )

            console.print(icp_table)

        console.print()

    # ------------------------------------------------------------------
    # Feedback loop — apply insights back to config
    # ------------------------------------------------------------------

    def _apply_icp_refinements(self, analysis: dict) -> int:
        """Write high-priority ICP refinements to icp.yaml.

        Appends structured refinement notes under a `learning_refinements` key
        rather than modifying the core ICP filters — preserving auditability.

        Returns:
            Number of refinements written.
        """
        refinements = [
            r for r in analysis.get("icp_refinements", [])
            if r.get("priority") == "high"
        ]
        if not refinements:
            return 0

        icp_path = CONFIG_DIR / "icp.yaml"
        if not icp_path.exists():
            logger.warning("icp.yaml not found, cannot apply ICP refinements")
            return 0

        with open(icp_path, "r") as f:
            config = yaml.safe_load(f) or {}

        # Backup
        backup_path = CONFIG_DIR / f"icp.yaml.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        existing = config.get("learning_refinements") or []
        for r in refinements:
            existing.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "refinement": r.get("refinement", ""),
                "evidence": r.get("evidence", ""),
                "priority": r.get("priority", "high"),
                "source": "learning_agent",
            })
            console.print(f"    [magenta]ICP note: {r.get('refinement', '')[:80]}[/magenta]")

        config["learning_refinements"] = existing

        with open(icp_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        console.print(f"\n  [dim]ICP backup saved to {backup_path.name}[/dim]")

        # Clear cache so next run picks up any downstream changes
        from backend.app.core.config import get_icp_config
        get_icp_config.cache_clear()

        return len(refinements)

    def _apply_scoring_adjustments(self, analysis: dict) -> int:
        """Apply scoring adjustments from Claude's analysis back to scoring.yaml.

        Only applies adjustments to threshold values and signal point weights.
        Backs up the original file before writing changes.

        Returns:
            Number of adjustments successfully applied.
        """
        adjustments = analysis.get("scoring_adjustments", [])
        if not adjustments:
            return 0

        scoring_path = CONFIG_DIR / "scoring.yaml"
        if not scoring_path.exists():
            logger.warning("scoring.yaml not found, cannot apply adjustments")
            return 0

        # Load current config
        with open(scoring_path, "r") as f:
            config = yaml.safe_load(f)

        # Back up before modifying
        backup_path = CONFIG_DIR / f"scoring.yaml.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        applied = 0
        dimensions = config.get("dimensions", {})

        for adj in adjustments:
            dimension = adj.get("dimension", "")
            signal = adj.get("signal", "")
            change = adj.get("suggested_change", "")

            if not dimension or not signal:
                continue

            # Only apply point-value changes (safe, reversible)
            # Parse suggestions like "increase to 7 points" or "reduce to 3 points"
            import re
            point_match = re.search(r"(\d+)\s*(?:points?|pts?)", change.lower())
            if not point_match:
                logger.info(
                    f"Skipping non-numeric adjustment: {dimension}/{signal}: {change}"
                )
                continue

            new_points = int(point_match.group(1))

            # Find the signal in the config
            dim_config = dimensions.get(dimension, {})
            signals = dim_config.get("signals", {})

            if signal in signals:
                old_points = signals[signal].get("points", 0)
                max_pts = dim_config.get("max_points", 25)

                # Safety: don't let any single signal exceed half the dimension max
                if new_points > max_pts // 2:
                    logger.warning(
                        f"Capping adjustment {dimension}/{signal}: "
                        f"{new_points} → {max_pts // 2} (max half of {max_pts})"
                    )
                    new_points = max_pts // 2

                if new_points != old_points:
                    signals[signal]["points"] = new_points
                    applied += 1
                    console.print(
                        f"    [green]Applied: {dimension}/{signal}: "
                        f"{old_points} → {new_points} pts[/green]"
                    )

        if applied > 0:
            # Write updated config
            with open(scoring_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            console.print(
                f"\n  [dim]Backup saved to {backup_path.name}[/dim]"
            )

            # Clear the lru_cache so next scoring run picks up changes
            from backend.app.core.config import get_scoring_config
            get_scoring_config.cache_clear()

        return applied
