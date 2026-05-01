"use client";

import { useEffect, useState, useCallback } from "react";
import {
  ShieldCheck, AlertTriangle, TrendingUp, Users, Activity,
  RefreshCw, Ban, GitBranch, ClipboardList, Trash2, Check, Loader2,
} from "lucide-react";
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

type IcpExclusion = {
  id: string;
  company_id: string | null;
  domain: string | null;
  reason: string;
  detail: string | null;
  excluded_by: string;
  excluded_at: string;
  companies?: { name: string } | null;
};

type TitleReviewItem = {
  id: string;
  title: string;
  industry: string;
  haiku_tier: string;
  haiku_confidence: number;
  haiku_reasoning: string;
  status: string;
  created_at: string;
};

type ThreadingRow = {
  id: string;
  company_id: string;
  state: string;
  contact_1_sent_at: string | null;
  contact_2_sent_at: string | null;
  last_reply_at: string | null;
  pqs_at_start: number | null;
  updated_at: string;
  companies?: { name: string; domain: string; tier: string; pqs_total: number } | null;
};

type Tab = "metrics" | "icp" | "titles" | "threading";

function pct(n: number) { return `${(n * 100).toFixed(1)}%`; }
function timeSince(iso?: string | null) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86400000);
  if (d > 0) return `${d}d ago`;
  const h = Math.floor(diff / 3600000);
  if (h > 0) return `${h}h ago`;
  return "just now";
}

