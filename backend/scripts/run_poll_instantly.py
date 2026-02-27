"""CLI runner for polling Instantly.ai lead events.

Fetches opens, clicks, replies, and bounces from Instantly by polling
campaign leads directly — no webhook plan required.

Intended to be run on a schedule (e.g. every 30–60 minutes via cron
or a Railway cron job) to keep ProspectIQ's engagement scores and
interaction log in sync with Instantly activity.
"""

import logging

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = typer.Typer(help="Poll Instantly.ai for new lead events and sync to ProspectIQ.")


@app.command()
def main() -> None:
    """Poll all Instantly campaigns for new opens/clicks/replies/bounces."""
    from backend.app.agents.engagement import EngagementAgent

    agent = EngagementAgent()
    result = agent.execute(action="poll_events")

    print(f"\nPoll complete: {result.summary()}")
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
