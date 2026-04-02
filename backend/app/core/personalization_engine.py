"""Personalization Engine — unified pipeline for ProspectIQ.

Takes company research → infers contact personas → identifies buying
triggers → generates personalized message hooks → computes a readiness
score.  Results are persisted back to the company and contact records
so the rest of the platform (outreach agent, drafts) can consume them.

Usage:
    engine = PersonalizationEngine()
    result = engine.run_full_pipeline(company_id="...", workspace_id="...")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import Database
from backend.app.core.config import get_settings
from backend.app.core.personalization_models import (
    TriggerEvent,
    PersonalizationHook,
    PersonalizationResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persona mapping — heuristic, no AI needed
# ---------------------------------------------------------------------------

_PERSONA_RULES: list[tuple[list[str], list[str], str]] = [
    # (title_keywords, seniority_keywords, persona)
    (
        ["vp", "vice president", "director", "head of"],
        ["operations", "manufacturing", "supply chain", "ops"],
        "vp_ops",
    ),
    (
        ["plant manager", "facility manager", "site manager", "plant director"],
        [],
        "plant_manager",
    ),
    (
        ["engineer", "technician", "maintenance", "reliability"],
        [],
        "engineer",
    ),
    (
        ["procurement", "purchasing", "supply chain", "sourcing", "buyer"],
        [],
        "procurement",
    ),
    (
        ["ceo", "coo", "president", "owner", "founder", "chief executive", "chief operating"],
        [],
        "executive",
    ),
]

_DEFAULT_PERSONA = "operations_general"


def _classify_persona(title: str | None, seniority: str | None, department: str | None) -> str:
    """Pure heuristic persona classification — O(1), no network call."""
    if not title:
        return _DEFAULT_PERSONA

    t = (title or "").lower()
    s = (seniority or "").lower()
    d = (department or "").lower()
    combined = f"{t} {s} {d}"

    for title_kws, context_kws, persona in _PERSONA_RULES:
        title_match = any(kw in t for kw in title_kws)
        if not title_match:
            continue
        if context_kws:
            context_match = any(kw in combined for kw in context_kws)
            if not context_match:
                continue
        return persona

    # Second pass — context words in title alone (e.g. "Plant Manager" or "VP Operations")
    for title_kws, _, persona in _PERSONA_RULES:
        if any(kw in t for kw in title_kws):
            return persona

    return _DEFAULT_PERSONA


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_TRIGGER_EXTRACTION_SYSTEM = """You are a buying-signal analyst for a manufacturing AI platform.
Extract buying triggers from company research text.

Output ONLY a valid JSON array of trigger objects. Each object:
{
  "trigger_type": "growth" | "pain" | "tech" | "timing",
  "description": "<one concise sentence describing the trigger>",
  "urgency": "immediate" | "near_term" | "background",
  "confidence": 0.0–1.0,
  "source_text": "<verbatim phrase from research that supports this trigger>"
}

Trigger categories:
- growth: hiring surge, new facility, expansion, acquisition, new customer win
- pain: downtime, quality issues, recalls, cost pressure, workforce challenges
- tech: legacy system mention, ERP/MES migration, digital transformation, Industry 4.0 initiative
- timing: budget cycle mention, fiscal year end, initiative launch, leadership change

Urgency rules:
- immediate: event happened in last 90 days OR leadership change OR active incident
- near_term: planned initiative, upcoming change, near-term budget cycle
- background: general pain point, ongoing challenge without recent trigger

Return [] if no triggers found. Output ONLY the JSON array."""

_HOOK_GENERATION_SYSTEM = """You are a senior manufacturing sales strategist.
Generate personalized email opening hooks for outreach to manufacturing companies.

Each hook must be:
- A single sentence (max 30 words)
- Specific to this company's actual situation (use the details provided)
- Immediately relevant to the persona receiving it
- Never generic — no "I noticed your company" or "As a leader in..."

Output ONLY a valid JSON array of hook objects. Each object:
{
  "hook_text": "<the opening sentence>",
  "persona_target": "<persona slug from input>",
  "trigger_reference": "<which trigger this hooks into>",
  "tone": "specific" | "empathetic" | "provocative",
  "confidence": 0.0–1.0
}

Tone guide:
- specific: anchors to a specific fact (facility, system, event, metric)
- empathetic: acknowledges a pain or challenge they're navigating
- provocative: challenges an assumption or frames an uncomfortable truth

