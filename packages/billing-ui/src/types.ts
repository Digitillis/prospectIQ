/**
 * Billing UI types — platform-agnostic.
 *
 * Field naming conventions:
 *   workspace_id        — the tenant / org / account identifier
 *   resource_limits     — flexible dict keyed by platform-defined metric keys
 *   usage               — Record<metricKey, UsageMetric> matching resource_limits keys
 */

export interface TierPlan {
  tier: string;                     // "free" | "starter" | "professional" | "enterprise"
  label: string;
  price_id?: string;                // Stripe price ID; absent for free/enterprise
  monthly_usd: number;              // 0 for free / custom
  seats_limit: number;
  resource_limits: Record<string, number>;
  // e.g. { "assets": 50, "agents": 10, "companies_per_month": 2000 }
  features: string[];
  annual_discount_pct: number;
}

export interface UsageMetric {
  used: number;
  limit: number;
}

export interface BillingSeats {
  used: number;
  limit: number;
}

export interface BillingStatus {
  tier: string;
  tier_label: string;
  subscription_status: string;      // active | trialing | past_due | canceled
  monthly_usd: number;
  features: string[];
  seats: BillingSeats;
  usage: Record<string, UsageMetric>;
  next_billing_date: number | null;  // Unix timestamp
  has_stripe_customer: boolean;
  has_subscription: boolean;
  upgrade_available: boolean;
}

export interface Invoice {
  id: string;
  number: string | null;
  status: "paid" | "open" | "draft" | "void" | "uncollectible";
  amount_due: number;               // dollars
  amount_paid: number;
  currency: string;                 // "USD"
  created: number;                  // Unix timestamp
  due_date: number | null;
  period_start: number | null;
  period_end: number | null;
  description: string;
  hosted_invoice_url: string | null;
  invoice_pdf: string | null;
}

export interface CardInfo {
  brand: string;                    // "Visa", "Mastercard", …
  last4: string;
  exp_month: number;
  exp_year: number;
}

export interface BankInfo {
  bank_name: string;
  last4: string;
  account_type: "checking" | "savings";
}

export interface PaymentMethod {
  id: string;
  type: "card" | "us_bank_account";
  card?: CardInfo;
  bank?: BankInfo;
}

/** What useBillingData returns. */
export interface BillingPageData {
  billing: BillingStatus | null;
  plans: TierPlan[];
  invoices: Invoice[];
  paymentMethod: PaymentMethod | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * BillingConfig — pass once to BillingPage to wire it into your platform.
 *
 * apiFetch should be your platform's authenticated fetch wrapper.
 * It must return the parsed JSON body.
 */
export interface BillingConfig {
  /** Authenticated fetch function for your platform. */
  apiFetch: <T = unknown>(
    path: string,
    options?: RequestInit
  ) => Promise<T>;

  /** API prefix where billing endpoints are mounted.
   *  Default: "/api/v1/billing"
   */
  apiPrefix?: string;

  /** Product / platform name shown in the "Contact sales" email. */
  productName?: string;

  /** Sales email for the enterprise card. */
  salesEmail?: string;

  /** Whether to show the invoice section. Default: true */
  showInvoices?: boolean;

  /** Whether to show the plan comparison grid. Default: true */
  showPlanComparison?: boolean;

  /**
   * Custom usage metric labels.
   * By default the metric key is used (e.g. "assets").
   * Pass e.g. { assets: "Assets connected", companies_per_month: "Companies / mo" }
   */
  usageLabels?: Record<string, string>;
}
