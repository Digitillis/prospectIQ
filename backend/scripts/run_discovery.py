"""CLI runner for the Discovery Agent.

Searches Apollo for manufacturing prospects matching the ICP.
"""

import logging
from typing import Optional

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = typer.Typer(help="Run the ProspectIQ Discovery Agent.")


@app.command()
def main(
    max_pages: int = typer.Option(5, "--max-pages", help="Max Apollo pages per tier to fetch."),
    campaign: Optional[str] = typer.Option(None, "--campaign", help="Campaign name to tag discovered records."),
    tiers: Optional[list[str]] = typer.Option(None, "--tiers", help="Specific tiers to search (repeatable)."),
) -> None:
    """Discover manufacturing prospects from Apollo matching the ICP."""
    from backend.app.agents.discovery import DiscoveryAgent

    agent = DiscoveryAgent()
    result = agent.execute(max_pages=max_pages, campaign_name=campaign, tiers=tiers)

    print(f"\nDiscovery complete: {result.summary()}")
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
