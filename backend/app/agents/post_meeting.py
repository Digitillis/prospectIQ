"""Post-Meeting Intelligence Agent — Extract structured intelligence from call transcripts.

Webhook-driven: receives transcripts from Fathom or Fireflies, then uses Claude
to extract BANT/MEDDIC coverage, pain points confirmed, tech stack, budget signals,
deal stage, and follow-up draft.

Auto-updates company status and queues follow-up draft for HITL approval.
Extends ProspectIQ from discovery-to-outreach → discovery-to-close.

Webhook endpoint: POST /api/webhooks/meeting-transcript
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic
from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings
from backend.app.core.model_router import get_model

console = Console()
logger = logging.getLogger(__name__)

MEETING_SYSTEM = """You are a B2B sales intelligence analyst specializing in manufacturing deals.
Your job is to extract structured intelligence from sales call transcripts and generate
follow-up email drafts.

Extract BANT and MEDDIC qualification dimensions:
  BANT: Budget, Authority, Need, Timeline
  MEDDIC: Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion

Be precise and conservative. Only mark something as "confirmed" if you heard it explicitly.
Mark as "mentioned" if it came up but wasn't confirmed. "Not covered" if not discussed.

Output ONLY valid JSON. No markdown, no explanation."""

MEETING_USER = """Extract structured intelligence from this sales call transcript.

COMPANY: {company_name}
CONTACT: {contact_name} ({contact_title})
MEETING DATE: {meeting_date}
TRANSCRIPT:
{transcript}

