"""Bounce hygiene agent — daily reconciliation of bounced drafts to suppression.

Wraps :func:`backend.app.core.bounce_suppressor.run_bounce_suppression` with
the ``PipelineMonitor`` lifecycle so the daily run shows up in the standard
pipeline_runs / pipeline_errors tables alongside research, qualification,
enrichment, etc.

Usage:
    from backend.app.agents.bounce_hygiene import BounceHygieneAgent

    BounceHygieneAgent(workspace_id=ws_id).run()
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.agents.monitoring import PipelineMonitor
from backend.app.core.bounce_suppressor import run_bounce_suppression
from backend.app.core.database import Database

logger = logging.getLogger(__name__)


class BounceHygieneAgent:
    """Reconcile ``outreach_drafts.bounced_at`` with contact + DNC tables."""

    def __init__(self, workspace_id: str | None = None):
        self.workspace_id = workspace_id

    def run(self) -> dict[str, Any]:
        db = Database(workspace_id=self.workspace_id)
        monitor = PipelineMonitor(agent="bounce_hygiene", workspace_id=self.workspace_id)
        monitor.start(meta={"workspace_id": self.workspace_id})

        try:
            summary = run_bounce_suppression(db)
            monitor.finish(
                processed=summary.get("contacts_suppressed", 0)
                + summary.get("domains_suppressed", 0),
                skipped=summary.get("already_suppressed", 0),
                errors=len(summary.get("errors") or []),
                meta=summary,
            )
            return summary
        except Exception as exc:
            logger.error("BounceHygieneAgent failed for workspace %s: %s", self.workspace_id, exc)
            monitor.fail(str(exc))
            raise
