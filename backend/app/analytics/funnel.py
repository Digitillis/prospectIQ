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
    print(fa.get_full_funnel(workspace_id="ws_xxx", days=90))
    print(fa.get_cohort_analysis(workspace_id="ws_xxx", group_by="cluster"))
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

    # ------------------------------------------------------------------
    # NEW: Full funnel with Pydantic models
    # ------------------------------------------------------------------

    def get_full_funnel(
        self,
        workspace_id: str | None = None,
        days: int = 90,
    ) -> "FunnelData":
        """Return full 10-stage funnel as structured FunnelData.

        Stages (in order):
            discovered → enriched → sequenced → touch_1_sent → touch_2_sent
            → touch_3_sent → replied → demo_scheduled → closed_won

        Maps the existing contact outreach_state values onto a clean
        funnel representation with per-stage conversion rates and drop-off.
        """
        from backend.app.analytics.models import FunnelData, FunnelStage

        # Pull raw counts from the existing engine
        counts = self.get_funnel_counts(days=days)

        # Pull velocity data for avg_days_in_stage estimates
        velocity = self.get_pipeline_velocity()

        # Ordered stage definitions: (stage_key, display_name, velocity_key or None)
        stage_defs = [
            ("discovered",      "Discovered",   None),
            ("enriched",        "Enriched",     "enriched_to_sequenced_days"),
            ("sequenced",       "Sequenced",    "enriched_to_sequenced_days"),
            ("touch_1_sent",    "Touch 1 Sent", None),
            ("touch_2_sent",    "Touch 2 Sent", None),
            ("touch_3_sent",    "Touch 3 Sent", None),
            ("replied",         "Replied",      "sequenced_to_replied_days"),
            ("demo_scheduled",  "Demo Booked",  None),
            ("closed_won",      "Closed Won",   None),
        ]

        stage_counts = {k: counts.get(k, 0) for k, _, _ in stage_defs}

        # Build stages list
        stages: list[FunnelStage] = []
        prev_count = None
        max_drop_off = 0
        bottleneck_key = stage_defs[0][0]

        for stage_key, stage_name, vel_key in stage_defs:
            count = stage_counts[stage_key]
            avg_days = velocity.get(vel_key, 0.0) if vel_key else 0.0

            if prev_count is None:
                conv_rate = 100.0
                drop_off = 0
            else:
                conv_rate = _safe_div(count, prev_count) if prev_count > 0 else 0.0
                drop_off = max(prev_count - count, 0)
                if drop_off > max_drop_off:
                    max_drop_off = drop_off
                    bottleneck_key = stage_key

            stages.append(FunnelStage(
                stage_name=stage_name,
                stage_key=stage_key,
                count=count,
                conversion_rate=conv_rate,
                avg_days_in_stage=avg_days,
                drop_off=drop_off,
            ))

            if count > 0:
                prev_count = count
            elif prev_count is not None:
                prev_count = prev_count  # carry forward so next drop-off is relative

        # Mark bottleneck
        for s in stages:
            s.is_bottleneck = (s.stage_key == bottleneck_key)

        total_entered = stage_counts["discovered"]
        total_converted = stage_counts["replied"] + stage_counts["demo_scheduled"] + stage_counts["closed_won"]
        overall_conv = _safe_div(total_converted, total_entered) if total_entered else 0.0

        return FunnelData(
            stages=stages,
            period_days=days,
            total_entered=total_entered,
            total_converted=total_converted,
            overall_conversion_rate=overall_conv,
            bottleneck_stage=bottleneck_key,
        )

    # ------------------------------------------------------------------
    # NEW: Cohort analysis
    # ------------------------------------------------------------------

    def get_cohort_analysis(
        self,
        workspace_id: str | None = None,
        group_by: str = "cluster",
        days: int = 90,
    ) -> "CohortAnalysis":
        """Return per-cohort conversion metrics grouped by the given dimension.

        group_by options: "cluster" | "tranche" | "persona" | "sequence_name"
        """
        from backend.app.analytics.models import CohortAnalysis, CohortRow

        # Map group_by to the correct table/column
        group_field_map = {
            "cluster":       ("companies", "campaign_cluster"),
            "tranche":       ("companies", "tranche"),
            "persona":       ("contacts",  "persona_type"),
            "sequence_name": ("outreach_drafts", "sequence_name"),
        }
        if group_by not in group_field_map:
            group_by = "cluster"

        table, field = group_field_map[group_by]

        try:
            if table == "companies":
                rows = self.db._filter_ws(
                    self.db.client.table("contacts").select(
                        f"outreach_state, intent_score, "
                        f"companies(id, pqs_total, {field})"
                    )
                ).execute().data or []

                buckets: dict[str, dict] = {}
                for row in rows:
                    company = row.get("companies") or {}
                    key = company.get(field) or "Unknown"
                    state = row.get("outreach_state") or ""
                    pqs = company.get("pqs_total") or 0

                    if key not in buckets:
                        buckets[key] = {
                            "total": 0, "contacted": 0, "replied": 0,
                            "interested": 0, "pqs_sum": 0,
                        }

                    b = buckets[key]
                    b["total"] += 1
                    b["pqs_sum"] += pqs

                    if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                        b["contacted"] += 1
                    if state in ("replied", "demo_scheduled", "closed_won", "nurture"):
                        b["replied"] += 1
                    if state in ("demo_scheduled", "closed_won"):
                        b["interested"] += 1

            elif table == "contacts":
                rows = self.db._filter_ws(
                    self.db.client.table("contacts").select(
                        f"outreach_state, {field}, intent_score, "
                        f"companies(pqs_total)"
                    )
                ).execute().data or []

                buckets = {}
                for row in rows:
                    key = row.get(field) or "Unknown"
                    state = row.get("outreach_state") or ""
                    pqs = (row.get("companies") or {}).get("pqs_total") or 0

                    if key not in buckets:
                        buckets[key] = {
                            "total": 0, "contacted": 0, "replied": 0,
                            "interested": 0, "pqs_sum": 0,
                        }

                    b = buckets[key]
                    b["total"] += 1
                    b["pqs_sum"] += pqs

                    if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                        b["contacted"] += 1
                    if state in ("replied", "demo_scheduled", "closed_won", "nurture"):
                        b["replied"] += 1
                    if state in ("demo_scheduled", "closed_won"):
                        b["interested"] += 1

            else:
                # sequence_name — join via outreach_drafts
                rows = self.db._filter_ws(
                    self.db.client.table("outreach_drafts").select(
                        "sequence_name, approval_status, sent_at, "
                        "contacts(outreach_state), companies(pqs_total)"
                    )
                ).execute().data or []

                buckets = {}
                for row in rows:
                    key = row.get("sequence_name") or "Unknown"
                    contact = row.get("contacts") or {}
                    state = contact.get("outreach_state") or ""
                    pqs = (row.get("companies") or {}).get("pqs_total") or 0

                    if key not in buckets:
                        buckets[key] = {
                            "total": 0, "contacted": 0, "replied": 0,
                            "interested": 0, "pqs_sum": 0,
                        }

                    b = buckets[key]
                    b["total"] += 1
                    b["pqs_sum"] += pqs

                    if row.get("sent_at"):
                        b["contacted"] += 1
                    if state in ("replied", "demo_scheduled", "closed_won"):
                        b["replied"] += 1
                    if state in ("demo_scheduled", "closed_won"):
                        b["interested"] += 1

        except Exception as exc:
            logger.error(f"get_cohort_analysis failed: {exc}")
            buckets = {}

        cohort_rows: list[CohortRow] = []
        for name, b in buckets.items():
            total = b["total"]
            cohort_rows.append(CohortRow(
                cohort_name=name,
                count=total,
                contacted_pct=_safe_div(b["contacted"], total),
                reply_rate=_safe_div(b["replied"], b["contacted"] or 1),
                interested_pct=_safe_div(b["interested"], b["contacted"] or 1),
                conversion_rate=_safe_div(b["replied"], total),
                avg_pqs=round(b["pqs_sum"] / max(total, 1), 1),
            ))

        cohort_rows.sort(key=lambda r: r.conversion_rate, reverse=True)

        return CohortAnalysis(
            rows=cohort_rows,
            group_by=group_by,
            period_days=days,
        )

    # ------------------------------------------------------------------
    # NEW: Enhanced velocity metrics with trend
    # ------------------------------------------------------------------

    def get_velocity_metrics(
        self,
        workspace_id: str | None = None,
    ) -> "VelocityMetrics":
        """Return stage-by-stage velocity with trend vs prior 30-day period."""
        from datetime import datetime, timezone
        from backend.app.analytics.models import VelocityMetrics, VelocityStage

        current = self.get_pipeline_velocity()
        # Compute trend by comparing recent 15 days vs prior 15 days via state log
        stages = [
            VelocityStage(
                stage_name="Enriched → Sequenced",
                avg_days=current.get("enriched_to_sequenced_days", 0.0),
                trend="no_data",
                trend_delta_days=0.0,
            ),
            VelocityStage(
                stage_name="Sequenced → Replied",
                avg_days=current.get("sequenced_to_replied_days", 0.0),
                trend="no_data",
                trend_delta_days=0.0,
            ),
            VelocityStage(
                stage_name="Overall to Reply",
                avg_days=current.get("overall_discovery_to_reply_days", 0.0),
                trend="no_data",
                trend_delta_days=0.0,
            ),
        ]

        # Attempt trend calculation from state log
        try:
            since_60 = _since_iso(60)
            since_30 = _since_iso(30)

            log_rows = (
                self.db._filter_ws(
                    self.db.client.table("outreach_state_log")
                    .select("contact_id, to_state, created_at")
                )
                .in_("to_state", ["enriched", "sequenced", "touch_1_sent", "replied"])
                .gte("created_at", since_60)
                .order("created_at")
                .execute().data or []
            )

            def _split_and_compute(rows: list, cutoff: str) -> tuple[dict, dict]:
                recent: dict[str, dict[str, str]] = {}
                prior: dict[str, dict[str, str]] = {}
                for r in rows:
                    bucket = recent if r["created_at"] >= cutoff else prior
                    bucket.setdefault(r["contact_id"], {})[r["to_state"]] = r["created_at"]
                return recent, prior

            recent_ct, prior_ct = _split_and_compute(log_rows, since_30)

            def _avg_d(contact_map: dict, from_state: str, to_state: str) -> float:
                deltas = []
                for ct in contact_map.values():
                    a = ct.get(from_state)
                    b = ct.get(to_state)
                    if a and b:
                        try:
                            ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
                            tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
                            deltas.append(abs((tb - ta).total_seconds() / 86400))
                        except Exception:
                            pass
                return round(sum(deltas) / len(deltas), 1) if deltas else 0.0

            pairs = [
                (0, "enriched", "sequenced"),
                (1, "touch_1_sent", "replied"),
                (2, "enriched", "replied"),
            ]

            for idx, from_s, to_s in pairs:
                r_avg = _avg_d(recent_ct, from_s, to_s)
                p_avg = _avg_d(prior_ct, from_s, to_s)
                delta = round(r_avg - p_avg, 1)

                if p_avg == 0:
                    trend = "no_data"
                elif abs(delta) < 0.5:
                    trend = "stable"
                elif delta > 0:
                    trend = "slower"
                else:
                    trend = "faster"

                if r_avg > 0:
                    stages[idx].avg_days = r_avg
                stages[idx].trend = trend
                stages[idx].trend_delta_days = delta

        except Exception as exc:
            logger.warning(f"Velocity trend computation failed: {exc}")

        return VelocityMetrics(
            stages=stages,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
