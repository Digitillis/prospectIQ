"""Tiered title classifier — three-pass system for ambiguous job titles.

Pass 1 (deterministic, free): keyword whitelist/blacklist in contact_filter.py.
  Handles ~80% of cases: "CEO", "VP Operations" → target; "HR Manager" → excluded.

Pass 2 (Haiku, cached by title+industry): for ambiguous titles that keyword
  matching cannot resolve confidently. Examples:
  - "Director of Continuous Improvement" (ops-adjacent, target)
  - "Plant Operations Lead" (target)
  - "Business Development" (context-dependent)
  Cost: ~$0.001/classification. Cached in title_classifications table by
  (normalized_title, industry) — only runs once per unique pair.

Pass 3 (human review queue): low-confidence outputs from Pass 2 flow to
  title_review_queue table. Human disposition writes to title_classifications
  as a confirmed override. Pass 1 checks this table first on future occurrences.

Usage:
    from backend.app.core.title_classifier import TitleClassifier
    tc = TitleClassifier(db)
    tier, confidence, source = tc.classify(title="Director of Lean Transformation",
                                            industry="food manufacturing")
    # Returns: ('target', 0.85, 'haiku')
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
LOW_CONFIDENCE_THRESHOLD = 0.65

_CLASSIFICATION_PROMPT = """You are classifying a B2B contact for cold outreach targeting.

Product context: AI platform for predictive maintenance, quality control, and operational
intelligence in manufacturing and food & beverage plants.

Target buyers are people who own operational problems:
  - Plant/site/facility managers
  - VP/Director Operations, Manufacturing, Quality
  - Maintenance/Reliability/Engineering leaders
  - COO, CTO, or other operational C-level
  - Continuous improvement, lean, EHS, or process leaders (context-dependent)

Non-buyers (do not outreach):
  - Sales, marketing, HR, legal, finance, accounting
  - Customer service, customer success
  - Purchasing/procurement (unless director level or above)

Job title to classify: "{title}"
Company industry: {industry}

Return ONLY valid JSON:
{{
  "tier": "target" | "borderline" | "excluded",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explaining the classification"
}}

tier definitions:
  target    — clearly a buyer persona for operational AI
  borderline — might be relevant but needs human confirmation
  excluded  — not a buyer; never send cold outreach"""


def _normalize_title(title: str) -> str:
    """Normalize title for cache key."""
    return re.sub(r"\s+", " ", title.lower().strip())


def _cache_key(title: str, industry: str) -> str:
    raw = f"{_normalize_title(title)}|{(industry or '').lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class TitleClassifier:
    def __init__(self, db: Any = None, settings: Any = None):
        self._db = db
        self._settings = settings

    def classify(
        self, title: str | None, industry: str | None = None
    ) -> tuple[str, float, str]:
        """Classify a job title into tier, returning (tier, confidence, source).

        source: 'deterministic', 'human_override', 'haiku', 'haiku_cache', 'fallback'

        Always runs Pass 1 first. Only calls Haiku for ambiguous cases.
        """
        if not title or not title.strip():
            return "target", 1.0, "deterministic"  # No title — benefit of the doubt

        # Pass 0: check human override table first (confirmed decisions persist)
        if self._db:
            override = self._check_human_override(title, industry)
            if override:
                return override["tier"], 1.0, "human_override"

        # Pass 1: deterministic classifier (fast, free)
        from backend.app.core.contact_filter import classify_contact_tier
        tier_p1 = classify_contact_tier(title)

        # Deterministic classifier is confident on clear cases — skip Haiku
        if tier_p1 in ("target", "excluded"):
            # Only send to Haiku if title contains signals suggesting it might be wrong
            # (e.g., "Director of Business Development" — excluded but C-level + BD is borderline)
            has_ambiguity = any(sig in title.lower() for sig in (
                "business development", "lean", "continuous improvement", "ehs",
                "logistics", "supply chain", "r&d", "research", "technology", "it "
            ))
            if not has_ambiguity:
                return tier_p1, 0.95, "deterministic"

        # Pass 1 returned borderline or ambiguous title — go to Haiku
        if self._db:
            cached = self._check_haiku_cache(title, industry)
            if cached:
                return cached["tier"], cached["confidence"], "haiku_cache"

        haiku_result = self._call_haiku(title, industry)
        if haiku_result:
            tier = haiku_result.get("tier", tier_p1)
            confidence = haiku_result.get("confidence", 0.5)

            if self._db:
                self._cache_haiku_result(title, industry, tier, confidence, haiku_result.get("reasoning", ""))

                # Pass 3: queue for human review if low confidence
                if confidence < LOW_CONFIDENCE_THRESHOLD:
                    self._queue_for_review(title, industry, tier, confidence, haiku_result.get("reasoning", ""))

            return tier, confidence, "haiku"

        # Haiku failed — fall back to deterministic result
        return tier_p1, 0.6, "fallback"

    def _check_human_override(self, title: str, industry: str | None) -> dict | None:
        key = _cache_key(title, industry or "")
        try:
            rows = (
                self._db.client.table("title_classifications")
                .select("tier,confidence,source")
                .eq("cache_key", key)
                .eq("source", "human")
                .limit(1)
                .execute()
                .data or []
            )
            return rows[0] if rows else None
        except Exception:
            return None

    def _check_haiku_cache(self, title: str, industry: str | None) -> dict | None:
        key = _cache_key(title, industry or "")
        try:
            rows = (
                self._db.client.table("title_classifications")
                .select("tier,confidence")
                .eq("cache_key", key)
                .neq("source", "human")
                .limit(1)
                .execute()
                .data or []
            )
            return rows[0] if rows else None
        except Exception:
            return None

    def _call_haiku(self, title: str, industry: str | None) -> dict | None:
        try:
            import anthropic
            settings = self._settings
            if not settings:
                from backend.app.core.config import get_settings
                settings = get_settings()
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            prompt = _CLASSIFICATION_PROMPT.format(
                title=title[:200],
                industry=industry or "manufacturing",
            )
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
            return json.loads(raw.strip())
        except Exception as e:
            logger.warning("Haiku title classification failed for %r: %s", title, e)
            return None

    def _cache_haiku_result(self, title: str, industry: str | None,
                             tier: str, confidence: float, reasoning: str) -> None:
        key = _cache_key(title, industry or "")
        try:
            self._db.client.table("title_classifications").upsert({
                "cache_key": key,
                "title": title[:255],
                "industry": industry or "",
                "tier": tier,
                "confidence": confidence,
                "reasoning": reasoning,
                "source": "haiku",
            }, on_conflict="cache_key").execute()
        except Exception as e:
            logger.warning("Could not cache Haiku result: %s", e)

    def _queue_for_review(self, title: str, industry: str | None,
                           tier: str, confidence: float, reasoning: str) -> None:
        try:
            self._db.client.table("title_review_queue").insert({
                "title": title[:255],
                "industry": industry or "",
                "haiku_tier": tier,
                "haiku_confidence": confidence,
                "haiku_reasoning": reasoning,
                "status": "pending",
            }).execute()
        except Exception as e:
            logger.warning("Could not queue title for review: %s", e)


# Allow Any type without importing for type hint clarity
from typing import Any  # noqa: E402 — placed at end to avoid circular imports
