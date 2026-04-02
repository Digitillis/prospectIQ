"use client";

import { BillingPage } from "@platform/billing-ui";
import { supabase } from "@/lib/supabase";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

async function authFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers as Record<string, string>),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export default function BillingSettingsPage() {
  return (
    <BillingPage
      config={{
        apiFetch: authFetch,
        apiPrefix: "/api/billing",
        productName: "ProspectIQ",
        salesEmail: "sales@prospectiq.io",
        usageLabels: {
          companies: "Companies researched",
          contacts: "Contacts enriched",
          outreach: "Outreach actions",
        },
      }}
      onUpgrade={(tier) =>
        authFetch<{ url?: string; checkout_url?: string }>("/api/billing/checkout", {
          method: "POST",
          body: JSON.stringify({ tier }),
        }).then((d) => {
          const url = d.url ?? d.checkout_url;
          if (url) window.location.href = url;
        })
      }
      onPortal={() =>
        authFetch<{ url?: string; portal_url?: string }>("/api/billing/portal", {
          method: "POST",
        }).then((d) => {
          const url = d.url ?? d.portal_url;
          if (url) window.open(url, "_blank");
        })
      }
      accentClass="text-blue-600 dark:text-blue-400"
      accentBgClass="bg-blue-600"
      subtitle="Manage your ProspectIQ subscription, usage, and invoices."
    />
  );
}
