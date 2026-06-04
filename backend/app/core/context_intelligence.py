"""Context Intelligence Layer — assembles a ContextPacket before every decision.

SHADOW MODE: ContextPacketBuilder is ready to use but is not wired into any
production path yet. Do not call it from approve, generate, send, or webhook
handlers until PR F explicitly authorises the wiring. This file is PR E scope:
assembly, persistence, and tests only.

Usage (shadow / evaluation):
    from backend.app.core.context_intelligence import ContextPacketBuilder

    builder = ContextPacketBuilder(db)
    packet = builder.build(
        contact_id="...",
        company_id="...",
        purpose="draft_generation",
        sequence_name="step1_manufacturing_ops",
        sequence_step=1,
    )
    # packet.prohibited_claims — angles that must not repeat
    # packet.suppression_status — governance gate
    # packet.company_locked — whether outreach to this company is paused
    # packet.id — UUID written to context_packets (None if persist failed)

Design principles:
  - Each DB query is independent; a failure yields a safe default and appends
    to packet.assembly_errors rather than aborting the whole build.
  - UUID inputs are validated before use in .or_() filter strings so malformed
    values cannot produce syntactically broken PostgREST queries.
  - workspace_id is nullable in context_packets. If it cannot be resolved, a
    WARNING is logged and the packet is persisted with workspace_id=NULL. It
    remains usable and queryable via service-role; it is simply absent from
    tenant-scoped RLS views until workspace_id is backfilled.
  - content_hash lets callers skip re-assembly when a recent packet for the
    same (contact, purpose, step) is within TTL.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UUID validation
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_valid_uuid(value: str | None) -> bool:
    """Return True only if value is a well-formed UUID string."""
    return bool(value and _UUID_RE.match(str(value)))


# ---------------------------------------------------------------------------
# ContextPacket dataclass
# ---------------------------------------------------------------------------


@dataclass
class ContextPacket:
    """Point-in-time snapshot of everything relevant to a draft decision.

    Fields are populated by ContextPacketBuilder.build(). Fields that could
    not be loaded from DB fall back to empty / False / "none" and the failure
    is recorded in assembly_errors.
    """

    # Identity
    id: str | None = None  # UUID assigned after DB write; None if persist failed
    workspace_id: str = ""
    purpose: str = ""  # draft_generation | approval | send | risk_score
    draft_id: str | None = None
    contact_id: str | None = None
    company_id: str | None = None
    schema_version: int = 1

    # ---- Contact snapshot ----
    contact_snapshot: dict = field(default_factory=dict)
    # keys: full_name, email, linkedin_url, seniority, title, department,
    #       reply_sentiment, linkedin_status, has_email, has_linkedin

    # ---- Company snapshot ----
    company_snapshot: dict = field(default_factory=dict)
    # keys: name, domain, employee_count, headcount_growth_6m, industry,
    #       tier, status, intent_score, assigned_persona

    # ---- Outreach history ----
    prior_messages: list[dict] = field(default_factory=list)
    # [{draft_id, step, channel, subject, sent_at, primary_angle}]

    sibling_contact_history: list[dict] = field(default_factory=list)
    # other contacts at this company who received outreach; prevents duplicate angles

    reply_history: list[dict] = field(default_factory=list)
    # [{contact_id, sentiment, replied_at, body_excerpt}]

    active_conversation: bool = False
    # True if an unresolved reply exists with positive/interested sentiment

    # ---- Governance context ----
    channel_assignment: str = "email"  # email | linkedin | both | none
    channel_reason: str = ""
    company_locked: bool = False
    company_lock_reason: str | None = None
    suppression_status: str = "none"  # none | contact | company | domain | global
    suppression_reason: str | None = None

    # ---- Content guardrails ----
    prohibited_claims: list[str] = field(default_factory=list)
    # Claims that must not appear in the generated draft
    # (prior step angles, retired proof points, etc.)

    registered_claims: list[dict] = field(default_factory=list)
    # [{claim_id, claim_text, source, verified_at}] — validated facts available for use

    # ---- Sequence context ----
    sequence_name: str | None = None
    sequence_step: int | None = None
    prior_step_angle: str | None = None  # angle used in step N-1; step N must not repeat

    # ---- Risk indicators (pre-score) ----
    traction_signal: str = "none"  # none | warm | active_reply | meeting_booked
    is_first_touch: bool = True
    days_since_last_touch: int | None = None

    # ---- Meta ----
    content_hash: str = ""  # SHA-256 over decision-relevant fields
    assembled_at: str = ""
    ttl_seconds: int = 300
    assembly_errors: list[str] = field(default_factory=list)
    # Field names that fell back to defaults due to DB errors


# ---------------------------------------------------------------------------
# ContextPacketBuilder
# ---------------------------------------------------------------------------


class ContextPacketBuilder:
    """Assembles a ContextPacket from live DB state and writes it to context_packets.

    SHADOW MODE — not called from any production path (approval, generation,
    send, or webhook handlers). The builder is exercised only by tests and
    explicit evaluation scripts until PR F wires it in.
    """

    def __init__(self, db: "Database"):
        self.db = db

    def build(
        self,
        contact_id: str,
        company_id: str | None,
        purpose: str,
        sequence_name: str | None = None,
        sequence_step: int | None = None,
        draft_id: str | None = None,
        workspace_id: str | None = None,
    ) -> ContextPacket:
        """Assemble, store, and return a ContextPacket.

        Each field is assembled independently — a DB failure on one field
        appends to assembly_errors and returns a safe default rather than
        aborting the whole build.
        """
        now = datetime.now(timezone.utc)
        packet = ContextPacket(
            purpose=purpose,
            contact_id=contact_id,
            company_id=company_id,
            draft_id=draft_id,
            sequence_name=sequence_name,
            sequence_step=sequence_step,
            assembled_at=now.isoformat(),
        )
        errors: list[str] = []

        # 1. Contact snapshot
        contact = self._load_contact(contact_id, errors)
        if contact:
            packet.contact_snapshot = {
                "full_name": contact.get("full_name"),
                "email": contact.get("email"),
                "linkedin_url": contact.get("linkedin_url"),
                "seniority": contact.get("seniority"),
                "title": contact.get("title"),
                "department": contact.get("department"),
                "reply_sentiment": contact.get("reply_sentiment"),
                "linkedin_status": contact.get("linkedin_status"),
                "has_email": bool(contact.get("email")),
                "has_linkedin": bool(contact.get("linkedin_url")),
            }
            if not workspace_id:
                workspace_id = str(contact.get("workspace_id") or "")

        packet.workspace_id = workspace_id or ""
        if not packet.workspace_id:
            logger.warning(
                "context_intelligence: context packet for contact=%s company=%s "
                "purpose=%s has no workspace_id — persisting with workspace_id=NULL. "
                "The row will not appear in tenant-scoped RLS views until backfilled.",
                contact_id,
                company_id,
                purpose,
            )

        # 2. Company snapshot
        company = None
        if company_id:
            company = self._load_company(company_id, errors)
            if company:
                packet.company_snapshot = {
                    "name": company.get("name"),
                    "domain": company.get("domain"),
                    "employee_count": company.get("employee_count"),
                    "headcount_growth_6m": company.get("headcount_growth_6m"),
                    "industry": company.get("industry"),
                    "tier": company.get("tier"),
                    "status": company.get("status"),
                    "intent_score": company.get("intent_score"),
                    "assigned_persona": company.get("assigned_persona"),
                }

        # 3. Channel assignment
        try:
            from backend.app.core.channel_coordinator import get_active_channel

            channel, reason = get_active_channel(self.db, contact_id)
            packet.channel_assignment = channel
            packet.channel_reason = reason or ""
        except Exception as exc:
            errors.append(f"channel_assignment:{exc}")

        # 4. Company lock
        if company_id:
            try:
                from backend.app.core.channel_coordinator import is_company_locked

                locked, lock_reason = is_company_locked(
                    self.db, company_id, exclude_contact_id=contact_id
                )
                packet.company_locked = locked
                packet.company_lock_reason = lock_reason
            except Exception as exc:
                errors.append(f"company_lock:{exc}")

        # 5. Suppression status — UUID-validated before use in .or_() filter
        self._load_suppression(contact_id, contact, company_id, packet, errors)

        # 6. Prior messages and first-touch detection
        packet.prior_messages = self._load_prior_messages(contact_id, errors)
        packet.is_first_touch = len(packet.prior_messages) == 0

        if packet.prior_messages:
            last_msg = packet.prior_messages[-1]
            last_sent_raw = last_msg.get("sent_at")
            if last_sent_raw:
                try:
                    last_sent = datetime.fromisoformat(last_sent_raw.replace("Z", "+00:00"))
                    packet.days_since_last_touch = (now - last_sent).days
                except (ValueError, AttributeError):
                    pass

        # 7. Prior step angle — step N must not repeat step N-1's angle
        if sequence_name and sequence_step and sequence_step > 1:
            packet.prior_step_angle = self._get_prior_angle(
                contact_id, sequence_name, sequence_step - 1, errors
            )
            if packet.prior_step_angle:
                packet.prohibited_claims.append(
                    f"primary_angle_from_step_{sequence_step - 1}:{packet.prior_step_angle}"
                )

        # 8. Reply history and active-conversation detection
        packet.reply_history = self._load_reply_history(contact_id, errors)
        if packet.reply_history:
            _active_sentiments = {"interested", "positive", "question", "maybe"}
            for reply in packet.reply_history:
                if (reply.get("sentiment") or "").lower() in _active_sentiments:
                    packet.active_conversation = True
                    break

        # 9. Sibling contact history (prevents duplicate angles across contacts)
        if company_id:
            packet.sibling_contact_history = self._load_sibling_history(
                company_id, contact_id, errors
            )

        # 10. Traction signal
        if company_id:
            try:
                from backend.app.core.channel_coordinator import get_company_traction

                traction = get_company_traction(self.db, company_id, exclude_contact_id=contact_id)
                if traction.get("has_traction"):
                    packet.traction_signal = "warm"
            except Exception as exc:
                errors.append(f"traction:{exc}")

        if packet.active_conversation:
            # Active reply supersedes warm traction signal
            packet.traction_signal = "active_reply"

        packet.assembly_errors = errors

        # 11. Content hash over decision-relevant fields
        packet.content_hash = self._hash(packet)

        # 12. Persist to DB — non-fatal; packet is usable even if persist fails
        try:
            packet.id = self._persist(packet)
        except Exception as exc:
            logger.warning(
                "context_intelligence: failed to persist packet for contact=%s: %s",
                contact_id,
                exc,
            )

        return packet

    # ------------------------------------------------------------------
    # Private loaders — each independent, each catches its own exceptions
    # ------------------------------------------------------------------

    def _load_contact(self, contact_id: str, errors: list[str]) -> dict | None:
        try:
            result = (
                self.db.client.table("contacts")
                .select(
                    "id, workspace_id, full_name, email, linkedin_url, seniority, "
                    "title, department, reply_sentiment, linkedin_status, company_id"
                )
                .eq("id", contact_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            errors.append(f"contact_load:{exc}")
            return None

    def _load_company(self, company_id: str, errors: list[str]) -> dict | None:
        try:
            result = (
                self.db.client.table("companies")
                .select(
                    "id, name, domain, employee_count, headcount_growth_6m, "
                    "industry, tier, status, intent_score, assigned_persona"
                )
                .eq("id", company_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            errors.append(f"company_load:{exc}")
            return None

    def _load_suppression(
        self,
        contact_id: str,
        contact: dict | None,
        company_id: str | None,
        packet: ContextPacket,
        errors: list[str],
    ) -> None:
        """Load active suppression entries. UUIDs are validated before use in .or_() filters."""
        filter_parts: list[str] = []

        if _is_valid_uuid(contact_id):
            filter_parts.append(f"contact_id.eq.{contact_id}")
        else:
            errors.append(f"suppression:invalid_contact_uuid:{contact_id!r}")

        if company_id is not None:
            if _is_valid_uuid(company_id):
                filter_parts.append(f"company_id.eq.{company_id}")
            else:
                errors.append(f"suppression:invalid_company_uuid:{company_id!r}")

        if not filter_parts:
            return

        try:
            rows = (
                self.db.client.table("suppression_log")
                .select("scope, reason, active")
                .or_(",".join(filter_parts))
                .eq("active", True)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
                .data
            ) or []
            if rows:
                worst = rows[0]
                packet.suppression_status = worst.get("scope") or "contact"
                packet.suppression_reason = worst.get("reason")
        except Exception as exc:
            errors.append(f"suppression:{exc}")

    def _load_prior_messages(self, contact_id: str, errors: list[str]) -> list[dict]:
        try:
            rows = (
                self.db.client.table("outreach_drafts")
                .select(
                    "id, sequence_name, sequence_step, channel, subject, "
                    "sent_at, personalization_notes"
                )
                .eq("contact_id", contact_id)
                .not_.is_("sent_at", "null")
                .order("sequence_step", desc=False)
                .order("sent_at", desc=False)
                .limit(10)
                .execute()
                .data
            ) or []
            return [
                {
                    "draft_id": r["id"],
                    "step": r.get("sequence_step"),
                    "channel": r.get("channel"),
                    "subject": r.get("subject"),
                    "sent_at": r.get("sent_at"),
                    "primary_angle": ((r.get("personalization_notes") or "").split("\n")[0][:200]),
                }
                for r in rows
            ]
        except Exception as exc:
            errors.append(f"prior_messages:{exc}")
            return []

    def _get_prior_angle(
        self,
        contact_id: str,
        sequence_name: str,
        step: int,
        errors: list[str],
    ) -> str | None:
        try:
            rows = (
                self.db.client.table("outreach_drafts")
                .select("personalization_notes")
                .eq("contact_id", contact_id)
                .eq("sequence_name", sequence_name)
                .eq("sequence_step", step)
                .not_.is_("sent_at", "null")
                .order("sent_at", desc=True)
                .limit(1)
                .execute()
                .data
            ) or []
            if rows:
                notes = rows[0].get("personalization_notes") or ""
                return notes.split("\n")[0][:200] or None
        except Exception as exc:
            errors.append(f"prior_angle:{exc}")
        return None

    def _load_reply_history(self, contact_id: str, errors: list[str]) -> list[dict]:
        try:
            rows = (
                self.db.client.table("interactions")
                .select("type, created_at, metadata")
                .eq("contact_id", contact_id)
                .in_("type", ["email_replied", "linkedin_message"])
                .order("created_at", desc=True)
                .limit(5)
                .execute()
                .data
            ) or []
            return [
                {
                    "contact_id": contact_id,
                    "sentiment": (r.get("metadata") or {}).get("sentiment"),
                    "replied_at": r.get("created_at"),
                    "body_excerpt": ((r.get("metadata") or {}).get("body_excerpt", "")[:200]),
                }
                for r in rows
            ]
        except Exception as exc:
            errors.append(f"reply_history:{exc}")
            return []

    def _load_sibling_history(
        self,
        company_id: str,
        exclude_contact_id: str,
        errors: list[str],
    ) -> list[dict]:
        try:
            contacts = (
                self.db.client.table("contacts")
                .select("id, full_name")
                .eq("company_id", company_id)
                .neq("id", exclude_contact_id)
                .limit(20)
                .execute()
                .data
            ) or []
            if not contacts:
                return []
            sibling_ids = [c["id"] for c in contacts]
            name_map = {c["id"]: c.get("full_name", "") for c in contacts}

            drafts = (
                self.db.client.table("outreach_drafts")
                .select("contact_id, sequence_step, sent_at, subject")
                .in_("contact_id", sibling_ids)
                .not_.is_("sent_at", "null")
                .order("sent_at", desc=True)
                .limit(20)
                .execute()
                .data
            ) or []
            return [
                {
                    "contact_id": d["contact_id"],
                    "contact_name": name_map.get(d["contact_id"], ""),
                    "step": d.get("sequence_step"),
                    "sent_at": d.get("sent_at"),
                    "subject": d.get("subject"),
                }
                for d in drafts
            ]
        except Exception as exc:
            errors.append(f"sibling_history:{exc}")
            return []

    @staticmethod
    def _hash(packet: ContextPacket) -> str:
        fields = {
            "contact_id": packet.contact_id,
            "company_id": packet.company_id,
            "sequence_name": packet.sequence_name,
            "sequence_step": packet.sequence_step,
            "company_locked": packet.company_locked,
            "suppression_status": packet.suppression_status,
            "active_conversation": packet.active_conversation,
            "traction_signal": packet.traction_signal,
            "prior_step_angle": packet.prior_step_angle,
            "prohibited_claims": packet.prohibited_claims,
        }
        raw = json.dumps(fields, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _persist(self, packet: ContextPacket) -> str | None:
        """Insert the packet into context_packets. Returns the UUID or None."""
        row: dict[str, Any] = {
            "purpose": packet.purpose,
            "schema_version": packet.schema_version,
            "content_hash": packet.content_hash,
            "contact_snapshot": packet.contact_snapshot,
            "company_snapshot": packet.company_snapshot,
            "prior_messages": packet.prior_messages,
            "sibling_contact_history": packet.sibling_contact_history,
            "reply_history": packet.reply_history,
            "active_conversation": packet.active_conversation,
            "channel_assignment": packet.channel_assignment,
            "channel_reason": packet.channel_reason,
            "company_locked": packet.company_locked,
            "company_lock_reason": packet.company_lock_reason,
            "suppression_status": packet.suppression_status,
            "suppression_reason": packet.suppression_reason,
            "prohibited_claims": packet.prohibited_claims,
            "registered_claims": packet.registered_claims,
            "sequence_name": packet.sequence_name,
            "sequence_step": packet.sequence_step,
            "prior_step_angle": packet.prior_step_angle,
            "traction_signal": packet.traction_signal,
            "is_first_touch": packet.is_first_touch,
            "days_since_last_touch": packet.days_since_last_touch,
            "ttl_seconds": packet.ttl_seconds,
        }
        # Optional FK fields — only include when the value is a valid UUID
        if _is_valid_uuid(packet.workspace_id):
            row["workspace_id"] = packet.workspace_id
        # workspace_id omitted → column is NULL (allowed by migration 052)

        if _is_valid_uuid(packet.draft_id):
            row["draft_id"] = packet.draft_id
        if _is_valid_uuid(packet.contact_id):
            row["contact_id"] = packet.contact_id
        if _is_valid_uuid(packet.company_id):
            row["company_id"] = packet.company_id

        result = self.db.client.table("context_packets").insert(row).execute()
        return result.data[0]["id"] if result.data else None
