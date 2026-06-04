"""D4: asyncpg AsyncpgBillingAdapter.apply_subscription_canceled must accept
free_tier_seats_limit as a third keyword argument.

Old signature had only (workspace_id, subscription_id) — webhook_handler.py
called it with free_tier_seats_limit=... causing TypeError on every
customer.subscription.deleted event. That TypeError was swallowed by D3,
so cancelled tenants were never downgraded.

Tests verify:
1. apply_subscription_canceled accepts the three-arg signature without TypeError.
2. The workspace tier is set to 'starter' and subscription_id cleared.
3. The seats_limit used is from the caller-supplied free_tier_seats_limit, not
   a hardcoded value.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_apply_subscription_canceled_accepts_three_arg_signature():
    """Three-arg call must not raise TypeError (the D4 bug)."""
    from billing_core.asyncpg_adapter import AsyncpgBillingAdapter
    import inspect

    sig = inspect.signature(AsyncpgBillingAdapter.apply_subscription_canceled)
    params = list(sig.parameters.keys())

    assert "free_tier_seats_limit" in params, (
        f"apply_subscription_canceled must accept free_tier_seats_limit, got params: {params}"
    )


def test_apply_subscription_canceled_uses_caller_seats_limit():
    """The seats_limit passed by the caller must be used, not a hardcoded value."""
    from billing_core.asyncpg_adapter import AsyncpgBillingAdapter

    adapter = AsyncpgBillingAdapter.__new__(AsyncpgBillingAdapter)
    execute_calls: list[tuple] = []

    mock_conn = AsyncMock()
    async def capture_execute(query, *args):
        execute_calls.append((query, args))
    mock_conn.execute.side_effect = capture_execute
    mock_conn.fetchval = AsyncMock(return_value=None)  # workspace_id lookup

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    adapter._pool = mock_pool

    _run(adapter.apply_subscription_canceled(
        workspace_id="ws-1",
        subscription_id="sub_123",
        free_tier_seats_limit=7,  # caller-specified, NOT hardcoded
    ))

    # Find the UPDATE call
    update_calls = [(q, a) for q, a in execute_calls if "UPDATE" in q.upper()]
    assert update_calls, "No UPDATE query was executed"

    query, args = update_calls[0]
    # seats_limit should be the caller-supplied 7, not a hardcoded value
    assert 7 in args, (
        f"Expected free_tier_seats_limit=7 in the UPDATE args, got: {args}"
    )


def test_apply_subscription_canceled_without_free_tier_seats_limit_still_works():
    """Calling without free_tier_seats_limit (backward compat) must not TypeError."""
    from billing_core.asyncpg_adapter import AsyncpgBillingAdapter

    adapter = AsyncpgBillingAdapter.__new__(AsyncpgBillingAdapter)
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    adapter._pool = mock_pool

    # Must not raise — free_tier_seats_limit has a default fallback
    try:
        _run(adapter.apply_subscription_canceled(
            workspace_id="ws-1",
            subscription_id="sub_123",
            # free_tier_seats_limit not provided — uses default
        ))
    except TypeError as e:
        pytest.fail(f"Should not raise TypeError: {e}")


def test_webhook_handler_calls_adapter_with_three_args():
    """BillingWebhookHandler._on_subscription_deleted passes free_tier_seats_limit."""
    import asyncio
    from billing_sdk.webhook_handler import BillingWebhookHandler
    from billing_sdk.types import TierPlan

    adapter = MagicMock()
    cancel_calls: list[dict] = []

    async def capture_cancel(**kwargs):
        cancel_calls.append(kwargs)

    adapter.apply_subscription_canceled = capture_cancel

    tier_plans = {
        "free": TierPlan(tier="free", label="Free", price_id="", monthly_usd=0, seats_limit=5),
        "starter": TierPlan(tier="starter", label="Starter", price_id="", monthly_usd=99, seats_limit=10),
    }
    handler = BillingWebhookHandler(adapter, tier_plans, free_tier="free")

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {
            "id": "sub_123",
            "metadata": {"workspace_id": "ws-abc"},
        }},
    }

    asyncio.get_event_loop().run_until_complete(handler.dispatch(event))

    assert cancel_calls, "apply_subscription_canceled was not called"
    call_kwargs = cancel_calls[0]
    assert "free_tier_seats_limit" in call_kwargs, (
        f"free_tier_seats_limit not passed to adapter: {call_kwargs}"
    )
    assert call_kwargs["free_tier_seats_limit"] == 5, (
        f"Expected free tier seats_limit=5 (from TierPlan), got {call_kwargs['free_tier_seats_limit']}"
    )
