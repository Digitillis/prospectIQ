"""Campaign Thread Manager — manages multi-turn conversation state.

Provides CRUD operations for campaign_threads and thread_messages tables.
Used by the ThreadAgent and the Phase 2/3 webhook handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.app.core.database import Database

logger = logging.getLogger(__name__)


class ThreadManager:
    """Manages campaign thread state and message history."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Thread CRUD
    # ------------------------------------------------------------------

    def get_or_create_thread(
        self,
        company_id: str,
        contact_id: str,
        sequence_name: str = "email_value_first",
        outreach_draft_id: str | None = None,
    ) -> dict:
        """Get existing active thread or create a new one.

        When creating a new thread, also inserts the initial outbound message
        if outreach_draft_id is provided.
        """
        # Check for existing active thread
        existing = (
            self.db.client.table("campaign_threads")
            .select("*")
            .eq("company_id", company_id)
            .eq("contact_id", contact_id)
            .in_("status", ["active", "paused"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]

        # Create new thread
        thread_row = {
            "company_id": company_id,
            "contact_id": contact_id,
            "sequence_name": sequence_name,
            "status": "active",
            "current_step": 1,
            "next_step": 2,
        }
        result = self.db.client.table("campaign_threads").insert(thread_row).execute()
        thread = result.data[0]

        # Record the initial outbound message if draft is known
        if outreach_draft_id:
            draft = self._get_draft(outreach_draft_id)
            if draft:
                self.add_outbound_message(
                    thread_id=thread["id"],
                    subject=draft.get("subject", ""),
                    body=draft.get("body", ""),
                    sent_at=draft.get("created_at", datetime.now(timezone.utc).isoformat()),
                    outreach_draft_id=outreach_draft_id,
                )
                self.db.client.table("campaign_threads").update({
                    "last_sent_at": draft.get("created_at"),
                }).eq("id", thread["id"]).execute()

        return thread

    def get_thread(self, thread_id: str) -> dict | None:
        result = (
            self.db.client.table("campaign_threads")
            .select("*")
            .eq("id", thread_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_thread_by_contact(self, company_id: str, contact_id: str) -> dict | None:
        result = (
            self.db.client.table("campaign_threads")
            .select("*")
            .eq("company_id", company_id)
            .eq("contact_id", contact_id)
            .in_("status", ["active", "paused"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def pause_thread(self, thread_id: str, reason: str = "reply_received") -> None:
        self.db.client.table("campaign_threads").update({
            "status": "paused",
            "paused_reason": reason,
            "last_replied_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", thread_id).execute()

    def resume_thread(self, thread_id: str, advance_step: bool = True) -> None:
        thread = self.get_thread(thread_id)
        if not thread:
            return
        update = {"status": "active", "paused_reason": None}
        if advance_step and thread.get("next_step"):
            update["current_step"] = thread["next_step"]
            update["next_step"] = thread["next_step"] + 1
        self.db.client.table("campaign_threads").update(update).eq("id", thread_id).execute()

    def close_thread(self, thread_id: str, status: str = "closed") -> None:
        """status: closed | converted | unsubscribed | bounced"""
        self.db.client.table("campaign_threads").update({
            "status": status,
        }).eq("id", thread_id).execute()

    # ------------------------------------------------------------------
    # Message CRUD
    # ------------------------------------------------------------------

    def add_outbound_message(
        self,
        thread_id: str,
        subject: str,
        body: str,
        sent_at: str | None = None,
        outreach_draft_id: str | None = None,
        source: str = "manual",
    ) -> dict:
        row = {
            "thread_id": thread_id,
            "direction": "outbound",
            "subject": subject,
            "body": body,
            "sent_at": sent_at or datetime.now(timezone.utc).isoformat(),
            "outreach_draft_id": outreach_draft_id,
            "source": source,
        }
        result = self.db.client.table("thread_messages").insert(row).execute()
        return result.data[0]

    def add_inbound_message(
        self,
        thread_id: str,
        subject: str,
        body: str,
        sent_at: str | None = None,
        source: str = "manual",
        raw_webhook_payload: dict | None = None,
    ) -> dict:
        row = {
            "thread_id": thread_id,
            "direction": "inbound",
            "subject": subject,
            "body": body,
            "sent_at": sent_at or datetime.now(timezone.utc).isoformat(),
            "source": source,
        }
        if raw_webhook_payload:
            row["raw_webhook_payload"] = raw_webhook_payload
        result = self.db.client.table("thread_messages").insert(row).execute()

        # Auto-pause the thread when an inbound message arrives
        self.pause_thread(thread_id, reason="reply_received")

        return result.data[0]

    def update_message_classification(
        self,
        message_id: str,
        classification: str,
        confidence: float,
        reasoning: str,
        confirmed_by: str = "user",
    ) -> None:
        self.db.client.table("thread_messages").update({
            "classification": classification,
            "classification_confidence": confidence,
            "classification_reasoning": reasoning,
            "classification_confirmed_by": confirmed_by,
        }).eq("id", message_id).execute()

    def get_thread_messages(self, thread_id: str) -> list[dict]:
        """Return all messages for a thread, oldest first."""
        result = (
            self.db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .order("sent_at")
            .execute()
        )
        return result.data or []

    def get_last_outbound(self, thread_id: str) -> dict | None:
        result = (
            self.db.client.table("thread_messages")
            .select("*")
            .eq("thread_id", thread_id)
            .eq("direction", "outbound")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # ------------------------------------------------------------------
    # Active threads query (used by Phase 2 webhook handler)
    # ------------------------------------------------------------------

    def find_thread_by_email(self, email: str) -> dict | None:
        """Find active/paused thread for a contact by email address."""
        contact_result = (
            self.db.client.table("contacts")
            .select("id")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        if not contact_result.data:
            return None
        contact_id = contact_result.data[0]["id"]

        result = (
            self.db.client.table("campaign_threads")
            .select("*")
            .eq("contact_id", contact_id)
            .in_("status", ["active", "paused"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_draft(self, draft_id: str) -> dict | None:
        result = (
            self.db.client.table("outreach_drafts")
            .select("*")
            .eq("id", draft_id)
            .execute()
        )
        return result.data[0] if result.data else None
