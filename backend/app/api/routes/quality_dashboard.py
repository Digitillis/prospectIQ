"""Quality Dashboard API — leading indicator metrics for outreach health.

Endpoints:
  GET /api/quality/metrics      — rolling rate metrics (bounce, reply, wrong-person)
  GET /api/quality/signals      — recent company signals by type
  GET /api/quality/assertions   — recent pre-send assertion failures
  GET /api/quality/outcomes     — reply classification breakdown
  GET /api/quality/contacts     — CCS distribution and gate pass rates

All metrics are rate-based, not volume-based. The primary metric is
reply_rate × meeting_conversion_rate — not emails sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from backend.app.core.database import Database
from backend.app.api.dependencies import get_db

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/metrics")
def get_quality_metrics(
    days: int = Query(default=7, ge=1, le=90),
    db: Database = Depends(get_db),
):
    """Rolling rate metrics over the past N days.

    Key metrics (all rate-based):
    - hard_bounce_rate: > 2% → pause sending immediately
    - wrong_person_reply_rate: > 1% → audit email-name check
    - reply_rate: primary leading indicator
    - meeting_conversion_rate: reply → meeting booked rate
    - assertion_failure_rate: % of draft attempts blocked by pre-send assertions

    Alert thresholds returned alongside each metric.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Total sends in window
    sent_result = (
        db.client.table("outreach_outcomes")
        .select("id", count="exact")
        .gte("sent_at", since)
        .execute()
    )
    total_sent = sent_result.count or 0

    # Outcomes with reply data
    outcomes = (
        db.client.table("outreach_outcomes")
        .select(
            "reply_sentiment,reply_classification,wrong_person_flag,"
            "replied_at,meeting_booked_at,sent_at"
        )
        .gte("created_at", since)
        .execute()
        .data or []
    )

    replied = [o for o in outcomes if o.get("replied_at")]
    wrong_person = [o for o in outcomes if o.get("wrong_person_flag")]
    meetings = [o for o in outcomes if o.get("meeting_booked_at")]
    interested = [o for o in replied if o.get("reply_classification") in ("interested", "meeting_request")]

    # Hard bounces from contacts
    bounce_result = (
        db.client.table("contacts")
        .select("id", count="exact")
        .eq("email_status", "bounce")
        .execute()
    )
    hard_bounces = bounce_result.count or 0

    # Pre-send assertion failures
    assertion_result = (
        db.client.table("send_assertions")
        .select("id,assertion", count="exact")
        .eq("passed", False)
        .gte("evaluated_at", since)
        .execute()
    )
    assertion_failures = assertion_result.count or 0

    # Draft attempts (assertions run) in window
    assertion_total_result = (
        db.client.table("send_assertions")
        .select("id", count="exact")
        .gte("evaluated_at", since)
        .execute()
    )
    assertion_total = assertion_total_result.count or 1

    def rate(num: int, denom: int) -> float:
        return round(num / max(denom, 1), 4)

    reply_rate = rate(len(replied), total_sent)
    wrong_person_rate = rate(len(wrong_person), total_sent)
    meeting_conversion = rate(len(meetings), max(len(replied), 1))
    positive_reply_rate = rate(len(interested), total_sent)
    assertion_failure_rate = rate(assertion_failures, assertion_total)

    # Intent breakdown
    intent_counts: dict[str, int] = {}
    for o in replied:
        intent = o.get("reply_classification") or "other"
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    return {
        "window_days": days,
        "since": since,
        "total_sent": total_sent,
        "metrics": {
            "reply_rate": reply_rate,
            "positive_reply_rate": positive_reply_rate,
            "wrong_person_reply_rate": wrong_person_rate,
            "meeting_conversion_rate": meeting_conversion,
            "assertion_failure_rate": assertion_failure_rate,
        },
        "alerts": {
            "hard_bounce_rate": {
                "value": rate(hard_bounces, total_sent) if total_sent else 0,
                "threshold": 0.02,
                "firing": hard_bounces > 0 and rate(hard_bounces, total_sent) > 0.02,
                "action": "Pause sending immediately. Run ZeroBounce scrub.",
            },
            "wrong_person_rate": {
                "value": wrong_person_rate,
                "threshold": 0.01,
                "firing": wrong_person_rate > 0.01,
                "action": "Audit email-name consistency check immediately.",
            },
            "assertion_failures": {
                "value": assertion_failure_rate,
                "threshold": 0.05,
                "firing": assertion_failure_rate > 0.05,
                "action": "Review assertion logs — upstream data quality degrading.",
            },
        },
        "reply_intent_breakdown": intent_counts,
        "meetings_booked": len(meetings),
    }


