"""FastAPI router factory for the billing SDK.

Usage — wire once at app startup:

    from billing_sdk.router_factory import create_billing_router
    from billing_sdk.types import BillingSettings

    router = create_billing_router(
        get_adapter=lambda req: MyAdapter(req.app.state.db_pool),
        get_workspace_id=lambda req: get_current_workspace(req).id,
        settings=BillingSettings(
            stripe_secret_key=os.environ["STRIPE_SECRET_KEY"],
            stripe_webhook_secret=os.environ["STRIPE_WEBHOOK_SECRET"],
            base_url=os.environ["APP_BASE_URL"],
            product_name="MyProduct",
        ),
        tier_plans=MY_TIER_PLANS,
        tier_order=["free", "starter", "professional", "enterprise"],
        api_prefix="/api/v1/billing",   # default: "/billing"
    )
    app.include_router(router)
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

import stripe as _stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from billing_sdk.db_adapter import BillingDbAdapter
from billing_sdk.types import BillingSettings, BillingStatusResponse, TierPlan
from billing_sdk.tier_utils import get_plan, is_upgrade_available, plans_as_dicts, tier_index
from billing_sdk import stripe_ops
from billing_sdk.webhook_handler import BillingWebhookHandler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _call(method, *args, **kwargs):
    result = method(*args, **kwargs)
    if inspect.iscoroutine(result):
        return await result
    return result


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class _CheckoutBody(BaseModel):
    tier: str
    billing_interval: str = "monthly"   # "monthly" | "annual"


class _InvoiceBody(BaseModel):
    billing_email: str
    months: int = 12
    net_days: int = 30


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_billing_router(
    *,
    get_adapter: Callable[[Request], BillingDbAdapter],
    get_workspace_id: Callable[[Request], str],
    settings: BillingSettings,
    tier_plans: dict[str, TierPlan],
    tier_order: list[str],
    free_tier: str = "free",
    api_prefix: str = "/billing",
    tags: list[str] | None = None,
) -> APIRouter:
    """Return a fully-configured FastAPI APIRouter for billing.

    Parameters
    ----------
    get_adapter:
        Factory called per-request; receives the FastAPI Request.
        Example: ``lambda req: AsyncpgBillingAdapter(req.app.state.db_pool)``
    get_workspace_id:
        Returns the current workspace/tenant ID for each request.
        Example: ``lambda req: get_current_tenant(req).id``
    settings:
        Static config (Stripe keys, base URL, product name).
    tier_plans:
        All plans for this platform.  Dict key = tier slug.
    tier_order:
        Ascending tier slugs, e.g. ["free", "starter", "professional", "enterprise"].
    free_tier:
        Slug of the free/base tier.  Used on subscription cancellation.
    api_prefix:
        URL prefix for all routes, e.g. "/api/v2/billing".
    tags:
        OpenAPI tags (default: ["billing"]).
    """
    router = APIRouter(prefix=api_prefix, tags=tags or ["billing"])
    webhook_handler = BillingWebhookHandler(None, tier_plans, free_tier)  # adapter set per-request

    def _stripe_module():
        if not settings.stripe_secret_key:
            raise HTTPException(503, "Stripe not configured")
        _stripe.api_key = settings.stripe_secret_key
        return _stripe

    def _base_url() -> str:
        return settings.base_url.rstrip("/")

    # ----------------------------------------------------------------
    # GET /plans  (unauthenticated)
    # ----------------------------------------------------------------

    @router.get("/plans")
    async def list_plans() -> dict[str, Any]:
        """Return all tier definitions — no auth required."""
        return {"plans": plans_as_dicts(tier_plans)}

    # ----------------------------------------------------------------
    # GET /status
    # ----------------------------------------------------------------

    @router.get("/status")
    async def billing_status(request: Request) -> dict[str, Any]:
        workspace_id = get_workspace_id(request)
        adapter = get_adapter(request)

        info = await _call(adapter.get_workspace_billing_info, workspace_id)
        plan = get_plan(info.tier, tier_plans, default=free_tier)
        usage = await _call(adapter.get_workspace_usage, workspace_id, plan)

        next_billing = None
        if info.stripe_subscription_id:
            try:
                s = _stripe_module()
                next_billing = stripe_ops.get_next_billing_date(s, info.stripe_subscription_id)
            except HTTPException:
                pass

        # Build the usage dict from resource_usage + resource_limits
        usage_dict: dict[str, Any] = {}
        for key, limit in plan.resource_limits.items():
            usage_dict[key] = {
                "used": usage.resource_usage.get(key, 0),
                "limit": limit,
            }

        response = BillingStatusResponse(
            tier=info.tier,
            tier_label=plan.label,
            subscription_status=info.subscription_status,
            monthly_usd=plan.monthly_usd,
            features=plan.features,
            seats={"used": usage.seats_used, "limit": info.seats_limit},
            usage=usage_dict,
            next_billing_date=next_billing,
            has_stripe_customer=bool(info.stripe_customer_id),
            has_subscription=bool(info.stripe_subscription_id),
            upgrade_available=is_upgrade_available(info.tier, tier_order),
        )
        return response.as_dict()

    # ----------------------------------------------------------------
    # GET /invoices
    # ----------------------------------------------------------------

    @router.get("/invoices")
    async def list_invoices(request: Request) -> dict[str, Any]:
        workspace_id = get_workspace_id(request)
        adapter = get_adapter(request)
        info = await _call(adapter.get_workspace_billing_info, workspace_id)

        if not info.stripe_customer_id:
            return {"invoices": []}

        s = _stripe_module()
        invoices = stripe_ops.list_invoices(s, info.stripe_customer_id, limit=settings.invoice_limit)
        return {"invoices": [inv.as_dict() for inv in invoices]}

    # ----------------------------------------------------------------
    # GET /payment-method
    # ----------------------------------------------------------------

    @router.get("/payment-method")
    async def get_payment_method(request: Request) -> dict[str, Any]:
        workspace_id = get_workspace_id(request)
        adapter = get_adapter(request)
        info = await _call(adapter.get_workspace_billing_info, workspace_id)

        if not info.stripe_customer_id:
            return {"payment_method": None}

        s = _stripe_module()
        pm = stripe_ops.get_default_payment_method(s, info.stripe_customer_id)
        return {"payment_method": pm.as_dict() if pm else None}

    # ----------------------------------------------------------------
    # POST /checkout
    # ----------------------------------------------------------------

    @router.post("/checkout")
    async def create_checkout(body: _CheckoutBody, request: Request) -> dict[str, Any]:
        plan = tier_plans.get(body.tier)
        if not plan or not plan.price_id:
            raise HTTPException(400, f"No Stripe price configured for tier '{body.tier}'")

        workspace_id = get_workspace_id(request)
        adapter = get_adapter(request)
        info = await _call(adapter.get_workspace_billing_info, workspace_id)

        s = _stripe_module()
        customer_id = stripe_ops.ensure_stripe_customer(
            s,
            info.stripe_customer_id,
            info.owner_email,
            info.workspace_name,
            workspace_id,
        )
        if customer_id != info.stripe_customer_id:
            await _call(adapter.save_stripe_customer_id, workspace_id, customer_id)

        base = _base_url()
        url = stripe_ops.create_checkout_session(
            s,
            customer_id=customer_id,
            plan=plan,
            workspace_id=workspace_id,
            success_url=f"{base}{settings.success_path}",
            cancel_url=f"{base}{settings.cancel_path}",
        )
        return {"url": url}

    # ----------------------------------------------------------------
    # POST /portal
    # ----------------------------------------------------------------

    @router.post("/portal")
    async def create_portal(request: Request) -> dict[str, Any]:
        workspace_id = get_workspace_id(request)
        adapter = get_adapter(request)
        info = await _call(adapter.get_workspace_billing_info, workspace_id)

        if not info.stripe_customer_id:
            raise HTTPException(400, "No Stripe customer — subscribe first")

        s = _stripe_module()
        url = stripe_ops.create_portal_session(
            s,
            customer_id=info.stripe_customer_id,
            return_url=f"{_base_url()}{settings.portal_return_path}",
        )
        return {"url": url}

    # ----------------------------------------------------------------
    # POST /invoice
    # ----------------------------------------------------------------

    @router.post("/invoice")
    async def create_invoice(body: _InvoiceBody, request: Request) -> dict[str, Any]:
        workspace_id = get_workspace_id(request)
        adapter = get_adapter(request)
        info = await _call(adapter.get_workspace_billing_info, workspace_id)

        plan = get_plan(info.tier, tier_plans, default=free_tier)
        if plan.monthly_usd == 0:
            raise HTTPException(
                400,
                "Cannot create invoice for free or custom-priced tiers.",
            )

        s = _stripe_module()
        customer_id = stripe_ops.ensure_stripe_customer(
            s,
            info.stripe_customer_id,
            body.billing_email,
            info.workspace_name,
            workspace_id,
        )
        if customer_id != info.stripe_customer_id:
            await _call(adapter.save_stripe_customer_id, workspace_id, customer_id)

        result = stripe_ops.create_and_send_invoice(
            s,
            customer_id=customer_id,
            plan=plan,
            workspace_id=workspace_id,
            billing_email=body.billing_email,
            months=body.months,
            net_days=body.net_days,
            product_name=settings.product_name,
        )
        return result

    # ----------------------------------------------------------------
    # POST /webhooks/stripe
    # ----------------------------------------------------------------

    @router.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> dict[str, str]:
        if not settings.stripe_webhook_secret:
            raise HTTPException(500, "Webhook secret not configured")

        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")

        try:
            s = _stripe_module()
            event = stripe_ops.parse_webhook_event(
                s, payload, sig_header, settings.stripe_webhook_secret
            )
        except Exception as exc:
            logger.warning("Webhook signature verification failed: %s", exc)
            raise HTTPException(400, "Invalid webhook signature")

        # Re-create handler with the per-request adapter
        adapter = get_adapter(request)
        handler = BillingWebhookHandler(adapter, tier_plans, free_tier)
        status = await handler.dispatch(event)
        return {"status": status}

    return router