function MetricCard({ label, value, sub, alert }: { label: string; value: string; sub?: string; alert?: boolean }) {
  return (
    <div className={cn("rounded-lg border p-4 bg-white dark:bg-gray-900", alert ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/20" : "border-gray-200 dark:border-gray-700")}>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 mb-1">{label}</p>
      <p className={cn("text-2xl font-bold", alert ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-gray-100")}>{value}</p>
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

const THREADING_STATE_COLORS: Record<string, string> = {
  not_started: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  contact_1_queued: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  contact_1_sent: "bg-blue-200 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300",
  contact_1_engaged: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  contact_2_queued: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  contact_2_sent: "bg-purple-200 text-purple-800 dark:bg-purple-900/50 dark:text-purple-300",
  paused: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  closed_won: "bg-green-200 text-green-800 dark:bg-green-900/50 dark:text-green-300",
  closed_lost: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  excluded: "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-400",
};

export default function QualityPage() {
  const [tab, setTab] = useState<Tab>("metrics");
  const [days, setDays] = useState(7);

  // Metrics tab
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null);
  const [contacts, setContacts] = useState<ContactQuality | null>(null);
  const [assertions, setAssertions] = useState<AssertionSummary | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);

  // ICP tab
  const [exclusions, setExclusions] = useState<IcpExclusion[]>([]);
  const [icpLoading, setIcpLoading] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  // Title review tab
  const [titleItems, setTitleItems] = useState<TitleReviewItem[]>([]);
  const [titlesLoading, setTitlesLoading] = useState(false);
  const [resolving, setResolving] = useState<string | null>(null);

  // Threading tab
  const [threadingRows, setThreadingRows] = useState<ThreadingRow[]>([]);
  const [threadingLoading, setThreadingLoading] = useState(false);
  const [threadingDist, setThreadingDist] = useState<Record<string, number>>({});

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const [m, c, a] = await Promise.all([
        fetch(`${API_BASE}/api/quality/metrics?days=${days}`).then((r) => r.json()),
        fetch(`${API_BASE}/api/quality/contacts`).then((r) => r.json()),
        fetch(`${API_BASE}/api/quality/assertions?days=${days}`).then((r) => r.json()),
      ]);
      setMetrics(m);
      setContacts(c);
      setAssertions(a);
    } catch { /* keep stale */ } finally { setMetricsLoading(false); }
  }, [days]);

  const loadIcp = useCallback(async () => {
    setIcpLoading(true);
    try {
      const data = await fetch(`${API_BASE}/api/quality/icp-exclusions`).then((r) => r.json());
      setExclusions(data.exclusions || []);
    } catch { } finally { setIcpLoading(false); }
  }, []);

  const loadTitles = useCallback(async () => {
    setTitlesLoading(true);
    try {
      const data = await fetch(`${API_BASE}/api/quality/title-review?status=pending`).then((r) => r.json());
      setTitleItems(data.items || []);
    } catch { } finally { setTitlesLoading(false); }
  }, []);

  const loadThreading = useCallback(async () => {
    setThreadingLoading(true);
    try {
      const data = await fetch(`${API_BASE}/api/quality/threading`).then((r) => r.json());
      setThreadingRows(data.companies || []);
      setThreadingDist(data.state_distribution || {});
    } catch { } finally { setThreadingLoading(false); }
  }, []);

  useEffect(() => { loadMetrics(); }, [loadMetrics]);
  useEffect(() => { if (tab === "icp") loadIcp(); }, [tab, loadIcp]);
  useEffect(() => { if (tab === "titles") loadTitles(); }, [tab, loadTitles]);
  useEffect(() => { if (tab === "threading") loadThreading(); }, [tab, loadThreading]);

  const removeExclusion = async (id: string) => {
    setRemoving(id);
    try {
      await fetch(`${API_BASE}/api/quality/icp-exclusions/${id}`, { method: "DELETE" });
      setExclusions((ex) => ex.filter((e) => e.id !== id));
    } catch { } finally { setRemoving(null); }
  };

  const resolveTitle = async (id: string, tier: string) => {
    setResolving(id);
    try {
      await fetch(`${API_BASE}/api/quality/title-review/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ human_tier: tier, reviewed_by: "dashboard" }),
      });
      setTitleItems((items) => items.filter((i) => i.id !== id));
    } catch { } finally { setResolving(null); }
  };

  const firingAlerts = metrics ? Object.entries(metrics.alerts).filter(([, v]) => v.firing) : [];

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "metrics", label: "Metrics", icon: <Activity className="h-3.5 w-3.5" /> },
    { key: "icp", label: "ICP Exclusions", icon: <Ban className="h-3.5 w-3.5" /> },
    { key: "titles", label: "Title Review", icon: <ClipboardList className="h-3.5 w-3.5" /> },
    { key: "threading", label: "Threading", icon: <GitBranch className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="flex flex-col gap-0 h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-gray-700 dark:text-gray-300" />
          <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100">Outreach Quality</h1>
        </div>
        <div className="flex items-center gap-2">
          {tab === "metrics" && (
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300"
            >
              {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
            </select>
          )}
          <button
            onClick={() => { if (tab === "metrics") loadMetrics(); else if (tab === "icp") loadIcp(); else if (tab === "titles") loadTitles(); else loadThreading(); }}
            className="flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 dark:border-gray-800 px-6 shrink-0">
        {TABS.map(({ key, label, icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors",
              tab === key
                ? "border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            )}
          >
            {icon}{label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-6">

        {/* ── METRICS TAB ── */}
        {tab === "metrics" && (
          <div className="flex flex-col gap-6 max-w-5xl">
            {firingAlerts.length > 0 && (
              <div className="flex flex-col gap-2">
                {firingAlerts.map(([key, alert]) => (
                  <AlertBanner key={key} label={`Alert: ${key.replace(/_/g, " ")} = ${pct(alert.value)} (threshold ${pct(alert.threshold)})`} action={alert.action} />
                ))}
              </div>
            )}

            <section>
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                Rate Metrics — {days}-day window{metrics && ` · ${metrics.total_sent.toLocaleString()} sends`}
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                <MetricCard label="Reply Rate" value={metrics ? pct(metrics.metrics.reply_rate) : "—"} sub="target > 3%" />
                <MetricCard label="Positive Reply" value={metrics ? pct(metrics.metrics.positive_reply_rate) : "—"} sub="interested + meeting" />
                <MetricCard label="Meeting Conv." value={metrics ? pct(metrics.metrics.meeting_conversion_rate) : "—"} sub={metrics ? `${metrics.meetings_booked} booked` : undefined} />
                <MetricCard label="Wrong Person" value={metrics ? pct(metrics.metrics.wrong_person_reply_rate) : "—"} sub="threshold < 1%" alert={metrics?.alerts.wrong_person_rate?.firing} />
                <MetricCard label="Assertion Failures" value={metrics ? pct(metrics.metrics.assertion_failure_rate) : "—"} sub="pre-send blocks" alert={metrics?.alerts.assertion_failures?.firing} />
              </div>
            </section>

            <section>
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-1.5">
                <Users className="h-3 w-3" /> Contact Gate Health
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                <MetricCard label="Total Contacts" value={contacts ? contacts.total_contacts.toLocaleString() : "—"} />
                <MetricCard label="Outreach Eligible" value={contacts ? contacts.outreach_eligible.toLocaleString() : "—"} sub={contacts ? `${pct(contacts.gate_pass_rate)} pass rate` : undefined} />
                <MetricCard label="Email Bounce/Invalid" value={contacts ? contacts.email_status_invalid_or_bounce.toLocaleString() : "—"} alert={contacts ? contacts.email_status_invalid_or_bounce > 0 : false} />
                <MetricCard label="Name Mismatch" value={contacts ? contacts.email_name_mismatch.toLocaleString() : "—"} sub="wrong-person risk" alert={contacts ? contacts.email_name_mismatch > 0 : false} />
                <MetricCard label="Avg CCS" value={contacts?.avg_ccs != null ? contacts.avg_ccs.toString() : "—"} sub="target ≥ 70" />
                <MetricCard label="Excluded Function" value={contacts ? contacts.excluded_wrong_function.toLocaleString() : "—"} sub="non-buyer roles" />
                <MetricCard label="Borderline" value={contacts ? contacts.borderline.toLocaleString() : "—"} sub="needs human review" />
              </div>
            </section>

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
                        <div className={cn("w-full rounded-t", isEligible ? "bg-green-500 dark:bg-green-600" : "bg-gray-200 dark:bg-gray-700")} style={{ height: `${Math.max(heightPct, 4)}%` }} />
                        <span className="text-[10px] text-gray-400">{bucket}</span>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-1 text-[10px] text-gray-400">Green = outreach eligible (CCS ≥ {contacts.ccs_thresholds.outbound_eligible}). Preferred VP/C-level: ≥ {contacts.ccs_thresholds.preferred_vp_clevel}.</p>
              </section>
            )}

            {assertions && assertions.total_failures > 0 && (
              <section>
                <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400 flex items-center gap-1.5">
                  <Activity className="h-3 w-3" /> Pre-Send Assertion Failures
                </p>
                <div className="rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800">
                  {Object.entries(assertions.by_assertion_type).map(([type, count]) => (
                    <div key={type} className="flex items-center justify-between px-4 py-2.5">
                      <span className="text-sm text-gray-700 dark:text-gray-300">{type.replace(/_/g, " ")}</span>
                      <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{count}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}

        {/* ── ICP EXCLUSIONS TAB ── */}
        {tab === "icp" && (
          <div className="max-w-4xl">
            <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
              Companies excluded from the pipeline. Added automatically when a prospect replies "not a fit", or manually below.
            </p>
            {icpLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-8"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
            ) : exclusions.length === 0 ? (
              <p className="text-sm text-gray-400 py-8 text-center">No ICP exclusions yet.</p>
            ) : (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800">
                <div className="grid grid-cols-[2fr_1fr_1fr_1fr_40px] gap-4 px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  <span>Company</span>
                  <span>Reason</span>
                  <span>Excluded by</span>
                  <span>When</span>
                  <span />
                </div>
                {exclusions.map((ex) => (
                  <div key={ex.id} className="grid grid-cols-[2fr_1fr_1fr_1fr_40px] gap-4 items-center px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {ex.companies?.name || ex.domain || ex.company_id || "Unknown"}
                      </p>
                      {ex.detail && <p className="text-xs text-gray-400 truncate">{ex.detail}</p>}
                    </div>
                    <span className="text-xs text-gray-600 dark:text-gray-400 capitalize">{ex.reason.replace(/_/g, " ")}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-500">{ex.excluded_by}</span>
                    <span className="text-xs text-gray-400">{timeSince(ex.excluded_at)}</span>
                    <button
                      onClick={() => removeExclusion(ex.id)}
                      disabled={removing === ex.id}
                      className="flex items-center justify-center rounded p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 disabled:opacity-50"
                      title="Remove exclusion"
                    >
                      {removing === ex.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── TITLE REVIEW TAB ── */}
        {tab === "titles" && (
          <div className="max-w-4xl">
            <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
              Job titles where Haiku confidence was below 65%. Confirm the correct tier to cache the result and prevent repeat API calls.
            </p>
            {titlesLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-8"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
            ) : titleItems.length === 0 ? (
              <p className="text-sm text-gray-400 py-8 text-center">No titles pending review.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {titleItems.map((item) => (
                  <div key={item.id} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3 flex items-center gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{item.title}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{item.industry || "No industry"} — Haiku: <span className="font-medium">{item.haiku_tier}</span> ({Math.round((item.haiku_confidence || 0) * 100)}% conf)</p>
                      {item.haiku_reasoning && <p className="text-xs text-gray-400 italic mt-0.5 truncate">{item.haiku_reasoning}</p>}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {(["target", "borderline", "excluded"] as const).map((tier) => (
                        <button
                          key={tier}
                          onClick={() => resolveTitle(item.id, tier)}
                          disabled={resolving === item.id}
                          className={cn(
                            "flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium disabled:opacity-50 transition-colors",
                            tier === "target" ? "bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400" :
                            tier === "borderline" ? "bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-900/30 dark:text-amber-400" :
                            "bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400"
                          )}
                        >
                          {resolving === item.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                          {tier}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── THREADING TAB ── */}
        {tab === "threading" && (
          <div className="max-w-5xl">
            {Object.keys(threadingDist).length > 0 && (
              <div className="flex flex-wrap gap-2 mb-5">
                {Object.entries(threadingDist).map(([state, count]) => (
                  <span key={state} className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium", THREADING_STATE_COLORS[state] || "bg-gray-100 text-gray-600")}>
                    {state.replace(/_/g, " ")} <span className="font-bold">{count}</span>
                  </span>
                ))}
              </div>
            )}
            {threadingLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-8"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
            ) : threadingRows.length === 0 ? (
              <p className="text-sm text-gray-400 py-8 text-center">No threading state records yet. Run outreach to generate data.</p>
            ) : (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800">
                <div className="grid grid-cols-[2fr_1.5fr_1fr_1fr_1fr] gap-4 px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  <span>Company</span>
                  <span>State</span>
                  <span>Contact 1 sent</span>
                  <span>Last reply</span>
                  <span>PQS</span>
                </div>
                {threadingRows.map((row) => (
                  <div key={row.id} className="grid grid-cols-[2fr_1.5fr_1fr_1fr_1fr] gap-4 items-center px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                        {row.companies?.name || row.company_id}
                      </p>
                      {row.companies?.domain && <p className="text-xs text-gray-400 truncate">{row.companies.domain}</p>}
                    </div>
                    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium w-fit", THREADING_STATE_COLORS[row.state] || "bg-gray-100 text-gray-600")}>
                      {row.state.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-gray-500">{timeSince(row.contact_1_sent_at)}</span>
                    <span className="text-xs text-gray-500">{timeSince(row.last_reply_at) || "—"}</span>
                    <span className="text-xs text-gray-500">{row.pqs_at_start ?? "—"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
