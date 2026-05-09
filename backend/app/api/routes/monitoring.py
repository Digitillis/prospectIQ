"""Monitoring routes for ProspectIQ.

Provides pipeline health, error tracking, and run history endpoints.
Intended for the CRM dashboard monitoring tab and CLI tooling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


@router.get("/health")
async def get_health():
    """Get the most recent health snapshot.

    Returns the latest system-wide metrics captured by the 15-minute
    health snapshot job: company counts, draft counts, cost, errors.
    """
    db = get_db()
    try:
        result = (
            db._filter_ws(db.client.table("health_snapshots").select("*"))
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            # No snapshot yet — capture one now on demand
            from backend.app.agents.monitoring import HealthSnapshotAgent
            snapshot = HealthSnapshotAgent().capture()
            return {"data": snapshot, "source": "live"}

        return {"data": result.data[0], "source": "snapshot"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/history")
async def get_health_history(hours: int = Query(24, ge=1, le=168)):
    """Get health snapshots over the past N hours (default 24h, max 7 days).

    Use this to build a cost-over-time chart or pipeline throughput trend.
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        result = (
            db._filter_ws(db.client.table("health_snapshots").select("*"))
            .gte("captured_at", cutoff)
            .order("captured_at")
            .execute()
        )
        return {"data": result.data or [], "count": len(result.data or []), "hours": hours}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs")
