"""Reply Agent -- Classifies incoming replies and drafts responses.

Uses Claude Haiku (1 call per reply) to classify prospect replies,
determine sentiment, and draft appropriate follow-up responses.
"""

from __future__ import annotations

import asyncio
import json
import logging

import anthropic

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_sequences_config
from backend.app.core.limits import L
from backend.app.core.notifications import notify_reply_received

logger = logging.getLogger(__name__)


def _build_reply_system_prompt() -> str:
    """Build the reply classification system prompt from offer_context + outreach_guidelines.

    Reads config fresh on each call so dashboard edits are picked up immediately.
    Falls back to generic instructions if config files are missing.
    """
    try:
        from backend.app.core.config import get_offer_context, get_outreach_guidelines
        offer = get_offer_context()
        guidelines = get_outreach_guidelines()
    except Exception:
        offer = {}
        guidelines = {}

    sender = guidelines.get("sender", {})
    sender_name = sender.get("name", "the sender")
    sender_title = sender.get("title", "")
    company_name = offer.get("company") or sender.get("company", "the company")
    core_vp = (offer.get("core_value_prop") or "").strip()
    capabilities = offer.get("capabilities") or []

    sender_line = sender_name
    if sender_title and company_name:
        sender_line = f"{sender_name}, {sender_title} at {company_name}"
    elif sender_title:
        sender_line = f"{sender_name}, {sender_title}"

    caps_block = "\n".join(f"- {c}" for c in capabilities[:8]) if capabilities else (
        "- Refer to offer_context.yaml for product capabilities"
    )

    return f"""You are a B2B sales reply classifier for {company_name}. Your job is to classify incoming prospect replies and draft appropriate responses.

{company_name} — {core_vp}

Key capabilities:
{caps_block}

Sender: {sender_line}

Classify the reply into exactly one of these categories:
- positive: Prospect is interested, wants a meeting, demo, or more info
- question: Prospect has specific questions but hasn't committed
- negative: Prospect is not interested or declines
- out_of_office: Automatic out-of-office reply
- unsubscribe: Prospect requests removal from communications
- bounce: Technical delivery failure / bounce notification

Draft an appropriate response based on the classification.
Always follow the reply strategy from the STRATEGY INSTRUCTIONS provided.
If no specific strategy is given, use these defaults:
- positive: Warm, concise response proposing 2-3 specific meeting times. No filler.
- question: Helpful, specific answer to their exact question. Reference capabilities without being pushy.
- negative: Polite acknowledgment. Thank them for their time. No pressure.
- out_of_office: No response needed; note the return date if available.
- unsubscribe: Brief confirmation that they have been removed.
- bounce: No response needed; flag for review.

Output ONLY valid JSON. No markdown, no explanation."""

REPLY_CLASSIFICATION_USER = """Classify this incoming reply and draft an appropriate response.

PROSPECT:
- Name: {prospect_name}
- Company: {company_name}
- Title: {their_title}

ORIGINAL OUTREACH:
- Subject: {original_subject}
- Body:
{original_body}

INCOMING REPLY:
{reply_body}

COMPANY CONTEXT:
- Research Summary: {company_context}
- Prospect Qualification Score: {pqs_total}

STRATEGY INSTRUCTIONS (follow these when drafting the response):
{strategy_instructions}

OUTPUT FORMAT (JSON):
{{
    "classification": "positive|question|negative|out_of_office|unsubscribe|bounce",
    "sentiment": "very_positive|positive|neutral|negative|very_negative",
    "strategy_used": "name of the reply strategy used",
    "response_draft_subject": "Re: subject line for the response",
    "response_draft_body": "The drafted response body. Use the sender signature from the system prompt.",
    "notes": "Brief internal notes about the reply and reasoning",
    "urgency": "high|medium|low"
}}

Output ONLY valid JSON. No markdown, no explanation."""


