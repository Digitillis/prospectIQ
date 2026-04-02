"""Lookalike Discovery API routes for ProspectIQ.

Endpoints:
    POST /api/lookalike/run              — run discovery from explicit seed IDs
    POST /api/lookalike/auto-run        — auto-seed from best performers + run
    GET  /api/lookalike/runs            — list past lookalike runs
    GET  /api/lookalike/runs/{run_id}   — full run detail
    POST /api/lookalike/runs/{run_id}/add-to-pipeline — bulk-add matches to pipeline
    GET  /api/lookalike/seed-profile    — preview seed profile without running
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.lookalike_engine import LookalikeEngine
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lookalike", tags=["lookalike"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


def get_engine() -> LookalikeEngine:
    return LookalikeEngine(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    seed_company_ids: list[str]
    limit: Optional[int] = 50
    exclude_contacted: Optional[bool] = True


class AddToPipelineRequest(BaseModel):
    company_ids: list[str]
    sequence_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_lookalike(body: RunRequest):
    """Run lookalike discovery from an explicit set of seed company IDs."""
    if not body.seed_company_ids:
        raise HTTPException(status_code=422, detail="seed_company_ids must not be empty")

    engine = get_engine()

    exclude_status = None
    if body.exclude_contacted:
        exclude_status = [
            "contacted", "outreach_pending", "engaged",
            "meeting_scheduled", "pilot_discussion", "pilot_signed",
            "active_pilot", "converted", "not_interested", "bounced",
        ]

    limit = max(1, min(body.limit or 50, 200))

    result = engine.find_lookalikes(
        seed_company_ids=body.seed_company_ids,
        limit=limit,
        exclude_status=exclude_status,
    )

    saved = engine.save_run(result)
    run_id = saved.get("id")

    return {
        "run_id": run_id,
        "seed_profile": result.seed_profile.model_dump(),
        "matches": [m.model_dump() for m in result.matches],
        "total_scored": result.total_scored,
        "generated_at": result.generated_at,
    }


@router.post("/auto-run")
async def auto_run_lookalike():
    """Auto-seed from best performers (replied/interested/demo/customer) and run discovery."""
    engine = get_engine()

    seed_ids = engine.auto_seed_from_best_performers()

    if not seed_ids:
        raise HTTPException(
            status_code=422,
            detail="No high-value companies found to use as seed. "
                   "You need at least one company with status: replied, interested, demo_booked, or customer.",
        )

    exclude_status = [
        "contacted", "outreach_pending", "engaged",
        "meeting_scheduled", "pilot_discussion", "pilot_signed",
        "active_pilot", "converted", "not_interested", "bounced",
    ]

    result = engine.find_lookalikes(
        seed_company_ids=seed_ids,
        limit=50,
        exclude_status=exclude_status,
    )

    saved = engine.save_run(result)
    run_id = saved.get("id")

    return {
        "run_id": run_id,
        "seed_profile": result.seed_profile.model_dump(),
        "matches": [m.model_dump() for m in result.matches],
        "total_scored": result.total_scored,
        "generated_at": result.generated_at,
    }


@router.get("/runs")
async def list_lookalike_runs():
    """List past lookalike runs (summary only)."""
    engine = get_engine()
    runs = engine.list_runs()
    return {"data": runs, "count": len(runs)}


@router.get("/runs/{run_id}")
async def get_lookalike_run(run_id: str):
    """Get full detail for a past lookalike run."""
    engine = get_engine()
    run = engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Lookalike run not found")

    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "seed_profile": run.get("seed_profile"),
        "matches": run.get("matches"),
        "total_scored": run.get("total_scored", 0),
    }


@router.post("/runs/{run_id}/add-to-pipeline")
async def add_to_pipeline(run_id: str, body: AddToPipelineRequest):
    """Bulk-add selected lookalike matches to the outreach pipeline."""
    if not body.company_ids:
        raise HTTPException(status_code=422, detail="company_ids must not be empty")

    db = get_db()

    # Verify the run exists
    engine = get_engine()
    run = engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Lookalike run not found")

    added = 0
    already_in_pipeline = 0

    pipeline_statuses = {
        "outreach_pending", "contacted", "engaged",
        "meeting_scheduled", "pilot_discussion", "pilot_signed",
        "active_pilot", "converted",
    }

    for company_id in body.company_ids:
        company = db.get_company(company_id)
        if not company:
            continue

        current_status = company.get("status", "discovered")

        if current_status in pipeline_statuses:
            already_in_pipeline += 1
            continue

        # Move to prospect / outreach_pending
        updates: dict = {}
        if current_status in ("discovered", "researched", "qualified"):
            updates["status"] = "outreach_pending"

        if body.sequence_name:
            updates["campaign_name"] = body.sequence_name

        if updates:
            db.update_company(company_id, updates)

        added += 1

    return {
        "added": added,
        "already_in_pipeline": already_in_pipeline,
    }


@router.get("/seed-profile")
async def get_seed_profile():
    """Preview the seed profile derived from best performers (no full run)."""
    engine = get_engine()
    seed_ids = engine.auto_seed_from_best_performers()

    if not seed_ids:
        return {
            "seed_company_count": 0,
            "dominant_cluster": None,
            "dominant_tranche": None,
            "avg_pqs": 0,
            "top_technologies": [],
            "top_pain_themes": [],
            "revenue_ranges": [],
            "employee_count_range": [0, 0],
            "seed_company_ids": [],
        }

    profile = engine.build_seed_profile(seed_ids)
    return profile.model_dump()
