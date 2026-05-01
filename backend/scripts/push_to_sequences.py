"""Push ready contacts into Instantly sequences.

DEPRECATED: ProspectIQ sends outreach via Resend, not Instantly.
Instantly is used for inbox warming only. Running this script would
enroll real prospects into Instantly campaigns and cause double-contact.
"""

import sys
sys.exit(
    "DEPRECATED: ProspectIQ sends outreach via Resend (engagement.py), not Instantly. "
    "This script is disabled to prevent double-contact. "
    "See docs/SENDING_ARCHITECTURE.md for the correct send path."
)

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Optional

# Load .env before any module that reads os.environ (sequence_router, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

from rich.console import Console
from rich.table import Table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_lead_payload(contact: dict, company: dict) -> dict:
    """Build the Instantly lead dict from a contact + company row.

    Pulls the personalization field from the contact if present (the
    OutreachAgent stores a first-line hook as 'personalization').
    """
    return {
        "email": contact.get("email", ""),
        "first_name": contact.get("first_name", ""),
        "last_name": contact.get("last_name", ""),
        "company_name": company.get("name", ""),
        "website": company.get("domain", ""),
        "personalization": contact.get("personalization") or "",
    }


def _get_company_for_contact(db, contact: dict) -> dict:
    """Return the parent company dict, or an empty dict if not found."""
    company_id = contact.get("company_id")
    if not company_id:
        return {}
    company = db.get_company(company_id)
    return company or {}


# ---------------------------------------------------------------------------
# Main push logic
# ---------------------------------------------------------------------------


