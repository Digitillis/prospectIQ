"""LinkedIn Activity Tracker — manual touchpoint logging for multi-channel outreach.

No scraping. The sales team logs LinkedIn activity they've observed or performed,
which feeds the intent signal engine for company-level prioritisation.

Signal types:
  - profile_view       : we viewed a prospect's profile
  - connection_accepted: prospect accepted our connection request
  - message_sent       : we sent an InMail or DM
  - post_engagement    : prospect or company posted content we engaged with

Company-level post_engagement events automatically fire an 'linkedin_activity'
intent signal via IntentEngine, boosting that company's intent score.

Usage:
    from backend.app.core.database import Database
    from backend.app.core.linkedin_tracker import LinkedInTracker

    db = Database()
    tracker = LinkedInTracker(db)

    # Log that we viewed a prospect's profile
    tracker.log_profile_view(contact_id="uuid", viewer_name="Avanish")

    # Log a company post we engaged with (fires intent signal automatically)
    tracker.log_post_engagement(
        company_id="uuid",
        post_url="https://linkedin.com/posts/...",
        engagement_type="comment",
        notes="VP Ops posted about equipment downtime costs",
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.app.core.database import Database

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class LinkedInTracker:
    """Records manual LinkedIn touchpoints and surfaces them as intent signals."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Contact-level touchpoints
    # ------------------------------------------------------------------

    def log_profile_view(
        self,
        contact_id: str,
        viewer_name: str,
        notes: Optional[str] = None,
    ) -> dict:
        """Log that a sales rep viewed a prospect's LinkedIn profile.

        Args:
            contact_id: Contact UUID.
            viewer_name: Name of the sales rep who viewed the profile.
            notes: Optional observation (e.g. "recently posted about downtime").

        Returns:
            Inserted linkedin_touchpoints row.
        """
        row = self._build_row(
            contact_id=contact_id,
            company_id=None,
            touchpoint_type="profile_view",
            viewer_or_actor=viewer_name,
            notes=notes,
        )
        result = self._insert(row)
        logger.info(f"[li] profile_view logged for contact {contact_id[:8]}")
        return result

    def log_connection_accepted(
        self,
        contact_id: str,
        notes: Optional[str] = None,
    ) -> dict:
        """Log that a prospect accepted our LinkedIn connection request.

        Args:
            contact_id: Contact UUID.
            notes: Optional context.

        Returns:
            Inserted linkedin_touchpoints row.
        """
        row = self._build_row(
            contact_id=contact_id,
            company_id=None,
            touchpoint_type="connection_accepted",
            notes=notes,
        )
        result = self._insert(row)
        logger.info(f"[li] connection_accepted logged for contact {contact_id[:8]}")
        return result

    def log_message_sent(
        self,
        contact_id: str,
        message_snippet: str,
        notes: Optional[str] = None,
    ) -> dict:
        """Log that we sent a LinkedIn InMail or DM to a prospect.

        Args:
            contact_id: Contact UUID.
            message_snippet: First ~100 chars of the message for reference.
            notes: Optional context.

        Returns:
            Inserted linkedin_touchpoints row.
        """
        row = self._build_row(
            contact_id=contact_id,
            company_id=None,
            touchpoint_type="message_sent",
            notes=notes or message_snippet[:200],
        )
        result = self._insert(row)
        logger.info(f"[li] message_sent logged for contact {contact_id[:8]}")
        return result

    # ------------------------------------------------------------------
    # Company-level touchpoints (post engagement → intent signal)
    # ------------------------------------------------------------------

    def log_post_engagement(
        self,
        company_id: str,
        post_url: str,
        engagement_type: str,
        notes: Optional[str] = None,
        contact_id: Optional[str] = None,
    ) -> dict:
        """Log that a company contact posted content we engaged with.

        Fires an 'linkedin_activity' intent signal via IntentEngine so the
        company's intent score is refreshed immediately.

        Args:
            company_id: Company UUID (required for intent signal).
            post_url: Full URL of the LinkedIn post.
            engagement_type: 'like', 'comment', or 'share'.
            notes: Description of the post / why it's relevant.
            contact_id: Optional contact UUID if we know who posted.

        Returns:
            Inserted linkedin_touchpoints row.
        """
        row = self._build_row(
            contact_id=contact_id,
            company_id=company_id,
            touchpoint_type="post_engagement",
            notes=notes,
            post_url=post_url,
            engagement_type=engagement_type,
        )
        result = self._insert(row)
        logger.info(
            f"[li] post_engagement ({engagement_type}) logged for company {company_id[:8]}"
        )

        # Fire intent signal so the company's score is updated immediately
        self._fire_intent_signal(
            company_id=company_id,
            contact_id=contact_id or "",
            detail=notes or f"LinkedIn post engagement ({engagement_type}): {post_url}",
        )

        return result

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_linkedin_touchpoints(self, contact_id: str) -> list[dict]:
        """Return all LinkedIn touchpoints for a contact, newest first.

        Args:
            contact_id: Contact UUID.

        Returns:
            List of linkedin_touchpoints rows.
        """
        try:
            result = (
                self.db.client.table("linkedin_touchpoints")
                .select("*")
                .eq("contact_id", contact_id)
                .order("created_at", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.warning(f"[li] Failed to fetch touchpoints for {contact_id[:8]}: {exc}")
            return []

    def get_companies_with_linkedin_activity(self, days: int = 7) -> list[dict]:
        """Return companies that have had LinkedIn activity in the past N days.

        Groups by company_id and returns the count of touchpoints.  Useful for
        surfacing warm accounts in the morning review.

        Args:
            days: Look-back window in days (default 7).

        Returns:
            List of dicts: {company_id, touchpoint_count, latest_activity}.
        """
        cutoff = (_now_utc() - timedelta(days=days)).isoformat()
        try:
            result = (
                self.db.client.table("linkedin_touchpoints")
                .select("company_id, created_at")
                .not_.is_("company_id", "null")
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .execute()
            )
            rows = result.data or []
        except Exception as exc:
            logger.warning(f"[li] Failed to fetch company LinkedIn activity: {exc}")
            return []

        # Aggregate in Python (Supabase free tier has no GROUP BY)
        companies: dict[str, dict] = {}
        for row in rows:
            cid = row["company_id"]
            if cid not in companies:
                companies[cid] = {
                    "company_id": cid,
                    "touchpoint_count": 0,
                    "latest_activity": row["created_at"],
                }
            companies[cid]["touchpoint_count"] += 1

        return sorted(
            companies.values(),
            key=lambda x: x["latest_activity"],
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_row(
        self,
        touchpoint_type: str,
        contact_id: Optional[str] = None,
        company_id: Optional[str] = None,
        viewer_or_actor: Optional[str] = None,
        notes: Optional[str] = None,
        post_url: Optional[str] = None,
        engagement_type: Optional[str] = None,
    ) -> dict:
        row: dict = {
            "touchpoint_type": touchpoint_type,
            "created_at": _now_utc().isoformat(),
        }
        if contact_id:
            row["contact_id"] = contact_id
        if company_id:
            row["company_id"] = company_id
        if viewer_or_actor:
            row["viewer_or_actor"] = viewer_or_actor
        if notes:
            row["notes"] = notes
        if post_url:
            row["post_url"] = post_url
        if engagement_type:
            row["engagement_type"] = engagement_type
        return row

    def _insert(self, row: dict) -> dict:
        result = self.db.client.table("linkedin_touchpoints").insert(row).execute()
        return result.data[0] if result.data else {}

    def _fire_intent_signal(
        self,
        company_id: str,
        contact_id: str,
        detail: str,
    ) -> None:
        """Fire an IntentEngine linkedin_activity signal (best-effort)."""
        try:
            from backend.app.core.intent_engine import IntentEngine
            engine = IntentEngine(self.db)
            engine.log_linkedin_activity(
                company_id=company_id,
                contact_id=contact_id,
                detail=detail,
            )
        except Exception as exc:
            logger.warning(
                f"[li] Could not fire intent signal for company {company_id[:8]}: {exc}"
            )
