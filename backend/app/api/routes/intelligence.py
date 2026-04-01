"""Intelligence API routes for ProspectIQ.

Aggregated analytics, intent signals, funnel metrics, pipeline velocity,
cost breakdowns, and weekly cadence goals.

Endpoints:
    GET /api/intelligence/signals      — intent signals + buying signals
    GET /api/intelligence/funnel       — full funnel counts + conversion rates
    GET /api/intelligence/velocity     — pipeline velocity (days per stage)
    GET /api/intelligence/costs        — API cost breakdown
    GET /api/intelligence/weekly       — weekly activity for sparklines
    GET /api/intelligence/goals        — get/set weekly cadence goals
    PUT /api/intelligence/goals        — update weekly goals
    GET /api/command-center            — combined dashboard payload
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["intelligence"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GoalsUpdateRequest(BaseModel):
    researched_target: Optional[int] = None
    emails_sent_target: Optional[int] = None
    replies_target: Optional[int] = None
    meetings_target: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_count(db: Database, table: str, filters: dict | None = None, not_null: str | None = None, is_null: str | None = None) -> int:
    """Count rows in a table, returning 0 on any error."""
    try:
        q = db._filter_ws(db.client.table(table).select("id", count="exact"))
        if filters:
            for k, v in filters.items():
                q = q.eq(k, v)
        if not_null:
            q = q.not_.is_(not_null, "null")
        if is_null:
            q = q.is_(is_null, "null")
        result = q.execute()
        return result.count or 0
    except Exception:
        return 0


def _get_company_counts(db: Database) -> dict[str, int]:
    """Count companies by status efficiently."""
    try:
        rows = db._filter_ws(db.client.table("companies").select("status")).execute().data or []
        counts: dict[str, int] = {}
        for r in rows:
            s = r.get("status") or "unknown"
            counts[s] = counts.get(s, 0) + 1
        return counts
    except Exception:
        return {}


def _get_weekly_goals(db: Database) -> dict:
    """Get weekly goals from app_settings, defaulting to sensible values."""
    defaults = {
        "researched_target": 50,
        "emails_sent_target": 30,
        "replies_target": 5,
        "meetings_target": 2,
    }
    try:
        result = db.client.table("app_settings").select("value").eq("key", "weekly_goals").execute()
        if result.data:
            stored = result.data[0].get("value") or {}
            return {**defaults, **stored}
    except Exception:
        pass
    return defaults


def _get_week_start() -> str:
    """ISO date for start of current week (Monday)."""
    today = datetime.now(timezone.utc)
    monday = today - __import__("datetime").timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d") + "T00:00:00+00:00"


def _get_weekly_actuals(db: Database) -> dict[str, int]:
    """Count activity this week."""
    week_start = _get_week_start()
    actuals: dict[str, int] = {
        "researched": 0,
        "emails_sent": 0,
        "replies": 0,
        "meetings": 0,
    }

    try:
        # Researched this week: companies where research was created this week
        r = (
            db._filter_ws(db.client.table("research").select("id", count="exact"))
            .gte("created_at", week_start)
            .execute()
        )
        actuals["researched"] = r.count or 0
    except Exception:
        pass

    try:
        # Emails sent: outreach drafts sent this week
        r = (
            db._filter_ws(db.client.table("outreach_drafts").select("id", count="exact"))
            .gte("sent_at", week_start)
            .not_.is_("sent_at", "null")
            .execute()
        )
        actuals["emails_sent"] = r.count or 0
    except Exception:
        pass

    try:
        # Replies: contacts whose outreach_state changed to 'replied' this week
        r = (
            db._filter_ws(db.client.table("outreach_state_log").select("id", count="exact"))
            .eq("to_state", "replied")
            .gte("created_at", week_start)
            .execute()
        )
        actuals["replies"] = r.count or 0
    except Exception:
        pass

    try:
        # Meetings: demo_scheduled transitions this week
        r = (
            db._filter_ws(db.client.table("outreach_state_log").select("id", count="exact"))
            .eq("to_state", "demo_scheduled")
            .gte("created_at", week_start)
            .execute()
        )
        actuals["meetings"] = r.count or 0
    except Exception:
        pass

    return actuals


def _get_cost_breakdown(db: Database) -> dict:
    """Get API cost summary for current month."""
    try:
        costs = db.get_api_costs_summary()
        total = sum(c.get("estimated_cost_usd", 0) for c in costs)
        by_agent: dict[str, float] = {}
        for c in costs:
            agent = c.get("agent_name") or "unknown"
            by_agent[agent] = by_agent.get(agent, 0) + (c.get("estimated_cost_usd") or 0)

        research_cost = sum(v for k, v in by_agent.items() if "research" in k.lower() or "discovery" in k.lower())
        draft_cost = sum(v for k, v in by_agent.items() if "outreach" in k.lower() or "draft" in k.lower() or "thread" in k.lower())

        return {
            "total_usd": round(total, 4),
            "research_usd": round(research_cost, 4),
            "drafts_usd": round(draft_cost, 4),
            "by_agent": {k: round(v, 4) for k, v in by_agent.items()},
            "monthly_cap_usd": 200.0,
            "pct_of_cap": round(min(total / 200.0 * 100, 999), 1),
        }
    except Exception:
        return {
            "total_usd": 0.0,
            "research_usd": 0.0,
            "drafts_usd": 0.0,
            "by_agent": {},
            "monthly_cap_usd": 200.0,
            "pct_of_cap": 0.0,
        }


def _get_threads_needing_action(db: Database, limit: int = 5) -> list[dict]:
    """Get threads needing human review."""
    try:
        result = (
            db.client.table("campaign_threads")
            .select(
                "id, status, current_step, updated_at, "
                "companies(id, name, tier, pqs_total, campaign_cluster), "
                "contacts(id, full_name, title, email, persona_type)"
            )
            .in_("status", ["paused"])
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        threads = result.data or []

        # Get last inbound message for each
        enriched = []
        for t in threads:
            try:
                msg_result = (
                    db.client.table("thread_messages")
                    .select("*")
                    .eq("thread_id", t["id"])
                    .eq("direction", "inbound")
                    .order("sent_at", desc=True)
                    .limit(1)
                    .execute()
                )
                last_msg = msg_result.data[0] if msg_result.data else None
                t["last_inbound"] = last_msg
                t["classification"] = last_msg.get("classification") if last_msg else None
            except Exception:
                t["last_inbound"] = None
                t["classification"] = None
            enriched.append(t)
        return enriched
    except Exception as exc:
        logger.debug(f"Could not fetch reply queue (threads table may not exist): {exc}")
        return []


def _get_pending_drafts_top(db: Database, limit: int = 5) -> list[dict]:
    """Get top pending drafts by PQS."""
    try:
        result = (
            db._filter_ws(
                db.client.table("outreach_drafts")
                .select(
                    "id, subject, body, sequence_name, sequence_step, created_at, quality_score, "
                    "companies(id, name, tier, pqs_total, campaign_cluster), "
                    "contacts(id, full_name, title, persona_type)"
                )
            )
            .eq("approval_status", "pending")
            .is_("sent_at", "null")
            .order("created_at", desc=True)
            .limit(limit * 5)
            .execute()
        )
        drafts = result.data or []
        # Sort by PQS
        drafts.sort(key=lambda d: (d.get("companies") or {}).get("pqs_total") or 0, reverse=True)
        return drafts[:limit]
    except Exception:
        return []


def _get_hot_signals_top(db: Database, limit: int = 5) -> list[dict]:
    """Get top companies by intent_score."""
    try:
        result = (
            db._filter_ws(
                db.client.table("companies")
                .select("id, name, tier, pqs_total, campaign_cluster, status, intent_score, research_summary, pain_signals")
            )
            .gt("intent_score", 0)
            .in_("status", ["discovered", "qualified", "researched"])
            .order("intent_score", desc=True)
            .limit(limit)
            .execute()
        )
        companies = result.data or []
        for c in companies:
            score = c.get("intent_score") or 0
            if score >= 20:
                c["intent_level"] = "hot"
            elif score >= 12:
                c["intent_level"] = "warm"
            elif score >= 5:
                c["intent_level"] = "warming"
            else:
                c["intent_level"] = "cold"
        return companies
    except Exception:
        return []


def _get_billing_status(db: Database) -> dict:
    """Get billing tier and usage percentage."""
    try:
        from backend.app.core.config import get_settings
        settings = get_settings()
        workspace_id = get_workspace_id()

        # Get current month company count
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0).isoformat()
        r = (
            db._filter_ws(db.client.table("companies").select("id", count="exact"))
            .gte("created_at", month_start)
            .execute()
        )
        companies_this_month = r.count or 0

        # Get workspace billing tier
        try:
            ws_result = db.client.table("workspaces").select("billing_tier").eq("id", workspace_id).limit(1).execute()
            tier = (ws_result.data[0].get("billing_tier") or "starter") if ws_result.data else "starter"
        except Exception:
            tier = "starter"

        limits = {"starter": 200, "growth": 2000, "scale": 10000, "api": 50000}
        limit = limits.get(tier, 200)
        usage_pct = round(companies_this_month / limit * 100, 1) if limit else 0

        return {
            "tier": tier,
            "companies_this_month": companies_this_month,
            "companies_limit": limit,
            "usage_pct": usage_pct,
            "over_limit": companies_this_month > limit,
            "approaching_limit": usage_pct >= 80,
        }
    except Exception:
        return {
            "tier": "starter",
            "companies_this_month": 0,
            "companies_limit": 200,
            "usage_pct": 0.0,
            "over_limit": False,
            "approaching_limit": False,
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/intelligence/signals")
async def get_signals():
    """Intent signals (research-detected) and buying signals (behavioral)."""
    db = get_db()

    # Intent signals from companies with intent_score > 0
    intent_signals = []
    try:
        rows = (
            db._filter_ws(
                db.client.table("companies")
                .select("id, name, tier, pqs_total, campaign_cluster, status, intent_score, pain_signals, personalization_hooks, research_summary")
            )
            .gt("intent_score", 0)
            .order("intent_score", desc=True)
            .limit(50)
            .execute()
        ).data or []

        for c in rows:
            score = c.get("intent_score") or 0
            level = "hot" if score >= 20 else "warm" if score >= 12 else "warming"
            pain = c.get("pain_signals") or []
            if isinstance(pain, str):
                import json
                try:
                    pain = json.loads(pain)
                except Exception:
                    pain = [pain]
            intent_signals.append({
                "company_id": c["id"],
                "company_name": c.get("name", "Unknown"),
                "tier": c.get("tier"),
                "pqs_total": c.get("pqs_total") or 0,
                "cluster": c.get("campaign_cluster"),
                "status": c.get("status"),
                "intent_score": score,
                "intent_level": level,
                "pain_signals": pain[:3] if isinstance(pain, list) else [],
                "research_summary": (c.get("research_summary") or "")[:150],
            })
    except Exception as exc:
        logger.warning(f"Intent signals query failed: {exc}")

    # Buying signals from engagement (opens/clicks)
    buying_signals = []
    try:
        rows = (
            db._filter_ws(
                db.client.table("contacts")
                .select(
                    "id, full_name, title, persona_type, outreach_state, open_count, click_count, "
                    "companies(id, name, tier, pqs_total, campaign_cluster)"
                )
            )
            .gt("open_count", 2)
            .in_("outreach_state", ["touch_1_sent", "touch_2_sent", "touch_3_sent", "touch_4_sent", "touch_5_sent"])
            .order("open_count", desc=True)
            .limit(20)
            .execute()
        ).data or []

        for r in rows:
            opens = r.get("open_count") or 0
            clicks = r.get("click_count") or 0
            score = opens * 2 + clicks * 5
            level = "hot" if score >= 20 else "warm" if score >= 8 else "warming"
            signal = "link click detected" if clicks > 0 else f"{opens} email opens"
            company = r.get("companies") or {}
            buying_signals.append({
                "contact_id": r["id"],
                "contact_name": r.get("full_name"),
                "title": r.get("title"),
                "persona_type": r.get("persona_type"),
                "company_id": company.get("id"),
                "company_name": company.get("name"),
                "tier": company.get("tier"),
                "pqs_total": company.get("pqs_total") or 0,
                "cluster": company.get("campaign_cluster"),
                "open_count": opens,
                "click_count": clicks,
                "signal_description": signal,
                "intent_level": level,
                "outreach_state": r.get("outreach_state"),
            })
    except Exception as exc:
        logger.debug(f"Buying signals query failed: {exc}")

    return {
        "intent_signals": intent_signals,
        "buying_signals": buying_signals,
        "total_hot": sum(1 for s in intent_signals if s["intent_level"] == "hot"),
        "total_warm": sum(1 for s in intent_signals if s["intent_level"] == "warm"),
    }


@router.get("/api/intelligence/funnel")
async def get_funnel(days: int = Query(default=30, ge=1, le=365)):
    """Full funnel counts and conversion rates."""
    db = get_db()
    from backend.app.analytics.funnel import FunnelAnalytics
    fa = FunnelAnalytics(db)
    funnel = fa.get_funnel_counts(days=days)
    reply_by_vertical = fa.get_reply_rate_by_vertical(days=days)
    reply_by_persona = fa.get_reply_rate_by_persona(days=days)
    return {
        "funnel": funnel,
        "by_vertical": reply_by_vertical,
        "by_persona": reply_by_persona,
    }


@router.get("/api/intelligence/velocity")
async def get_velocity():
    """Pipeline velocity in days per stage."""
    db = get_db()
    from backend.app.analytics.funnel import FunnelAnalytics
    fa = FunnelAnalytics(db)
    velocity = fa.get_pipeline_velocity()
    return {"data": velocity}


@router.get("/api/intelligence/costs")
async def get_costs_intelligence():
    """API cost breakdown by agent and totals for current month."""
    db = get_db()
    breakdown = _get_cost_breakdown(db)

    # Weekly spend trend
    try:
        from backend.app.analytics.funnel import FunnelAnalytics
        fa = FunnelAnalytics(db)
        weekly = fa.get_weekly_activity(weeks=8)
    except Exception:
        weekly = []

    # Get Anthropic API balance if configured
    anthropic_balance = None
    try:
        from backend.app.core.config import get_settings
        settings = get_settings()
        if settings.anthropic_api_key:
            import httpx
            resp = httpx.get(
                "https://api.anthropic.com/v1/account/credits",
                headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                anthropic_balance = round(data.get("credits", 0) / 100, 2)
    except Exception:
        pass

    return {
        "data": breakdown,
        "anthropic_balance_usd": anthropic_balance,
        "weekly_trend": weekly,
    }


@router.get("/api/intelligence/weekly")
async def get_weekly_activity(weeks: int = Query(default=8, ge=1, le=52)):
    """Weekly activity for sparklines."""
    db = get_db()
    from backend.app.analytics.funnel import FunnelAnalytics
    fa = FunnelAnalytics(db)
    weekly = fa.get_weekly_activity(weeks=weeks)
    return {"data": weekly}


@router.get("/api/intelligence/goals")
async def get_goals():
    """Get weekly cadence goals and current week actuals."""
    db = get_db()
    goals = _get_weekly_goals(db)
    actuals = _get_weekly_actuals(db)
    return {
        "targets": goals,
        "actuals": actuals,
        "week_start": _get_week_start()[:10],
    }


@router.put("/api/intelligence/goals")
async def update_goals(body: GoalsUpdateRequest):
    """Update weekly cadence goals."""
    db = get_db()

    current = _get_weekly_goals(db)
    update = body.model_dump(exclude_none=True)
    merged = {**current, **update}

    try:
        # Try upsert into app_settings
        existing = db.client.table("app_settings").select("id").eq("key", "weekly_goals").execute()
        if existing.data:
            db.client.table("app_settings").update({"value": merged}).eq("key", "weekly_goals").execute()
        else:
            db.client.table("app_settings").insert({"key": "weekly_goals", "value": merged}).execute()
    except Exception as exc:
        logger.warning(f"Could not persist goals (app_settings may not have 'value' column): {exc}")

    return {"data": merged, "message": "Goals updated"}


@router.get("/api/command-center")
async def get_command_center():
    """Single combined payload for the Command Center page."""
    db = get_db()

    # Company counts
    company_counts = _get_company_counts(db)
    total_companies = sum(company_counts.values())

    researched_statuses = {"researched", "qualified", "contacted", "engaged", "outreach_pending"}
    researched_count = sum(company_counts.get(s, 0) for s in researched_statuses)

    active_outreach_statuses = {"contacted", "engaged", "outreach_pending"}
    active_outreach = sum(company_counts.get(s, 0) for s in active_outreach_statuses)

    # Replies this week
    week_start = _get_week_start()
    replies_this_week = 0
    try:
        r = (
            db._filter_ws(db.client.table("outreach_state_log").select("id", count="exact"))
            .eq("to_state", "replied")
            .gte("created_at", week_start)
            .execute()
        )
        replies_this_week = r.count or 0
    except Exception:
        pass

    meetings_booked = 0
    try:
        r = (
            db._filter_ws(db.client.table("outreach_state_log").select("id", count="exact"))
            .eq("to_state", "demo_scheduled")
            .gte("created_at", week_start)
            .execute()
        )
        meetings_booked = r.count or 0
    except Exception:
        pass

    # Cost this month
    cost_data = _get_cost_breakdown(db)

    kpis = {
        "pipeline_total": total_companies,
        "researched": researched_count,
        "researched_pct": round(researched_count / max(total_companies, 1) * 100, 1),
        "active_outreach": active_outreach,
        "replies_this_week": replies_this_week,
        "meetings_booked": meetings_booked,
        "ai_cost_month": cost_data["total_usd"],
        "ai_cost_cap": cost_data["monthly_cap_usd"],
        "ai_cost_pct": cost_data["pct_of_cap"],
    }

    # Attention items
    pending_drafts_count = _safe_count(db, "outreach_drafts", {"approval_status": "pending"}, is_null="sent_at")
    threads_needing_action = _get_threads_needing_action(db, limit=5)
    hot_signals_count = 0
    try:
        r = db._filter_ws(db.client.table("companies").select("id", count="exact")).gt("intent_score", 15).execute()
        hot_signals_count = r.count or 0
    except Exception:
        pass

    attention_items: list[dict] = []
    if len(threads_needing_action) > 0:
        attention_items.append({
            "type": "replies",
            "count": len(threads_needing_action),
            "label": f"{len(threads_needing_action)} {'reply needs' if len(threads_needing_action) == 1 else 'replies need'} classification",
            "href": "/threads",
        })
    if pending_drafts_count > 0:
        attention_items.append({
            "type": "drafts",
            "count": pending_drafts_count,
            "label": f"{pending_drafts_count} {'draft' if pending_drafts_count == 1 else 'drafts'} ready to approve",
            "href": "/outreach",
        })
    if hot_signals_count > 0:
        attention_items.append({
            "type": "signals",
            "count": hot_signals_count,
            "label": f"{hot_signals_count} {'company flagged' if hot_signals_count == 1 else 'companies flagged'} hot",
            "href": "/signals",
        })

    # Funnel summary
    funnel_summary: dict[str, Any] = {}
    try:
        from backend.app.analytics.funnel import FunnelAnalytics
        fa = FunnelAnalytics(db)
        funnel_summary = fa.get_funnel_counts(days=30)
    except Exception:
        pass

    # Weekly goals
    goals = _get_weekly_goals(db)
    actuals = _get_weekly_actuals(db)

    # Billing
    billing = _get_billing_status(db)

    return {
        "attention_items": attention_items,
        "kpis": kpis,
        "reply_queue": threads_needing_action,
        "draft_queue": _get_pending_drafts_top(db, limit=5),
        "hot_signals": _get_hot_signals_top(db, limit=5),
        "funnel_summary": funnel_summary,
        "weekly_goals": {"targets": goals, "actuals": actuals},
        "billing_status": billing,
    }
