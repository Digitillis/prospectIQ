"""Thread Agent — Adaptive campaign thread manager.

Handles the human-in-the-loop classification + context-aware reply drafting
for the campaign thread system. Uses Claude Sonnet for all AI calls.

Phase 1: Manual reply insert → classify → confirm → draft next message
Phase 2: Webhook auto-capture (called by webhook handler)
Phase 3: Full sequencer ownership via Instantly sending API

Classification categories (for a COLD EMAIL context):
  interested       — wants to know more, open to a call
  objection        — has a specific concern (incumbent, budget, timing)
  referral         — pointing you to someone else in the org
  soft_no          — not right now but not a hard rejection
  out_of_office    — auto-reply, follow up after return date
  unsubscribe      — remove me
  bounce           — delivery failure
  other            — doesn't fit the above (human review needed)
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings
from backend.app.core.thread_manager import ThreadManager

console = Console()
logger = logging.getLogger(__name__)

# Classification labels shown to the user
CLASSIFICATION_LABELS = {
    "interested":   "✅  Interested — open to a call/demo",
    "objection":    "⚡  Objection — specific pushback (competitor, budget, timing)",
    "referral":     "➡️  Referral — pointing to someone else in the org",
    "soft_no":      "🌫️  Soft No — not now, but not a hard rejection",
    "out_of_office":"📅  Out of Office — auto-reply",
    "unsubscribe":  "🚫  Unsubscribe — remove me",
    "bounce":       "❌  Bounce — delivery failure",
    "other":        "❓  Other — needs human review",
}

CLASSIFY_SYSTEM = """You are an expert B2B sales analyst for Digitillis, an AI-native manufacturing intelligence platform.

Your job: classify an incoming prospect reply and provide the next-message strategy.

Digitillis in one line: AI agents that predict equipment failures 18+ days in advance, so manufacturers avoid unplanned downtime.

Founder: Avi (Avanish Mehrotra), Co-Founder & MD, avi@digitillis.io

Classification categories:
- interested: Prospect wants more info, a demo, a call, or says something encouraging
- objection: Has a specific concern — incumbent system ("we have SAP PM"), budget ("not in budget"), timing ("come back Q3"), or implementation fear
- referral: Directs you to a colleague in the org ("talk to our VP Ops", "cc'd John")
- soft_no: Polite decline but not hostile ("not a priority right now", "we're focused elsewhere")
- out_of_office: Automatic reply; note any return date
- unsubscribe: Explicitly requests removal
- bounce: Technical delivery failure or auto-rejection notice
- other: Doesn't fit the above cleanly

Output ONLY valid JSON. No markdown."""

CLASSIFY_USER = """Classify this prospect reply in context of the thread.

THREAD CONTEXT:
Company: {company_name} | Sub-sector: {sub_sector} | Tier: T{tier}
Contact: {contact_name}, {contact_title}
Research summary: {research_summary}

LAST OUTBOUND MESSAGE (step {current_step}):
Subject: {last_subject}
---
{last_body}
---

INCOMING REPLY:
Subject: {reply_subject}
---
{reply_body}
---

OUTPUT FORMAT (JSON):
{{
    "classification": "interested|objection|referral|soft_no|out_of_office|unsubscribe|bounce|other",
    "confidence": 0.0,
    "reasoning": "One sentence explaining the classification",
    "extracted_signal": "The single most important thing they said (direct quote or paraphrase)",
    "recommended_next_action": "What the next message should accomplish in 1 sentence",
    "return_date": null
}}"""

DRAFT_SYSTEM = """You are a world-class B2B sales writer for Digitillis, an AI-native manufacturing intelligence platform.

Digitillis capabilities:
- 32 AI agents across 7 manufacturing domains (predictive maintenance, quality, energy, supply chain, OEE, safety, sustainability)
- Predictive maintenance: 18+ day advance warning, 87% confidence, across 100+ sensor types
- Integrations: SAP PM, Maximo, Plex, Infor EAM, OPC-UA, MQTT, Modbus
- Pilot: 6-8 weeks, no long-term commitment required
- Proven: 25-40% maintenance cost reduction in pilots

Founder: Avi (Avanish Mehrotra), Co-Founder & MD
Email: avi@digitillis.io

