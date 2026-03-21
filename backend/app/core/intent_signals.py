"""Intent signal detection and scoring.

Layers buying-intent signals on top of the static PQS score to identify
prospects who are actively in-market RIGHT NOW. This is the difference
between "good ICP fit" (firmographic) and "ready to buy" (intent).

Signal sources:
1. Apollo intent data (technology adoption signals, hiring signals)
2. Engagement velocity (multiple opens/clicks in short window)
3. Research-extracted timing signals (job postings, capex announcements)
4. Website visitor matching (future: when Plausible/analytics is wired)

The intent score is a multiplier on PQS, not a replacement:
- PQS tells you WHO to target (fit)
- Intent tells you WHEN to target (timing)
- Combined: prioritize outreach to high-fit + high-intent prospects
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from backend.app.core.database import Database

logger = logging.getLogger(__name__)


@dataclass
class IntentSignal:
    """A single detected intent signal."""
    signal_type: str        # e.g., "hiring_digital", "multi_open", "capex"
    strength: str           # "strong", "moderate", "weak"
    points: int             # 1-10
    evidence: str           # Human-readable evidence
    source: str             # "apollo", "engagement", "research"


@dataclass
class IntentReport:
    """Aggregated intent analysis for a company."""
    company_id: str
    company_name: str
    signals: list[IntentSignal] = field(default_factory=list)
    total_score: int = 0
    intent_level: str = "cold"  # cold, warming, warm, hot

    def add_signal(self, signal: IntentSignal) -> None:
        self.signals.append(signal)
        self.total_score += signal.points
        # Recalculate level
        if self.total_score >= 20:
            self.intent_level = "hot"
        elif self.total_score >= 12:
            self.intent_level = "warm"
        elif self.total_score >= 5:
            self.intent_level = "warming"
        else:
            self.intent_level = "cold"


def analyze_intent(
    db: Database,
    company_id: str,
    company: dict | None = None,
) -> IntentReport:
    """Analyze all available intent signals for a company.

    Args:
        db: Database instance.
        company_id: Company to analyze.
        company: Pre-fetched company dict (optional, avoids extra query).

    Returns:
        IntentReport with all detected signals.
    """
    if not company:
        company = db.get_company(company_id)
    if not company:
        return IntentReport(company_id=company_id, company_name="Unknown")

    report = IntentReport(
        company_id=company_id,
        company_name=company.get("name", "Unknown"),
    )

    # 1. Apollo intent signals (from discovery data)
    _check_apollo_signals(company, report)

    # 2. Engagement velocity (from interactions)
    _check_engagement_velocity(db, company_id, report)

    # 3. Research-extracted timing signals
    _check_research_signals(db, company_id, company, report)

    # 4. Hiring signals (from Apollo headcount growth)
    _check_hiring_signals(company, report)

    return report


def _check_apollo_signals(company: dict, report: IntentReport) -> None:
    """Check Apollo-provided intent and technology signals."""
    # Apollo provides headcount growth rates
    growth_6m = company.get("headcount_six_month_growth") or 0
    growth_12m = company.get("headcount_twelve_month_growth") or 0

    if growth_6m > 0.15:
        report.add_signal(IntentSignal(
            signal_type="rapid_growth",
            strength="strong",
            points=7,
            evidence=f"Headcount grew {growth_6m:.0%} in 6 months — active expansion",
            source="apollo",
        ))
    elif growth_6m > 0.05:
        report.add_signal(IntentSignal(
            signal_type="steady_growth",
            strength="moderate",
            points=3,
            evidence=f"Headcount grew {growth_6m:.0%} in 6 months",
            source="apollo",
        ))

    # Negative growth can also be a signal (cost-cutting → need efficiency tools)
    if growth_6m < -0.10:
        report.add_signal(IntentSignal(
            signal_type="workforce_reduction",
            strength="moderate",
            points=4,
            evidence=f"Headcount declined {abs(growth_6m):.0%} in 6 months — may need automation",
            source="apollo",
        ))


def _check_engagement_velocity(
    db: Database, company_id: str, report: IntentReport
) -> None:
    """Detect buying signals from engagement patterns.

    Multiple opens/clicks in a short window = actively evaluating.
    """
    # Look at last 14 days of interactions
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

    interactions = (
        db.client.table("interactions")
        .select("type, created_at")
        .eq("company_id", company_id)
        .in_("type", ["email_opened", "email_clicked", "email_replied"])
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
        .data
    )

    if not interactions:
        return

    opens = [i for i in interactions if i["type"] == "email_opened"]
    clicks = [i for i in interactions if i["type"] == "email_clicked"]
    replies = [i for i in interactions if i["type"] == "email_replied"]

    # Multiple opens = reading carefully
    if len(opens) >= 3:
        report.add_signal(IntentSignal(
            signal_type="multi_open",
            strength="strong",
            points=8,
            evidence=f"{len(opens)} email opens in 14 days — actively reading",
            source="engagement",
        ))
    elif len(opens) >= 2:
        report.add_signal(IntentSignal(
            signal_type="repeat_open",
            strength="moderate",
            points=4,
            evidence=f"{len(opens)} email opens in 14 days",
            source="engagement",
        ))

    # Any click = very high intent
    if clicks:
        report.add_signal(IntentSignal(
            signal_type="link_click",
            strength="strong",
            points=10,
            evidence=f"{len(clicks)} link click(s) — actively exploring",
            source="engagement",
        ))

    # Reply = highest possible intent (but these already change status)
    if replies:
        report.add_signal(IntentSignal(
            signal_type="reply",
            strength="strong",
            points=10,
            evidence=f"Replied to outreach",
            source="engagement",
        ))


def _check_research_signals(
    db: Database, company_id: str, company: dict, report: IntentReport
) -> None:
    """Extract intent from research intelligence."""
    research = db.get_research(company_id)
    if not research:
        return

    # Check for high-intent research indicators
    pain_points = research.get("pain_points") or []
    opportunities = research.get("opportunities") or []
    dt_status = (research.get("digital_transformation_status") or "").lower()

    # Active digital transformation = budget allocated
    if any(kw in dt_status for kw in [
        "active", "in progress", "recently launched", "implementing",
        "invested in", "piloting", "evaluating",
    ]):
        report.add_signal(IntentSignal(
            signal_type="active_digital_transformation",
            strength="strong",
            points=8,
            evidence=f"Digital transformation: {dt_status[:100]}",
            source="research",
        ))

    # Specific pain points that align with Digitillis
    high_intent_pains = {
        "downtime", "unplanned", "reactive maintenance", "equipment failure",
        "compliance", "fsma", "haccp", "audit", "recall",
        "quality", "defect", "scrap",
    }
    matching_pains = [
        p for p in pain_points
        if any(kw in p.lower() for kw in high_intent_pains)
    ]
    if matching_pains:
        report.add_signal(IntentSignal(
            signal_type="aligned_pain_points",
            strength="strong" if len(matching_pains) >= 2 else "moderate",
            points=6 if len(matching_pains) >= 2 else 3,
            evidence=f"Pain points: {', '.join(matching_pains[:3])}",
            source="research",
        ))

    # IoT maturity = readiness to adopt
    iot_maturity = research.get("iot_maturity", "none")
    if iot_maturity in ("intermediate", "advanced"):
        report.add_signal(IntentSignal(
            signal_type="iot_ready",
            strength="moderate",
            points=4,
            evidence=f"IoT maturity: {iot_maturity} — infrastructure ready for AI layer",
            source="research",
        ))

    # Funding/investment = budget available
    funding = research.get("funding_status") or ""
    if any(kw in funding.lower() for kw in [
        "raised", "funded", "invested", "series", "growth equity",
    ]):
        report.add_signal(IntentSignal(
            signal_type="recent_funding",
            strength="moderate",
            points=5,
            evidence=f"Funding: {funding[:100]}",
            source="research",
        ))


def _check_hiring_signals(company: dict, report: IntentReport) -> None:
    """Detect hiring-related intent signals.

    Companies hiring for digital/automation/maintenance roles
    are actively investing in operational technology.
    """
    # This would ideally check Apollo job postings API
    # For now, check the personalization_hooks for hiring mentions
    hooks = company.get("personalization_hooks") or []
    for hook in hooks:
        hook_lower = hook.lower()
        if any(kw in hook_lower for kw in [
            "hired", "appointed", "new role", "joined as",
            "head of digital", "vp digital", "director of innovation",
            "chief digital", "head of automation",
        ]):
            report.add_signal(IntentSignal(
                signal_type="hiring_digital_role",
                strength="strong",
                points=7,
                evidence=hook[:150],
                source="research",
            ))
            break  # Only count once


def prioritize_by_intent(
    db: Database,
    company_ids: list[str],
) -> list[tuple[str, IntentReport]]:
    """Score and rank a list of companies by intent signals.

    Args:
        db: Database instance.
        company_ids: Companies to analyze.

    Returns:
        List of (company_id, IntentReport) sorted by intent score descending.
    """
    reports = []
    for cid in company_ids:
        report = analyze_intent(db, cid)
        reports.append((cid, report))

    # Sort by intent score (highest first)
    reports.sort(key=lambda x: x[1].total_score, reverse=True)
    return reports
