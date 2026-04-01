/**
 * Shared billing utility functions — copy into any app that uses billing_core.
 * Zero external dependencies.
 */

import type { BillingStatus, PaymentMethod, Invoice } from "./types";

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** Format a Unix timestamp as "Jan 15, 2025" */
export function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Format a dollar amount, e.g. 299 → "$299" or 299.50 → "$299.50" */
export function fmtCurrency(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount);
}

/** Format a number with commas: 10000 → "10,000" */
export function fmtNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

// ---------------------------------------------------------------------------
// Invoice helpers
// ---------------------------------------------------------------------------

/**
 * Tailwind CSS classes for invoice status badge color.
 * Works with bg-* and text-* utilities.
 */
export function invoiceStatusColor(status: string): string {
  switch (status) {
    case "paid":           return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400";
    case "open":           return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
    case "draft":          return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400";
    case "void":           return "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500";
    case "uncollectible":  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    default:               return "bg-slate-100 text-slate-600";
  }
}

// ---------------------------------------------------------------------------
// Subscription status helpers
// ---------------------------------------------------------------------------

export function subscriptionStatusColor(status: string): string {
  switch (status) {
    case "active":   return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400";
    case "trialing": return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
    case "past_due": return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    case "canceled": return "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500";
    default:         return "bg-slate-100 text-slate-600";
  }
}

export function subscriptionStatusLabel(status: string): string {
  switch (status) {
    case "active":   return "Active";
    case "trialing": return "Trial";
    case "past_due": return "Past due";
    case "canceled": return "Canceled";
    default:         return status;
  }
}

// ---------------------------------------------------------------------------
// Payment method helpers
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
    return `Expires ${pm.card.exp_month.toString().padStart(2, "0")}/${pm.card.exp_year}`;
  }
  return null;
}

/** True if the card expires within 60 days from now */
export function isCardExpiringSoon(pm: PaymentMethod): boolean {
  if (pm.type !== "card" || !pm.card) return false;
  const expiry = new Date(pm.card.exp_year, pm.card.exp_month - 1, 1);
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() + 60);
  return expiry <= cutoff;
}

// ---------------------------------------------------------------------------
// Usage helpers
// ---------------------------------------------------------------------------

/** Percentage of a limit used, capped at 100 */
export function usagePct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(Math.round((used / limit) * 100), 100);
}

/** "warning" at 80%+, "danger" at 100%+ */
export function usageLevel(used: number, limit: number): "ok" | "warning" | "danger" {
  const pct = usagePct(used, limit);
  if (pct >= 100) return "danger";
  if (pct >= 80)  return "warning";
  return "ok";
}

// ---------------------------------------------------------------------------
// Annual savings
// ---------------------------------------------------------------------------

/** True if the user would benefit from switching to annual billing */
export function showAnnualBanner(billing: BillingStatus): boolean {
  return (
    billing.has_subscription &&
    billing.subscription_status === "active" &&
    billing.tier !== "starter" &&
    billing.monthly_usd > 0
  );
}

/** Monthly savings in dollars at a given discount percentage */
export function annualSavings(monthlyUsd: number, discountPct: number): number {
  return Math.round(monthlyUsd * 12 * (discountPct / 100));
}
