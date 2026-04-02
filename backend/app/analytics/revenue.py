"""Revenue attribution and activity ROI analytics for ProspectIQ.

Tracks pipeline-to-revenue correlation and outreach activity ROI.

Usage:
    from backend.app.analytics.revenue import RevenueAnalytics
    from backend.app.core.database import Database

    db = Database()
    ra = RevenueAnalytics(db)
    print(ra.get_revenue_attribution(workspace_id="ws_xxx"))
    print(ra.get_activity_roi(workspace_id="ws_xxx"))
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.app.core.database import Database
from backend.app.analytics.funnel import FunnelAnalytics, _safe_div, _since_iso

logger = logging.getLogger(__name__)

# Default deal size assumption (annual contract value)
DEFAULT_DEAL_SIZE_USD = 48_000.0

# Conversion rate assumptions per stage (probability of reaching closed_won)
_STAGE_WIN_PROBABILITY = {
    "outreach_sent": 0.02,      # 2% of all contacted close
    "replied":       0.10,      # 10% of replies close
    "interested":    0.25,      # 25% of interested close
    "demo_booked":   0.40,      # 40% of demos close
    "proposal":      0.60,
    "closed_won":    1.0,
    "closed_lost":   0.0,
}

_POSITIVE_STATES = {"replied", "demo_scheduled", "closed_won"}
_TOUCH_STATES = {f"touch_{n}_sent" for n in range(1, 7)}


class RevenueAnalytics:
    """Revenue attribution engine."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.fa = FunnelAnalytics(db)

    # ------------------------------------------------------------------
    # Revenue attribution
    # ------------------------------------------------------------------

    def get_revenue_attribution(
        self,
        workspace_id: str | None = None,
        deal_size_usd: float = DEFAULT_DEAL_SIZE_USD,
    ) -> "RevenueAttribution":
        """Compute pipeline value and projected ARR."""
        from backend.app.analytics.models import RevenueAttribution, DealStage

        funnel = self.fa.get_funnel_counts(days=180)

        # Map funnel states to deal stages
        outreach_sent = sum(funnel.get(f"touch_{n}_sent", 0) for n in range(1, 6))
        replied = funnel.get("replied", 0)
        demo_booked = funnel.get("demo_scheduled", 0)
        closed_won = funnel.get("closed_won", 0)
        closed_lost = funnel.get("closed_lost", 0)

        pipeline_stages = [
            DealStage(
                stage="outreach_sent",
                count=outreach_sent,
                est_value_usd=outreach_sent * deal_size_usd * _STAGE_WIN_PROBABILITY["outreach_sent"],
            ),
            DealStage(
                stage="replied",
                count=replied,
                est_value_usd=replied * deal_size_usd * _STAGE_WIN_PROBABILITY["replied"],
            ),
            DealStage(
                stage="demo_booked",
                count=demo_booked,
                est_value_usd=demo_booked * deal_size_usd * _STAGE_WIN_PROBABILITY["demo_booked"],
            ),
            DealStage(
                stage="closed_won",
                count=closed_won,
                est_value_usd=closed_won * deal_size_usd,
            ),
            DealStage(
                stage="closed_lost",
                count=closed_lost,
                est_value_usd=0.0,
            ),
        ]

        # Weighted pipeline value (probability-adjusted)
        weighted_value = sum(s.est_value_usd for s in pipeline_stages)

        # Projected ARR: weight by expected close rate and time-to-close
        # 90-day assumes ~30% of pipeline closes in 3 months
        projected_90d = round(weighted_value * 0.30, 0)
        projected_180d = round(weighted_value * 0.60, 0)

        # Confidence range: ±40% based on typical B2B variance
        confidence_low = round(projected_90d * 0.60, 0)
        confidence_high = round(projected_90d * 1.40, 0)

        # Best-performing cluster and sequence
        best_cluster = self._get_best_cluster()
        best_sequence = self._get_best_sequence()

        return RevenueAttribution(
            pipeline_stages=pipeline_stages,
            projected_arr_90d=projected_90d,
            projected_arr_180d=projected_180d,
            confidence_range=(confidence_low, confidence_high),
            best_performing_cluster=best_cluster,
            best_performing_sequence=best_sequence,
            avg_deal_size_assumption=deal_size_usd,
            weighted_pipeline_value=round(weighted_value, 0),
        )

    # ------------------------------------------------------------------
    # Activity ROI
    # ------------------------------------------------------------------

    def get_activity_roi(
        self,
        workspace_id: str | None = None,
    ) -> "ActivityROI":
        """Compute reply rates by channel, sequence, persona, and cluster."""
        from backend.app.analytics.models import ActivityROI, ChannelROI, SequenceROI

        # --- By channel ---
        by_channel: list[ChannelROI] = []
        try:
            drafts = self.db._filter_ws(
                self.db.client.table("outreach_drafts").select(
                    "channel, sent_at, "
                    "contacts(outreach_state)"
                )
            ).not_.is_("sent_at", "null").execute().data or []

            channel_buckets: dict[str, dict[str, int]] = {}
            for d in drafts:
                ch = (d.get("channel") or "email").lower()
                state = (d.get("contacts") or {}).get("outreach_state") or ""
                channel_buckets.setdefault(ch, {"sent": 0, "replied": 0})
                channel_buckets[ch]["sent"] += 1
                if state in ("replied", "demo_scheduled", "closed_won"):
                    channel_buckets[ch]["replied"] += 1

            for ch, b in channel_buckets.items():
                by_channel.append(ChannelROI(
                    channel=ch,
                    total_sent=b["sent"],
                    total_replied=b["replied"],
                    reply_rate_pct=_safe_div(b["replied"], b["sent"]),
                ))
            by_channel.sort(key=lambda x: x.reply_rate_pct, reverse=True)
        except Exception as exc:
            logger.error(f"get_activity_roi by_channel failed: {exc}")

        # --- By sequence ---
        by_sequence: list[SequenceROI] = []
        try:
            seq_rows = self.db._filter_ws(
                self.db.client.table("outreach_drafts").select(
                    "sequence_name, sent_at, "
                    "contacts(outreach_state)"
                )
            ).not_.is_("sent_at", "null").execute().data or []

            seq_buckets: dict[str, dict[str, int]] = {}
            for r in seq_rows:
                name = r.get("sequence_name") or "unknown"
                state = (r.get("contacts") or {}).get("outreach_state") or ""
                seq_buckets.setdefault(name, {"sent": 0, "replied": 0})
                seq_buckets[name]["sent"] += 1
                if state in ("replied", "demo_scheduled", "closed_won"):
                    seq_buckets[name]["replied"] += 1

            for name, b in seq_buckets.items():
                by_sequence.append(SequenceROI(
                    sequence_name=name,
                    total_sent=b["sent"],
                    total_replied=b["replied"],
                    reply_rate_pct=_safe_div(b["replied"], b["sent"]),
                ))
            by_sequence.sort(key=lambda x: x.reply_rate_pct, reverse=True)
        except Exception as exc:
            logger.error(f"get_activity_roi by_sequence failed: {exc}")

        # --- By persona (reuse existing) ---
        by_persona = self.fa.get_reply_rate_by_persona(days=90)

        # --- By cluster ---
        by_cluster: list[dict] = []
        try:
            cluster_rows = self.db._filter_ws(
                self.db.client.table("contacts").select(
                    "outreach_state, "
                    "companies(campaign_cluster)"
                )
            ).execute().data or []

            cluster_buckets: dict[str, dict[str, int]] = {}
            for r in cluster_rows:
                cluster = (r.get("companies") or {}).get("campaign_cluster") or "Unknown"
                state = r.get("outreach_state") or ""
                cluster_buckets.setdefault(cluster, {"total": 0, "replied": 0})
                if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                    cluster_buckets[cluster]["total"] += 1
                if state in ("replied", "demo_scheduled", "closed_won"):
                    cluster_buckets[cluster]["replied"] += 1

            for cluster, b in cluster_buckets.items():
                by_cluster.append({
                    "cluster": cluster,
                    "total_sequenced": b["total"],
                    "replied": b["replied"],
                    "reply_rate_pct": _safe_div(b["replied"], b["total"]),
                })
            by_cluster.sort(key=lambda x: x["reply_rate_pct"], reverse=True)
        except Exception as exc:
            logger.error(f"get_activity_roi by_cluster failed: {exc}")

        return ActivityROI(
            by_channel=by_channel,
            by_sequence=by_sequence,
            by_persona=by_persona,
            by_cluster=by_cluster,
        )

    # ------------------------------------------------------------------
    # Analytics summary (for command center card)
    # ------------------------------------------------------------------

    def get_analytics_summary(
        self,
        workspace_id: str | None = None,
    ) -> "AnalyticsSummary":
        """Combined top-level summary for the command center analytics card."""
        from backend.app.analytics.models import AnalyticsSummary

        funnel = self.fa.get_funnel_counts(days=90)
        revenue = self.get_revenue_attribution(workspace_id=workspace_id)

        total_pipeline = sum(
            funnel.get(s, 0)
            for s in ("discovered", "enriched", "sequenced",
                      "touch_1_sent", "touch_2_sent", "touch_3_sent",
                      "replied", "demo_scheduled", "closed_won")
        )
        total_contacted = sum(
            funnel.get(f"touch_{n}_sent", 0) for n in range(1, 6)
        )
        total_replied = funnel.get("replied", 0)
        total_interested = funnel.get("demo_scheduled", 0) + funnel.get("closed_won", 0)

        overall_conv = funnel.get("overall_reply_rate", 0.0)
        if overall_conv >= 5.0:
            health = "green"
        elif overall_conv >= 2.0:
            health = "amber"
        else:
            health = "red"

        # Count companies stuck in research for >14 days
        stuck_count = 0
        try:
            since_14 = _since_iso(14)
            # Companies in "researched" state that haven't advanced
            r = (
                self.db._filter_ws(
                    self.db.client.table("companies").select("id", count="exact")
                )
                .eq("status", "researched")
                .lt("updated_at", since_14)
                .execute()
            )
            stuck_count = r.count or 0
        except Exception:
            pass

        return AnalyticsSummary(
            total_pipeline=total_pipeline,
            total_contacted=total_contacted,
            total_replied=total_replied,
            total_interested=total_interested,
            projected_arr_90d=revenue.projected_arr_90d,
            overall_conversion_rate=overall_conv,
            pipeline_health=health,
            bottleneck_stage=self._find_bottleneck(funnel),
            stuck_in_research_14d=stuck_count,
            best_cluster=revenue.best_performing_cluster,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_best_cluster(self) -> str:
        """Return cluster name with highest reply rate (min 5 contacts)."""
        try:
            rows = self.db._filter_ws(
                self.db.client.table("contacts").select(
                    "outreach_state, companies(campaign_cluster)"
                )
            ).execute().data or []

            buckets: dict[str, dict] = {}
            for r in rows:
                cluster = (r.get("companies") or {}).get("campaign_cluster") or "Unknown"
                state = r.get("outreach_state") or ""
                buckets.setdefault(cluster, {"total": 0, "replied": 0})
                if state in _TOUCH_STATES or state in _POSITIVE_STATES:
                    buckets[cluster]["total"] += 1
                if state in ("replied", "demo_scheduled", "closed_won"):
                    buckets[cluster]["replied"] += 1

            best = max(
                ((k, _safe_div(v["replied"], v["total"])) for k, v in buckets.items() if v["total"] >= 5),
                key=lambda x: x[1],
                default=("Unknown", 0.0),
            )
            return best[0]
        except Exception:
            return "Unknown"

    def _get_best_sequence(self) -> str:
        """Return sequence name with highest reply rate (min 10 sent)."""
        try:
            rows = self.db._filter_ws(
                self.db.client.table("outreach_drafts").select(
                    "sequence_name, sent_at, contacts(outreach_state)"
                )
            ).not_.is_("sent_at", "null").execute().data or []

            buckets: dict[str, dict] = {}
            for r in rows:
                name = r.get("sequence_name") or "unknown"
                state = (r.get("contacts") or {}).get("outreach_state") or ""
                buckets.setdefault(name, {"sent": 0, "replied": 0})
                buckets[name]["sent"] += 1
                if state in ("replied", "demo_scheduled", "closed_won"):
                    buckets[name]["replied"] += 1

            best = max(
                ((k, _safe_div(v["replied"], v["sent"])) for k, v in buckets.items() if v["sent"] >= 10),
                key=lambda x: x[1],
                default=("Unknown", 0.0),
            )
            return best[0]
        except Exception:
            return "Unknown"

    @staticmethod
    def _find_bottleneck(funnel: dict) -> str:
        """Find stage with highest absolute drop-off from previous stage."""
        stages = [
            "discovered", "enriched", "sequenced",
            "touch_1_sent", "replied", "demo_scheduled", "closed_won",
        ]
        max_drop = 0
        bottleneck = "enriched"
        prev = funnel.get(stages[0], 0)
        for stage in stages[1:]:
            count = funnel.get(stage, 0)
            drop = prev - count
            if drop > max_drop:
                max_drop = drop
                bottleneck = stage
            if count > 0:
                prev = count
        return bottleneck
