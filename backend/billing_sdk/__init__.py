"""billing-sdk — white-label Stripe billing for FastAPI SaaS apps.

Quick start
-----------
    from billing_sdk.router_factory import create_billing_router
    from billing_sdk.types import BillingSettings, TierPlan
    from billing_sdk.db_adapter import BillingDbAdapter

See packages/billing-sdk/README.md for full integration guide.
"""

from billing_sdk.types import (
    BillingSettings,
    BillingStatusResponse,
    InvoiceRecord,
    PaymentMethodInfo,
    TierPlan,
    WorkspaceBillingInfo,
    WorkspaceUsage,
)
from billing_sdk.db_adapter import BillingDbAdapter
from billing_sdk.router_factory import create_billing_router
from billing_sdk.webhook_handler import BillingWebhookHandler
from billing_sdk import stripe_ops, tier_utils

__version__ = "1.0.0"
__all__ = [
    "BillingSettings",
    "BillingStatusResponse",
    "BillingDbAdapter",
    "BillingWebhookHandler",
    "InvoiceRecord",
    "PaymentMethodInfo",
    "TierPlan",
    "WorkspaceBillingInfo",
    "WorkspaceUsage",
    "create_billing_router",
    "stripe_ops",
    "tier_utils",
]
