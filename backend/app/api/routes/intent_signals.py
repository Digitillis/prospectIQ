"""Intent Signals API — Detect and surface buying signals & outreach triggers."""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.auth import require_workspace_member
from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/api/intent-signals", tags=["intent_signals"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ============================================================================
# Models
# ============================================================================


class SignalType(str, Enum):
    """Types of intent signals indicating readiness for outreach."""
    RECENT_RESEARCH = "recent_research"  # Recently researched in system
    PQS_IMPROVEMENT = "pqs_improvement"  # PQS score increased significantly
    ENGAGEMENT_SPIKE = "engagement_spike"  # Increased email open rate
    RECENT_CONTACT_ENGAGEMENT = "contact_engagement"  # Contact recently opened/clicked
    JOB_CHANGE = "job_change"  # New contact from target company
    INBOUND_INTEREST = "inbound_interest"  # Inbound inquiry or demo request
    SIGNAL_MATCH = "signal_match"  # Matches intelligence signal/intent data
    COMPETITIVE_THREAT = "competitive_threat"  # Using competitor solutions
    GROWTH_SIGNAL = "growth_signal"  # Company announced growth/funding
    OUTREACH_WINDOW = "outreach_window"  # Optimal timing for contact


class SignalPriority(str, Enum):
    """Signal urgency levels."""
    CRITICAL = "critical"  # Act immediately
    HIGH = "high"  # High priority, this week
    MEDIUM = "medium"  # This month
    LOW = "low"  # Background monitoring


class IntentSignal(BaseModel):
    """A single intent signal for a prospect."""
    company_id: int
    company_name: str
    signal_type: SignalType
    priority: SignalPriority
    description: str
    signal_date: datetime
    data: dict  # Additional signal-specific data
    recommended_action: str
    action_urgency_days: int  # Days to act before signal loses value


class IntentSummary(BaseModel):
    """Summary of all intent signals."""
    total_signals: int
    critical_count: int
    high_count: int
    by_type: dict[str, int]
    top_prospects: List[IntentSignal]


