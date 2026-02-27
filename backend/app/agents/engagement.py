"""Engagement Agent — Sequence orchestration + Instantly.ai delivery.

Handles:
- Sending approved outreach via Instantly.ai campaigns
- Managing multi-stage engagement sequences
- Processing webhook events (opens, clicks, replies, bounces)
- Generating follow-up drafts when sequences are due
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_sequences_config
from backend.app.integrations.instantly import InstantlyClient

console = Console()
logger = logging.getLogger(__name__)


class EngagementAgent(BaseAgent):
    """Orchestrate email delivery and multi-stage engagement sequences."""

    agent_name = "engagement"

    def run(
        self,
        action: str = "send_approved",
        campaign_name: str | None = None,
    ) -> AgentResult:
        """Execute engagement actions.

        Args:
            action: One of:
                - "send_approved": Send all approved outreach drafts via Instantly
                - "process_due": Process sequences with due follow-ups
                - "check_status": Check and log campaign analytics
            campaign_name: Instantly campaign name (created if not exists).

        Returns:
            AgentResult with engagement stats.
        """
        if action == "send_approved":
            return self._send_approved_drafts(campaign_name)
        elif action == "process_due":
            return self._process_due_sequences()
        elif action == "check_status":
            return self._check_campaign_status()
        else:
            result = AgentResult()
            result.success = False
            result.add_detail("N/A", "error", f"Unknown action: {action}")
            return result

    def _send_approved_drafts(self, campaign_name: str | None = None) -> AgentResult:
        """Send all approved but unsent outreach drafts via Instantly.ai."""
        result = AgentResult()

        # Get approved drafts that haven't been sent yet
        drafts = (
            self.db.client.table("outreach_drafts")
            .select("*, companies(name, tier), contacts(full_name, email, first_name, last_name, company_id)")
            .eq("approval_status", "approved")
            .is_("sent_at", "null")
            .order("created_at")
            .execute()
            .data
        )

        if not drafts:
            console.print("[yellow]No approved drafts to send.[/yellow]")
            return result

        console.print(f"[cyan]Sending {len(drafts)} approved drafts via Instantly.ai...[/cyan]")

        with InstantlyClient() as instantly:
            # Get or create campaign
            campaign_label = campaign_name or f"ProspectIQ_{datetime.now().strftime('%Y%m')}"

            campaigns = instantly.list_campaigns()
            campaign_id = None
            for c in campaigns:
                if c.get("name") == campaign_label:
                    campaign_id = c.get("id")
                    break

            if not campaign_id:
                console.print(f"  [dim]Creating campaign: {campaign_label}[/dim]")
                campaign = instantly.create_campaign(name=campaign_label)
                campaign_id = campaign.get("id")

            if not campaign_id:
                console.print("[red]Failed to get/create Instantly campaign.[/red]")
                result.success = False
                return result

            for draft in drafts:
                contact = draft.get("contacts", {})
                company = draft.get("companies", {})
                company_name = company.get("name", "Unknown")
                contact_email = contact.get("email")

                if not contact_email:
                    console.print(f"  [yellow]{company_name}: No email for contact. Skipping.[/yellow]")
                    result.skipped += 1
                    continue

                try:
                    # Add lead to Instantly campaign
                    lead = {
                        "email": contact_email,
                        "first_name": contact.get("first_name", ""),
                        "last_name": contact.get("last_name", ""),
                        "company_name": company_name,
                        "campaign_id": campaign_id,
                        "custom_variables": {
                            "subject": draft.get("subject", ""),
                            "body": draft.get("edited_body") or draft.get("body", ""),
                            "prospect_iq_draft_id": draft["id"],
                        },
                    }

                    instantly.add_leads_to_campaign(
                        campaign_id=campaign_id,
                        leads=[lead],
                    )

                    # Mark draft as sent
                    now = datetime.now(timezone.utc).isoformat()
                    self.db.update_outreach_draft(draft["id"], {
                        "sent_at": now,
                        "instantly_lead_id": contact_email,
                    })

                    # Log interaction
                    self.db.insert_interaction({
                        "company_id": draft["company_id"],
                        "contact_id": draft["contact_id"],
                        "type": "email_sent",
                        "channel": "email",
                        "subject": draft.get("subject", ""),
                        "body": draft.get("edited_body") or draft.get("body", ""),
                        "source": "instantly",
                        "metadata": {
                            "campaign_id": campaign_id,
                            "sequence_name": draft.get("sequence_name"),
                            "sequence_step": draft.get("sequence_step"),
                        },
                    })

                    # Update company status
                    self.db.update_company(draft["company_id"], {"status": "contacted"})

                    # Create engagement sequence record
                    seq_config = get_sequences_config()
                    sequence = seq_config["sequences"].get(draft.get("sequence_name", "initial_outreach"), {})
                    total_steps = sequence.get("total_steps", 5)
                    current_step = draft.get("sequence_step", 1)

                    # Calculate next action
                    next_step = current_step + 1
                    next_action_at = None
                    next_action_type = None

                    if next_step <= total_steps:
                        for step in sequence.get("steps", []):
                            if step["step"] == next_step:
                                delay = step.get("delay_days", 3)
                                next_action_at = (
                                    datetime.now(timezone.utc) + timedelta(days=delay)
                                ).isoformat()
                                next_action_type = f"send_{step['channel']}"
                                break

                    self.db.insert_engagement_sequence({
                        "company_id": draft["company_id"],
                        "contact_id": draft["contact_id"],
                        "sequence_name": draft.get("sequence_name", "initial_outreach"),
                        "current_step": current_step,
                        "total_steps": total_steps,
                        "status": "active" if next_step <= total_steps else "completed",
                        "next_action_at": next_action_at,
                        "next_action_type": next_action_type,
                        "started_at": now,
                    })

                    console.print(
                        f"  [green]{company_name} → {contact_email}: Sent via Instantly[/green]"
                    )
                    result.processed += 1
                    result.add_detail(company_name, "sent", f"To: {contact_email}")

                except Exception as e:
                    logger.error(f"Error sending to {company_name}: {e}", exc_info=True)
                    result.errors += 1
                    result.add_detail(company_name, "error", str(e)[:200])

        return result

    def _process_due_sequences(self) -> AgentResult:
        """Process engagement sequences with due follow-up actions."""
        result = AgentResult()

        now = datetime.now(timezone.utc).isoformat()
        due_sequences = self.db.get_active_sequences(due_before=now)

        if not due_sequences:
            console.print("[yellow]No sequences due for action.[/yellow]")
            return result

        console.print(f"[cyan]Processing {len(due_sequences)} due sequence actions...[/cyan]")

        for seq in due_sequences:
            company = seq.get("companies", {})
            contact = seq.get("contacts", {})
            company_name = company.get("name", "Unknown")

            try:
                next_step = seq["current_step"] + 1
                seq_config = get_sequences_config()
                sequence = seq_config["sequences"].get(seq["sequence_name"], {})

                # Find the step config
                step_config = None
                for step in sequence.get("steps", []):
                    if step["step"] == next_step:
                        step_config = step
                        break

                if not step_config:
                    # Sequence complete
                    self.db.update_engagement_sequence(seq["id"], {
                        "status": "completed",
                        "completed_at": now,
                    })
                    result.processed += 1
                    result.add_detail(company_name, "completed", "Sequence finished")
                    continue

                channel = step_config["channel"]

                if channel == "email":
                    # Generate follow-up draft via Outreach Agent
                    from backend.app.agents.outreach import OutreachAgent

                    outreach = OutreachAgent(batch_id=self.batch_id)
                    outreach_result = outreach.run(
                        company_ids=[seq["company_id"]],
                        sequence_name=seq["sequence_name"],
                        sequence_step=next_step,
                    )

                    if outreach_result.processed > 0:
                        console.print(
                            f"  [green]{company_name}: Follow-up draft created "
                            f"(step {next_step}, email)[/green]"
                        )
                    else:
                        console.print(
                            f"  [yellow]{company_name}: Could not generate follow-up[/yellow]"
                        )

                elif channel == "linkedin":
                    # LinkedIn actions are manual — just surface them
                    console.print(
                        f"  [bold cyan]{company_name}: LinkedIn touch needed "
                        f"(step {next_step}) → {contact.get('full_name', 'Unknown')}[/bold cyan]"
                    )

                    # Log as a pending manual action
                    self.db.insert_interaction({
                        "company_id": seq["company_id"],
                        "contact_id": seq["contact_id"],
                        "type": "linkedin_connection" if next_step <= 2 else "linkedin_message",
                        "channel": "linkedin",
                        "subject": f"LinkedIn touch — Step {next_step}",
                        "body": step_config.get("instructions", {}).get("approach", ""),
                        "source": "system",
                        "metadata": {
                            "action_required": "manual",
                            "sequence_name": seq["sequence_name"],
                            "sequence_step": next_step,
                        },
                    })

                # Update sequence
                further_step = next_step + 1
                next_next_action_at = None
                next_next_type = None

                if further_step <= seq["total_steps"]:
                    for step in sequence.get("steps", []):
                        if step["step"] == further_step:
                            delay = step.get("delay_days", 3)
                            next_next_action_at = (
                                datetime.now(timezone.utc) + timedelta(days=delay)
                            ).isoformat()
                            next_next_type = f"send_{step['channel']}"
                            break

                self.db.update_engagement_sequence(seq["id"], {
                    "current_step": next_step,
                    "next_action_at": next_next_action_at,
                    "next_action_type": next_next_type,
                    "status": "active" if further_step <= seq["total_steps"] else "completed",
                })

                result.processed += 1
                result.add_detail(company_name, f"step_{next_step}", f"Channel: {channel}")

            except Exception as e:
                logger.error(f"Error processing sequence for {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        return result

    def _check_campaign_status(self) -> AgentResult:
        """Check Instantly.ai campaign analytics and update engagement scores."""
        result = AgentResult()

        with InstantlyClient() as instantly:
            campaigns = instantly.list_campaigns()

            if not campaigns:
                console.print("[yellow]No Instantly campaigns found.[/yellow]")
                return result

            console.print(f"[cyan]Checking {len(campaigns)} campaigns...[/cyan]")

            for campaign in campaigns:
                campaign_id = campaign.get("id")
                campaign_name = campaign.get("name", "Unknown")

                try:
                    analytics = instantly.get_campaign_analytics(campaign_id)

                    sent = analytics.get("sent", 0)
                    opened = analytics.get("opened", 0)
                    replied = analytics.get("replied", 0)
                    bounced = analytics.get("bounced", 0)

                    open_rate = (opened / sent * 100) if sent > 0 else 0
                    reply_rate = (replied / sent * 100) if sent > 0 else 0

                    console.print(
                        f"  {campaign_name}: "
                        f"Sent={sent} Opened={opened} ({open_rate:.1f}%) "
                        f"Replied={replied} ({reply_rate:.1f}%) "
                        f"Bounced={bounced}"
                    )

                    result.processed += 1
                    result.add_detail(
                        campaign_name,
                        "analytics",
                        f"Sent={sent}, Open={open_rate:.1f}%, Reply={reply_rate:.1f}%",
                    )

                except Exception as e:
                    logger.error(f"Error checking campaign {campaign_name}: {e}")
                    result.errors += 1

        return result

    @staticmethod
    def process_webhook_event(event_type: str, event_data: dict) -> dict:
        """Process an Instantly.ai webhook event.

        Called by the webhook endpoint. Creates interactions and updates sequences.

        Args:
            event_type: One of email_sent, email_opened, email_clicked, reply_received, email_bounced
            event_data: Event payload from Instantly

        Returns:
            Dict with processing result.
        """
        from backend.app.core.database import Database

        db = Database()
        email = event_data.get("email") or event_data.get("lead_email", "")

        if not email:
            return {"status": "skipped", "reason": "No email in event"}

        # Find the contact by email
        contacts = (
            db.client.table("contacts")
            .select("id, company_id")
            .eq("email", email)
            .execute()
            .data
        )

        if not contacts:
            logger.warning(f"Webhook: No contact found for email {email}")
            return {"status": "skipped", "reason": f"No contact for {email}"}

        contact = contacts[0]
        company_id = contact["company_id"]
        contact_id = contact["id"]

        # Map event type to interaction type
        interaction_map = {
            "email_sent": "email_sent",
            "email_opened": "email_opened",
            "email_clicked": "email_clicked",
            "reply_received": "email_replied",
            "email_bounced": "email_bounced",
        }

        interaction_type = interaction_map.get(event_type)
        if not interaction_type:
            return {"status": "skipped", "reason": f"Unknown event type: {event_type}"}

        # Log interaction
        db.insert_interaction({
            "company_id": company_id,
            "contact_id": contact_id,
            "type": interaction_type,
            "channel": "email",
            "subject": event_data.get("subject", ""),
            "body": event_data.get("body", ""),
            "source": "instantly_webhook",
            "external_id": event_data.get("event_id", ""),
            "metadata": event_data,
        })

        # Update engagement score
        engagement_bump = {
            "email_opened": 2,
            "email_clicked": 5,
            "reply_received": 10,
        }.get(event_type, 0)

        if engagement_bump:
            company = db.get_company(company_id)
            if company:
                current_engagement = company.get("pqs_engagement", 0)
                new_engagement = min(current_engagement + engagement_bump, 25)
                new_total = (
                    company.get("pqs_firmographic", 0)
                    + company.get("pqs_technographic", 0)
                    + company.get("pqs_timing", 0)
                    + new_engagement
                )
                db.update_company(company_id, {
                    "pqs_engagement": new_engagement,
                    "pqs_total": new_total,
                })

        # Handle specific events
        if event_type == "email_opened":
            db.update_company(company_id, {"status": "contacted"})

        elif event_type == "email_bounced":
            db.update_company(company_id, {"status": "bounced"})
            db.update_contact(contact_id, {"status": "bounced"})
            # Cancel active sequences
            active_seqs = (
                db.client.table("engagement_sequences")
                .select("id")
                .eq("contact_id", contact_id)
                .eq("status", "active")
                .execute()
                .data
            )
            for seq in active_seqs:
                db.update_engagement_sequence(seq["id"], {"status": "cancelled"})

        elif event_type == "reply_received":
            db.update_company(company_id, {"status": "engaged"})

        return {
            "status": "processed",
            "event_type": event_type,
            "company_id": company_id,
            "contact_id": contact_id,
        }