You are writing a CONTEXT-AWARE reply to a prospect who has responded to our outreach.
The full thread history is provided. Your reply must:
1. Directly acknowledge what they said (their exact signal, not a generic acknowledgment)
2. Move the conversation forward based on the classification
3. Match the tone of a founder reaching out personally — not a sales template
4. Be SHORT: max 120 words unless the situation absolutely requires more
5. End with a clear, single next step

Sign off format (always use exactly this):
Avi
Co-Founder, Digitillis
avi@digitillis.io

Output ONLY valid JSON. No markdown."""

DRAFT_USER = """Draft the next reply in this conversation thread.

COMPANY: {company_name} | Sub-sector: {sub_sector} | Tier: T{tier}
CONTACT: {contact_name}, {contact_title}

RESEARCH INTELLIGENCE:
{research_summary}

PERSONALIZATION HOOKS:
{personalization_hooks}

TECHNOLOGY STACK: {technology_stack}

FULL THREAD HISTORY (oldest first):
{thread_history}

INCOMING REPLY CLASSIFICATION: {classification}
CLASSIFICATION REASONING: {classification_reasoning}
EXTRACTED SIGNAL: {extracted_signal}
RECOMMENDED NEXT ACTION: {recommended_next_action}

DRAFTING STRATEGY BY CLASSIFICATION:
- interested: Propose 2-3 specific meeting slots this week. Reinforce one specific pain signal from their operation.
- objection: Address the specific objection head-on. For incumbent systems: explain integration path. For budget: offer pilot with no upfront commitment. For timing: offer a 15-minute primer now, full conversation later. Do NOT be defensive.
- referral: Gracefully ask for an intro or cc. Thank them. Keep it short.
- soft_no: Accept gracefully, plant a seed, offer to reconnect at a specific trigger event (Q3 budget cycle, next audit, etc.).
- other: Ask one clarifying question to understand where they stand.

