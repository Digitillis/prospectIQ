"""Remediation script — fix over-broad company bounce suppression.

Migration 048 introduced tiered suppression where a single contact bounce
does not escalate to company scope. This script resets the 'bounced' status
on companies where the bounce was isolated to a single contact (the original
incorrect behaviour), restoring them to their correct pre-bounce status.

Safe to re-run: uses an idempotent UPDATE pattern.

Usage:
    python scripts/remediate_company_bounce_status.py [--dry-run] [--workspace-id ...]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def run(dry_run: bool = True, workspace_id: str | None = None) -> None:
    from backend.app.core.database import Database
    db = Database(workspace_id=workspace_id or "00000000-0000-0000-0000-000000000001")

    print(f"{'[DRY RUN] ' if dry_run else ''}Remediating company bounce status...")

    # 1. Find all companies currently marked bounced
    bounced_companies = (
        db.client.table("companies")
        .select("id, name, status, updated_at")
        .eq("status", "bounced")
        .execute()
        .data or []
    )
    print(f"  Found {len(bounced_companies)} companies with status='bounced'")

    remediated = 0
    kept_bounced = 0
    errors = 0

    for company in bounced_companies:
        cid = company["id"]
        name = company.get("name", cid)

        # 2. Count distinct contacts with bounced status at this company
        bounced_contacts = (
            db.client.table("contacts")
            .select("id, full_name, email")
            .eq("company_id", cid)
            .eq("status", "bounced")
            .execute()
            .data or []
        )
        bounced_count = len(bounced_contacts)

        # 3. If multiple contacts bounced, keep company suppression (escalation is correct)
        if bounced_count >= 2:
            print(f"  KEEP   {name}: {bounced_count} contacts bounced — company suppression correct")
            kept_bounced += 1
            continue

        # 4. Single contact bounce — determine the correct status to restore
        # Logic: if any email was sent (not bounced contact), use 'contacted'.
        # If the company has an 'engaged' or 'replied' signal, preserve it.
        # Fallback: 'contacted' (conservative — they've had at least one send attempt).
        sent_count = (
            db.client.table("outreach_drafts")
            .select("id", count="exact")
            .eq("company_id", cid)
            .not_.is_("sent_at", "null")
            .execute()
            .count or 0
        )

        # Check for positive engagement signals
        engaged = (
            db.client.table("interactions")
            .select("id")
            .eq("company_id", cid)
            .in_("type", ["email_opened", "email_clicked", "email_replied"])
            .limit(1)
            .execute()
            .data or []
        )

        restore_status = "engaged" if engaged else ("contacted" if sent_count > 0 else "discovered")

        bounced_names = ", ".join(c.get("full_name", c["id"]) for c in bounced_contacts)
        print(f"  RESET  {name}: 1 bounced contact ({bounced_names}) → restoring to '{restore_status}'")

        if not dry_run:
            try:
                db.client.table("companies").update({
                    "status": restore_status,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", cid).execute()
                remediated += 1
            except Exception as exc:
                print(f"  ERROR  {name}: {exc}")
                errors += 1
        else:
            remediated += 1

    print()
    print(f"Summary ({'DRY RUN — no changes written' if dry_run else 'APPLIED'}):")
    print(f"  Would reset / reset: {remediated}")
    print(f"  Kept bounced (multi-contact): {kept_bounced}")
    print(f"  Errors: {errors}")

    if dry_run:
        print()
        print("Re-run with --no-dry-run to apply changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remediate over-broad company bounce suppression")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", default=True)
    parser.add_argument("--workspace-id", default=None)
    args = parser.parse_args()
    run(dry_run=args.dry_run, workspace_id=args.workspace_id)
