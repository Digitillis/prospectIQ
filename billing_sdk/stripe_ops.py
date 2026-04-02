"""Pure Stripe operations — no DB, no framework dependencies.

Every function accepts:
  - `stripe`   — the initialized stripe module (caller sets stripe.api_key)
  - Plain Python values (strings, ints, dicts)
  - `product_name` where user-visible copy is needed

Fully testable standalone; usable from any framework.
"""

from __future__ import annotations

import logging
from typing import Any

from billing_sdk.types import InvoiceRecord, PaymentMethodInfo, TierPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------

def ensure_stripe_customer(
    stripe,
    customer_id: str | None,
    owner_email: str,
    workspace_name: str,
    workspace_id: str,
) -> str:
    """Return existing customer ID or create a new one.

    Caller must persist a newly-created ID via adapter.save_stripe_customer_id().
    """
    if customer_id:
        return customer_id

    customer = stripe.Customer.create(
        email=owner_email,
        name=workspace_name,
        metadata={"workspace_id": workspace_id},
    )
    return customer["id"]


# ---------------------------------------------------------------------------
# Checkout / portal
# ---------------------------------------------------------------------------

def create_checkout_session(
    stripe,
    customer_id: str,
    plan: TierPlan,
    workspace_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session and return the redirect URL."""
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        payment_method_types=["card", "us_bank_account"],
        payment_method_options={
            "us_bank_account": {
                "financial_connections": {"permissions": ["payment_method"]},
                "verification_method": "instant_or_microdeposit",
            },
        },
        line_items=[{"price": plan.price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"workspace_id": workspace_id, "tier": plan.tier},
        subscription_data={"metadata": {"workspace_id": workspace_id, "tier": plan.tier}},
    )
    return session.url


def create_portal_session(stripe, customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session and return the redirect URL."""
    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return portal.url


# ---------------------------------------------------------------------------
# Invoiced billing (annual / enterprise contracts)
# ---------------------------------------------------------------------------

def create_and_send_invoice(
    stripe,
    customer_id: str,
    plan: TierPlan,
    workspace_id: str,
    billing_email: str,
    months: int,
    net_days: int,
    product_name: str = "Platform",
) -> dict[str, Any]:
    """Create a Stripe Invoice item + invoice, finalise and send.

    Returns dict with invoice_id, invoice_url, pdf_url, amount_usd,
    due_date, status.
    """
    stripe.Customer.modify(customer_id, email=billing_email)

    amount_cents = plan.monthly_usd * months * 100
    stripe.InvoiceItem.create(
        customer=customer_id,
        amount=amount_cents,
        currency="usd",
        description=f"{product_name} {plan.label} — {months}-month subscription",
        metadata={"workspace_id": workspace_id, "tier": plan.tier, "months": str(months)},
    )

    invoice = stripe.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=net_days,
        payment_settings={
            "payment_method_types": ["card", "us_bank_account", "customer_balance"],
        },
        metadata={"workspace_id": workspace_id, "tier": plan.tier},
    )
    invoice = stripe.Invoice.finalize_invoice(invoice["id"])
    stripe.Invoice.send_invoice(invoice["id"])

    return {
        "invoice_id": invoice["id"],
        "invoice_url": invoice.get("hosted_invoice_url", ""),
        "pdf_url": invoice.get("invoice_pdf", ""),
        "amount_usd": plan.monthly_usd * months,
        "due_date": invoice.get("due_date"),
        "status": invoice.get("status"),
    }


# ---------------------------------------------------------------------------
# Invoice history
# ---------------------------------------------------------------------------

def list_invoices(stripe, customer_id: str, limit: int = 24) -> list[InvoiceRecord]:
    """Return up to `limit` invoices for a Stripe customer."""
    try:
        stripe_invoices = stripe.Invoice.list(customer=customer_id, limit=limit)
    except Exception as exc:
        logger.warning("Failed to list invoices for customer %s: %s", customer_id, exc)
        return []

    result: list[InvoiceRecord] = []
    for inv in stripe_invoices.auto_paging_iter():
        description = inv.get("description")
        if not description:
            lines = inv.get("lines", {}).get("data", [])
            if lines:
                description = lines[0].get("description")
        if not description:
            description = inv.get("number") or "Invoice"

        result.append(InvoiceRecord(
            id=inv["id"],
            number=inv.get("number"),
            status=inv.get("status", ""),
            amount_due=(inv.get("amount_due") or 0) / 100,
            amount_paid=(inv.get("amount_paid") or 0) / 100,
            currency=(inv.get("currency") or "usd").upper(),
            created=inv.get("created", 0),
            due_date=inv.get("due_date"),
            period_start=inv.get("period_start"),
            period_end=inv.get("period_end"),
            description=description,
            hosted_invoice_url=inv.get("hosted_invoice_url"),
            invoice_pdf=inv.get("invoice_pdf"),
        ))
        if len(result) >= limit:
            break

    return result


# ---------------------------------------------------------------------------
# Payment method
# ---------------------------------------------------------------------------

def get_default_payment_method(stripe, customer_id: str) -> PaymentMethodInfo | None:
    """Return the default payment method for a Stripe customer, or None."""
    try:
        customer = stripe.Customer.retrieve(
            customer_id,
            expand=["invoice_settings.default_payment_method"],
        )
        pm = (customer.get("invoice_settings") or {}).get("default_payment_method")

        if not pm:
            pms = stripe.PaymentMethod.list(customer=customer_id, type="card")
            if pms.data:
                pm = pms.data[0]

        if not pm:
            pms = stripe.PaymentMethod.list(customer=customer_id, type="us_bank_account")
            if pms.data:
                pm = pms.data[0]

        if not pm:
            return None

        pm_type = pm.get("type", "")
        info = PaymentMethodInfo(id=pm.get("id", ""), type=pm_type)

        if pm_type == "card":
            card = pm.get("card") or {}
            info.brand = (card.get("brand") or "card").capitalize()
            info.last4 = card.get("last4")
            info.exp_month = card.get("exp_month")
            info.exp_year = card.get("exp_year")
        elif pm_type == "us_bank_account":
            bank = pm.get("us_bank_account") or {}
            info.bank_name = bank.get("bank_name") or "Bank account"
            info.last4 = bank.get("last4")
            info.account_type = bank.get("account_type")

        return info

    except Exception as exc:
        logger.warning("Failed to get payment method for customer %s: %s", customer_id, exc)
        return None


# ---------------------------------------------------------------------------
# Next billing date
# ---------------------------------------------------------------------------

def get_next_billing_date(stripe, subscription_id: str) -> int | None:
    """Return Unix timestamp of the next billing date, or None on error."""
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        return sub.get("current_period_end")
    except Exception as exc:
        logger.warning("Failed to retrieve subscription %s: %s", subscription_id, exc)
        return None


# ---------------------------------------------------------------------------
# Webhook event parsing
# ---------------------------------------------------------------------------

def parse_webhook_event(
    stripe,
    payload: bytes,
    sig_header: str,
    webhook_secret: str,
) -> dict[str, Any]:
    """Verify HMAC signature and return the Stripe event dict.

    Raises stripe.error.SignatureVerificationError on bad signature.
    """
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