class ReplyAgent(BaseAgent):
    """Classify incoming replies and draft appropriate responses."""

    agent_name = "reply"

    def run(self, reply_data: dict | None = None, **kwargs) -> AgentResult:
        """Classify an incoming reply and take appropriate action.

        Args:
            reply_data: Dictionary with keys:
                - company_id (required)
                - contact_id (required)
                - subject (required)
                - body (required)
                - outreach_draft_id (required)

        Returns:
            AgentResult with classification and action details.
        """
        result = AgentResult()

        if not reply_data:
            logger.warning("No reply_data provided. Expected dict with company_id, contact_id, subject, body, outreach_draft_id.")
            result.success = False
            result.errors = 1
            result.add_detail("N/A", "error", "No reply_data provided")
            return result

        # Validate required fields
        required_fields = ["company_id", "contact_id", "subject", "body", "outreach_draft_id"]
        missing = [f for f in required_fields if not reply_data.get(f)]
        if missing:
            logger.warning(f"Missing required fields in reply_data: {', '.join(missing)}")
            result.success = False
            result.errors = 1
            result.add_detail("N/A", "error", f"Missing fields: {', '.join(missing)}")
            return result

        company_id = reply_data["company_id"]
        contact_id = reply_data["contact_id"]
        reply_subject = reply_data["subject"]
        reply_body = reply_data["body"]
        outreach_draft_id = reply_data["outreach_draft_id"]

        settings = get_settings()

        try:
            # Fetch company, contact, and original outreach draft
            company = self.db.get_company(company_id)
            if not company:
                result.success = False
                result.errors = 1
                result.add_detail("N/A", "error", f"Company {company_id} not found")
                return result

            company_name = company.get("name", "Unknown")

            # Get contact -- query contacts table by ID
            contacts = self.db.get_contacts_for_company(company_id)
            contact = next((c for c in contacts if c.get("id") == contact_id), None)
            if not contact:
                logger.warning(f"{company_name}: Contact {contact_id} not found. Proceeding with limited context.")
                contact = {"full_name": "Unknown", "title": "Unknown"}

            # Get original outreach draft
            draft_result = (
                self.db.client.table("outreach_drafts")
                .select("*")
                .eq("id", outreach_draft_id)
                .execute()
            )
            original_draft = draft_result.data[0] if draft_result.data else None
            original_subject = original_draft.get("subject", reply_subject) if original_draft else reply_subject
            original_body = original_draft.get("body", "(Original message not available)") if original_draft else "(Original message not available)"
            # Reply-to-signal attribution: surface which signal personalised the
            # original outreach so notifications reveal what triggered the reply.
            top_signal_type = original_draft.get("top_signal_type") if original_draft else None

            # Get research for company context
            research = self.db.get_research(company_id)
            research_summary = company.get("research_summary", "No research available")
            if research and research.get("company_description"):
                research_summary = research["company_description"]

            pqs_total = company.get("pqs_total", 0)

            # Load reply strategies from sequences.yaml
            strategy_instructions = _get_reply_strategy_hint(reply_body)

            # Build the classification prompt
            prompt = REPLY_CLASSIFICATION_USER.format(
                prospect_name=contact.get("full_name", contact.get("first_name", "Unknown")),
                company_name=company_name,
                their_title=contact.get("title", "Unknown"),
                original_subject=original_subject,
                original_body=original_body,
                reply_body=reply_body,
                company_context=research_summary,
                pqs_total=pqs_total,
                strategy_instructions=strategy_instructions,
            )

            # Call Claude Haiku for classification
            logger.info(f"{company_name} -- Classifying reply from {contact.get('full_name', 'Unknown')}...")

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                system=_build_reply_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )

            # Track cost
            usage = response.usage
            self.track_cost(
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                endpoint="/messages",
                company_id=company_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            # Parse response
            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            parsed = json.loads(content)

            classification = parsed.get("classification", "unknown")
            sentiment = parsed.get("sentiment", "neutral")
            response_subject = parsed.get("response_draft_subject", "")
            response_body = parsed.get("response_draft_body", "")
            notes = parsed.get("notes", "")
            urgency = parsed.get("urgency", "medium")

            logger.info(
                f"{company_name}: Classification = {classification} | "
                f"Sentiment = {sentiment} | Urgency = {urgency}"
            )

            # Take action based on classification
            if classification == "positive":
                # Create a new outreach draft (response, pending approval)
                draft_data = {
                    "company_id": company_id,
                    "contact_id": contact_id,
                    "channel": "email",
                    "sequence_name": "reply_response",
                    "sequence_step": 0,
                    "subject": response_subject,
                    "body": response_body,
                    "personalization_notes": f"Reply classification: {classification}. {notes}",
                    "approval_status": "pending",
                }
                self.db.insert_outreach_draft(draft_data)

                # Update company status to engaged
                self.db.update_company(company_id, {
                    "status": "engaged",
                    "priority_flag": urgency == "high",
                })

                if L.notify_on_positive and L.workspace_owner_email:
                    contact_name = contact.get("full_name") or contact.get("email", "Unknown")
                    asyncio.run(notify_reply_received(
                        company_name=company_name,
                        contact_name=contact_name,
                        reply_preview=reply_body,
                        workspace_email=L.workspace_owner_email,
                        signal_context=top_signal_type,
                    ))

                # A/B tracker — record reply event (non-blocking)
                try:
                    from backend.app.analytics.ab_tracker import ABTracker
                    _cid = str(contact_id).replace("-", "")
                    ab_variant = "a" if int(_cid, 16) % 2 == 0 else "b"
                    ABTracker(self.db).record_reply(contact_id=contact_id, variant=ab_variant)
                except Exception:
                    pass  # A/B tracking is non-blocking

                logger.info(f"{company_name}: POSITIVE reply -- response draft created, status -> engaged, owner notified")

            elif classification == "question":
                # Create a new outreach draft with the answer
                draft_data = {
                    "company_id": company_id,
                    "contact_id": contact_id,
                    "channel": "email",
                    "sequence_name": "reply_response",
                    "sequence_step": 0,
                    "subject": response_subject,
                    "body": response_body,
                    "personalization_notes": f"Reply classification: {classification}. {notes}",
                    "approval_status": "pending",
                }
                self.db.insert_outreach_draft(draft_data)

                if L.notify_on_question and L.workspace_owner_email:
                    contact_name = contact.get("full_name") or contact.get("email", "Unknown")
                    asyncio.run(notify_reply_received(
                        company_name=company_name,
                        contact_name=contact_name,
                        reply_preview=reply_body,
                        workspace_email=L.workspace_owner_email,
                        signal_context=top_signal_type,
                    ))

                # A/B tracker — record reply event (non-blocking)
                try:
                    from backend.app.analytics.ab_tracker import ABTracker
                    _cid = str(contact_id).replace("-", "")
                    ab_variant = "a" if int(_cid, 16) % 2 == 0 else "b"
                    ABTracker(self.db).record_reply(contact_id=contact_id, variant=ab_variant)
                except Exception:
                    pass  # A/B tracking is non-blocking

                logger.info(f"{company_name}: QUESTION reply -- answer draft created, owner notified")

            elif classification == "negative":
                # Update company status to not_interested
                self.db.update_company(company_id, {"status": "not_interested"})

                # Cancel any active engagement sequences for this company
                self._cancel_active_sequences(company_id)

                logger.warning(f"{company_name}: NEGATIVE reply -- status -> not_interested, sequences cancelled")

            elif classification == "out_of_office":
                # Log but don't change status -- follow up later
                logger.info(f"{company_name}: OUT OF OFFICE -- logged, no status change")

            elif classification == "unsubscribe":
                # Update contact status to unsubscribed
                self.db.update_contact(contact_id, {"status": "unsubscribed"})

                # Cancel active sequences
                self._cancel_active_sequences(company_id)

                logger.warning(f"{company_name}: UNSUBSCRIBE -- contact unsubscribed, sequences cancelled")

            elif classification == "bounce":
                # Update contact status to bounced, company status to bounced
                self.db.update_contact(contact_id, {"status": "bounced"})
                self.db.update_company(company_id, {"status": "bounced"})

                logger.warning(f"{company_name}: BOUNCE -- contact and company marked bounced")

            else:
                logger.warning(f"{company_name}: Unknown classification '{classification}' -- logged for review")

            # Log interaction for all classifications
            self.db.insert_interaction({
                "company_id": company_id,
                "contact_id": contact_id,
                "type": "email_replied",
                "channel": "email",
                "subject": reply_subject,
                "body": reply_body[:500] if reply_body else "",
                "source": "reply_agent",
                "metadata": {
                    "classification": classification,
                    "sentiment": sentiment,
                    "urgency": urgency,
                    "outreach_draft_id": outreach_draft_id,
                    "notes": notes,
                },
            })

            # Insert learning outcome for analytics
            self.db.insert_learning_outcome({
                "company_id": company_id,
                "contact_id": contact_id,
                "outreach_approach": "reply_response",
                "channel": "email",
                "outcome": f"replied_{classification}",
                "company_tier": company.get("tier"),
                "sub_sector": company.get("sub_sector", company.get("industry", "")),
                "persona_type": contact.get("persona_type", ""),
                "pqs_at_time": pqs_total,
            })

            # Structured outcome classification — updates outreach_outcomes, handles
            # wrong_person and unsubscribe by blocking contact in outbound_eligible_contacts,
            # and adds not-a-fit companies to icp_exclusions.
            try:
                from backend.app.agents.reply_classifier import ReplyClassifierAgent
                ReplyClassifierAgent(self.db).classify_reply(
                    reply_text=reply_body or reply_subject or "",
                    contact_id=contact_id,
                    company_id=company_id,
                    send_id=outreach_draft_id,
                    contact=contact,
                    company=company,
                )
            except Exception as _rce:
                logger.warning("ReplyClassifierAgent failed (non-blocking): %s", _rce)

            # Update threading state — reply moves company to engaged/paused
            try:
                from backend.app.core.threading_coordinator import ThreadingCoordinator
                ThreadingCoordinator(self.db).record_reply(company_id, contact_id)
            except Exception as _tce:
                logger.warning("ThreadingCoordinator.record_reply failed (non-blocking): %s", _tce)

            result.processed += 1
            result.add_detail(
                company_name,
                classification,
                f"Sentiment: {sentiment}, Urgency: {urgency}. {notes}",
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response for reply classification: {e}")
            result.errors += 1
            result.add_detail(
                reply_data.get("company_id", "N/A"),
                "error",
                f"JSON parse error: {str(e)[:100]}",
            )
        except Exception as e:
            logger.error(f"Error classifying reply: {e}", exc_info=True)
            result.errors += 1
            result.add_detail(
                reply_data.get("company_id", "N/A"),
                "error",
                str(e)[:200],
            )

        return result

def _get_reply_strategy_hint(reply_body: str) -> str:
    """Return strategy instructions from sequences.yaml based on reply content.

    Uses simple keyword heuristics for fast classification before the LLM call.
    The LLM can override the strategy in edge cases.
    """
    try:
        seq_config = get_sequences_config()
        strategies = seq_config.get("reply_strategies", {})
    except Exception:
        return "Use your best judgment based on the reply classification."

    body_lower = reply_body.lower()

    # Detect "tell me more" pattern
    tell_more_signals = [
        "tell me more", "more information", "more info",
        "how does", "what does", "can you explain", "walk me through",
        "sounds interesting", "interesting", "intrigued",
    ]
    if any(s in body_lower for s in tell_more_signals):
        s = strategies.get("tell_me_more", {})
        variants = s.get("variants", {})
        # Default to concise variant
        concise = variants.get("concise", {})
        return f"Strategy: tell_me_more (concise variant). {concise.get('instructions', '')}"

    # Detect objection patterns
    if any(w in body_lower for w in ["already using", "already have", "current vendor", "working with"]):
        obj = strategies.get("objection", {}).get("strategies", {}).get("incumbent_vendor", {})
        return f"Strategy: objection_incumbent. {obj.get('instructions', '')}"

    if any(w in body_lower for w in ["budget", "cost", "expensive", "price", "afford"]):
        obj = strategies.get("objection", {}).get("strategies", {}).get("budget", {})
        return f"Strategy: objection_budget. {obj.get('instructions', '')}"

    if any(w in body_lower for w in ["not right now", "bad timing", "next year", "next quarter", "q4", "q1"]):
        obj = strategies.get("objection", {}).get("strategies", {}).get("timing", {})
        return f"Strategy: objection_timing. {obj.get('instructions', '')}"

    if any(w in body_lower for w in ["not the right person", "not my area", "reach out to", "contact"]):
        obj = strategies.get("objection", {}).get("strategies", {}).get("not_the_right_person", {})
        return f"Strategy: objection_referral. {obj.get('instructions', '')}"

    # Detect positive reply
    positive_signals = [
        "yes", "interested", "let's", "happy to", "sure", "sounds good",
        "would love", "open to", "schedule", "calendar", "book",
    ]
    if any(s in body_lower for s in positive_signals):
        s = strategies.get("positive_reply", {})
        return f"Strategy: positive_reply. {s.get('instructions', '')}"

    # Default: use judgment
    return "Use your best judgment based on the reply content and classification."


def _cancel_active_sequences(self, company_id: str) -> int:
    """Cancel all active engagement sequences for a company.

    Returns:
        Number of sequences cancelled.
    """
    cancelled = 0
    try:
        active_sequences = self.db.get_active_sequences()
        for seq in active_sequences:
            if seq.get("company_id") == company_id:
                self.db.update_engagement_sequence(seq["id"], {
                    "status": "cancelled",
                })
                cancelled += 1

        if cancelled:
            logger.info(f"Cancelled {cancelled} active sequences for company {company_id}")

    except Exception as e:
        logger.warning(f"Error cancelling sequences for {company_id}: {e}")

    return cancelled
