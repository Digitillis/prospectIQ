"""Shared data types for billing_core.

These are plain dataclasses / TypedDicts with no external dependencies so the
package can be imported anywhere without pulling in Supabase or asyncpg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TierPlan:
    tier: str                        # "starter" | "growth" | "scale" | "api"
    label: str
    price_id: str                    # Stripe price ID — empty string for free tier
    seats_limit: int
    companies_per_month: int
    monthly_usd: int                 # 0 for free / usage-based
    features: list[str] = field(default_factory=list)
    annual_discount_pct: int = 20    # % discount offered on annual billing


@dataclass
class WorkspaceBillingInfo:
    """Everything the billing routes need from the workspace row."""
    workspace_id: str
    tier: str
    subscription_status: str         # active | trialing | past_due | canceled
    seats_limit: int
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    owner_email: str
    workspace_name: str


@dataclass
class UsageMetrics:
    companies_this_month: int = 0
    companies_limit: int = 200
    contacts_total: int = 0
    outreach_this_month: int = 0
    seats_used: int = 0
    seats_limit: int = 1


@dataclass
class InvoiceRecord:
    id: str
    number: str | None
    status: str                      # paid | open | draft | void | uncollectible
    amount_due: float
    amount_paid: float
    currency: str
    created: int                     # Unix timestamp
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
    type: str                        # "card" | "us_bank_account"
    # Card fields
    brand: str | None = None         # "Visa", "Mastercard", etc.
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    # Bank fields
    bank_name: str | None = None
    account_type: str | None = None  # "checking" | "savings"

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


@dataclass
class BillingStatusResponse:
    """Serialisable response for GET /billing/status."""
    tier: str
    tier_label: str
    subscription_status: str
    monthly_usd: int
    features: list[str]
    seats: dict[str, int]
    usage: dict[str, int]
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