def push_contacts_to_sequences(
    campaign_name: Optional[str] = None,
    limit: int = 100,
    dry_run: bool = False,
) -> dict:
    """Push enriched contacts into Instantly sequences.

    Args:
        campaign_name: If set, restricts to contacts whose company was
            tagged with this campaign name.
        limit: Maximum number of contacts to process in this run.
        dry_run: If True, all logic runs but no Instantly API calls are
            made and no database updates are written.

    Returns:
        Dict with counts: pushed, skipped_active, skipped_no_campaign,
        skipped_no_email, errors.
    """
    from backend.app.core.database import Database
    from backend.app.core.dnc_registry import DNCRegistry
    from backend.app.core.sequence_router import get_campaign_id, get_vertical_bucket

    db = Database()
    dnc = DNCRegistry()

    # Lazily import Instantly client only if not a dry run (avoids requiring
    # the API key to be set during development / CI dry-run testing).
    instantly = None
    if not dry_run:
        from backend.app.integrations.instantly import InstantlyClient
        instantly = InstantlyClient()

    stats = {
        "pushed": 0,
        "skipped_active": 0,
        "skipped_no_campaign": 0,
        "skipped_no_email": 0,
        "skipped_dnc": 0,
        "errors": 0,
    }
    rows: list[dict] = []  # for the Rich summary table

    # ------------------------------------------------------------------
    # 1. Fetch candidates: enriched, have an email, not yet sequenced
    # ------------------------------------------------------------------
    console.print(
        f"\n[bold cyan]Fetching enriched contacts ready for sequencing "
        f"(limit={limit})…[/bold cyan]"
    )

    query = (
        db.client.table("contacts")
        .select("*, companies!contacts_company_id_fkey(id, name, domain, tier, naics_code, campaign_name, outreach_active)")
        .eq("enrichment_status", "enriched")
        .not_.is_("email", "null")
        .not_.eq("email", "")
        .or_("outreach_state.is.null,outreach_state.eq.enriched")
        .order("priority_score", desc=True)
        .limit(limit)
    )
    if campaign_name:
        # Filter via Python after fetch (Supabase join filter limitation)
        raw = query.execute().data
        contacts = [
            c for c in raw
            if (c.get("companies") or {}).get("campaign_name") == campaign_name
        ]
    else:
        contacts = query.execute().data

    console.print(f"  Found {len(contacts)} candidate contact(s)")

    # ------------------------------------------------------------------
    # 2. Process each contact
    # ------------------------------------------------------------------
    for contact in contacts:
        email = (contact.get("email") or "").strip()
        full_name = contact.get("full_name") or (
            f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
        )
        company_row = contact.get("companies") or {}
        company_id = contact.get("company_id") or company_row.get("id")
        contact_id = contact["id"]
        persona_type = contact.get("persona_type")

        # Guard: email required
        if not email:
            logger.debug("Skipping %s — no email", full_name)
            stats["skipped_no_email"] += 1
            rows.append({
                "name": full_name,
                "email": "—",
                "company": company_row.get("name", "?"),
                "status": "[yellow]skip: no email[/yellow]",
                "sequence": "—",
            })
            continue

        # Guard: DNC check
        blocked, reason = dnc.is_blocked(email=email)
        if blocked:
            logger.info("Skipping %s (%s) — DNC: %s", full_name, email, reason)
            stats["skipped_dnc"] += 1
            rows.append({
                "name": full_name,
                "email": email,
                "company": company_row.get("name", "?"),
                "status": f"[red]skip: DNC ({reason})[/red]",
                "sequence": "—",
            })
            continue

        # Guard: one active thread per company
        if company_id and db.is_company_in_active_outreach(company_id):
            logger.info(
                "Skipping %s (%s) — company %s already has active outreach",
                full_name, email, company_row.get("name"),
            )
            stats["skipped_active"] += 1
            rows.append({
                "name": full_name,
                "email": email,
                "company": company_row.get("name", "?"),
                "status": "[dim]skip: company active[/dim]",
                "sequence": "—",
            })
            continue

        # ------------------------------------------------------------------
        # Resolve vertical bucket → campaign ID
        # ------------------------------------------------------------------
        naics_code = company_row.get("naics_code") or contact.get("naics_code")
        naics_prefix = str(naics_code)[:3] if naics_code else None
        camp_name_tag = company_row.get("campaign_name")

        vertical = get_vertical_bucket(naics_prefix, camp_name_tag or campaign_name)
        campaign_id = get_campaign_id(vertical, persona_type)

        if not campaign_id:
            logger.warning(
                "No Instantly campaign configured for vertical=%r persona=%r — skipping %s",
                vertical, persona_type, email,
            )
            stats["skipped_no_campaign"] += 1
            rows.append({
                "name": full_name,
                "email": email,
                "company": company_row.get("name", "?"),
                "status": "[yellow]skip: no campaign[/yellow]",
                "sequence": f"{vertical}/{persona_type or 'unknown'}",
            })
            continue

        # ------------------------------------------------------------------
        # Push to Instantly
        # ------------------------------------------------------------------
        lead_payload = _build_lead_payload(contact, company_row)

        if dry_run:
            console.print(
                f"  [DRY-RUN] Would push {email} → campaign {campaign_id} "
                f"({vertical}/{persona_type})"
            )
            stats["pushed"] += 1
            rows.append({
                "name": full_name,
                "email": email,
                "company": company_row.get("name", "?"),
                "status": "[cyan]dry-run: would push[/cyan]",
                "sequence": campaign_id,
            })
            continue

        try:
            instantly.add_lead_to_campaign(campaign_id, lead_payload)

            # Update contact state
            db.update_contact_state(
                contact_id=contact_id,
                new_state="sequenced",
                from_state=contact.get("outreach_state"),
                channel="email",
                metadata={
                    "instantly_campaign_id": campaign_id,
                    "vertical": vertical,
                    "persona_type": persona_type,
                },
                extra_updates={"instantly_sequence_id": campaign_id},
            )

            # Mark company as having an active outreach thread
            if company_id:
                db.set_company_outreach_active(company_id, contact_id)

            logger.info("Pushed %s → %s (campaign %s)", email, vertical, campaign_id)
            stats["pushed"] += 1
            rows.append({
                "name": full_name,
                "email": email,
                "company": company_row.get("name", "?"),
                "status": "[green]pushed[/green]",
                "sequence": campaign_id,
            })

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to push %s: %s", email, exc)
            stats["errors"] += 1
            rows.append({
                "name": full_name,
                "email": email,
                "company": company_row.get("name", "?"),
                "status": f"[red]error: {str(exc)[:60]}[/red]",
                "sequence": campaign_id,
            })

    # ------------------------------------------------------------------
    # 3. Rich summary table
    # ------------------------------------------------------------------
    table = Table(title="Push to Sequences — Results", show_lines=False)
    table.add_column("Contact", style="bold", no_wrap=True, max_width=28)
    table.add_column("Email", max_width=34)
    table.add_column("Company", max_width=26)
    table.add_column("Status", no_wrap=True)
    table.add_column("Sequence / Campaign ID", max_width=36)

    for r in rows:
        table.add_row(r["name"], r["email"], r["company"], r["status"], r["sequence"])

    console.print()
    console.print(table)
    console.print()
    console.print(
        f"[bold green]Done.[/bold green]  "
        f"Pushed: {stats['pushed']}  |  "
        f"Skipped (company active): {stats['skipped_active']}  |  "
        f"Skipped (no campaign): {stats['skipped_no_campaign']}  |  "
        f"Skipped (DNC): {stats['skipped_dnc']}  |  "
        f"Skipped (no email): {stats['skipped_no_email']}  |  "
        f"Errors: {stats['errors']}"
    )

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Push enriched ProspectIQ contacts into Instantly sequences."
    )
    parser.add_argument(
        "--campaign",
        default=None,
        help="Restrict to contacts tagged with this campaign name.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of contacts to process (default: 100).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic without making Instantly API calls or DB writes.",
    )
    args = parser.parse_args()

    stats = push_contacts_to_sequences(
        campaign_name=args.campaign,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    if stats.get("errors", 0) > 0:
        sys.exit(1)
