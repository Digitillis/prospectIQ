"""CLI runner for the Outreach Agent.

Generates personalized outreach message drafts using Claude,
based on research intelligence and sequence configuration.
"""

import logging
from typing import Optional

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = typer.Typer(help="Run the ProspectIQ Outreach Agent.")


@app.command()
def main(
    company_ids: Optional[list[str]] = typer.Option(None, "--company-ids", help="Specific company IDs for outreach (repeatable)."),
    sequence: str = typer.Option("initial_outreach", "--sequence", help="Outreach sequence name."),
    step: int = typer.Option(1, "--step", help="Step number within the sequence."),
    limit: int = typer.Option(20, "--limit", help="Max companies to generate outreach for."),
) -> None:
    """Generate personalized outreach drafts for qualified companies."""
    from backend.app.agents.outreach import OutreachAgent

    agent = OutreachAgent()
    result = agent.execute(
        company_ids=company_ids,
        sequence_name=sequence,
        sequence_step=step,
        limit=limit,
    )

    print(f"\nOutreach complete: {result.summary()}")
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
