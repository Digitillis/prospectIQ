"""LLM Qualification API routes.

Endpoints:
    POST  /api/qualify/advanced/{company_id}  — run 7-gate LLM qualification
    GET   /api/qualify/advanced/{company_id}  — retrieve stored result
    POST  /api/qualify/advanced/{company_id}/override — manual override
    POST  /api/qualify/advanced/batch         — batch-qualify multiple companies
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/qualify", tags=["qualification"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


class OverridePayload(BaseModel):
    passed: bool
    reason: str


class BatchQualifyPayload(BaseModel):
    company_ids: list[str]


@router.post("/advanced/{company_id}")
async def run_llm_qualification(company_id: str, background_tasks: BackgroundTasks):
    """Trigger 7-gate LLM qualification for a single company.

    Runs synchronously for immediate response. For large batches, use the
    batch endpoint which runs in the background.
    """
    db = get_db()
    workspace_id = get_workspace_id()

    # Verify company exists and belongs to workspace
    company = db.get_company(company_id)
    if not company or company.get("workspace_id") != workspace_id:
        raise HTTPException(404, "Company not found.")

    contacts = db.get_contacts(company_id=company_id, limit=3)
    if not contacts:
        raise HTTPException(422, "No contacts found for this company. Enrich contacts first.")

    from backend.app.core.config import get_settings
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured.")

    try:
        from backend.app.agents.llm_qualification import LLMQualificationAgent
        agent = LLMQualificationAgent(workspace_id=workspace_id)
        result = agent.qualify_contact(company=company, contact=contacts[0])

        # Persist
        from datetime import datetime, timezone
        db.client.table("companies").update({
            "llm_qualification_result": result,
            "llm_qualified_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", company_id).execute()

        return {
            "company_id": company_id,
            "company_name": company.get("name"),
            "result": result,
        }
    except Exception as e:
        logger.error(f"llm_qualify: {company_id} failed: {e}")
        raise HTTPException(500, f"Qualification failed: {str(e)[:200]}")


@router.get("/advanced/{company_id}")
async def get_llm_qualification(company_id: str):
    """Retrieve stored LLM qualification result for a company."""
    db = get_db()
    workspace_id = get_workspace_id()

    company = db.get_company(company_id)
    if not company or company.get("workspace_id") != workspace_id:
        raise HTTPException(404, "Company not found.")

    result = company.get("llm_qualification_result")
    qualified_at = company.get("llm_qualified_at")

    if not result:
        raise HTTPException(404, "No LLM qualification result found. Run qualification first.")

    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "qualified_at": qualified_at,
        "result": result,
    }


@router.post("/advanced/{company_id}/override")
async def override_llm_qualification(company_id: str, payload: OverridePayload):
    """Manually override the LLM qualification result with an audit trail."""
    db = get_db()
    workspace_id = get_workspace_id()

    company = db.get_company(company_id)
    if not company or company.get("workspace_id") != workspace_id:
        raise HTTPException(404, "Company not found.")

    existing = company.get("llm_qualification_result") or {}

    from datetime import datetime, timezone
    override_record = {
        **existing,
        "passed": payload.passed,
        "override": True,
        "override_reason": payload.reason,
        "override_at": datetime.now(timezone.utc).isoformat(),
    }

    db.client.table("companies").update({
        "llm_qualification_result": override_record,
    }).eq("id", company_id).execute()

    # Log to audit
    try:
        from backend.app.core.audit import log_audit_event
        log_audit_event(
            db=db,
            workspace_id=workspace_id,
            event_type="llm_qualify_override",
            entity_id=company_id,
            metadata={"passed": payload.passed, "reason": payload.reason},
        )
    except Exception:
        pass

    return {"company_id": company_id, "overridden": True, "passed": payload.passed}


@router.post("/advanced/batch")
async def batch_llm_qualification(payload: BatchQualifyPayload, background_tasks: BackgroundTasks):
    """Trigger LLM qualification for multiple companies (runs in background)."""
    if not payload.company_ids:
        raise HTTPException(400, "company_ids cannot be empty.")
    if len(payload.company_ids) > 100:
        raise HTTPException(400, "Maximum 100 companies per batch.")

    workspace_id = get_workspace_id()

    def _run_batch():
        try:
            from backend.app.agents.llm_qualification import LLMQualificationAgent
            agent = LLMQualificationAgent(workspace_id=workspace_id)
            agent.run(company_ids=payload.company_ids)
        except Exception as e:
            logger.error(f"batch_llm_qualification background task failed: {e}")

    background_tasks.add_task(_run_batch)
    return {
        "status": "queued",
        "company_count": len(payload.company_ids),
        "message": "Batch qualification running in background.",
    }
