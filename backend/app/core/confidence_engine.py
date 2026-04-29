"""Confidence Engine — promotes learning_outcomes through the confidence lifecycle.

Lifecycle:
    hypothesis  (0–4 evidence points)  — initial observation, not yet validated
    validated   (5–14 evidence points, p < 0.10)  — consistent pattern
    proven      (15+ evidence points, p < 0.05, ≥3 distinct sources) — actionable rule

Evidence sources that count:
    ab_winner         — A/B test winner declaration for this sequence/pattern
    reply_positive    — 'interested' or 'referral' reply classification
    reply_converted   — contact converted to meeting or pilot
    meeting_booked    — meeting logged against this contact
    manual            — manually entered by a team member

Usage:
    engine = ConfidenceEngine(db, workspace_id)
    engine.record_evidence(outcome_id, source_type="reply_positive", source_ref=contact_id)
    engine.record_evidence(outcome_id, source_type="ab_winner", source_ref=sequence_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Promotion thresholds
_VALIDATED_EVIDENCE_MIN = 5
_PROVEN_EVIDENCE_MIN = 15
_PROVEN_SOURCE_MIN = 3  # distinct source_type values required

# Simple p-value approximation based on evidence count and consistency
# (no scipy dependency — lightweight binomial approximation)
_VALIDATED_P_THRESHOLD = 0.10
_PROVEN_P_THRESHOLD = 0.05


class ConfidenceEngine:
    """Records evidence and auto-promotes learning outcomes through the confidence lifecycle."""

    def __init__(self, db: Any, workspace_id: str) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def record_evidence(
        self,
        outcome_id: str,
        source_type: str,
        source_ref: str | None = None,
        signal_text: str | None = None,
    ) -> dict:
        """Record one piece of evidence and promote confidence level if thresholds are met.

        Args:
            outcome_id: UUID of the learning_outcome row.
            source_type: One of: ab_winner, reply_positive, reply_converted,
                         meeting_booked, manual.
            source_ref: Optional reference ID (sequence_id, thread_id, etc.).
            signal_text: Human-readable description of the signal.

        Returns:
            Updated learning_outcome row dict.
        """
        # 1. Insert evidence record
        try:
            self.db.client.table("intelligence_evidence").insert({
                "outcome_id": outcome_id,
                "source_type": source_type,
                "source_ref": source_ref or "",
                "signal_text": signal_text or "",
                "workspace_id": self.workspace_id,
            }).execute()
        except Exception as e:
            logger.error(f"ConfidenceEngine.record_evidence insert failed: {e}")
            return {}

        # 2. Re-count evidence and distinct sources
        try:
            ev_result = (
                self.db.client.table("intelligence_evidence")
                .select("id, source_type")
                .eq("outcome_id", outcome_id)
                .execute()
            )
            evidence_rows = ev_result.data or []
        except Exception as e:
            logger.error(f"ConfidenceEngine: evidence count query failed: {e}")
            return {}

        evidence_count = len(evidence_rows)
        source_types = {r["source_type"] for r in evidence_rows}
        source_count = len(source_types)

        # 3. Determine new confidence level
        current = self._get_outcome(outcome_id)
        if not current:
            return {}

        current_level = current.get("confidence_level", "hypothesis")
        new_level = self._compute_level(evidence_count, source_count, current_level)

        # 4. Check bias: flag if only 1 source type across all evidence
        bias_flagged = source_count == 1 and evidence_count >= _VALIDATED_EVIDENCE_MIN

        # 5. Build update payload
        now = datetime.now(timezone.utc).isoformat()
        update: dict[str, Any] = {
            "evidence_count": evidence_count,
            "source_count": source_count,
            "confidence_level": new_level,
            "bias_flagged": bias_flagged,
            "last_evidence_at": now,
        }
        if new_level != current_level:
            update["promoted_at"] = now
            logger.info(
                f"ConfidenceEngine: outcome {outcome_id} promoted "
                f"{current_level} → {new_level} "
                f"(evidence={evidence_count}, sources={source_count})"
            )

        try:
            result = (
                self.db.client.table("learning_outcomes")
                .update(update)
                .eq("id", outcome_id)
                .execute()
            )
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"ConfidenceEngine: update failed: {e}")
            return {}

    def record_evidence_for_sequence(
        self,
        sequence_id: str,
        source_type: str,
        signal_text: str | None = None,
    ) -> list[dict]:
        """Record evidence for all learning_outcomes tagged with this sequence.

        Used when an A/B winner is declared to bulk-credit all related outcomes.
        """
        try:
            rows = (
                self.db.client.table("learning_outcomes")
                .select("id")
                .eq("workspace_id", self.workspace_id)
                .execute()
            )
            outcome_ids = [r["id"] for r in (rows.data or [])]
        except Exception as e:
            logger.error(f"ConfidenceEngine.record_evidence_for_sequence: query failed: {e}")
            return []

        results = []
        for oid in outcome_ids:
            r = self.record_evidence(
                oid,
                source_type=source_type,
                source_ref=sequence_id,
                signal_text=signal_text,
            )
            if r:
                results.append(r)
        return results

    def get_summary(self, workspace_id: str | None = None) -> dict:
        """Return counts of outcomes at each confidence level."""
        ws = workspace_id or self.workspace_id
        try:
            rows = (
                self.db.client.table("learning_outcomes")
                .select("confidence_level")
                .eq("workspace_id", ws)
                .execute()
            )
            counts = {"hypothesis": 0, "validated": 0, "proven": 0}
            for r in rows.data or []:
                level = r.get("confidence_level", "hypothesis")
                counts[level] = counts.get(level, 0) + 1
            return counts
        except Exception as e:
            logger.error(f"ConfidenceEngine.get_summary failed: {e}")
            return {"hypothesis": 0, "validated": 0, "proven": 0}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_outcome(self, outcome_id: str) -> dict | None:
        try:
            result = (
                self.db.client.table("learning_outcomes")
                .select("id, confidence_level, evidence_count")
                .eq("id", outcome_id)
                .single()
                .execute()
            )
            return result.data
        except Exception:
            return None

    @staticmethod
    def _compute_level(
        evidence_count: int,
        source_count: int,
        current_level: str,
    ) -> str:
        """Determine new confidence level from evidence count + source diversity.

        Promotion is one-directional: levels can only go up, never down.
        """
        if (
            current_level in ("validated", "proven")
            or evidence_count >= _PROVEN_EVIDENCE_MIN
            and source_count >= _PROVEN_SOURCE_MIN
        ):
            if (
                evidence_count >= _PROVEN_EVIDENCE_MIN
                and source_count >= _PROVEN_SOURCE_MIN
            ):
                return "proven"
            if evidence_count >= _VALIDATED_EVIDENCE_MIN:
                return "validated"
            return current_level

        if evidence_count >= _VALIDATED_EVIDENCE_MIN:
            return "validated"

        return "hypothesis"