MAX WORDS: 120 (short is better — this is a founder's personal reply, not a sales template)

OUTPUT FORMAT (JSON):
{{
    "subject": "Re: [keep their subject line, don't change it]",
    "body": "The full reply body including the sign-off block",
    "strategy_used": "One sentence explaining the angle you took and why"
}}"""


class ThreadAgent(BaseAgent):
    """Adaptive campaign thread manager with human-in-the-loop classification."""

    agent_name = "thread"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.thread_manager = ThreadManager(self.db)

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def run(self, **kwargs) -> AgentResult:
        """Not used directly — call classify_and_draft() or process_webhook_reply() instead."""
        result = AgentResult()
        result.add_detail("N/A", "info", "Use classify_and_draft() or process_webhook_reply() directly.")
        return result

    def classify_reply(
        self,
        thread_id: str,
        reply_subject: str,
        reply_body: str,
        sent_at: str | None = None,
        source: str = "manual",
    ) -> dict:
        """Insert an inbound reply, classify it with Sonnet, and return classification.

        Does NOT prompt the user — that is the caller's responsibility (see manage_thread.py).
        Returns a dict with: message_id, thread, classification, confidence, reasoning, etc.
        """
        thread = self.thread_manager.get_thread(thread_id)
        if not thread:
            raise ValueError(f"Thread {thread_id} not found")

        # Insert the inbound message (auto-pauses the thread)
        msg = self.thread_manager.add_inbound_message(
            thread_id=thread_id,
            subject=reply_subject,
            body=reply_body,
            sent_at=sent_at,
            source=source,
        )

        # Get context for classification
        company = self.db.get_company(thread["company_id"])
        contacts = self.db.get_contacts_for_company(thread["company_id"])
        contact = next((c for c in contacts if c["id"] == thread["contact_id"]), {})
        research = self.db.get_research(thread["company_id"])
        last_outbound = self.thread_manager.get_last_outbound(thread_id)

        company_name = company.get("name", "Unknown") if company else "Unknown"
        research_summary = ""
        if research:
            research_summary = research.get("company_description", "") or research.get("pain_signals", "")
        if not research_summary and company:
            research_summary = company.get("research_summary", "No research available")

        # Build the classification prompt
        prompt = CLASSIFY_USER.format(
            company_name=company_name,
            sub_sector=company.get("sub_sector", company.get("industry", "Manufacturing")) if company else "Manufacturing",
            tier=company.get("tier", "2") if company else "2",
            contact_name=contact.get("full_name", contact.get("first_name", "Unknown")),
            contact_title=contact.get("title", "Unknown"),
            research_summary=research_summary[:600] if research_summary else "No research available",
            current_step=thread.get("current_step", 1),
            last_subject=last_outbound.get("subject", "(unknown)") if last_outbound else "(unknown)",
            last_body=(last_outbound.get("body", "(original email not available)") if last_outbound else "(original email not available)")[:800],
            reply_subject=reply_subject,
            reply_body=reply_body[:800],
        )

        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        self.track_cost(
            provider="anthropic",
            model="claude-sonnet-4-6",
            endpoint="/messages",
            company_id=thread["company_id"],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        raw = response.content[0].text.strip()
        parsed = json.loads(raw)

        return {
            "message_id": msg["id"],
            "thread": thread,
            "company": company,
            "contact": contact,
            "research": research,
            "reply_subject": reply_subject,
            "reply_body": reply_body,
            "classification": parsed.get("classification", "other"),
            "confidence": parsed.get("confidence", 0.5),
            "reasoning": parsed.get("reasoning", ""),
            "extracted_signal": parsed.get("extracted_signal", ""),
            "recommended_next_action": parsed.get("recommended_next_action", ""),
            "return_date": parsed.get("return_date"),
        }

    def draft_next_message(self, classification_result: dict) -> dict:
        """Draft the next message given a confirmed classification result.

        Returns a dict with: subject, body, strategy_used
        """
        thread = classification_result["thread"]
        company = classification_result["company"]
        contact = classification_result["contact"]
        research = classification_result.get("research") or {}

        # Get personalization hooks
        hooks: list[str] = []
        if company:
            hooks.extend(company.get("personalization_hooks") or [])
        if research:
            hooks.extend(research.get("personalization_hooks") or [])
        if isinstance(hooks, str):
            try:
                import json as _json
                hooks = _json.loads(hooks)
            except Exception:
                hooks = [hooks]

        # Tech stack
        tech_stack = ""
        if research:
            tech = research.get("technology_stack") or {}
            if isinstance(tech, dict):
                parts = []
                for k, v in tech.items():
                    if v:
                        parts.append(f"{k}: {v}" if not isinstance(v, list) else f"{k}: {', '.join(v)}")
                tech_stack = "; ".join(parts[:4])
            elif isinstance(tech, str):
                tech_stack = tech[:200]

        # Build thread history string
        messages = self.thread_manager.get_thread_messages(thread["id"])
        history_parts = []
        for m in messages:
            direction = "→ OUTBOUND" if m["direction"] == "outbound" else "← INBOUND"
            snippet = (m.get("body") or "")[:400]
            history_parts.append(
                f"[Step {thread['current_step']} | {direction}]\n"
                f"Subject: {m.get('subject', '(no subject)')}\n"
                f"{snippet}"
                + ("..." if len(m.get("body", "")) > 400 else "")
            )
        thread_history = "\n\n---\n\n".join(history_parts)

        research_summary = ""
        if research:
            research_summary = research.get("company_description", "") or ""
        if not research_summary and company:
            research_summary = company.get("research_summary", "")

        prompt = DRAFT_USER.format(
            company_name=company.get("name", "Unknown") if company else "Unknown",
            sub_sector=company.get("sub_sector", company.get("industry", "Manufacturing")) if company else "Manufacturing",
            tier=company.get("tier", "2") if company else "2",
            contact_name=contact.get("full_name", contact.get("first_name", "Unknown")),
            contact_title=contact.get("title", "Unknown"),
            research_summary=research_summary[:500],
            personalization_hooks="\n".join(f"- {h}" for h in hooks[:5]) if hooks else "None available",
            technology_stack=tech_stack or "Unknown",
            thread_history=thread_history,
            classification=classification_result["classification"],
            classification_reasoning=classification_result["reasoning"],
            extracted_signal=classification_result["extracted_signal"],
            recommended_next_action=classification_result["recommended_next_action"],
        )

        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=DRAFT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        self.track_cost(
            provider="anthropic",
            model="claude-sonnet-4-6",
            endpoint="/messages",
            company_id=thread["company_id"],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        raw = response.content[0].text.strip()
        parsed = json.loads(raw)

        return {
            "subject": parsed.get("subject", "Re: " + classification_result["reply_subject"]),
            "body": parsed.get("body", ""),
            "strategy_used": parsed.get("strategy_used", ""),
        }

    def save_draft(
        self,
        thread: dict,
        contact: dict,
        draft: dict,
        classification: str,
    ) -> str:
        """Save the drafted next message to outreach_drafts and return the draft ID."""
        draft_data = {
            "company_id": thread["company_id"],
            "contact_id": thread["contact_id"],
            "channel": "email",
            "sequence_name": f"thread_reply_{thread['id'][:8]}",
            "sequence_step": (thread.get("next_step") or thread.get("current_step", 1) + 1),
            "subject": draft["subject"],
            "body": draft["body"],
            "personalization_notes": (
                f"Thread reply. Classification: {classification}. "
                f"Strategy: {draft.get('strategy_used', '')}"
            ),
            "approval_status": "pending",
        }
        return self.db.insert_outreach_draft(draft_data)

    # ------------------------------------------------------------------
    # Phase 2: Webhook handler (auto-capture)
    # ------------------------------------------------------------------

    def process_webhook_reply(
        self,
        sender_email: str,
        reply_subject: str,
        reply_body: str,
        sent_at: str | None = None,
        raw_payload: dict | None = None,
    ) -> dict | None:
        """Process an inbound reply from a webhook (Instantly or Gmail).

        Finds the active thread for the sender, inserts the inbound message,
        and classifies it automatically (confidence >= 0.85 → auto-confirm;
        lower → queue for human review).

        Returns the classification result dict or None if no thread found.
        """
        thread = self.thread_manager.find_thread_by_email(sender_email)
        if not thread:
            logger.warning(f"No active thread found for {sender_email}")
            return None

        result = self.classify_reply(
            thread_id=thread["id"],
            reply_subject=reply_subject,
            reply_body=reply_body,
            sent_at=sent_at,
            source="instantly_webhook" if raw_payload else "gmail_webhook",
        )

        # Auto-confirm high-confidence classifications for non-human-review categories
        auto_confirm_categories = {"out_of_office", "unsubscribe", "bounce"}
        if (
            result["confidence"] >= 0.85
            and result["classification"] in auto_confirm_categories
        ):
            self._apply_classification_actions(
                thread=result["thread"],
                message_id=result["message_id"],
                classification=result["classification"],
                confidence=result["confidence"],
                reasoning=result["reasoning"],
                confirmed_by="auto",
            )
            result["auto_confirmed"] = True
        else:
            result["auto_confirmed"] = False
            result["needs_review"] = True

        return result

    # ------------------------------------------------------------------
    # Internal: apply side effects of a confirmed classification
    # ------------------------------------------------------------------

    def _apply_classification_actions(
        self,
        thread: dict,
        message_id: str,
        classification: str,
        confidence: float,
        reasoning: str,
        confirmed_by: str = "user",
    ) -> None:
        """Update DB state based on confirmed classification."""
        # Update the message with confirmed classification
        self.thread_manager.update_message_classification(
            message_id=message_id,
            classification=classification,
            confidence=confidence,
            reasoning=reasoning,
            confirmed_by=confirmed_by,
        )

        company_id = thread["company_id"]

        if classification == "interested":
            self.db.update_company(company_id, {"status": "engaged"})

        elif classification in ("soft_no",):
            # Keep thread paused, set a future follow-up marker
            self.db.update_company(company_id, {"status": "qualified"})  # stays in pipeline

        elif classification == "unsubscribe":
            self.thread_manager.close_thread(thread["id"], status="unsubscribed")
            self.db.update_contact(thread["contact_id"], {"outreach_state": "unsubscribed"})

        elif classification == "bounce":
            self.thread_manager.close_thread(thread["id"], status="bounced")
            self.db.update_contact(thread["contact_id"], {"outreach_state": "bounced"})

        elif classification == "referral":
            self.db.update_company(company_id, {"status": "engaged"})  # warm — note the referral
