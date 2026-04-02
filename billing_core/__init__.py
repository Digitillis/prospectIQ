"""billing_core — portable Stripe billing logic.

Drop this package into any FastAPI service and wire up a BillingDbAdapter
to get a fully-featured billing system. Two adapters are provided:

  - SupabaseBillingAdapter  — for ProspectIQ (supabase-py client)
  - AsyncpgBillingAdapter   — for Digitillis (asyncpg connection pool)

Usage (ProspectIQ):
    from billing_core import SupabaseBillingAdapter, stripe_ops, TIER_PLANS
    adapter = SupabaseBillingAdapter(get_supabase_client())

Usage (Digitillis):
    from billing_core import AsyncpgBillingAdapter, stripe_ops, TIER_PLANS
    adapter = AsyncpgBillingAdapter(app.state.db_pool)
"""

from billing_core.types import (
    TierPlan,
    WorkspaceBillingInfo,
    UsageMetrics,
    InvoiceRecord,
    PaymentMethodInfo,
    BillingStatusResponse,
)
from billing_core.tier_plans import TIER_PLANS
from billing_core.db_adapter import BillingDbAdapter
from billing_core.supabase_adapter import SupabaseBillingAdapter
from billing_core.asyncpg_adapter import AsyncpgBillingAdapter
from billing_core import stripe_ops

__all__ = [
    "TierPlan",
    "WorkspaceBillingInfo",
    "UsageMetrics",
    "InvoiceRecord",
    "PaymentMethodInfo",
    "BillingStatusResponse",
    "TIER_PLANS",
    "BillingDbAdapter",
    "SupabaseBillingAdapter",
    "AsyncpgBillingAdapter",
    "stripe_ops",
]
