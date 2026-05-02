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

def _iso_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


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

    # --- Approval queue ---
    approval_queue = (
        client.table("outreach_drafts")
        .select("approval_status, sequence_name")
        .in_("approval_status", ["pending", "rejected"])
        .execute()
        .data or []
    )
    pending = [d for d in approval_queue if d.get("approval_status") == "pending"]
    rejected = [d for d in approval_queue if d.get("approval_status") == "rejected"]
    m["approval_queue"] = {
        "pending_count": len(pending),
        "rejected_count": len(rejected),
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
targeting North American manufacturing companies (revenue $100M-$2B, 300-3,500 employees).

You receive structured pipeline metrics each day and write a concise daily brief for the founder (Avi).
Your job is NOT to restate the numbers — Avi can read tables. Your job is to:
1. Interpret what the numbers mean for the overall GTM strategy
2. Identify trends, anomalies, and leading indicators
3. Give specific, prioritized recommendations
4. Call out actions Avi must take today or this week

IMPORTANT: Open rate is unreliable in B2B manufacturing outreach — corporate Outlook clients
block or pre-fetch tracking pixels. Do NOT use open rate to assess campaign health.
The reliable signals in order of trustworthiness: replies > clicks > bounces > delivered.
Grade GTM health on reply rate and pipeline velocity, not open rate.

Tone: direct, sharp, no fluff. Write like a trusted advisor who has seen the full picture.
Format: structured sections with headers. Keep the whole report under 600 words."""

REPORT_USER_TEMPLATE = """Today's pipeline metrics (as of {as_of}):

PIPELINE STAGES:
{pipeline_table}

EMAIL PERFORMANCE (last 7 days):
- Sent: {email_sent} | Opens: {email_opened} ({open_rate}%) | Replies: {email_replied} ({reply_rate}%) | Bounces: {email_bounced}

REPLY BREAKDOWN (last 7 days):
{reply_breakdown}

RESEARCH (last 24h):
- Companies researched: {research_count}
- Avg PQS post-research: {avg_pqs}
- % scoring 20+ (proceed to pipeline): {qualified_pct}%

APPROVAL QUEUE:
- Pending your approval: {pending_drafts}
- Rejected (need regen): {rejected_drafts}

ENGAGED COMPANIES (positive replies, most recent):
{engaged_list}

API SPEND:
- This week: ${week_usd} | Month-to-date: ${month_usd} / $100.00 budget
- Top cost drivers: {top_models}

Write the daily brief now. Structure it as:
1. Overall GTM Health (1-2 sentences, a letter grade A-F with brief rationale)
2. What's Working
3. What Needs Attention
4. Recommended Actions (numbered, prioritized — separate Avi's actions from automated pipeline actions)
5. Leading Indicators to Watch This Week"""


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
    engaged_list = "\n".join(f"  - {n}" for n in engaged[:8]) or "  None yet"

    spend = m.get("api_spend", {})
    top_models = ", ".join(f"{k} ${v:.2f}" for k, v in spend.get("top_models", {}).items())

    research = m.get("research_24h", {})
    queue = m.get("approval_queue", {})

    return REPORT_USER_TEMPLATE.format(
        as_of=m.get("as_of", "today"),
        pipeline_table=pipeline_table,
        email_sent=email.get("sent", 0),
        email_opened=email.get("opened", 0),
        open_rate=email.get("open_rate_pct", 0),
        email_replied=email.get("replied", 0),
        reply_rate=email.get("reply_rate_pct", 0),
        email_bounced=email.get("bounced", 0),
        reply_breakdown=reply_breakdown,
        research_count=research.get("companies_researched", 0),
        avg_pqs=research.get("avg_pqs", 0),
        qualified_pct=research.get("qualified_pct", 0),
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

def _render_html(narrative: str, m: dict, date_str: str) -> str:
    email_7d = m.get("email_7d", {})
    pipeline = m.get("pipeline", {})
    spend = m.get("api_spend", {})

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
        elif stripped.startswith("##") or stripped.startswith("**") and stripped.endswith("**"):
            label = stripped.lstrip("#").strip().strip("*")
            html_body += f"<h3 style='color:#1a1a2e;margin:20px 0 6px'>{label}</h3>"
        elif stripped.startswith("- ") or stripped.startswith("* "):
            html_body += f"<li style='margin:4px 0'>{stripped[2:]}</li>"
        elif stripped[0].isdigit() and stripped[1] in ".)" and len(stripped) > 2:
            html_body += f"<li style='margin:4px 0'>{stripped[2:].strip()}</li>"
        else:
            html_body += f"<p style='margin:8px 0'>{stripped}</p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;padding:24px;color:#222">

  <div style="background:#1a1a2e;color:#fff;padding:20px 24px;border-radius:8px;margin-bottom:24px">
    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:.7">Daily GTM Brief</div>
    <div style="font-size:22px;font-weight:700;margin-top:4px">ProspectIQ — {date_str}</div>
  </div>

  <!-- Stats row -->
  <div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap">
    <div style="flex:1;min-width:120px;background:#f5f5f5;border-radius:6px;padding:14px 16px">
      <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Sent (7d)</div>
      <div style="font-size:26px;font-weight:700;margin-top:4px">{email_7d.get('sent',0)}</div>
    </div>
    <div style="flex:1;min-width:120px;background:#f5f5f5;border-radius:6px;padding:14px 16px">
      <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Open rate</div>
      <div style="font-size:26px;font-weight:700;margin-top:4px">{email_7d.get('open_rate_pct',0)}%</div>
    </div>
    <div style="flex:1;min-width:120px;background:#f5f5f5;border-radius:6px;padding:14px 16px">
      <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Reply rate</div>
      <div style="font-size:26px;font-weight:700;margin-top:4px">{email_7d.get('reply_rate_pct',0)}%</div>
    </div>
    <div style="flex:1;min-width:120px;background:#f5f5f5;border-radius:6px;padding:14px 16px">
      <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">API spend MTD</div>
      <div style="font-size:26px;font-weight:700;margin-top:4px">${spend.get('month_usd',0):.0f}</div>
    </div>
  </div>

  <!-- Claude narrative -->
  <div style="margin-bottom:28px">
    {html_body}
  </div>

  <!-- Pipeline table -->
  <div style="background:#f9f9f9;border-radius:6px;padding:16px 20px;margin-bottom:24px">
    <div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#888;margin-bottom:10px">Pipeline Snapshot</div>
    <table style="border-collapse:collapse;width:100%">
      {pipeline_rows}
    </table>
  </div>

  <div style="font-size:11px;color:#aaa;border-top:1px solid #eee;padding-top:12px">
    Generated by ProspectIQ GTM Engine · {m.get('as_of','')}
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

        logger.info("Daily report: generating Claude narrative...")
        prompt = _build_report_prompt(m)
        narrative = _call_claude(prompt, settings.anthropic_api_key)

        date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
        html = _render_html(narrative, m, date_str)

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
