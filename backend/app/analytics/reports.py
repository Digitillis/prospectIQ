"""Campaign report generation for ProspectIQ.

Produces weekly reports (Slack-pasteable plain text) and hot account lists
from funnel data. No ANSI codes in text output — safe for Slack/email paste.

Usage:
    from backend.app.analytics.reports import CampaignReporter
    from backend.app.core.database import Database

    db = Database()
    reporter = CampaignReporter(db)
    print(reporter.generate_weekly_report())
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import Database
from backend.app.analytics.funnel import FunnelAnalytics, _safe_div

logger = logging.getLogger(__name__)


class CampaignReporter:
    """Formats analytics data into actionable reports."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.funnel = FunnelAnalytics(db)

    # ------------------------------------------------------------------
    # Weekly report
    # ------------------------------------------------------------------

    def generate_weekly_report(self, campaign_name: str | None = None) -> str:
        """Rich-formatted weekly report — safe to paste into Slack or email.

        Returns a plain-text string with no ANSI escape codes.
        """
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_label = f"{week_start.strftime('%b %d')} – {today.strftime('%b %d, %Y')}"

        funnel = self.funnel.get_funnel_counts(campaign_name=campaign_name, days=7)
        funnel_30 = self.funnel.get_funnel_counts(campaign_name=campaign_name, days=30)
        velocity = self.funnel.get_pipeline_velocity(campaign_name=campaign_name)
        by_persona = self.funnel.get_reply_rate_by_persona(days=30)
        by_touch = self.funnel.get_reply_rate_by_touch(days=30)
        hot_accounts = self.get_hot_accounts_report(threshold=10)
        recommendations = self.get_optimization_recommendations()

        lines: list[str] = []

        title = "ProspectIQ Weekly Report"
        if campaign_name:
            title += f" — {campaign_name}"
        lines.append("=" * 60)
        lines.append(title)
        lines.append(f"Week of {week_label}")
        lines.append("=" * 60)

        # --- This week funnel ---
        lines.append("")
        lines.append("FUNNEL OVERVIEW (last 7 days)")
        lines.append("-" * 40)
        for stage in ["discovered", "enriched", "sequenced", "touch_1_sent",
                      "replied", "demo_scheduled", "closed_won"]:
            count = funnel.get(stage, 0)
            label = stage.replace("_", " ").title()
            lines.append(f"  {label:<25} {count:>6}")

        reply_rate = funnel.get("overall_reply_rate", 0.0)
        demo_rate = funnel.get("demo_from_reply_rate", 0.0)
        win_rate = funnel.get("win_rate", 0.0)
        lines.append("")
        lines.append(f"  Reply rate (7d):          {reply_rate:>5.1f}%")
        lines.append(f"  Demo / Reply rate (30d):  {demo_rate:>5.1f}%")
        lines.append(f"  Win rate (30d):           {win_rate:>5.1f}%")

        # --- 30-day funnel totals ---
        lines.append("")
        lines.append("PIPELINE TOTALS (last 30 days)")
        lines.append("-" * 40)
        for stage in ["sequenced", "touch_1_sent", "touch_2_sent", "touch_3_sent",
                      "touch_4_sent", "touch_5_sent", "replied", "demo_scheduled",
                      "closed_won", "dnc"]:
            count = funnel_30.get(stage, 0)
            if count > 0:
                label = stage.replace("_", " ").title()
                lines.append(f"  {label:<25} {count:>6}")

        # --- Velocity ---
        lines.append("")
        lines.append("PIPELINE VELOCITY (30d avg)")
        lines.append("-" * 40)
        lines.append(
            f"  Enriched → Sequenced:     {velocity['enriched_to_sequenced_days']:>5.1f} days"
        )
        lines.append(
            f"  Sequenced → Reply:        {velocity['sequenced_to_replied_days']:>5.1f} days"
        )
        lines.append(
            f"  Overall to reply:         {velocity['overall_discovery_to_reply_days']:>5.1f} days"
        )

        # --- Reply rate by persona ---
        if by_persona:
            lines.append("")
            lines.append("REPLY RATE BY PERSONA (30d)")
            lines.append("-" * 40)
            for row in by_persona[:6]:
                persona = row["persona_type"].replace("_", " ").title()
                rate = row["reply_rate_pct"]
                total = row["total_sequenced"]
                lines.append(f"  {persona:<28} {rate:>5.1f}%  (n={total})")

        # --- Reply rate by touch ---
        if by_touch:
            lines.append("")
            lines.append("REPLY RATE BY TOUCH NUMBER (30d)")
            lines.append("-" * 40)
            for row in by_touch:
                touch = row["touch_number"]
                rate = row["reply_rate_pct"]
                sent = row["emails_sent"]
                lines.append(f"  Touch {touch}:  {rate:>5.1f}%  ({sent} sent)")

        # --- Hot accounts ---
        if hot_accounts:
            lines.append("")
            lines.append("HOT ACCOUNTS")
            lines.append("-" * 40)
            for acc in hot_accounts[:5]:
                name = acc["company_name"]
                score = acc["composite_score"]
                signals = []
                if acc.get("won"):
                    signals.append("WON")
                if acc.get("demo"):
                    signals.append("DEMO")
                if acc.get("replied"):
                    signals.append("REPLIED")
                intent = acc.get("intent_score", 0)
                if intent:
                    signals.append(f"intent={intent}")
                lines.append(f"  {name:<30} [{', '.join(signals)}]  score={score}")

        # --- Recommendations ---
        if recommendations:
            lines.append("")
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 40)
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"  {i}. {rec}")

        lines.append("")
        lines.append("=" * 60)
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Funnel report (programmatic)
    # ------------------------------------------------------------------

    def generate_funnel_report(self, campaign_name: str | None = None) -> dict:
        """Full funnel data as dict for programmatic use or API responses."""
        return {
            "funnel_7d": self.funnel.get_funnel_counts(campaign_name=campaign_name, days=7),
            "funnel_30d": self.funnel.get_funnel_counts(campaign_name=campaign_name, days=30),
            "velocity": self.funnel.get_pipeline_velocity(campaign_name=campaign_name),
            "by_vertical": self.funnel.get_reply_rate_by_vertical(days=30),
            "by_persona": self.funnel.get_reply_rate_by_persona(days=30),
            "by_touch": self.funnel.get_reply_rate_by_touch(days=30),
            "intent_impact": self.funnel.get_intent_signal_impact(),
            "weekly_activity": self.funnel.get_weekly_activity(weeks=8),
            "hot_accounts": self.get_hot_accounts_report(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "campaign_name": campaign_name,
        }

    # ------------------------------------------------------------------
    # Hot accounts
    # ------------------------------------------------------------------

    def get_hot_accounts_report(self, threshold: int = 20) -> list[dict]:
        """Companies with high intent scores + positive outreach signals.

        A "hot" account scores above `threshold` on a composite of:
          - Intent score (company level, 0–100)
          - Reply score (replied=1, demo=2, won=3 per contact)
          - Engagement (open/click counts)

        Returns list sorted by composite_score desc.
        """
        try:
            rows = (
                self.db._filter_ws(
                    self.db.client.table("contacts")
                    .select(
                        "company_id, outreach_state, open_count, click_count, "
                        "reply_sentiment, "
                        "companies(id, name, domain, tier, campaign_name, "
                        "intent_score, outreach_active)"
                    )
                )
                .execute().data or []
            )

            # Fetch active intent signals counts per company
            intent_rows = (
                self.db._filter_ws(
                    self.db.client.table("company_intent_signals").select("company_id")
                )
                .eq("is_active", True)
                .execute().data or []
            )
        except Exception as exc:
            logger.error(f"get_hot_accounts_report failed: {exc}")
            return []

        intent_counts: dict[str, int] = {}
        for r in intent_rows:
            cid = r["company_id"]
            intent_counts[cid] = intent_counts.get(cid, 0) + 1

        company_agg: dict[str, dict] = {}
        for row in rows:
            company = row.get("companies") or {}
            cid = row.get("company_id")
            if not cid:
                continue

            if cid not in company_agg:
                company_agg[cid] = {
                    "company_id": cid,
                    "company_name": company.get("name", "Unknown"),
                    "domain": company.get("domain", ""),
                    "tier": company.get("tier", "?"),
                    "campaign_name": company.get("campaign_name", ""),
                    "intent_score": company.get("intent_score") or 0,
                    "active_intent_signals": intent_counts.get(cid, 0),
                    "won": 0,
                    "demo": 0,
                    "replied": 0,
                    "total_opens": 0,
                    "total_clicks": 0,
                    "positive_sentiments": 0,
                    "composite_score": 0,
                }

            agg = company_agg[cid]
            state = row.get("outreach_state") or ""
            sentiment = row.get("reply_sentiment") or ""
            agg["total_opens"] += row.get("open_count") or 0
            agg["total_clicks"] += row.get("click_count") or 0

            if state == "closed_won":
                agg["won"] += 1
            elif state == "demo_scheduled":
                agg["demo"] += 1
            elif state in ("replied", "nurture"):
                agg["replied"] += 1

            if sentiment == "positive":
                agg["positive_sentiments"] += 1

        # Compute composite score and filter
        hot = []
        for agg in company_agg.values():
            score = (
                agg["intent_score"] * 0.4
                + agg["active_intent_signals"] * 5
                + agg["won"] * 30
                + agg["demo"] * 20
                + agg["replied"] * 10
                + agg["positive_sentiments"] * 5
                + min(agg["total_opens"], 10) * 1
                + min(agg["total_clicks"], 5) * 2
            )
            agg["composite_score"] = round(score, 1)
            if score >= threshold:
                hot.append(agg)

        hot.sort(key=lambda x: x["composite_score"], reverse=True)
        return hot

    # ------------------------------------------------------------------
    # Optimization recommendations
    # ------------------------------------------------------------------

    def get_optimization_recommendations(self) -> list[str]:
        """Data-driven suggestions based on current funnel metrics.

        Returns list of plain-text recommendation strings.
        """
        recs: list[str] = []

        # Funnel health
        funnel = self.funnel.get_funnel_counts(days=30)
        by_touch = self.funnel.get_reply_rate_by_touch(days=30)
        by_persona = self.funnel.get_reply_rate_by_persona(days=30)
        intent_impact = self.funnel.get_intent_signal_impact()
        velocity = self.funnel.get_pipeline_velocity()

        # --- Touch sequence optimization ---
        if by_touch:
            rates = [(r["touch_number"], r["reply_rate_pct"], r["emails_sent"]) for r in by_touch]
            # Find lowest-performing touch with enough volume
            low_touches = [(t, r) for t, r, s in rates if s >= 20 and r < 3.0]
            if low_touches:
                t, r = min(low_touches, key=lambda x: x[1])
                recs.append(
                    f"Touch {t} has the lowest reply rate ({r:.1f}%) — consider "
                    f"rewriting the subject line or shortening the email body."
                )

            # Find the best-performing touch
            high_touches = [(t, r) for t, r, s in rates if s >= 10]
            if high_touches:
                t, r = max(high_touches, key=lambda x: x[1])
                if r > 0:
                    recs.append(
                        f"Touch {t} is your best performer ({r:.1f}% reply rate) — "
                        f"consider using its messaging style in other touches."
                    )

        # --- Persona focus ---
        if by_persona:
            top = by_persona[0] if by_persona[0]["total_sequenced"] >= 5 else None
            if top and top["reply_rate_pct"] > 5:
                persona_label = top["persona_type"].replace("_", " ").title()
                recs.append(
                    f"{persona_label} is your highest-converting persona "
                    f"({top['reply_rate_pct']:.1f}%) — prioritise this role "
                    f"in future prospecting."
                )

        # --- Funnel drop-off ---
        enriched = funnel.get("enriched", 0)
        sequenced = funnel.get("sequenced", 0) + funnel.get("touch_1_sent", 0)
        if enriched > 0 and sequenced == 0:
            recs.append(
                f"You have {enriched} enriched contacts that have not been sequenced. "
                f"Run the push-to-sequences script to activate them."
            )
        elif enriched > 0 and _safe_div(sequenced, enriched) < 20:
            recs.append(
                f"Only {_safe_div(sequenced, enriched):.0f}% of enriched contacts are in sequence. "
                f"Consider a batch push to increase outreach volume."
            )

        # --- Reply rate benchmark ---
        overall_rate = funnel.get("overall_reply_rate", 0.0)
        if overall_rate == 0.0 and funnel.get("touch_1_sent", 0) > 20:
            recs.append(
                "Zero replies recorded despite active sends. "
                "Check your Instantly webhook configuration — events may not be arriving."
            )
        elif 0 < overall_rate < 2.0:
            recs.append(
                f"Reply rate is {overall_rate:.1f}% (below 2% benchmark). "
                f"Review subject lines, personalisation, and ICP fit."
            )

        # --- Intent signal lift ---
        if intent_impact.get("has_meaningful_data") and intent_impact.get("lift_pct", 0) > 5:
            lift = intent_impact["lift_pct"]
            recs.append(
                f"Intent-signal contacts reply {lift:.1f}% more than non-intent contacts. "
                f"Prioritise companies with active intent signals in your daily send queue."
            )

        # --- Velocity ---
        seq_to_reply = velocity.get("sequenced_to_replied_days", 0)
        if seq_to_reply > 21:
            recs.append(
                f"Average sequence-to-reply time is {seq_to_reply:.0f} days — "
                f"consider tightening email spacing to accelerate the cycle."
            )

        # --- Demo conversion ---
        demo_rate = funnel.get("demo_from_reply_rate", 0.0)
        replied = funnel.get("replied", 0)
        if replied >= 5 and demo_rate < 20:
            recs.append(
                f"Only {demo_rate:.1f}% of replies convert to demos. "
                f"Improve your booking CTA or follow-up speed when replies come in."
            )

        if not recs:
            recs.append(
                "Not enough data yet for recommendations. "
                "Run the pipeline for at least 2 weeks before reviewing."
            )

        return recs
