"""Tier plan definitions — single source of truth.

Copy/paste this file into any product that uses billing_core and update
the price_ids and limits to match that product's Stripe products.

ProspectIQ tiers:
  starter  — free
  growth   — $299/mo
  scale    — $799/mo
  api      — usage-based

Digitillis tiers (different limits/pricing — override via your own copy):
  free     — 1 site, 3 agents
  starter  — $2,500/mo
  growth   — $7,500/mo
  scale    — $15,000/mo
"""

from __future__ import annotations

from billing_core.types import TierPlan

# ---------------------------------------------------------------------------
# ProspectIQ tier definitions
# Update price_id values after creating products in your Stripe dashboard.
# ---------------------------------------------------------------------------

TIER_PLANS: dict[str, TierPlan] = {
    "starter": TierPlan(
        tier="starter",
        label="Starter",
        price_id="",                          # Free — no Stripe price needed
        seats_limit=1,
        companies_per_month=200,
        monthly_usd=0,
        features=["200 companies/month", "1 seat", "Email outreach"],
    ),
    "growth": TierPlan(
        tier="growth",
        label="Growth",
        price_id="price_growth_placeholder",  # Replace with real Stripe price ID
        seats_limit=5,
        companies_per_month=2000,
        monthly_usd=299,
        features=["2,000 companies/month", "5 seats", "Email + LinkedIn", "Priority support"],
    ),
    "scale": TierPlan(
        tier="scale",
        label="Scale",
        price_id="price_scale_placeholder",   # Replace with real Stripe price ID
        seats_limit=15,
        companies_per_month=10000,
        monthly_usd=799,
        features=["10,000 companies/month", "15 seats", "Full outreach suite", "Dedicated CSM"],
    ),
    "api": TierPlan(
        tier="api",
        label="API",
        price_id="price_api_placeholder",
        seats_limit=3,
        companies_per_month=50000,
        monthly_usd=0,
        features=["API access", "50K companies/month", "Custom limits"],
    ),
}

# Ordered list for tier comparison (ascending)
TIER_ORDER: list[str] = ["starter", "growth", "scale", "api"]


def get_plan(tier: str) -> TierPlan:
    """Return the TierPlan for a tier name, defaulting to starter."""
    return TIER_PLANS.get(tier, TIER_PLANS["starter"])


def tier_index(tier: str) -> int:
    """Return numeric rank of a tier (higher = more expensive)."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def plans_as_dicts() -> list[dict]:
    """Serialise all plans for the frontend /billing/plans endpoint."""
    return [
        {
            "tier": p.tier,
            "label": p.label,
            "monthly_usd": p.monthly_usd,
            "seats_limit": p.seats_limit,
            "companies_per_month": p.companies_per_month,
            "features": p.features,
            "annual_discount_pct": p.annual_discount_pct,
        }
        for p in TIER_PLANS.values()
    ]
