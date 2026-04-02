"""Billing API — ProspectIQ.

Thin adapter that wires billing_sdk.create_billing_router into the ProspectIQ
serving layer. All business logic lives in billing_sdk.

Endpoints (registered at /api/billing):
    GET  /plans           — unauthenticated, returns all tier plans
    GET  /status          — authenticated, current plan + usage
    GET  /invoices        — authenticated, Stripe invoice history
    GET  /payment-method  — authenticated, default payment method
    POST /checkout        — start Stripe Checkout for a paid tier
    POST /portal          — open Stripe Customer Portal
    POST /invoice         — create & send invoice (annual / enterprise)
    POST /webhooks/stripe — Stripe webhook receiver

Required environment variables:
    STRIPE_SECRET_KEY       — sk_live_... or sk_test_...
    STRIPE_WEBHOOK_SECRET   — whsec_...
    APP_BASE_URL            — https://app.prospectiq.io (no trailing slash)
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from billing_sdk import BillingSettings, create_billing_router
from billing_sdk.types import TierPlan as SdkTierPlan
from backend.app.core.database import get_supabase_client
from backend.app.core.workspace import get_workspace_id as _get_ws_id
from billing_core.supabase_adapter import SupabaseBillingAdapter
from billing_core.tier_plans import TIER_PLANS as _PIQ_PLANS, TIER_ORDER


# ---------------------------------------------------------------------------
# Convert ProspectIQ TierPlan → SDK TierPlan
# (ProspectIQ uses companies_per_month; SDK uses resource_limits dict)
# ---------------------------------------------------------------------------

def _to_sdk_plans(plans: dict) -> dict[str, SdkTierPlan]:
    result: dict[str, SdkTierPlan] = {}
    for tier, p in plans.items():
        cpm = getattr(p, "companies_per_month", 0)
        result[tier] = SdkTierPlan(
            tier=p.tier,
            label=p.label,
            price_id=p.price_id,
            monthly_usd=p.monthly_usd,
            seats_limit=p.seats_limit,
            resource_limits={
                "companies": cpm,
                "contacts": p.seats_limit * 500,
                "outreach": cpm * 3,
            },
            features=p.features,
            annual_discount_pct=p.annual_discount_pct,
        )
    return result


TIER_PLANS = _to_sdk_plans(_PIQ_PLANS)


# ---------------------------------------------------------------------------
# Platform-specific dependency injectors
# ---------------------------------------------------------------------------

def _get_adapter(request: Request) -> SupabaseBillingAdapter:  # noqa: ARG001
    return SupabaseBillingAdapter(get_supabase_client())


def _get_workspace_id(request: Request) -> str:  # noqa: ARG001
    """Read workspace_id from WorkspaceContext set by WorkspaceMiddleware."""
    ws_id = _get_ws_id()
    if not ws_id:
        raise HTTPException(401, "Authentication required")
    return ws_id


# ---------------------------------------------------------------------------
# Settings from environment
# ---------------------------------------------------------------------------

def _build_settings() -> BillingSettings:
    return BillingSettings(
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        base_url=os.environ.get("APP_BASE_URL", "https://app.prospectiq.io").rstrip("/"),
        product_name="ProspectIQ",
        success_path="/settings/billing?checkout=success",
        cancel_path="/settings/billing?checkout=cancelled",
        portal_return_path="/settings/billing",
        invoice_limit=24,
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = create_billing_router(
    get_adapter=_get_adapter,
    get_workspace_id=_get_workspace_id,
    settings=_build_settings(),
    tier_plans=TIER_PLANS,
    tier_order=TIER_ORDER,
    free_tier="starter",
    api_prefix="/api/billing",
    tags=["billing"],
)
