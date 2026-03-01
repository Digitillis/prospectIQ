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
from backend.app.agents.engagement import EngagementAgent
from backend.app.orchestrator.pipeline import Pipeline

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


class FullPipelineRequest(BaseModel):
    max_pages: Optional[int] = None
    campaign: Optional[str] = None
    tiers: Optional[list[str]] = None
    skip_outreach: bool = False


class EngagementRequest(BaseModel):
    action: str = "send_approved"  # send_approved | process_due | check_status | poll_events
    campaign_name: Optional[str] = None


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

    if result.processed > 0:
        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f"*{result.processed} new outreach draft(s) ready for approval.* "
                f"Open the ProspectIQ Approvals page to review and send.",
                emoji=":pencil:",
            )
        except Exception:
            pass

    return {"data": _serialize_result(result)}


@router.post("/run/engagement")
async def run_engagement(body: EngagementRequest):
    """Trigger an engagement action (send approved drafts, process sequences, poll events).

    Actions:
    - send_approved: Send all approved outreach drafts via Instantly
    - process_due: Process sequences with due follow-up actions
    - check_status: Fetch aggregate campaign analytics from Instantly
    - poll_events: Poll Instantly for per-lead opens/clicks/replies/bounces
                   (webhook-free alternative for lower-tier Instantly plans)
    """
    agent = EngagementAgent()
    result = agent.execute(action=body.action, campaign_name=body.campaign_name)
    return {"data": _serialize_result(result)}


@router.post("/run/poll-instantly")
async def poll_instantly():
    """Convenience endpoint: poll Instantly for new lead events and sync to DB.

    Equivalent to POST /run/engagement with action=poll_events.
    Designed to be called on a schedule (e.g. every hour via cron or Railway cron job).
    """
    agent = EngagementAgent()
    result = agent.execute(action="poll_events")
    return {"data": _serialize_result(result)}


@router.post("/run/full")
async def run_full_pipeline(body: FullPipelineRequest):
    """Run the full pipeline: discovery → research → qualification → outreach.

    Chains all four agents in sequence. Stops early if any stage fails.
    Human approval of outreach drafts is still required before sending.

    Set skip_outreach=true to stop after qualification (no drafts generated).
    """
    pipeline = Pipeline()
    results = pipeline.run_full(
        max_pages=body.max_pages,
        campaign_name=body.campaign,
        skip_outreach=body.skip_outreach,
        tiers=body.tiers,
    )
    return {
        "data": {
            stage: _serialize_result(result)
            for stage, result in results.items()
        }
    }
