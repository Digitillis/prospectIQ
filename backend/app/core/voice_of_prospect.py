# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: ProspectIQ Technical Team
"""Voice of Prospect Agent — reply corpus intelligence for ProspectIQ.

Analyses all received replies to surface:
  - Messaging themes that resonate vs. block
  - Which personas engage most
  - Where sequences have the highest drop-off

Results are cached in voice_of_prospect_snapshots for 24 hours.

Usage:
    agent = VoiceOfProspectAgent()
    insights = await agent.analyse_workspace(workspace_id)
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from pydantic import BaseModel, Field

from backend.app.core.database import Database
from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic data models
# ---------------------------------------------------------------------------

class MessagingTheme(BaseModel):
    theme: str
    frequency: int
    sentiment: str  # "positive" | "negative" | "neutral"
    example_quote: str


class PersonaEngagement(BaseModel):
    persona_type: str
    reply_count: int
    reply_rate: float
    avg_intent_score: float


class SequenceStepMetrics(BaseModel):
    step_number: int
    step_type: str  # "email" | "linkedin"
    sends: int
    replies: int
    reply_rate: float
    avg_days_to_reply: float
    drop_off: bool  # True if this step's rate is significantly below the previous step


class VoiceInsights(BaseModel):
    workspace_id: str
    analysed_at: datetime
    total_replies_analysed: int
    data_quality: str  # "rich" | "moderate" | "limited" | "demo"

    resonance_themes: list[MessagingTheme] = Field(default_factory=list)
    objection_themes: list[MessagingTheme] = Field(default_factory=list)

    top_performing_angle: str = ""
    top_objection: str = ""
    recommended_adjustment: str = ""

    persona_engagement: list[PersonaEngagement] = Field(default_factory=list)
    sequence_dropoff: list[SequenceStepMetrics] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Demo data — shown when < 5 replies exist
# ---------------------------------------------------------------------------

def _build_demo_insights(workspace_id: str) -> VoiceInsights:
    """Return illustrative demo insights so the UI is never empty."""
    now = datetime.now(timezone.utc)
    return VoiceInsights(
        workspace_id=workspace_id,
        analysed_at=now,
        total_replies_analysed=0,
        data_quality="demo",
        resonance_themes=[
            MessagingTheme(
                theme="ROI and cost savings",
                frequency=14,
                sentiment="positive",
                example_quote="Your numbers around reducing downtime costs caught my attention.",
            ),
            MessagingTheme(
                theme="Efficiency and throughput gains",
                frequency=11,
                sentiment="positive",
                example_quote="We've been struggling with throughput variance — would love to learn more.",
            ),
            MessagingTheme(
                theme="Ease of integration",
                frequency=8,
                sentiment="positive",
                example_quote="Appreciated that you mentioned the plug-and-play approach.",
            ),
            MessagingTheme(
                theme="Real-world case studies",
                frequency=6,
                sentiment="positive",
                example_quote="Do you have examples from automotive suppliers specifically?",
            ),
            MessagingTheme(
                theme="Speed to value",
                frequency=5,
                sentiment="positive",
                example_quote="How quickly can we realistically see results?",
            ),
        ],
        objection_themes=[
            MessagingTheme(
                theme="Timing — budget cycle not aligned",
                frequency=12,
                sentiment="negative",
                example_quote="Q3 budget is already locked. Reach out in October.",
            ),
            MessagingTheme(
                theme="Existing vendor relationship",
                frequency=9,
                sentiment="negative",
                example_quote="We're mid-contract with our current MES provider.",
            ),
            MessagingTheme(
                theme="Internal capacity constraints",
                frequency=7,
                sentiment="negative",
                example_quote="Our team is stretched thin on a plant expansion right now.",
            ),
            MessagingTheme(
                theme="Uncertainty about ROI proof",
                frequency=5,
                sentiment="neutral",
                example_quote="Can you share independent validation data?",
            ),
            MessagingTheme(
                theme="IT/OT security concerns",
                frequency=4,
                sentiment="negative",
                example_quote="We'd need sign-off from IT security before anything moves forward.",
            ),
        ],
        top_performing_angle="ROI language with specific downtime cost figures drives 3× more positive replies than feature-focused messaging.",
        top_objection="Budget timing — most soft-nos cite locked Q3/Q4 budgets or active vendor contracts.",
        recommended_adjustment=(
            "Add a concrete dollar figure to the subject line (e.g. '$240K/yr in avoidable downtime') "
            "and offer a single 20-minute ROI walkthrough as the CTA instead of a generic demo request."
        ),
        persona_engagement=[
            PersonaEngagement(persona_type="VP Operations", reply_count=34, reply_rate=0.34, avg_intent_score=3.8),
            PersonaEngagement(persona_type="Plant Manager", reply_count=28, reply_rate=0.29, avg_intent_score=3.5),
            PersonaEngagement(persona_type="Director of Manufacturing", reply_count=21, reply_rate=0.26, avg_intent_score=3.3),
            PersonaEngagement(persona_type="Engineer", reply_count=15, reply_rate=0.18, avg_intent_score=2.7),
            PersonaEngagement(persona_type="CTO / CIO", reply_count=9, reply_rate=0.14, avg_intent_score=3.1),
        ],
        sequence_dropoff=[
            SequenceStepMetrics(step_number=1, step_type="email", sends=200, replies=52, reply_rate=0.26, avg_days_to_reply=1.4, drop_off=False),
            SequenceStepMetrics(step_number=2, step_type="linkedin", sends=148, replies=21, reply_rate=0.14, avg_days_to_reply=2.1, drop_off=False),
            SequenceStepMetrics(step_number=3, step_type="email", sends=127, replies=8, reply_rate=0.06, avg_days_to_reply=3.9, drop_off=True),
            SequenceStepMetrics(step_number=4, step_type="email", sends=119, replies=5, reply_rate=0.04, avg_days_to_reply=5.2, drop_off=False),
        ],
    )


# ---------------------------------------------------------------------------
# Persona normalisation
# ---------------------------------------------------------------------------

_PERSONA_KEYWORDS: list[tuple[str, list[str]]] = [
    ("VP Operations", ["vp operations", "vp of operations", "vice president operations"]),
    ("Plant Manager", ["plant manager", "plant director", "facility manager"]),
    ("Director of Manufacturing", ["director of manufacturing", "manufacturing director", "director, manufacturing"]),
    ("CTO / CIO", ["cto", "cio", "chief technology", "chief information", "chief digital"]),
    ("Engineer", ["engineer", "engineering manager", "process engineer", "automation engineer"]),
    ("CEO / President", ["ceo", "president", "chief executive", "owner", "founder"]),
    ("Procurement", ["procurement", "purchasing", "supply chain manager", "sourcing"]),
    ("Operations Manager", ["operations manager", "operations director", "head of operations"]),
]

def _normalise_persona(title: str | None) -> str:
    if not title:
        return "Other"
    t = title.lower()
    for persona_name, keywords in _PERSONA_KEYWORDS:
        if any(kw in t for kw in keywords):
            return persona_name
    return "Other"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class VoiceOfProspectAgent:
    """Analyses reply corpus to surface Voice-of-Prospect intelligence."""

    _CACHE_TTL_HOURS = 24

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyse_workspace(self, workspace_id: str) -> VoiceInsights:
        """Full analysis run — queries all replies, analyses with Claude, caches result."""
        db = Database(workspace_id=workspace_id)

        replies = self._fetch_replies(db, workspace_id)
        total = len(replies)

        if total < 5:
            logger.info(f"VoP: workspace {workspace_id} has {total} replies — returning demo insights")
            insights = _build_demo_insights(workspace_id)
            self._persist_snapshot(db, workspace_id, insights)
            return insights

        quality = "rich" if total > 50 else ("moderate" if total >= 10 else "limited")

        resonance, objections = await self._analyse_themes(replies)
        personas = self._compute_persona_engagement(db, workspace_id)
        steps = self._compute_sequence_dropoff(db, workspace_id)
        top_angle, top_objection, recommendation = await self._generate_recommendation(
            resonance, objections, personas, steps
        )

        insights = VoiceInsights(
            workspace_id=workspace_id,
            analysed_at=datetime.now(timezone.utc),
            total_replies_analysed=total,
            data_quality=quality,
            resonance_themes=resonance[:5],
            objection_themes=objections[:5],
            top_performing_angle=top_angle,
            top_objection=top_objection,
            recommended_adjustment=recommendation,
            persona_engagement=sorted(personas, key=lambda p: p.reply_rate, reverse=True),
            sequence_dropoff=steps,
        )

        self._persist_snapshot(db, workspace_id, insights)
        return insights

    async def get_latest_insights(self, workspace_id: str) -> VoiceInsights | None:
        """Return cached snapshot if < 24 h old, else None."""
        db = Database(workspace_id=workspace_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=self._CACHE_TTL_HOURS)).isoformat()
        try:
            result = (
                db.client.table("voice_of_prospect_snapshots")
                .select("*")
                .eq("workspace_id", workspace_id)
                .gte("analysed_at", cutoff)
                .order("analysed_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            if not rows:
                return None
            return self._row_to_insights(rows[0])
        except Exception as e:
            logger.warning(f"VoP get_latest_insights failed: {e}")
            return None

    async def get_messaging_themes(self, workspace_id: str) -> dict[str, list[MessagingTheme]]:
        """Return top 5 resonance themes and top 5 objection themes."""
        cached = await self.get_latest_insights(workspace_id)
        if cached:
            return {"resonance": cached.resonance_themes, "objections": cached.objection_themes}
        insights = await self.analyse_workspace(workspace_id)
        return {"resonance": insights.resonance_themes, "objections": insights.objection_themes}

    async def get_persona_engagement(self, workspace_id: str) -> list[PersonaEngagement]:
        """Reply rate by inferred persona."""
        cached = await self.get_latest_insights(workspace_id)
        if cached:
            return cached.persona_engagement
        insights = await self.analyse_workspace(workspace_id)
        return insights.persona_engagement

    async def get_sequence_dropoff(self, workspace_id: str) -> list[SequenceStepMetrics]:
        """Per-step reply rate across all campaigns."""
        cached = await self.get_latest_insights(workspace_id)
        if cached:
            return cached.sequence_dropoff
        insights = await self.analyse_workspace(workspace_id)
        return insights.sequence_dropoff

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_replies(self, db: Database, workspace_id: str) -> list[dict[str, Any]]:
        """Fetch all replied campaign_threads for the workspace."""
        try:
            result = (
                db.client.table("campaign_threads")
                .select("id, reply_body, subject, replied_at, classification, intent_score, contact_id, sequence_step")
                .eq("workspace_id", workspace_id)
                .eq("replied", True)
                .not_.is_("reply_body", "null")
                .limit(500)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning(f"VoP _fetch_replies failed: {e}")
            return []

    def _compute_persona_engagement(self, db: Database, workspace_id: str) -> list[PersonaEngagement]:
        """Reply rate by normalised persona derived from contact title."""
        try:
            # Fetch all outreach drafts (sends) with their contact's title
            drafts_result = (
                db.client.table("outreach_drafts")
                .select("id, contact_id")
                .eq("workspace_id", workspace_id)
                .execute()
            )
            drafts = drafts_result.data or []

            # Fetch all replied threads with contact_id and intent_score
            replies_result = (
                db.client.table("campaign_threads")
                .select("contact_id, intent_score")
                .eq("workspace_id", workspace_id)
                .eq("replied", True)
                .execute()
            )
            replied_threads = replies_result.data or []

            # Collect unique contact IDs
            contact_ids: set[str] = set()
            for d in drafts:
                if d.get("contact_id"):
                    contact_ids.add(d["contact_id"])
            for r in replied_threads:
                if r.get("contact_id"):
                    contact_ids.add(r["contact_id"])

            if not contact_ids:
                return []

            # Fetch contact titles in batches of 100
            contacts: dict[str, str] = {}  # contact_id → title
            id_list = list(contact_ids)
            for i in range(0, len(id_list), 100):
                batch = id_list[i : i + 100]
                cr = (
                    db.client.table("contacts")
                    .select("id, title")
                    .in_("id", batch)
                    .execute()
                )
                for row in (cr.data or []):
                    contacts[row["id"]] = row.get("title") or ""

            # Aggregate sends per persona
            sends_by_persona: dict[str, int] = {}
            for d in drafts:
                title = contacts.get(d.get("contact_id") or "", "")
                persona = _normalise_persona(title)
                sends_by_persona[persona] = sends_by_persona.get(persona, 0) + 1

            # Aggregate replies per persona
            replies_by_persona: dict[str, list[float]] = {}
            for r in replied_threads:
                title = contacts.get(r.get("contact_id") or "", "")
                persona = _normalise_persona(title)
                score = float(r.get("intent_score") or 0)
                replies_by_persona.setdefault(persona, []).append(score)

            results: list[PersonaEngagement] = []
            for persona, send_count in sends_by_persona.items():
                scores = replies_by_persona.get(persona, [])
                reply_count = len(scores)
                reply_rate = round(reply_count / send_count, 3) if send_count > 0 else 0.0
                avg_intent = round(sum(scores) / len(scores), 2) if scores else 0.0
                results.append(PersonaEngagement(
                    persona_type=persona,
                    reply_count=reply_count,
                    reply_rate=reply_rate,
                    avg_intent_score=avg_intent,
                ))

            return sorted(results, key=lambda p: p.reply_rate, reverse=True)

        except Exception as e:
            logger.warning(f"VoP _compute_persona_engagement failed: {e}")
            return []

    def _compute_sequence_dropoff(self, db: Database, workspace_id: str) -> list[SequenceStepMetrics]:
        """Per-step reply rate across all campaigns."""
        try:
            result = (
                db.client.table("campaign_threads")
                .select("sequence_step, step_type, replied, reply_body, sent_at, replied_at")
                .eq("workspace_id", workspace_id)
                .execute()
            )
            rows = result.data or []

            # Aggregate per step
            step_data: dict[int, dict[str, Any]] = {}
            for row in rows:
                step_num = row.get("sequence_step") or 1
                if step_num not in step_data:
                    step_data[step_num] = {
                        "step_type": row.get("step_type") or "email",
                        "sends": 0,
                        "replies": 0,
                        "days_to_reply": [],
                    }
                step_data[step_num]["sends"] += 1
                if row.get("replied"):
                    step_data[step_num]["replies"] += 1
                    # Compute days to reply if both timestamps available
                    if row.get("sent_at") and row.get("replied_at"):
                        try:
                            sent = datetime.fromisoformat(row["sent_at"].replace("Z", "+00:00"))
                            replied = datetime.fromisoformat(row["replied_at"].replace("Z", "+00:00"))
                            days = max(0.0, (replied - sent).total_seconds() / 86400)
                            step_data[step_num]["days_to_reply"].append(days)
                        except Exception:
                            pass

            if not step_data:
                return []

            sorted_steps = sorted(step_data.keys())
            metrics: list[SequenceStepMetrics] = []
            prev_rate: float | None = None

            for step_num in sorted_steps:
                d = step_data[step_num]
                sends = d["sends"]
                replies = d["replies"]
                rate = round(replies / sends, 3) if sends > 0 else 0.0
                days_list = d["days_to_reply"]
                avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0.0

                # Drop-off: current rate < 50% of previous rate
                drop_off = bool(prev_rate is not None and prev_rate > 0 and rate < prev_rate * 0.5)

                metrics.append(SequenceStepMetrics(
                    step_number=step_num,
                    step_type=d["step_type"],
                    sends=sends,
                    replies=replies,
                    reply_rate=rate,
                    avg_days_to_reply=avg_days,
                    drop_off=drop_off,
                ))
                prev_rate = rate

            return metrics

        except Exception as e:
            logger.warning(f"VoP _compute_sequence_dropoff failed: {e}")
            return []

    # ------------------------------------------------------------------
    # AI analysis
    # ------------------------------------------------------------------

    async def _analyse_themes(
        self, replies: list[dict[str, Any]]
    ) -> tuple[list[MessagingTheme], list[MessagingTheme]]:
        """Extract resonance and objection themes from reply corpus using Haiku."""
        import anthropic

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

        BATCH = 20
        all_resonance: dict[str, dict] = {}
        all_objections: dict[str, dict] = {}

        for i in range(0, len(replies), BATCH):
            batch = replies[i : i + BATCH]
            corpus = "\n\n---\n\n".join(
                f"Reply {j + 1}:\n{(r.get('reply_body') or '').strip()[:400]}"
                for j, r in enumerate(batch)
                if r.get("reply_body")
            )
            if not corpus.strip():
                continue

            prompt = f"""Analyse this batch of sales reply emails. Extract:
