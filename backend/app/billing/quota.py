"""Quota enforcement for ProspectIQ pipeline agents.

Provides FastAPI dependencies that block agent runs when a workspace has
exceeded its monthly company research quota for the current tier.

Usage in route handlers:
    @router.post("/run/research")
    async def run_research(
        body: ResearchRequest,
        _quota: None = Depends(require_quota("research")),
    ):
        ...

The dependency raises HTTP 402 when the quota is exceeded, with a clear
message telling the operator which limit was hit and how to upgrade.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, status

from backend.app.core.auth import require_workspace_member
from backend.app.core.database import get_supabase_client
from backend.app.core.workspace import WorkspaceContext

logger = logging.getLogger(__name__)

# Quota action types — each maps to a cost-incurring operation
QuotaAction = Literal["research", "enrichment", "outreach", "discovery"]

# Companies-per-month limits per tier — must match billing_core/tier_plans.py
_TIER_LIMITS: dict[str, int] = {
    "starter": 500,
    "growth": 2000,
    "scale": 10000,
    "api": 50000,
}

# Statuses that allow continued usage
_ACTIVE_STATUSES = {"active", "trialing"}


def _count_companies_this_month(workspace_id: str) -> int:
    """Count companies added to this workspace since the start of the current month."""
    client = get_supabase_client()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        result = (
            client.table("companies")
            .select("id", count="exact")
            .eq("workspace_id", workspace_id)
            .gte("created_at", month_start)
            .execute()
        )
        return result.count or 0
    except Exception as exc:
        logger.warning("quota: failed to count companies for %s: %s", workspace_id, exc)
        return 0


def require_quota(action: QuotaAction = "research"):
    """FastAPI dependency factory: enforce the workspace's monthly company quota.

    Raises HTTP 402 when:
    - The subscription is canceled or past_due
    - The workspace has exceeded its monthly company limit

    API key callers (non-billing auth) are allowed through — quota is only
    enforced for dashboard sessions where a workspace tier is known.
    """
    async def _check(ctx: WorkspaceContext = Depends(require_workspace_member)) -> None:
        # Subscription status gate
        if ctx.subscription_status not in _ACTIVE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Your subscription is {ctx.subscription_status}. "
                    "Please update your billing details to continue using ProspectIQ."
                ),
            )

        # Company quota gate — only applies to research/enrichment/discovery
        if action in ("research", "enrichment", "discovery"):
            tier_limit = _TIER_LIMITS.get(ctx.tier, 500)
            used = _count_companies_this_month(ctx.workspace_id)
            if used >= tier_limit:
                tier_label = ctx.tier.capitalize()
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Monthly company limit reached: {used}/{tier_limit} "
                        f"companies researched on your {tier_label} plan. "
                        "Upgrade to continue or wait until next billing cycle."
                    ),
                )

    return _check
