"""AI-powered event analysis — sentiment, intent signals, next action recommendation.

Calls Claude to analyze an inbound event in the context of the full conversation
thread, contact profile, and company research. Returns structured recommendations
for next action, sentiment classification, and a suggested follow-up message.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from anthropic import Anthropic

from backend.app.core.config import get_settings
from backend.app.core.cost_tracker import log_cost
from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# Sentiment → PQS engagement delta
_SENTIMENT_PQS_DELTA = {
    "positive": 5,
    "neutral": 2,
    "negative": -3,
}

# Default next-action delay by event type (business days to add)
_DEFAULT_DELAY_DAYS = {
    "response_received": 1,
    "connection_accepted": 1,
    "meeting_held": 2,
    "email_opened": 3,
    "link_clicked": 2,
    "profile_viewed": 3,
}


def _format_thread(events: list[dict]) -> str:
    """Format the conversation thread for the prompt."""
    if not events:
        return "(No prior interactions)"
    lines: list[str] = []
    for ev in events:
        dt = (ev.get("created_at") or "")[:10]
        direction = ev.get("direction") or "unknown"
        channel = ev.get("channel") or "unknown"
        event_type = ev.get("event_type") or ""
        body = (ev.get("body") or "").strip()
        if body:
            body_preview = body[:300] + ("..." if len(body) > 300 else "")
        else:
            body_preview = "(no body)"
        lines.append(
            f"[{dt}] {direction.upper()} via {channel} — {event_type}\n  {body_preview}"
        )
    return "\n\n".join(lines)


def _format_drafts(drafts: list[dict]) -> str:
    """Format prepared outreach drafts for the prompt."""
    if not drafts:
        return "(No prepared drafts available)"
    lines: list[str] = []
    for d in drafts[:3]:
        seq = d.get("sequence_name") or ""
        body = (d.get("body") or "")[:200]
        lines.append(f"Draft ({seq}): {body}")
    return "\n".join(lines)


def _parse_response(text: str, fallback_date: str) -> dict:
    """Parse Claude's structured response into a result dict."""
    result: dict[str, Any] = {
        "sentiment": None,
        "sentiment_reason": None,
        "signals": [],
        "next_action": "Follow up with the prospect",
        "next_action_date": fallback_date,
        "suggested_message": None,
        "action_reasoning": "",
        "pqs_delta": 0,
    }

    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().upper()
        value = value.strip()

        if key == "SENTIMENT":
            v = value.lower()
            if v in ("positive", "neutral", "negative"):
                result["sentiment"] = v
                result["pqs_delta"] = _SENTIMENT_PQS_DELTA.get(v, 0)
        elif key == "SENTIMENT_REASON":
            result["sentiment_reason"] = value
        elif key == "SIGNALS":
            result["signals"] = [s.strip() for s in value.split(",") if s.strip()]
        elif key == "NEXT_ACTION":
            result["next_action"] = value
        elif key == "NEXT_ACTION_DATE":
            result["next_action_date"] = value if value else fallback_date
        elif key == "SUGGESTED_MESSAGE":
            result["suggested_message"] = value if value else None
        elif key == "REASONING":
            result["action_reasoning"] = value
        elif key == "PQS_DELTA":
            try:
                result["pqs_delta"] = int(value)
            except ValueError:
                pass

    return result


