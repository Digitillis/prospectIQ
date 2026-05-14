"""Context Intelligence Layer — assembles a ContextPacket before every decision.

Every draft generation, approval decision, and outbound send should call
ContextPacketBuilder.build() first. The packet captures a consistent snapshot
of everything relevant at decision time and writes it to context_packets so
the decision is permanently explainable.

Usage:
    builder = ContextPacketBuilder(db)
    packet = builder.build(
        contact_id="...",
        company_id="...",
        purpose="draft_generation",
        sequence_name="step1_manufacturing_ops",
        sequence_step=1,
        draft_id=None,  # set after draft is created
    )
    # packet.prohibited_claims, packet.prior_step_angle, packet.company_locked, etc.
    # packet.id is stored in context_packets and can be referenced by workflow_events

Design notes:
- Each DB query is run independently; a failure returns a safe default rather than
  crashing the whole assembly. The packet records which fields came from live data
  vs safe defaults.
- The content_hash enables callers to skip re-assembly when a recent packet for
  the same (contact, purpose, step) is still within TTL.
- Shadow mode: the packet is always assembled and stored, even if the calling
  code currently ignores some fields. This lets us compare the packet's picture
  of the world against current behavior without changing send logic yet.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import Database
from backend.app.core.channel_coordinator import (
    get_active_channel,
    is_company_locked,
    get_company_traction,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ContextPacket:
    """Point-in-time snapshot of everything relevant to a draft decision."""

    # Identity
    id: str | None = None                      # UUID assigned after DB write
    workspace_id: str = ""
    purpose: str = ""                          # draft_generation | approval | send | risk_score
    draft_id: str | None = None
    contact_id: str | None = None
    company_id: str | None = None
    schema_version: int = 1

    # Contact
    contact_snapshot: dict = field(default_factory=dict)
    # full_name, email, linkedin_url, seniority, title, department,
    # reply_sentiment, linkedin_status, has_email, has_linkedin

    # Company
    company_snapshot: dict = field(default_factory=dict)
    # name, domain, employee_count, headcount_growth_6m, industry,
    # tier, status, intent_score, assigned_persona

    # Outreach history
    prior_messages: list[dict] = field(default_factory=list)
    # [{step, channel, subject, sent_at, primary_angle, draft_id}]

    sibling_contact_history: list[dict] = field(default_factory=list)
    # other contacts at this company who received outreach

    reply_history: list[dict] = field(default_factory=list)
    # [{contact_id, sentiment, replied_at, body_excerpt}]

    active_conversation: bool = False

    # Governance
    channel_assignment: str = "email"
    channel_reason: str = ""
    company_locked: bool = False
    company_lock_reason: str | None = None
    suppression_status: str = "none"          # none | contact | company | domain | global
    suppression_reason: str | None = None

    # Content guardrails
    prohibited_claims: list[str] = field(default_factory=list)
    registered_claims: list[dict] = field(default_factory=list)
    # [{claim_id, claim_text, source, verified_at}]

    # Sequence context
    sequence_name: str | None = None
    sequence_step: int | None = None
    prior_step_angle: str | None = None

    # Risk indicators (pre-score)
    traction_signal: str = "none"             # none | warm | active_reply | meeting_booked
    is_first_touch: bool = True
    days_since_last_touch: int | None = None

    # Meta
    content_hash: str = ""
    assembled_at: str = ""
    ttl_seconds: int = 300
    assembly_errors: list[str] = field(default_factory=list)
    # fields that fell back to defaults due to DB errors


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class ContextPacketBuilder:
    """Assembles a ContextPacket from live DB state and writes it to context_packets."""

    def __init__(self, db: Database):
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
        returns a safe default rather than aborting the whole packet.
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
            channel, reason = get_active_channel(self.db, contact_id)
            packet.channel_assignment = channel
            packet.channel_reason = reason or ""
        except Exception as exc:
            errors.append(f"channel_assignment:{exc}")

        # 4. Company lock
        if company_id:
            try:
                locked, lock_reason = is_company_locked(
                    self.db, company_id, exclude_contact_id=contact_id
                )
                packet.company_locked = locked
                packet.company_lock_reason = lock_reason
            except Exception as exc:
                errors.append(f"company_lock:{exc}")

        # 5. Suppression status
        self._load_suppression(contact_id, contact, company_id, packet, errors)

        # 6. Prior messages for this contact
        packet.prior_messages = self._load_prior_messages(contact_id, errors)
        packet.is_first_touch = len(packet.prior_messages) == 0

        if packet.prior_messages:
            last_msg = packet.prior_messages[-1]
            last_sent_raw = last_msg.get("sent_at")
            if last_sent_raw:
                try:
                    last_sent = datetime.fromisoformat(
                        last_sent_raw.replace("Z", "+00:00")
                    )
                    packet.days_since_last_touch = (now - last_sent).days
                except (ValueError, AttributeError):
                    pass

        # 7. Prior step angle (step N must not repeat step N-1's angle)
        if sequence_name and sequence_step and sequence_step > 1:
            packet.prior_step_angle = self._get_prior_angle(
                contact_id, sequence_name, sequence_step - 1, errors
            )
            if packet.prior_step_angle:
                packet.prohibited_claims.append(
                    f"primary_angle_from_step_{sequence_step - 1}:{packet.prior_step_angle}"
                )

        # 8. Reply history
        packet.reply_history = self._load_reply_history(contact_id, errors)
        if packet.reply_history:
            active_sentiments = {"interested", "positive", "question", "maybe"}
            for reply in packet.reply_history:
                if (reply.get("sentiment") or "").lower() in active_sentiments:
                    packet.active_conversation = True
                    break

        # 9. Sibling contact history
        if company_id:
            packet.sibling_contact_history = self._load_sibling_history(
                company_id, contact_id, errors
            )

        # 10. Traction signal
        if company_id:
            try:
                traction = get_company_traction(
                    self.db, company_id, exclude_contact_id=contact_id
                )
                if traction.get("has_traction"):
                    packet.traction_signal = "warm"
            except Exception as exc:
                errors.append(f"traction:{exc}")

        if packet.active_conversation:
            packet.traction_signal = "active_reply"

        packet.assembly_errors = errors

        # 11. Content hash over the fields that affect draft generation
        packet.content_hash = self._hash(packet)

        # 12. Write to DB and capture assigned UUID
        try:
            packet.id = self._persist(packet)
        except Exception as exc:
            logger.warning("context_intelligence: failed to persist packet: %s", exc)
            # Non-fatal — the packet is still usable; just won't be stored

        return packet

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_contact(self, contact_id: str, errors: list[str]) -> dict | None:
        try:
            result = (
                self.db.client.table("contacts")
                .select(
                    "id, workspace_id, full_name, email, linkedin_url, seniority, "
                    "title, department, reply_sentiment, linkedin_status, has_email, "
                    "company_id"
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
        try:
            rows = (
                self.db.client.table("suppression_log")
                .select("scope, reason, active")
                .or_(
                    f"contact_id.eq.{contact_id}"
                    + (f",company_id.eq.{company_id}" if company_id else "")
                )
                .eq("active", True)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
                .data
            )
            if rows:
                worst = rows[0]
                packet.suppression_status = worst.get("scope", "contact")
                packet.suppression_reason = worst.get("reason")
        except Exception as exc:
            errors.append(f"suppression:{exc}")

        # Also check linkedin_status for warm intro
        if contact:
            ls = (contact.get("linkedin_status") or "").lower()
            if "warm" in ls and packet.suppression_status == "none":
                packet.suppression_status = "contact"
                packet.suppression_reason = f"warm_intro_in_progress:{ls}"

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
            )
            return [
                {
                    "draft_id": r["id"],
                    "step": r.get("sequence_step"),
                    "channel": r.get("channel"),
                    "subject": r.get("subject"),
                    "sent_at": r.get("sent_at"),
                    "primary_angle": (r.get("personalization_notes") or "").split("\n")[0][:200],
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
                .select("personalization_notes, body")
                .eq("contact_id", contact_id)
                .eq("sequence_name", sequence_name)
                .eq("sequence_step", step)
                .not_.is_("sent_at", "null")
                .order("sent_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
            if rows:
                notes = rows[0].get("personalization_notes") or ""
                return notes.split("\n")[0][:200] if notes else None
        except Exception as exc:
            errors.append(f"prior_angle:{exc}")
        return None

    def _load_reply_history(
        self, contact_id: str, errors: list[str]
    ) -> list[dict]:
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
            )
            return [
                {
                    "contact_id": contact_id,
                    "sentiment": (r.get("metadata") or {}).get("sentiment"),
                    "replied_at": r.get("created_at"),
                    "body_excerpt": (r.get("metadata") or {}).get("body_excerpt", "")[:200],
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
            )
            if not contacts:
                return []
            sibling_ids = [c["id"] for c in contacts]
            contact_map = {c["id"]: c.get("full_name", "") for c in contacts}

            drafts = (
                self.db.client.table("outreach_drafts")
                .select("contact_id, sequence_step, sent_at, subject")
                .in_("contact_id", sibling_ids)
                .not_.is_("sent_at", "null")
                .order("sent_at", desc=True)
                .limit(20)
                .execute()
                .data
            )
            return [
                {
                    "contact_id": d["contact_id"],
                    "contact_name": contact_map.get(d["contact_id"], ""),
                    "step": d.get("sequence_step"),
                    "sent_at": d.get("sent_at"),
                    "subject": d.get("subject"),
                }
                for d in drafts
            ]
        except Exception as exc:
            errors.append(f"sibling_history:{exc}")
            return []

    def _hash(self, packet: ContextPacket) -> str:
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
        """Write the packet to the context_packets table. Returns the UUID."""
        row = {
            "workspace_id": packet.workspace_id or None,
            "purpose": packet.purpose,
            "schema_version": packet.schema_version,
            "content_hash": packet.content_hash,
            "draft_id": packet.draft_id or None,
            "contact_id": packet.contact_id or None,
            "company_id": packet.company_id or None,
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
        # Strip None workspace_id — Supabase rejects NULL UUIDs in RLS policies
        if not row["workspace_id"]:
            row.pop("workspace_id")

        result = self.db.client.table("context_packets").insert(row).execute()
        if result.data:
            return result.data[0]["id"]
        return None


# ---------------------------------------------------------------------------
# Convenience: write a workflow_event alongside any state transition
# ---------------------------------------------------------------------------

def emit_workflow_event(
    db: Database,
    *,
    workspace_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    from_state: str | None = None,
    to_state: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    triggered_by: str | None = None,
    context_packet_id: str | None = None,
    policy_snapshot_id: str | None = None,
    metadata: dict | None = None,
) -> str | None:
    """Write a single row to workflow_events. Returns the event UUID.

    Call this every time approval_status, sent_at, or suppression state changes.
    Non-fatal: logs on failure rather than propagating the exception so callers
    don't need try/except around every state transition.
    """
    try:
        row: dict[str, Any] = {
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "actor_type": actor_type,
            "metadata": metadata or {},
        }
        if from_state is not None:
            row["from_state"] = from_state
        if to_state is not None:
            row["to_state"] = to_state
        if actor_id is not None:
            row["actor_id"] = actor_id
        if triggered_by is not None:
            row["triggered_by"] = triggered_by
        if context_packet_id is not None:
            row["context_packet_id"] = context_packet_id
        if policy_snapshot_id is not None:
            row["policy_snapshot_id"] = policy_snapshot_id

        result = db.client.table("workflow_events").insert(row).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as exc:
        logger.warning(
            "context_intelligence: failed to emit workflow_event %s for %s %s: %s",
            event_type, entity_type, entity_id, exc,
        )
    return None


def get_latest_policy_snapshot(db: Database, workspace_id: str) -> dict | None:
    """Return the most recent policy_snapshot payload for this workspace."""
    try:
        result = (
            db.client.table("policy_snapshots")
            .select("id, payload, version, created_at")
            .eq("workspace_id", workspace_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def capture_policy_snapshot(db: Database, workspace_id: str, payload: dict, changed_by: str = "system", reason: str | None = None) -> str | None:
    """Create a new policy_snapshot from the current limits config.

    Call this whenever limits.yaml is reloaded or outreach_send_config changes.
    Returns the new snapshot UUID.
    """
    try:
        # Get current version number
        latest = get_latest_policy_snapshot(db, workspace_id)
        next_version = (latest["version"] + 1) if latest else 1

        result = (
            db.client.table("policy_snapshots")
            .insert({
                "workspace_id": workspace_id,
                "version": next_version,
                "sources": payload.get("_sources", ["unknown"]),
                "payload": payload,
                "change_reason": reason,
                "changed_by": changed_by,
            })
            .execute()
        )
        return result.data[0]["id"] if result.data else None
    except Exception as exc:
        logger.warning("context_intelligence: failed to capture policy snapshot: %s", exc)
        return None
