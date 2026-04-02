"""Supabase implementation of billing_sdk.BillingDbAdapter — used by ProspectIQ.

Depends only on the supabase-py client passed in at construction time.
No FastAPI or app-specific imports allowed here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from billing_sdk.db_adapter import BillingDbAdapter
from billing_sdk.types import WorkspaceBillingInfo, WorkspaceUsage

logger = logging.getLogger(__name__)


class SupabaseBillingAdapter(BillingDbAdapter):
    """BillingDbAdapter backed by a supabase-py client."""

    def __init__(self, client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_workspace_billing_info(self, workspace_id: str) -> WorkspaceBillingInfo:
        ws = (
            self._client.table("workspaces")
            .select(
                "tier, subscription_status, seats_limit, "
                "stripe_customer_id, stripe_subscription_id, "
                "owner_email, name"
            )
            .eq("id", workspace_id)
            .limit(1)
            .execute()
        )
        if not ws.data:
            raise LookupError(f"Workspace {workspace_id} not found")

        row = ws.data[0]
        return WorkspaceBillingInfo(
            workspace_id=workspace_id,
            tier=row.get("tier") or "starter",
            subscription_status=row.get("subscription_status") or "trialing",
            seats_limit=row.get("seats_limit") or 1,
            stripe_customer_id=row.get("stripe_customer_id"),
            stripe_subscription_id=row.get("stripe_subscription_id"),
            owner_email=row.get("owner_email") or "",
            workspace_name=row.get("name") or "",
        )

    def get_workspace_usage(self, workspace_id: str, plan) -> WorkspaceUsage:
        """Count companies, contacts, and outreach actions for the workspace."""
        client = self._client
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        seats_used = 0
        companies_this_month = 0
        contacts_total = 0
        outreach_this_month = 0

        try:
            res = (
                client.table("workspace_members")
                .select("id", count="exact")
                .eq("workspace_id", workspace_id)
                .in_("status", ["active", "pending"])
                .execute()
            )
            seats_used = res.count or 0
        except Exception:
            pass

        try:
            res = (
                client.table("companies")
                .select("id", count="exact")
                .eq("workspace_id", workspace_id)
                .gte("created_at", month_start)
                .execute()
            )
            companies_this_month = res.count or 0
        except Exception:
            pass

        try:
            res = (
                client.table("contacts")
                .select("id", count="exact")
                .eq("workspace_id", workspace_id)
                .execute()
            )
            contacts_total = res.count or 0
        except Exception:
            pass

        try:
            res = (
                client.table("actions")
                .select("id", count="exact")
                .eq("workspace_id", workspace_id)
                .gte("created_at", month_start)
                .execute()
            )
            outreach_this_month = res.count or 0
        except Exception:
            pass

        return WorkspaceUsage(
            seats_used=seats_used,
            resource_usage={
                "companies": companies_this_month,
                "contacts": contacts_total,
                "outreach": outreach_this_month,
            },
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_stripe_customer_id(self, workspace_id: str, customer_id: str) -> None:
        self._client.table("workspaces").update(
            {"stripe_customer_id": customer_id}
        ).eq("id", workspace_id).execute()

    def apply_checkout_completed(
        self,
        workspace_id: str,
        tier: str,
        seats_limit: int,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        update: dict = {
            "tier": tier,
            "subscription_status": "active",
            "seats_limit": seats_limit,
        }
        if subscription_id:
            update["stripe_subscription_id"] = subscription_id
        if customer_id:
            update["stripe_customer_id"] = customer_id
        self._client.table("workspaces").update(update).eq("id", workspace_id).execute()

    def apply_subscription_updated(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        status: str,
        tier: str | None,
        seats_limit: int | None,
    ) -> None:
        if not workspace_id and subscription_id:
            ws = (
                self._client.table("workspaces")
                .select("id")
                .eq("stripe_subscription_id", subscription_id)
                .limit(1)
                .execute()
            )
            if ws.data:
                workspace_id = ws.data[0]["id"]

        if not workspace_id:
            return

        update: dict = {"subscription_status": status}
        if tier:
            update["tier"] = tier
        if seats_limit is not None:
            update["seats_limit"] = seats_limit
        self._client.table("workspaces").update(update).eq("id", workspace_id).execute()

    def apply_subscription_canceled(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        free_tier_seats_limit: int = 1,
    ) -> None:
        if not workspace_id and subscription_id:
            ws = (
                self._client.table("workspaces")
                .select("id")
                .eq("stripe_subscription_id", subscription_id)
                .limit(1)
                .execute()
            )
            if ws.data:
                workspace_id = ws.data[0]["id"]

        if not workspace_id:
            return

        self._client.table("workspaces").update({
            "tier": "starter",
            "subscription_status": "canceled",
            "stripe_subscription_id": None,
            "seats_limit": free_tier_seats_limit,
        }).eq("id", workspace_id).execute()

    def apply_invoice_paid(
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        customer_id: str | None,
        tier: str | None,
        seats_limit: int | None,
    ) -> None:
        if not workspace_id:
            ws = None
            if subscription_id:
                ws = (
                    self._client.table("workspaces")
                    .select("id")
                    .eq("stripe_subscription_id", subscription_id)
                    .limit(1)
                    .execute()
                )
            if not (ws and ws.data) and customer_id:
                ws = (
                    self._client.table("workspaces")
                    .select("id")
                    .eq("stripe_customer_id", customer_id)
                    .limit(1)
                    .execute()
                )
            if ws and ws.data:
                workspace_id = ws.data[0]["id"]

        if not workspace_id:
            return

        update: dict = {"subscription_status": "active"}
        if tier:
            update["tier"] = tier
        if seats_limit is not None:
            update["seats_limit"] = seats_limit
        if customer_id:
            update["stripe_customer_id"] = customer_id
        self._client.table("workspaces").update(update).eq("id", workspace_id).execute()

    def apply_payment_failed(
        self,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        ws = None
        if subscription_id:
            ws = (
                self._client.table("workspaces")
                .select("id")
                .eq("stripe_subscription_id", subscription_id)
                .limit(1)
                .execute()
            )
        if not (ws and ws.data) and customer_id:
            ws = (
                self._client.table("workspaces")
                .select("id")
                .eq("stripe_customer_id", customer_id)
                .limit(1)
                .execute()
            )
        if ws and ws.data:
            workspace_id = ws.data[0]["id"]
            self._client.table("workspaces").update(
                {"subscription_status": "past_due"}
            ).eq("id", workspace_id).execute()
