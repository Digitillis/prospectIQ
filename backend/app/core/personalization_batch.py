"""Personalization Batch Runner.

Runs PersonalizationEngine.run_full_pipeline() over a filtered set of
companies that have research and meet a minimum PQS threshold.

Usage:
    runner = PersonalizationBatch(workspace_id="...")
    result = runner.run_batch(filters={"cluster": "automotive"}, max_companies=50)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.core.database import Database
from backend.app.core.personalization_engine import PersonalizationEngine
from backend.app.core.personalization_models import BatchResult

logger = logging.getLogger(__name__)

_DEFAULT_MIN_PQS = 50
_DEFAULT_MAX_COMPANIES = 50


class PersonalizationBatch:
    """Batch runner that applies PersonalizationEngine across multiple companies."""

    def __init__(self, workspace_id: str | None = None):
        self.db = Database(workspace_id=None)
        self.workspace_id = workspace_id

    def run_batch(
        self,
        filters: dict[str, Any] | None = None,
        max_companies: int = _DEFAULT_MAX_COMPANIES,
    ) -> BatchResult:
        """Run personalization for up to max_companies qualified companies.

        Args:
            filters: Optional dict with keys: cluster, tranche, min_pqs
            max_companies: Hard cap on companies processed in this run

        Returns:
            BatchResult with aggregate stats
        """
        filters = filters or {}
        min_pqs = int(filters.get("min_pqs", _DEFAULT_MIN_PQS))
        cluster = filters.get("cluster")
        tranche = filters.get("tranche")

        companies = self._fetch_eligible_companies(
            min_pqs=min_pqs,
            cluster=cluster,
            tranche=tranche,
            limit=max_companies,
        )

        result = BatchResult()
        total_score = 0.0

        for company in companies:
            company_id = company["id"]
            company_name = company.get("name", company_id)
            try:
                engine = PersonalizationEngine(workspace_id=self.workspace_id)
                pr = engine.run_full_pipeline(
                    company_id=company_id,
                    workspace_id=self.workspace_id,
                )
                result.processed += 1
                result.updated += 1
                result.total_cost_usd += pr.cost_usd
                total_score += pr.readiness_score
                logger.info(
                    f"Personalized {company_name}: score={pr.readiness_score}, "
                    f"triggers={len(pr.triggers)}, hooks={len(pr.hooks)}"
                )
            except Exception as e:
                result.errors += 1
                result.error_details.append({"company_id": company_id, "error": str(e)[:200]})
                logger.error(f"Personalization failed for {company_name}: {e}")

        if result.processed > 0:
            result.avg_readiness_score = round(total_score / result.processed, 1)

        result.total_cost_usd = round(result.total_cost_usd, 6)
        return result

    def _fetch_eligible_companies(
        self,
        min_pqs: int,
        cluster: str | None,
        tranche: str | None,
        limit: int,
    ) -> list[dict]:
        """Fetch companies that have research and meet min PQS threshold.

        Filters out companies whose personalization has been run in the last 7 days
        to avoid redundant re-runs.
        """
        from datetime import datetime, timezone, timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Base query: researched companies with sufficient PQS
        query = (
            self.db.client.table("companies")
            .select("id, name, pqs_total, campaign_cluster, tier, custom_tags")
            .not_.is_("research_summary", "null")
            .gte("pqs_total", min_pqs)
        )

        if cluster:
            query = query.eq("campaign_cluster", cluster)
        if tranche:
            query = query.eq("tier", tranche)

        rows = query.order("pqs_total", desc=True).limit(limit * 3).execute().data

        # Filter in Python: skip companies personalized within last 7 days
        eligible = []
        for row in rows:
            tags = row.get("custom_tags") or {}
            if isinstance(tags, str):
                import json
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = {}
            last_run = tags.get("personalization_last_run")
            if last_run and last_run > cutoff:
                continue
            eligible.append(row)
            if len(eligible) >= limit:
                break

        return eligible
