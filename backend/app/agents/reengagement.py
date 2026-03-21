"""Re-engagement Agent — Reactivate stale prospects after cooldown.

Finds contacts whose outreach sequences completed without a reply,
checks if the cooldown period has elapsed, and re-queues them for
a warm follow-up sequence with fresh messaging.

This closes the gap where prospects fall off the pipeline after
5 touches with no reply — instead of being lost, they re-enter
with a different angle after 90 days.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.suppression import SEQUENCE_COOLDOWN_DAYS

console = Console()
logger = logging.getLogger(__name__)


class ReengagementAgent(BaseAgent):
    """Find and re-queue stale prospects for warm follow-up."""

    agent_name = "reengagement"

    def run(
        self,
        limit: int = 50,
        cooldown_days: int = SEQUENCE_COOLDOWN_DAYS,
        **kwargs,
    ) -> AgentResult:
        """Find prospects eligible for re-engagement.

        A prospect is eligible if:
        1. Their engagement sequence status is "completed"
        2. The company status is "contacted" (never replied / engaged)
        3. The sequence completed_at is older than cooldown_days
        4. They haven't been re-engaged already (no active warm_follow_up sequence)

        Args:
            limit: Max prospects to re-engage in this batch.
            cooldown_days: Days after sequence completion before re-engaging.

        Returns:
            AgentResult with re-engagement stats.
        """
        result = AgentResult()

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        ).isoformat()

        console.print(
            f"[cyan]Scanning for re-engagement candidates "
            f"(cooldown: {cooldown_days} days, cutoff: {cutoff[:10]})...[/cyan]"
        )

        # Find completed sequences older than cooldown
        completed = (
            self.db.client.table("engagement_sequences")
            .select(
                "id, company_id, contact_id, sequence_name, completed_at, "
                "companies(name, status, pqs_total), "
                "contacts(full_name, email, status)"
            )
            .eq("status", "completed")
            .lte("completed_at", cutoff)
            .order("completed_at")
            .limit(limit * 2)  # fetch extra to account for filtering
            .execute()
            .data
        )

        if not completed:
            console.print("[yellow]No completed sequences past cooldown period.[/yellow]")
            return result

        console.print(f"  Found {len(completed)} completed sequences past cooldown.")

        reengaged = 0
        for seq in completed:
            if reengaged >= limit:
                break

            company = seq.get("companies") or {}
            contact = seq.get("contacts") or {}
            company_name = company.get("name", "Unknown")
            company_id = seq["company_id"]
            contact_id = seq["contact_id"]

            # Skip if company already progressed past "contacted"
            company_status = company.get("status", "")
            if company_status in (
                "engaged", "meeting_scheduled", "pilot_discussion",
                "pilot_signed", "active_pilot", "converted",
                "not_interested", "disqualified",
            ):
                continue

            # Skip if contact bounced or unsubscribed
            contact_status = contact.get("status", "")
            if contact_status in ("bounced", "not_interested", "unsubscribed"):
                continue

            # Skip if no email
            if not contact.get("email"):
                continue

            # Skip if already has an active warm_follow_up sequence
            existing_warm = (
                self.db.client.table("engagement_sequences")
                .select("id")
                .eq("contact_id", contact_id)
                .eq("sequence_name", "warm_follow_up")
                .in_("status", ["active", "completed"])
                .limit(1)
                .execute()
            )
            if existing_warm.data:
                continue

            # Check if there was a reply after the sequence (would mean they engaged)
            replies = (
                self.db.client.table("interactions")
                .select("id")
                .eq("contact_id", contact_id)
                .eq("type", "email_replied")
                .gte("created_at", seq.get("completed_at", ""))
                .limit(1)
                .execute()
            )
            if replies.data:
                continue

            # This prospect is eligible for re-engagement
            try:
                # Reset company status to qualified (re-enters outreach pipeline)
                self.db.update_company(company_id, {"status": "qualified"})

                # Log the re-engagement
                self.db.insert_interaction({
                    "company_id": company_id,
                    "contact_id": contact_id,
                    "type": "note",
                    "channel": "other",
                    "subject": "Re-engagement triggered",
                    "body": (
                        f"Prospect re-queued for warm_follow_up sequence after "
                        f"{cooldown_days}-day cooldown. Original sequence: "
                        f"{seq.get('sequence_name')}. PQS at re-engagement: "
                        f"{company.get('pqs_total', 0)}."
                    ),
                    "source": "system",
                    "metadata": {
                        "original_sequence_id": seq["id"],
                        "original_sequence_name": seq.get("sequence_name"),
                        "cooldown_days": cooldown_days,
                    },
                })

                console.print(
                    f"  [green]{company_name}: Re-queued for warm follow-up "
                    f"({contact.get('full_name', '?')})[/green]"
                )

                reengaged += 1
                result.processed += 1
                result.add_detail(
                    company_name,
                    "reengaged",
                    f"Contact: {contact.get('full_name')}, "
                    f"Original: {seq.get('sequence_name')}, "
                    f"Cooldown: {cooldown_days}d",
                )

            except Exception as e:
                logger.error(f"Error re-engaging {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        if reengaged > 0:
            console.print(
                f"\n  [bold green]{reengaged} prospects re-queued for warm follow-up.[/bold green]"
                f"\n  [dim]Next: run outreach with sequence_name='warm_follow_up' "
                f"to generate fresh drafts.[/dim]"
            )

        try:
            from backend.app.utils.notifications import notify_slack
            if reengaged > 0:
                notify_slack(
                    f"*Re-engagement:* {reengaged} stale prospects re-queued for warm follow-up "
                    f"after {cooldown_days}-day cooldown.",
                    emoji=":recycle:",
                )
        except Exception:
            pass

        return result
