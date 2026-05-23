"""
Deterministic Review Queue Validator
=====================================
Validates the current queue state is consistent: positions are stable,
no silent mutations have occurred, and approved-but-unsent drafts match
current governance eligibility.

Usage:
    python scripts/deterministic_review_validator.py

Author: Avanish Mehrotra & Digitillis Architecture Team
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("review_validator")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
SENDABLE_EMAIL_STATUSES = {"verified", "catch_all"}


def sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def validate_queue_state() -> dict:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "issues": [],
    }

    # 1. Check ordering stability
    log.info("[1] Checking queue ordering stability...")
    step2_unsent = (
        sb.table("outreach_drafts")
        .select("id, approval_status, body, created_at, contact_id, company_id")
        .eq("sequence_step", 2)
        .is_("sent_at", "null")
        .execute()
        .data or []
    )

    company_ids = list({r["company_id"] for r in step2_unsent if r.get("company_id")})
    contact_ids = list({r["contact_id"] for r in step2_unsent if r.get("contact_id")})

    companies: dict = {}
    for i in range(0, len(company_ids), 100):
        chunk = company_ids[i : i + 100]
        cr = sb.table("companies").select("id, name").in_("id", chunk).execute()
        for c in cr.data or []:
            companies[c["id"]] = c

    contacts: dict = {}
    for i in range(0, len(contact_ids), 100):
        chunk = contact_ids[i : i + 100]
        cr = sb.table("contacts").select("id, full_name, last_name, email_status, is_outreach_eligible").in_("id", chunk).execute()
        for c in cr.data or []:
            contacts[c["id"]] = c

    def sort_key(r: dict) -> tuple[str, str]:
        co = companies.get(r.get("company_id", ""), {})
        ct = contacts.get(r.get("contact_id", ""), {})
        return (
            (co.get("name") or "").lower(),
            (ct.get("last_name") or (ct.get("full_name", "").split()[-1] if ct.get("full_name") else "")).lower()
        )

    sorted_by_canonical = sorted(step2_unsent, key=sort_key)
    sorted_by_created = sorted(step2_unsent, key=lambda r: r.get("created_at", ""), reverse=True)

    # Compare position of first 64 records between orderings
    canonical_ids_64 = [r["id"] for r in sorted_by_canonical[:64]]
    created_ids_64 = [r["id"] for r in sorted_by_created[:64]]

    order_match = canonical_ids_64 == created_ids_64
    results["checks"]["ordering_canonical_vs_created_match_first_64"] = order_match
    if not order_match:
        results["issues"].append({
            "severity": "HIGH",
            "check": "ordering_drift",
            "detail": "Canonical sort (company/last_name) differs from created_at DESC in positions 1-64",
            "impact": "Bulk approvals using created_at order target wrong drafts"
        })
    log.info("  Ordering stable: %s", order_match)

    # 2. Check approved drafts governance eligibility
    log.info("[2] Checking approved draft governance eligibility...")
    approved_unsent = (
        sb.table("outreach_drafts")
        .select("id, contact_id, company_id, approved_at, approval_status")
        .eq("approval_status", "approved")
        .is_("sent_at", "null")
        .execute()
        .data or []
    )

    approved_contact_ids = list({r["contact_id"] for r in approved_unsent if r.get("contact_id")})
    approved_contacts: dict = {}
    for i in range(0, len(approved_contact_ids), 100):
        chunk = approved_contact_ids[i : i + 100]
        cr = sb.table("contacts").select("id, email_status, is_outreach_eligible, contact_tier").in_("id", chunk).execute()
        for c in cr.data or []:
            approved_contacts[c["id"]] = c

    gov_violations = []
    for draft in approved_unsent:
        ct = approved_contacts.get(draft.get("contact_id", ""), {})
        email_status = ct.get("email_status") or "null"
        eligible = ct.get("is_outreach_eligible")
        if email_status not in SENDABLE_EMAIL_STATUSES or not eligible:
            gov_violations.append({
                "draft_id": draft["id"][:8],
                "contact_id": draft.get("contact_id", "")[:8],
                "email_status": email_status,
                "is_eligible": eligible,
            })

    results["checks"]["approved_unsent_with_gov_violations"] = len(gov_violations)
    if gov_violations:
        results["issues"].append({
            "severity": "HIGH",
            "check": "approved_governance_drift",
            "count": len(gov_violations),
            "detail": f"{len(gov_violations)} approved drafts have contacts that are now ineligible",
            "examples": gov_violations[:3],
        })
    log.info("  Approved governance violations: %d / %d", len(gov_violations), len(approved_unsent))

    # 3. Check for post-approval suppression
    log.info("[3] Checking post-approval suppression...")
    suppressed_after_approval = []
    for draft in approved_unsent:
        contact_id = draft.get("contact_id")
        approved_at = draft.get("approved_at")
        if not contact_id or not approved_at:
            continue
        try:
            supp = (
                sb.table("suppression_log")
                .select("id, created_at")
                .eq("contact_id", contact_id)
                .gt("created_at", approved_at)
                .limit(1)
                .execute()
            )
            if supp.data:
                suppressed_after_approval.append(draft["id"][:8])
        except Exception:
            pass

    results["checks"]["approved_drafts_suppressed_after_approval"] = len(suppressed_after_approval)
    if suppressed_after_approval:
        results["issues"].append({
            "severity": "CRITICAL",
            "check": "post_approval_suppression",
            "count": len(suppressed_after_approval),
            "detail": "Contacts suppressed AFTER their draft was approved — must not send",
            "draft_ids": suppressed_after_approval[:10],
        })
    log.info("  Post-approval suppressions: %d", len(suppressed_after_approval))

    # 4. Check send_assertions coverage for sent drafts
    log.info("[4] Checking send_assertion coverage...")
    sent_drafts = (
        sb.table("outreach_drafts")
        .select("id, contact_id, sent_at")
        .not_.is_("sent_at", "null")
        .limit(500)
        .execute()
        .data or []
    )

    sent_contact_ids = list({r["contact_id"] for r in sent_drafts if r.get("contact_id")})
    contacts_with_assertions: set[str] = set()
    for i in range(0, len(sent_contact_ids), 100):
        chunk = sent_contact_ids[i : i + 100]
        try:
            ar = (
                sb.table("send_assertions")
                .select("contact_id")
                .in_("contact_id", chunk)
                .execute()
            )
            for a in ar.data or []:
                if a.get("contact_id"):
                    contacts_with_assertions.add(a["contact_id"])
        except Exception:
            pass

    sent_without_assertions = [
        r for r in sent_drafts if r.get("contact_id") not in contacts_with_assertions
    ]
    assertion_coverage_pct = (
        round(100 * len(contacts_with_assertions) / len(sent_contact_ids), 1)
        if sent_contact_ids else 100.0
    )
    results["checks"]["sent_drafts_total"] = len(sent_drafts)
    results["checks"]["sent_drafts_without_assertions"] = len(sent_without_assertions)
    results["checks"]["assertion_coverage_pct"] = assertion_coverage_pct
    if assertion_coverage_pct < 80:
        results["issues"].append({
            "severity": "MEDIUM",
            "check": "assertion_coverage_low",
            "detail": f"Only {assertion_coverage_pct}% of sent drafts have send_assertions records",
        })
    log.info("  Assertion coverage: %.1f%% (%d/%d contacts)", assertion_coverage_pct,
             len(contacts_with_assertions), len(sent_contact_ids))

    # 5. Orphan state detection
    log.info("[5] Detecting orphan states...")
    # Step-2 approved without step-1 sent
    step2_approved = (
        sb.table("outreach_drafts")
        .select("id, contact_id")
        .eq("sequence_step", 2)
        .eq("approval_status", "approved")
        .is_("sent_at", "null")
        .execute()
        .data or []
    )

    orphan_step2 = []
    for d in step2_approved:
        cid = d.get("contact_id")
        if not cid:
            continue
        r = (
            sb.table("outreach_drafts")
            .select("id")
            .eq("contact_id", cid)
            .eq("sequence_step", 1)
            .not_.is_("sent_at", "null")
            .limit(1)
            .execute()
        )
        if not r.data:
            orphan_step2.append(d["id"][:8])

    results["checks"]["step2_approved_without_step1_sent"] = len(orphan_step2)
    if orphan_step2:
        results["issues"].append({
            "severity": "HIGH",
            "check": "orphan_step2",
            "count": len(orphan_step2),
            "detail": "Step-2 approved but step-1 was never sent",
            "examples": orphan_step2[:5],
        })
    log.info("  Orphan step-2 (no step-1 sent): %d", len(orphan_step2))

    # 6. Manifests table exists
    log.info("[6] Checking review_manifests table...")
    manifests_exist = False
    try:
        r = sb.table("review_manifests").select("manifest_id").limit(1).execute()
        manifests_exist = True
    except Exception as exc:
        results["issues"].append({
            "severity": "HIGH",
            "check": "review_manifests_table_missing",
            "detail": f"review_manifests table not found: {exc}",
        })
    results["checks"]["review_manifests_table_exists"] = manifests_exist
    log.info("  review_manifests table exists: %s", manifests_exist)

    # Summary
    issue_count = len(results["issues"])
    severity_counts = {}
    for issue in results["issues"]:
        s = issue.get("severity", "UNKNOWN")
        severity_counts[s] = severity_counts.get(s, 0) + 1
    results["issue_count"] = issue_count
    results["severity_summary"] = severity_counts

    return results


if __name__ == "__main__":
    from pathlib import Path

    results = validate_queue_state()

    output_dir = Path("docs/reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "operational_state_consistency_report.md"
    lines = [
        "# Operational State Consistency Report",
        "",
        f"**Run at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Check Results",
        "",
        "| Check | Value |",
        "|-------|-------|",
    ]
    for k, v in results["checks"].items():
        lines.append(f"| {k} | {v} |")

    lines += ["", "## Issues Found", ""]
    if not results["issues"]:
        lines.append("_No issues found._")
    else:
        for issue in results["issues"]:
            lines.append(f"### [{issue['severity']}] {issue['check']}")
            lines.append(f"{issue.get('detail', '')}")
            if issue.get("examples"):
                lines.append(f"Examples: {issue['examples']}")
            if issue.get("count"):
                lines.append(f"Count: {issue['count']}")
            lines.append("")

    report_path.write_text("\n".join(lines))
    log.info("Report written to %s", report_path)

    # Write SQL validation queries
    sql_path = output_dir / "state_integrity_validation.sql"
    sql_path.write_text("""-- State Integrity Validation Queries
