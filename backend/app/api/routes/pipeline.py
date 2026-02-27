"""Pipeline routes for ProspectIQ API.

Trigger agent runs (discovery, research, qualification, outreach)
and return results synchronously.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.agents.discovery import DiscoveryAgent
from backend.app.agents.research import ResearchAgent
from backend.app.agents.qualification import QualificationAgent
from backend.app.agents.outreach import OutreachAgent

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class DiscoveryRequest(BaseModel):
    max_pages: Optional[int] = None
    campaign: Optional[str] = None
    tiers: Optional[list[str]] = None


class ResearchRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    min_score: Optional[int] = None
    limit: Optional[int] = None


class QualificationRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    limit: int = 100


class OutreachRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    sequence_name: str = "initial_outreach"
    step: int = 1
    limit: int = 20


# ------------------------------------------------------------------
# Helper to serialize AgentResult
# ------------------------------------------------------------------

def _serialize_result(result) -> dict:
    """Convert AgentResult to a JSON-safe dict."""
    return {
        "success": result.success,
        "processed": result.processed,
        "skipped": result.skipped,
        "errors": result.errors,
        "batch_id": result.batch_id,
        "duration_seconds": result.duration_seconds,
        "total_cost_usd": result.total_cost_usd,
        "details": result.details,
        "summary": result.summary(),
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/run/discovery")
async def run_discovery(body: DiscoveryRequest):
    """Trigger the discovery agent to find new companies via Apollo."""
    agent = DiscoveryAgent()
    result = agent.execute(
        max_pages=body.max_pages,
        campaign_name=body.campaign,
        tiers=body.tiers,
    )
    return {"data": _serialize_result(result)}


@router.post("/run/research")
async def run_research(body: ResearchRequest):
    """Trigger the research agent for deep company analysis."""
    agent = ResearchAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        min_firmographic_score=body.min_score,
        limit=body.limit,
    )
    return {"data": _serialize_result(result)}


@router.post("/run/qualification")
async def run_qualification(body: QualificationRequest):
    """Trigger the qualification agent to score companies."""
    agent = QualificationAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        limit=body.limit,
    )
    return {"data": _serialize_result(result)}


@router.post("/run/outreach")
async def run_outreach(body: OutreachRequest):
    """Trigger the outreach agent to generate personalized drafts."""
    agent = OutreachAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        sequence_name=body.sequence_name,
        sequence_step=body.step,
        limit=body.limit,
    )
    return {"data": _serialize_result(result)}
