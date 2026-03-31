"""Do-Not-Contact (DNC) registry.

Provides a fast, two-level block check:
  1. Exact email match  — e.g. ceo@acme.com
  2. Whole-domain block — e.g. acme.com  (blocks all @acme.com addresses)

Entries are stored in the `do_not_contact` Supabase table.
Common reasons: unsubscribed, bounced, competitor, legal, manual.

Usage:
    from backend.app.core.dnc_registry import DNCRegistry

    dnc = DNCRegistry()
    if dnc.is_blocked(email="ceo@acme.com"):
        print("Blocked — skip this contact")

    dnc.add_entry(email="ceo@acme.com", reason="unsubscribed")
    dnc.add_entry(domain="competitor.com", reason="competitor")
"""

from __future__ import annotations

import logging
from typing import Optional

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database

console = Console()
logger = logging.getLogger(__name__)


class DNCRegistry:
    """Checks and manages the do-not-contact list."""

    def __init__(self):
        self.db = Database()

    # ------------------------------------------------------------------
    # Core check — used by pace_limiter
    # ------------------------------------------------------------------

    def is_blocked(
        self,
        email: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Return (is_blocked, reason).

        Checks:
          1. Exact email match (if email provided)
          2. Domain match derived from email OR explicit domain arg
        """
        if not email and not domain:
            return False, ""

        # Derive domain from email if not explicitly provided
        effective_domain = domain
        if email and "@" in email and not effective_domain:
            effective_domain = email.split("@")[-1].lower()

        email_lower = email.lower() if email else None

        try:
            # Check exact email
            if email_lower:
                result = (
                    self.db.client.table("do_not_contact")
                    .select("reason")
                    .ilike("email", email_lower)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    reason = result.data[0].get("reason", "on DNC list")
                    return True, f"email blocked ({reason})"

            # Check domain
            if effective_domain:
                result = (
                    self.db.client.table("do_not_contact")
                    .select("reason")
                    .ilike("domain", effective_domain)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    reason = result.data[0].get("reason", "on DNC list")
                    return True, f"domain blocked ({reason})"

        except Exception as exc:
            logger.warning(f"DNC check failed (allowing send): {exc}")

        return False, ""

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_entry(
        self,
        email: Optional[str] = None,
        domain: Optional[str] = None,
        reason: str = "unsubscribed",
        added_by: str = "system",
        notes: str = "",
    ) -> dict:
        """Add an email or domain to the DNC list."""
        if not email and not domain:
            raise ValueError("Must provide at least one of email or domain")

        record: dict = {
            "reason": reason,
            "added_by": added_by,
        }
        if email:
            record["email"] = email.lower().strip()
        if domain:
            record["domain"] = domain.lower().strip().lstrip("@")
        if notes:
            record["notes"] = notes

        result = self.db.client.table("do_not_contact").insert(record).execute()
        entry = result.data[0] if result.data else record
        logger.info(f"[dnc] Added entry: {email or domain} ({reason})")
        return entry

    def remove_entry(
        self,
        email: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> int:
        """Remove matching entries. Returns count removed."""
        if not email and not domain:
            raise ValueError("Must provide at least one of email or domain")

        removed = 0
        if email:
            result = (
                self.db.client.table("do_not_contact")
                .delete()
                .ilike("email", email.lower())
                .execute()
            )
            removed += len(result.data or [])

        if domain:
            result = (
                self.db.client.table("do_not_contact")
                .delete()
                .ilike("domain", domain.lower())
                .execute()
            )
            removed += len(result.data or [])

        logger.info(f"[dnc] Removed {removed} entries for {email or domain}")
        return removed

    def list_entries(self, limit: int = 200) -> list[dict]:
        """Return all DNC entries."""
        result = (
            self.db.client.table("do_not_contact")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    # ------------------------------------------------------------------
    # Auto-add from bounce events (called by engagement agent)
    # ------------------------------------------------------------------

    def add_bounce(self, email: str, notes: str = "") -> dict:
        """Convenience wrapper to add a hard bounce."""
        return self.add_entry(
            email=email,
            reason="bounced",
            added_by="system",
            notes=notes or "Hard bounce detected by Instantly poll",
        )


# ------------------------------------------------------------------
# CLI helpers
# ------------------------------------------------------------------

def print_dnc_table(entries: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold red")
    table.add_column("Type", min_width=8)
    table.add_column("Value", min_width=30)
    table.add_column("Reason", min_width=16)
    table.add_column("Added By", min_width=10)
    table.add_column("Added At", min_width=12)

    for entry in entries:
        entry_type = "email" if entry.get("email") else "domain"
        value = entry.get("email") or entry.get("domain") or "—"
        added_at = (entry.get("created_at") or "")[:10]
        table.add_row(
            entry_type,
            value,
            entry.get("reason", "—"),
            entry.get("added_by", "—"),
            added_at,
        )
    console.print(table)
