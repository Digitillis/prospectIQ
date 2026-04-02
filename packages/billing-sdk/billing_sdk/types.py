"""Core data types for billing-sdk.

Pure dataclasses — no external dependencies.
All field names are platform-agnostic (workspace_id, not tenant_id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BillingSettings:
    """Passed once at router-creation time; holds all env-level config."""
    stripe_secret_key: str
    stripe_webhook_secret: str
    base_url: str                           # "https://app.example.com" (no trailing slash)
    product_name: str = "Platform"          # Used in invoice line-item descriptions
    success_path: str = "/settings/billing?checkout=success"
    cancel_path: str = "/settings/billing?checkout=canceled"
    portal_return_path: str = "/settings/billing"
    invoice_limit: int = 24


# ---------------------------------------------------------------------------
# Tier plan (platform supplies its own instances)
# ---------------------------------------------------------------------------

@dataclass
class TierPlan:
    """Describes one pricing tier.

    Consumers define their own TIER_PLANS dict[str, TierPlan] and pass
    it to create_billing_router().  The SDK does not ship any defaults.
    """
    tier: str                               # unique slug, e.g. "free" | "starter"
    label: str                              # display name, e.g. "Starter"
    price_id: str                           # Stripe price ID; empty for free/enterprise
    monthly_usd: int                        # 0 for free or custom-priced tiers
    seats_limit: int
    resource_limits: dict[str, int] = field(default_factory=dict)
    # e.g. {"assets": 50, "agents": 10} — flexible, consumer-defined
    features: list[str] = field(default_factory=list)
    annual_discount_pct: int = 15


# ---------------------------------------------------------------------------
# Workspace info (returned by DB adapter)
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceBillingInfo:
    """Billing-relevant fields fetched from the workspace/tenant row."""
    workspace_id: str
    tier: str
    subscription_status: str               # active | trialing | past_due | canceled
    seats_limit: int
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    owner_email: str
    workspace_name: str


# ---------------------------------------------------------------------------
# Usage (returned by DB adapter)
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceUsage:
    """Current usage counts for a workspace.

    `resource_usage` mirrors the TierPlan.resource_limits keys.
    The adapter fills it; the SDK compares them for the status response.
    """
    seats_used: int = 0
    seats_limit: int = 3
    resource_usage: dict[str, int] = field(default_factory=dict)
    # e.g. {"assets": 12, "agents": 3}


# ---------------------------------------------------------------------------
# Stripe data
# ---------------------------------------------------------------------------

@dataclass
class InvoiceRecord:
    id: str
    number: str | None
    status: str                             # paid | open | draft | void | uncollectible
    amount_due: float
    amount_paid: float
    currency: str
    created: int                            # Unix timestamp
    due_date: int | None
    period_start: int | None
    period_end: int | None
    description: str
    hosted_invoice_url: str | None
    invoice_pdf: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "status": self.status,
            "amount_due": self.amount_due,
            "amount_paid": self.amount_paid,
            "currency": self.currency,
            "created": self.created,
            "due_date": self.due_date,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "description": self.description,
            "hosted_invoice_url": self.hosted_invoice_url,
            "invoice_pdf": self.invoice_pdf,
        }


@dataclass
class PaymentMethodInfo:
    id: str
    type: str                               # "card" | "us_bank_account"
    brand: str | None = None
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    bank_name: str | None = None
    account_type: str | None = None         # "checking" | "savings"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.type == "card":
            result["card"] = {
                "brand": self.brand,
                "last4": self.last4,
                "exp_month": self.exp_month,
                "exp_year": self.exp_year,
            }
        elif self.type == "us_bank_account":
            result["bank"] = {
                "bank_name": self.bank_name,
                "last4": self.last4,
                "account_type": self.account_type,
            }
        return result


# ---------------------------------------------------------------------------
# API response shape
# ---------------------------------------------------------------------------

@dataclass
class BillingStatusResponse:
    """Serialisable shape for GET /billing/status."""
    tier: str
    tier_label: str
    subscription_status: str
    monthly_usd: int
    features: list[str]
    seats: dict[str, int]                   # {"used": N, "limit": N}
    usage: dict[str, Any]                   # resource_usage + resource_limits merged
    next_billing_date: int | None
    has_stripe_customer: bool
    has_subscription: bool
    upgrade_available: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_label": self.tier_label,
            "subscription_status": self.subscription_status,
            "monthly_usd": self.monthly_usd,
            "features": self.features,
            "seats": self.seats,
            "usage": self.usage,
            "next_billing_date": self.next_billing_date,
            "has_stripe_customer": self.has_stripe_customer,
            "has_subscription": self.has_subscription,
            "upgrade_available": self.upgrade_available,
        }
