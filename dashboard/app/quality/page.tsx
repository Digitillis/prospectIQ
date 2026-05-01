"use client";

import { useEffect, useState } from "react";
import { ShieldCheck, AlertTriangle, TrendingUp, Users, Activity, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";

type QualityMetrics = {
  window_days: number;
  total_sent: number;
  metrics: {
    reply_rate: number;
    positive_reply_rate: number;
    wrong_person_reply_rate: number;
    meeting_conversion_rate: number;
    assertion_failure_rate: number;
  };
  alerts: Record<string, { value: number; threshold: number; firing: boolean; action: string }>;
  reply_intent_breakdown: Record<string, number>;
  meetings_booked: number;
};

type ContactQuality = {
  total_contacts: number;
  outreach_eligible: number;
  excluded_wrong_function: number;
  borderline: number;
  email_status_invalid_or_bounce: number;
  email_name_mismatch: number;
  gate_pass_rate: number;
  avg_ccs: number | null;
  ccs_distribution: Record<string, number>;
  ccs_thresholds: { outbound_eligible: number; preferred_vp_clevel: number };
};

type AssertionSummary = {
  window_days: number;
  total_failures: number;
  by_assertion_type: Record<string, number>;
};

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

function MetricCard({
  label,
  value,
  sub,
  alert,
}: {
  label: string;
  value: string;
  sub?: string;
  alert?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-4 bg-white dark:bg-gray-900",
        alert
          ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/20"
          : "border-gray-200 dark:border-gray-700"
      )}
    >
      <p className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 mb-1">
        {label}
      </p>
      <p
        className={cn(
          "text-2xl font-bold",
          alert ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-gray-100"
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{sub}</p>}
    </div>
  );
}

function AlertBanner({ label, action }: { label: string; action: string }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/20 px-4 py-3">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
      <div>
        <p className="text-sm font-semibold text-red-700 dark:text-red-400">{label}</p>
        <p className="text-xs text-red-600 dark:text-red-500">{action}</p>
      </div>
    </div>
  );
}

