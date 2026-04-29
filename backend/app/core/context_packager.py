"""GTM Context Packager — builds a reusable, cacheable prompt prefix.

Merges the ICP YAML config + proven learnings from the intelligence store
into a single string injected into every Claude call. Using Anthropic's
prompt caching, this prefix is charged at ~10% of normal input token cost
after the first call in a 5-minute window.

Usage:
    from backend.app.core.context_packager import build_context_block

    # Returns an Anthropic content block with cache_control set
    block = build_context_block(workspace_id)

    # Pass as the first element of the system list in your Claude call:
    response = client.messages.create(
        model=model,
        system=[block, {"type": "text", "text": task_specific_prompt}],
        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        ...
    )
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from backend.app.core.config import get_icp_config, get_offer_context

logger = logging.getLogger(__name__)

# In-process cache: workspace_id → (context_string, built_at_epoch)
_CONTEXT_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes — learnings update slowly


def build_context_block(
    workspace_id: str,
    db: Any | None = None,
    force_refresh: bool = False,
) -> dict:
    """Build a prompt-cacheable context block for Claude system prompts.

    Combines:
      1. ICP definition (tiers, industries, firmographics, personas)
      2. Value proposition + offer context
      3. Proven learnings from intelligence store (confidence_level = 'proven')

    The returned dict is an Anthropic content block with cache_control set.
    Pass it as the FIRST element of the `system` list in any Claude call,
    and include `anthropic-beta: prompt-caching-2024-07-31` in extra_headers.

    Args:
        workspace_id: Workspace to pull learnings for.
        db: Database instance (optional). If None, learnings are skipped.
        force_refresh: Bypass the in-process 5-minute TTL cache.

    Returns:
        Dict with keys: type, text, cache_control
    """
    context_str = _get_cached_context(workspace_id, db, force_refresh)
    return {
        "type": "text",
        "text": context_str,
        "cache_control": {"type": "ephemeral"},
    }


def build_context_string(
    workspace_id: str,
    db: Any | None = None,
    force_refresh: bool = False,
) -> str:
    """Return just the context string (for non-structured Claude callers)."""
    return _get_cached_context(workspace_id, db, force_refresh)


def _get_cached_context(
    workspace_id: str,
    db: Any | None,
    force_refresh: bool,
) -> str:
    """Return context from in-process cache or rebuild if stale."""
    now = time.monotonic()
    cached = _CONTEXT_CACHE.get(workspace_id)

    if not force_refresh and cached:
        ctx, built_at = cached
        if now - built_at < _CACHE_TTL_SECONDS:
            return ctx

    ctx = _build_context_string(workspace_id, db)
    _CONTEXT_CACHE[workspace_id] = (ctx, now)
    return ctx


def _build_context_string(workspace_id: str, db: Any | None) -> str:
    """Build the full context string from ICP config + learnings."""
    parts: list[str] = [
        "## PROSPECTIQ GTM OPERATING CONTEXT",
        "This context defines the Ideal Customer Profile, value proposition, and proven",
        "learnings from real campaign outcomes. Apply this to every decision you make.",
        "",
    ]

    # --- ICP definition ---
    try:
        icp = get_icp_config()
        parts += _format_icp(icp)
    except Exception as e:
        logger.warning(f"context_packager: could not load ICP config: {e}")

    # --- Offer context ---
    try:
        offer = get_offer_context()
        parts += _format_offer(offer)
    except Exception as e:
        logger.warning(f"context_packager: could not load offer context: {e}")

    # --- Proven learnings from DB ---
    if db is not None:
        try:
            learnings = _fetch_proven_learnings(workspace_id, db)
            if learnings:
                parts += _format_learnings(learnings)
        except Exception as e:
            logger.warning(f"context_packager: could not fetch learnings: {e}")

    return "\n".join(parts)


def _format_icp(icp: dict) -> list[str]:
    """Serialise ICP YAML into a compact prompt-friendly format."""
    lines = ["### ICP DEFINITION"]

    # Firmographics
    firm = icp.get("firmographic_filters", {})
    if firm:
        lines += [
            f"Employee count: {firm.get('employee_count_min', 300)}–{firm.get('employee_count_max', 3500)}",
            f"Revenue range: {firm.get('revenue_range_min', '$100M')}–{firm.get('revenue_range_max', '$2B')}",
        ]

    # Industry tiers
    tiers = icp.get("tiers", {})
    if tiers:
        lines.append("Industry tiers (priority order):")
        for tier_name, tier_data in list(tiers.items())[:6]:  # Top 6 tiers
            label = tier_data.get("label", tier_name)
            industries = tier_data.get("apollo_industries", [])[:3]
            lines.append(f"  {tier_name}: {label} — e.g. {', '.join(industries)}")

    # Contact filters
    contact = icp.get("contact_filters", {})
    titles = contact.get("title_patterns", [])[:8]
    if titles:
        lines.append(f"Target titles: {', '.join(titles[:8])}")

    lines.append("")
    return lines


def _format_offer(offer: dict) -> list[str]:
    """Serialise offer context into a compact prompt-friendly format."""
    lines = ["### VALUE PROPOSITION"]

    core_vp = (offer.get("core_value_prop") or "").strip()
    if core_vp:
        lines.append(core_vp)

    capabilities = offer.get("capabilities", [])[:4]
    if capabilities:
        lines.append("Key capabilities:")
        for cap in capabilities:
            name = cap.get("name", "") if isinstance(cap, dict) else str(cap)
            lines.append(f"  - {name}")

    proof = offer.get("proof_points", [])[:3]
    if proof:
        lines.append("Proof points:")
        for p in proof:
            lines.append(f"  - {p}")

    lines.append("")
    return lines


def _format_learnings(learnings: list[dict]) -> list[str]:
    """Serialise proven learnings into a compact prompt-friendly format."""
    lines = [
        "### PROVEN LEARNINGS (from real campaign data)",
        "These are statistically validated insights. Prefer approaches consistent with them.",
        "",
    ]
    for idx, item in enumerate(learnings[:10], 1):  # Cap at 10 to control token use
        summary = item.get("insight_summary") or item.get("notes", "")
        segment = item.get("segment", "")
        channel = item.get("channel", "")
        evidence = item.get("evidence_count", 0)
        context_tags = " | ".join(filter(None, [segment, channel]))
        lines.append(
            f"{idx}. [{context_tags}] {summary} (evidence: {evidence} data points)"
        )
    lines.append("")
    return lines


def _fetch_proven_learnings(workspace_id: str, db: Any) -> list[dict]:
    """Fetch proven learnings from learning_outcomes table."""
    result = (
        db.client.table("learning_outcomes")
        .select("insight_summary, notes, segment, channel, evidence_count")
        .eq("workspace_id", workspace_id)
        .eq("confidence_level", "proven")
        .order("evidence_count", desc=True)
        .limit(10)
        .execute()
    )
    return result.data or []