1. Up to 5 resonance themes — what messaging or topics prompted positive engagement or genuine curiosity.
2. Up to 5 objection themes — what blocked progress (timing, budget, competitor, capacity, etc.).

For each theme provide:
- theme: short descriptive name (5 words max)
- frequency: how many of these {len(batch)} replies mention it (integer)
- sentiment: "positive" for resonance, "negative" for objections, "neutral" otherwise
- example_quote: a short anonymised verbatim excerpt (max 15 words)

Return ONLY valid JSON with this shape:
{{
  "resonance": [{{"theme": "...", "frequency": N, "sentiment": "positive", "example_quote": "..."}}],
  "objections": [{{"theme": "...", "frequency": N, "sentiment": "negative", "example_quote": "..."}}]
}}

Replies:
{corpus}"""

            try:
                response = client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                parsed = json.loads(raw)

                for item in parsed.get("resonance", []):
                    t = item.get("theme", "").strip()
                    if not t:
                        continue
                    if t in all_resonance:
                        all_resonance[t]["frequency"] += item.get("frequency", 1)
                    else:
                        all_resonance[t] = dict(item)

                for item in parsed.get("objections", []):
                    t = item.get("theme", "").strip()
                    if not t:
                        continue
                    if t in all_objections:
                        all_objections[t]["frequency"] += item.get("frequency", 1)
                    else:
                        all_objections[t] = dict(item)

            except Exception as e:
                logger.warning(f"VoP theme batch {i // BATCH} failed: {e}")
                continue

        resonance = [
            MessagingTheme(
                theme=v["theme"],
                frequency=v.get("frequency", 1),
                sentiment=v.get("sentiment", "positive"),
                example_quote=v.get("example_quote", ""),
            )
            for v in sorted(all_resonance.values(), key=lambda x: x.get("frequency", 0), reverse=True)
        ]
        objections = [
            MessagingTheme(
                theme=v["theme"],
                frequency=v.get("frequency", 1),
                sentiment=v.get("sentiment", "negative"),
                example_quote=v.get("example_quote", ""),
            )
            for v in sorted(all_objections.values(), key=lambda x: x.get("frequency", 0), reverse=True)
        ]

        return resonance[:5], objections[:5]

    async def _generate_recommendation(
        self,
        resonance: list[MessagingTheme],
        objections: list[MessagingTheme],
        personas: list[PersonaEngagement],
        steps: list[SequenceStepMetrics],
    ) -> tuple[str, str, str]:
        """Use Sonnet to synthesise a concrete, actionable recommendation."""
        import anthropic

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

        top_resonance = resonance[0].theme if resonance else "unknown"
        top_objection = objections[0].theme if objections else "unknown"

        best_persona = personas[0].persona_type if personas else "unknown"
        drop_steps = [s.step_number for s in steps if s.drop_off]

        prompt = f"""You are an expert B2B sales strategist. Based on reply analysis:

