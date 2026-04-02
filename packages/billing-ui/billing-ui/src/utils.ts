/**
 * Billing display utilities — zero external dependencies.
 */

import type { BillingStatus, Invoice, PaymentMethod } from "./types";

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function fmtCurrency(amount: number, currency: string = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function fmtNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

// ---------------------------------------------------------------------------
// Invoice status
// ---------------------------------------------------------------------------

export function invoiceStatusColor(status: Invoice["status"]): string {
  switch (status) {
    case "paid":
      return "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400";
    case "open":
      return "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400";
    case "draft":
      return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
    case "void":
    case "uncollectible":
      return "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400";
    default:
      return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  }
}

// ---------------------------------------------------------------------------
// Subscription status
// ---------------------------------------------------------------------------

export function subscriptionStatusColor(status: string): string {
  switch (status) {
    case "active":
      return "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400";
    case "trialing":
      return "bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400";
    case "past_due":
      return "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400";
    case "canceled":
      return "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400";
    default:
      return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  }
}

export function subscriptionStatusLabel(status: string): string {
  switch (status) {
    case "active":   return "Active";
    case "trialing": return "Trial";
    case "past_due": return "Payment past due";
    case "canceled": return "Canceled";
    default:         return status;
  }
}

// ---------------------------------------------------------------------------
// Payment method
// ---------------------------------------------------------------------------

export function paymentMethodLabel(pm: PaymentMethod): string {
  if (pm.type === "card" && pm.card) {
    return `${pm.card.brand} ···· ${pm.card.last4}`;
  }
  if (pm.type === "us_bank_account" && pm.bank) {
    return `${pm.bank.bank_name} ···· ${pm.bank.last4}`;
  }
  return "Payment method";
}

export function paymentMethodExpiry(pm: PaymentMethod): string | null {
  if (pm.type === "card" && pm.card) {
    const { exp_month, exp_year } = pm.card;
    return `Expires ${String(exp_month).padStart(2, "0")}/${String(exp_year).slice(-2)}`;
  }
  return null;
}

export function isCardExpiringSoon(pm: PaymentMethod): boolean {
  if (pm.type !== "card" || !pm.card) return false;
  const { exp_month, exp_year } = pm.card;
  const now = new Date();
  const expiry = new Date(exp_year, exp_month - 1, 1);
  const sixtyDays = new Date(now.getTime() + 60 * 24 * 60 * 60 * 1000);
  return expiry <= sixtyDays;
}

// ---------------------------------------------------------------------------
// Usage bar helpers
// ---------------------------------------------------------------------------

export function usagePct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

export type UsageLevel = "ok" | "warning" | "danger";

export function usageLevel(used: number, limit: number): UsageLevel {
  const pct = usagePct(used, limit);
  if (pct >= 90) return "danger";
  if (pct >= 75) return "warning";
  return "ok";
}

// ---------------------------------------------------------------------------
// Annual savings banner
// ---------------------------------------------------------------------------

export function showAnnualBanner(billing: BillingStatus | null): boolean {
  if (!billing) return false;
  return (
    billing.monthly_usd > 0 &&
    billing.subscription_status === "active" &&
    billing.tier !== "enterprise"
  );
}

export function annualSavings(monthlyUsd: number, discountPct: number): number {
  return Math.round(monthlyUsd * 12 * (discountPct / 100));
}
