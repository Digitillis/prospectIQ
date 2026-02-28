"""CLI runner for the Research Agent.

Deep-researches companies using Perplexity + Claude to populate
research intelligence and update company records.
"""

import logging
from typing import Optional

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = typer.Typer(help="Run the ProspectIQ Research Agent.")


@app.command()
def main(
    company_ids: Optional[list[str]] = typer.Option(None, "--company-ids", help="Specific company IDs to research (repeatable)."),
    batch_id: Optional[str] = typer.Option(None, "--batch-id", help="Research all companies tagged with this batch ID (from select_batch)."),
    min_score: Optional[int] = typer.Option(None, "--min-score", help="Minimum firmographic PQS to select companies."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max companies to research in this batch."),
) -> None:
    """Run deep research on discovered companies."""
    from backend.app.agents.research import ResearchAgent

    agent = ResearchAgent()
    result = agent.execute(company_ids=company_ids, batch_id=batch_id, min_firmographic_score=min_score, limit=limit)

    print(f"\nResearch complete: {result.summary()}")
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
