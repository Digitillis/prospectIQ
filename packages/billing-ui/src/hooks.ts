/**
 * useBillingData — shared React hook for billing page data.
 *
 * Accepts the BillingConfig object so it works in any app:
 *   - ProspectIQ: config.apiFetch = supabase-session authFetch
 *   - Digitillis: config.apiFetch = JWT authFetch
 *
 * Usage:
 *   const { billing, invoices, paymentMethod, loading, refetch } =
 *     useBillingData(config);
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  BillingConfig,
  BillingPageData,
  BillingStatus,
  Invoice,
  PaymentMethod,
  TierPlan,
} from "./types";

export function useBillingData(config: BillingConfig): BillingPageData {
  const prefix = config.apiPrefix?.replace(/\/$/, "") ?? "/api/v1/billing";

  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [plans, setPlans] = useState<TierPlan[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);

    // Plans endpoint is typically unauthenticated
    config
      .apiFetch<{ plans: TierPlan[] }>(`${prefix}/plans`)
      .then((d) => setPlans(d.plans ?? []))
      .catch(() => {});

    Promise.allSettled([
      config.apiFetch<BillingStatus>(`${prefix}/status`),
      config.apiFetch<{ invoices: Invoice[] }>(`${prefix}/invoices`),
      config.apiFetch<{ payment_method: PaymentMethod | null }>(`${prefix}/payment-method`),
    ]).then(([statusRes, invoicesRes, pmRes]) => {
      if (statusRes.status === "fulfilled") {
        setBilling(statusRes.value as BillingStatus);
      } else {
        setError("Could not load billing information.");
      }
      if (invoicesRes.status === "fulfilled") {
        setInvoices((invoicesRes.value as any).invoices ?? []);
      }
      if (pmRes.status === "fulfilled") {
        setPaymentMethod((pmRes.value as any).payment_method ?? null);
      }
    }).finally(() => {
      setLoading(false);
    });
  }, [config.apiFetch, prefix]);

  useEffect(() => {
    load();
  }, [load]);

  return { billing, plans, invoices, paymentMethod, loading, error, refetch: load };
}
