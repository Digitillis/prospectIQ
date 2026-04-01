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