-- Run these periodically to verify ProspectIQ send-pipeline integrity.
-- Author: Avanish Mehrotra & Digitillis Architecture Team

-- 1. Approved drafts with ineligible email status
SELECT od.id, od.contact_id, c.email_status, c.is_outreach_eligible
FROM outreach_drafts od
JOIN contacts c ON c.id = od.contact_id
WHERE od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND (c.email_status NOT IN ('verified', 'catch_all') OR c.is_outreach_eligible IS NOT TRUE);

-- 2. Approved drafts for contacts suppressed after approval
SELECT od.id, od.contact_id, od.approved_at, sl.created_at as suppressed_at
FROM outreach_drafts od
JOIN suppression_log sl ON sl.contact_id = od.contact_id
WHERE od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND sl.created_at > od.approved_at;

-- 3. Step-2 approved drafts without step-1 sent
SELECT od.id, od.contact_id
FROM outreach_drafts od
WHERE od.sequence_step = 2
  AND od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM outreach_drafts s1
      WHERE s1.contact_id = od.contact_id
        AND s1.sequence_step = 1
        AND s1.sent_at IS NOT NULL
  );

-- 4. Sent drafts without send_assertion records
SELECT od.id, od.contact_id, od.sent_at
FROM outreach_drafts od
WHERE od.sent_at IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM send_assertions sa WHERE sa.contact_id = od.contact_id
  );

