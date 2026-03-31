"""Send priority queue manager.

Scores and ranks contacts ready for outreach so the pace limiter
sends the highest-value targets first each day.

Priority score (0–100) is a weighted composite of:
  - Completeness (40 pts)  — how complete the contact record is
  - Persona priority (35 pts) — how valuable the decision-maker role is
  - Company tier (15 pts)  — Tier 0 > Tier 1 > Tier 2
  - Intent boost (15 pts max) — company-level buying signals (job postings,
    FDA letters, OSHA citations, funding events, LinkedIn activity)
  - Recency penalty (-10 pts max) — penalises contacts we have already tried
    recently (prevents hammering the same people)

Usage:
    from backend.app.core.queue_manager import QueueManager

    q = QueueManager(campaign_name="tier0-mfg-pdm-roi")
    contacts = q.get_send_queue(limit=10)   # ranked list of contacts to send
    q.update_priority_scores()              # recompute + persist scores to DB
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from rich.console import Console
from rich.table import Table

from backend.app.core.database import Database

console = Console()
logger = logging.getLogger(__name__)

# Points awarded per persona type (out of 35 max)
_PERSONA_POINTS: dict[str, int] = {
    "vp_ops": 35,
    "coo": 33,
    "plant_manager": 30,
    "digital_transformation": 28,
    "vp_supply_chain": 25,
    "director_ops": 22,
    "cio": 20,
}
_PERSONA_DEFAULT = 10  # unknown / uncategorised persona

# Points awarded per tier (out of 15 max)
_TIER_POINTS: dict[str, int] = {
    "0": 15,
    "1": 10,
    "2": 5,
}
_TIER_DEFAULT = 3


def _persona_points(persona_type: str | None) -> int:
    if not persona_type:
        return _PERSONA_DEFAULT
    return _PERSONA_POINTS.get(persona_type.lower(), _PERSONA_DEFAULT)


def _tier_points(tier: str | int | None) -> int:
    if tier is None:
        return _TIER_DEFAULT
    return _TIER_POINTS.get(str(tier), _TIER_DEFAULT)


def _completeness_points(score: int | None) -> int:
    """Map 0–100 completeness score to 0–40 priority points."""
    s = max(0, min(100, score or 0))
    return round(s * 40 / 100)


def _recency_penalty(last_contacted_at: str | None) -> int:
    """Return 0–10 penalty based on how recently we contacted this person.

    >30 days ago (or never): 0 penalty
    15–30 days ago: 3 penalty
    7–14 days ago: 6 penalty
    <7 days ago: 10 penalty
    """
    if not last_contacted_at:
        return 0
    try:
        dt = datetime.fromisoformat(last_contacted_at.replace("Z", "+00:00"))
        days_ago = (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0

    if days_ago < 7:
        return 10
    if days_ago < 15:
        return 6
    if days_ago < 30:
        return 3
    return 0


def compute_priority_score(contact: dict, company: dict | None = None) -> int:
    """Compute a 0–100 priority score for a single contact dict."""
    comp = _completeness_points(contact.get("completeness_score"))
    persona = _persona_points(contact.get("persona_type"))
    tier = _tier_points((company or {}).get("tier") if company else contact.get("_tier"))
    penalty = _recency_penalty(contact.get("last_contacted_at") or contact.get("updated_at"))
    intent = min((company or {}).get("intent_score", 0), 15)  # cap intent contribution at 15
    raw = comp + persona + tier + intent - penalty
    return max(0, min(100, raw))


class QueueManager:
    """Ranks contacts ready for outreach by priority score."""

    def __init__(self, campaign_name: str | None = None):
        self.campaign_name = campaign_name
        self.db = Database()

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def get_send_queue(
        self,
        limit: int = 20,
        exclude_dnc: bool = True,
        min_completeness: int = 40,
    ) -> list[dict]:
        """Return the top `limit` contacts to send to today, ranked by priority.

        Filters:
        - enrichment_status = 'enriched'
        - email present
        - completeness_score >= min_completeness
        - Not already sent today
        - Not on DNC list (if exclude_dnc=True)
        """
        # Pull enriched contacts with email
        query = (
            self.db.client.table("contacts")
            .select("*, companies(name, domain, tier, campaign_name, status)")
            .eq("enrichment_status", "enriched")
            .not_.is_("email", "null")
            .gte("completeness_score", min_completeness)
            .order("priority_score", desc=True)
            .limit(limit * 5)  # fetch buffer to account for filters
        )

        rows = query.execute().data or []

        # Filter by campaign
        if self.campaign_name:
            rows = [
                r for r in rows
                if (r.get("companies") or {}).get("campaign_name") == self.campaign_name
            ]

        # Exclude companies in terminal states
        skip_company_statuses = {"bounced", "not_interested", "disqualified", "unsubscribed"}
        rows = [
            r for r in rows
            if (r.get("companies") or {}).get("status") not in skip_company_statuses
        ]

        # Exclude contacts already sent today
        sent_today: set[str] = set()
        try:
            today = date.today().isoformat()
            sent_result = (
                self.db.client.table("outreach_pace_log")
                .select("contact_id")
                .eq("send_date", today)
                .eq("status", "sent")
                .execute()
            )
            sent_today = {r["contact_id"] for r in (sent_result.data or [])}
        except Exception as exc:
            logger.warning(f"[queue] Could not fetch sent-today log: {exc}")

        rows = [r for r in rows if r["id"] not in sent_today]

        # Exclude DNC if requested
        if exclude_dnc:
            from backend.app.core.dnc_registry import DNCRegistry
            dnc = DNCRegistry()
            filtered = []
            for r in rows:
                blocked, _ = dnc.is_blocked(email=r.get("email"))
                if not blocked:
                    filtered.append(r)
            rows = filtered

        # Sort by priority_score descending, then completeness
        rows.sort(
            key=lambda r: (r.get("priority_score") or 0, r.get("completeness_score") or 0),
            reverse=True,
        )

        return rows[:limit]

    def update_priority_scores(
        self,
        campaign_name: Optional[str] = None,
        batch_size: int = 500,
    ) -> int:
        """Recompute and persist priority_score for all enriched contacts.

        Returns count updated.
        """
        campaign = campaign_name or self.campaign_name

        # Fetch all enriched contacts
        query = (
            self.db.client.table("contacts")
            .select("id, completeness_score, persona_type, updated_at, companies(tier, campaign_name)")
            .eq("enrichment_status", "enriched")
        )
        rows = query.execute().data or []

        if campaign:
            rows = [
                r for r in rows
                if (r.get("companies") or {}).get("campaign_name") == campaign
            ]

        updated = 0
        for contact in rows:
            company = contact.get("companies") or {}
            score = compute_priority_score(contact, company)
            try:
                self.db.client.table("contacts").update(
                    {"priority_score": score}
                ).eq("id", contact["id"]).execute()
                updated += 1
            except Exception as exc:
                logger.warning(f"[queue] Failed to update priority for {contact['id'][:8]}: {exc}")

        logger.info(f"[queue] Updated priority scores for {updated} contacts")
        return updated

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def print_queue(self, contacts: list[dict]) -> None:
        """Print the send queue as a Rich table."""
        table = Table(show_header=True, header_style="bold green")
        table.add_column("#", justify="right", min_width=3)
        table.add_column("Company", min_width=26)
        table.add_column("Contact", min_width=22)
        table.add_column("Title", min_width=26)
        table.add_column("Score", justify="center", min_width=6)
        table.add_column("Completeness", justify="center", min_width=12)
        table.add_column("Email", min_width=28)

        for i, c in enumerate(contacts, 1):
            company_name = (c.get("companies") or {}).get("name", "—")
            priority = c.get("priority_score") or 0
            completeness = c.get("completeness_score") or 0
            priority_str = (
                f"[green]{priority}[/green]" if priority >= 60 else
                f"[yellow]{priority}[/yellow]" if priority >= 40 else
                f"[dim]{priority}[/dim]"
            )
            table.add_row(
                str(i),
                company_name[:26],
                (c.get("full_name") or "—")[:22],
                (c.get("title") or "—")[:26],
                priority_str,
                f"{completeness}/100",
                (c.get("email") or "—")[:28],
            )

        console.print(table)
        console.print(f"\n[bold]{len(contacts)} contacts queued for today[/bold]")
