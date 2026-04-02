"""Funnel analytics engine for ProspectIQ.

Computes stage-by-stage funnel metrics from the outreach_state_log and
contacts tables. All queries degrade gracefully on empty tables, returning
zeros rather than errors.

Usage:
    from backend.app.analytics.funnel import FunnelAnalytics
    from backend.app.core.database import Database

    db = Database()
    fa = FunnelAnalytics(db)
    print(fa.get_funnel_counts(days=30))
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# Ordered funnel stages — used for conversion rate computation
_FUNNEL_STAGES = [
    "discovered",
    "enriched",
    "sequenced",
    "touch_1_sent",
    "touch_2_sent",
    "touch_3_sent",
    "touch_4_sent",
    "touch_5_sent",
    "replied",
    "demo_scheduled",
    "closed_won",
]

# States that count as "positive outcome" for a touch step
_TOUCH_STATES = {
    f"touch_{n}_sent" for n in range(1, 7)
}

# Terminal positive states
_POSITIVE_STATES = {"replied", "demo_scheduled", "closed_won"}


def _since_iso(days: int) -> str:
    """ISO timestamp for `days` ago from now."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _safe_div(numerator: float, denominator: float, pct: bool = True) -> float:
    """Safe division returning 0.0 on zero denominator. Optionally returns percentage."""
    if not denominator:
        return 0.0
    result = numerator / denominator
    return round(result * 100, 1) if pct else round(result, 4)