Return [] if insufficient data. Output ONLY the JSON array."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PersonalizationEngine:
    """Unified personalization pipeline for a single company."""

    def __init__(self, workspace_id: str | None = None):
        self.db = Database(workspace_id=None)  # service-role; no workspace filter at DB level
        self.workspace_id = workspace_id
        self._cost_accumulator: float = 0.0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_full_pipeline(self, company_id: str, workspace_id: str | None = None) -> PersonalizationResult:
        """Run the full personalization pipeline for one company.

        Steps:
        1. Load company + contacts
        2. Infer contact personas (heuristic — free)
        3. Extract buying triggers from research (Claude Haiku)
        4. Score trigger urgency
        5. Generate personalization hooks (Claude Sonnet)
        6. Compute readiness score
        7. Persist results
        """
        ws_id = workspace_id or self.workspace_id
        self._cost_accumulator = 0.0

        company = self.db.get_company(company_id)
        if not company:
            raise ValueError(f"Company {company_id} not found")

        contacts = self.db.get_contacts_for_company(company_id)

        # Step 2 — persona inference
        contacts_with_persona = self._infer_personas(contacts)

        # Step 3 — trigger extraction
        triggers = self._extract_triggers(company)

        # Step 4 — urgency scoring
        triggers = self._score_trigger_urgency(triggers)

        # Step 5 — hook generation
        personas_found = list({c["inferred_persona"] for c in contacts_with_persona})
        hooks = self._generate_hooks(company, personas_found, triggers)

        # Step 6 — readiness score
        contacts_updated = self._persist_personas(contacts, contacts_with_persona)
        readiness_score, readiness_breakdown = self._compute_readiness_score(
            company, contacts, hooks, triggers
        )

        # Step 7 — persist to company
        self._persist_results(company_id, triggers, hooks, readiness_score)

        generated_at = datetime.now(timezone.utc).isoformat()

        return PersonalizationResult(
            company_id=company_id,
            readiness_score=readiness_score,
            readiness_breakdown=readiness_breakdown,
            triggers=triggers,
            hooks=hooks,
            personas_found=personas_found,
            contacts_updated=contacts_updated,
            generated_at=generated_at,
            cost_usd=round(self._cost_accumulator, 6),
        )

    # ------------------------------------------------------------------
    # Step 2 — persona inference
    # ------------------------------------------------------------------

    def _infer_personas(self, contacts: list[dict]) -> list[dict]:
        """Enrich each contact dict with inferred_persona field."""
        enriched = []
        for c in contacts:
            persona = _classify_persona(
                c.get("title"),
                c.get("seniority"),
                c.get("department"),
            )
            enriched.append({**c, "inferred_persona": persona})
        return enriched

    def _persist_personas(self, original_contacts: list[dict], enriched: list[dict]) -> int:
        """Write inferred persona back to DB for contacts that had no persona_type."""
        updated = 0
        for enriched_c in enriched:
            original = next((c for c in original_contacts if c["id"] == enriched_c["id"]), None)
            if original and not original.get("persona_type"):
                try:
                    self.db.update_contact(
                        enriched_c["id"],
                        {"persona_type": enriched_c["inferred_persona"]},
                    )
                    updated += 1
                except Exception as e:
                    logger.warning(f"Failed to update persona for contact {enriched_c['id']}: {e}")
        return updated

    # ------------------------------------------------------------------
    # Step 3 — trigger extraction (Claude Haiku)
    # ------------------------------------------------------------------

    def _extract_triggers(self, company: dict) -> list[TriggerEvent]:
        """Extract buying triggers from research_summary using Claude Haiku."""
        research = self._build_research_context(company)
        if not research:
            logger.debug(f"No research context for company {company.get('id')} — skipping trigger extraction")
            return []

        settings = get_settings()
        if not settings.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY not set — skipping trigger extraction")
            return []

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = (
            f"Company: {company.get('name', 'Unknown')}\n"
            f"Industry: {company.get('industry', 'Manufacturing')}\n"
            f"Location: {company.get('city', '')}, {company.get('state', '')}\n\n"
            f"Research context:\n{research}"
        )

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                system=_TRIGGER_EXTRACTION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            self._accumulate_cost("claude-haiku-4-5-20251001", response.usage)

            raw = response.content[0].text.strip()
            raw = self._strip_markdown(raw)
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []

            triggers = []
            for item in parsed:
                try:
                    triggers.append(TriggerEvent(**item))
                except Exception:
                    continue
            return triggers

        except json.JSONDecodeError as e:
            logger.warning(f"Trigger extraction JSON parse error for {company.get('name')}: {e}")
            return []
        except Exception as e:
            logger.error(f"Trigger extraction failed for {company.get('name')}: {e}")
            return []

    # ------------------------------------------------------------------
    # Step 4 — urgency scoring
    # ------------------------------------------------------------------

    def _score_trigger_urgency(self, triggers: list[TriggerEvent]) -> list[TriggerEvent]:
        """Sort triggers by urgency then confidence; assign priority_rank."""
        urgency_order = {"immediate": 0, "near_term": 1, "background": 2}
        sorted_triggers = sorted(
            triggers,
            key=lambda t: (urgency_order.get(t.urgency, 3), -t.confidence),
        )
        for rank, trigger in enumerate(sorted_triggers, start=1):
            trigger.priority_rank = rank
        return sorted_triggers

    # ------------------------------------------------------------------
    # Step 5 — hook generation (Claude Sonnet)
    # ------------------------------------------------------------------

    def _generate_hooks(
        self,
        company: dict,
        personas_found: list[str],
        triggers: list[TriggerEvent],
    ) -> list[PersonalizationHook]:
        """Generate personalized hooks using Claude Sonnet."""
        if not personas_found and not triggers:
            return []

        settings = get_settings()
        if not settings.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY not set — skipping hook generation")
            return []

        # Target top 3 persona types only
        target_personas = personas_found[:3]
        top_triggers = triggers[:5]  # feed top 5 triggers max

        trigger_summary = "\n".join(
            f"- [{t.urgency.upper()}] {t.trigger_type}: {t.description}"
            for t in top_triggers
        ) or "No specific triggers identified."

        company_context = (
            f"Company: {company.get('name', 'Unknown')}\n"
            f"Industry: {company.get('industry', 'Manufacturing')}\n"
            f"Location: {company.get('city', '')}, {company.get('state', '')}\n"
            f"Size: {company.get('employee_count', 'unknown')} employees\n"
            f"Research summary: {company.get('research_summary', '')}\n"
            f"Pain signals: {', '.join(company.get('pain_signals') or [])}\n"
            f"Technology stack: {', '.join(company.get('technology_stack') or [])}\n"
            f"Buying triggers:\n{trigger_summary}\n"
            f"Personas to cover: {', '.join(target_personas)}\n\n"
            "Generate 2-3 hooks per persona listed above (max 9 total hooks)."
        )

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1800,
                system=_HOOK_GENERATION_SYSTEM,
                messages=[{"role": "user", "content": company_context}],
            )
            self._accumulate_cost("claude-sonnet-4-6", response.usage)

            raw = response.content[0].text.strip()
            raw = self._strip_markdown(raw)
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []

            hooks = []
            for item in parsed:
                try:
                    hooks.append(PersonalizationHook(**item))
                except Exception:
                    continue
            return hooks

        except json.JSONDecodeError as e:
            logger.warning(f"Hook generation JSON parse error for {company.get('name')}: {e}")
            return []
        except Exception as e:
            logger.error(f"Hook generation failed for {company.get('name')}: {e}")
            return []

    # ------------------------------------------------------------------
    # Step 6 — readiness score
    # ------------------------------------------------------------------

    def _compute_readiness_score(
        self,
        company: dict,
        contacts: list[dict],
        hooks: list[PersonalizationHook],
        triggers: list[TriggerEvent],
    ) -> tuple[int, dict]:
        """Compute 0-100 personalization readiness score with breakdown.

        Scoring bands:
          0-25:  research present
          26-50: + contacts with personas enriched
          51-75: + triggers identified
          76-90: + hooks generated with decent confidence
          91-100: + multiple personas covered + immediate trigger present
        """
        breakdown: dict[str, int] = {"research": 0, "contacts": 0, "triggers": 0, "hooks": 0}
        score = 0

        # Research band (0-25)
        has_research = bool(company.get("research_summary"))
        has_pain_signals = bool(company.get("pain_signals"))
        if has_research:
            score += 20
            breakdown["research"] = 20
        if has_pain_signals:
            score += 5
            breakdown["research"] += 5

        # Contacts band (26-50: up to +25 more)
        enriched_contacts = [c for c in contacts if c.get("persona_type") or c.get("title")]
        if enriched_contacts:
            contact_pts = min(25, len(enriched_contacts) * 5)
            score += contact_pts
            breakdown["contacts"] = contact_pts

        # Triggers band (51-75: up to +25 more)
        if triggers:
            trigger_pts = min(20, len(triggers) * 5)
            high_confidence = sum(1 for t in triggers if t.confidence >= 0.7)
            trigger_pts += min(5, high_confidence * 2)
            score += trigger_pts
            breakdown["triggers"] = trigger_pts

        # Hooks band (76-90: up to +15 more)
        if hooks:
            avg_confidence = sum(h.confidence for h in hooks) / len(hooks) if hooks else 0
            hook_pts = min(15, int(avg_confidence * 15))
            score += hook_pts
            breakdown["hooks"] = hook_pts

        # Excellence bonus (91-100: up to +10 more)
        bonus = 0
        persona_set = {h.persona_target for h in hooks}
        has_immediate = any(t.urgency == "immediate" for t in triggers)
        if len(persona_set) >= 2:
            bonus += 5
        if has_immediate:
            bonus += 5
        score += bonus
        if bonus:
            breakdown["hooks"] = breakdown.get("hooks", 0) + bonus

        return min(100, score), breakdown

    # ------------------------------------------------------------------
    # Step 7 — persist
    # ------------------------------------------------------------------

    def _persist_results(
        self,
        company_id: str,
        triggers: list[TriggerEvent],
        hooks: list[PersonalizationHook],
        readiness_score: int,
    ) -> None:
        """Write personalization results back to the company record."""
        hook_texts = [h.hook_text for h in hooks]
        trigger_dicts = [t.model_dump() for t in triggers]

        now = datetime.now(timezone.utc).isoformat()

        try:
            existing = self.db.get_company(company_id) or {}
            existing_tags = existing.get("custom_tags") or {}
            if isinstance(existing_tags, str):
                try:
                    existing_tags = json.loads(existing_tags)
                except Exception:
                    existing_tags = {}

            updated_tags = {
                **existing_tags,
                "personalization_readiness": readiness_score,
                "personalization_triggers": trigger_dicts,
                "personalization_last_run": now,
            }

            self.db.update_company(company_id, {
                "personalization_hooks": hook_texts,
                "custom_tags": updated_tags,
            })
        except Exception as e:
            logger.error(f"Failed to persist personalization results for {company_id}: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_research_context(self, company: dict) -> str:
        """Assemble research text from available company fields."""
        parts = []

        summary = company.get("research_summary") or ""
        if summary:
            parts.append(f"Description: {summary}")

        pain_signals = company.get("pain_signals") or []
        if pain_signals:
            parts.append(f"Pain signals: {', '.join(pain_signals)}")

        tech_stack = company.get("technology_stack") or []
        if tech_stack:
            parts.append(f"Technology stack: {', '.join(tech_stack)}")

        mfg_profile = company.get("manufacturing_profile") or {}
        if isinstance(mfg_profile, str):
            try:
                mfg_profile = json.loads(mfg_profile)
            except Exception:
                mfg_profile = {}
        if mfg_profile:
            iot = mfg_profile.get("iot_maturity", "")
            maint = mfg_profile.get("maintenance_approach", "")
            if iot:
                parts.append(f"IoT maturity: {iot}")
            if maint:
                parts.append(f"Maintenance approach: {maint}")

        hooks = company.get("personalization_hooks") or []
        if hooks:
            parts.append(f"Existing hooks: {'; '.join(hooks[:3])}")

        return "\n".join(parts)

    def _strip_markdown(self, text: str) -> str:
        """Remove markdown code fences from Claude output."""
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # drop opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _accumulate_cost(self, model: str, usage: Any) -> None:
        """Estimate and accumulate cost for a Claude call."""
        # Pricing per million tokens (approximate, 2025)
        pricing: dict[str, dict[str, float]] = {
            "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
            "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        }
        rates = pricing.get(model, {"input": 3.00, "output": 15.00})
        input_cost = (getattr(usage, "input_tokens", 0) / 1_000_000) * rates["input"]
        output_cost = (getattr(usage, "output_tokens", 0) / 1_000_000) * rates["output"]
        self._cost_accumulator += input_cost + output_cost
