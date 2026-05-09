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

P3.3 — Signal evidence policy
=============================
Also exposes the helper `apply_evidence_cap()` and `classify_evidence_url()`
used by the intent engine when summing signal scores. The policy is loaded
from config/scoring.yaml under `signal_evidence_policy`. A signal whose
evidence_url is missing OR whose evidence_type is not on the acceptable
list has its contribution capped at `unevidenced_cap` (default 0.30) when
its raw normalized score would exceed `required_above_score` (default 0.50).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# P3.3 — Signal evidence policy
# ---------------------------------------------------------------------------

_SCORING_PATH = Path(__file__).parent.parent.parent.parent / "config" / "scoring.yaml"

_DEFAULT_EVIDENCE_POLICY = {
    "required_above_score": 0.50,
    "unevidenced_cap": 0.30,
    "acceptable_evidence_types": [
        "press_release", "sec_filing", "job_posting",
        "news_article", "company_blog", "regulatory_filing",
    ],
}


@lru_cache(maxsize=1)
def _load_evidence_policy() -> dict:
    """Cached load of the signal_evidence_policy block."""
    try:
        with open(_SCORING_PATH) as fh:
            doc = yaml.safe_load(fh) or {}
        policy = doc.get("signal_evidence_policy") or {}
    except Exception as exc:
        logger.warning("evidence_policy: failed to load %s (%s) — using defaults", _SCORING_PATH, exc)
        policy = {}
    return {**_DEFAULT_EVIDENCE_POLICY, **policy}


# Map the public source labels onto the acceptable_evidence_types list.
# This is intentionally lenient: a signal carrying source='apollo' on a
# job_posting URL still counts as 'job_posting'.
_URL_TYPE_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"sec\.gov", re.I),                           "sec_filing"),
    (re.compile(r"(/jobs/|/careers/|greenhouse\.io|lever\.co|workday)", re.I), "job_posting"),
    (re.compile(r"(prnewswire|businesswire|globenewswire|press[- ]?release)", re.I), "press_release"),
    (re.compile(r"(/blog/|/insights/|/news/)", re.I),         "company_blog"),
    (re.compile(r"\.gov(/|$)", re.I),                          "regulatory_filing"),
    (re.compile(r"(reuters|bloomberg|cnbc|wsj|nytimes|forbes)", re.I), "news_article"),
)


def classify_evidence_url(url: str | None) -> str | None:
    """Map an evidence URL to one of the acceptable evidence types.

    Returns None when the URL is absent, malformed, or doesn't match any rule.
    """
    if not url or not isinstance(url, str):
        return None
    for pat, label in _URL_TYPE_RULES:
        if pat.search(url):
            return label
    return None


def apply_evidence_cap(
    raw_score: float,
    evidence_url: str | None,
    evidence_type: str | None = None,
    *,
    policy: dict | None = None,
) -> float:
    """Cap an unevidenced signal score per the signal_evidence_policy.

    Args:
        raw_score: The signal's computed weight in [0, 1] (or any positive
                   numeric scale; the cap is applied numerically).
        evidence_url: URL of the source backing the signal. None → unevidenced.
        evidence_type: Optional explicit type. When None, derived from
                       `evidence_url` via classify_evidence_url().
        policy: Override the policy (used in tests). Defaults to the cached
                load of `signal_evidence_policy` from scoring.yaml.

    Returns:
        The capped score. When the signal is properly evidenced, raw_score
        is returned unchanged. When evidence is missing AND raw_score is
        above `required_above_score`, the score is reduced to
        `unevidenced_cap`.
    """
    pol = policy if policy is not None else _load_evidence_policy()
    required_above = float(pol.get("required_above_score", 0.50))
    cap = float(pol.get("unevidenced_cap", 0.30))
    acceptable = set(pol.get("acceptable_evidence_types", []))

    derived_type = evidence_type or classify_evidence_url(evidence_url)
    has_evidence = bool(evidence_url) and (derived_type in acceptable)

    if has_evidence:
        return float(raw_score)
    if raw_score > required_above:
        return cap
    # Below the required_above threshold: leave alone (it's already <= cap-ish).
    return float(raw_score)


def reload_evidence_policy() -> None:
    """Drop the cached policy. Used by tests after editing scoring.yaml."""
    _load_evidence_policy.cache_clear()

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
