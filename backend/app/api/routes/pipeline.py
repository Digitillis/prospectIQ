"""Pipeline routes for ProspectIQ API.

Trigger agent runs (discovery, research, qualification, outreach)
and return results synchronously.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.agents.discovery import DiscoveryAgent
from backend.app.agents.research import ResearchAgent
from backend.app.agents.qualification import QualificationAgent
from backend.app.agents.enrichment import EnrichmentAgent
from backend.app.agents.outreach import OutreachAgent
from backend.app.agents.engagement import EngagementAgent
from backend.app.agents.reengagement import ReengagementAgent
from backend.app.agents.linkedin import LinkedInAgent
from backend.app.agents.learning import LearningAgent
from backend.app.agents.linkedin_sender import LinkedInSenderAgent
from backend.app.orchestrator.pipeline import Pipeline
from backend.app.billing.quota import require_quota
from backend.app.core.audit import log_audit_event_from_ctx

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
    tier: Optional[str] = None
    tiers: Optional[list[str]] = None
    limit: Optional[int] = None


class QualificationRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    limit: int = 100


class EnrichmentRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    limit: int = 25
    include_phone: bool = False


class OutreachRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    sequence_name: str = "email_value_first"
    step: int = 1
    limit: int = 20
    tiers: Optional[list[str]] = None


class FullPipelineRequest(BaseModel):
    max_pages: Optional[int] = None
    campaign: Optional[str] = None
    tiers: Optional[list[str]] = None
    skip_outreach: bool = False


class ReengagementRequest(BaseModel):
    limit: int = 50
    cooldown_days: int = 90


class LinkedInRequest(BaseModel):
    company_ids: Optional[list[str]] = None
    limit: int = 20
    regenerate: bool = False


class EngagementRequest(BaseModel):
    action: str = "send_approved"  # send_approved | process_due | check_status | poll_events
    campaign_name: Optional[str] = None


class LearningRequest(BaseModel):
    period_days: int = 30
    auto_apply: bool = False


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
async def run_discovery(
    body: DiscoveryRequest,
    _quota: None = Depends(require_quota("discovery")),
):
    """Trigger the discovery agent to find new companies via Apollo."""
    agent = DiscoveryAgent()
    result = agent.execute(
        max_pages=body.max_pages,
        campaign_name=body.campaign,
        tiers=body.tiers,
    )
    log_audit_event_from_ctx(
        "pipeline.run",
        resource_type="agent",
        metadata={"agent": "discovery", "processed": result.processed, "errors": result.errors},
    )
    return {"data": _serialize_result(result)}


@router.post("/run/research")
async def run_research(
    body: ResearchRequest,
    _quota: None = Depends(require_quota("research")),
):
    """Trigger the research agent for deep company analysis."""
    agent = ResearchAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        min_firmographic_score=body.min_score,
        tier=body.tier,
        tiers=body.tiers,
        limit=body.limit,
    )
    log_audit_event_from_ctx(
        "pipeline.run",
        resource_type="agent",
        metadata={"agent": "research", "processed": result.processed, "errors": result.errors, "cost_usd": result.total_cost_usd},
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


@router.post("/run/enrichment")
async def run_enrichment(
    body: EnrichmentRequest,
    _quota: None = Depends(require_quota("enrichment")),
):
    """Trigger the enrichment agent to get emails/phones for qualified contacts.

    Consumes Apollo credits — only enriches the top-priority contact per company.
    Must run after qualification, before outreach.
    """
    agent = EnrichmentAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        limit=body.limit,
        include_phone=body.include_phone,
    )
    return {"data": _serialize_result(result)}


@router.post("/run/outreach")
async def run_outreach(
    body: OutreachRequest,
    _role=Depends(require_role("member")),
):
    """Trigger the outreach agent to generate personalized drafts."""
    agent = OutreachAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        sequence_name=body.sequence_name,
        sequence_step=body.step,
        limit=body.limit,
        tiers=body.tiers,
    )

    log_audit_event_from_ctx(
        "pipeline.run",
        resource_type="agent",
        metadata={"agent": "outreach", "processed": result.processed, "errors": result.errors, "cost_usd": result.total_cost_usd},
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


@router.post("/run/linkedin")
async def run_linkedin(
    body: LinkedInRequest,
    _role=Depends(require_role("member")),
):
    """Generate LinkedIn messages (connection note, opening DM, follow-up DM) for qualified contacts.

    All drafts are auto-approved since LinkedIn messages are copy-pasted manually.
    Only processes contacts that have a linkedin_url on their contact record.
    """
    agent = LinkedInAgent()
    result = agent.execute(
        company_ids=body.company_ids,
        limit=body.limit,
        regenerate=body.regenerate,
    )

    if result.processed > 0:
        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f"*{result.processed} LinkedIn message set(s) generated.* "
                f"Open the ProspectIQ LinkedIn page to review and copy.",
                emoji=":linkedin:",
            )
        except Exception:
            pass

    return {"data": _serialize_result(result)}


@router.post("/run/reengagement")
async def run_reengagement(
    body: ReengagementRequest,
    _role=Depends(require_role("member")),
):
    """Re-queue stale prospects whose sequences completed without reply.

    Scans for contacts past the cooldown period (default 90 days) and
    moves them back to 'qualified' status for warm follow-up outreach.
    """
    agent = ReengagementAgent()
    result = agent.execute(limit=body.limit, cooldown_days=body.cooldown_days)
    return {"data": _serialize_result(result)}


@router.post("/run/engagement")
async def run_engagement(
    body: EngagementRequest,
    _role=Depends(require_role("member")),
):
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


@router.post("/run/buying-signals")
async def run_buying_signals():
    """Scan contacted/engaged prospects for buying signals and auto-escalate.

    Detects: multi-opens, link clicks, multi-contact engagement,
    re-engagement after silence. Auto-bumps PQS and notifies Slack.
    """
    from backend.app.core.buying_signals import BuyingSignalDetector
    agent = BuyingSignalDetector()
    result = agent.execute()
    return {"data": _serialize_result(result)}


@router.get("/intent/{company_id}")
async def get_intent_signals(company_id: str):
    """Get intent signal analysis for a specific company."""
    from backend.app.core.intent_signals import analyze_intent
    from backend.app.core.database import Database
    from backend.app.core.workspace import get_workspace_id
    db = Database(workspace_id=get_workspace_id())
    report = analyze_intent(db, company_id)
    return {
        "data": {
            "company_id": report.company_id,
            "company_name": report.company_name,
            "intent_level": report.intent_level,
            "total_score": report.total_score,
            "signals": [
                {
                    "type": s.signal_type,
                    "strength": s.strength,
                    "points": s.points,
                    "evidence": s.evidence,
                    "source": s.source,
                }
                for s in report.signals
            ],
        }
    }


@router.post("/run/poll-instantly")
async def poll_instantly():
    """Convenience endpoint: poll Instantly for new lead events and sync to DB.

    Equivalent to POST /run/engagement with action=poll_events.
    Designed to be called on a schedule (e.g. every hour via cron or Railway cron job).
    """
    agent = EngagementAgent()
    result = agent.execute(action="poll_events")
    return {"data": _serialize_result(result)}


class LinkedInSendRequest(BaseModel):
    send_connection_requests: bool = True
    send_dms: bool = True
    withdraw_stale: bool = True
    dry_run: bool = False


@router.post("/run/linkedin-send")
async def run_linkedin_send(
    body: LinkedInSendRequest,
    _role=Depends(require_role("member")),
):
    """Trigger the LinkedIn sender agent to send approved drafts via Unipile.

    - send_connection_requests: send approved connection note drafts (max 20/day)
    - send_dms: send approved opening DM drafts for accepted connections
    - withdraw_stale: withdraw pending invites older than 21 days
    - dry_run: log actions without sending anything
    """
    agent = LinkedInSenderAgent()
    result = agent.execute(
        send_connection_requests=body.send_connection_requests,
        send_dms=body.send_dms,
        withdraw_stale=body.withdraw_stale,
        dry_run=body.dry_run,
    )
    return {"data": _serialize_result(result)}


@router.post("/run/learning")
async def run_learning(body: LearningRequest):
    """Analyze outreach engagement outcomes and generate actionable insights.

    Aggregates performance data from the last `period_days` days and uses
    Claude to surface insights, suggest scoring adjustments, and recommend
    ICP refinements.

    Set auto_apply=true to write scoring adjustments directly to scoring.yaml.
    Requires at least 20 outcome records in the analysis window.
    """
    agent = LearningAgent()
    result = agent.execute(period_days=body.period_days, auto_apply=body.auto_apply)
    return {"data": _serialize_result(result)}


@router.post("/run/full")
async def run_full_pipeline(
    body: FullPipelineRequest,
    _role=Depends(require_role("member")),
    _quota: None = Depends(require_quota("research")),
):
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
