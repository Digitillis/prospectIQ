"""Buying signal detector — auto-escalate hot prospects.

Monitors engagement patterns and auto-escalates prospects showing
buying signals. Runs as part of the daily actions workflow.

A "buying signal" is a pattern that historically correlates with
conversion. In B2B manufacturing sales:

- 3+ email opens in 7 days = "researching" (2.5x more likely to reply)
- Link click = "evaluating" (5x more likely to book a meeting)
- Reply to any email = "interested" (handled by reply agent)
- Opens from 2+ contacts at same company = "organizational interest"

When detected, the system:
1. Bumps PQS engagement score
2. Sets priority_flag = True
3. Logs an interaction for audit trail
4. Notifies Slack for immediate founder attention
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.database import Database

console = Console()
logger = logging.getLogger(__name__)

# Signal definitions
_SIGNALS = [
    {
        "name": "multi_open_7d",
        "description": "3+ email opens in 7 days from same contact",
        "interaction_type": "email_opened",
        "window_days": 7,
        "min_count": 3,
        "pqs_bump": 5,
        "priority": True,
        "severity": "hot",
    },
    {
        "name": "link_click",
        "description": "Clicked a link in outreach email",
        "interaction_type": "email_clicked",
        "window_days": 30,
        "min_count": 1,
        "pqs_bump": 8,
        "priority": True,
        "severity": "hot",
    },
    {
        "name": "multi_contact_opens",
        "description": "Opens from 2+ different contacts at same company",
        "interaction_type": "email_opened",
        "window_days": 14,
        "min_count": 2,
        "pqs_bump": 10,
        "priority": True,
        "severity": "hot",
        "count_by": "unique_contacts",
    },
    {
        "name": "open_after_silence",
        "description": "Opened an email after 30+ days of no engagement",
        "interaction_type": "email_opened",
        "window_days": 7,
        "silence_days": 30,
        "min_count": 1,
        "pqs_bump": 4,
        "priority": False,
        "severity": "warm",
    },
]


class BuyingSignalDetector(BaseAgent):
    """Detect buying signals from engagement patterns and auto-escalate."""

    agent_name = "buying_signals"

    def run(self, **kwargs) -> AgentResult:
        """Scan all contacted/engaged companies for buying signals.

        Returns:
            AgentResult with detected signals.
        """
        result = AgentResult()

        # Get companies in active outreach
        contacted = self.db.get_companies(status="contacted", limit=500)
        engaged = self.db.get_companies(status="engaged", limit=500)
        companies = contacted + engaged

        if not companies:
            console.print("[yellow]No companies in active outreach to scan.[/yellow]")
            return result

        console.print(f"[cyan]Scanning {len(companies)} companies for buying signals...[/cyan]")

        hot_alerts = []

        for company in companies:
            company_id = company["id"]
            company_name = company.get("name", "Unknown")

            detected = self._detect_signals(company_id)

            if detected:
                # Apply the strongest signal
                strongest = max(detected, key=lambda s: s["pqs_bump"])

                # Bump engagement score
                current_eng = company.get("pqs_engagement", 0)
                new_eng = min(current_eng + strongest["pqs_bump"], 25)
                new_total = (
                    company.get("pqs_firmographic", 0)
                    + company.get("pqs_technographic", 0)
                    + company.get("pqs_timing", 0)
                    + new_eng
                )

                update = {
                    "pqs_engagement": new_eng,
                    "pqs_total": new_total,
                }
                if strongest["priority"]:
                    update["priority_flag"] = True

                self.db.update_company(company_id, update)

                # Log detection
                signal_names = [s["name"] for s in detected]
                self.db.insert_interaction({
                    "company_id": company_id,
                    "type": "note",
                    "channel": "other",
                    "subject": f"Buying signal detected: {', '.join(signal_names)}",
                    "body": "\n".join(s["description"] for s in detected),
                    "source": "system",
                    "metadata": {
                        "signal_names": signal_names,
                        "pqs_bump": strongest["pqs_bump"],
                        "severity": strongest["severity"],
                    },
                })

                severity = strongest["severity"]
                if severity == "hot":
                    hot_alerts.append((company_name, signal_names))

                console.print(
                    f"  [{'bold red' if severity == 'hot' else 'yellow'}]"
                    f"{company_name}: {', '.join(signal_names)} "
                    f"(PQS engagement {current_eng}→{new_eng})"
                    f"[/{'bold red' if severity == 'hot' else 'yellow'}]"
                )

                result.processed += 1
                result.add_detail(
                    company_name,
                    f"signal_{severity}",
                    f"Signals: {', '.join(signal_names)}, PQS bump: +{strongest['pqs_bump']}",
                )

        # Notify Slack about hot signals
        if hot_alerts:
            try:
                from backend.app.utils.notifications import notify_slack
                alert_text = "\n".join(
                    f"• *{name}*: {', '.join(signals)}"
                    for name, signals in hot_alerts
                )
                notify_slack(
                    f"*Buying signals detected!* {len(hot_alerts)} hot prospect(s):\n{alert_text}\n\n"
                    f"These prospects are actively engaging — prioritize follow-up.",
                    emoji=":fire:",
                )
            except Exception:
                pass

        return result

    def _detect_signals(self, company_id: str) -> list[dict]:
        """Detect buying signals for a company.

        Returns:
            List of signal dicts that were triggered.
        """
        detected = []
        now = datetime.now(timezone.utc)

        for signal in _SIGNALS:
            window_start = (
                now - timedelta(days=signal["window_days"])
            ).isoformat()

            interactions = (
                self.db.client.table("interactions")
                .select("id, contact_id, created_at")
                .eq("company_id", company_id)
                .eq("type", signal["interaction_type"])
                .gte("created_at", window_start)
                .execute()
                .data
            )

            if not interactions:
                continue

            # Check count threshold
            count_by = signal.get("count_by")
            if count_by == "unique_contacts":
                unique = len(set(i.get("contact_id") for i in interactions if i.get("contact_id")))
                if unique >= signal["min_count"]:
                    detected.append(signal)
            else:
                if len(interactions) >= signal["min_count"]:
                    # For "open_after_silence", check that there was a silence period
                    if signal.get("silence_days"):
                        silence_start = (
                            now - timedelta(days=signal["silence_days"])
                        ).isoformat()
                        silence_end = window_start  # before the current window

                        silence_period = (
                            self.db.client.table("interactions")
                            .select("id", count="exact")
                            .eq("company_id", company_id)
                            .in_("type", ["email_opened", "email_clicked", "email_replied"])
                            .gte("created_at", silence_start)
                            .lte("created_at", silence_end)
                            .execute()
                        )
                        if (silence_period.count or 0) == 0:
                            detected.append(signal)
                    else:
                        detected.append(signal)

        return detected
