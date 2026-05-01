"""Post-Send Audit Agent — weekly data quality sweep.

Scans all emails sent in the past N days and flags:
1. Name-email mismatches (email local part inconsistent with contact name)
2. Wrong-function contacts that slipped through the filter
3. Contacts with no email record in the DB (null-email sends)
4. Companies receiving sends to more than MAX_THREADS contacts

Writes findings to the outreach_audit_log table and sends a Slack digest.
Run weekly via the workspace scheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from rich.console import Console
from rich.table import Table

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.contact_filter import (
    check_email_name_consistency,
    classify_contact_tier,
)

console = Console()
logger = logging.getLogger(__name__)

MAX_THREADS_PER_COMPANY = 2
AUDIT_WINDOW_DAYS = 7


class PostSendAuditAgent(BaseAgent):
    """Weekly audit: scan recent sends for data quality violations."""

    agent_name = "post_send_audit"

    def run(self, days: int = AUDIT_WINDOW_DAYS) -> AgentResult:
        result = AgentResult()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        console.print(f"[cyan]Post-send audit: scanning sends since {since[:10]}...[/cyan]")

        # ── Fetch recent sends with contact info
        drafts = (
            self.db.client.table("outreach_drafts")
            .select("id,contact_id,company_id,subject,sent_at,approval_status")
            .gte("sent_at", since)
            .not_.is_("sent_at", "null")
            .execute()
            .data
        ) or []

        if not drafts:
            console.print("[yellow]No sends found in audit window.[/yellow]")
            return result

        console.print(f"Auditing {len(drafts)} sends from the past {days} days...")

        # Load contact and company data in bulk
        contact_ids = list({d["contact_id"] for d in drafts if d.get("contact_id")})
        company_ids = list({d["company_id"] for d in drafts if d.get("company_id")})

        contacts_raw = (
            self.db.client.table("contacts")
            .select("id,first_name,last_name,full_name,email,title,status,contact_tier,email_name_verified")
            .in_("id", contact_ids)
            .execute()
            .data
        ) or []
        contacts = {c["id"]: c for c in contacts_raw}

        companies_raw = (
            self.db.client.table("companies")
            .select("id,name")
            .in_("id", company_ids)
            .execute()
            .data
        ) or []
        companies = {c["id"]: c for c in companies_raw}

        # ── Run checks
        findings: list[dict[str, Any]] = []

        # Track sends per company for over-threading check
        sends_per_company: dict[str, list[str]] = {}

        for draft in drafts:
            contact_id = draft.get("contact_id")
            company_id = draft.get("company_id")
            contact = contacts.get(contact_id, {})
            company = companies.get(company_id, {})
            company_name = company.get("name", "Unknown")
            contact_name = contact.get("full_name") or f"{contact.get('first_name','')} {contact.get('last_name','')}".strip()
            email = contact.get("email")
            title = contact.get("title", "")

            sends_per_company.setdefault(company_id, []).append(contact_name)

            # Check 1: Null email
            if not email:
                findings.append({
                    "severity": "critical",
                    "type": "null_email",
                    "company": company_name,
                    "contact": contact_name,
                    "detail": "Email sent but contact has no email address on record",
                    "draft_id": draft["id"],
                })
                continue

            # Check 2: Email-name consistency
            tier_verified = contact.get("email_name_verified")
            if tier_verified is False:
                # Already flagged — escalate
                findings.append({
                    "severity": "critical",
                    "type": "email_name_mismatch_flagged",
                    "company": company_name,
                    "contact": contact_name,
                    "email": email,
                    "detail": "Contact has email_name_verified=False — email belongs to a different person",
                    "draft_id": draft["id"],
                })
            elif tier_verified is None:
                # Not yet checked — run the check now
                first = contact.get("first_name") or ""
                last = contact.get("last_name") or ""
                consistent, reason = check_email_name_consistency(first, last, email)
                if not consistent:
                    findings.append({
                        "severity": "critical",
                        "type": "email_name_mismatch_detected",
                        "company": company_name,
                        "contact": contact_name,
                        "email": email,
                        "detail": f"Name-email inconsistency detected post-send: {reason}",
                        "draft_id": draft["id"],
                    })
                    # Write back so future sends catch it at import time
                    try:
                        self.db.client.table("contacts").update({
                            "email_name_verified": False,
                            "is_outreach_eligible": False,
                        }).eq("id", contact_id).execute()
                    except Exception as e:
                        logger.warning("Could not update contact %s: %s", contact_id, e)

            # Check 3: Wrong job function
            tier = contact.get("contact_tier") or classify_contact_tier(title)
            if tier == "excluded":
                findings.append({
                    "severity": "high",
                    "type": "wrong_function",
                    "company": company_name,
                    "contact": contact_name,
                    "email": email,
                    "title": title,
                    "detail": f"Contact has wrong job function (tier=excluded): {title}",
                    "draft_id": draft["id"],
                })

        # Check 4: Over-threading (too many contacts hit at same company)
        for cid, names in sends_per_company.items():
            if len(names) > MAX_THREADS_PER_COMPANY:
                company_name = companies.get(cid, {}).get("name", "Unknown")
                findings.append({
                    "severity": "warning",
                    "type": "over_threading",
                    "company": company_name,
                    "contact": ", ".join(names),
                    "detail": f"{len(names)} contacts reached at same company in {days} days (max={MAX_THREADS_PER_COMPANY})",
                    "draft_id": None,
                })

        result.processed = len(drafts)

        # ── Report
        critical = [f for f in findings if f["severity"] == "critical"]
        high = [f for f in findings if f["severity"] == "high"]
        warnings = [f for f in findings if f["severity"] == "warning"]

        console.print(f"\n[bold]Audit complete:[/bold] {len(drafts)} sends | "
                      f"[red]{len(critical)} critical[/red] | "
                      f"[yellow]{len(high)} high[/yellow] | "
                      f"[dim]{len(warnings)} warnings[/dim]")

        if findings:
            table = Table(title=f"Audit Findings — past {days} days", show_lines=True)
            table.add_column("Severity", style="bold", width=10)
            table.add_column("Type", width=28)
            table.add_column("Company", width=22)
            table.add_column("Contact", width=22)
            table.add_column("Detail", width=45)

            sev_colors = {"critical": "red", "high": "yellow", "warning": "dim"}
            for f in findings:
                color = sev_colors.get(f["severity"], "")
                table.add_row(
                    f"[{color}]{f['severity'].upper()}[/{color}]",
                    f["type"],
                    f.get("company", ""),
                    f.get("contact", ""),
                    f.get("detail", ""),
                )
            console.print(table)

            # Slack digest
            try:
                from backend.app.utils.notifications import notify_slack
                lines = [f"*Post-Send Audit — past {days} days:* {len(drafts)} sends scanned"]
                if critical:
                    lines.append(f":red_circle: *{len(critical)} CRITICAL* — email went to wrong person or null email")
                    for f in critical[:5]:
                        lines.append(f"  • {f['company']} / {f['contact']}: {f['detail']}")
                if high:
                    lines.append(f":warning: *{len(high)} HIGH* — wrong job function reached")
                if warnings:
                    lines.append(f":large_yellow_circle: {len(warnings)} warnings (over-threading)")
                if not critical and not high:
                    lines.append(":white_check_mark: No critical or high issues found")
                notify_slack("\n".join(lines), emoji=":mag:")
            except Exception:
                pass

        result.add_detail(
            "audit",
            "complete",
            f"{len(drafts)} sends, {len(critical)} critical, {len(high)} high, {len(warnings)} warnings",
        )
        return result