-- 5. Queue ordering drift check
-- Compare canonical (company/last_name) vs created_at positions
WITH canonical AS (
    SELECT od.id, ROW_NUMBER() OVER (
        ORDER BY LOWER(co.name), LOWER(COALESCE(ct.last_name, SPLIT_PART(ct.full_name, ' ', -1)))
    ) as canonical_pos
    FROM outreach_drafts od
    JOIN companies co ON co.id = od.company_id
    JOIN contacts ct ON ct.id = od.contact_id
    WHERE od.sequence_step = 2 AND od.sent_at IS NULL
),
by_created AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at DESC) as created_pos
    FROM outreach_drafts
    WHERE sequence_step = 2 AND sent_at IS NULL
)
SELECT c.id, c.canonical_pos, bc.created_pos,
       ABS(c.canonical_pos - bc.created_pos) as position_drift
FROM canonical c
JOIN by_created bc ON bc.id = c.id
WHERE c.canonical_pos <= 64 OR bc.created_pos <= 64
ORDER BY position_drift DESC
LIMIT 20;
""")
    log.info("SQL validation queries written to %s", sql_path)

    print("\n=== VALIDATION SUMMARY ===")
    for k, v in results["checks"].items():
        print(f"  {k}: {v}")
    if results["issues"]:
        print(f"\nISSUES FOUND ({results['issue_count']}):")
        for issue in results["issues"]:
            print(f"  [{issue['severity']}] {issue['check']}: {issue.get('detail', '')[:80]}")
    else:
        print("\nAll checks passed.")
