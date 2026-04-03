"""ReplyClassifier — Classifies inbound prospect replies using Claude Haiku.

Designed for the HITL pipeline: called from the webhook handler on every
inbound reply before inserting into thread_messages and hitl_queue.

Classification categories (aligned with ThreadAgent):
    interested   — wants a call / demo / more info
    objection    — specific concern (incumbent, budget, timing)
    referral     — points to a colleague in the org
    soft_no      — polite decline, not hostile
    out_of_office — auto-reply with return date
    unsubscribe  — remove me from this list
    bounce       — delivery failure / NDR
    other        — doesn't fit cleanly; human review needed
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Optional

import anthropic
from pydantic import BaseModel

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class ReplyClassification(BaseModel):
    intent: str  # one of the 8 categories
    confidence: float  # 0.0–1.0
    extracted_entities: dict  # {"competitors": [], "pain_points": [], "timeline": ""}
    summary: str  # 1-sentence summary of what prospect said
    next_action_suggestion: str
    auto_actionable: bool  # True for unsubscribe/bounce — no human review needed


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

_SYSTEM = """You are a B2B sales reply classifier. Your job is to classify incoming prospect replies and extract key signals for the sales team.

Classify the incoming prospect reply into exactly one of these categories:
- interested: wants more info, open to a call/demo, encouraging signal
- objection: specific concern — incumbent system, budget, timing, implementation fear
- referral: directing you to a colleague ("talk to our VP Ops", cc'd someone)
- soft_no: polite decline but not hostile ("not a priority", "come back later")
- out_of_office: automatic out-of-office reply; extract return date if present
- unsubscribe: explicitly requests removal from communications
- bounce: technical delivery failure / NDR notification
- other: doesn't fit cleanly; needs human review

Also extract:
- competitors mentioned (e.g. "we use SAP PM", "IBM Maximo")
- pain points hinted at (e.g. "our downtime is already low")
- timeline signals (e.g. "come back Q3", "evaluating in 6 months")
- a 1-sentence neutral summary of what the prospect said
- recommended next action for the sales rep

Output ONLY valid JSON. No markdown, no explanation."""

_USER = """Classify this inbound reply.

THREAD CONTEXT:
Company: {company_name}
Contact: {contact_name}
Sequence step: {sequence_step}
Previous messages in thread: {message_count}

REPLY:
{reply_body}

OUTPUT FORMAT (JSON):
{{
    "intent": "interested|objection|referral|soft_no|out_of_office|unsubscribe|bounce|other",
    "confidence": 0.0,
    "extracted_entities": {{
        "competitors": [],
        "pain_points": [],
        "timeline": ""
    }},
    "summary": "One sentence summary of what the prospect said.",
    "next_action_suggestion": "What the sales rep should do next."
}}

Output ONLY valid JSON."""


# ---------------------------------------------------------------------------
# Simple in-process cache — keyed by a hash of the reply body
# ---------------------------------------------------------------------------

_classification_cache: dict[str, ReplyClassification] = {}


def _body_key(body: str) -> str:
    """Cheap deterministic cache key from body text."""
    import hashlib
    return hashlib.sha256(body.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class ReplyClassifier:
    """Classify inbound prospect replies using Claude Haiku."""

    AUTO_ACTION_INTENTS = {"unsubscribe", "bounce"}
    PRIORITY_MAP = {
        "interested": 1,
        "referral": 2,
        "objection": 3,
        "out_of_office": 4,
        "soft_no": 5,
        "other": 5,
        "unsubscribe": 9,
        "bounce": 9,
    }

    def classify(
        self,
        body_text: str,
        thread_context: Optional[dict] = None,
    ) -> ReplyClassification:
        """Classify ``body_text`` using Claude Haiku.

        ``thread_context`` keys (all optional):
            company_name, contact_name, sequence_step, previous_messages (int)

        Results are cached in-process by body hash so duplicate webhook
        deliveries are idempotent without a second API call.
        """
        cache_key = _body_key(body_text)
        if cache_key in _classification_cache:
            logger.debug("ReplyClassifier: cache hit for body hash %s", cache_key[:8])
            return _classification_cache[cache_key]

        ctx = thread_context or {}
        prompt = _USER.format(
            company_name=ctx.get("company_name", "Unknown"),
            contact_name=ctx.get("contact_name", "Unknown"),
            sequence_step=ctx.get("sequence_step", 1),
            message_count=ctx.get("previous_messages", 0),
            reply_body=body_text[:1200],  # guard against enormous bodies
        )

        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        # Strip optional markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        parsed = json.loads(raw)

        intent = parsed.get("intent", "other")
        result = ReplyClassification(
            intent=intent,
            confidence=float(parsed.get("confidence", 0.5)),
            extracted_entities=parsed.get("extracted_entities", {
                "competitors": [], "pain_points": [], "timeline": ""
            }),
            summary=parsed.get("summary", ""),
            next_action_suggestion=parsed.get("next_action_suggestion", ""),
            auto_actionable=intent in self.AUTO_ACTION_INTENTS,
        )

        _classification_cache[cache_key] = result
        return result

    def priority_for(self, intent: str) -> int:
        """Return HITL queue priority for the given intent (lower = more urgent)."""
        return self.PRIORITY_MAP.get(intent, 5)