async def list_runs(
    agent: Optional[str] = Query(None, description="Filter by agent: research | qualification | enrichment | outreach | engagement"),
    status: Optional[str] = Query(None, description="Filter by status: running | completed | failed | partial"),
    limit: int = Query(50, ge=1, le=500),
):
    """List recent pipeline runs with performance metrics.

    Shows start/finish times, processed/error counts, and cost per run.
    Useful for spotting slow batches, repeated failures, or cost spikes.
    """
    db = get_db()
    try:
        query = (
            db._filter_ws(db.client.table("pipeline_runs").select("*"))
            .order("started_at", desc=True)
            .limit(limit)
        )
        if agent:
            query = query.eq("agent", agent)
        if status:
            query = query.eq("status", status)

        result = query.execute()
        runs = result.data or []

        # Add duration_seconds for each completed run
        for run in runs:
            started = run.get("started_at")
            finished = run.get("finished_at")
            if started and finished:
                try:
                    s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                    run["duration_seconds"] = int((f - s).total_seconds())
                except Exception:
                    run["duration_seconds"] = None

        return {"data": runs, "count": len(runs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get a specific pipeline run with its errors."""
    db = get_db()
    try:
        run_result = (
            db._filter_ws(db.client.table("pipeline_runs").select("*"))
            .eq("id", run_id)
            .execute()
        )
        if not run_result.data:
            raise HTTPException(status_code=404, detail="Run not found")

        run = run_result.data[0]

        # Fetch associated errors
        errors_result = (
            db._filter_ws(db.client.table("pipeline_errors").select("*"))
            .eq("run_id", run_id)
            .order("occurred_at")
            .execute()
        )
        run["pipeline_errors"] = errors_result.data or []

        return {"data": run}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/errors")
async def list_errors(
    agent: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=500),
):
    """List recent pipeline errors.

    Default: last 24 hours, unresolved errors across all agents.
    Use resolved=false to see only open issues.
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        query = (
            db._filter_ws(
                db.client.table("pipeline_errors").select("*, companies(name, tier)")
            )
            .gte("occurred_at", cutoff)
            .order("occurred_at", desc=True)
            .limit(limit)
        )
        if agent:
            query = query.eq("agent", agent)
        if resolved is not None:
            query = query.eq("resolved", resolved)

        result = query.execute()
        return {"data": result.data or [], "count": len(result.data or []), "hours": hours}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/errors/{error_id}/resolve")
async def resolve_error(error_id: str):
    """Mark a pipeline error as resolved."""
    db = get_db()
    try:
        result = (
            db._filter_ws(db.client.table("pipeline_errors").update({"resolved": True}))
            .eq("id", error_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Error not found")
        return {"data": result.data[0], "message": "Error marked as resolved"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/costs")
async def get_cost_breakdown(days: int = Query(7, ge=1, le=30)):
    """Cost breakdown by agent and day for the last N days.

    Shows daily API spend so you can track research cost velocity.
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        # Pull from pipeline_runs (has cost_usd per run)
        runs = (
            db._filter_ws(
                db.client.table("pipeline_runs").select("agent, started_at, cost_usd, processed")
            )
            .gte("started_at", cutoff)
            .not_.is_("cost_usd", "null")
            .execute()
        )

        # Group by agent + day
        by_agent: dict[str, float] = {}
        by_day: dict[str, float] = {}
        total = 0.0

        for run in (runs.data or []):
            cost = float(run.get("cost_usd") or 0)
            agent = run.get("agent", "unknown")
            day = (run.get("started_at") or "")[:10]

            by_agent[agent] = round(by_agent.get(agent, 0) + cost, 4)
            by_day[day] = round(by_day.get(day, 0) + cost, 4)
            total += cost

        # Also sum from api_costs table (older format)
        try:
            costs = (
                db._filter_ws(
                    db.client.table("api_costs").select("cost_usd, created_at")
                )
                .gte("created_at", cutoff)
                .execute()
            )
            for row in (costs.data or []):
                cost = float(row.get("cost_usd") or 0)
                day = (row.get("created_at") or "")[:10]
                by_day[day] = round(by_day.get(day, 0) + cost, 4)
                total += cost
        except Exception:
            pass

        return {
            "total_usd": round(total, 4),
            "by_agent": by_agent,
            "by_day": dict(sorted(by_day.items())),
            "days": days,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshot")
async def trigger_snapshot():
    """Manually trigger a health snapshot now (instead of waiting 15 minutes)."""
    try:
        from backend.app.agents.monitoring import HealthSnapshotAgent
        snapshot = HealthSnapshotAgent().capture()
        return {"data": snapshot, "message": "Snapshot captured"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Admin metrics — operations dashboard snapshot
# ---------------------------------------------------------------------------

admin_router = APIRouter(prefix="/api/prospectiq/admin", tags=["admin"])


def _count(query) -> int:
    try:
        return query.execute().count or 0
    except Exception:
        return 0


def _select_count(table_query):
    """Return a query primed for count='exact' selects."""
    return table_query.select("id", count="exact")


@admin_router.get("/metrics")
async def get_admin_metrics():
    """Operations dashboard snapshot for the last 30 days.

    Aggregates send / open / click / reply / bounce / approval / spend /
    pipeline counters in one round-trip-friendly payload. Bounce
    ``unsuppressed`` is the headline data quality signal — it counts drafts
    where ``bounced_at`` is set but the joined contact still flags
    ``is_outreach_eligible=true``, i.e. the bounce hygiene job has not
    caught up yet.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()
    window_start = (now - timedelta(days=30)).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    # ------------------------------------------------------------------
    # Sends
    # ------------------------------------------------------------------
    drafts_30d = (
        db._filter_ws(
            db.client.table("outreach_drafts").select(
                "id, sent_at, opened_at, clicked_at, bounced_at, replied_at, "
                "approval_status, contacts(is_outreach_eligible)"
            )
        )
        .gte("sent_at", window_start)
        .not_.is_("sent_at", "null")
        .execute()
        .data or []
    )

    sends_total = len(drafts_30d)
    sends_today = sum(1 for d in drafts_30d if (d.get("sent_at") or "") >= today_start)
    sends_week = sum(1 for d in drafts_30d if (d.get("sent_at") or "") >= week_start)

    # ------------------------------------------------------------------
    # Opens / clicks
    # ------------------------------------------------------------------
    opens_total = sum(1 for d in drafts_30d if d.get("opened_at"))
    clicks_total = sum(1 for d in drafts_30d if d.get("clicked_at"))
    open_rate = round(opens_total * 100.0 / max(sends_total, 1), 2)
    click_rate = round(clicks_total * 100.0 / max(sends_total, 1), 2)

    # ------------------------------------------------------------------
    # Replies — pull from outreach_outcomes for the classification breakdown
    # ------------------------------------------------------------------
    replies_total = 0
    replies_positive = 0
    replies_question = 0
    replies_not_interested = 0
    try:
        outcomes = (
            db._filter_ws(
                db.client.table("outreach_outcomes").select(
                    "reply_classification, replied_at"
                )
            )
            .gte("replied_at", window_start)
            .not_.is_("replied_at", "null")
            .execute()
            .data or []
        )
        for o in outcomes:
            replies_total += 1
            cls = (o.get("reply_classification") or "").lower()
            if cls in ("interested", "meeting_request", "positive"):
                replies_positive += 1
            elif cls in ("question", "needs_info", "info_request"):
                replies_question += 1
            elif cls in ("not_interested", "soft_no", "hard_no", "unsubscribe"):
                replies_not_interested += 1
    except Exception as exc:
        logger.warning("admin metrics: outcomes query failed (%s) — falling back to drafts", exc)
        replies_total = sum(1 for d in drafts_30d if d.get("replied_at"))

    # ------------------------------------------------------------------
    # Bounces — total, rate, unsuppressed count (the data quality signal)
    # ------------------------------------------------------------------
    bounced_drafts = (
        db._filter_ws(
            db.client.table("outreach_drafts").select(
                "id, bounced_at, contacts(is_outreach_eligible)"
            )
        )
        .not_.is_("bounced_at", "null")
        .execute()
        .data or []
    )
    bounces_total = len(bounced_drafts)
    bounce_rate = round(bounces_total * 100.0 / max(sends_total, 1), 2)
    unsuppressed = sum(
        1 for d in bounced_drafts
        if (d.get("contacts") or {}).get("is_outreach_eligible") is True
    )

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------
    pending = _count(
        db._filter_ws(_select_count(db.client.table("outreach_drafts")))
        .eq("approval_status", "pending")
    )
    approved_unsent = _count(
        db._filter_ws(_select_count(db.client.table("outreach_drafts")))
        .in_("approval_status", ["approved", "edited"])
        .is_("sent_at", "null")
    )
    rejected = _count(
        db._filter_ws(_select_count(db.client.table("outreach_drafts")))
        .eq("approval_status", "rejected")
    )

    # ------------------------------------------------------------------
    # Spend — month-to-date vs cap from limits.yaml
    # ------------------------------------------------------------------
    mtd_usd = 0.0
    cap_usd = 200.0
    try:
        from backend.app.core.limits import L
        cap_usd = float(L.workspace_monthly_default_usd)
    except Exception as exc:
        logger.warning("admin metrics: limits load failed (%s) — using $200 default", exc)

    try:
        cost_rows = (
            db._filter_ws(
                db.client.table("api_costs").select("estimated_cost_usd")
            )
            .gte("created_at", month_start)
            .execute()
            .data or []
        )
        mtd_usd = round(sum(float(r.get("estimated_cost_usd") or 0) for r in cost_rows), 4)
    except Exception as exc:
        logger.warning("admin metrics: api_costs query failed (%s)", exc)

    remaining_usd = round(max(0.0, cap_usd - mtd_usd), 4)

    # ------------------------------------------------------------------
    # Pipeline counts (companies + contacts)
    # ------------------------------------------------------------------
    pipeline = {
        "discovered": _count(
            db._filter_ws(_select_count(db.client.table("companies")))
            .eq("status", "discovered")
        ),
        "qualified": _count(
            db._filter_ws(_select_count(db.client.table("companies")))
            .in_("status", ["qualified", "high_priority", "hot_prospect"])
        ),
        "enriched": _count(
            db._filter_ws(_select_count(db.client.table("contacts")))
            .eq("enrichment_status", "enriched")
        ),
        "outreach_pending": _count(
            db._filter_ws(_select_count(db.client.table("companies")))
            .eq("status", "outreach_pending")
        ),
    }

    return {
        "period": "last_30_days",
        "sends": {"total": sends_total, "today": sends_today, "this_week": sends_week},
        "opens": {"total": opens_total, "rate_pct": open_rate},
        "clicks": {"total": clicks_total, "rate_pct": click_rate},
        "replies": {
            "total": replies_total,
            "positive": replies_positive,
            "question": replies_question,
            "not_interested": replies_not_interested,
        },
        "bounces": {
            "total": bounces_total,
            "rate_pct": bounce_rate,
            "unsuppressed": unsuppressed,
        },
        "approvals": {
            "pending": pending,
            "approved_unsent": approved_unsent,
            "rejected": rejected,
        },
        "spend": {
            "mtd_usd": mtd_usd,
            "cap_usd": cap_usd,
            "remaining_usd": remaining_usd,
        },
        "pipeline": pipeline,
        "generated_at": now.isoformat(),
    }