async def analyze_inbound_event(
    db: Database,
    contact_id: str,
    company_id: str,
    new_event_body: str,
    new_event_channel: str,
    new_event_type: str,
) -> dict:
    """Analyze an inbound event using Claude and return structured recommendations.

    Returns:
        {
            "sentiment": "positive" | "neutral" | "negative" | None,
            "sentiment_reason": str | None,
            "signals": list[str],
            "next_action": str,
            "next_action_date": str (ISO date),
            "suggested_message": str | None,
            "action_reasoning": str,
            "pqs_delta": int,
        }
    """
    settings = get_settings()
    fallback_date = (date.today() + timedelta(days=2)).isoformat()

    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping event analysis")
        return {
            "sentiment": "neutral",
            "sentiment_reason": "AI analysis unavailable",
            "signals": [],
            "next_action": "Follow up with the prospect",
            "next_action_date": fallback_date,
            "suggested_message": None,
            "action_reasoning": "Anthropic API key not configured.",
            "pqs_delta": 0,
        }

    # ------------------------------------------------------------------
    # 1. Gather context: contact, company, research, prior events, drafts
    # ------------------------------------------------------------------
    contact: dict = {}
    company: dict = {}
    research: dict = {}
    prior_events: list[dict] = []
    drafts: list[dict] = []

    try:
        result = db.client.table("contacts").select("*").eq("id", contact_id).execute()
        contact = result.data[0] if result.data else {}
    except Exception as e:
        logger.warning(f"Failed to fetch contact for event analysis: {e}")

    try:
        result = db.client.table("companies").select("*").eq("id", company_id).execute()
        company = result.data[0] if result.data else {}
    except Exception as e:
        logger.warning(f"Failed to fetch company for event analysis: {e}")

    try:
        result = (
            db.client.table("research_intelligence")
            .select("*")
            .eq("company_id", company_id)
            .execute()
        )
        research = result.data[0] if result.data else {}
    except Exception as e:
        logger.warning(f"Failed to fetch research for event analysis: {e}")

    try:
        result = (
            db.client.table("contact_events")
            .select("*")
            .eq("contact_id", contact_id)
            .order("created_at")
            .limit(20)
            .execute()
        )
        prior_events = result.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch prior events for event analysis: {e}")

    try:
        result = (
            db.client.table("outreach_drafts")
            .select("body, sequence_name")
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        drafts = result.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch drafts for event analysis: {e}")

    # ------------------------------------------------------------------
    # 2. Build the analysis prompt
    # ------------------------------------------------------------------
    contact_name = contact.get("full_name") or "Unknown"
    contact_title = contact.get("title") or "Unknown title"
    contact_seniority = contact.get("seniority") or ""
    company_name = company.get("name") or "Unknown company"
    industry = company.get("industry") or ""
    research_summary = (
        research.get("claude_analysis")
        or company.get("research_summary")
        or "(No research available)"
    )
    pain_signals_raw = company.get("pain_signals") or []
    pain_signals = (
        ", ".join(pain_signals_raw)
        if isinstance(pain_signals_raw, list)
        else str(pain_signals_raw)
    ) or "(none identified)"
    personalization_hooks_raw = company.get("personalization_hooks") or []
    hooks = (
        ", ".join(personalization_hooks_raw)
        if isinstance(personalization_hooks_raw, list)
        else str(personalization_hooks_raw)
    ) or "(none)"

    thread_text = _format_thread(prior_events)
    drafts_text = _format_drafts(drafts)
    today_str = date.today().isoformat()

    prompt = f"""You are a B2B sales AI assistant helping analyze a prospect's response and recommend the next action.

## Contact Profile
- Name: {contact_name}
- Title: {contact_title} ({contact_seniority})
- Company: {company_name} ({industry})

## Company Intelligence
{research_summary}

Pain signals: {pain_signals}
Personalization hooks: {hooks}

## Conversation Thread (chronological)
{thread_text}

## New Inbound Event (what just happened)
Channel: {new_event_channel}
Type: {new_event_type}
Message:
{new_event_body or "(no message body)"}

## Available Prepared Messages
{drafts_text}

## Today's Date
{today_str}

---
Analyze the new inbound event and provide your recommendation. Respond ONLY in this exact format — one value per line, no extra commentary:

SENTIMENT: positive|neutral|negative
SENTIMENT_REASON: One sentence explaining why
SIGNALS: comma-separated intent signals (e.g. admitted_pain:reactive_maintenance, openness:volunteered_info, budget_mention, timeline_urgency, competitor_mention, no_objection)
NEXT_ACTION: One clear sentence describing the next action to take
NEXT_ACTION_DATE: YYYY-MM-DD (when to take this action)
SUGGESTED_MESSAGE: The actual message text to send (or leave blank if no message needed yet)
REASONING: One or two sentences explaining your recommendation
PQS_DELTA: integer score change (-5 to +10)"""

    # ------------------------------------------------------------------
    # 3. Call Claude
    # ------------------------------------------------------------------
    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        model = "claude-haiku-4-20250414"

        response = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        log_cost(
            provider="anthropic",
            model=model,
            endpoint="event_analyzer",
            company_id=company_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        raw_text = response.content[0].text if response.content else ""
        logger.debug(f"Event analysis raw response:\n{raw_text}")
        return _parse_response(raw_text, fallback_date)

    except Exception as e:
        logger.error(f"Claude event analysis failed: {e}")
        return {
            "sentiment": None,
            "sentiment_reason": "Analysis failed",
            "signals": [],
            "next_action": "Follow up with the prospect",
            "next_action_date": fallback_date,
            "suggested_message": None,
            "action_reasoning": f"AI analysis error: {e}",
            "pqs_delta": 0,
        }
