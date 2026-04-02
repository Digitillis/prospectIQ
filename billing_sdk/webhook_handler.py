"""Stripe webhook event dispatcher.

Decoupled from the HTTP layer — accepts the parsed event dict and
dispatches to the appropriate adapter method.

Usage:
    handler = BillingWebhookHandler(adapter, tier_plans)
    await handler.dispatch(event)   # or handler.dispatch(event) for sync adapters
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from billing_sdk.db_adapter import BillingDbAdapter
from billing_sdk.types import TierPlan
from billing_sdk.tier_utils import get_plan

logger = logging.getLogger(__name__)

# Stripe event types handled by this dispatcher
HANDLED_EVENTS = frozenset({
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
})


async def _call(method, *args, **kwargs):
    """Call a method whether it is sync or async."""
    result = method(*args, **kwargs)
    if inspect.iscoroutine(result):
        return await result
    return result


class BillingWebhookHandler:
    """Dispatches Stripe webhook events to the DB adapter.

    :param adapter:    A BillingDbAdapter implementation.
    :param tier_plans: The platform's TIER_PLANS dict, used to look up
                       seats_limit after a tier change.
    :param free_tier:  Slug of the free/base tier (used on cancellation).
    """

    def __init__(
        self,
        adapter: BillingDbAdapter,
        tier_plans: dict[str, TierPlan],
        free_tier: str = "free",
    ) -> None:
        self._adapter = adapter
        self._tier_plans = tier_plans
        self._free_tier = free_tier

    async def dispatch(self, event: dict[str, Any]) -> str:
        """Dispatch a parsed Stripe event.  Returns "ok" or "ignored"."""
        event_type: str = event.get("type", "")
        data_object: dict = event.get("data", {}).get("object", {})

        try:
            if event_type == "checkout.session.completed":
                return await self._on_checkout_completed(data_object)
            elif event_type == "customer.subscription.updated":
                return await self._on_subscription_updated(data_object)
            elif event_type == "customer.subscription.deleted":
                return await self._on_subscription_deleted(data_object)
            elif event_type == "invoice.paid":
                return await self._on_invoice_paid(data_object)
            elif event_type == "invoice.payment_failed":
                return await self._on_invoice_payment_failed(data_object)
            else:
                logger.debug("Unhandled Stripe event type: %s", event_type)
                return "ignored"
        except Exception as exc:
            logger.error("Webhook handler error for %s: %s", event_type, exc, exc_info=True)
            # Return "ok" to prevent Stripe retries for handler bugs
            return "handler_error"

    # ------------------------------------------------------------------
    # Private event handlers
    # ------------------------------------------------------------------

    async def _on_checkout_completed(self, session: dict) -> str:
        meta = session.get("metadata") or {}
        workspace_id = meta.get("workspace_id") or ""
        tier = meta.get("tier") or self._free_tier
        if not workspace_id:
            return "ignored"

        plan = get_plan(tier, self._tier_plans, default=self._free_tier)
        await _call(
            self._adapter.apply_checkout_completed,
            workspace_id=workspace_id,
            tier=tier,
            seats_limit=plan.seats_limit,
            subscription_id=session.get("subscription"),
            customer_id=session.get("customer"),
        )
        return "ok"

    async def _on_subscription_updated(self, sub: dict) -> str:
        meta = sub.get("metadata") or {}
        workspace_id = meta.get("workspace_id")
        tier = meta.get("tier")
        plan = get_plan(tier, self._tier_plans, default=self._free_tier) if tier else None
        await _call(
            self._adapter.apply_subscription_updated,
            workspace_id=workspace_id,
            subscription_id=sub.get("id"),
            status=sub.get("status", "active"),
            tier=tier,
            seats_limit=plan.seats_limit if plan else None,
        )
        return "ok"

    async def _on_subscription_deleted(self, sub: dict) -> str:
        meta = sub.get("metadata") or {}
        free_plan = get_plan(self._free_tier, self._tier_plans, default=self._free_tier)
        await _call(
            self._adapter.apply_subscription_canceled,
            workspace_id=meta.get("workspace_id"),
            subscription_id=sub.get("id"),
            free_tier_seats_limit=free_plan.seats_limit,
        )
        return "ok"

    async def _on_invoice_paid(self, inv: dict) -> str:
        sub_id = inv.get("subscription")
        meta = (inv.get("subscription_details") or {}).get("metadata") or {}
        tier = meta.get("tier")
        plan = get_plan(tier, self._tier_plans, default=self._free_tier) if tier else None
        await _call(
            self._adapter.apply_invoice_paid,
            workspace_id=meta.get("workspace_id"),
            subscription_id=sub_id,
            customer_id=inv.get("customer"),
            tier=tier,
            seats_limit=plan.seats_limit if plan else None,
        )
        return "ok"

    async def _on_invoice_payment_failed(self, inv: dict) -> str:
        await _call(
            self._adapter.apply_payment_failed,
            subscription_id=inv.get("subscription"),
            customer_id=inv.get("customer"),
        )
        return "ok"