export default function QualityPage() {
  const [days, setDays] = useState(7);
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null);
  const [contacts, setContacts] = useState<ContactQuality | null>(null);
  const [assertions, setAssertions] = useState<AssertionSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [m, c, a] = await Promise.all([
        fetch(`${API_BASE}/api/quality/metrics?days=${days}`).then((r) => r.json()),
        fetch(`${API_BASE}/api/quality/contacts`).then((r) => r.json()),
        fetch(`${API_BASE}/api/quality/assertions?days=${days}`).then((r) => r.json()),
      ]);
      setMetrics(m);
      setContacts(c);
      setAssertions(a);
    } catch {
      // silently fail — stale data stays
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [days]);

  const firingAlerts = metrics
    ? Object.entries(metrics.alerts).filter(([, v]) => v.firing)
    : [];

  return (
    <div className="flex flex-col gap-6 p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-gray-700 dark:text-gray-300" />
          <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Outreach Quality
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300"
          >
            {[7, 14, 30, 60, 90].map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Firing alerts */}
      {firingAlerts.length > 0 && (
        <div className="flex flex-col gap-2">
          {firingAlerts.map(([key, alert]) => (
            <AlertBanner
              key={key}
              label={`Alert: ${key.replace(/_/g, " ")} = ${pct(alert.value)} (threshold ${pct(alert.threshold)})`}
              action={alert.action}
            />
          ))}
        </div>
      )}

      {/* Rate metrics */}
      <section>
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          Rate Metrics — {days}-day window
          {metrics && ` · ${metrics.total_sent.toLocaleString()} sends`}
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <MetricCard
            label="Reply Rate"
            value={metrics ? pct(metrics.metrics.reply_rate) : "—"}
            sub="target > 3%"
          />
          <MetricCard
            label="Positive Reply"
            value={metrics ? pct(metrics.metrics.positive_reply_rate) : "—"}
            sub="interested + meeting"
          />
          <MetricCard
            label="Meeting Conv."
            value={metrics ? pct(metrics.metrics.meeting_conversion_rate) : "—"}
            sub={metrics ? `${metrics.meetings_booked} booked` : undefined}
          />
          <MetricCard
            label="Wrong Person"
            value={metrics ? pct(metrics.metrics.wrong_person_reply_rate) : "—"}
            sub="threshold < 1%"
            alert={
              metrics
                ? metrics.alerts.wrong_person_rate?.firing
                : false
            }
          />
          <MetricCard
            label="Assertion Failures"
            value={metrics ? pct(metrics.metrics.assertion_failure_rate) : "—"}
            sub="pre-send blocks"
            alert={metrics ? metrics.alerts.assertion_failures?.firing : false}
          />
        </div>
      </section>

      {/* Contact quality */}
      <section>
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-1.5">
          <Users className="h-3 w-3" /> Contact Gate Health
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <MetricCard
            label="Total Contacts"
            value={contacts ? contacts.total_contacts.toLocaleString() : "—"}
          />
          <MetricCard
            label="Outreach Eligible"
            value={contacts ? contacts.outreach_eligible.toLocaleString() : "—"}
            sub={contacts ? `${pct(contacts.gate_pass_rate)} pass rate` : undefined}
          />
          <MetricCard
            label="Email Bounce / Invalid"
            value={contacts ? contacts.email_status_invalid_or_bounce.toLocaleString() : "—"}
            alert={contacts ? contacts.email_status_invalid_or_bounce > 0 : false}
          />
          <MetricCard
            label="Name Mismatch"
            value={contacts ? contacts.email_name_mismatch.toLocaleString() : "—"}
            sub="wrong-person risk"
            alert={contacts ? contacts.email_name_mismatch > 0 : false}
          />
          <MetricCard
            label="Avg CCS"
            value={contacts?.avg_ccs != null ? contacts.avg_ccs.toString() : "—"}
            sub="target ≥ 70"
          />
          <MetricCard
            label="Excluded Function"
            value={contacts ? contacts.excluded_wrong_function.toLocaleString() : "—"}
            sub="non-buyer roles"
          />
          <MetricCard
            label="Borderline"
            value={contacts ? contacts.borderline.toLocaleString() : "—"}
            sub="needs human review"
          />
        </div>
      </section>

      {/* CCS distribution */}
      {contacts?.ccs_distribution && (
        <section>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-1.5">
            <TrendingUp className="h-3 w-3" /> CCS Distribution
          </p>
          <div className="flex items-end gap-2 h-24">
            {Object.entries(contacts.ccs_distribution).map(([bucket, count]) => {
              const total = Object.values(contacts.ccs_distribution).reduce((a, b) => a + b, 0);
              const heightPct = total > 0 ? (count / total) * 100 : 0;
              const isEligible = bucket === "70-85" || bucket === "85-100";
              return (
                <div key={bucket} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-[10px] text-gray-400">{count}</span>
                  <div
                    className={cn(
                      "w-full rounded-t",
                      isEligible
                        ? "bg-green-500 dark:bg-green-600"
                        : "bg-gray-200 dark:bg-gray-700"
                    )}
                    style={{ height: `${Math.max(heightPct, 4)}%` }}
                  />
                  <span className="text-[10px] text-gray-400">{bucket}</span>
                </div>
              );
            })}
          </div>
          <p className="mt-1 text-[10px] text-gray-400">
            Green bars (70+) = outreach eligible. CCS threshold:{" "}
            {contacts.ccs_thresholds.outbound_eligible} for outbound,{" "}
            {contacts.ccs_thresholds.preferred_vp_clevel} preferred.
          </p>
        </section>
      )}

      {/* Assertion failures */}
      {assertions && assertions.total_failures > 0 && (
        <section>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-1.5">
            <Activity className="h-3 w-3" /> Pre-Send Assertion Failures — {days}-day window
          </p>
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800">
            {Object.entries(assertions.by_assertion_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-sm text-gray-700 dark:text-gray-300">
                  {type.replace(/_/g, " ")}
                </span>
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {count}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {assertions && assertions.total_failures === 0 && !loading && (
        <p className="text-center text-sm text-gray-400 py-4">
          No assertion failures in the last {days} days.
        </p>
      )}
    </div>
  );
}
