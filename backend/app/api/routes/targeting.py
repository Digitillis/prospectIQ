"""Smart Targeting & Prospects API — AI-driven prospect scoring and recommendations."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.auth import require_workspace_member
from backend.app.core.database import Database, get_db
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/api/targeting", tags=["targeting"])


# ============================================================================
# Models
# ============================================================================


class TargetingStrategy(str, Enum):
    """Different strategies for identifying high-value prospects."""
    HIGH_PQS = "high_pqs"  # High PQS score (60+)
    QUICK_WINS = "quick_wins"  # Ready to contact (researched + decent PQS)
    WARM_LEADS = "warm_leads"  # Recent engagement + PQS
    DECISION_MAKERS = "decision_makers"  # Multiple contacts, high status
    RECENT_ACTIVITY = "recent_activity"  # Recently researched/contacted
    MEETING_READY = "meeting_ready"  # Had calls/emails, likely to book
    DEAL_FOCUSED = "deal_focused"  # High probability close deals


class ProspectScore(BaseModel):
    """Comprehensive scoring for a prospect."""
    company_id: int
    company_name: str
    pqs_score: int
    pqs_breakdown: dict
    contact_count: int
    recent_activity: bool
    has_open_deal: bool
    outreach_stage: str
    meeting_scheduled: bool
    engagement_score: float  # 0-100
    conversion_probability: float  # 0-100, based on patterns
    priority: str  # "critical", "high", "medium", "low"
    recommended_next_action: str


class TargetingRecommendation(BaseModel):
    """Top prospects matching a targeting strategy."""
    strategy: str
    total_count: int
    prospects: list[ProspectScore]
    description: str


class ProspectFilterRequest(BaseModel):
    """Advanced filtering for prospect discovery."""
    min_pqs: int = Field(default=0, ge=0, le=100)
    max_pqs: int = Field(default=100, ge=0, le=100)
    status: Optional[str] = None
    tier: Optional[str] = None
    has_open_deal: Optional[bool] = None
    recent_activity_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=50, ge=1, le=500)


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/smart-targets", response_model=TargetingRecommendation)
async def get_smart_targets(
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
    strategy: TargetingStrategy = Query(TargetingStrategy.HIGH_PQS),
    limit: int = Query(20, ge=1, le=100),
):
    """Get recommended prospects based on targeting strategy."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    prospects = await _get_prospects_for_strategy(db, workspace_id, strategy, limit)

    strategy_descriptions = {
        "high_pqs": "Companies with strong PQS scores (60+) indicating good fit",
        "quick_wins": "Ready-to-contact prospects with research done and decent PQS",
        "warm_leads": "Prospects with recent engagement and conversation momentum",
        "decision_makers": "Companies with multiple high-value contacts",
        "recent_activity": "Recently researched or contacted companies",
        "meeting_ready": "Prospects showing conversation readiness signals",
        "deal_focused": "Companies with high-probability close opportunities",
    }

    return TargetingRecommendation(
        strategy=strategy.value,
        total_count=len(prospects),
        prospects=prospects,
        description=strategy_descriptions.get(strategy.value, "")
    )


@router.post("/search", response_model=dict)
async def search_prospects(
    filters: ProspectFilterRequest,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Search and filter prospects with advanced criteria."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    query = db.client.table("companies").select(
        "id, name, domain, status, pqs_total, pqs_firmographic, pqs_technographic, tier, research_summary"
    ).eq("workspace_id", workspace_id)

    # Apply PQS range filter
    if filters.min_pqs > 0:
        query = query.gte("pqs_total", filters.min_pqs)
    if filters.max_pqs < 100:
        query = query.lte("pqs_total", filters.max_pqs)

    # Apply status filter
    if filters.status:
        query = query.eq("status", filters.status)

    # Apply tier filter
    if filters.tier:
        query = query.eq("tier", filters.tier)

    # Apply recent activity filter
    if filters.recent_activity_days > 0:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=filters.recent_activity_days)).isoformat()
        query = query.gte("updated_at", cutoff_date)

    # Execute search
    result = query.limit(filters.limit).execute()

    # Enrich with deal and engagement data
    companies = result.data or []
    enriched = []

    for company in companies:
        company_id = company["id"]

        # Get deal status
        deal_result = (
            db.client.table("deals")
            .select("id, stage")
            .eq("company_id", company_id)
            .eq("workspace_id", workspace_id)
            .not_.eq("stage", "lost")
            .limit(1)
            .execute()
        )
        has_deal = bool(deal_result.data)

        # Get meeting status
        meeting_result = (
            db.client.table("meetings")
            .select("id")
            .eq("company_id", company_id)
            .eq("workspace_id", workspace_id)
            .in_("status", ["scheduled", "confirmed"])
            .limit(1)
            .execute()
        )
        has_meeting = bool(meeting_result.data)

        # Get contact count
        contact_result = (
            db.client.table("contacts")
            .select("id", count="exact")
            .eq("company_id", company_id)
            .eq("workspace_id", workspace_id)
            .execute()
        )
        contact_count = contact_result.count or 0

        enriched.append({
            "id": company_id,
            "name": company["name"],
            "domain": company["domain"],
            "status": company["status"],
            "pqs_total": company["pqs_total"],
            "tier": company["tier"],
            "has_open_deal": has_deal,
            "has_scheduled_meeting": has_meeting,
            "contact_count": contact_count,
        })

    return {
        "total": len(enriched),
        "prospects": enriched,
        "filters_applied": filters.dict(),
    }