OUTPUT FORMAT:
{{
    "meeting_summary": "2-3 sentence summary of what was discussed and the overall tone",
    "next_step": "specific agreed next step (or 'None agreed')",
    "deal_stage": "outreach_pending|contacted|engaged|meeting_scheduled|pilot_discussion|pilot_signed",
    "bant": {{
        "budget": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "what was said about budget (or empty string)"
        }},
        "authority": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "decision maker identified (or empty string)"
        }},
        "need": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "specific pain points confirmed (or empty string)"
        }},
        "timeline": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "decision or implementation timeline (or empty string)"
        }}
    }},
    "meddic": {{
        "metrics": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "success metrics or KPIs they mentioned"
        }},
        "economic_buyer": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "who controls the budget"
        }},
        "decision_criteria": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "how they will evaluate vendors"
        }},
        "decision_process": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "steps to get to a signed contract"
        }},
        "identify_pain": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "specific operational pain points confirmed"
        }},
        "champion": {{
            "status": "confirmed|mentioned|not_covered",
            "detail": "internal champion who will drive the purchase"
        }}
    }},
    "tech_stack_mentioned": ["list", "of", "technology", "systems", "mentioned"],
    "pain_points_confirmed": ["list", "of", "specific", "pain", "points", "confirmed"],
    "objections_raised": ["list", "of", "objections", "raised"],
    "competitors_mentioned": ["list", "of", "competitors", "mentioned"],
    "budget_signal": "strong|moderate|weak|none",
    "deal_confidence": "high|medium|low",
    "qualification_score": 0-10,
    "follow_up_email_subject": "Short, specific follow-up email subject line",
    "follow_up_email_body": "Full follow-up email body. Reference specific things discussed. Sign as {sender_signature}. 150 words max.",
    "internal_notes": "Brief notes for CRM — key takeaways, risks, and recommended next actions"
}}"""


class PostMeetingAgent(BaseAgent):
    """Extract structured intelligence from meeting transcripts."""

    agent_name = "post_meeting"

    def run(
        self,
        company_id: str | None = None,
        contact_id: str | None = None,
        transcript: str | None = None,
        meeting_date: str | None = None,
        meeting_source: str = "manual",
    ) -> AgentResult:
        """Process a meeting transcript for one company/contact.

        Args:
            company_id: Company the meeting was with.
            contact_id: Primary contact in the meeting.
            transcript: Full meeting transcript text.
            meeting_date: ISO date string (default: today).
            meeting_source: "fathom" | "fireflies" | "manual"

        Returns:
            AgentResult with extraction and follow-up stats.
        """
        result = AgentResult()

        if not company_id or not transcript:
            result.success = False
            result.errors = 1
            result.add_detail("N/A", "error", "company_id and transcript are required")
            return result

        settings = get_settings()
        meeting_dt = meeting_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            company = self.db.get_company(company_id)
            if not company:
                result.success = False
                result.errors = 1
                result.add_detail("N/A", "error", f"Company {company_id} not found")
                return result

            company_name = company.get("name", "Unknown")

            # Get contact details
            contact_name = "Unknown"
            contact_title = "Unknown"
            if contact_id:
                contacts = self.db.get_contacts_for_company(company_id)
                contact = next((c for c in contacts if c.get("id") == contact_id), None)
                if contact:
                    contact_name = contact.get("full_name", contact.get("first_name", "Unknown"))
                    contact_title = contact.get("title", "Unknown")

            console.print(f"  [cyan]{company_name}: Processing meeting transcript ({len(transcript)} chars)...[/cyan]")

            # Resolve sender signature from outreach_guidelines
            sender_signature = "the sender"
            try:
                from backend.app.core.config import get_outreach_guidelines
                _g = get_outreach_guidelines()
                _s = _g.get("sender", {})
                _parts = [_s.get("name", ""), _s.get("title", ""), _s.get("company", "")]
                sender_signature = ", ".join(p for p in _parts if p)
            except Exception:
                pass

            # Build prompt — truncate transcript to ~8000 chars to stay within context
            transcript_excerpt = transcript[:8000]
            if len(transcript) > 8000:
                transcript_excerpt += "\n[transcript truncated]"

            prompt = MEETING_USER.format(
                company_name=company_name,
                contact_name=contact_name,
                contact_title=contact_title,
                meeting_date=meeting_dt,
                transcript=transcript_excerpt,
                sender_signature=sender_signature,
            )

            _model = get_model("research")
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model=_model,
                max_tokens=2000,
                system=MEETING_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            self.track_cost(
                provider="anthropic",
                model=_model,
                endpoint="/messages",
                company_id=company_id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            parsed = json.loads(content)

            # --- Update company record ---
            new_status = parsed.get("deal_stage", "")
            update_data: dict = {}

            if new_status and new_status in (
                "contacted", "engaged", "meeting_scheduled",
                "pilot_discussion", "pilot_signed",
            ):
                update_data["status"] = new_status

            # Merge confirmed tech stack into company record
            tech_mentioned = parsed.get("tech_stack_mentioned", [])
            if tech_mentioned:
                existing_stack = company.get("technology_stack") or []
                merged = list({*existing_stack, *tech_mentioned})
                update_data["technology_stack"] = merged

            # Merge confirmed pain points
            pains = parsed.get("pain_points_confirmed", [])
            if pains:
                existing_pain = company.get("pain_signals") or []
                merged_pain = list({*existing_pain, *pains})
                update_data["pain_signals"] = merged_pain

            if update_data:
                self.db.update_company(company_id, update_data)

            # --- Log meeting interaction ---
            bant = parsed.get("bant", {})
            meddic = parsed.get("meddic", {})
            qual_score = parsed.get("qualification_score", 0)

            self.db.insert_interaction({
                "company_id": company_id,
                "contact_id": contact_id,
                "type": "meeting",
                "channel": "other",
                "subject": f"Meeting — {meeting_dt} — {company_name}",
                "body": parsed.get("meeting_summary", ""),
                "source": meeting_source,
                "metadata": {
                    "bant": bant,
                    "meddic": meddic,
                    "deal_confidence": parsed.get("deal_confidence", ""),
                    "qualification_score": qual_score,
                    "budget_signal": parsed.get("budget_signal", ""),
                    "competitors_mentioned": parsed.get("competitors_mentioned", []),
                    "objections_raised": parsed.get("objections_raised", []),
                    "next_step": parsed.get("next_step", ""),
                    "internal_notes": parsed.get("internal_notes", ""),
                },
            })

            # --- Create follow-up draft ---
            follow_up_subject = parsed.get("follow_up_email_subject", "")
            follow_up_body = parsed.get("follow_up_email_body", "")

            if follow_up_subject and follow_up_body and contact_id:
                draft_data = {
                    "company_id": company_id,
                    "contact_id": contact_id,
                    "channel": "email",
                    "sequence_name": "post_meeting_followup",
                    "sequence_step": 1,
                    "subject": follow_up_subject,
                    "body": follow_up_body,
                    "personalization_notes": (
                        f"Post-meeting follow-up. Deal confidence: {parsed.get('deal_confidence', 'N/A')}. "
                        f"BANT: Budget={bant.get('budget', {}).get('status', 'N/A')}, "
                        f"Authority={bant.get('authority', {}).get('status', 'N/A')}, "
                        f"Need={bant.get('need', {}).get('status', 'N/A')}, "
                        f"Timeline={bant.get('timeline', {}).get('status', 'N/A')}"
                    ),
                    "approval_status": "pending",
                }
                self.db.insert_outreach_draft(draft_data)

            # --- Slack notification for high-confidence deals ---
            if parsed.get("deal_confidence") == "high" or qual_score >= 7:
                try:
                    from backend.app.utils.notifications import notify_slack
                    notify_slack(
                        f"*Hot prospect: {company_name}* — meeting on {meeting_dt}. "
                        f"Deal confidence: {parsed.get('deal_confidence', 'N/A')}. "
                        f"Qualification score: {qual_score}/10. "
                        f"Next step: {parsed.get('next_step', 'None agreed')}",
                        emoji=":fire:",
                    )
                except Exception:
                    pass

            result.processed += 1
            result.add_detail(
                company_name,
                parsed.get("deal_stage", "processed"),
                f"Confidence: {parsed.get('deal_confidence', 'N/A')}, "
                f"Qual: {qual_score}/10, Budget: {bant.get('budget', {}).get('status', 'N/A')}",
            )
            console.print(
                f"  [green]{company_name}: Meeting processed. "
                f"Stage → {parsed.get('deal_stage', 'N/A')}, "
                f"confidence: {parsed.get('deal_confidence', 'N/A')}[/green]"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Post-meeting parse error for {company_id}: {e}")
            result.errors += 1
        except Exception as e:
            logger.error(f"Post-meeting agent error for {company_id}: {e}", exc_info=True)
            result.errors += 1

        return result
