"""Daily GTM Report Agent — writes and emails a daily performance + strategy brief.

Collects pipeline metrics, reply signals, API spend, and approval queue state,
then calls Claude (Haiku) to produce a narrative analysis with observations and
specific recommendations. Sends the result as an HTML email via Resend.

Designed to run as a scheduled job (e.g. 5pm Chicago daily).
All DB queries are synchronous (Supabase client); email send uses asyncio.run().
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timezone, timedelta

import anthropic

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

_PLAN_CLAUDE_MONTHLY = 21.0   # from docs/FINANCIAL_PROJECTIONS.md
_PLAN_CLAUDE_DAILY   = _PLAN_CLAUDE_MONTHLY / 30
_BUDGET_CAP          = 200.0  # monthly hard cap (Claude only)


def _iso_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _collect_engagement_spotlight(client) -> list[dict]:
    """Return top engaged companies with click/open/reply counts and last interaction."""
    week_ago = _iso_days_ago(7)
    # Get all sent drafts with message IDs (for interaction join)
    sent_drafts = (
        client.table("outreach_drafts")
        .select("id, company_id, company_name, contact_name, contact_title, sequence_step, resend_message_id, sent_at")
        .eq("approval_status", "approved")
        .not_.is_("sent_at", "null")
        .not_.is_("resend_message_id", "null")
        .gte("sent_at", _iso_days_ago(30))
        .execute()
        .data or []
    )
    if not sent_drafts:
        return []

    msg_ids = [d["resend_message_id"] for d in sent_drafts if d.get("resend_message_id")]
    if not msg_ids:
        return []

    interactions = (
        client.table("interactions")
        .select("type, metadata, created_at")
        .in_("type", ["email_opened", "email_clicked", "email_replied"])
        .gte("created_at", week_ago)
        .execute()
        .data or []
    )

    # Build resend_message_id → interaction list from metadata
    by_msg: dict[str, list] = {}
    for iv in interactions:
        meta = iv.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        mid = meta.get("resend_message_id") or meta.get("message_id")
        if mid:
            by_msg.setdefault(mid, []).append(iv)

    # Aggregate per company
    company_agg: dict[str, dict] = {}
    for draft in sent_drafts:
        mid = draft.get("resend_message_id")
        ivs = by_msg.get(mid, [])
        if not ivs:
            continue
        cname = draft.get("company_name") or "Unknown"
        if cname not in company_agg:
            company_agg[cname] = {
                "company_name": cname,
                "contact_name": draft.get("contact_name", ""),
                "contact_title": draft.get("contact_title", ""),
                "sequence_step": draft.get("sequence_step", 1),
                "opens": 0, "clicks": 0, "replies": 0,
                "last_interaction": None,
            }
        agg = company_agg[cname]
        for iv in ivs:
            t = iv.get("type", "")
            if t == "email_opened":
                agg["opens"] += 1
            elif t == "email_clicked":
                agg["clicks"] += 1
            elif t == "email_replied":
                agg["replies"] += 1
            ts = iv.get("created_at")
            if ts and (agg["last_interaction"] is None or ts > agg["last_interaction"]):
                agg["last_interaction"] = ts

    # Sort by signal strength: replies first, then clicks, then opens
    result = sorted(
        company_agg.values(),
        key=lambda x: (x["replies"] * 100 + x["clicks"] * 10 + x["opens"]),
        reverse=True,
    )
    return result[:5]


def _collect_financial_metrics(client) -> dict:
    """Collect Claude API spend + pipeline activity for the financial section."""
    now = datetime.now(timezone.utc)
    today_start  = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start  = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    def fetch_costs(since: str) -> list[dict]:
        rows = (
            client.table("api_costs")
            .select("provider,model,estimated_cost_usd")
            .gte("created_at", since)
            .execute()
            .data or []
        )
        return [r for r in rows if r.get("provider") != "apollo"]

    today_rows = fetch_costs(today_start)
    month_rows = fetch_costs(month_start)

    def sum_claude(rows: list[dict]) -> float:
        return sum(float(r.get("estimated_cost_usd") or 0) for r in rows if r.get("provider") == "anthropic")

    today_claude = sum_claude(today_rows)
    mtd_claude   = sum_claude(month_rows)

    # Top models today
    by_model: dict[str, float] = {}
    for r in today_rows:
        key = f"{r.get('provider','?')}/{r.get('model','?')}"
        by_model[key] = by_model.get(key, 0) + float(r.get("estimated_cost_usd") or 0)
    top_models = dict(sorted(by_model.items(), key=lambda x: -x[1])[:4])

    # Web search alert
    web_search_today = [r for r in today_rows if "web_search" in (r.get("model") or "")]

    # Sends today and MTD
    sends_today = (
        client.table("outreach_drafts").select("id", count="exact")
        .not_.is_("sent_at", "null").gte("sent_at", today_start).execute().count or 0
    )
    sends_mtd = (
        client.table("outreach_drafts").select("id", count="exact")
        .not_.is_("sent_at", "null").gte("sent_at", month_start).execute().count or 0
    )

    # Apollo calls today (proxy for credit usage)
    apollo_today = (
        client.table("api_costs").select("id", count="exact")
        .eq("provider", "apollo").gte("created_at", today_start).execute().count or 0
    )

    return {
        "today_claude": today_claude,
        "mtd_claude": mtd_claude,
        "budget_cap": _BUDGET_CAP,
        "plan_daily": _PLAN_CLAUDE_DAILY,
        "plan_monthly": _PLAN_CLAUDE_MONTHLY,
        "top_models": top_models,
        "web_search_alert": len(web_search_today) > 0,
        "sends_today": sends_today,
        "sends_mtd": sends_mtd,
        "apollo_calls_today": apollo_today,
        "cost_per_email_mtd": round(mtd_claude / sends_mtd, 4) if sends_mtd else None,
    }


def _collect_metrics(client) -> dict:
    """Pull all metrics needed for the report from Supabase."""
    now = datetime.now(timezone.utc)
    yesterday = _iso_days_ago(1)
    week_ago = _iso_days_ago(7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    m: dict = {"as_of": now.strftime("%Y-%m-%d %H:%M UTC")}

    # --- Pipeline stage counts (one query per status, avoids 1000-row page limit) ---
    known_statuses = [
        "discovered", "researched", "qualified", "outreach_pending",
        "contacted", "engaged", "not_interested", "disqualified",
        "bounced", "paused",
    ]
    stage_counts: dict[str, int] = {}
    for status in known_statuses:
        result = (
            client.table("companies")
            .select("id", count="exact")
            .eq("status", status)
            .limit(1)
            .execute()
        )
        cnt = result.count if result.count is not None else len(result.data or [])
        if cnt:
            stage_counts[status] = cnt
    m["pipeline"] = stage_counts

    # --- Email activity last 7 days ---
    email_events = (
        client.table("interactions")
        .select("type, created_at")
        .in_("type", ["email_sent", "email_opened", "email_clicked",
                       "email_replied", "email_bounced"])
        .gte("created_at", week_ago)
        .execute()
        .data or []
    )
    event_counts = Counter(e["type"] for e in email_events)
    sent = event_counts.get("email_sent", 0)
    m["email_7d"] = {
        "sent": sent,
        "opened": event_counts.get("email_opened", 0),
        "clicked": event_counts.get("email_clicked", 0),
        "replied": event_counts.get("email_replied", 0),
        "bounced": event_counts.get("email_bounced", 0),
        "open_rate_pct": round(event_counts.get("email_opened", 0) / sent * 100, 1) if sent else 0,
        "reply_rate_pct": round(event_counts.get("email_replied", 0) / sent * 100, 1) if sent else 0,
    }

    # --- Reply classifications last 7 days ---
    reply_interactions = (
        client.table("interactions")
        .select("metadata")
        .eq("type", "email_replied")
        .gte("created_at", week_ago)
        .execute()
        .data or []
    )
    classifications: dict[str, int] = {}
    urgencies: dict[str, int] = {}
    for r in reply_interactions:
        meta = r.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        cls = meta.get("classification", "unknown")
        urg = meta.get("urgency", "medium")
        classifications[cls] = classifications.get(cls, 0) + 1
        urgencies[urg] = urgencies.get(urg, 0) + 1
    m["replies_7d"] = {"classifications": classifications, "urgencies": urgencies}

    # --- Research activity last 24h ---
    researched_24h = (
        client.table("companies")
        .select("pqs_total, status")
        .eq("status", "researched")
        .gte("updated_at", yesterday)
        .execute()
        .data or []
    )
    pqs_scores = [r.get("pqs_total") or 0 for r in researched_24h]
    m["research_24h"] = {
        "companies_researched": len(researched_24h),
        "avg_pqs": round(sum(pqs_scores) / len(pqs_scores), 1) if pqs_scores else 0,
        "qualified_pct": round(
            sum(1 for p in pqs_scores if p >= 20) / len(pqs_scores) * 100, 1
        ) if pqs_scores else 0,
    }

    # --- Approval queue with rejection category breakdown ---
    approval_queue = (
        client.table("outreach_drafts")
        .select("approval_status, sequence_name, rejection_category, quality_score")
        .in_("approval_status", ["pending", "rejected"])
        .execute()
        .data or []
    )
    pending = [d for d in approval_queue if d.get("approval_status") == "pending"]
    rejected = [d for d in approval_queue if d.get("approval_status") == "rejected"]
    rejection_cats = Counter(d.get("rejection_category") or "uncategorized" for d in rejected)
    m["approval_queue"] = {
        "pending_count": len(pending),
        "rejected_count": len(rejected),
        "rejection_categories": dict(rejection_cats),
        "genuine_rejections": rejection_cats.get("quality_manual", 0),
        "systemic_rejections": rejection_cats.get("systemic", 0),
        "hallucination_rejections": rejection_cats.get("model_hallucination", 0),
        "targeting_rejections": rejection_cats.get("targeting", 0),
    }

    # --- Top-of-funnel metrics ---
    # Total discovered vs qualified (qualification funnel health)
    discovered_total = (
        client.table("companies").select("id", count="exact").execute().count or 0
    )
    qualified_total = sum(
        stage_counts.get(s, 0)
        for s in ["qualified", "outreach_pending", "contacted", "engaged"]
    )
    outreach_total = sum(
        stage_counts.get(s, 0)
        for s in ["outreach_pending", "contacted", "engaged"]
    )
    m["funnel"] = {
        "discovered": discovered_total,
        "qualified": qualified_total,
        "in_outreach": outreach_total,
        "qualification_rate_pct": round(qualified_total / discovered_total * 100, 1) if discovered_total else 0,
        "outreach_conversion_pct": round(outreach_total / qualified_total * 100, 1) if qualified_total else 0,
    }

    # --- Draft quality metrics (all-time, genuine GTM quality only) ---
    approved_count = (
        client.table("outreach_drafts").select("id", count="exact")
        .eq("approval_status", "approved").execute().count or 0
    )
    genuine_rejected_count = (
        client.table("outreach_drafts").select("id", count="exact")
        .eq("approval_status", "rejected")
        .eq("rejection_category", "quality_manual")
        .execute().count or 0
    )
    total_decided = approved_count + genuine_rejected_count
    m["draft_quality"] = {
        "approved": approved_count,
        "genuine_rejected": genuine_rejected_count,
        "approval_rate_pct": round(approved_count / total_decided * 100, 1) if total_decided else 0,
    }

    # --- Companies that moved to engaged (positive replies) ---
    engaged_companies = (
        client.table("companies")
        .select("name, pqs_total")
        .eq("status", "engaged")
        .order("updated_at", desc=True)
        .limit(10)
        .execute()
        .data or []
    )
    m["engaged_companies"] = [c["name"] for c in engaged_companies]

    # --- API spend ---
    week_costs = (
        client.table("api_costs")
        .select("provider, model, estimated_cost_usd")
        .gte("created_at", week_ago)
        .execute()
        .data or []
    )
    month_costs = (
        client.table("api_costs")
        .select("estimated_cost_usd")
        .gte("created_at", month_start)
        .execute()
        .data or []
    )
    by_model: dict[str, float] = {}
    for r in week_costs:
        key = f"{r.get('provider','?')}/{r.get('model','?')}"
        by_model[key] = by_model.get(key, 0) + float(r.get("estimated_cost_usd") or 0)
    m["api_spend"] = {
        "week_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in week_costs), 2),
        "month_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in month_costs), 2),
        "budget_usd": 100.0,
        "top_models": dict(sorted(by_model.items(), key=lambda x: -x[1])[:5]),
    }

    # --- Sequence activity last 7 days ---
    sequences_7d = (
        client.table("engagement_sequences")
        .select("status")
        .gte("created_at", week_ago)
        .execute()
        .data or []
    )
    seq_status = Counter(s.get("status") for s in sequences_7d)
    m["sequences_7d"] = dict(seq_status)

    return m


# ---------------------------------------------------------------------------
# Claude narrative generation
# ---------------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """You are the GTM analyst for ProspectIQ, an AI-powered B2B outreach platform
targeting North American manufacturing companies (revenue $50M-$500M, VP Ops / VP Quality personas).

