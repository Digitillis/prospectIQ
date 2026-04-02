"""Tier plan definitions — single source of truth for ProspectIQ.

Pricing (2026):
  starter  — $1,500/mo  500 companies/mo, 1 seat
  growth   — $3,500/mo  2,000 companies/mo, 5 seats, CRM sync, LinkedIn automation
  scale    — $7,500/mo  10,000 companies/mo, 20 seats, API access, dedicated CSM
  api      — $0.05/company  usage-based credits

Stripe price IDs are loaded from environment variables so they can be set
per-environment (test vs live) without code changes:

  STRIPE_PRICE_STARTER   — monthly price ID for starter tier
  STRIPE_PRICE_GROWTH    — monthly price ID for growth tier
  STRIPE_PRICE_SCALE     — monthly price ID for scale tier
  STRIPE_PRICE_API       — per-unit metered price ID for api tier

Create these products in the Stripe dashboard, then set the env vars.
Annual pricing (15% discount) requires separate annual price IDs:
  STRIPE_PRICE_STARTER_ANNUAL
  STRIPE_PRICE_GROWTH_ANNUAL
  STRIPE_PRICE_SCALE_ANNUAL
"""

from __future__ import annotations

import os

from billing_core.types import TierPlan


def _price(env_var: str) -> str:
    """Read a Stripe price ID from an environment variable.

    Returns an empty string if not set — billing routes detect this and
    surface a clear error rather than silently using a placeholder.
    """
    return os.environ.get(env_var, "")


# ---------------------------------------------------------------------------
# ProspectIQ tier definitions
# ---------------------------------------------------------------------------

TIER_PLANS: dict[str, TierPlan] = {
    "starter": TierPlan(
        tier="starter",
        label="Starter",
        price_id=_price("STRIPE_PRICE_STARTER"),
        seats_limit=1,
        companies_per_month=500,
        monthly_usd=1500,
        features=[
            "500 companies/month",
            "1 seat",
            "Email outreach",
            "PQS scoring",
            "Manufacturing ontology",
            "14-day free trial",
        ],
    ),
    "growth": TierPlan(
        tier="growth",
        label="Growth",
        price_id=_price("STRIPE_PRICE_GROWTH"),
        seats_limit=5,
        companies_per_month=2000,
        monthly_usd=3500,
        features=[
            "2,000 companies/month",
            "5 seats",
            "Email + LinkedIn automation",
            "CRM sync (HubSpot)",
            "Signal monitoring",
            "Priority support",
            "14-day free trial",
        ],
    ),
    "scale": TierPlan(
        tier="scale",
        label="Scale",
        price_id=_price("STRIPE_PRICE_SCALE"),
        seats_limit=20,
        companies_per_month=10000,
        monthly_usd=7500,
        features=[
            "10,000 companies/month",
            "20 seats",
            "Full outreach suite",
            "API access",
            "Custom ICPs",
            "Dedicated CSM",
            "14-day free trial",
        ],
    ),
    "api": TierPlan(
        tier="api",
        label="API Credits",
        price_id=_price("STRIPE_PRICE_API"),
        seats_limit=3,
        companies_per_month=50000,
        monthly_usd=0,  # Usage-based: $0.05/company researched
        features=[
            "API access",
            "50K companies/month",
            "$0.05 per company researched",
            "Research + contacts + scoring",
        ],
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
