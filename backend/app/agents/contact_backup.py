"""Weekly contact profile backup agent.

Exports all contacts (with linked company data) for all workspaces to local
JSON files. Runs every Saturday at 5am Chicago time.

Backup path: /Volumes/Digitillis/Data/prospectiq_backups/contacts/
Filename format: YYYY-MM-DD_<workspace_id>.json
Retention: 12 weeks (older files auto-pruned).

Why local backup: Apollo, Instantly, and enrichment data live in Supabase.
A local copy gives us an offline record with full profile context — useful if
the cloud DB ever has an incident or if we need to audit what was in the
pipeline at a specific point in time.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult

console = Console()
logger = logging.getLogger(__name__)

BACKUP_ROOT = Path("/Volumes/Digitillis/Data/prospectiq_backups/contacts")
RETENTION_WEEKS = 12


class ContactBackupAgent(BaseAgent):
    """Exports all contact + company profiles to local JSON for offline retention."""

    agent_name = "contact_backup"

    def run(self) -> AgentResult:
        result = AgentResult()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        workspace_id = getattr(self.db, "workspace_id", "default")

        # Ensure backup directory exists (NAS may not be mounted in CI)
        try:
            BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Backup directory unavailable: %s", e)
            result.errors += 1
            result.add_detail("backup", "error", f"Directory unavailable: {e}")
            return result

        # ── Fetch all contacts for this workspace
        contacts_raw = (
            self.db.client.table("contacts")
            .select(
                "id,workspace_id,company_id,first_name,last_name,full_name,"
                "email,email_status,email_name_verified,phone,title,"
                "contact_tier,is_outreach_eligible,status,enrichment_status,"
                "linkedin_url,apollo_id,persona_type,is_decision_maker,"
                "created_at,updated_at"
            )
            .execute()
            .data
        ) or []

        if not contacts_raw:
            console.print(f"[yellow]Contact backup: no contacts found for workspace {workspace_id}.[/yellow]")
            result.add_detail("backup", "skipped", "No contacts found")
            return result

        # Fetch companies for foreign-key enrichment
        company_ids = list({c["company_id"] for c in contacts_raw if c.get("company_id")})
        companies_raw = []
        if company_ids:
            companies_raw = (
                self.db.client.table("companies")
                .select(
                    "id,name,domain,industry,employee_count,revenue_range,"
                    "hq_city,hq_state,hq_country,status,created_at"
                )
                .in_("id", company_ids)
                .execute()
                .data
            ) or []
        companies_map = {c["id"]: c for c in companies_raw}

        # Merge company data into each contact record
        records = []
        for contact in contacts_raw:
            cid = contact.get("company_id")
            record = {**contact}
            if cid and cid in companies_map:
                record["company"] = companies_map[cid]
            records.append(record)

        # ── Write backup file
        outfile = BACKUP_ROOT / f"{today}_{workspace_id}.json"
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "workspace_id": workspace_id,
            "contact_count": len(records),
            "company_count": len(companies_map),
            "contacts": records,
        }
        try:
            outfile.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            size_kb = outfile.stat().st_size // 1024
            console.print(
                f"[green]Contact backup: {len(records)} contacts written to "
                f"{outfile.name} ({size_kb} KB)[/green]"
            )
            result.processed = len(records)
            result.add_detail("backup", "complete", f"{outfile.name} — {len(records)} contacts, {size_kb} KB")
        except OSError as e:
            logger.error("Failed to write backup file %s: %s", outfile, e)
            result.errors += 1
            result.add_detail("backup", "error", str(e))
            return result

        # ── Prune backups older than retention window
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=RETENTION_WEEKS)
        pruned = 0
        for f in BACKUP_ROOT.glob(f"*_{workspace_id}.json"):
            try:
                # Filename prefix is YYYY-MM-DD
                date_str = f.name[:10]
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    f.unlink()
                    pruned += 1
            except (ValueError, OSError):
                pass  # Non-matching filename or permission error — skip

        if pruned:
            console.print(f"[dim]Contact backup: pruned {pruned} file(s) older than {RETENTION_WEEKS} weeks.[/dim]")
            result.add_detail("backup", "pruned", f"{pruned} old files removed")

        return result