@router.get("/prospect-score/{company_id}", response_model=ProspectScore)
async def get_prospect_score(
    company_id: int,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Get comprehensive scoring for a specific prospect."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Get company data
    company_result = (
        db.client.table("companies")
        .select("id, name, status, pqs_total, pqs_firmographic, pqs_technographic, updated_at")
        .eq("id", company_id)
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not company_result.data:
        raise HTTPException(status_code=404, detail="Company not found")

    company = company_result.data

    # Get deal info
    deal_result = (
        db.client.table("deals")
        .select("id, stage, probability")
        .eq("company_id", company_id)
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    deal = deal_result.data[0] if deal_result.data else None

    # Get meeting info
    meeting_result = (
        db.client.table("meetings")
        .select("id, status, scheduled_at")
        .eq("company_id", company_id)
        .eq("workspace_id", workspace_id)
        .order("scheduled_at", desc=True)
        .limit(1)
        .execute()
    )
    meeting = meeting_result.data[0] if meeting_result.data else None

    # Get contact count
    contact_result = (
        db.client.table("contacts")
        .select("id", count="exact")
        .eq("company_id", company_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    contact_count = contact_result.count or 0

    # Calculate engagement score
    engagement_score = _calculate_engagement_score(company, deal, meeting, contact_count)

    # Calculate conversion probability
    conversion_prob = _calculate_conversion_probability(company, deal, meeting)

    # Determine priority
    priority = _determine_priority(company["pqs_total"], conversion_prob, company["status"])

    # Recommend next action
    next_action = _recommend_next_action(company["status"], deal, meeting)

    return ProspectScore(
        company_id=company_id,
        company_name=company["name"],
        pqs_score=company["pqs_total"],
        pqs_breakdown={
            "firmographic": company["pqs_firmographic"],
            "technographic": company["pqs_technographic"],
        },
        contact_count=contact_count,
        recent_activity=(datetime.fromisoformat(company["updated_at"]) > datetime.now(timezone.utc) - timedelta(days=7)),
        has_open_deal=bool(deal),
        outreach_stage=company["status"],
        meeting_scheduled=bool(meeting and meeting["status"] in ["scheduled", "confirmed"]),
        engagement_score=engagement_score,
        conversion_probability=conversion_prob,
        priority=priority,
        recommended_next_action=next_action,
    )


# ============================================================================
# Helper Functions
# ============================================================================


async def _get_prospects_for_strategy(
    db: Database,
    workspace_id: str,
    strategy: TargetingStrategy,
    limit: int,
) -> list[ProspectScore]:
    """Get prospects matching a specific targeting strategy."""
    prospects = []

    if strategy == TargetingStrategy.HIGH_PQS:
        # Companies with PQS 60+
        result = (
            db.client.table("companies")
            .select("id, name, status, pqs_total, pqs_firmographic, pqs_technographic, updated_at")
            .eq("workspace_id", workspace_id)
            .gte("pqs_total", 60)
            .order("pqs_total", desc=True)
            .limit(limit)
            .execute()
        )

    elif strategy == TargetingStrategy.QUICK_WINS:
        # Status researched + PQS >= 30
        result = (
            db.client.table("companies")
            .select("id, name, status, pqs_total, pqs_firmographic, pqs_technographic, updated_at")
            .eq("workspace_id", workspace_id)
            .eq("status", "researched")
            .gte("pqs_total", 30)
            .order("pqs_total", desc=True)
            .limit(limit)
            .execute()
        )

    elif strategy == TargetingStrategy.RECENT_ACTIVITY:
        # Updated in last 7 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        result = (
            db.client.table("companies")
            .select("id, name, status, pqs_total, pqs_firmographic, pqs_technographic, updated_at")
            .eq("workspace_id", workspace_id)
            .gte("updated_at", cutoff)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )

    else:
        # Default: high PQS
        result = (
            db.client.table("companies")
            .select("id, name, status, pqs_total, pqs_firmographic, pqs_technographic, updated_at")
            .eq("workspace_id", workspace_id)
            .gte("pqs_total", 50)
            .limit(limit)
            .execute()
        )

    companies = result.data or []
    for company in companies:
        # Enrich with deal/meeting/contact info
        deal_result = (
            db.client.table("deals")
            .select("id, stage")
            .eq("company_id", company["id"])
            .eq("workspace_id", workspace_id)
            .not_.eq("stage", "lost")
            .limit(1)
            .execute()
        )
        has_deal = bool(deal_result.data)

        meeting_result = (
            db.client.table("meetings")
            .select("id")
            .eq("company_id", company["id"])
            .eq("workspace_id", workspace_id)
            .in_("status", ["scheduled", "confirmed"])
            .limit(1)
            .execute()
        )
        has_meeting = bool(meeting_result.data)

        contact_result = (
            db.client.table("contacts")
            .select("id", count="exact")
            .eq("company_id", company["id"])
            .eq("workspace_id", workspace_id)
            .execute()
        )
        contact_count = contact_result.count or 0

        engagement_score = _calculate_engagement_score(company, has_deal, has_meeting, contact_count)
        conversion_prob = _calculate_conversion_probability(company, has_deal, has_meeting)
        priority = _determine_priority(company["pqs_total"], conversion_prob, company["status"])
        next_action = _recommend_next_action(company["status"], has_deal, has_meeting)

        prospects.append(ProspectScore(
            company_id=company["id"],
            company_name=company["name"],
            pqs_score=company["pqs_total"],
            pqs_breakdown={
                "firmographic": company["pqs_firmographic"],
                "technographic": company["pqs_technographic"],
            },
            contact_count=contact_count,
            recent_activity=(datetime.fromisoformat(company["updated_at"]) > datetime.now(timezone.utc) - timedelta(days=7)),
            has_open_deal=has_deal,
            outreach_stage=company["status"],
            meeting_scheduled=has_meeting,
            engagement_score=engagement_score,
            conversion_probability=conversion_prob,
            priority=priority,
            recommended_next_action=next_action,
        ))

    return prospects


def _calculate_engagement_score(company: dict, deal, meeting, contact_count: int) -> float:
    """Calculate engagement score based on interactions and contacts."""
    score = 0.0

    # Contact count contribution (max 30 points)
    score += min(contact_count * 5, 30)

    # Deal contribution (max 30 points)
    if deal:
        score += 30

    # Meeting contribution (max 25 points)
    if meeting:
        score += 25

    # PQS contribution (max 15 points)
    score += min(company.get("pqs_total", 0) / 100 * 15, 15)

    return min(score, 100.0)


def _calculate_conversion_probability(company: dict, deal, meeting) -> float:
    """Estimate probability of conversion based on company attributes."""
    prob = 0.0

    # Base probability from PQS
    pqs = company.get("pqs_total", 0)
    prob = (pqs / 100) * 40  # PQS accounts for 40% of probability

    # Deal stage contribution
    if deal:
        stage_probs = {
            "prospect": 5,
            "qualified": 15,
            "proposal": 35,
            "negotiation": 60,
            "won": 100,
        }
        stage = deal.get("stage") if isinstance(deal, dict) else "prospect"
        prob += stage_probs.get(stage, 0) * 0.5  # Deal stage is 50%

    # Meeting signals
    if meeting:
        prob += 15  # 15% boost for having scheduled meetings

    return min(prob, 100.0)


def _determine_priority(pqs_score: int, conversion_prob: float, status: str) -> str:
    """Determine priority level based on scoring."""
    if conversion_prob >= 70 or pqs_score >= 80:
        return "critical"
    elif conversion_prob >= 50 or pqs_score >= 60:
        return "high"
    elif conversion_prob >= 25 or pqs_score >= 40:
        return "medium"
    else:
        return "low"


def _recommend_next_action(status: str, deal, meeting) -> str:
    """Recommend next action based on prospect state."""
    if status == "discovered":
        return "Research the company to qualify"
    elif status == "researched":
        return "Schedule discovery call"
    elif status == "qualified":
        if not meeting:
            return "Schedule initial meeting"
        else:
            return "Send demo/proposal"
    elif status in ["meeting_scheduled", "contacted"]:
        return "Prepare for meeting"
    elif status == "pilot_discussion":
        return "Create and send proposal"
    elif status == "pilot_signed":
        return "Monitor pilot progress"
    elif status == "active_pilot":
        return "Plan expansion discussion"
    else:
        return "Follow up and assess status"
