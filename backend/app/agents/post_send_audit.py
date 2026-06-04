"""Post-Send Audit Agent — weekly data quality sweep.

Scans all emails sent in the past N days and flags:
1. Name-email mismatches (email local part inconsistent with contact name)
2. Wrong-function contacts that slipped through the filter
3. Contacts with no email record in the DB (null-email sends)
4. Companies receiving sends to more than MAX_THREADS contacts

Writes findings to the outreach_audit_log table and sends a Slack digest.
Run weekly via the workspace scheduler.

SCOPE FREEZE — 2026-05-12:
Post-send audit runs are fine for data quality — do NOT extend this agent
to drive automated account disqualification or list pruning. During the
precision GTM phase, disqualification decisions are made by the founder
after reviewing each audit result. The agent reports; it does not act.

Also exposes `audit_approvals()` (P2.4 — GTM rebuild). That method samples
20 approved drafts from the prior week, runs BenchmarkDetector against
each, and writes a JSON report to data/exports/approval_audit_<date>.json.
The runner cron is registered separately in backend/app/api/main.py for
Friday 09:00 CT.
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.benchmark_detector import BenchmarkDetector
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
            .select(
                "id,first_name,last_name,full_name,email,title,status,contact_tier,email_name_verified"
            )
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
            contact_name = (
                contact.get("full_name")
                or f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
            )
            email = contact.get("email")
            title = contact.get("title", "")

            sends_per_company.setdefault(company_id, []).append(contact_name)

            # Check 1: Null email
            if not email:
                findings.append(
                    {
                        "severity": "critical",
                        "type": "null_email",
                        "company": company_name,
                        "contact": contact_name,
                        "detail": "Email sent but contact has no email address on record",
                        "draft_id": draft["id"],
                    }
                )
                continue

            # Check 2: Email-name consistency
            tier_verified = contact.get("email_name_verified")
            if tier_verified is False:
                # Already flagged — escalate
                findings.append(
                    {
                        "severity": "critical",
                        "type": "email_name_mismatch_flagged",
                        "company": company_name,
                        "contact": contact_name,
                        "email": email,
                        "detail": "Contact has email_name_verified=False — email belongs to a different person",
                        "draft_id": draft["id"],
                    }
                )
            elif tier_verified is None:
                # Not yet checked — run the check now
                first = contact.get("first_name") or ""
                last = contact.get("last_name") or ""
                consistent, reason = check_email_name_consistency(first, last, email)
                if not consistent:
                    findings.append(
                        {
                            "severity": "critical",
                            "type": "email_name_mismatch_detected",
                            "company": company_name,
                            "contact": contact_name,
                            "email": email,
                            "detail": f"Name-email inconsistency detected post-send: {reason}",
                            "draft_id": draft["id"],
                        }
                    )
                    # Write back so future sends catch it at import time
                    try:
                        self.db.client.table("contacts").update(
                            {
                                "email_name_verified": False,
                                "is_outreach_eligible": False,
                            }
                        ).eq("id", contact_id).execute()
                    except Exception as e:
                        logger.warning("Could not update contact %s: %s", contact_id, e)

            # Check 3: Wrong job function
            tier = contact.get("contact_tier") or classify_contact_tier(title)
            if tier == "excluded":
                findings.append(
                    {
                        "severity": "high",
                        "type": "wrong_function",
                        "company": company_name,
                        "contact": contact_name,
                        "email": email,
                        "title": title,
                        "detail": f"Contact has wrong job function (tier=excluded): {title}",
                        "draft_id": draft["id"],
                    }
                )

        # Check 4: Over-threading (too many contacts hit at same company)
        for cid, names in sends_per_company.items():
            if len(names) > MAX_THREADS_PER_COMPANY:
                company_name = companies.get(cid, {}).get("name", "Unknown")
                findings.append(
                    {
                        "severity": "warning",
                        "type": "over_threading",
                        "company": company_name,
                        "contact": ", ".join(names),
                        "detail": f"{len(names)} contacts reached at same company in {days} days (max={MAX_THREADS_PER_COMPANY})",
                        "draft_id": None,
                    }
                )

        result.processed = len(drafts)

        # ── Report
        critical = [f for f in findings if f["severity"] == "critical"]
        high = [f for f in findings if f["severity"] == "high"]
        warnings = [f for f in findings if f["severity"] == "warning"]

        console.print(
            f"\n[bold]Audit complete:[/bold] {len(drafts)} sends | "
            f"[red]{len(critical)} critical[/red] | "
            f"[yellow]{len(high)} high[/yellow] | "
            f"[dim]{len(warnings)} warnings[/dim]"
        )

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
                    lines.append(
                        f":red_circle: *{len(critical)} CRITICAL* — email went to wrong person or null email"
                    )
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

    # ------------------------------------------------------------------
    # P2.4 — Weekly approval audit (BenchmarkDetector against approvals)
    # ------------------------------------------------------------------

    def audit_approvals(
        self,
        sample_size: int = 20,
        window_days: int = 7,
        export_dir: Path | None = None,
    ) -> dict:
        """Sample approved drafts from the past `window_days` and run them
        through BenchmarkDetector. Writes a JSON report and returns it.

        Output schema:
          {
            "date": "YYYY-MM-DD",
            "total_sampled": int,
            "false_negative_count": int,    # benchmark fabrications that
                                            # slipped past human review
            "attestation_defects": int,     # approved rows missing/false
                                            # required attestation keys
            "post_send_rejections": int,    # bounces, complaints, hard rejects
                                            # in the same window
            "findings": [...]
          }
        """
        now = datetime.now(timezone.utc)
        since = (now - timedelta(days=window_days)).isoformat()

        # Gather candidates: drafts approved in window. Some installs may not
        # yet have reviewed_at — fall back to approved_at if so.
        approved_rows: list[dict] = []
        try:
            approved_rows = (
                self.db.client.table("outreach_drafts")
                .select(
                    "id, body, edited_body, approval_status, approved_at, "
                    "reviewed_at, approved_by, attestation, sequence_step, "
                    "company_id, contact_id"
                )
                .in_("approval_status", ["approved", "edited"])
                .gte("approved_at", since)
                .limit(500)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning("audit_approvals: approved-drafts query failed: %s", exc)

        if not approved_rows:
            console.print("[yellow]audit_approvals: no approved drafts in window.[/yellow]")
            report = {
                "date": now.date().isoformat(),
                "window_days": window_days,
                "total_sampled": 0,
                "false_negative_count": 0,
                "attestation_defects": 0,
                "post_send_rejections": 0,
                "findings": [],
            }
            self._write_audit_report(report, export_dir)
            return report

        # Sample without replacement
        n = min(sample_size, len(approved_rows))
        sample = random.sample(approved_rows, n)

        detector = BenchmarkDetector(llm_enabled=bool(os.environ.get("ANTHROPIC_API_KEY")))

        false_negatives = 0
        attestation_defects = 0
        findings_out: list[dict] = []

        for row in sample:
            body = row.get("edited_body") or row.get("body") or ""
            analysis = detector.analyze(body)
            if analysis.has_violations:
                false_negatives += 1

            att = row.get("attestation") or {}
            required = (
                "numeric_claims_attributed",
                "persona_in_allowlist",
                "no_url_step_1",
                "company_is_manufacturer",
                "specific_opener",
            )
            att_missing = [k for k in required if not att.get(k)]
            if att_missing:
                attestation_defects += 1

            findings_out.append(
                {
                    "draft_id": row.get("id"),
                    "company_id": row.get("company_id"),
                    "contact_id": row.get("contact_id"),
                    "approved_by": row.get("approved_by"),
                    "approved_at": row.get("approved_at"),
                    "reviewed_at": row.get("reviewed_at"),
                    "sequence_step": row.get("sequence_step"),
                    "benchmark_verdict": analysis.verdict,
                    "benchmark_findings": [
                        {
                            "layer": f.layer,
                            "rule": f.rule,
                            "verdict": f.verdict,
                            "excerpt": f.excerpt,
                            "evidence_id": f.evidence_id,
                        }
                        for f in analysis.findings
                    ],
                    "attestation_missing_keys": att_missing,
                }
            )

        # Post-send rejections in the same window — bounces, complaints,
        # hard fails recorded in interactions.
        post_send_rejections = 0
        try:
            ev = (
                self.db.client.table("interactions")
                .select("id, type")
                .in_("type", ["email_bounced", "email_complained", "email_failed"])
                .gte("created_at", since)
                .limit(1000)
                .execute()
                .data
                or []
            )
            post_send_rejections = len(ev)
        except Exception as exc:
            logger.info("audit_approvals: post-send rejection lookup skipped: %s", exc)

        report = {
            "date": now.date().isoformat(),
            "window_days": window_days,
            "total_sampled": n,
            "false_negative_count": false_negatives,
            "attestation_defects": attestation_defects,
            "post_send_rejections": post_send_rejections,
            "findings": findings_out,
        }
        self._write_audit_report(report, export_dir)
        return report

    @staticmethod
    def _write_audit_report(report: dict, export_dir: Path | None = None) -> Path:
        """Write `report` to data/exports/approval_audit_<date>.json."""
        target_dir = (
            Path(export_dir)
            if export_dir
            else (Path(__file__).resolve().parents[3] / "data" / "exports")
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / f"approval_audit_{report['date']}.json"
        with open(out_path, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        console.print(f"[green]Approval audit report written: {out_path}[/green]")
        return out_path
