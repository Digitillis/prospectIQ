"""Monitoring Agent — Pipeline observability, error tracking, and health snapshots.

Records pipeline run start/finish, individual errors, API costs, and periodic
health snapshots. Designed to be called at the start and end of every agent run
so you have full visibility into the pipeline without tail-ing log files.

Usage in any script:
    from backend.app.agents.monitoring import PipelineMonitor

    monitor = PipelineMonitor(agent="research", batch_id="wave1_mfg1")
    run_id = monitor.start(meta={"tiers": ["mfg1"], "limit": 200})

    try:
        # ... do work ...
        monitor.finish(processed=50, skipped=3, errors=0, cost_usd=0.65)
    except Exception as e:
        monitor.fail(str(e))
        raise
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import Database

logger = logging.getLogger(__name__)


class PipelineMonitor:
    """Lightweight run logger for ProspectIQ pipeline agents."""

    def __init__(self, agent: str, batch_id: str | None = None, workspace_id: str | None = None):
        self.agent = agent
        self.batch_id = batch_id
        self.workspace_id = workspace_id
        self.run_id: str | None = None
        self._db: Database | None = None

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database(workspace_id=self.workspace_id)
        return self._db

    def start(self, meta: dict[str, Any] | None = None) -> str | None:
        """Record that a pipeline run has started. Returns the run_id."""
        try:
            result = (
                self.db.client.table("pipeline_runs")
                .insert({
                    "agent": self.agent,
                    "batch_id": self.batch_id,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "status": "running",
                    "meta": meta or {},
                })
                .execute()
            )
            if result.data:
                self.run_id = result.data[0]["id"]
                logger.debug(f"[Monitor] Run started: {self.run_id} ({self.agent})")
            return self.run_id
        except Exception as e:
            logger.warning(f"[Monitor] Could not record run start: {e}")
            return None

    def finish(
        self,
        processed: int = 0,
        skipped: int = 0,
        errors: int = 0,
        cost_usd: float | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Record successful (or partial) completion of a run."""
        if not self.run_id:
            return
        status = "completed" if errors == 0 else "partial"
        try:
            update: dict[str, Any] = {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "processed": processed,
                "skipped": skipped,
                "errors": errors,
            }
            if cost_usd is not None:
                update["cost_usd"] = round(cost_usd, 4)
            if meta:
                update["meta"] = meta

            self.db.client.table("pipeline_runs").update(update).eq("id", self.run_id).execute()
            logger.debug(f"[Monitor] Run finished: {self.run_id} ({status})")
        except Exception as e:
            logger.warning(f"[Monitor] Could not record run finish: {e}")

    def fail(self, error_msg: str) -> None:
        """Record a catastrophic failure (exception that stopped the run)."""
        if not self.run_id:
            return
        try:
            self.db.client.table("pipeline_runs").update({
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "error_detail": error_msg[:2000],
            }).eq("id", self.run_id).execute()
        except Exception as e:
            logger.warning(f"[Monitor] Could not record run failure: {e}")

    def log_error(
        self,
        error_msg: str,
        company_id: str | None = None,
        error_type: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        """Record an individual company-level error during a run."""
        try:
            self.db.client.table("pipeline_errors").insert({
                "run_id": self.run_id,
                "agent": self.agent,
                "company_id": company_id,
                "error_type": error_type or "unknown",
                "error_msg": error_msg[:2000],
                "stack_trace": traceback.format_exc() if exc else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"[Monitor] Could not log error: {e}")

    def update_progress(self, processed: int, errors: int, cost_usd: float | None = None) -> None:
        """Mid-run progress update (optional — useful for long batches)."""
        if not self.run_id:
            return
        try:
            update: dict[str, Any] = {"processed": processed, "errors": errors}
            if cost_usd is not None:
                update["cost_usd"] = round(cost_usd, 4)
            self.db.client.table("pipeline_runs").update(update).eq("id", self.run_id).execute()
        except Exception as e:
            logger.warning(f"[Monitor] Could not update progress: {e}")


class HealthSnapshotAgent:
    """Captures a full system health snapshot and writes it to health_snapshots.

    Intended to run every 15–30 minutes (via APScheduler or cron).
    Provides the data source for a monitoring dashboard.
    """

    def __init__(self, workspace_id: str | None = None):
        self.workspace_id = workspace_id
        self._db: Database | None = None

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database(workspace_id=self.workspace_id)
        return self._db

    def capture(self) -> dict[str, Any]:
        """Take a full pipeline health snapshot and persist it."""
        from backend.app.core.config import get_settings
        settings = get_settings()

        snapshot: dict[str, Any] = {
            "send_enabled": settings.send_enabled,
        }

        try:
            # Company counts
            total = self.db.client.table("companies").select("id", count="exact").execute()
            snapshot["companies_total"] = total.count or 0

            researched = (
                self.db.client.table("companies")
                .select("id", count="exact")
                .eq("status", "researched")
                .execute()
            )
            snapshot["companies_researched"] = researched.count or 0

            qualified = (
                self.db.client.table("companies")
                .select("id", count="exact")
                .in_("status", ["qualified", "high_priority", "hot_prospect"])
                .execute()
            )
            snapshot["companies_qualified"] = qualified.count or 0

            # Contact enrichment
            enriched = (
                self.db.client.table("contacts")
                .select("id", count="exact")
                .eq("enrichment_status", "enriched")
                .execute()
            )
            snapshot["contacts_enriched"] = enriched.count or 0

            # Draft counts
            pending = (
                self.db.client.table("outreach_drafts")
                .select("id", count="exact")
                .eq("approval_status", "pending")
                .execute()
            )
            snapshot["drafts_pending"] = pending.count or 0

            approved = (
                self.db.client.table("outreach_drafts")
                .select("id", count="exact")
                .in_("approval_status", ["approved", "edited"])
                .is_("sent_at", "null")
                .execute()
            )
            snapshot["drafts_approved"] = approved.count or 0

            sent = (
                self.db.client.table("outreach_drafts")
                .select("id", count="exact")
                .not_.is_("sent_at", "null")
                .execute()
            )
            snapshot["drafts_sent"] = sent.count or 0

            # API cost total
            try:
                costs = self.db.client.table("api_costs").select("cost_usd").execute()
                total_cost = sum(
                    float(r.get("cost_usd") or 0) for r in (costs.data or [])
                )
                snapshot["total_cost_usd"] = round(total_cost, 4)
            except Exception:
                snapshot["total_cost_usd"] = None

            # Last research activity
            try:
                last_run = (
                    self.db.client.table("pipeline_runs")
                    .select("started_at, status")
                    .eq("agent", "research")
                    .order("started_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if last_run.data:
                    snapshot["last_research_at"] = last_run.data[0]["started_at"]
                    snapshot["research_running"] = last_run.data[0]["status"] == "running"
                else:
                    snapshot["last_research_at"] = None
                    snapshot["research_running"] = False
            except Exception:
                snapshot["research_running"] = False
                snapshot["last_research_at"] = None

            # Error count in last 24h
            try:
                from datetime import timedelta
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                errors = (
                    self.db.client.table("pipeline_errors")
                    .select("id", count="exact")
                    .gte("occurred_at", cutoff)
                    .execute()
                )
                snapshot["error_count_24h"] = errors.count or 0

                last_error = (
                    self.db.client.table("pipeline_errors")
                    .select("occurred_at")
                    .order("occurred_at", desc=True)
                    .limit(1)
                    .execute()
                )
                snapshot["last_error_at"] = last_error.data[0]["occurred_at"] if last_error.data else None
            except Exception:
                snapshot["error_count_24h"] = 0
                snapshot["last_error_at"] = None

        except Exception as e:
            logger.error(f"[HealthSnapshot] Error capturing metrics: {e}")
            snapshot["meta"] = {"capture_error": str(e)}

        # Persist
        try:
            self.db.client.table("health_snapshots").insert(snapshot).execute()
            logger.info(f"[HealthSnapshot] Captured: {snapshot.get('companies_total')} companies, "
                        f"${snapshot.get('total_cost_usd', 0)} spent, "
                        f"{snapshot.get('drafts_approved', 0)} drafts staged")
        except Exception as e:
            logger.error(f"[HealthSnapshot] Could not persist snapshot: {e}")

        return snapshot
