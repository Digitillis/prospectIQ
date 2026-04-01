"""CLI runner for the Enrichment Agent.

Enriches contacts at qualified companies via Apollo People Match.
Only enriches top-priority contact per company to conserve Apollo credits.
"""

import logging
from typing import Optional

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = typer.Typer(help="Run the ProspectIQ Enrichment Agent.")


@app.command()
def main(
    company_ids: Optional[list[str]] = typer.Option(None, "--company-ids", help="Specific company IDs to enrich (repeatable)."),
    limit: int = typer.Option(25, "--limit", help="Max companies to enrich in this batch."),
    include_phone: bool = typer.Option(False, "--include-phone", help="Request phone numbers (uses async webhook)."),
) -> None:
    """Enrich contacts at qualified companies via Apollo People Match."""
    from backend.app.agents.enrichment import EnrichmentAgent

    agent = EnrichmentAgent()
    result = agent.execute(company_ids=company_ids, limit=limit, include_phone=include_phone)

    print(f"\nEnrichment complete: {result.summary()}")
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
