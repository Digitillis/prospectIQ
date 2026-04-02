"""Personalization API routes for ProspectIQ.

Exposes the PersonalizationEngine as a REST API for the dashboard.

Endpoints:
    POST /api/personalization/run/{company_id}         — run pipeline for one company
    POST /api/personalization/run-batch                — run batch pipeline
    GET  /api/personalization/status/{company_id}      — current personalization state
    GET  /api/personalization/leaderboard              — companies ranked by readiness score
    POST /api/personalization/add-trigger/{company_id} — manually add a trigger
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id
from backend.app.core.personalization_engine import PersonalizationEngine
from backend.app.core.personalization_batch import PersonalizationBatch
from backend.app.core.personalization_models import (
    PersonalizationResult,
    BatchResult,
    PersonalizationStatus,
    PersonalizationLeaderboardItem,
    TriggerEvent,
    ManualTriggerInput,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/personalization", tags=["personalization"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RunBatchRequest(BaseModel):
    filters: Optional[dict[str, Any]] = None
    max_companies: int = 50


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/run/{company_id}", response_model=PersonalizationResult)
async def run_personalization(company_id: str) -> PersonalizationResult:
    """Run the full personalization pipeline for a single company.

    Loads research → infers personas → extracts triggers → generates hooks →
    computes readiness score → persists back to company record.
    """
    ws_id = get_workspace_id()
    engine = PersonalizationEngine(workspace_id=ws_id)
    try:
        result = engine.run_full_pipeline(company_id=company_id, workspace_id=ws_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Personalization pipeline failed for {company_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)[:200]}")


@router.post("/run-batch", response_model=BatchResult)
async def run_personalization_batch(request: RunBatchRequest) -> BatchResult:
    """Run personalization across a batch of qualified companies.

    Filters: cluster, tranche, min_pqs (defaults to 50).
    Skips companies that were personalized in the last 7 days.
    """
    ws_id = get_workspace_id()
    runner = PersonalizationBatch(workspace_id=ws_id)
    try:
        result = runner.run_batch(
            filters=request.filters or {},
            max_companies=min(request.max_companies, 200),
        )
        return result
    except Exception as e:
        logger.error(f"Batch personalization failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch error: {str(e)[:200]}")


@router.get("/status/{company_id}", response_model=PersonalizationStatus)
async def get_personalization_status(company_id: str) -> PersonalizationStatus:
    """Return current personalization state for a company.

    Returns zeros/empty lists if personalization has not been run yet.
    """
    db = get_db()
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

    contacts = db.get_contacts_for_company(company_id)

    tags = company.get("custom_tags") or {}
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = {}

    readiness_score = int(tags.get("personalization_readiness", 0))
    last_run_at = tags.get("personalization_last_run")

    raw_triggers = tags.get("personalization_triggers") or []
    triggers: list[TriggerEvent] = []
    for t in raw_triggers:
        try:
            triggers.append(TriggerEvent(**t))
        except Exception:
            continue

    hooks_texts = company.get("personalization_hooks") or []
    # hooks stored as plain strings — return minimal TriggerEvent-compatible view
    personas_found = list({c.get("persona_type") for c in contacts if c.get("persona_type")})

    return PersonalizationStatus(
        company_id=company_id,
        readiness_score=readiness_score,
        triggers=triggers,
        hooks=[],  # full hooks not stored; use /run/{id} to regenerate
        personas_found=personas_found,
        last_run_at=last_run_at,
        contacts_count=len(contacts),
    )


@router.get("/leaderboard", response_model=list[PersonalizationLeaderboardItem])
async def get_personalization_leaderboard(
    limit: int = Query(default=50, ge=1, le=200),
    cluster: Optional[str] = Query(default=None),
    tranche: Optional[str] = Query(default=None),
) -> list[PersonalizationLeaderboardItem]:
    """Return companies ranked by personalization readiness score (desc).

    This is the "who is most ready for personalized outreach" view.
    Only includes companies that have been personalized at least once.
    """
    db = get_db()

    query = (
        db.client.table("companies")
        .select(
            "id, name, campaign_cluster, tier, pqs_total, custom_tags, "
            "personalization_hooks"
        )
        .not_.is_("research_summary", "null")
    )

    if cluster:
        query = query.eq("campaign_cluster", cluster)
    if tranche:
        query = query.eq("tier", tranche)

    rows = query.order("pqs_total", desc=True).limit(limit * 4).execute().data

    items: list[PersonalizationLeaderboardItem] = []
    for row in rows:
        tags = row.get("custom_tags") or {}
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = {}

        readiness_score = int(tags.get("personalization_readiness", 0))
        if readiness_score == 0:
            continue  # only show companies that have been run

        raw_triggers = tags.get("personalization_triggers") or []
        hooks = row.get("personalization_hooks") or []

        # Get contact count separately would be N+1 — use a cached approach
        # via the tags if available, else 0
        contact_count = int(tags.get("contact_count", 0))
        personas_found = tags.get("personas_found") or []
        last_run_at = tags.get("personalization_last_run")

        items.append(PersonalizationLeaderboardItem(
            company_id=row["id"],
            company_name=row.get("name", ""),
            cluster=row.get("campaign_cluster"),
            tranche=row.get("tier"),
            readiness_score=readiness_score,
            trigger_count=len(raw_triggers),
            hook_count=len(hooks),
            contact_count=contact_count,
            personas_found=personas_found if isinstance(personas_found, list) else [],
            last_run_at=last_run_at,
            pqs_total=row.get("pqs_total") or 0,
        ))

    # Sort by readiness_score desc, then pqs_total desc
    items.sort(key=lambda x: (-x.readiness_score, -x.pqs_total))
    return items[:limit]


@router.post("/add-trigger/{company_id}", response_model=TriggerEvent)
async def add_manual_trigger(
    company_id: str,
    body: ManualTriggerInput,
) -> TriggerEvent:
    """Manually add a buying trigger to a company's personalization data.

    Useful when the user knows something that research didn't surface,
    e.g. heard on a call that they're evaluating new systems.
    """
    db = get_db()
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

    tags = company.get("custom_tags") or {}
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = {}

    existing_triggers: list[dict] = tags.get("personalization_triggers") or []

    new_trigger = TriggerEvent(
        trigger_type=body.trigger_type,
        description=body.description,
        urgency=body.urgency,
        confidence=1.0,
        source_text=f"Manually added — source: {body.source}",
        priority_rank=1,
    )

    # Re-rank: push manual immediate triggers to top
    if body.urgency == "immediate":
        existing_triggers = [new_trigger.model_dump()] + existing_triggers
    else:
        existing_triggers = existing_triggers + [new_trigger.model_dump()]

    # Re-number ranks
    for i, t in enumerate(existing_triggers, start=1):
        t["priority_rank"] = i

    tags["personalization_triggers"] = existing_triggers
    db.update_company(company_id, {"custom_tags": tags})

    return new_trigger