You receive structured pipeline metrics daily and write a critical, deeply analytical brief for the founder (Avi).
Your job is NOT to restate numbers. Your job is:
1. Critically assess the health of each stage of the GTM machine — discovery through engagement
2. Score each process 1-10 with sharp reasoning (not vague praise)
3. Identify root causes, not symptoms — if a metric is bad, say WHY and what specifically to fix
4. Separate systemic problems (require code/config changes) from execution problems (require decisions)
5. Give Avi a precise, prioritized action list — no more than 5 items, each actionable today or this week

SCORING RULES:
- 9-10: World class. Benchmarked against best-in-class B2B outreach (reply rate >3%, 0 systemic failures)
- 7-8: Healthy. Minor issues but no structural problem
- 5-6: Marginal. Pattern of underperformance that compounds if unaddressed
- 3-4: Broken. One or more core processes failing; pipeline at risk
- 1-2: Critical. Immediate intervention required

SIGNAL HIERARCHY (most to least reliable for B2B manufacturing):
replies > clicks > bounces > delivered volume
Open rate is NOISE in this vertical — corporate Outlook pre-fetches pixels. Never use it to assess health.

REJECTION INTERPRETATION:
- systemic = engineering bug (URL in step 1, step-label leaks) — these are FIXED, do not penalize GTM quality
- targeting = wrong persona/role — reflects ICP calibration accuracy
- quality_manual / quality_auto = genuine draft quality failures — these ARE the GTM signal
Use only genuine quality rejections in your GTM health assessment.

