"""CLI runner for the Qualification Agent.

Scores and qualifies companies using the rule-based PQS framework.
"""

import logging
from typing import Optional

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = typer.Typer(help="Run the ProspectIQ Qualification Agent.")


@app.command()
def main(
    company_ids: Optional[list[str]] = typer.Option(None, "--company-ids", help="Specific company IDs to qualify (repeatable)."),
    limit: int = typer.Option(100, "--limit", help="Max companies to qualify in this batch."),
) -> None:
    """Score and qualify researched companies using PQS."""
    from backend.app.agents.qualification import QualificationAgent

    agent = QualificationAgent()
    result = agent.execute(company_ids=company_ids, limit=limit)

    print(f"\nQualification complete: {result.summary()}")
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
