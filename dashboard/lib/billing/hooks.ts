/**
 * useBillingData — shared React hook for billing page data.
 *
 * Accepts an `authFetch` function so it works in both apps:
 *   - ProspectIQ: passes supabase-session authFetch
 *   - Digitillis: passes JWT authFetch
 *
 * Usage:
 *   const { billing, invoices, paymentMethod, loading, refetch } = useBillingData(authFetch);
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  BillingStatus,
  Invoice,
  PaymentMethod,
  TierPlan,
  BillingPageData,
} from "./types";

type FetchFn = (path: string, options?: RequestInit) => Promise<any>;

export function useBillingData(authFetch: FetchFn): BillingPageData {
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [plans, setPlans] = useState<TierPlan[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);

    // Plans endpoint is unauthenticated — fetch independently
    authFetch("/api/billing/plans")
      .then((d) => setPlans(d.plans ?? []))
      .catch(() => {});

    // Status, invoices, payment method — fetch in parallel
    Promise.allSettled([
      authFetch("/api/billing/status"),
      authFetch("/api/billing/invoices"),
      authFetch("/api/billing/payment-method"),
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
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  return { billing, plans, invoices, paymentMethod, loading, error, refetch: load };
}