class FunnelAnalytics:
    """Core metrics engine — all data from Supabase via the Database wrapper."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Primary funnel
    # ------------------------------------------------------------------

    def get_funnel_counts(
        self,
        campaign_name: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Stage-by-stage contact counts and conversion rates.

        Returns a dict with:
          - One key per funnel stage with its count
          - 'conversion_rates': dict of stage → % of previous stage that reached it
          - 'total_in_outreach': sum of all touch_N_sent + positive states
          - 'overall_reply_rate': replied / touch_1_sent * 100
        """
        since = _since_iso(days)

        try:
            # Fetch all contacts with their outreach state
            query = self.db._filter_ws(
                self.db.client.table("contacts").select("outreach_state, company_id")
            )
            if campaign_name:
                # Join via companies
                company_ids = self._get_campaign_company_ids(campaign_name)
                if not company_ids:
                    return self._empty_funnel()
                query = query.in_("company_id", company_ids)

            rows = query.execute().data or []
        except Exception as exc:
            logger.error(f"get_funnel_counts query failed: {exc}")
            return self._empty_funnel()

        # Count by state
        state_counts: dict[str, int] = {}
        for row in rows:
            state = row.get("outreach_state") or "unknown"
            state_counts[state] = state_counts.get(state, 0) + 1

        # Aggregate touch states across all steps
        total_touch = sum(
            state_counts.get(f"touch_{n}_sent", 0) for n in range(1, 6)
        )

        result: dict[str, Any] = {}
        for stage in _FUNNEL_STAGES:
            result[stage] = state_counts.get(stage, 0)

        # Include non-positive terminal states in result for completeness
        for extra in ("closed_lost", "nurture", "not_qualified", "dnc"):
            result[extra] = state_counts.get(extra, 0)

        result["total_in_outreach"] = total_touch + sum(
            state_counts.get(s, 0) for s in _POSITIVE_STATES
        )

        # Conversion rates between adjacent funnel stages
        conversion_rates: dict[str, float] = {}
        prev_count = result.get(_FUNNEL_STAGES[0], 0)
        for i, stage in enumerate(_FUNNEL_STAGES[1:], 1):
            conv = _safe_div(result.get(stage, 0), prev_count)
            conversion_rates[f"{_FUNNEL_STAGES[i-1]}_to_{stage}"] = conv
            if result.get(stage, 0) > 0:
                prev_count = result[stage]

        result["conversion_rates"] = conversion_rates
        result["overall_reply_rate"] = _safe_div(
            result.get("replied", 0),
            result.get("touch_1_sent", 0),
        )
        result["demo_from_reply_rate"] = _safe_div(
            result.get("demo_scheduled", 0),
            result.get("replied", 0),
        )
        result["win_rate"] = _safe_div(
            result.get("closed_won", 0),
            result.get("demo_scheduled", 0),
        )

        return result

    # ------------------------------------------------------------------
    # Breakdowns by dimension
    # ------------------------------------------------------------------

    def get_reply_rate_by_vertical(self, days: int = 30) -> list[dict]:
        """Reply rates broken down by vertical (campaign_name / industry).

        Returns list of {vertical, total_sequenced, replied, reply_rate_pct}
        sorted by reply_rate_pct desc.
        """
        try:
            rows = self.db._filter_ws(
                self.db.client.table("contacts").select(
                    "outreach_state, companies(campaign_name, industry)"
                )
            ).execute().data or []
        except Exception as exc:
            logger.error(f"get_reply_rate_by_vertical failed: {exc}")
            return []

        # Bucket by campaign_name (used as "vertical" proxy)
        buckets: dict[str, dict[str, int]] = {}
        for row in rows:
            company = row.get("companies") or {}
            vertical = company.get("campaign_name") or company.get("industry") or "unknown"
            state = row.get("outreach_state") or ""

            if vertical not in buckets:
                buckets[vertical] = {"total": 0, "replied": 0}

            if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                buckets[vertical]["total"] += 1
            if state in _POSITIVE_STATES:
                buckets[vertical]["replied"] += 1

        result = []
        for vertical, counts in buckets.items():
            result.append({
                "vertical": vertical,
                "total_sequenced": counts["total"],
                "replied": counts["replied"],
                "reply_rate_pct": _safe_div(counts["replied"], counts["total"]),
            })

        return sorted(result, key=lambda x: x["reply_rate_pct"], reverse=True)

    def get_reply_rate_by_persona(self, days: int = 30) -> list[dict]:
        """Reply rates by persona_type.

        Returns list of {persona_type, total_sequenced, replied, reply_rate_pct}.
        """
        try:
            rows = self.db._filter_ws(
                self.db.client.table("contacts").select("outreach_state, persona_type")
            ).execute().data or []
        except Exception as exc:
            logger.error(f"get_reply_rate_by_persona failed: {exc}")
            return []

        buckets: dict[str, dict[str, int]] = {}
        for row in rows:
            persona = row.get("persona_type") or "unknown"
            state = row.get("outreach_state") or ""

            if persona not in buckets:
                buckets[persona] = {"total": 0, "replied": 0}

            if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                buckets[persona]["total"] += 1
            if state in _POSITIVE_STATES:
                buckets[persona]["replied"] += 1

        result = []
        for persona, counts in buckets.items():
            result.append({
                "persona_type": persona,
                "total_sequenced": counts["total"],
                "replied": counts["replied"],
                "reply_rate_pct": _safe_div(counts["replied"], counts["total"]),
            })

        return sorted(result, key=lambda x: x["reply_rate_pct"], reverse=True)

    def get_reply_rate_by_touch(self, days: int = 30) -> list[dict]:
        """Which touch number generated the most replies.

        Queries outreach_state_log to find which sequence_step was active
        when a reply came in, then computes rate per touch number.

        Returns list of {touch_number, emails_sent, replies_from_touch, reply_rate_pct}.
        """
        since = _since_iso(days)
        try:
            # Get all email_sent events with sequence_step in metadata
            sent_rows = (
                self.db._filter_ws(
                    self.db.client.table("outreach_state_log")
                    .select("metadata, contact_id")
                )
                .eq("instantly_event", "email_sent")
                .gte("created_at", since)
                .execute().data or []
            )

            # Get reply events
            reply_rows = (
                self.db._filter_ws(
                    self.db.client.table("outreach_state_log")
                    .select("contact_id, created_at")
                )
                .eq("instantly_event", "email_replied")
                .gte("created_at", since)
                .execute().data or []
            )
        except Exception as exc:
            logger.error(f"get_reply_rate_by_touch failed: {exc}")
            return []

        # Contact → last touch step before reply
        # Build: contact_id → list of (step, timestamp) for sent events
        contact_touches: dict[str, list[tuple[int, str]]] = {}
        for row in sent_rows:
            meta = row.get("metadata") or {}
            step = meta.get("sequence_step") or 1
            try:
                step = int(step)
            except (TypeError, ValueError):
                step = 1
            cid = row.get("contact_id")
            if cid:
                contact_touches.setdefault(cid, []).append(step)

        # Count sends per touch
        sends_by_touch: dict[int, int] = {}
        for touches in contact_touches.values():
            for step in touches:
                sends_by_touch[step] = sends_by_touch.get(step, 0) + 1

        # For replies, attribute to the highest touch step that contact received
        reply_contact_ids = {r["contact_id"] for r in reply_rows if r.get("contact_id")}
        replies_by_touch: dict[int, int] = {}
        for cid in reply_contact_ids:
            touches = contact_touches.get(cid, [])
            if touches:
                step = max(touches)
                replies_by_touch[step] = replies_by_touch.get(step, 0) + 1

        result = []
        for touch in range(1, 6):
            sent = sends_by_touch.get(touch, 0)
            replied = replies_by_touch.get(touch, 0)
            result.append({
                "touch_number": touch,
                "emails_sent": sent,
                "replies_from_touch": replied,
                "reply_rate_pct": _safe_div(replied, sent),
            })

        return result

    # ------------------------------------------------------------------
    # Account-level analytics
    # ------------------------------------------------------------------

    def get_top_converting_companies(self, limit: int = 10) -> list[dict]:
        """Companies with positive signals: replied, demo, won.

        Returns list sorted by a composite signal score:
          - closed_won = 3 pts
          - demo_scheduled = 2 pts
          - replied = 1 pt
        """
        try:
            rows = (
                self.db._filter_ws(
                    self.db.client.table("contacts")
                    .select(
                        "company_id, outreach_state, reply_sentiment, "
                        "open_count, click_count, intent_score, "
                        "companies(id, name, domain, tier, campaign_name, intent_score)"
                    )
                )
                .execute().data or []
            )
        except Exception as exc:
            logger.error(f"get_top_converting_companies failed: {exc}")
            return []

        # Aggregate by company
        company_agg: dict[str, dict] = {}
        for row in rows:
            company = row.get("companies") or {}
            cid = row.get("company_id")
            if not cid:
                continue

            if cid not in company_agg:
                company_agg[cid] = {
                    "company_id": cid,
                    "name": company.get("name", "Unknown"),
                    "domain": company.get("domain", ""),
                    "tier": company.get("tier", "?"),
                    "campaign_name": company.get("campaign_name", ""),
                    "intent_score": company.get("intent_score") or 0,
                    "won": 0,
                    "demo": 0,
                    "replied": 0,
                    "total_opens": 0,
                    "total_clicks": 0,
                    "signal_score": 0,
                }

            agg = company_agg[cid]
            state = row.get("outreach_state") or ""
            agg["total_opens"] += row.get("open_count") or 0
            agg["total_clicks"] += row.get("click_count") or 0

            if state == "closed_won":
                agg["won"] += 1
                agg["signal_score"] += 3
            elif state == "demo_scheduled":
                agg["demo"] += 1
                agg["signal_score"] += 2
            elif state in ("replied", "nurture"):
                agg["replied"] += 1
                agg["signal_score"] += 1

        # Filter to companies with at least one positive signal
        positive = [v for v in company_agg.values() if v["signal_score"] > 0]
        positive.sort(key=lambda x: (x["signal_score"], x["intent_score"]), reverse=True)
        return positive[:limit]

    # ------------------------------------------------------------------
    # Velocity
    # ------------------------------------------------------------------

    def get_pipeline_velocity(self, campaign_name: str | None = None) -> dict:
        """Average days between key state transitions.

        Returns {discovery_to_enriched_days, enriched_to_sequenced_days,
                 sequenced_to_replied_days, overall_days}.
        """
        try:
            query = self.db._filter_ws(
                self.db.client.table("outreach_state_log").select(
                    "contact_id, to_state, created_at"
                )
            ).in_("to_state", ["enriched", "sequenced", "touch_1_sent", "replied"])

            rows = query.order("created_at").execute().data or []
        except Exception as exc:
            logger.error(f"get_pipeline_velocity failed: {exc}")
            return self._empty_velocity()

        # Build per-contact timestamps
        contact_ts: dict[str, dict[str, str]] = {}
        for row in rows:
            cid = row["contact_id"]
            state = row["to_state"]
            ts = row["created_at"]
            contact_ts.setdefault(cid, {})[state] = ts

        def _avg_days(pairs: list[tuple[str | None, str | None]]) -> float:
            deltas = []
            for a, b in pairs:
                if a and b:
                    try:
                        ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
                        tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
                        deltas.append(abs((tb - ta).total_seconds() / 86400))
                    except Exception:
                        pass
            return round(sum(deltas) / len(deltas), 1) if deltas else 0.0

        pairs_enrich = [
            (ct.get("enriched"), ct.get("sequenced"))
            for ct in contact_ts.values()
        ]
        pairs_seq = [
            (ct.get("sequenced") or ct.get("touch_1_sent"), ct.get("replied"))
            for ct in contact_ts.values()
        ]
        pairs_overall = [
            (ct.get("enriched"), ct.get("replied"))
            for ct in contact_ts.values()
        ]

        return {
            "enriched_to_sequenced_days": _avg_days(pairs_enrich),
            "sequenced_to_replied_days": _avg_days(pairs_seq),
            "overall_discovery_to_reply_days": _avg_days(pairs_overall),
            "contacts_with_reply": sum(
                1 for ct in contact_ts.values() if "replied" in ct
            ),
        }

    # ------------------------------------------------------------------
    # Weekly activity
    # ------------------------------------------------------------------

    def get_weekly_activity(self, weeks: int = 8) -> list[dict]:
        """Week-by-week activity: contacts added, sequenced, and replies received.

        Returns list of dicts, oldest week first:
          {week_start, contacts_added, sequenced, replied}
        """
        since = _since_iso(weeks * 7)
        try:
            # Contacts created per week
            contact_rows = (
                self.db._filter_ws(
                    self.db.client.table("contacts").select("created_at")
                )
                .gte("created_at", since)
                .execute().data or []
            )

            # State log events per week
            state_rows = (
                self.db._filter_ws(
                    self.db.client.table("outreach_state_log").select("to_state, created_at")
                )
                .in_("to_state", ["sequenced", "touch_1_sent", "replied"])
                .gte("created_at", since)
                .execute().data or []
            )
        except Exception as exc:
            logger.error(f"get_weekly_activity failed: {exc}")
            return []

        def _week_start(ts_str: str) -> str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                monday = ts - timedelta(days=ts.weekday())
                return monday.strftime("%Y-%m-%d")
            except Exception:
                return "unknown"

        # Aggregate
        weekly: dict[str, dict[str, int]] = {}
        for row in contact_rows:
            wk = _week_start(row["created_at"])
            weekly.setdefault(wk, {"contacts_added": 0, "sequenced": 0, "replied": 0})
            weekly[wk]["contacts_added"] += 1

        for row in state_rows:
            wk = _week_start(row["created_at"])
            state = row["to_state"]
            weekly.setdefault(wk, {"contacts_added": 0, "sequenced": 0, "replied": 0})
            if state in ("sequenced", "touch_1_sent"):
                weekly[wk]["sequenced"] += 1
            elif state == "replied":
                weekly[wk]["replied"] += 1

        result = [
            {"week_start": wk, **counts}
            for wk, counts in sorted(weekly.items())
            if wk != "unknown"
        ]
        return result[-weeks:]

    # ------------------------------------------------------------------
    # Intent signal impact
    # ------------------------------------------------------------------

    def get_intent_signal_impact(self) -> dict:
        """Compare reply rates for contacts with vs without intent signals.

        Returns {with_intent: {total, replied, rate}, without_intent: {...}, lift_pct}.
        """
        try:
            rows = (
                self.db._filter_ws(
                    self.db.client.table("contacts")
                    .select("outreach_state, intent_score, companies(intent_score)")
                )
                .execute().data or []
            )
        except Exception as exc:
            logger.error(f"get_intent_signal_impact failed: {exc}")
            return {}

        with_intent = {"total": 0, "replied": 0}
        without_intent = {"total": 0, "replied": 0}

        for row in rows:
            state = row.get("outreach_state") or ""
            # Use company-level or contact-level intent score
            company = row.get("companies") or {}
            score = max(row.get("intent_score") or 0, company.get("intent_score") or 0)
            has_intent = score > 0

            bucket = with_intent if has_intent else without_intent

            if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                bucket["total"] += 1
            if state in _POSITIVE_STATES:
                bucket["replied"] += 1

        with_rate = _safe_div(with_intent["replied"], with_intent["total"])
        without_rate = _safe_div(without_intent["replied"], without_intent["total"])
        lift = round(with_rate - without_rate, 1)

        return {
            "with_intent": {**with_intent, "reply_rate_pct": with_rate},
            "without_intent": {**without_intent, "reply_rate_pct": without_rate},
            "lift_pct": lift,
            "has_meaningful_data": with_intent["total"] >= 10 and without_intent["total"] >= 10,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_campaign_company_ids(self, campaign_name: str) -> list[str]:
        try:
            rows = (
                self.db._filter_ws(
                    self.db.client.table("companies").select("id")
                )
                .eq("campaign_name", campaign_name)
                .execute().data or []
            )
            return [r["id"] for r in rows]
        except Exception:
            return []

    @staticmethod
    def _empty_funnel() -> dict[str, Any]:
        result: dict[str, Any] = {}
        for stage in _FUNNEL_STAGES:
            result[stage] = 0
        for extra in ("closed_lost", "nurture", "not_qualified", "dnc"):
            result[extra] = 0
        result["total_in_outreach"] = 0
        result["overall_reply_rate"] = 0.0
        result["demo_from_reply_rate"] = 0.0
        result["win_rate"] = 0.0
        result["conversion_rates"] = {}
        return result

    @staticmethod
    def _empty_velocity() -> dict:
        return {
            "enriched_to_sequenced_days": 0.0,
            "sequenced_to_replied_days": 0.0,
            "overall_discovery_to_reply_days": 0.0,
            "contacts_with_reply": 0,
        }
