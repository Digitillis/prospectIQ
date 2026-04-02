"""Tier comparison helpers.

Platform supplies its own TierPlan instances; this module provides
utilities for comparing and serializing them.
"""

from __future__ import annotations

from billing_sdk.types import TierPlan


def tier_index(tier: str, tier_order: list[str]) -> int:
    """Return the numeric rank of a tier within an ordered list.

    Higher index = more capable / more expensive.
    Returns 0 (lowest) for unknown tiers.
    """
    try:
        return tier_order.index(tier)
    except ValueError:
        return 0


def is_upgrade_available(current_tier: str, tier_order: list[str]) -> bool:
    """Return True if the workspace can still upgrade to a higher tier."""
    idx = tier_index(current_tier, tier_order)
    return idx < len(tier_order) - 1


def get_plan(tier: str, tier_plans: dict[str, TierPlan], default: str = "free") -> TierPlan:
    """Return the TierPlan for a tier slug, falling back to `default`."""
    return tier_plans.get(tier) or tier_plans[default]


def plans_as_dicts(tier_plans: dict[str, TierPlan]) -> list[dict]:
    """Serialise all plans for the /billing/plans endpoint."""
    return [
        {
            "tier": p.tier,
            "label": p.label,
            "price_id": p.price_id,
            "monthly_usd": p.monthly_usd,
            "seats_limit": p.seats_limit,
            "resource_limits": p.resource_limits,
            "features": p.features,
            "annual_discount_pct": p.annual_discount_pct,
        }
        for p in tier_plans.values()
    ]
