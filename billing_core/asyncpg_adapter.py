"""asyncpg implementation of BillingDbAdapter — used by Digitillis.

Drop this file into the Digitillis backend alongside the rest of billing_core.
Wire it up in the billing route:

    from billing_core import AsyncpgBillingAdapter
    adapter = AsyncpgBillingAdapter(request.app.state.db_pool)

The Digitillis workspaces table is called `tenants` and uses `tenant_id`
as the primary key. Adjust the TABLE and PK constants below if your schema
differs.

All methods are async — use `await` in route handlers.

Required columns on the `tenants` table:
    id                       VARCHAR / UUID
    tier                     VARCHAR  (starter/growth/scale/enterprise)
    subscription_status      VARCHAR  (active/trialing/past_due/canceled)
    seats_limit              INTEGER
    stripe_customer_id       VARCHAR  NULLABLE
    stripe_subscription_id   VARCHAR  NULLABLE
    owner_email              VARCHAR
    name                     VARCHAR

Required tables:
    tenant_members           (tenant_id, status)
    companies                (tenant_id, created_at)    — or equivalent
    contacts                 (tenant_id)                — or equivalent
    actions                  (tenant_id, created_at)    — or equivalent
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from billing_core.db_adapter import BillingDbAdapter
from billing_core.types import WorkspaceBillingInfo, UsageMetrics
from billing_core.tier_plans import get_plan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema constants — override for your DB schema
# ---------------------------------------------------------------------------

WORKSPACE_TABLE = "tenants"          # Change to "workspaces" if needed
WORKSPACE_PK = "id"
MEMBERS_TABLE = "tenant_members"
MEMBERS_FK = "tenant_id"
COMPANIES_TABLE = "companies"
COMPANIES_FK = "tenant_id"
CONTACTS_TABLE = "contacts"
CONTACTS_FK = "tenant_id"
ACTIONS_TABLE = "actions"
ACTIONS_FK = "tenant_id"


class AsyncpgBillingAdapter(BillingDbAdapter):
    """BillingDbAdapter backed by an asyncpg connection pool.

    All methods are async. Use `await adapter.method()` in your route handlers.
    """

    def __init__(self, pool) -> None:
        # `pool` is an asyncpg.Pool instance
        self._pool = pool

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_workspace_billing_info(self, workspace_id: str) -> WorkspaceBillingInfo:  # type: ignore[override]
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT tier, subscription_status, seats_limit,
                       stripe_customer_id, stripe_subscription_id,
                       owner_email, name
                FROM {WORKSPACE_TABLE}
                WHERE {WORKSPACE_PK} = $1
                """,
                workspace_id,
            )
        if not row:
            raise LookupError(f"Workspace {workspace_id} not found")

        return WorkspaceBillingInfo(
            workspace_id=workspace_id,
            tier=row["tier"] or "starter",
            subscription_status=row["subscription_status"] or "trialing",
            seats_limit=row["seats_limit"] or 1,
            stripe_customer_id=row["stripe_customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
            owner_email=row["owner_email"] or "",
            workspace_name=row["name"] or "",
        )

    async def get_usage_metrics(  # type: ignore[override]
        self, workspace_id: str, companies_limit: int
    ) -> UsageMetrics:
        metrics = UsageMetrics(companies_limit=companies_limit)
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        async with self._pool.acquire() as conn:
            try:
                metrics.seats_used = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {MEMBERS_TABLE} WHERE {MEMBERS_FK} = $1 "
                    f"AND status IN ('active', 'pending')",
                    workspace_id,
                ) or 0
            except Exception:
                pass

            try:
                metrics.companies_this_month = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {COMPANIES_TABLE} "
                    f"WHERE {COMPANIES_FK} = $1 AND created_at >= $2",
                    workspace_id, month_start,
                ) or 0
            except Exception:
                pass

            try:
                metrics.contacts_total = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {CONTACTS_TABLE} WHERE {CONTACTS_FK} = $1",
                    workspace_id,
                ) or 0
            except Exception:
                pass

            try:
                metrics.outreach_this_month = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {ACTIONS_TABLE} "
                    f"WHERE {ACTIONS_FK} = $1 AND created_at >= $2",
                    workspace_id, month_start,
                ) or 0
            except Exception:
                pass

        return metrics

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def save_stripe_customer_id(  # type: ignore[override]
        self, workspace_id: str, customer_id: str
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {WORKSPACE_TABLE} SET stripe_customer_id = $1 "
                f"WHERE {WORKSPACE_PK} = $2",
                customer_id, workspace_id,
            )

    async def apply_checkout_completed(  # type: ignore[override]
        self,
        workspace_id: str,
        tier: str,
        seats_limit: int,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {WORKSPACE_TABLE}
                SET tier = $1, subscription_status = 'active', seats_limit = $2,
                    stripe_subscription_id = COALESCE($3, stripe_subscription_id),
                    stripe_customer_id     = COALESCE($4, stripe_customer_id)
                WHERE {WORKSPACE_PK} = $5
                """,
                tier, seats_limit, subscription_id, customer_id, workspace_id,
            )

    async def apply_subscription_updated(  # type: ignore[override]
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        status: str,
        tier: str | None,
        seats_limit: int | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if not workspace_id and subscription_id:
                workspace_id = await conn.fetchval(
                    f"SELECT {WORKSPACE_PK} FROM {WORKSPACE_TABLE} "
                    f"WHERE stripe_subscription_id = $1",
                    subscription_id,
                )
            if not workspace_id:
                return

            if tier and seats_limit is not None:
                await conn.execute(
                    f"UPDATE {WORKSPACE_TABLE} SET subscription_status = $1, "
                    f"tier = $2, seats_limit = $3 WHERE {WORKSPACE_PK} = $4",
                    status, tier, seats_limit, workspace_id,
                )
            else:
                await conn.execute(
                    f"UPDATE {WORKSPACE_TABLE} SET subscription_status = $1 "
                    f"WHERE {WORKSPACE_PK} = $2",
                    status, workspace_id,
                )

    async def apply_subscription_canceled(  # type: ignore[override]
        self,
        workspace_id: str | None,
        subscription_id: str | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if not workspace_id and subscription_id:
                workspace_id = await conn.fetchval(
                    f"SELECT {WORKSPACE_PK} FROM {WORKSPACE_TABLE} "
                    f"WHERE stripe_subscription_id = $1",
                    subscription_id,
                )
            if not workspace_id:
                return

            starter = get_plan("starter")
            await conn.execute(
                f"""
                UPDATE {WORKSPACE_TABLE}
                SET tier = 'starter', subscription_status = 'canceled',
                    stripe_subscription_id = NULL, seats_limit = $1
                WHERE {WORKSPACE_PK} = $2
                """,
                starter.seats_limit, workspace_id,
            )

    async def apply_invoice_paid(  # type: ignore[override]
        self,
        workspace_id: str | None,
        subscription_id: str | None,
        customer_id: str | None,
        tier: str | None,
        seats_limit: int | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if not workspace_id:
                if subscription_id:
                    workspace_id = await conn.fetchval(
                        f"SELECT {WORKSPACE_PK} FROM {WORKSPACE_TABLE} "
                        f"WHERE stripe_subscription_id = $1",
                        subscription_id,
                    )
                if not workspace_id and customer_id:
                    workspace_id = await conn.fetchval(
                        f"SELECT {WORKSPACE_PK} FROM {WORKSPACE_TABLE} "
                        f"WHERE stripe_customer_id = $1",
                        customer_id,
                    )
            if not workspace_id:
                return

            if tier and seats_limit is not None:
                await conn.execute(
                    f"""
                    UPDATE {WORKSPACE_TABLE}
                    SET subscription_status = 'active', tier = $1, seats_limit = $2,
                        stripe_customer_id = COALESCE($3, stripe_customer_id)
                    WHERE {WORKSPACE_PK} = $4
                    """,
                    tier, seats_limit, customer_id, workspace_id,
                )
            else:
                await conn.execute(
                    f"UPDATE {WORKSPACE_TABLE} SET subscription_status = 'active' "
                    f"WHERE {WORKSPACE_PK} = $1",
                    workspace_id,
                )

    async def apply_payment_failed(  # type: ignore[override]
        self,
        subscription_id: str | None,
        customer_id: str | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            workspace_id = None
            if subscription_id:
                workspace_id = await conn.fetchval(
                    f"SELECT {WORKSPACE_PK} FROM {WORKSPACE_TABLE} "
                    f"WHERE stripe_subscription_id = $1",
                    subscription_id,
                )
            if not workspace_id and customer_id:
                workspace_id = await conn.fetchval(
                    f"SELECT {WORKSPACE_PK} FROM {WORKSPACE_TABLE} "
                    f"WHERE stripe_customer_id = $1",
                    customer_id,
                )
            if workspace_id:
                await conn.execute(
                    f"UPDATE {WORKSPACE_TABLE} SET subscription_status = 'past_due' "
                    f"WHERE {WORKSPACE_PK} = $1",
                    workspace_id,
                )
