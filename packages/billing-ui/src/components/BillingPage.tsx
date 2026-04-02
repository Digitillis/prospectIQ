/**
 * BillingPage — drop-in billing page component.
 *
 * Usage in any Next.js / React app:
 *
 *   import { BillingPage } from "@platform/billing-ui";
 *
 *   export default function SettingsBillingPage() {
 *     return (
 *       <BillingPage
 *         config={{
 *           apiFetch: myAuthFetch,
 *           apiPrefix: "/api/v1/billing",
 *           productName: "MyProduct",
 *           salesEmail: "sales@myproduct.com",
 *           usageLabels: {
 *             assets: "Assets connected",
 *             agents: "Active AI agents",
 *             companies_per_month: "Companies / month",
 *           },
 *         }}
 *         onUpgrade={(tier) => myAuthFetch("/api/v1/billing/checkout", {
 *           method: "POST",
 *           body: JSON.stringify({ tier }),
 *         }).then((d) => { if (d.url) window.location.href = d.url; })}
 *         onPortal={() => myAuthFetch("/api/v1/billing/portal", { method: "POST" })
 *           .then((d) => { if (d.url) window.location.href = d.url; })}
 *         accentClass="text-indigo-600 dark:text-indigo-400"
 *         accentBgClass="bg-indigo-600"
 *       />
 *     );
 *   }
 */

"use client";

