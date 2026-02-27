"""CLI runner for the full ProspectIQ pipeline.

Runs discovery -> research -> qualification -> outreach in sequence.
If any agent fails, the pipeline stops and reports the failure.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

console = Console()
app = typer.Typer(help="Run the full ProspectIQ pipeline (discovery -> research -> qualification -> outreach).")


@app.command()
def main(
    max_pages: int = typer.Option(3, "--max-pages", help="Max Apollo pages per tier for discovery."),
    campaign: Optional[str] = typer.Option(None, "--campaign", help="Campaign name for the pipeline run."),
    skip_outreach: bool = typer.Option(False, "--skip-outreach", help="Skip the outreach step."),
) -> None:
    """Run the full ProspectIQ pipeline end-to-end."""
    from backend.app.agents.discovery import DiscoveryAgent
    from backend.app.agents.research import ResearchAgent
    from backend.app.agents.qualification import QualificationAgent
    from backend.app.agents.outreach import OutreachAgent

    batch_prefix = f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    pipeline_start = time.time()

    console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
    console.print(f"[bold magenta]ProspectIQ Full Pipeline[/bold magenta]")
    console.print(f"[bold magenta]Batch prefix: {batch_prefix}[/bold magenta]")
    console.print(f"[bold magenta]{'='*60}[/bold magenta]\n")

    results: dict[str, object] = {}

    # --- Stage 1: Discovery ---
    console.print("[bold cyan]Stage 1/4: Discovery[/bold cyan]")
    discovery = DiscoveryAgent(batch_id=f"{batch_prefix}_discovery")
    results["discovery"] = discovery.execute(max_pages=max_pages, campaign_name=campaign)

    if not results["discovery"].success:
        console.print("[bold red]Discovery failed. Pipeline stopped.[/bold red]")
        _print_pipeline_summary(results, pipeline_start)
        raise typer.Exit(code=1)

    # --- Stage 2: Research ---
    console.print("[bold cyan]Stage 2/4: Research[/bold cyan]")
    research = ResearchAgent(batch_id=f"{batch_prefix}_research")
    results["research"] = research.execute()

    if not results["research"].success:
        console.print("[bold red]Research failed. Pipeline stopped.[/bold red]")
        _print_pipeline_summary(results, pipeline_start)
        raise typer.Exit(code=1)

    # --- Stage 3: Qualification ---
    console.print("[bold cyan]Stage 3/4: Qualification[/bold cyan]")
    qualification = QualificationAgent(batch_id=f"{batch_prefix}_qualification")
    results["qualification"] = qualification.execute()

    if not results["qualification"].success:
        console.print("[bold red]Qualification failed. Pipeline stopped.[/bold red]")
        _print_pipeline_summary(results, pipeline_start)
        raise typer.Exit(code=1)

    # --- Stage 4: Outreach ---
    if skip_outreach:
        console.print("[yellow]Stage 4/4: Outreach — SKIPPED (--skip-outreach)[/yellow]")
    else:
        console.print("[bold cyan]Stage 4/4: Outreach[/bold cyan]")
        outreach = OutreachAgent(batch_id=f"{batch_prefix}_outreach")
        results["outreach"] = outreach.execute()

        if not results["outreach"].success:
            console.print("[bold red]Outreach failed.[/bold red]")
            _print_pipeline_summary(results, pipeline_start)
            raise typer.Exit(code=1)

    _print_pipeline_summary(results, pipeline_start)


def _print_pipeline_summary(results: dict, pipeline_start: float) -> None:
    """Print a summary table of all pipeline stages."""
    total_duration = round(time.time() - pipeline_start, 2)
    total_cost = sum(r.total_cost_usd for r in results.values())

    console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
    console.print("[bold magenta]Pipeline Summary[/bold magenta]")
    console.print(f"[bold magenta]{'='*60}[/bold magenta]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Processed", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Duration (s)", justify="right")
    table.add_column("Cost ($)", justify="right")

    for stage_name, result in results.items():
        status = "[green]OK[/green]" if result.success else "[red]FAILED[/red]"
        table.add_row(
            stage_name,
            status,
            str(result.processed),
            str(result.skipped),
            str(result.errors),
            f"{result.duration_seconds:.1f}",
            f"{result.total_cost_usd:.4f}",
        )

    console.print(table)
    console.print(f"\n[bold]Total duration: {total_duration:.1f}s | Total cost: ${total_cost:.4f}[/bold]\n")


if __name__ == "__main__":
    app()
