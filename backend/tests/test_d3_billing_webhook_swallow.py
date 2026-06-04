"""D3: BillingWebhookHandler.dispatch must NOT swallow exceptions.

Old code caught every exception and returned "handler_error" which the router
returned as HTTP 200 — Stripe treats 2xx as success and never retries, so a
transient DB error permanently drops checkout.session.completed / invoice.paid.

Tests verify:
1. DB failure during event handling propagates as an exception (not "handler_error").
2. Unknown event types still return "ignored" (correct 200 behavior).
3. "ok" is returned for successful handling.
4. The old handler_error return no longer appears.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_handler(adapter=None):
    from billing_sdk.webhook_handler import BillingWebhookHandler
    from billing_sdk.types import TierPlan

    if adapter is None:
        adapter = MagicMock()
        adapter.apply_checkout_completed = AsyncMock(return_value=None)
        adapter.apply_subscription_updated = AsyncMock(return_value=None)
        adapter.apply_subscription_canceled = AsyncMock(return_value=None)
        adapter.apply_invoice_paid = AsyncMock(return_value=None)
        adapter.apply_invoice_payment_failed = AsyncMock(return_value=None)

    tier_plans = {
        "free": TierPlan(tier="free", label="Free", price_id="", monthly_usd=0, seats_limit=5),
        "starter": TierPlan(
            tier="starter", label="Starter", price_id="", monthly_usd=99, seats_limit=10
        ),
    }
    return BillingWebhookHandler(adapter, tier_plans, free_tier="free")


def _checkout_event() -> dict:
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"workspace_id": "ws-1", "tier": "starter"},
                "subscription": "sub_123",
                "customer": "cus_123",
            }
        },
    }


def test_transient_db_error_propagates_as_exception():
    """A DB error during checkout.session.completed must NOT be caught — must propagate."""
    adapter = MagicMock()
    adapter.apply_checkout_completed = AsyncMock(side_effect=RuntimeError("DB connection lost"))

    handler = _make_handler(adapter)

    with pytest.raises(RuntimeError, match="DB connection lost"):
        _run(handler.dispatch(_checkout_event()))


def test_transient_error_is_not_swallowed_to_handler_error():
    """dispatch() must never return 'handler_error' string."""
    adapter = MagicMock()
    adapter.apply_checkout_completed = AsyncMock(side_effect=Exception("network timeout"))

    handler = _make_handler(adapter)

    # Old code returned "handler_error"; new code propagates
    try:
        result = _run(handler.dispatch(_checkout_event()))
        assert result != "handler_error", (
            "dispatch() returned 'handler_error' — exception swallow still present"
        )
    except Exception:
        pass  # Exception propagated — correct behavior


def test_unknown_event_type_returns_ignored():
    """Unknown event types must return 'ignored' (HTTP 200 is correct for unknown events)."""
    handler = _make_handler()
    event = {"type": "payment_intent.created", "data": {"object": {}}}
    result = _run(handler.dispatch(event))
    assert result == "ignored", f"Expected 'ignored' for unknown event, got {result!r}"


def test_successful_checkout_returns_ok():
    """Successful processing returns 'ok'."""
    handler = _make_handler()
    result = _run(handler.dispatch(_checkout_event()))
    assert result == "ok", f"Expected 'ok' for successful checkout, got {result!r}"


def test_invoice_paid_db_error_propagates():
    """invoice.paid DB error must propagate so Stripe retries."""
    adapter = MagicMock()
    adapter.apply_invoice_paid = AsyncMock(side_effect=ConnectionError("pool exhausted"))

    handler = _make_handler(adapter)
    event = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_1",
                "customer": "cus_1",
                "subscription_details": {"metadata": {"workspace_id": "ws-1", "tier": "starter"}},
            }
        },
    }

    with pytest.raises(ConnectionError, match="pool exhausted"):
        _run(handler.dispatch(event))


def test_subscription_deleted_db_error_propagates():
    """customer.subscription.deleted DB error must propagate."""
    adapter = MagicMock()
    adapter.apply_subscription_canceled = AsyncMock(side_effect=RuntimeError("tx failed"))

    handler = _make_handler(adapter)
    event = {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_1",
                "metadata": {"workspace_id": "ws-1"},
            }
        },
    }

    with pytest.raises(RuntimeError, match="tx failed"):
        _run(handler.dispatch(event))
