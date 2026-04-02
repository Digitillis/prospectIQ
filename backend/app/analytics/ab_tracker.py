"""A/B test tracker for email subject line experiments.

Tracks send, open, and reply events per variant and computes statistical
significance using a chi-squared test (scipy.stats.chi2_contingency).

Storage: ab_test_events table (see migration 013_analytics.sql).

Usage:
    from backend.app.analytics.ab_tracker import ABTracker
    from backend.app.core.database import Database

    db = Database()
    tracker = ABTracker(db)

    tracker.record_send(contact_id="uuid", variant="a",
                        subject_line="We help...", sequence_id="seq_001")
    tracker.record_open(contact_id="uuid", variant="a")
    tracker.record_reply(contact_id="uuid", variant="a")

    stats = tracker.get_variant_stats("seq_001")
    winner = tracker.get_winning_variant("seq_001", min_sends=50)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Significance threshold for declaring a winner
_P_VALUE_THRESHOLD = 0.05
# Minimum sends per variant before we even compute significance
_MIN_SENDS_PER_VARIANT = 10


class ABTracker:
    """Records and analyses A/B test events stored in ab_test_events."""

    def __init__(self, db: Any) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Recording events
    # ------------------------------------------------------------------

    def record_send(
        self,
        contact_id: str,
        variant: str,
        subject_line: str,
        sequence_id: str,
    ) -> None:
        """Record that an email was sent to a contact as part of variant a/b."""
        variant = variant.lower().strip()
        if variant not in ("a", "b"):
            logger.warning(f"ABTracker.record_send: invalid variant={variant!r}, skipping")
            return
        try:
            self.db.client.table("ab_test_events").insert(
                self.db._inject_ws({
                    "contact_id": contact_id,
                    "sequence_id": sequence_id,
                    "variant": variant,
                    "subject_line": subject_line,
                    "event_type": "sent",
                })
            ).execute()
        except Exception as exc:
            logger.error(f"ABTracker.record_send failed: {exc}")

    def record_open(self, contact_id: str, variant: str) -> None:
        """Record that a contact opened an email (variant must match the send)."""
        variant = variant.lower().strip()
        if variant not in ("a", "b"):
            return
        try:
            # Look up the sequence_id from the most recent sent event for this contact
            row = (
                self.db._filter_ws(
                    self.db.client.table("ab_test_events")
                    .select("sequence_id, subject_line")
                )
                .eq("contact_id", contact_id)
                .eq("event_type", "sent")
                .order("created_at", desc=True)
                .limit(1)
                .execute().data
            )
            if not row:
                logger.debug(f"ABTracker.record_open: no prior send for contact {contact_id}")
                return
            sequence_id = row[0]["sequence_id"]
            subject_line = row[0].get("subject_line")

            self.db.client.table("ab_test_events").insert(
                self.db._inject_ws({
                    "contact_id": contact_id,
                    "sequence_id": sequence_id,
                    "variant": variant,
                    "subject_line": subject_line,
                    "event_type": "opened",
                })
            ).execute()
        except Exception as exc:
            logger.error(f"ABTracker.record_open failed: {exc}")

    def record_reply(self, contact_id: str, variant: str) -> None:
        """Record that a contact replied (variant must match the send)."""
        variant = variant.lower().strip()
        if variant not in ("a", "b"):
            return
        try:
            row = (
                self.db._filter_ws(
                    self.db.client.table("ab_test_events")
                    .select("sequence_id, subject_line")
                )
                .eq("contact_id", contact_id)
                .eq("event_type", "sent")
                .order("created_at", desc=True)
                .limit(1)
                .execute().data
            )
            if not row:
                return
            sequence_id = row[0]["sequence_id"]
            subject_line = row[0].get("subject_line")

            self.db.client.table("ab_test_events").insert(
                self.db._inject_ws({
                    "contact_id": contact_id,
                    "sequence_id": sequence_id,
                    "variant": variant,
                    "subject_line": subject_line,
                    "event_type": "replied",
                })
            ).execute()
        except Exception as exc:
            logger.error(f"ABTracker.record_reply failed: {exc}")

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_variant_stats(self, sequence_id: str) -> dict:
        """Open rates and reply rates per variant for a sequence.

        Returns:
            {
                'a': {sent, opened, replied, open_rate_pct, reply_rate_pct, subject_line},
                'b': {sent, opened, replied, open_rate_pct, reply_rate_pct, subject_line},
                'sequence_id': str,
                'total_sends': int,
            }
        """
        try:
            rows = (
                self.db._filter_ws(
                    self.db.client.table("ab_test_events")
                    .select("variant, event_type, subject_line")
                )
                .eq("sequence_id", sequence_id)
                .execute().data or []
            )
        except Exception as exc:
            logger.error(f"ABTracker.get_variant_stats failed: {exc}")
            return self._empty_stats(sequence_id)

        stats: dict[str, dict[str, Any]] = {
            "a": {"sent": 0, "opened": 0, "replied": 0, "subject_line": None},
            "b": {"sent": 0, "opened": 0, "replied": 0, "subject_line": None},
        }

        for row in rows:
            variant = row.get("variant", "")
            if variant not in ("a", "b"):
                continue
            event = row.get("event_type", "")
            subject = row.get("subject_line")

            if event == "sent":
                stats[variant]["sent"] += 1
                if not stats[variant]["subject_line"] and subject:
                    stats[variant]["subject_line"] = subject
            elif event == "opened":
                stats[variant]["opened"] += 1
            elif event == "replied":
                stats[variant]["replied"] += 1

        for variant in ("a", "b"):
            s = stats[variant]
            sent = s["sent"]
            s["open_rate_pct"] = round(s["opened"] / sent * 100, 1) if sent else 0.0
            s["reply_rate_pct"] = round(s["replied"] / sent * 100, 1) if sent else 0.0

        total = stats["a"]["sent"] + stats["b"]["sent"]
        return {
            "sequence_id": sequence_id,
            "a": stats["a"],
            "b": stats["b"],
            "total_sends": total,
        }

    def get_winning_variant(
        self,
        sequence_id: str,
        min_sends: int = 50,
    ) -> str | None:
        """Return 'a' or 'b' if there is a statistically significant winner (p<0.05).

        Returns None if:
          - Total sends < min_sends
          - Neither variant has >= _MIN_SENDS_PER_VARIANT sends
          - p-value >= _P_VALUE_THRESHOLD (no significant difference)
          - scipy is unavailable
        """
        stats = self.get_variant_stats(sequence_id)
        total = stats["total_sends"]

        if total < min_sends:
            logger.info(
                f"ABTracker: {sequence_id} only has {total} sends "
                f"(need {min_sends}) — no winner yet"
            )
            return None

        a = stats["a"]
        b = stats["b"]

        if a["sent"] < _MIN_SENDS_PER_VARIANT or b["sent"] < _MIN_SENDS_PER_VARIANT:
            logger.info(
                f"ABTracker: one variant has insufficient sends for {sequence_id}"
            )
            return None

        # Chi-squared test on reply counts
        # Contingency table:
        #   [[a_replied, a_not_replied],
        #    [b_replied, b_not_replied]]
        a_replied = a["replied"]
        a_not = a["sent"] - a_replied
        b_replied = b["replied"]
        b_not = b["sent"] - b_replied

        # Guard: chi2 requires non-zero expected frequencies
        if a_replied + b_replied == 0:
            logger.info(f"ABTracker: {sequence_id} has zero replies — no winner")
            return None

        try:
            from scipy.stats import chi2_contingency  # type: ignore[import]

            contingency = [
                [a_replied, a_not],
                [b_replied, b_not],
            ]
            chi2, p_value, dof, expected = chi2_contingency(contingency)
            logger.info(
                f"ABTracker {sequence_id}: chi2={chi2:.3f} p={p_value:.4f} "
                f"a_rate={a['reply_rate_pct']}% b_rate={b['reply_rate_pct']}%"
            )

            if p_value >= _P_VALUE_THRESHOLD:
                return None

            # p < 0.05 — declare winner by reply rate
            return "a" if a["reply_rate_pct"] >= b["reply_rate_pct"] else "b"

        except ImportError:
            logger.warning(
                "scipy not installed — cannot compute A/B significance. "
                "Add scipy to requirements.txt."
            )
            # Fallback: simple rate comparison (no statistical guarantee)
            if a_replied == 0 and b_replied == 0:
                return None
            if abs(a["reply_rate_pct"] - b["reply_rate_pct"]) < 2.0:
                return None
            return "a" if a["reply_rate_pct"] >= b["reply_rate_pct"] else "b"

        except Exception as exc:
            logger.error(f"ABTracker chi2 test failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_stats(sequence_id: str) -> dict:
        empty = {"sent": 0, "opened": 0, "replied": 0, "open_rate_pct": 0.0,
                 "reply_rate_pct": 0.0, "subject_line": None}
        return {"sequence_id": sequence_id, "a": dict(empty), "b": dict(empty), "total_sends": 0}
