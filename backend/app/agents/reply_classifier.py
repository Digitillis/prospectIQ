"""Reply Classifier Agent — auto-classify every incoming prospect reply.

Uses Claude Haiku to classify reply intent, sentiment, and key objection.
Runs on every new reply detected by the Gmail intake job.

When wrong_person_flag=True:
  - Sets contact is_outreach_eligible=False
  - Removes from outbound_eligible_contacts
  - Queues for re-enrichment
  - Excludes company from ICP if reply confirms wrong target

Cost: ~$0.0005/reply. Output cached by reply hash to avoid double-spend.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"

_CLASSIFICATION_PROMPT = """You are classifying a cold outreach reply from a prospect.

Outreach context:
- Sender: {sender_name} ({sender_company})
- Recipient: {contact_name}, {contact_title} at {company_name}
- Sequence step: {sequence_step}

Reply:
---
{reply_text}
---

Classify this reply. Return ONLY valid JSON with exactly these fields:

{{
  "sentiment": "positive" | "neutral" | "negative",
  "intent": "interested" | "not_interested" | "wrong_person" | "unsubscribe" | "meeting_request" | "auto_reply" | "other",
  "wrong_person_flag": true | false,
  "key_objection": "budget" | "timing" | "not_a_fit" | "already_have_solution" | "do_not_contact" | null,
  "confidence": 0.0-1.0,
  "reasoning": "one sentence"
}}

