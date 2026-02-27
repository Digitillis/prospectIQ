"""Analytics routes for ProspectIQ API.

Pipeline overview, API cost tracking, and outreach performance metrics.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from backend.app.core.database import Database

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_db() -> Database:
    return Database()


@router.get("/pipeline")
async def get_pipeline_overview():
    """Get company counts by status for the pipeline funnel view."""
    db = get_db()
    counts = db.count_companies_by_status()
    return {"data": counts}


@router.get("/costs")
async def get_costs(batch_id: Optional[str] = None):
    """Get API cost summary, optionally filtered by batch_id."""
    db = get_db()
    costs = db.get_api_costs_summary(batch_id=batch_id)

    # Compute totals
    total_cost = sum(c.get("estimated_cost_usd", 0) for c in costs)
    total_input_tokens = sum(c.get("input_tokens", 0) or 0 for c in costs)
    total_output_tokens = sum(c.get("output_tokens", 0) or 0 for c in costs)

    return {
        "data": costs,
        "totals": {
            "cost_usd": round(total_cost, 4),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "records": len(costs),
        },
    }


@router.get("/performance")
async def get_performance(limit: int = Query(default=100, ge=1, le=1000)):
    """Get outreach performance metrics from learning outcomes."""
    db = get_db()
    outcomes = db.get_learning_outcomes(limit=limit)
    return {"data": outcomes, "count": len(outcomes)}
