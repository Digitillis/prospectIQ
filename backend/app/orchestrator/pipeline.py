"""Pipeline coordinator — chains agents in the correct order.

Provides a high-level API for running the full prospecting pipeline
or specific segments of it.
"""

from __future__ import annotations

import logging
from datetime import datetime

from rich.console import Console
from rich.table import Table

from backend.app.agents.base import AgentResult

console = Console()
logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrate agent execution in pipeline order."""

    def __init__(self, batch_prefix: str | None = None):
        self.batch_prefix = batch_prefix or f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.results: dict[str, AgentResult] = {}

    def run_full(
        self,
        max_pages: int = 3,
        campaign_name: str | None = None,
        skip_outreach: bool = False,
        tiers: list[str] | None = None,
    ) -> dict[str, AgentResult]:
        """Run the full pipeline: discovery → research → qualification → enrichment → outreach.

        Args:
            max_pages: Max pages per tier for Apollo discovery.
            campaign_name: Campaign name for tracking.
            skip_outreach: If True, stop after enrichment.
            tiers: Specific tiers to target.

        Returns:
            Dict of agent_name → AgentResult.
        """
        console.print("\n[bold magenta]{'='*60}[/bold magenta]")
        console.print("[bold magenta]ProspectIQ Full Pipeline[/bold magenta]")
        console.print(f"[bold magenta]Batch: {self.batch_prefix}[/bold magenta]")
        console.print("[bold magenta]{'='*60}[/bold magenta]\n")

        # Step 1: Discovery
        console.print("[bold]Step 1/5: Discovery[/bold]")
        discovery_result = self.run_discovery(
            max_pages=max_pages,
            campaign_name=campaign_name,
            tiers=tiers,
        )
        if not discovery_result.success:
            console.print("[red]Discovery failed. Stopping pipeline.[/red]")
            return self.results

        # Step 2: Research
        console.print("\n[bold]Step 2/5: Research[/bold]")
        research_result = self.run_research()
        if not research_result.success:
            console.print("[red]Research failed. Stopping pipeline.[/red]")
            return self.results

        # Step 3: Qualification
        console.print("\n[bold]Step 3/5: Qualification[/bold]")
        qualification_result = self.run_qualification()
        if not qualification_result.success:
            console.print("[red]Qualification failed. Stopping pipeline.[/red]")
            return self.results

        # Step 4: Enrichment (get emails/phones for qualified contacts)
        console.print("\n[bold]Step 4/5: Enrichment[/bold]")
        enrichment_result = self.run_enrichment()
        if not enrichment_result.success:
            console.print("[red]Enrichment failed. Stopping pipeline.[/red]")
            return self.results

        # Step 5: Outreach (optional)
        if not skip_outreach:
            console.print("\n[bold]Step 5/5: Outreach Generation[/bold]")
            self.run_outreach()
        else:
            console.print("\n[dim]Step 5/5: Outreach skipped[/dim]")

        self._print_summary()
        return self.results

    def run_discovery(self, **kwargs) -> AgentResult:
        """Run discovery agent."""
        from backend.app.agents.discovery import DiscoveryAgent

        agent = DiscoveryAgent(batch_id=f"{self.batch_prefix}_discovery")
        result = agent.execute(**kwargs)
        self.results["discovery"] = result
        return result

    def run_research(self, **kwargs) -> AgentResult:
        """Run research agent."""
        from backend.app.agents.research import ResearchAgent

        agent = ResearchAgent(batch_id=f"{self.batch_prefix}_research")
        result = agent.execute(**kwargs)
        self.results["research"] = result
        return result

    def run_qualification(self, **kwargs) -> AgentResult:
        """Run qualification agent."""
        from backend.app.agents.qualification import QualificationAgent

        agent = QualificationAgent(batch_id=f"{self.batch_prefix}_qualification")
        result = agent.execute(**kwargs)
        self.results["qualification"] = result
        return result

    def run_enrichment(self, **kwargs) -> AgentResult:
        """Run enrichment agent."""
        from backend.app.agents.enrichment import EnrichmentAgent

        agent = EnrichmentAgent(batch_id=f"{self.batch_prefix}_enrichment")
        result = agent.execute(**kwargs)
        self.results["enrichment"] = result
        return result

    def run_outreach(self, **kwargs) -> AgentResult:
        """Run outreach agent."""
        from backend.app.agents.outreach import OutreachAgent

        agent = OutreachAgent(batch_id=f"{self.batch_prefix}_outreach")
        result = agent.execute(**kwargs)
        self.results["outreach"] = result
        return result

    def run_learning(self, **kwargs) -> AgentResult:
        """Run learning agent to analyze engagement outcomes and refine scoring."""
        from backend.app.agents.learning import LearningAgent

        agent = LearningAgent(batch_id=f"{self.batch_prefix}_learning")
        result = agent.execute(**kwargs)
        self.results["learning"] = result
        return result

    def _print_summary(self):
        """Print a summary table of all pipeline results."""
        console.print("\n")
        table = Table(title="Pipeline Summary", show_lines=True)
        table.add_column("Agent", style="bold")
        table.add_column("Processed", justify="right")
        table.add_column("Skipped", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("Duration", justify="right")
        table.add_column("Cost", justify="right")
        table.add_column("Status")

        total_cost = 0.0
        total_duration = 0.0

        for name, result in self.results.items():
            status = "[green]OK[/green]" if result.success else "[red]FAILED[/red]"
            table.add_row(
                name,
                str(result.processed),
                str(result.skipped),
                str(result.errors),
                f"{result.duration_seconds:.1f}s",
                f"${result.total_cost_usd:.4f}",
                status,
            )
            total_cost += result.total_cost_usd
            total_duration += result.duration_seconds

        table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            "",
            "",
            f"[bold]{total_duration:.1f}s[/bold]",
            f"[bold]${total_cost:.4f}[/bold]",
            "",
        )

        console.print(table)