Tone: direct, critical, no hedging, no reassurance. If something is broken, name it plainly.
Write like a fractional CMO who has seen the full data and has zero patience for spin.

FORMAT — you must use EXACTLY these section headers (bold, followed by colon):
**GTM HEALTH SCORECARD:**
**TOP OF FUNNEL:**
**OUTREACH QUALITY:**
**ENGAGEMENT & SIGNALS:**
**PIPELINE VELOCITY:**
**ACTIONS FOR AVI:**
**WATCH THIS WEEK:**

Keep the entire report under 750 words. Be ruthless with cuts."""

REPORT_USER_TEMPLATE = """Pipeline state as of {as_of}:

FUNNEL OVERVIEW:
- Total companies discovered: {discovered}
- Qualified (ICP match): {qualified} ({qualification_rate}% of discovered)
- In active outreach: {in_outreach} ({outreach_conversion}% of qualified)

PIPELINE STAGES:
{pipeline_table}

EMAIL PERFORMANCE (last 7 days):
- Sent: {email_sent} | Clicks: {email_clicked} | Replies: {email_replied} ({reply_rate}%) | Bounces: {email_bounced}
- Note: open rate ({open_rate}%) is unreliable — pixel pre-fetch noise. Ignore it.

REPLY BREAKDOWN (last 7 days):
{reply_breakdown}

