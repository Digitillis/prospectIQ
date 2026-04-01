"""Import / sync lead engagement state from Instantly into ProspectIQ.

The Instantly v2 API does NOT have a bulk lead listing endpoint.
The only working lead endpoint is GET /leads?email=<email> (individual lookup).

Strategy:
  1. Query ProspectIQ for contacts that have a sent outreach draft
     (outreach_drafts.sent_at IS NOT NULL).
  2. For each email, call instantly.get_lead_status() to check their
     activity flags in Instantly (is_replied, is_bounced, is_opened, etc.).
  3. Update outreach_state and fire suppression logic accordingly.
  4. Print a reconciliation summary.

Safe to re-run: state transitions are guarded against downgrades.

Usage:
    python -m backend.scripts.import_instantly_leads [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database
from backend.app.integrations.instantly import InstantlyClient

console = Console()
logger = logging.getLogger(__name__)

# Minimum seconds between individual Instantly API lookups (avoid rate limit)
_LOOKUP_DELAY = 0.5

# State rank — don't downgrade a higher state
_STATE_RANK = {
    "identified": 0,
    "sequenced": 1,
    "touch_1_sent": 2,
    "touch_2_sent": 3,
    "touch_3_sent": 4,
    "touch_4_sent": 5,
    "touch_5_sent": 6,
    "replied": 10,
    "bounced": 10,
    "unsubscribed": 10,
    "meeting_booked": 10,
    "closed_won": 10,
    "closed_lost": 10,
}

_TERMINAL_STATES = {"replied", "bounced", "unsubscribed", "meeting_booked", "closed_won", "closed_lost"}


def _classify_instantly_lead(lead: dict) -> str | None:
    """Map Instantly activity flags to an outreach_state.

    Returns None if no meaningful state can be determined (e.g. lead not found).
    """
    if not lead:
        return None
    # Instantly v2 uses various field names across versions
    if lead.get("is_replied") or lead.get("replied"):
        return "replied"
    if lead.get("is_bounced") or lead.get("bounced"):
        return "bounced"
    if lead.get("is_unsubscribed") or lead.get("unsubscribed"):
        return "unsubscribed"
    if lead.get("is_sent") or lead.get("is_opened") or lead.get("is_clicked") or lead.get("sent"):
        return "touch_1_sent"
    return None  # in Instantly but not yet acted on


def import_leads(dry_run: bool = False) -> None:
    db = Database()

    stats = {
        "contacts_checked": 0,
        "not_in_instantly": 0,
        "state_updated": 0,
        "suppressed": 0,
        "skipped_already_terminal": 0,
        "skipped_no_upgrade": 0,
        "errors": 0,
    }

    # ------------------------------------------------------------------
    # Step 1: Find all contacts that have a sent draft
    # ------------------------------------------------------------------
    console.print("\n[bold cyan]Finding contacts with sent outreach drafts...[/bold cyan]")

    sent_rows = (
        db.client.table("outreach_drafts")
        .select("contact_id, sent_at, contacts(id, email, outreach_state, company_id)")
        .not_.is_("sent_at", "null")
        .execute()
        .data
    )

    # Deduplicate by contact_id — one lookup per contact
    seen_contact_ids: set[str] = set()
    contacts_to_check: list[dict] = []

    for row in sent_rows:
        contact = row.get("contacts") or {}
        contact_id = contact.get("id") or row.get("contact_id")
        email = contact.get("email", "").lower().strip()

        if not email or not contact_id:
            continue
        if contact_id in seen_contact_ids:
            continue

        seen_contact_ids.add(contact_id)
        contacts_to_check.append({
            "contact_id": contact_id,
            "email": email,
            "outreach_state": contact.get("outreach_state") or "identified",
            "company_id": contact.get("company_id"),
        })

    console.print(f"[green]Found {len(contacts_to_check)} unique contacts with sent drafts.[/green]")

    if not contacts_to_check:
        console.print("[yellow]No sent drafts found — nothing to sync.[/yellow]")
        return

    # ------------------------------------------------------------------
    # Step 2: Look up each email in Instantly and sync state
    # ------------------------------------------------------------------
    console.print("\n[bold cyan]Looking up each contact in Instantly...[/bold cyan]")

    with InstantlyClient() as instantly:
        for contact in contacts_to_check:
            email = contact["email"]
            contact_id = contact["contact_id"]
            company_id = contact["company_id"]
            current_state = contact["outreach_state"]
            stats["contacts_checked"] += 1

            try:
                time.sleep(_LOOKUP_DELAY)
                lead = instantly.get_lead_status(email)

                if not lead:
                    stats["not_in_instantly"] += 1
                    console.print(f"  [dim]{email} — not found in Instantly[/dim]")
                    continue

                target_state = _classify_instantly_lead(lead)
                if not target_state:
                    console.print(f"  [dim]{email} — in Instantly but no activity yet[/dim]")
                    continue

                # Don't overwrite a terminal state
                if current_state in _TERMINAL_STATES and target_state not in _TERMINAL_STATES:
                    stats["skipped_already_terminal"] += 1
                    continue

                # Don't downgrade
                current_rank = _STATE_RANK.get(current_state, 0)
                target_rank = _STATE_RANK.get(target_state, 0)
                if target_rank <= current_rank and target_state not in _TERMINAL_STATES:
                    stats["skipped_no_upgrade"] += 1
                    continue

                suppress = target_state in ("bounced", "unsubscribed")

                if not dry_run:
                    extra: dict = {}
                    if target_state == "replied":
                        extra["replied_at"] = datetime.now(timezone.utc).isoformat()
                    elif target_state == "bounced":
                        extra["bounced_at"] = datetime.now(timezone.utc).isoformat()

                    db.update_contact_state(
                        contact_id=contact_id,
                        new_state=target_state,
                        from_state=current_state,
                        channel="email",
                        instantly_event=f"import_{target_state}",
                        metadata={"imported_from_instantly": True},
                        extra_updates=extra or None,
                    )

                    if suppress:
                        reason = "bounced" if target_state == "bounced" else "unsubscribed"
                        db.add_to_dnc(email=email, reason=reason, added_by="instantly_import")
                        stats["suppressed"] += 1

                stats["state_updated"] += 1
                action = "[dim](dry run)[/dim]" if dry_run else ""
                suppress_note = " + DNC" if suppress else ""
                console.print(
                    f"  [green]✓[/green] {email}: {current_state} → {target_state}{suppress_note} {action}"
                )

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error syncing {email}: {e}", exc_info=True)
                console.print(f"  [red]✗[/red] {email} — {e}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    console.print("\n")
    table = Table(title="Instantly Sync Summary", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Contacts checked", str(stats["contacts_checked"]))
    table.add_row("Not found in Instantly", str(stats["not_in_instantly"]))
    table.add_row("State transitions applied", str(stats["state_updated"]))
    table.add_row("Suppressed (DNC added)", str(stats["suppressed"]))
    table.add_row("Skipped (already terminal)", str(stats["skipped_already_terminal"]))
    table.add_row("Skipped (no upgrade needed)", str(stats["skipped_no_upgrade"]))
    table.add_row("Errors", str(stats["errors"]))

    console.print(table)

    if dry_run:
        console.print("\n[bold yellow]DRY RUN — no changes written.[/bold yellow]")
    else:
        console.print("\n[bold green]Sync complete.[/bold green]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync lead engagement state from Instantly into ProspectIQ"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    import_leads(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
