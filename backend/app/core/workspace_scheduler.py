"""Workspace-aware scheduler helpers.

Provides a pattern for running background jobs across all active workspaces
so the platform can serve multiple clients without data leakage between them.

Usage in scheduler jobs:
    from backend.app.core.workspace_scheduler import for_each_workspace

    def _run_enrichment() -> None:
        for_each_workspace(_enrich_workspace)

    def _enrich_workspace(workspace: dict) -> None:
        from backend.app.agents.enrichment import EnrichmentAgent
        agent = EnrichmentAgent(workspace_id=workspace["id"])
        agent.run(limit=100)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def get_active_workspaces() -> list[dict[str, Any]]:
    """Return all workspaces whose subscription is active or trialing."""
    try:
        from backend.app.core.database import get_supabase_client
        result = (
            get_supabase_client()
            .table("workspaces")
            .select("id, name, owner_email, tier, subscription_status, settings")
            .in_("subscription_status", ["active", "trialing"])
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.error("get_active_workspaces failed: %s", exc)
        return []


def for_each_workspace(
    fn: Callable[[dict[str, Any]], None],
    job_name: str = "unknown",
) -> None:
    """Call fn(workspace) for each active workspace, isolating errors per workspace.

    Sets WorkspaceContext for each iteration so DB helpers and credential
    lookups automatically scope to the correct workspace.
    """
    workspaces = get_active_workspaces()
    if not workspaces:
        logger.warning("%s: no active workspaces found — skipping", job_name)
        return

    logger.info("%s: running for %d workspace(s)", job_name, len(workspaces))
    for ws in workspaces:
        ws_id = ws["id"]
        ws_name = ws.get("name", ws_id)
        try:
            from backend.app.core.workspace import WorkspaceContext, set_workspace_context, clear_workspace_context
            ctx = WorkspaceContext(
                workspace_id=ws_id,
                name=ws_name,
                owner_email=ws.get("owner_email", ""),
                tier=ws.get("tier", "starter"),
                subscription_status=ws.get("subscription_status", "active"),
                settings=ws.get("settings") or {},
            )
            set_workspace_context(ctx)
            fn(ws)
        except Exception as exc:
            logger.error("%s: failed for workspace %s (%s): %s", job_name, ws_name, ws_id, exc, exc_info=True)
        finally:
            try:
                clear_workspace_context()
            except Exception:
                pass


def get_workspace_monthly_spend(workspace_id: str) -> float:
    """Return total API spend for a workspace in the current calendar month.

    Paginates through all rows to avoid the 1000-row PostgREST default limit
    truncating the result for high-volume workspaces.
    """
    try:
        from backend.app.core.database import get_supabase_client
        from datetime import datetime, timezone
        client = get_supabase_client()
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        total = 0.0
        offset = 0
        while True:
            rows = (
                client.table("api_costs")
                .select("estimated_cost_usd")
                .eq("workspace_id", workspace_id)
                .gte("created_at", month_start)
                .range(offset, offset + 999)
                .execute()
            ).data or []
            total += sum(float(r.get("estimated_cost_usd") or 0) for r in rows)
            if len(rows) < 1000:
                break
            offset += 1000
        return total
    except Exception as exc:
        logger.warning("get_workspace_monthly_spend failed: %s", exc)
        return 0.0


def workspace_daily_sends_ok(workspace: dict, job_name: str = "outreach") -> bool:
    """Return True if workspace is under its daily outreach send limit.

    Limit is read from workspace.settings.daily_send_limit (default 125).
    Counts drafts with sent_at set today UTC (not approval_status, which has
    no 'sent' enum value — that caused a DB error on every check).
    Fails open on DB error.
    """
    ws_id = workspace["id"]
    settings = workspace.get("settings") or {}
    daily_limit = int(settings.get("daily_send_limit", 125))
    try:
        from backend.app.core.database import get_supabase_client
        from datetime import datetime, timezone
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        rows = (
            get_supabase_client()
            .table("outreach_drafts")
            .select("id", count="exact")
            .eq("workspace_id", ws_id)
            .not_.is_("sent_at", "null")
            .gte("sent_at", today_start)
            .execute()
        )
        today_count = rows.count or 0
        if today_count >= daily_limit:
            logger.warning(
                "%s: workspace %s daily limit reached (%d/%d) — skipping",
                job_name, workspace.get("name", ws_id), today_count, daily_limit,
            )
            return False
        return True
    except Exception as exc:
        logger.warning("workspace_daily_sends_ok check failed: %s", exc)
        return True  # Fail open — don't block sends on a check failure


def workspace_budget_ok(workspace: dict, job_name: str) -> bool:
    """Return True if this workspace is under its monthly API budget.

    Budget is read from workspace.settings.monthly_api_budget_usd (default $200).
    Sends a one-time email alert at 50% and 80% of the cap — not just when exhausted.
    """
    ws_id = workspace["id"]
    settings = workspace.get("settings") or {}
    budget = float(settings.get("monthly_api_budget_usd", 200.0))
    spend = get_workspace_monthly_spend(ws_id)

    pct = spend / budget if budget > 0 else 0.0

    # Alert at 50% and 80% — one log line per threshold crossing per check.
    # Email is best-effort; never block the job on notification failure.
    if pct >= 0.80:
        logger.warning(
            "%s: workspace %s budget at %.0f%% ($%.2f / $%.2f)",
            job_name, workspace.get("name", ws_id), pct * 100, spend, budget,
        )
        _send_budget_alert(workspace, spend, budget, pct)
    elif pct >= 0.50:
        logger.warning(
            "%s: workspace %s budget at %.0f%% ($%.2f / $%.2f)",
            job_name, workspace.get("name", ws_id), pct * 100, spend, budget,
        )

    if spend >= budget:
        logger.warning(
            "%s: workspace %s budget exhausted ($%.2f / $%.2f) — skipping",
            job_name, workspace.get("name", ws_id), spend, budget,
        )
        return False
    return True


def _send_budget_alert(workspace: dict, spend: float, budget: float, pct: float) -> None:
    """Fire a one-shot email when the workspace hits 80%+ of its monthly budget.

    Suppresses duplicate alerts: does not re-send if we already sent one this calendar hour.
    """
    try:
        from datetime import datetime, timezone
        from backend.app.core.database import get_supabase_client

        ws_id = workspace.get("id", "unknown")
        ws_name = workspace.get("name", ws_id)
        now_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

        # Cheap idempotency: skip if we already alerted this hour for this workspace
        client = get_supabase_client()
        existing = (
            client.table("api_costs")
            .select("id", count="exact")
            .eq("workspace_id", ws_id)
            .eq("provider", "budget_alert")
            .gte("created_at", now_hour + ":00:00+00:00")
            .execute()
        ).count or 0
        if existing > 0:
            return  # Already alerted this hour

        # Write a sentinel row so the next check in this hour is suppressed
        client.table("api_costs").insert({
            "workspace_id": ws_id,
            "provider": "budget_alert",
            "model": f"{pct:.0%}_threshold",
            "estimated_cost_usd": 0,
        }).execute()

        import asyncio
        from backend.app.core.notifications import send_email
        asyncio.run(send_email(
            to="avi@digitillis.io",
            subject=f"[ProspectIQ] Budget alert: {pct:.0%} of ${budget:.0f} cap used",
            html_body=(
                f"<p><strong>{ws_name}</strong> has used "
                f"<strong style='color:#d97706'>${spend:.2f}</strong> of its "
                f"<strong>${budget:.0f}/month</strong> API budget "
                f"({pct:.0%}).</p>"
                f"<p>At the current burn rate this cap will be hit before month end. "
                f"Either top up the Anthropic account or raise "
                f"<code>monthly_api_budget_usd</code> in workspace settings.</p>"
            ),
        ))
        logger.info("Budget alert email sent for workspace %s (%.0f%% of $%.0f)", ws_name, pct * 100, budget)
    except Exception as exc:
        logger.warning("_send_budget_alert failed (non-critical): %s", exc)


def research_budget_ok(workspace: dict) -> bool:
    """Return True if research-specific monthly spend is under the research cap.

    Cap is read from workspace.settings.research_monthly_budget_usd (default: no cap).
    Spend is calculated from api_costs rows whose batch_id starts with 'research'.
    """
    settings = workspace.get("settings") or {}
    cap = settings.get("research_monthly_budget_usd")
    if cap is None:
        return True  # No cap configured — allow
    cap = float(cap)
    ws_id = workspace["id"]
    try:
        from backend.app.core.database import get_supabase_client
        from datetime import datetime, timezone
        client = get_supabase_client()
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        # Paginate to avoid PostgREST 1000-row default limit silently truncating spend.
        research_spend = 0.0
        page_size = 1000
        offset = 0
        while True:
            result = (
                client.table("api_costs")
                .select("estimated_cost_usd")
                .eq("workspace_id", ws_id)
                .gte("created_at", month_start)
                .like("batch_id", "research%")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            page = result.data or []
            research_spend += sum(float(r.get("estimated_cost_usd") or 0) for r in page)
            if len(page) < page_size:
                break
            offset += page_size
        if research_spend >= cap:
            logger.warning(
                "research: workspace %s research budget exhausted ($%.2f / $%.2f) — pausing research",
                workspace.get("name", ws_id), research_spend, cap,
            )
            return False
        logger.info(
            "research: workspace %s research spend $%.2f / $%.2f",
            workspace.get("name", ws_id), research_spend, cap,
        )
        return True
    except Exception as exc:
        logger.warning("research_budget_ok check failed (%s) — blocking research (fail-closed)", exc)
        return False  # Fail CLOSED — budget checks must pass; transient DB errors block research


def get_total_daily_capacity(workspace_id: str) -> int:
    """Return total daily send capacity for a workspace.

    Sums per-account daily_limit from workspace.settings.sender_pool.
    Falls back to workspace.settings.daily_send_limit if no sender_pool defined.
    Falls back to 125 if neither is set.

    sender_pool format (stored in workspace.settings):
        [{"email": "avi@...", "daily_limit": 30, "active": true}, ...]
    """
    try:
        from backend.app.core.database import get_supabase_client
        ws = (
            get_supabase_client()
            .table("workspaces")
            .select("settings")
            .eq("id", workspace_id)
            .limit(1)
            .execute()
        ).data
        if not ws:
            return 125

        settings = ws[0].get("settings") or {}

        sender_pool = settings.get("sender_pool") or []
        if sender_pool:
            return sum(
                int(acct.get("daily_limit", 30))
                for acct in sender_pool
                if acct.get("active", True)
            )

        return int(settings.get("daily_send_limit", 125))
    except Exception as exc:
        logger.warning("get_total_daily_capacity failed: %s", exc)
        return 125


def apollo_credits_ok(workspace_id: str | None = None, min_buffer: int = 200) -> bool:
    """Return False if Apollo remaining credits are at or below min_buffer.

    Calls GET /auth/health (free, no credit cost). Fails open on any error
    so enrichment is never blocked by a transient network issue.

    Args:
        workspace_id: Used to resolve the correct Apollo API key.
        min_buffer: Halt enrichment when remaining credits fall at or below this.
                    Default 200 — keeps a safety margin for manual sessions.

    Returns:
        True if enrichment may proceed; False if credit guard triggered.
    """
    try:
        from backend.app.integrations.apollo import ApolloClient
        with ApolloClient(workspace_id=workspace_id) as apollo:
            info = apollo.get_credits()
            remaining = info.get("credits_remaining", 9999)
            used = info.get("credits_used", 0)
            limit = info.get("credit_limit", 0)
            logger.info(
                "Apollo credits: %d used / %d limit (%d remaining)",
                used, limit, remaining,
            )
            if remaining <= min_buffer:
                logger.warning(
                    "Apollo credit guard triggered: %d remaining (min_buffer=%d) — enrichment halted",
                    remaining, min_buffer,
                )
                return False
        return True
    except Exception as exc:
        logger.warning("apollo_credits_ok check failed (%s) — allowing enrichment", exc)
        return True  # Fail open