RESEARCH (last 24h):
- Companies researched: {research_count} | Avg PQS: {avg_pqs} | Scoring 20+ (proceed): {qualified_pct}%

DRAFT QUALITY (all-time, four-bucket breakdown):
- Approved: {approved_drafts} | GTM quality rejections: {genuine_rejected} | Approval rate vs quality denominator: {approval_rate}%
- systemic={systemic_rej} (code bugs, fixed) | model_hallucination={hallucination_rej} (prompt failures, now filtered) | targeting={targeting_rej} | genuine_quality={genuine_rejected}
- Only genuine_quality rejections count toward GTM health scoring

APPROVAL QUEUE NOW:
- Pending approval: {pending_drafts}
- In rejected state: {rejected_drafts}

ENGAGED COMPANIES (positive signals — clicks/replies, last 7 days):
{engaged_list}

API SPEND:
- This week: ${week_usd} | MTD: ${month_usd} / $100.00 budget | Top drivers: {top_models}

Write the daily brief using the required section headers. Score each process section 1-10.
For each score below 7, include: (a) specific cause, (b) precise fix.
For ACTIONS FOR AVI: no more than 5 items. Mark each as [TODAY] or [THIS WEEK]."""


def _build_report_prompt(m: dict) -> str:
    pipeline = m.get("pipeline", {})
    pipeline_table = "\n".join(
        f"  {s:20s} {cnt:4d}"
        for s, cnt in sorted(pipeline.items(), key=lambda x: -x[1])
    )

    email = m.get("email_7d", {})
    replies = m.get("replies_7d", {})
    cls = replies.get("classifications", {})
    reply_breakdown = (
        "\n".join(f"  {k}: {v}" for k, v in sorted(cls.items(), key=lambda x: -x[1]))
        or "  No replies yet"
    )

    engaged = m.get("engaged_companies", [])
    engaged_list = "\n".join(f"  - {n}" for n in engaged[:8]) or "  None yet (0 confirmed replies)"

    spend = m.get("api_spend", {})
    top_models = ", ".join(f"{k} ${v:.2f}" for k, v in spend.get("top_models", {}).items())

    research = m.get("research_24h", {})
    queue = m.get("approval_queue", {})
    funnel = m.get("funnel", {})
    dq = m.get("draft_quality", {})

    return REPORT_USER_TEMPLATE.format(
        as_of=m.get("as_of", "today"),
        discovered=funnel.get("discovered", 0),
        qualified=funnel.get("qualified", 0),
        qualification_rate=funnel.get("qualification_rate_pct", 0),
        in_outreach=funnel.get("in_outreach", 0),
        outreach_conversion=funnel.get("outreach_conversion_pct", 0),
        pipeline_table=pipeline_table,
        email_sent=email.get("sent", 0),
        email_clicked=email.get("clicked", 0),
        email_opened=email.get("opened", 0),
        open_rate=email.get("open_rate_pct", 0),
        email_replied=email.get("replied", 0),
        reply_rate=email.get("reply_rate_pct", 0),
        email_bounced=email.get("bounced", 0),
        reply_breakdown=reply_breakdown,
        research_count=research.get("companies_researched", 0),
        avg_pqs=research.get("avg_pqs", 0),
        qualified_pct=research.get("qualified_pct", 0),
        approved_drafts=dq.get("approved", 0),
        genuine_rejected=dq.get("genuine_rejected", 0),
        approval_rate=dq.get("approval_rate_pct", 0),
        systemic_rej=queue.get("systemic_rejections", 0),
        hallucination_rej=queue.get("hallucination_rejections", 0),
        targeting_rej=queue.get("targeting_rejections", 0),
        pending_drafts=queue.get("pending_count", 0),
        rejected_drafts=queue.get("rejected_count", 0),
        engaged_list=engaged_list,
        week_usd=spend.get("week_usd", 0),
        month_usd=spend.get("month_usd", 0),
        top_models=top_models or "none yet",
    )


def _call_claude(prompt: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system=REPORT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# HTML formatter
# ---------------------------------------------------------------------------

def _render_financial_section(fin: dict) -> str:
    today_claude = fin.get("today_claude", 0.0)
    mtd_claude   = fin.get("mtd_claude", 0.0)
    cap          = fin.get("budget_cap", 200.0)
    plan_daily   = fin.get("plan_daily", 0.70)
    plan_monthly = fin.get("plan_monthly", 21.0)
    sends_today  = fin.get("sends_today", 0)
    sends_mtd    = fin.get("sends_mtd", 0)
    apollo_today = fin.get("apollo_calls_today", 0)
    cost_per_email = fin.get("cost_per_email_mtd")
    top_models   = fin.get("top_models", {})
    web_alert    = fin.get("web_search_alert", False)

    budget_pct   = (mtd_claude / cap * 100) if cap else 0
    cap_color    = "#16a34a" if budget_pct < 60 else "#d97706" if budget_pct < 85 else "#dc2626"
    day_over     = today_claude > plan_daily
    mtd_over     = mtd_claude > plan_monthly

    model_rows = "".join(
        f"<tr><td style='padding:5px 12px;border-top:1px solid #e5e7eb;font-size:12px'>{k}</td>"
        f"<td style='text-align:right;padding:5px 12px;border-top:1px solid #e5e7eb;font-size:12px'>${v:.4f}</td></tr>"
        for k, v in top_models.items()
    ) or "<tr><td colspan='2' style='padding:5px 12px;font-size:12px;color:#9ca3af'>No API calls today</td></tr>"

    web_banner = (
        "<div style='background:#fee2e2;border-left:4px solid #dc2626;padding:8px 12px;"
        "border-radius:4px;margin-bottom:12px;font-size:12px'>"
        "<strong>ALERT: web_search model triggered today.</strong> Disabled on 2026-05-02 — investigate.</div>"
    ) if web_alert else ""

    return f"""
  <div style="margin-top:24px;border-top:2px solid #eee;padding-top:20px">
    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#888;margin-bottom:12px">Financial Summary</div>
    {web_banner}
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
      <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Today (Claude)</div>
        <div style="font-size:22px;font-weight:700;margin-top:2px">${today_claude:.4f}</div>
        <div style="font-size:11px;color:{'#dc2626' if day_over else '#16a34a'}">${plan_daily:.2f} plan {'OVER' if day_over else 'under'}</div>
      </div>
      <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">MTD (Claude)</div>
        <div style="font-size:22px;font-weight:700;margin-top:2px">${mtd_claude:.2f}</div>
        <div style="font-size:11px;color:{'#dc2626' if mtd_over else '#16a34a'}">${plan_monthly:.0f} plan {'OVER' if mtd_over else 'under'}</div>
      </div>
      <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Budget cap</div>
        <div style="font-size:22px;font-weight:700;margin-top:2px;color:{cap_color}">{budget_pct:.0f}%</div>
        <div style="font-size:11px;color:#888">${cap - mtd_claude:.2f} remaining</div>
      </div>
      <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Cost / email</div>
        <div style="font-size:22px;font-weight:700;margin-top:2px">${f'{cost_per_email:.4f}' if cost_per_email else '—'}</div>
        <div style="font-size:11px;color:#888">{sends_today} sent today · {sends_mtd} MTD</div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;margin-bottom:10px">
      <tr style="background:#f3f4f6">
        <th style="text-align:left;padding:6px 12px;font-size:12px">Model (today)</th>
        <th style="text-align:right;padding:6px 12px;font-size:12px">Cost</th>
      </tr>
      {model_rows}
    </table>
    <p style="font-size:11px;color:#9ca3af;margin:6px 0">
      Apollo enrichment: {apollo_today} API calls today.
      Apollo credit balance — check <a href="https://app.apollo.io/#/settings/credits/current" style="color:#1a56db">Apollo dashboard</a>.
      Railway (~$50/mo) billed separately.
    </p>
  </div>"""


def _render_engagement_spotlight(companies: list[dict]) -> str:
    """Visual card section for top engaged companies (click/reply behavior)."""
    if not companies:
        return ""

    def signal_badge(company: dict) -> str:
        if company["replies"] > 0:
            return "<span style='background:#7c3aed;color:#fff;border-radius:12px;padding:2px 9px;font-size:11px;font-weight:700'>REPLIED</span>"
        if company["clicks"] > 0:
            return "<span style='background:#16a34a;color:#fff;border-radius:12px;padding:2px 9px;font-size:11px;font-weight:700'>CLICKED</span>"
        return "<span style='background:#2563eb;color:#fff;border-radius:12px;padding:2px 9px;font-size:11px;font-weight:700'>OPENED</span>"

    def signal_bar(opens: int, clicks: int, replies: int) -> str:
        bars = ""
        for i in range(min(clicks, 10)):
            bars += "<span style='display:inline-block;width:10px;height:10px;background:#16a34a;border-radius:2px;margin-right:2px'></span>"
        for i in range(min(opens, 10)):
            bars += "<span style='display:inline-block;width:10px;height:10px;background:#93c5fd;border-radius:2px;margin-right:2px'></span>"
        return bars or "<span style='color:#d1d5db;font-size:11px'>no engagement</span>"

    cards = ""
    for c in companies:
        last_ts = c.get("last_interaction", "")
        if last_ts:
            try:
                dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                last_ts = dt.strftime("%-m/%-d %H:%M CT")
            except Exception:
                last_ts = last_ts[:10]

        cards += f"""
      <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;flex:1;min-width:160px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
          <div>
            <div style="font-weight:700;font-size:13px;color:#111">{c['company_name']}</div>
            <div style="font-size:11px;color:#666;margin-top:2px">{c.get('contact_name','')} · {c.get('contact_title','')[:28]}</div>
          </div>
          {signal_badge(c)}
        </div>
        <div style="margin-bottom:8px">{signal_bar(c['opens'], c['clicks'], c['replies'])}</div>
        <div style="font-size:11px;color:#888;display:flex;gap:12px">
          <span><strong style="color:#16a34a">{c['clicks']}</strong> clicks</span>
          <span><strong style="color:#93c5fd">{c['opens']}</strong> opens</span>
          <span>Step {c.get('sequence_step',1)}</span>
        </div>
        {'<div style="font-size:10px;color:#aaa;margin-top:6px">Last: ' + last_ts + '</div>' if last_ts else ''}
      </div>"""

    return f"""
  <div style="margin-top:24px;border-top:2px solid #eee;padding-top:20px">
    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#888;margin-bottom:12px">Engagement Spotlight — Last 7 Days</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      {cards}
    </div>
  </div>"""


def _render_html(narrative: str, m: dict, date_str: str, fin: dict | None = None, spotlight: list | None = None) -> str:
    email_7d = m.get("email_7d", {})
    pipeline = m.get("pipeline", {})
    spend = m.get("api_spend", {})
    queue = m.get("approval_queue", {})
    funnel = m.get("funnel", {})
    dq = m.get("draft_quality", {})

    pipeline_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{s}</td>"
        f"<td style='padding:4px 0;font-weight:600'>{cnt}</td></tr>"
        for s, cnt in sorted(pipeline.items(), key=lambda x: -x[1])
    )

    # Convert narrative markdown-ish to basic HTML
    html_body = ""
    for line in narrative.split("\n"):
        stripped = line.strip()
        if not stripped:
            html_body += "<br>"
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            label = stripped.strip("*").rstrip(":")
            html_body += f"<h3 style='color:#1a1a2e;margin:22px 0 6px;border-bottom:1px solid #e5e7eb;padding-bottom:4px'>{label}</h3>"
        elif stripped.startswith("##"):
            label = stripped.lstrip("#").strip()
            html_body += f"<h3 style='color:#1a1a2e;margin:22px 0 6px'>{label}</h3>"
        elif stripped.startswith("- ") or stripped.startswith("* "):
            html_body += f"<li style='margin:4px 0'>{stripped[2:]}</li>"
        elif stripped and stripped[0].isdigit() and len(stripped) > 2 and stripped[1] in ".)":
            html_body += f"<li style='margin:6px 0'>{stripped[2:].strip()}</li>"
        else:
            html_body += f"<p style='margin:8px 0;line-height:1.6'>{stripped}</p>"

    # Rejection breakdown bar
    systemic = queue.get("systemic_rejections", 0)
    hallucination = queue.get("hallucination_rejections", 0)
    targeting = queue.get("targeting_rejections", 0)
    genuine = queue.get("genuine_rejections", 0)
    total_rej = systemic + hallucination + targeting + genuine or 1

    def pct_bar(val, total, color):
        pct = round(val / total * 100)
        return (
            f"<div style='background:{color};height:8px;border-radius:2px;width:{pct}%;display:inline-block'></div>"
            f"<span style='font-size:11px;color:#555;margin-left:6px'>{val} ({pct}%)</span>"
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:system-ui,sans-serif;max-width:700px;margin:0 auto;padding:24px;color:#222">

  <div style="background:#1a1a2e;color:#fff;padding:20px 24px;border-radius:8px;margin-bottom:24px">
    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.7">Daily GTM Brief</div>
    <div style="font-size:22px;font-weight:700;margin-top:4px">ProspectIQ — {date_str}</div>
    <div style="font-size:12px;opacity:.6;margin-top:4px">{funnel.get('discovered',0)} companies discovered · {funnel.get('qualified',0)} qualified · {funnel.get('in_outreach',0)} in outreach</div>
  </div>

  <!-- Stats row -->
  <div style="display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap">
    <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
      <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Sent (7d)</div>
      <div style="font-size:24px;font-weight:700;margin-top:4px">{email_7d.get('sent',0)}</div>
    </div>
    <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
      <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Clicks (7d)</div>
      <div style="font-size:24px;font-weight:700;margin-top:4px">{email_7d.get('clicked',0)}</div>
    </div>
    <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
      <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Replies (7d)</div>
      <div style="font-size:24px;font-weight:700;margin-top:4px;color:{'#16a34a' if email_7d.get('replied',0)>0 else '#111'}">{email_7d.get('replied',0)}</div>
      <div style="font-size:11px;color:#888">{email_7d.get('reply_rate_pct',0)}% rate</div>
    </div>
    <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
      <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">Approval rate</div>
      <div style="font-size:24px;font-weight:700;margin-top:4px">{dq.get('approval_rate_pct',0)}%</div>
      <div style="font-size:11px;color:#888">{dq.get('approved',0)} approved</div>
    </div>
    <div style="flex:1;min-width:110px;background:#f5f5f5;border-radius:6px;padding:12px 14px">
      <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px">API spend MTD</div>
      <div style="font-size:24px;font-weight:700;margin-top:4px">${spend.get('month_usd',0):.0f}</div>
    </div>
  </div>

  <!-- Rejection breakdown -->
  <div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;padding:12px 16px;margin-bottom:20px">
    <div style="font-size:10px;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Rejection Breakdown — {systemic + hallucination + targeting + genuine} total (all-time)</div>
    <div style="margin-bottom:5px">Systemic / code bugs (fixed): {pct_bar(systemic, total_rej, '#d1d5db')}</div>
    <div style="margin-bottom:5px">Model hallucination (now filtered): {pct_bar(hallucination, total_rej, '#c4b5fd')}</div>
    <div style="margin-bottom:5px">Targeting / wrong persona: {pct_bar(targeting, total_rej, '#fbbf24')}</div>
    <div>GTM quality — genuine: {pct_bar(genuine, total_rej, '#ef4444')}</div>
  </div>

  <!-- Engagement spotlight -->
  {_render_engagement_spotlight(spotlight or [])}

  <!-- Claude narrative -->
  <div style="margin-top:24px;margin-bottom:28px">
    {html_body}
  </div>

  <!-- Pipeline table -->
  <div style="background:#f9f9f9;border-radius:6px;padding:16px 20px;margin-bottom:24px">
    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#888;margin-bottom:10px">Pipeline Snapshot</div>
    <table style="border-collapse:collapse;width:100%">
      {pipeline_rows}
    </table>
  </div>

  <!-- Financial summary -->
  {_render_financial_section(fin) if fin else ''}

  <div style="font-size:11px;color:#aaa;border-top:1px solid #eee;padding-top:12px;margin-top:16px">
    ProspectIQ GTM Engine · {m.get('as_of','')}
  </div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_daily_report() -> bool:
    """Generate and email the daily GTM brief. Returns True on success."""
    settings = get_settings()
    recipient = getattr(settings, "report_recipient_email", "") or "avi@digitillis.io"

    try:
        client = get_supabase_client()
        logger.info("Daily report: collecting metrics...")
        m = _collect_metrics(client)
        fin = _collect_financial_metrics(client)
        spotlight = _collect_engagement_spotlight(client)

        logger.info("Daily report: generating Claude narrative...")
        prompt = _build_report_prompt(m)
        narrative = _call_claude(prompt, settings.anthropic_api_key)

        date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
        html = _render_html(narrative, m, date_str, fin=fin, spotlight=spotlight)

        subject = f"ProspectIQ GTM Brief — {date_str}"
        logger.info(f"Daily report: sending to {recipient}...")

        from backend.app.core.notifications import send_email
        success = asyncio.run(send_email(to=recipient, subject=subject, html_body=html))

        if success:
            logger.info("Daily report: sent successfully.")
        else:
            logger.warning("Daily report: Resend returned failure — check logs.")

        return success

    except Exception as e:
        logger.error(f"Daily report failed: {e}", exc_info=True)
        return False