class CommandCenterItem(BaseModel):
    """High-priority item for command center dashboard."""
    item_id: str
    item_type: str  # "intent_signal", "hitl_queue", "meeting", "deal"
    priority: str
    company_id: int
    company_name: str
    title: str
    description: str
    action_required: str
    created_at: datetime
    expires_at: Optional[datetime] = None


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/detected", response_model=IntentSummary)
async def get_intent_signals(
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
    priority: Optional[SignalPriority] = Query(None),
    signal_type: Optional[SignalType] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Get detected intent signals for all prospects."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    signals = await _detect_all_signals(db, workspace_id, priority, signal_type, limit)

    # Count signals by priority and type
    critical_count = sum(1 for s in signals if s.priority == SignalPriority.CRITICAL)
    high_count = sum(1 for s in signals if s.priority == SignalPriority.HIGH)

    by_type = {}
    for signal in signals:
        sig_type = signal.signal_type.value
        by_type[sig_type] = by_type.get(sig_type, 0) + 1

    return IntentSummary(
        total_signals=len(signals),
        critical_count=critical_count,
        high_count=high_count,
        by_type=by_type,
        top_prospects=signals[:20],
    )


@router.get("/prospect/{company_id}", response_model=List[IntentSignal])
async def get_prospect_signals(
    company_id: int,
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
):
    """Get all detected intent signals for a specific prospect."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    # Verify company exists in workspace
    company_result = (
        db.client.table("companies")
        .select("id, name")
        .eq("id", company_id)
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not company_result.data:
        raise HTTPException(status_code=404, detail="Company not found")

    signals = await _detect_signals_for_company(db, workspace_id, company_id)
    return signals


@router.get("/command-center", response_model=dict)
async def get_command_center(
    db: Database = Depends(get_db),
    user = Depends(require_workspace_member),
    limit: int = Query(20, ge=1, le=100),
):
    """Get high-priority items for command center dashboard."""
    workspace_id = get_workspace_id()
    if not workspace_id:
        raise HTTPException(status_code=401, detail="No workspace context")

    items = []

    # 1. Critical intent signals
    signals = await _detect_all_signals(db, workspace_id, SignalPriority.CRITICAL, None, limit)
    for signal in signals:
        items.append(CommandCenterItem(
            item_id=f"signal-{signal.company_id}",
            item_type="intent_signal",
            priority=signal.priority.value,
            company_id=signal.company_id,
            company_name=signal.company_name,
            title=f"{signal.signal_type.value.replace('_', ' ').title()} Detected",
            description=signal.description,
            action_required=signal.recommended_action,
            created_at=signal.signal_date,
            expires_at=signal.signal_date + timedelta(days=signal.action_urgency_days),
        ))

    # 2. High-priority HITL items
    hitl_result = (
        db.client.table("hitl_queue")
        .select("id, company_id, classification, created_at")
        .eq("workspace_id", workspace_id)
        .eq("status", "pending")
        .in_("classification", ["high_value", "deal_risk"])
        .order("created_at", desc=True)
        .limit(limit // 2)
        .execute()
    )

    for hitl_item in (hitl_result.data or []):
        company_result = (
            db.client.table("companies")
            .select("id, name")
            .eq("id", hitl_item["company_id"])
            .eq("workspace_id", workspace_id)
            .single()
            .execute()
        )

        if company_result.data:
            company = company_result.data
            items.append(CommandCenterItem(
                item_id=f"hitl-{hitl_item['id']}",
                item_type="hitl_queue",
                priority="high",
                company_id=company["id"],
                company_name=company["name"],
                title=f"HITL Review: {hitl_item['classification'].replace('_', ' ').title()}",
                description="Review and take action on this prospect",
                action_required="Review in HITL queue",
                created_at=datetime.fromisoformat(hitl_item["created_at"]),
            ))

    # 3. Upcoming meetings
    meeting_result = (
        db.client.table("meetings")
        .select("id, company_id, scheduled_at, title")
        .eq("workspace_id", workspace_id)
        .in_("status", ["scheduled", "confirmed"])
        .gte("scheduled_at", datetime.now(timezone.utc).isoformat())
        .lte("scheduled_at", (datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        .order("scheduled_at", desc=False)
        .limit(limit // 3)
        .execute()
    )

    for meeting in (meeting_result.data or []):
        company_result = (
            db.client.table("companies")
            .select("id, name")
            .eq("id", meeting["company_id"])
            .eq("workspace_id", workspace_id)
            .single()
            .execute()
        )

        if company_result.data:
            company = company_result.data
            items.append(CommandCenterItem(
                item_id=f"meeting-{meeting['id']}",
                item_type="meeting",
                priority="high",
                company_id=company["id"],
                company_name=company["name"],
                title=f"Meeting: {meeting.get('title', 'Scheduled')}",
                description=f"Scheduled for {meeting['scheduled_at']}",
                action_required="Prepare for meeting",
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(meeting["scheduled_at"]),
            ))

    # 4. At-risk deals
    deal_result = (
        db.client.table("deals")
        .select("id, company_id, title, stage, expected_close_date")
        .eq("workspace_id", workspace_id)
        .eq("stage", "negotiation")
        .order("expected_close_date", desc=False)
        .limit(limit // 5)
        .execute()
    )

    for deal in (deal_result.data or []):
        company_result = (
            db.client.table("companies")
            .select("id, name")
            .eq("id", deal["company_id"])
            .eq("workspace_id", workspace_id)
            .single()
            .execute()
        )

        if company_result.data:
            company = company_result.data
            items.append(CommandCenterItem(
                item_id=f"deal-{deal['id']}",
                item_type="deal",
                priority="medium",
                company_id=company["id"],
                company_name=company["name"],
                title=f"Deal in Negotiation: {deal['title']}",
                description="Actively working on deal closure",
                action_required="Follow up on proposal",
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(deal["expected_close_date"]) if deal.get("expected_close_date") else None,
            ))

    # Sort by priority and return limit
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda x: (priority_order.get(x.priority, 4), x.created_at), reverse=True)

    return {
        "total_items": len(items),
        "items": items[:limit],
        "critical_count": sum(1 for i in items if i.priority == "critical"),
        "high_count": sum(1 for i in items if i.priority == "high"),
    }


# ============================================================================
# Helper Functions
# ============================================================================


async def _detect_all_signals(
    db: Database,
    workspace_id: str,
    priority: Optional[SignalPriority] = None,
    signal_type: Optional[SignalType] = None,
    limit: int = 50,
) -> List[IntentSignal]:
    """Detect intent signals for all prospects in workspace."""
    signals = []

    # Get recent research activity (last 7 days)
    cutoff_recent = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    result = (
        db.client.table("companies")
        .select("id, name, updated_at")
        .eq("workspace_id", workspace_id)
        .gte("updated_at", cutoff_recent)
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )

    for company in (result.data or []):
        signals.append(IntentSignal(
            company_id=company["id"],
            company_name=company["name"],
            signal_type=SignalType.RECENT_RESEARCH,
            priority=SignalPriority.MEDIUM,
            description=f"Prospect was recently researched",
            signal_date=datetime.fromisoformat(company["updated_at"]),
            data={"updated_at": company["updated_at"]},
            recommended_action="Schedule discovery call",
            action_urgency_days=3,
        ))

    # Get high engagement prospects
    engagement_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    result = (
        db.client.table("companies")
        .select("id, name, pqs_total")
        .eq("workspace_id", workspace_id)
        .gte("pqs_total", 70)
        .execute()
    )

    for company in (result.data or []):
        # Check for recent contact engagement
        contact_activity = (
            db.client.table("outreach_drafts")
            .select("id, status")
            .eq("company_id", company["id"])
            .eq("workspace_id", workspace_id)
            .in_("status", ["sent", "opened"])
            .gte("created_at", engagement_cutoff)
            .limit(1)
            .execute()
        )

        if contact_activity.data:
            signals.append(IntentSignal(
                company_id=company["id"],
                company_name=company["name"],
                signal_type=SignalType.ENGAGEMENT_SPIKE,
                priority=SignalPriority.HIGH,
                description=f"Strong engagement: High PQS ({company['pqs_total']}) + recent opens",
                signal_date=datetime.now(timezone.utc),
                data={"pqs_score": company["pqs_total"]},
                recommended_action="Schedule demo or call",
                action_urgency_days=2,
            ))

    # Get companies with positive sentiment in recent interactions
    sentiment_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    result = (
        db.client.table("outreach_drafts")
        .select("company_id, approval_status")
        .eq("workspace_id", workspace_id)
        .in_("approval_status", ["replied_positive"])
        .gte("created_at", sentiment_cutoff)
        .execute()
    )

    seen_companies = set()
    for draft in (result.data or []):
        company_id = draft["company_id"]
        if company_id not in seen_companies:
            seen_companies.add(company_id)
            company_result = (
                db.client.table("companies")
                .select("id, name")
                .eq("id", company_id)
                .eq("workspace_id", workspace_id)
                .single()
                .execute()
            )

            if company_result.data:
                company = company_result.data
                signals.append(IntentSignal(
                    company_id=company["id"],
                    company_name=company["name"],
                    signal_type=SignalType.INBOUND_INTEREST,
                    priority=SignalPriority.CRITICAL,
                    description="Prospect showed positive interest in recent communication",
                    signal_date=datetime.now(timezone.utc),
                    data={"latest_status": "replied_positive"},
                    recommended_action="Call immediately or send proposal",
                    action_urgency_days=1,
                ))

    # Filter by priority/type if requested
    if priority:
        signals = [s for s in signals if s.priority == priority]
    if signal_type:
        signals = [s for s in signals if s.signal_type == signal_type]

    # Sort by priority and urgency
    priority_order = {SignalPriority.CRITICAL: 0, SignalPriority.HIGH: 1, SignalPriority.MEDIUM: 2, SignalPriority.LOW: 3}
    signals.sort(key=lambda x: (priority_order[x.priority], x.action_urgency_days))

    return signals[:limit]


async def _detect_signals_for_company(
    db: Database,
    workspace_id: str,
    company_id: int,
) -> List[IntentSignal]:
    """Detect intent signals for a specific company."""
    signals = []

    # Get company info
    company_result = (
        db.client.table("companies")
        .select("id, name, pqs_total, updated_at")
        .eq("id", company_id)
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )

    if not company_result.data:
        return signals

    company = company_result.data

    # Check recent research
    cutoff_recent = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    if company["updated_at"] >= cutoff_recent:
        signals.append(IntentSignal(
            company_id=company["id"],
            company_name=company["name"],
            signal_type=SignalType.RECENT_RESEARCH,
            priority=SignalPriority.MEDIUM,
            description="Prospect was recently researched in the system",
            signal_date=datetime.fromisoformat(company["updated_at"]),
            data={"updated_at": company["updated_at"]},
            recommended_action="Schedule discovery call",
            action_urgency_days=3,
        ))

    # Check high PQS
    if company["pqs_total"] >= 70:
        signals.append(IntentSignal(
            company_id=company["id"],
            company_name=company["name"],
            signal_type=SignalType.PQS_IMPROVEMENT,
            priority=SignalPriority.HIGH,
            description=f"Strong company fit with PQS score of {company['pqs_total']}",
            signal_date=datetime.now(timezone.utc),
            data={"pqs_score": company["pqs_total"]},
            recommended_action="Prioritize for outreach",
            action_urgency_days=7,
        ))

    # Check for positive sentiment
    sentiment_result = (
        db.client.table("outreach_drafts")
        .select("id, approval_status")
        .eq("company_id", company_id)
        .eq("workspace_id", workspace_id)
        .in_("approval_status", ["replied_positive"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if sentiment_result.data:
        signals.append(IntentSignal(
            company_id=company["id"],
            company_name=company["name"],
            signal_type=SignalType.INBOUND_INTEREST,
            priority=SignalPriority.CRITICAL,
            description="Prospect has shown positive interest in recent communication",
            signal_date=datetime.now(timezone.utc),
            data={"latest_status": "replied_positive"},
            recommended_action="Call immediately or send proposal",
            action_urgency_days=1,
        ))

    return signals
