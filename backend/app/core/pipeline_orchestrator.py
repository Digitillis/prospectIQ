"""Pipeline Orchestrator — event-driven, lead-time-aware autonomous pipeline manager.

The orchestrator is the brain of the autonomous pipeline. It replaces fixed-schedule
cron discovery with a continuous state machine that asks one question on every tick:

    "Given current pipeline depth, send velocity, and stage lead times,
     what needs to happen right now to ensure Avanish always has approved
     drafts ready to send?"

Stage lead times (conservative estimates):
    Discovery → Qualified:       2–4 hours  (research + qualification runs)
    Qualified → Enriched:        up to 12 hours (enrichment runs 2× daily)
    Enriched → Draft + Approved: 24–48 hours (Claude draft + your review)
    Total pipeline lead time:    3 days

The orchestrator is called from three sites:
    1. Heartbeat every 4 hours — backstop for any missed events
    2. After each send batch — "we consumed capacity, do we need more?"
    3. After reply intake processes replies — for learning signal + pause accounting

All decisions are workspace-scoped. Calling advance() is idempotent — if the
pipeline is healthy it logs that and exits immediately.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Conservative estimate: fraction of discovered companies that reach outreach_pending
# (discovery → qualification ~60% pass, → enrichment ~80% contactable, → draft ~90%)
# 0.60 * 0.80 * 0.90 ≈ 0.43 → use 0.35 for safety margin
DISCOVERY_YIELD_RATE = 0.35

# Number of days of pipeline capacity to maintain ahead of sends
LEAD_TIME_DAYS = 3

# Trigger a learning run after this many new replies since last run
LEARNING_MIN_REPLIES = 10

# Maximum Apollo pages per discovery run (prevents runaway credit spend)
MAX_DISCOVERY_PAGES_PER_RUN = 10

# F&B and mfg tier lists — centralized here so orchestrator owns routing
FB_TIERS = ["fb_dairy", "fb_bev", "fb_seafood", "fb_meat", "fb_produce", "fb_bakery"]
MFG_TIERS = ["mfg1", "mfg2", "mfg3", "pmfg1"]


class PipelineOrchestrator:
    """Evaluates pipeline state and fires discovery + learning when needed.

    Usage:
        orchestrator = PipelineOrchestrator(workspace_id)
        result = orchestrator.advance()
        # result["pipeline_status"] has the current state
        # result["actions"] lists what was triggered
    """

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def advance(self) -> dict:
        """Evaluate pipeline state and trigger agents if needed. Idempotent."""
        from backend.app.core.database import Database

        db = Database(workspace_id=self.workspace_id)
        actions: list[str] = []

        # Learning trigger runs first — it's cheap (just a count query)
        if self._should_run_learning(db):
            actions.append(self._run_learning())

        # Pipeline depth check
        status = self._compute_status(db)

        logger.info(
            "Pipeline [%s]: pending=%d in_flight=%d effective=%d watermark=%d days_left=%.1f needs_discovery=%s",
            self.workspace_id,
            status["outreach_pending"],
            status["in_flight"],
            status["effective_depth"],
            status["watermark"],
            status["days_remaining"],
            status["needs_discovery"],
        )

        if status["needs_discovery"]:
            actions.extend(self._run_discovery(status, db))

        return {"actions": actions, "pipeline_status": status}

    def get_status(self) -> dict:
        """Return pipeline health snapshot without triggering any agents."""
        from backend.app.core.database import Database

        return self._compute_status(Database(workspace_id=self.workspace_id))

    # ------------------------------------------------------------------
    # Pipeline state
    # ------------------------------------------------------------------

    def _compute_status(self, db) -> dict:
        from backend.app.core.workspace_scheduler import get_total_daily_capacity

        capacity = get_total_daily_capacity(self.workspace_id)
        watermark = capacity * LEAD_TIME_DAYS

        outreach_pending = db.count_companies(status="outreach_pending")
        qualified = db.count_companies(status="qualified")
        enriched_not_drafted = self._count_enriched_not_drafted(db)

        in_flight = qualified + enriched_not_drafted
        effective_depth = outreach_pending + in_flight
        shortage = max(0, watermark - effective_depth)

        # Pages needed: shortage / yield_rate = discovered companies needed
        # Each Apollo page returns ~10 companies → divide by 10
        discovery_companies_needed = int(shortage / DISCOVERY_YIELD_RATE) if shortage > 0 else 0
        pages_needed = max(1, int(discovery_companies_needed / 10))

        days_remaining = round(outreach_pending / capacity, 1) if capacity > 0 else 999.0

        return {
            "capacity_per_day": capacity,
            "watermark": int(watermark),
            "outreach_pending": outreach_pending,
            "qualified": qualified,
            "enriched_not_drafted": enriched_not_drafted,
            "in_flight": in_flight,
            "effective_depth": effective_depth,
            "shortage": shortage,
            "days_remaining": days_remaining,
            "needs_discovery": shortage > 0,
            "discovery_target_companies": discovery_companies_needed,
            "discovery_pages_needed": min(pages_needed, MAX_DISCOVERY_PAGES_PER_RUN),
        }

    def _count_enriched_not_drafted(self, db) -> int:
        """Count companies that have enriched contacts but no pending outreach draft."""
        try:
            # Contacts with emails in this workspace
            enriched_rows = (
                db.client.table("contacts")
                .select("company_id")
                .eq("workspace_id", self.workspace_id)
                .not_.is_("email", "null")
                .neq("email", "")
                .execute()
            ).data or []

            if not enriched_rows:
                return 0

            company_ids = list({r["company_id"] for r in enriched_rows if r.get("company_id")})
            if not company_ids:
                return 0

            # Batch in chunks of 50 to stay within Supabase in() limits
            drafted_ids: set[str] = set()
            for i in range(0, len(company_ids), 50):
                chunk = company_ids[i:i + 50]
                drafted_rows = (
                    db.client.table("outreach_drafts")
                    .select("company_id")
                    .eq("workspace_id", self.workspace_id)
                    .in_("approval_status", ["pending", "approved", "sent"])
                    .in_("company_id", chunk)
                    .execute()
                ).data or []
                drafted_ids.update(r["company_id"] for r in drafted_rows if r.get("company_id"))

            return len([cid for cid in company_ids if cid not in drafted_ids])
        except Exception as exc:
            logger.warning("_count_enriched_not_drafted failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Learning trigger
    # ------------------------------------------------------------------

    def _should_run_learning(self, db) -> bool:
        """Return True if enough new replies have accumulated since last learning run."""
        try:
            ws_rows = (
                db.client.table("workspaces")
                .select("settings")
                .eq("id", self.workspace_id)
                .limit(1)
                .execute()
            ).data
            settings = (ws_rows[0].get("settings") or {}) if ws_rows else {}
            last_learning_at = settings.get("last_learning_at")

            q = (
                db.client.table("interactions")
                .select("id", count="exact")
                .eq("workspace_id", self.workspace_id)
                .eq("type", "email_replied")
            )
            if last_learning_at:
                q = q.gte("created_at", last_learning_at)

            count = (q.execute()).count or 0
            if count >= LEARNING_MIN_REPLIES:
                logger.info(
                    "Learning trigger: %d new replies since last run (threshold=%d)",
                    count, LEARNING_MIN_REPLIES,
                )
                return True
            return False
        except Exception as exc:
            logger.warning("Learning trigger check failed: %s", exc)
            return False

    def _run_learning(self) -> str:
        from backend.app.agents.learning import LearningAgent
        from backend.app.core.database import Database

        try:
            auto_apply = os.environ.get("LEARNING_AUTO_APPLY", "false").lower() == "true"
            db = Database(workspace_id=self.workspace_id)
            result = LearningAgent(db=db).run(period_days=30, auto_apply=auto_apply)

            # Stamp last_learning_at in workspace settings
            now_iso = datetime.now(timezone.utc).isoformat()
            ws_rows = (
                db.client.table("workspaces")
                .select("settings")
                .eq("id", self.workspace_id)
                .limit(1)
                .execute()
            ).data
            settings = (ws_rows[0].get("settings") or {}) if ws_rows else {}
            settings["last_learning_at"] = now_iso
            db.client.table("workspaces").update({"settings": settings}).eq(
                "id", self.workspace_id
            ).execute()

            msg = f"learning: {result.processed} outcomes analysed (auto_apply={auto_apply})"
            logger.info("Pipeline [%s]: %s", self.workspace_id, msg)
            return msg
        except Exception as exc:
            logger.error("Orchestrator: learning failed: %s", exc, exc_info=True)
            return f"learning: failed ({exc})"

    # ------------------------------------------------------------------
    # Discovery trigger
    # ------------------------------------------------------------------

    def _run_discovery(self, status: dict, db) -> list[str]:
        from backend.app.agents.discovery import DiscoveryAgent
        from backend.app.core.database import Database
        from backend.app.core.workspace_scheduler import workspace_budget_ok

        ws_rows = (
            db.client.table("workspaces")
            .select("*")
            .eq("id", self.workspace_id)
            .limit(1)
            .execute()
        ).data
        if not ws_rows:
            return ["discovery: workspace not found"]
        workspace = ws_rows[0]

        if not workspace_budget_ok(workspace, "pipeline_discovery"):
            return ["discovery: budget limit reached"]

        max_pages = status["discovery_pages_needed"]
        actions: list[str] = []

        for campaign_name, tiers, label in [
            ("fsma204-fb", FB_TIERS, "fb"),
            ("mfg-fsma", MFG_TIERS, "mfg"),
        ]:
            try:
                agent = DiscoveryAgent(db=Database(workspace_id=self.workspace_id))
                result = agent.run(
                    campaign_name=campaign_name,
                    tiers=tiers,
                    max_pages=max_pages,
                )
                msg = (
                    f"{label}_discovery: {result.processed} found, "
                    f"{result.skipped} skipped (pages={max_pages})"
                )
                logger.info("Pipeline [%s]: %s", self.workspace_id, msg)
                actions.append(msg)
            except Exception as exc:
                logger.error("Orchestrator: %s discovery failed: %s", label, exc, exc_info=True)
                actions.append(f"{label}_discovery: failed ({exc})")

        return actions
