"""Abstract DB adapter for billing-sdk.

Implement this interface once per database backend:
  - AsyncpgBillingAdapter   — asyncpg pool (PostgreSQL / TimescaleDB)
  - SupabaseBillingAdapter  — supabase-py (Supabase / PostgREST)
  - any other backend...

The SDK calls these methods; you implement them for your schema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from billing_sdk.types import WorkspaceBillingInfo, WorkspaceUsage


class BillingDbAdapter(ABC):
    """Database operations required by the billing SDK."""

    @abstractmethod
    def get_workspace_billing_info(self, workspace_id: str) -> WorkspaceBillingInfo:
        """Return billing-relevant fields for the workspace row.

        Must raise LookupError when the workspace is not found.
        May be sync or async — the router awaits coroutines automatically.
        """
        ...

    @abstractmethod
    def get_workspace_usage(self, workspace_id: str, plan: "TierPlan") -> WorkspaceUsage:  # noqa: F821
        """Return current usage counts for the workspace.

        Must never raise — return WorkspaceUsage with zeros on any DB error.
        """
        ...

    @abstractmethod
    def save_stripe_customer_id(self, workspace_id: str, customer_id: str) -> None:
        """Persist a newly-created Stripe customer ID."""
        ...

    @abstractmethod
    def apply_checkout_completed(
        self,
        workspace_id: str,
        tier: str,
        seats_limit: int,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        """Upgrade workspace after a successful Stripe Checkout session."""
        ...

    @abstractmethod
    def apply_subscription_updated(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        status: str,
        tier: str | None,
        seats_limit: int | None,
    ) -> None:
        """Update subscription status (and optionally tier)."""
        ...

    @abstractmethod
    def apply_subscription_canceled(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        free_tier_seats_limit: int,
    ) -> None:
        """Downgrade workspace to free tier and clear subscription fields."""
        ...

    @abstractmethod
    def apply_invoice_paid(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        customer_id: str | None,
        tier: str | None,
        seats_limit: int | None,
    ) -> None:
        """Mark subscription active after a paid invoice."""
        ...

    @abstractmethod
    def apply_payment_failed(
        self,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        """Mark subscription as past_due after a failed payment."""
        ...