@router.get("/signals")
def get_company_signals(
    signal_type: str | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    db: Database = Depends(get_db),
):
    """Recent company signals with freshness weights."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = (
        db.client.table("company_signals")
        .select("id,company_id,signal_type,source,signal_text,observed_at,decay_half_life_days,value")
        .gte("observed_at", since)
        .order("observed_at", desc=True)
        .limit(limit)
    )
    if signal_type:
        q = q.eq("signal_type", signal_type)

    signals = q.execute().data or []

    # Compute freshness weight inline
    now = datetime.now(timezone.utc)
    for s in signals:
        try:
            obs = datetime.fromisoformat(s["observed_at"].replace("Z", "+00:00"))
            days_old = (now - obs).days
            half_life = s.get("decay_half_life_days") or 90
            s["freshness_weight"] = round(0.5 ** (days_old / half_life), 4)
        except Exception:
            s["freshness_weight"] = None

    return {"signals": signals, "total": len(signals)}


@router.get("/assertions")
def get_assertion_failures(
    days: int = Query(default=7, ge=1, le=30),
    db: Database = Depends(get_db),
):
    """Recent pre-send assertion failures."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    failures = (
        db.client.table("send_assertions")
        .select("id,contact_id,company_id,assertion,detail,evaluated_at")
        .eq("passed", False)
        .gte("evaluated_at", since)
        .order("evaluated_at", desc=True)
        .limit(100)
        .execute()
        .data or []
    )

    # Group by assertion type for summary
    by_type: dict[str, int] = {}
    for f in failures:
        t = f.get("assertion", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "window_days": days,
        "total_failures": len(failures),
        "by_assertion_type": by_type,
        "failures": failures[:50],  # cap detail rows
    }


