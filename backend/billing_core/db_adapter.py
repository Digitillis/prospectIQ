"""Abstract DB adapter for billing_core.

Implement this interface for each database backend:
  - SupabaseBillingAdapter  — supabase-py (ProspectIQ)
  - AsyncpgBillingAdapter   — asyncpg pool (Digitillis)

All methods are synchronous here and in the Supabase adapter.
The asyncpg adapter provides async versions — annotate with `async def`
and use `await` in the route handlers when using asyncpg.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from billing_core.types import WorkspaceBillingInfo, UsageMetrics


class BillingDbAdapter(ABC):
    """Interface between billing_core and the underlying database."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @abstractmethod
    def get_workspace_billing_info(self, workspace_id: str) -> WorkspaceBillingInfo:
        """Return billing-relevant fields for the workspace row.

        Must raise LookupError (or a framework-specific 404 exception) when
        the workspace is not found.
        """
        ...

    @abstractmethod
    def get_usage_metrics(self, workspace_id: str, companies_limit: int) -> UsageMetrics:
        """Return current usage counts for the workspace.

        Must never raise — return UsageMetrics with zeros on any DB error.
        """
        ...

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @abstractmethod
    def save_stripe_customer_id(self, workspace_id: str, customer_id: str) -> None:
        """Persist a newly-created Stripe customer ID to the workspace row."""
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
        """Update workspace after a successful Stripe Checkout session."""
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
        """Update subscription status (and optionally tier) on the workspace.

        When workspace_id is None, look up by stripe_subscription_id.
        """
        ...

    @abstractmethod
    def apply_subscription_canceled(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
    ) -> None:
        """Downgrade workspace to starter and clear subscription fields."""
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
        """Mark subscription as active after a paid invoice.

        Falls back to looking up workspace by subscription_id then customer_id.
        """
        ...

    @abstractmethod
    def apply_payment_failed(
        self,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        """Mark subscription as past_due after a failed payment."""
        ...