wrong_person_flag=true means the reply explicitly states this email reached the wrong inbox
(e.g., "I think you meant to contact someone else", "Wrong person", "I handle X not Y").
Only set it when the reply clearly indicates wrong recipient, not just wrong timing or fit."""


class ReplyClassifierAgent:
    """Classifies prospect replies and updates outcomes + contact eligibility."""

    def __init__(self, db: Any, settings: Any | None = None):
        self._db = db
        self._settings = settings

    def classify_reply(
        self,
        reply_text: str,
        contact_id: str,
        company_id: str,
        send_id: str | None = None,
        contact: dict | None = None,
        company: dict | None = None,
    ) -> dict:
        """Classify a single reply and update all downstream records.

        Args:
            reply_text: Raw reply text from prospect.
            contact_id: Contact UUID.
            company_id: Company UUID.
            send_id: Draft UUID (used to link to outreach_outcomes).
            contact: Contact dict (fetched from DB if not provided).
            company: Company dict (fetched from DB if not provided).

        Returns:
            Classification result dict.
        """
        # Check cache by reply hash — avoid double-spend on re-processed emails
        reply_hash = hashlib.sha256(reply_text.encode()).hexdigest()[:32]
        try:
            cached = (
                self._db.client.table("reply_classifications")
                .select("classification")
                .eq("reply_hash", reply_hash)
                .limit(1)
                .execute()
                .data or []
            )
            if cached and cached[0].get("classification"):
                logger.debug("Reply classification cache hit: %s", reply_hash)
                return cached[0]["classification"]
        except Exception:
            pass  # Cache miss — proceed with Haiku call

        # Fetch contact + company context if not provided
        if not contact:
            try:
                rows = self._db.client.table("contacts").select(
                    "full_name,title,contact_tier"
                ).eq("id", contact_id).limit(1).execute().data or []
                contact = rows[0] if rows else {}
            except Exception:
                contact = {}

        if not company:
            try:
                rows = self._db.client.table("companies").select(
                    "name"
                ).eq("id", company_id).limit(1).execute().data or []
                company = rows[0] if rows else {}
            except Exception:
                company = {}

        from backend.app.core.config import get_outreach_guidelines
        g = get_outreach_guidelines()
        sender = g.get("sender", {})

        prompt = _CLASSIFICATION_PROMPT.format(
            sender_name=sender.get("name", "Avanish"),
            sender_company=sender.get("company", "Digitillis"),
            contact_name=contact.get("full_name", "the recipient"),
            contact_title=contact.get("title", ""),
            company_name=company.get("name", "their company"),
            sequence_step="unknown",
            reply_text=reply_text[:2000],  # Haiku context limit guard
        )

        classification: dict = {}
        try:
            import anthropic
            settings = self._settings
            if not settings:
                from backend.app.core.config import get_settings
                settings = get_settings()

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
            classification = json.loads(raw.strip())
        except Exception as e:
            logger.error("Haiku classification failed: %s", e)
            classification = {
                "sentiment": "neutral",
                "intent": "other",
                "wrong_person_flag": False,
                "key_objection": None,
                "confidence": 0.0,
                "reasoning": f"classification_error: {str(e)[:100]}",
            }

        # Write to cache table
        try:
            self._db.client.table("reply_classifications").insert({
                "reply_hash": reply_hash,
                "contact_id": contact_id,
                "company_id": company_id,
                "classification": classification,
            }).execute()
        except Exception:
            pass

        # Update outreach_outcomes
        self._update_outcome(send_id, contact_id, company_id, classification, reply_text)

        # Handle wrong_person_flag
        if classification.get("wrong_person_flag"):
            self._handle_wrong_person(contact_id, company_id, contact)

        # Handle unsubscribe
        if classification.get("intent") == "unsubscribe":
            self._handle_unsubscribe(contact_id, company_id)

        # Handle not_a_fit (add to ICP exclusions)
        if classification.get("intent") == "not_interested" and classification.get("key_objection") == "not_a_fit":
            self._handle_not_fit(company_id)

        logger.info(
            "Classified reply from %s at %s: intent=%s, sentiment=%s, wrong_person=%s",
            contact.get("full_name"), company.get("name"),
            classification.get("intent"), classification.get("sentiment"),
            classification.get("wrong_person_flag"),
        )

        return classification

    def _update_outcome(self, send_id: str | None, contact_id: str, company_id: str,
                        classification: dict, reply_text: str) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "replied_at": now,
            "reply_sentiment": classification.get("sentiment"),
            "reply_classification": classification.get("intent"),
            "reply_key_objection": classification.get("key_objection"),
            "wrong_person_flag": classification.get("wrong_person_flag", False),
            "raw_reply_snippet": reply_text[:500],
            "updated_at": now,
        }
        try:
            q = self._db.client.table("outreach_outcomes").update(update)
            if send_id:
                q = q.eq("send_id", send_id)
            else:
                q = q.eq("contact_id", contact_id)
            q.execute()
        except Exception as e:
            logger.warning("Could not update outreach_outcome: %s", e)

    def _handle_wrong_person(self, contact_id: str, company_id: str, contact: dict) -> None:
        """Block outreach to contact, alert, and queue for re-enrichment."""
        logger.warning(
            "Wrong person reply: contact_id=%s (%s). Blocking outreach.",
            contact_id, contact.get("full_name"),
        )
        try:
            self._db.client.table("contacts").update({
                "is_outreach_eligible": False,
                "email_name_verified": False,
                "status": "wrong_person",
            }).eq("id", contact_id).execute()
        except Exception as e:
            logger.warning("Could not update contact %s: %s", contact_id, e)

        try:
            self._db.client.table("outbound_eligible_contacts").delete().eq("contact_id", contact_id).execute()
        except Exception:
            pass

        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f":warning: *Wrong person reply* — {contact.get('full_name', contact_id)} "
                f"has been blocked and removed from outbound_eligible_contacts. "
                f"Re-enrich to find the correct contact.",
                emoji=":x:",
            )
        except Exception:
            pass

    def _handle_unsubscribe(self, contact_id: str, company_id: str) -> None:
        try:
            self._db.client.table("contacts").update({
                "is_outreach_eligible": False,
                "status": "unsubscribed",
            }).eq("id", contact_id).execute()
            self._db.client.table("outbound_eligible_contacts").delete().eq("contact_id", contact_id).execute()
        except Exception as e:
            logger.warning("Could not process unsubscribe for %s: %s", contact_id, e)

    def _handle_not_fit(self, company_id: str) -> None:
        """Add company to ICP exclusions."""
        try:
            from backend.app.core.icp_manager import ICPManager
            ICPManager(self._db).exclude_company(
                company_id, reason="not_a_fit",
                detail="Prospect replied: not a fit",
                excluded_by="reply_classifier",
            )
        except Exception as e:
            logger.warning("Could not add ICP exclusion for company %s: %s", company_id, e)
