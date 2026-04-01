/**
 * Shared billing types — copy this file into any Next.js app that uses billing_core.
 *
 * Used by:
 *   - ProspectIQ: dashboard/app/settings/billing/page.tsx
 *   - Digitillis: frontend/src/app/admin/billing/page.tsx  (copy as-is)
 */

export interface TierPlan {
  tier: string;
  label: string;
  monthly_usd: number;
  seats_limit: number;
  companies_per_month: number;
  features: string[];
  annual_discount_pct: number;
}

export interface BillingUsage {
  companies_this_month: number;
  companies_limit: number;
  contacts_total: number;
  outreach_this_month: number;
}

export interface BillingSeats {
  used: number;
  limit: number;
}

export interface BillingStatus {
  tier: string;
  tier_label: string;
  subscription_status: string;   // active | trialing | past_due | canceled
  monthly_usd: number;
  features: string[];
  seats: BillingSeats;
  usage: BillingUsage;
  next_billing_date: number | null;   // Unix timestamp
  has_stripe_customer: boolean;
  has_subscription: boolean;
  upgrade_available: boolean;
}

export interface Invoice {
  id: string;
  number: string | null;
  status: string;                // paid | open | draft | void | uncollectible
  amount_due: number;
  amount_paid: number;
  currency: string;
  created: number;               // Unix timestamp
  due_date: number | null;       // Unix timestamp or null
  period_start: number | null;
  period_end: number | null;
  description: string;
  hosted_invoice_url: string | null;
  invoice_pdf: string | null;
}

export interface CardInfo {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
}

export interface BankInfo {
  bank_name: string;
  last4: string;
  account_type: string;
}

export interface PaymentMethod {
  id: string;
  type: string;                  // "card" | "us_bank_account"
  card?: CardInfo;
  bank?: BankInfo;
}

/** Aggregated state returned by useBillingData hook */
export interface BillingPageData {
  billing: BillingStatus | null;
  plans: TierPlan[];
  invoices: Invoice[];
  paymentMethod: PaymentMethod | null;
  loading: boolean;
  error: string | null;
  /** Call to force a full refresh (e.g., after checkout success) */
  refetch: () => void;
}
