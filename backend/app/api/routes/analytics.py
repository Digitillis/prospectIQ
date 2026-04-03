"""Analytics routes for ProspectIQ API.

Pipeline overview, API cost tracking, and outreach performance metrics.
Includes full Revenue Intelligence endpoints added in feature/analytics-revenue.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


@router.get("/pipeline")
async def get_pipeline_overview():
    """Get company counts by status for the pipeline funnel view."""
    db = get_db()
    counts = db.count_companies_by_status()
    return {"data": counts}


@router.get("/costs")
async def get_costs(batch_id: Optional[str] = None):
    """Get API cost summary, optionally filtered by batch_id."""
    db = get_db()
    costs = db.get_api_costs_summary(batch_id=batch_id)

    # Compute totals
    total_cost = sum(c.get("estimated_cost_usd", 0) for c in costs)
    total_input_tokens = sum(c.get("input_tokens", 0) or 0 for c in costs)
    total_output_tokens = sum(c.get("output_tokens", 0) or 0 for c in costs)

    return {
        "data": costs,
        "totals": {
            "cost_usd": round(total_cost, 4),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "records": len(costs),
        },
    }


@router.get("/performance")
async def get_performance(limit: int = Query(default=100, ge=1, le=1000)):
    """Get outreach performance metrics from learning outcomes."""
    db = get_db()
    outcomes = db.get_learning_outcomes(limit=limit)
    return {"data": outcomes, "count": len(outcomes)}


@router.get("/duplicates")
async def get_potential_duplicates():
    """Find companies with duplicate domains or very similar names."""
    db = get_db()
    # Get all companies with domains
    result = db._filter_ws(
        db.client.table("companies").select("id, name, domain, tier, status, pqs_total")
    ).not_.is_("domain", "null").order("domain").execute()

    companies = result.data
    duplicates = []

    # Group by domain
    domain_groups: dict = {}
    for c in companies:
        domain = (c.get("domain") or "").lower().strip()
        if not domain:
            continue
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(c)

    for domain, group in domain_groups.items():
        if len(group) > 1:
            duplicates.append({
                "type": "domain",
                "key": domain,
                "companies": group,
            })

    return {"data": duplicates, "total_duplicate_groups": len(duplicates)}


@router.get("/sequence-performance")
async def get_sequence_performance():
    """Get outreach performance broken down by sequence and step."""
    db = get_db()

    result = db._filter_ws(
        db.client.table("outreach_drafts").select("sequence_name, sequence_step, approval_status, channel")
    ).execute()

    sequences: dict = {}
    for draft in result.data:
        seq = draft.get("sequence_name") or "unknown"
        step = draft.get("sequence_step") or 0
        key = f"{seq}__step_{step}"

        if key not in sequences:
            sequences[key] = {
                "sequence_name": seq,
                "step": step,
                "channel": draft.get("channel") or "email",
                "total_drafts": 0,
                "approved": 0,
                "rejected": 0,
                "pending": 0,
            }

        sequences[key]["total_drafts"] += 1
        approval_status = draft.get("approval_status") or "pending"
        if approval_status == "approved":
            sequences[key]["approved"] += 1
        elif approval_status == "rejected":
            sequences[key]["rejected"] += 1
        else:
            sequences[key]["pending"] += 1

    sorted_data = sorted(sequences.values(), key=lambda s: (s["sequence_name"], s["step"]))
    return {"data": sorted_data}


@router.get("/competitive-risks")
async def get_competitive_risks():
    """Find researched companies that already use AI/ML competitors."""
    db = get_db()
    # Get research_intelligence entries with existing_solutions
    result = db._filter_ws(
        db.client.table("research_intelligence").select(
            "company_id, existing_solutions, companies(id, name, tier, status, pqs_total)"
        )
    ).not_.is_("existing_solutions", "null").execute()

    risks = []
    for r in result.data:
        solutions = r.get("existing_solutions") or []
        if solutions and len(solutions) > 0 and solutions != ["None found"]:
            risks.append({
                "company_id": r.get("company_id"),
                "company": r.get("companies"),
                "existing_solutions": solutions,
            })

    return {"data": risks, "total": len(risks)}


@router.get("/activity-feed")
async def get_activity_feed(limit: int = 50):
    """Get a unified activity feed from recent system events."""
    db = get_db()

    activities = []

    # Recent status changes (companies updated recently)
    companies = db._filter_ws(
        db.client.table("companies").select("id, name, status, tier, updated_at")
    ).order("updated_at", desc=True).limit(limit).execute()

    for c in companies.data:
        activities.append({
            "type": "status_change",
            "entity": "company",
            "entity_id": c["id"],
            "title": c["name"],
            "description": f"Status: {c['status']}",
            "tier": c.get("tier"),
            "timestamp": c["updated_at"],
        })

    # Recent outreach drafts
    drafts = db._filter_ws(
        db.client.table("outreach_drafts").select(
            "id, company_id, approval_status, sequence_name, sequence_step, created_at, companies(name, tier)"
        )
    ).order("created_at", desc=True).limit(limit).execute()

    for d in drafts.data:
        activities.append({
            "type": "outreach",
            "entity": "draft",
            "entity_id": d.get("company_id"),
            "title": d.get("companies", {}).get("name", "Unknown"),
            "description": f"{d['approval_status']} — {d['sequence_name']} step {d['sequence_step']}",
            "tier": d.get("companies", {}).get("tier"),
            "timestamp": d["created_at"],
        })

    # Recent API costs (agent runs)
    costs = db._filter_ws(
        db.client.table("api_costs").select("batch_id, provider, model, cost, created_at")
    ).order("created_at", desc=True).limit(20).execute()

    seen_batches = set()
    for c in costs.data:
        bid = c.get("batch_id", "")
        if bid in seen_batches:
            continue
        seen_batches.add(bid)
        agent = bid.split("_")[0] if "_" in bid else "unknown"
        activities.append({
            "type": "agent_run",
            "entity": "agent",
            "entity_id": None,
            "title": f"{agent.title()} agent",
            "description": f"via {c.get('provider', '?')} · ${c.get('cost', 0):.4f}",
            "tier": None,
            "timestamp": c["created_at"],
        })

    # Sort all by timestamp descending
    activities.sort(key=lambda a: a.get("timestamp", ""), reverse=True)

    return {"data": activities[:limit]}


@router.get("/data-quality")
async def get_data_quality():
    """Analyze data completeness across companies."""
    db = get_db()

    # Get all companies
    result = db._filter_ws(
        db.client.table("companies").select(
            "id, name, domain, tier, status, state, email, employee_count, revenue_range, industry"
        )
    ).execute()

    companies = result.data
    total = len(companies)

    # Count missing fields
    missing = {
        "domain": sum(1 for c in companies if not c.get("domain")),
        "tier": sum(1 for c in companies if not c.get("tier")),
        "state": sum(1 for c in companies if not c.get("state")),
        "industry": sum(1 for c in companies if not c.get("industry")),
        "employee_count": sum(1 for c in companies if not c.get("employee_count")),
        "revenue_range": sum(1 for c in companies if not c.get("revenue_range")),
    }

    # Get contact counts per company
    contacts = db._filter_ws(
        db.client.table("contacts").select("company_id")
    ).execute()
    companies_with_contacts = set(c["company_id"] for c in contacts.data)
    no_contacts = sum(1 for c in companies if c["id"] not in companies_with_contacts)
    missing["contacts"] = no_contacts

    # Companies with no email on any contact
    contacts_with_email = db._filter_ws(
        db.client.table("contacts").select("company_id, email")
    ).not_.is_("email", "null").execute()
    companies_with_email = set(c["company_id"] for c in contacts_with_email.data)
    no_email = sum(1 for c in companies if c["id"] not in companies_with_email)
    missing["contact_email"] = no_email

    # Completeness score per company
    fields = ["domain", "tier", "state", "industry", "employee_count", "revenue_range"]
    incomplete_companies = []
    for c in companies:
        missing_fields = [f for f in fields if not c.get(f)]
        has_contact = c["id"] in companies_with_contacts
        has_email = c["id"] in companies_with_email
        if not has_contact:
            missing_fields.append("contacts")
        if not has_email:
            missing_fields.append("contact_email")
        if missing_fields:
            incomplete_companies.append({
                "id": c["id"],
                "name": c["name"],
                "status": c.get("status"),
                "tier": c.get("tier"),
                "missing_fields": missing_fields,
                "completeness": round((1 - len(missing_fields) / 8) * 100),
            })

    incomplete_companies.sort(key=lambda c: c["completeness"])

    return {
        "data": {
            "total_companies": total,
            "field_coverage": {k: {"missing": v, "coverage": round((1 - v/max(total, 1)) * 100)} for k, v in missing.items()},
            "incomplete_companies": incomplete_companies[:50],
            "overall_completeness": round((1 - sum(missing.values()) / (total * 8)) * 100) if total else 0,
        }
    }


@router.get("/campaign-performance")
async def get_campaign_performance():
    """Analyze discovery campaign effectiveness."""
    db = get_db()
    result = db._filter_ws(
        db.client.table("companies").select("campaign_name, status, pqs_total, tier")
    ).not_.is_("campaign_name", "null").execute()

    campaigns: dict = {}
    for c in result.data:
        name = c.get("campaign_name", "unknown")
        if name not in campaigns:
            campaigns[name] = {"name": name, "total": 0, "statuses": {}, "avg_pqs": 0, "pqs_sum": 0, "tiers": {}}
        campaigns[name]["total"] += 1
        status = c.get("status", "unknown")
        campaigns[name]["statuses"][status] = campaigns[name]["statuses"].get(status, 0) + 1
        campaigns[name]["pqs_sum"] += c.get("pqs_total", 0) or 0
        tier = c.get("tier") or "none"
        campaigns[name]["tiers"][tier] = campaigns[name]["tiers"].get(tier, 0) + 1

    for camp in campaigns.values():
        camp["avg_pqs"] = round(camp["pqs_sum"] / max(camp["total"], 1), 1)
        del camp["pqs_sum"]
        # Compute advancement rate: qualified + outreach_pending + contacted + engaged + meeting + pilot stages
        advanced = sum(camp["statuses"].get(s, 0) for s in [
            "qualified", "outreach_pending", "contacted", "engaged",
            "meeting_scheduled", "pilot_discussion", "pilot_signed", "converted"
        ])
        camp["advancement_rate"] = round(advanced / max(camp["total"], 1) * 100, 1)

    return {"data": sorted(campaigns.values(), key=lambda c: c["advancement_rate"], reverse=True)}


@router.get("/agent-runs")
async def get_agent_runs():
    """Get agent run history grouped by batch_id from api_costs."""
    db = get_db()
    result = (
        db._filter_ws(db.client.table("api_costs").select("*"))
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )

    # Group cost entries by batch_id
    runs: dict[str, dict] = {}
    for entry in result.data:
        bid = entry.get("batch_id") or "unknown"

        # Derive agent name from batch_id prefix or endpoint
        endpoint = entry.get("endpoint") or ""
        provider = entry.get("provider") or "unknown"
        if bid.startswith("discovery_"):
            agent = "discovery"
        elif bid.startswith("research_"):
            agent = "research"
        elif bid.startswith("qualification_"):
            agent = "qualification"
        elif bid.startswith("outreach_"):
            agent = "outreach"
        elif bid.startswith("engagement_"):
            agent = "engagement"
        elif "discovery" in endpoint.lower():
            agent = "discovery"
        elif "research" in endpoint.lower():
            agent = "research"
        elif "qualification" in endpoint.lower():
            agent = "qualification"
        elif "outreach" in endpoint.lower():
            agent = "outreach"
        else:
            agent = provider

        if bid not in runs:
            runs[bid] = {
                "batch_id": bid,
                "agent": agent,
                "started_at": entry.get("created_at"),
                "total_cost": 0.0,
                "total_calls": 0,
                "companies_processed": set(),
                "providers": set(),
            }

        runs[bid]["total_cost"] += float(entry.get("estimated_cost_usd") or 0)
        runs[bid]["total_calls"] += 1
        if entry.get("company_id"):
            runs[bid]["companies_processed"].add(entry["company_id"])
        if entry.get("provider"):
            runs[bid]["providers"].add(entry["provider"])

        # Keep the earliest timestamp as started_at
        entry_ts = entry.get("created_at")
        if entry_ts and entry_ts < (runs[bid]["started_at"] or ""):
            runs[bid]["started_at"] = entry_ts

    # Convert sets to serialisable values and sort most-recent first
    serialised = []
    for run in runs.values():
        serialised.append(
            {
                "batch_id": run["batch_id"],
                "agent": run["agent"],
                "started_at": run["started_at"],
                "total_cost": round(run["total_cost"], 6),
                "total_calls": run["total_calls"],
                "companies_processed": len(run["companies_processed"]),
                "providers": sorted(run["providers"]),
            }
        )

    serialised.sort(key=lambda r: r.get("started_at") or "", reverse=True)

    total_cost = round(sum(r["total_cost"] for r in serialised), 6)
    return {
        "data": serialised,
        "totals": {
            "runs": len(serialised),
            "cost_usd": total_cost,
        },
    }


@router.get("/pipeline-velocity")
async def get_pipeline_velocity():
    """Compute average days companies spend in each pipeline stage."""
    db = get_db()
    result = db._filter_ws(
        db.client.table("companies").select("status, created_at, updated_at")
    ).execute()

    stage_durations: dict = {}
    for c in result.data:
        status = c.get("status", "unknown")
        created = c.get("created_at")
        updated = c.get("updated_at")
        if created and updated:
            from datetime import datetime
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days = (updated_dt - created_dt).total_seconds() / 86400
                if status not in stage_durations:
                    stage_durations[status] = []
                stage_durations[status].append(days)
            except (ValueError, TypeError):
                pass

    velocity = {}
    for status, durations in stage_durations.items():
        velocity[status] = {
            "avg_days": round(sum(durations) / len(durations), 1),
            "min_days": round(min(durations), 1),
            "max_days": round(max(durations), 1),
            "count": len(durations),
        }

    return {"data": velocity}


# ---------------------------------------------------------------------------
# Revenue Intelligence routes (feature/analytics-revenue)
# ---------------------------------------------------------------------------

@router.get("/funnel")
async def get_full_funnel(days: int = Query(default=90, ge=1, le=365)):
    """Full 10-stage funnel with conversion rates, drop-off, and bottleneck detection."""
    db = get_db()
    from backend.app.analytics.funnel import FunnelAnalytics
    fa = FunnelAnalytics(db)
    result = fa.get_full_funnel(workspace_id=db.workspace_id, days=days)
    return result.model_dump()


@router.get("/cohorts")
async def get_cohort_analysis(
    group_by: str = Query(default="cluster", pattern="^(cluster|tranche|persona|sequence_name)$"),
    days: int = Query(default=90, ge=1, le=365),
):
    """Cohort conversion performance grouped by cluster, tranche, persona, or sequence."""
    db = get_db()
    from backend.app.analytics.funnel import FunnelAnalytics
    fa = FunnelAnalytics(db)
    result = fa.get_cohort_analysis(workspace_id=db.workspace_id, group_by=group_by, days=days)
    return result.model_dump()


@router.get("/velocity")
async def get_velocity_metrics():
    """Stage-by-stage velocity in days with trend vs prior 30-day period."""
    db = get_db()
    from backend.app.analytics.funnel import FunnelAnalytics
    fa = FunnelAnalytics(db)
    result = fa.get_velocity_metrics(workspace_id=db.workspace_id)
    return result.model_dump()


@router.get("/revenue")
async def get_revenue_attribution(
    deal_size: float = Query(default=48000.0, ge=1000.0, le=10_000_000.0),
):
    """Pipeline-to-revenue attribution with projected ARR and confidence range."""
    db = get_db()
    from backend.app.analytics.revenue import RevenueAnalytics
    ra = RevenueAnalytics(db)
    result = ra.get_revenue_attribution(workspace_id=db.workspace_id, deal_size_usd=deal_size)
    return result.model_dump()


@router.get("/activity-roi")
async def get_activity_roi():
    """Reply rates by channel, sequence, persona, and cluster."""
    db = get_db()
    from backend.app.analytics.revenue import RevenueAnalytics
    ra = RevenueAnalytics(db)
    result = ra.get_activity_roi(workspace_id=db.workspace_id)
    return result.model_dump()


@router.get("/summary")
async def get_analytics_summary():
    """Combined analytics summary: top KPIs, funnel health, top cluster, projected ARR."""
    db = get_db()
    from backend.app.analytics.revenue import RevenueAnalytics
    ra = RevenueAnalytics(db)
    result = ra.get_analytics_summary(workspace_id=db.workspace_id)
    return result.model_dump()


@router.get("/benchmarks")
async def get_benchmarks(days: int = Query(default=30, ge=1, le=365)):
    """Compare actual outreach metrics vs target benchmarks.

    Targets (industry-calibrated for cold B2B outreach):
    - Reply rate:          18%
    - Open rate:           40%
    - Meeting rate:         3%
    - Positive reply rate:  8%
    - Cost per enriched lead: $0.15
    """
    import datetime
    db = get_db()
    client = db.client
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()

    TARGETS = {
        "reply_rate_pct": 18.0,
        "open_rate_pct": 40.0,
        "meeting_rate_pct": 3.0,
        "positive_reply_rate_pct": 8.0,
        "cost_per_enriched_lead_usd": 0.15,
    }

    # Approved outreach sent in period
    sent_result = (
        db._filter_ws(client.table("outreach_drafts").select("id", count="exact"))
        .eq("approval_status", "approved")
        .gte("created_at", since)
        .execute()
    )
    total_sent = sent_result.count or 0

    # Interactions — opens, replies, meetings
    interactions = (
        db._filter_ws(client.table("interactions").select("type"))
        .gte("created_at", since)
        .execute()
    ).data or []
    opens = sum(1 for i in interactions if i.get("type") == "email_opened")
    replies = sum(1 for i in interactions if i.get("type") == "email_replied")
    meetings = sum(1 for i in interactions if i.get("type") == "meeting")

    # Positive replies from learning outcomes
    outcomes = (
        db._filter_ws(client.table("learning_outcomes").select("outcome"))
        .gte("created_at", since)
        .execute()
    ).data or []
    positive_replies = sum(1 for o in outcomes if o.get("outcome") == "replied_positive")

    # Enrichment cost
    costs = (
        db._filter_ws(client.table("api_costs").select("estimated_cost_usd, endpoint"))
        .gte("created_at", since)
        .execute()
    ).data or []
    enrichment_cost = sum(
        r.get("estimated_cost_usd") or 0
        for r in costs
        if "enrich" in (r.get("endpoint") or "").lower()
    )

    enriched_count_result = (
        db._filter_ws(client.table("contacts").select("id", count="exact"))
        .not_.is_("email", "null")
        .gte("created_at", since)
        .execute()
    )
    enriched_count = enriched_count_result.count or 0

    def _pct(n: int, d: int) -> float | None:
        return round(n / d * 100, 1) if d > 0 else None

    actuals = {
        "reply_rate_pct": _pct(replies, total_sent),
        "open_rate_pct": _pct(opens, total_sent),
        "meeting_rate_pct": _pct(meetings, total_sent),
        "positive_reply_rate_pct": _pct(positive_replies, total_sent),
        "cost_per_enriched_lead_usd": (
            round(enrichment_cost / enriched_count, 4) if enriched_count > 0 else None
        ),
    }

    def _status(actual: float | None, target: float, higher_is_better: bool = True) -> str:
        if actual is None:
            return "no_data"
        ratio = actual / target if target else 0
        if higher_is_better:
            if ratio >= 1.0:
                return "on_target"
            if ratio >= 0.75:
                return "below_target"
            return "significantly_below"
        else:  # lower is better (cost metrics)
            if ratio <= 1.0:
                return "on_target"
            if ratio <= 1.5:
                return "above_target"
            return "significantly_above"

    metrics = {}
    for key, target in TARGETS.items():
        actual = actuals.get(key)
        is_cost = "cost" in key
        metrics[key] = {
            "target": target,
            "actual": actual,
            "status": _status(actual, target, higher_is_better=not is_cost),
            "delta": round(actual - target, 2) if actual is not None else None,
        }

    return {
        "data": {
            "period_days": days,
            "total_sent": total_sent,
            "metrics": metrics,
            "raw_counts": {
                "opens": opens,
                "replies": replies,
                "meetings": meetings,
                "positive_replies": positive_replies,
                "enriched_contacts": enriched_count,
                "enrichment_cost_usd": round(enrichment_cost, 4),
            },
        }
    }


@router.get("/ab-tests")
async def get_ab_tests():
    """Get A/B test stats for all tracked sequences."""
    from backend.app.analytics.ab_tracker import ABTracker
    db = get_db()
    tracker = ABTracker(db)

    result = (
        db._filter_ws(
            db.client.table("ab_test_events").select("sequence_id")
        )
        .execute()
    )
    sequence_ids = list({
        r["sequence_id"] for r in (result.data or []) if r.get("sequence_id")
    })

    stats = []
    for seq_id in sorted(sequence_ids):
        seq_stats = tracker.get_variant_stats(seq_id)
        winner = tracker.get_winning_variant(seq_id)
        stats.append({**seq_stats, "winner": winner})

    return {"data": stats, "count": len(stats)}


@router.get("/ab-tests/{sequence_id}")
async def get_ab_test(sequence_id: str):
    """Get A/B test stats for a specific sequence."""
    from backend.app.analytics.ab_tracker import ABTracker
    db = get_db()
    tracker = ABTracker(db)
    stats = tracker.get_variant_stats(sequence_id)
    winner = tracker.get_winning_variant(sequence_id)
    return {"data": {**stats, "winner": winner}}


@router.get("/cost-per-meeting")
async def get_cost_per_meeting(days: int = Query(default=90, ge=1, le=365)):
    """Return cost-per-meeting breakdown for the last N days.

    Aggregates:
    - total_cost_usd: all API costs (Anthropic, Perplexity, Apollo enrichment)
    - meetings_booked: interactions with type='meeting' in the window
    - cost_per_meeting_usd: total_cost / meetings (null if no meetings yet)
    - cost_breakdown: per-provider and per-model cost totals
    - meetings_pipeline: companies at meeting_scheduled / pilot_discussion / pilot_signed stage

    This is the north-star unit economic metric for the outreach program.
    """
    import datetime
    db = get_db()
    client = db.client
    workspace_id = db.workspace_id

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()

    # --- Total API costs ---
    costs_result = (
        db._filter_ws(client.table("api_costs").select("provider, model, estimated_cost_usd"))
        .gte("created_at", since)
        .execute()
    )
    costs_rows = costs_result.data or []
    total_cost = sum(r.get("estimated_cost_usd") or 0.0 for r in costs_rows)

    # Cost breakdown by provider + model
    breakdown: dict = {}
    for row in costs_rows:
        key = f"{row.get('provider', 'unknown')}/{row.get('model') or 'unknown'}"
        breakdown[key] = round(breakdown.get(key, 0.0) + (row.get("estimated_cost_usd") or 0.0), 6)

    # --- Meetings booked ---
    meetings_result = (
        db._filter_ws(
            client.table("interactions")
            .select("id, company_id, created_at", count="exact")
        )
        .eq("type", "meeting")
        .gte("created_at", since)
        .execute()
    )
    meetings_count = meetings_result.count or 0

    # --- Companies at advanced pipeline stages ---
    pipeline_result = (
        db._filter_ws(
            client.table("companies")
            .select("id, name, status, tier, pqs_total", count="exact")
        )
        .in_("status", ["meeting_scheduled", "pilot_discussion", "pilot_signed", "active_pilot", "converted"])
        .execute()
    )
    pipeline_companies = pipeline_result.data or []

    cost_per_meeting = (
        round(total_cost / meetings_count, 2) if meetings_count > 0 else None
    )

    return {
        "data": {
            "period_days": days,
            "total_cost_usd": round(total_cost, 4),
            "meetings_booked": meetings_count,
            "cost_per_meeting_usd": cost_per_meeting,
            "cost_breakdown": breakdown,
            "meetings_pipeline": {
                "count": len(pipeline_companies),
                "companies": pipeline_companies,
            },
        }
    }