Top resonance theme: {top_resonance}
Top objection theme: {top_objection}
Best-responding persona: {best_persona} ({personas[0].reply_rate * 100:.0f}% reply rate if {personas} else 'n/a')
Sequence drop-off detected at steps: {drop_steps if drop_steps else 'none'}

Write:
1. top_performing_angle: One sentence (max 20 words) describing the single best-performing messaging approach.
2. top_objection: One sentence (max 15 words) naming the most common blocker.
3. recommended_adjustment: One concrete, actionable change a rep should make to their sequence this week. Max 2 sentences.

Return ONLY valid JSON:
{{"top_performing_angle": "...", "top_objection": "...", "recommended_adjustment": "..."}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            return (
                parsed.get("top_performing_angle", top_resonance),
                parsed.get("top_objection", top_objection),
                parsed.get("recommended_adjustment", ""),
            )
        except Exception as e:
            logger.warning(f"VoP _generate_recommendation failed: {e}")
            return (
                top_resonance,
                top_objection,
                f"Double down on '{top_resonance}' messaging and address '{top_objection}' proactively in step 1.",
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_snapshot(self, db: Database, workspace_id: str, insights: VoiceInsights) -> None:
        """Upsert the latest snapshot to the DB (keeps history intact)."""
        try:
            db.client.table("voice_of_prospect_snapshots").insert({
                "workspace_id": workspace_id,
                "total_replies_analysed": insights.total_replies_analysed,
                "data_quality": insights.data_quality,
                "resonance_themes": [t.model_dump() for t in insights.resonance_themes],
                "objection_themes": [t.model_dump() for t in insights.objection_themes],
                "persona_engagement": [p.model_dump() for p in insights.persona_engagement],
                "sequence_dropoff": [s.model_dump() for s in insights.sequence_dropoff],
                "top_performing_angle": insights.top_performing_angle,
                "top_objection": insights.top_objection,
                "recommended_adjustment": insights.recommended_adjustment,
                "analysed_at": insights.analysed_at.isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"VoP _persist_snapshot failed: {e}")

    def _row_to_insights(self, row: dict[str, Any]) -> VoiceInsights:
        """Deserialise a DB row into a VoiceInsights object."""
        def _themes(raw: Any) -> list[MessagingTheme]:
            if not raw:
                return []
            items = raw if isinstance(raw, list) else json.loads(raw)
            return [MessagingTheme(**item) for item in items]

        def _personas(raw: Any) -> list[PersonaEngagement]:
            if not raw:
                return []
            items = raw if isinstance(raw, list) else json.loads(raw)
            return [PersonaEngagement(**item) for item in items]

        def _steps(raw: Any) -> list[SequenceStepMetrics]:
            if not raw:
                return []
            items = raw if isinstance(raw, list) else json.loads(raw)
            return [SequenceStepMetrics(**item) for item in items]

        analysed_at_raw = row.get("analysed_at")
        if isinstance(analysed_at_raw, str):
            analysed_at = datetime.fromisoformat(analysed_at_raw.replace("Z", "+00:00"))
        elif isinstance(analysed_at_raw, datetime):
            analysed_at = analysed_at_raw
        else:
            analysed_at = datetime.now(timezone.utc)

        return VoiceInsights(
            workspace_id=str(row["workspace_id"]),
            analysed_at=analysed_at,
            total_replies_analysed=row.get("total_replies_analysed") or 0,
            data_quality=row.get("data_quality") or "demo",
            resonance_themes=_themes(row.get("resonance_themes")),
            objection_themes=_themes(row.get("objection_themes")),
            persona_engagement=_personas(row.get("persona_engagement")),
            sequence_dropoff=_steps(row.get("sequence_dropoff")),
            top_performing_angle=row.get("top_performing_angle") or "",
            top_objection=row.get("top_objection") or "",
            recommended_adjustment=row.get("recommended_adjustment") or "",
        )