@router.get("/outcomes")
def get_outcome_breakdown(
    days: int = Query(default=30, ge=1, le=180),
    db: Database = Depends(get_db),
):
    """Reply classification breakdown and sentiment distribution."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    outcomes = (
        db.client.table("outreach_outcomes")
        .select(
            "reply_sentiment,reply_classification,reply_key_objection,"
            "wrong_person_flag,sequence_step,persona,pqs_at_send,ccs_at_send"
        )
        .gte("created_at", since)
        .execute()
        .data or []
    )

    replied = [o for o in outcomes if o.get("reply_sentiment")]
    sentiment: dict[str, int] = {}
    classification: dict[str, int] = {}
    objections: dict[str, int] = {}

    for o in replied:
        s = o.get("reply_sentiment") or "unknown"
        sentiment[s] = sentiment.get(s, 0) + 1
        c = o.get("reply_classification") or "other"
        classification[c] = classification.get(c, 0) + 1
        obj = o.get("reply_key_objection")
        if obj:
            objections[obj] = objections.get(obj, 0) + 1

    # Average CCS and PQS for replied vs total
    def avg(lst: list, key: str) -> float | None:
        vals = [o.get(key) for o in lst if o.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "window_days": days,
        "total_tracked": len(outcomes),
        "total_replied": len(replied),
        "wrong_person_count": sum(1 for o in outcomes if o.get("wrong_person_flag")),
        "sentiment_breakdown": sentiment,
        "classification_breakdown": classification,
        "objection_breakdown": objections,
        "avg_pqs_all": avg(outcomes, "pqs_at_send"),
        "avg_pqs_replied": avg(replied, "pqs_at_send"),
        "avg_ccs_all": avg(outcomes, "ccs_at_send"),
        "avg_ccs_replied": avg(replied, "ccs_at_send"),
    }


@router.get("/contacts")
def get_contact_quality(
    db: Database = Depends(get_db),
):
    """CCS distribution and gate pass rates across all contacts."""
    contacts = (
        db.client.table("contacts")
        .select(
            "is_outreach_eligible,contact_tier,email_status,"
            "email_name_verified,ccs_score,has_email"
        )
        .execute()
        .data or []
    )

    total = len(contacts)
    eligible = sum(1 for c in contacts if c.get("is_outreach_eligible"))
    excluded = sum(1 for c in contacts if c.get("contact_tier") == "excluded")
    borderline = sum(1 for c in contacts if c.get("contact_tier") == "borderline")
    email_invalid = sum(1 for c in contacts if c.get("email_status") in ("invalid", "bounce"))
    name_mismatch = sum(1 for c in contacts if c.get("email_name_verified") is False)

    # CCS distribution buckets
    ccs_dist = {"0-30": 0, "30-50": 0, "50-70": 0, "70-85": 0, "85-100": 0}
    ccs_scores = [float(c["ccs_score"]) for c in contacts if c.get("ccs_score") is not None]
    for score in ccs_scores:
        if score < 30:
            ccs_dist["0-30"] += 1
        elif score < 50:
            ccs_dist["30-50"] += 1
        elif score < 70:
            ccs_dist["50-70"] += 1
        elif score < 85:
            ccs_dist["70-85"] += 1
        else:
            ccs_dist["85-100"] += 1

    avg_ccs = round(sum(ccs_scores) / len(ccs_scores), 2) if ccs_scores else None

    return {
        "total_contacts": total,
        "outreach_eligible": eligible,
        "excluded_wrong_function": excluded,
        "borderline": borderline,
        "email_status_invalid_or_bounce": email_invalid,
        "email_name_mismatch": name_mismatch,
        "gate_pass_rate": round(eligible / max(total, 1), 4),
        "avg_ccs": avg_ccs,
        "ccs_distribution": ccs_dist,
        "ccs_thresholds": {
            "outbound_eligible": 70,
            "preferred_vp_clevel": 85,
        },
    }


# ---------------------------------------------------------------------------
# ICP Exclusions
# ---------------------------------------------------------------------------

from fastapi import Body
from typing import Optional


@router.get("/icp-exclusions")
def list_icp_exclusions(
    db: Database = Depends(get_db),
):
    """List all ICP-excluded companies."""
    rows = (
        db.client.table("icp_exclusions")
        .select("id,company_id,domain,reason,detail,excluded_by,excluded_at,companies(name)")
        .order("excluded_at", desc=True)
        .limit(200)
        .execute()
        .data or []
    )
    return {"exclusions": rows, "total": len(rows)}


@router.post("/icp-exclusions")
def add_icp_exclusion(
    company_id: Optional[str] = Body(None),
    domain: Optional[str] = Body(None),
    reason: str = Body(...),
    detail: Optional[str] = Body(None),
    excluded_by: str = Body("manual"),
    db: Database = Depends(get_db),
):
    """Manually exclude a company from the ICP pipeline."""
    if not company_id and not domain:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Either company_id or domain is required.")

    from backend.app.core.icp_manager import ICPManager
    mgr = ICPManager(db)
    if company_id:
        mgr.exclude_company(
            company_id=company_id,
            reason=reason,
            detail=detail or "",
            excluded_by=excluded_by,
        )
    else:
        # Domain-only exclusion (no matching company in DB yet)
        db.client.table("icp_exclusions").insert({
            "domain": domain,
            "reason": reason,
            "detail": detail or "",
            "excluded_by": excluded_by,
        }).execute()
    return {"status": "excluded"}


@router.delete("/icp-exclusions/{exclusion_id}")
def remove_icp_exclusion(
    exclusion_id: str,
    db: Database = Depends(get_db),
):
    """Remove an ICP exclusion (re-admits the company to the pipeline)."""
    db.client.table("icp_exclusions").delete().eq("id", exclusion_id).execute()
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# Title Review Queue
# ---------------------------------------------------------------------------

@router.get("/title-review")
def list_title_review(
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Database = Depends(get_db),
):
    """List titles pending human classification review."""
    rows = (
        db.client.table("title_review_queue")
        .select("*")
        .eq("status", status)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data or []
    )
    return {"items": rows, "total": len(rows)}


@router.post("/title-review/{item_id}")
def resolve_title_review(
    item_id: str,
    human_tier: str = Body(...),
    reviewed_by: str = Body("manual"),
    db: Database = Depends(get_db),
):
    """Approve a queued title with a human-confirmed tier.

    Writes to title_classifications as source='human' so future
    occurrences skip Haiku and use the confirmed tier immediately.
    """
    import hashlib
    import re

    VALID_TIERS = {"target", "borderline", "excluded"}
    if human_tier not in VALID_TIERS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"human_tier must be one of {VALID_TIERS}")

    # Fetch the queued item
    rows = (
        db.client.table("title_review_queue")
        .select("*")
        .eq("id", item_id)
        .limit(1)
        .execute()
        .data or []
    )
    if not rows:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Item not found")

    item = rows[0]
    title = item["title"]
    industry = item.get("industry", "")

    # Compute cache key (same logic as TitleClassifier)
    normalized = re.sub(r"\s+", " ", title.lower().strip())
    raw_key = f"{normalized}|{industry.lower().strip()}"
    cache_key = hashlib.sha256(raw_key.encode()).hexdigest()[:32]

    # Write human override to title_classifications
    db.client.table("title_classifications").upsert({
        "cache_key": cache_key,
        "title": title[:255],
        "industry": industry,
        "tier": human_tier,
        "confidence": 1.0,
        "source": "human",
        "reasoning": f"Human review by {reviewed_by}",
    }, on_conflict="cache_key").execute()

    # Mark queue item resolved
    db.client.table("title_review_queue").update({
        "status": "reviewed",
        "human_tier": human_tier,
        "reviewed_by": reviewed_by,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", item_id).execute()

    return {"status": "resolved", "tier": human_tier, "cache_key": cache_key}


# ---------------------------------------------------------------------------
# Threading State
# ---------------------------------------------------------------------------

@router.get("/threading")
def get_threading_state(
    state: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Database = Depends(get_db),
):
    """Company outreach threading state summary."""
    q = (
        db.client.table("company_outreach_state")
        .select("*,companies(name,domain,tier,pqs_total)")
        .order("updated_at", desc=True)
        .limit(limit)
    )
    if state:
        q = q.eq("state", state)
    rows = q.execute().data or []

    # State distribution summary
    state_counts: dict[str, int] = {}
    for row in rows:
        s = row.get("state", "unknown")
        state_counts[s] = state_counts.get(s, 0) + 1

    return {
        "companies": rows,
        "total": len(rows),
        "state_distribution": state_counts,
    }