import { useState, useCallback } from "react";
import {
  CreditCard,
  Zap,
  ArrowUpRight,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

import type { BillingConfig, TierPlan } from "../types";
import { useBillingData } from "../hooks";
import {
  fmtCurrency,
  fmtDate,
  subscriptionStatusColor,
  subscriptionStatusLabel,
  showAnnualBanner,
  annualSavings,
} from "../utils";
import { UsageBar } from "./UsageBar";
import { InvoiceTable } from "./InvoiceTable";
import { PaymentMethodCard } from "./PaymentMethodCard";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface BillingPageProps {
  config: BillingConfig;

  /** Called when the user clicks "Upgrade plan" or a plan card's Upgrade button.
   *  Should start a Stripe Checkout session and redirect the browser. */
  onUpgrade?: (tier: string) => Promise<void>;

  /** Called when the user clicks "Manage / Update payment method".
   *  Should open the Stripe Customer Portal and redirect the browser. */
  onPortal?: () => Promise<void>;

  /** Tailwind text color class for accented links/buttons. */
  accentClass?: string;

  /** Tailwind bg color class for the upgrade button fill state. */
  accentBgClass?: string;

  /** Page title shown in the header. Default: "Billing" */
  title?: string;

  /** Page subtitle. Default: "Manage your subscription, usage, and invoices." */
  subtitle?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BillingPage({
  config,
  onUpgrade,
  onPortal,
  accentClass = "text-blue-600 dark:text-blue-400",
  accentBgClass = "bg-blue-600",
  title = "Billing",
  subtitle = "Manage your subscription, usage, and invoices.",
}: BillingPageProps) {
  const { billing, plans, invoices, paymentMethod, loading, error, refetch } =
    useBillingData(config);

  const [isPortalLoading, setPortalLoading] = useState(false);
  const prefix = config.apiPrefix?.replace(/\/$/, "") ?? "/api/v1/billing";

  const handlePortal = useCallback(async () => {
    if (!onPortal) return;
    setPortalLoading(true);
    try {
      await onPortal();
    } finally {
      setPortalLoading(false);
    }
  }, [onPortal]);

  const handleUpgrade = useCallback(async (tier: string) => {
    if (!onUpgrade) return;
    await onUpgrade(tier);
  }, [onUpgrade]);

  const usageLabels = config.usageLabels ?? {};
  const salesEmail = config.salesEmail ?? "sales@example.com";
  const productName = config.productName ?? "Platform";
  const showInvoices = config.showInvoices !== false;
  const showPlanComparison = config.showPlanComparison !== false;

  // ----------------------------------------------------------------
  // Loading skeleton
  // ----------------------------------------------------------------

  if (loading) {
    return (
      <div className="p-6 sm:p-8 max-w-4xl mx-auto">
        <div className="h-7 w-36 bg-gray-200 dark:bg-gray-700 rounded animate-pulse mb-2" />
        <div className="h-4 w-64 bg-gray-100 dark:bg-gray-800 rounded animate-pulse mb-8" />
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  // ----------------------------------------------------------------
  // Error state
  // ----------------------------------------------------------------

  if (error) {
    return (
      <div className="p-6 sm:p-8 max-w-4xl mx-auto">
        <div className="rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/10 p-5 flex gap-3">
          <AlertCircle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-700 dark:text-red-400">{error}</p>
            <button
              onClick={refetch}
              className="mt-2 text-xs text-red-600 dark:text-red-400 hover:underline"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ----------------------------------------------------------------
  // Derived values
  // ----------------------------------------------------------------

  const currentPlan = plans.find((p) => p.tier === billing?.tier);
  const annualSavingsAmt = billing
    ? annualSavings(billing.monthly_usd, currentPlan?.annual_discount_pct ?? 15)
    : 0;

  // ----------------------------------------------------------------
  // Render
  // ----------------------------------------------------------------

  return (
    <div className="p-6 sm:p-8 max-w-4xl mx-auto space-y-8">

      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">{title}</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{subtitle}</p>
      </div>

      {/* Annual savings banner */}
      {showAnnualBanner(billing) && annualSavingsAmt > 0 && (
        <div className="rounded-xl border border-blue-200 dark:border-blue-800/50 bg-blue-50 dark:bg-blue-900/10 px-5 py-4 flex items-center gap-4">
          <Zap className="h-5 w-5 text-blue-500 shrink-0" />
          <div className="flex-1 text-sm">
            <span className="font-medium text-blue-800 dark:text-blue-300">
              Save {fmtCurrency(annualSavingsAmt)} per year
            </span>
            <span className="text-blue-700 dark:text-blue-400">
              {" "}by switching to annual billing.
            </span>
          </div>
          <button
            onClick={handlePortal}
            className="shrink-0 text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
          >
            Switch to annual
          </button>
        </div>
      )}

      {/* Current plan */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 sm:p-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4">
          Current plan
        </h2>
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
                {billing?.tier_label ?? "—"}
              </span>
              {billing?.subscription_status && (
                <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${subscriptionStatusColor(billing.subscription_status)}`}>
                  {subscriptionStatusLabel(billing.subscription_status)}
                </span>
              )}
            </div>
            {billing && billing.monthly_usd > 0 ? (
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                {fmtCurrency(billing.monthly_usd)} / month
                {billing.next_billing_date && (
                  <> · Next billing {fmtDate(billing.next_billing_date)}</>
                )}
              </p>
            ) : billing?.tier === "enterprise" ? (
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Custom contract</p>
            ) : (
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Free</p>
            )}
            {billing?.features && billing.features.length > 0 && (
              <ul className="mt-3 space-y-1">
                {billing.features.slice(0, 4).map((f) => (
                  <li key={f} className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-400">
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {billing?.upgrade_available && onUpgrade && (
            <button
              onClick={handlePortal}
              className={`shrink-0 flex items-center gap-1.5 text-sm font-medium ${accentClass} hover:underline`}
            >
              Upgrade plan <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </section>

      {/* Usage */}
      {billing && Object.keys(billing.usage).length > 0 && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-5">
            Usage this month
          </h2>
          <div className="space-y-5">
            <UsageBar
              label="Seats"
              used={billing.seats.used}
              limit={billing.seats.limit}
            />
            {Object.entries(billing.usage).map(([key, metric]) => (
              <UsageBar
                key={key}
                label={usageLabels[key] ?? key.replace(/_/g, " ")}
                used={metric.used}
                limit={metric.limit}
              />
            ))}
          </div>
        </section>
      )}

      {/* Payment method */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 sm:p-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4">
          Payment method
        </h2>
        <PaymentMethodCard
          paymentMethod={paymentMethod}
          onUpdate={handlePortal}
          isUpdating={isPortalLoading}
          accentClass={accentClass}
        />
      </section>

      {/* Invoice history */}
      {showInvoices && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4">
            Invoice history
          </h2>
          <InvoiceTable invoices={invoices} />
        </section>
      )}

      {/* Plan comparison */}
      {showPlanComparison && billing?.upgrade_available && plans.length > 0 && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-5">
            Available plans
          </h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {plans
              .filter((p: TierPlan) => p.tier !== "free" && p.tier !== "enterprise")
              .map((plan: TierPlan) => {
                const isCurrent = plan.tier === billing?.tier;
                return (
                  <div
                    key={plan.tier}
                    className={`rounded-lg border p-4 ${
                      isCurrent
                        ? "border-blue-400/50 bg-blue-50/50 dark:bg-blue-900/10"
                        : "border-gray-200 dark:border-gray-700"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-semibold text-gray-900 dark:text-gray-100">
                        {plan.label}
                      </span>
                      {isCurrent && (
                        <span className={`text-xs font-medium ${accentClass}`}>Current</span>
                      )}
                    </div>
                    <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                      {fmtCurrency(plan.monthly_usd)}
                      <span className="text-sm font-normal text-gray-400"> /mo</span>
                    </p>
                    <ul className="mt-3 space-y-1 mb-4">
                      {plan.features.slice(0, 4).map((f: string) => (
                        <li key={f} className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
                          <CheckCircle2 className="h-3 w-3 text-green-500 shrink-0" />
                          {f}
                        </li>
                      ))}
                    </ul>
                    {!isCurrent && plan.price_id && onUpgrade && (
                      <button
                        onClick={() => handleUpgrade(plan.tier)}
                        className={`w-full rounded-lg border text-sm font-medium py-1.5 transition-colors border-current ${accentClass} hover:${accentBgClass} hover:text-white hover:border-transparent`}
                      >
                        Upgrade
                      </button>
                    )}
                  </div>
                );
              })}

            {/* Enterprise card */}
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <p className="font-semibold text-gray-900 dark:text-gray-100 mb-2">Enterprise</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                Unlimited resources, SLA, custom deployment, and dedicated support.
              </p>
              <a
                href={`mailto:${salesEmail}`}
                className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 text-center text-sm font-medium py-1.5 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                Contact sales
              </a>
            </div>
          </div>
        </section>
      )}

    </div>
  );
}
