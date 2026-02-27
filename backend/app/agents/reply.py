"""Reply Agent -- Classifies incoming replies and drafts responses.

Uses Claude Haiku (1 call per reply) to classify prospect replies,
determine sentiment, and draft appropriate follow-up responses.
"""

from __future__ import annotations

import json
import logging

import anthropic
from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings

console = Console()
logger = logging.getLogger(__name__)

REPLY_CLASSIFICATION_SYSTEM = """You are a B2B sales reply classifier for Digitillis, an AI-native manufacturing intelligence platform. Your job is to classify incoming prospect replies and draft appropriate responses.

Digitillis capabilities:
- 32 specialized AI agents across 7 manufacturing domains
- Predictive maintenance with 18+ day advance warning, 87% confidence
- Anomaly detection across 100+ sensors
- Quality control with defect prediction
- Energy optimization and ESG reporting
- Production optimization with OEE analytics
- Conversational AI copilot (ARIA)
- Pilot program: 6-8 weeks, no long-term commitment

Founder sending these emails: Avi, Co-Founder & MD at Digitillis
Email: avi@digitillis.com

Classify the reply into exactly one of these categories:
- positive: Prospect is interested, wants a meeting, demo, or more info
- question: Prospect has specific questions but hasn't committed
- negative: Prospect is not interested or declines
- out_of_office: Automatic out-of-office reply
- unsubscribe: Prospect requests removal from communications
- bounce: Technical delivery failure / bounce notification

Draft an appropriate response based on the classification:
- positive: Warm, enthusiastic response proposing 2-3 specific meeting times in the coming week. Keep it concise and action-oriented.
- question: Helpful, informative answer addressing their specific questions. Reference relevant Digitillis capabilities without being pushy.
- negative: Polite, gracious acknowledgment. Thank them for their time. Offer to stay in touch for future needs. No pressure.
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

OUTPUT FORMAT (JSON):
{{
    "classification": "positive|question|negative|out_of_office|unsubscribe|bounce",
    "sentiment": "very_positive|positive|neutral|negative|very_negative",
    "response_draft_subject": "Re: subject line for the response",
    "response_draft_body": "The drafted response body. Sign off as Avi, Co-Founder, Digitillis.",
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
            console.print("[red]No reply_data provided. Expected dict with company_id, contact_id, subject, body, outreach_draft_id.[/red]")
            result.success = False
            result.errors = 1
            result.add_detail("N/A", "error", "No reply_data provided")
            return result

        # Validate required fields
        required_fields = ["company_id", "contact_id", "subject", "body", "outreach_draft_id"]
        missing = [f for f in required_fields if not reply_data.get(f)]
        if missing:
            console.print(f"[red]Missing required fields in reply_data: {', '.join(missing)}[/red]")
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
                console.print(f"  [yellow]{company_name}: Contact {contact_id} not found. Proceeding with limited context.[/yellow]")
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

            # Get research for company context
            research = self.db.get_research(company_id)
            research_summary = company.get("research_summary", "No research available")
            if research and research.get("company_description"):
                research_summary = research["company_description"]

            pqs_total = company.get("pqs_total", 0)

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
            )

            # Call Claude Haiku for classification
            console.print(f"  [dim]{company_name} -- Classifying reply from {contact.get('full_name', 'Unknown')}...[/dim]")

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                system=REPLY_CLASSIFICATION_SYSTEM,
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

            console.print(
                f"  [cyan]{company_name}: Classification = {classification} | "
                f"Sentiment = {sentiment} | Urgency = {urgency}[/cyan]"
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

                console.print(f"  [green]{company_name}: POSITIVE reply -- response draft created, status -> engaged[/green]")

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

                console.print(f"  [blue]{company_name}: QUESTION reply -- answer draft created[/blue]")

            elif classification == "negative":
                # Update company status to not_interested
                self.db.update_company(company_id, {"status": "not_interested"})

                # Cancel any active engagement sequences for this company
                self._cancel_active_sequences(company_id)

                console.print(f"  [yellow]{company_name}: NEGATIVE reply -- status -> not_interested, sequences cancelled[/yellow]")

            elif classification == "out_of_office":
                # Log but don't change status -- follow up later
                console.print(f"  [dim]{company_name}: OUT OF OFFICE -- logged, no status change[/dim]")

            elif classification == "unsubscribe":
                # Update contact status to unsubscribed
                self.db.update_contact(contact_id, {"status": "unsubscribed"})

                # Cancel active sequences
                self._cancel_active_sequences(company_id)

                console.print(f"  [yellow]{company_name}: UNSUBSCRIBE -- contact unsubscribed, sequences cancelled[/yellow]")

            elif classification == "bounce":
                # Update contact status to bounced, company status to bounced
                self.db.update_contact(contact_id, {"status": "bounced"})
                self.db.update_company(company_id, {"status": "bounced"})

                console.print(f"  [red]{company_name}: BOUNCE -- contact and company marked bounced[/red]")

            else:
                console.print(f"  [yellow]{company_name}: Unknown classification '{classification}' -- logged for review[/yellow]")

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
                self.logger.info(f"Cancelled {cancelled} active sequences for company {company_id}")

        except Exception as e:
            self.logger.warning(f"Error cancelling sequences for {company_id}: {e}")

        return cancelled
