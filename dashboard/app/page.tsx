"use client";

/**
 * Command Center — Primary operational dashboard.
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  MessageSquare,
  FileText,
  Zap,
  TrendingUp,
  RefreshCw,
  Inbox,
  DollarSign,
} from "lucide-react";
import { getCommandCenter, updateIntelligenceGoals, getHitlStats, getAnalyticsSummary, type CommandCenterData, type HitlStats, type AnalyticsSummary } from "@/lib/api";
import { cn, getPQSColor } from "@/lib/utils";

const CLASSIFICATION_COLORS: Record<string, string> = {
  interested: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  objection: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  out_of_office: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  soft_no: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  unsubscribe: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  referral: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
};

function classificationLabel(c?: string) {
  const labels: Record<string, string> = {
    interested: "Interested", objection: "Objection", out_of_office: "OOO",
    soft_no: "Soft No", unsubscribe: "Unsub", referral: "Referral", bounce: "Bounce", other: "Other",
  };
  return c ? (labels[c] ?? c) : "Unclassified";
}

function timeSince(iso?: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function qualityBadgeClass(score?: number): string {
  if (!score) return "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400";
  if (score >= 80) return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300";
  if (score >= 60) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
}

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-gray-100 dark:bg-gray-800", className)} />;
}

function KPICard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={cn("text-2xl font-bold text-gray-900 dark:text-gray-100", color)}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{sub}</p>}
    </div>
  );
}

function WeeklyBar({ label, actual, target, onEdit }: { label: string; actual: number; target: number; onEdit: () => void }) {
  const pct = target > 0 ? Math.min((actual / target) * 100, 100) : 0;
  const dayOfWeek = new Date().getDay();
  const daysIn = Math.max(dayOfWeek === 0 ? 7 : dayOfWeek, 1);
  const pace = (actual / daysIn) * 7;
  const barColor = pace >= target ? "bg-green-500" : pace >= target * 0.8 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{label}</span>
        <div className="flex items-center gap-1">
          <span className="text-xs font-semibold text-gray-900 dark:text-gray-100">{actual}</span>
          <span className="text-xs text-gray-400">/</span>
          <button onClick={onEdit} className="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:underline underline-offset-2" title="Click to edit target">{target}</button>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800">
        <div className={cn("h-1.5 rounded-full transition-all", barColor)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function formatCurrencyShort(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${Math.round(v).toLocaleString()}`;
}

export default function CommandCenterPage() {
  const [data, setData] = useState<CommandCenterData | null>(null);
  const [hitlStats, setHitlStats] = useState<HitlStats | null>(null);
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [editingGoal, setEditingGoal] = useState<string | null>(null);
  const [goalInput, setGoalInput] = useState("");

  const doFetch = useCallback(async () => {
    try {
      setLoading(true);
      const [res, hStats, aSum] = await Promise.allSettled([
        getCommandCenter(),
        getHitlStats(),
        getAnalyticsSummary(),
      ]);
      if (res.status === "fulfilled") setData(res.value);
      if (hStats.status === "fulfilled") setHitlStats(hStats.value);
      if (aSum.status === "fulfilled") setAnalyticsSummary(aSum.value);
    } catch {
      // graceful empty state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { doFetch(); }, [doFetch]);

  const saveGoal = async (key: string, value: number) => {
    if (!data) return;
    try {
      await updateIntelligenceGoals({ [key]: value } as Parameters<typeof updateIntelligenceGoals>[0]);
      setData((prev) => prev ? {
        ...prev,
        weekly_goals: { ...prev.weekly_goals, targets: { ...prev.weekly_goals.targets, [key]: value } }
      } : prev);
    } catch { /* noop */ }
    setEditingGoal(null);
  };

  const kpis = data?.kpis;
  const goals = data?.weekly_goals;
  const billing = data?.billing_status;

  return (
    <div className="space-y-6">

      {/* ── Section A: Attention Bar ── */}
      {loading ? (
        <Skeleton className="h-12 w-full rounded-lg" />
      ) : data?.attention_items && data.attention_items.length > 0 ? (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            {data.attention_items.map((item, i) => (
              <span key={i} className="text-sm text-amber-800 dark:text-amber-300">
                <Link href={item.href} className="font-medium hover:underline">{item.label}</Link>
                {i < data.attention_items.length - 1 && <span className="ml-4 text-amber-400">·</span>}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20 px-4 py-3 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
          <span className="text-sm font-medium text-green-700 dark:text-green-400">All clear — no pending actions</span>
        </div>
      )}

      {/* ── Section B: KPI Cards ── */}
      {loading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
              <Skeleton className="h-3 w-24 mb-3" /><Skeleton className="h-8 w-16" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          <KPICard label="Pipeline" value={kpis?.pipeline_total ?? 0} sub="total companies" />
          <KPICard label="Researched" value={kpis?.researched ?? 0} sub={`${kpis?.researched_pct ?? 0}% of pipeline`} />
          <KPICard label="Active Outreach" value={kpis?.active_outreach ?? 0} sub="in sequence" />
          <KPICard label="Replies This Week" value={kpis?.replies_this_week ?? 0} color={(kpis?.replies_this_week ?? 0) > 0 ? "text-green-600 dark:text-green-400" : undefined} />
          <KPICard label="Meetings Booked" value={kpis?.meetings_booked ?? 0} color={(kpis?.meetings_booked ?? 0) > 0 ? "text-green-600 dark:text-green-400" : undefined} />
          <KPICard label="AI Cost / Month" value={`$${(kpis?.ai_cost_month ?? 0).toFixed(2)}`} sub={`${kpis?.ai_cost_pct ?? 0}% of $${kpis?.ai_cost_cap ?? 200} cap`} color={(kpis?.ai_cost_pct ?? 0) >= 90 ? "text-red-600 dark:text-red-400" : undefined} />
        </div>
      )}

      {/* Billing warning */}
      {!loading && billing && (billing.approaching_limit || billing.over_limit) && (
        <div className={cn("rounded-lg border px-4 py-3 flex items-center justify-between",
          billing.over_limit
            ? "border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20"
            : "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20"
        )}>
          <span className="text-sm text-gray-800 dark:text-gray-200">
            You&apos;ve used <strong>{billing.companies_this_month.toLocaleString()} / {billing.companies_limit.toLocaleString()}</strong> companies this month ({billing.usage_pct}%).
          </span>
          <Link href="/settings/billing" className="ml-4 shrink-0 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100">Upgrade →</Link>
        </div>
      )}

      {/* ── Section C: Weekly Cadence ── */}
      {!loading && goals && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Weekly Cadence</h3>
            <span className="text-xs text-gray-400 dark:text-gray-500">Click a target to edit</span>
          </div>
          <div className="flex flex-wrap gap-6">
            {([
              { key: "researched_target", actKey: "researched", label: "Researched" },
              { key: "emails_sent_target", actKey: "emails_sent", label: "Emails Sent" },
              { key: "replies_target", actKey: "replies", label: "Replies" },
              { key: "meetings_target", actKey: "meetings", label: "Meetings" },
            ] as const).map(({ key, actKey, label }) => (
              <div key={key} className="flex-1 min-w-[140px]">
                {editingGoal === key ? (
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{label}</span>
                    <input
                      type="number" value={goalInput} onChange={(e) => setGoalInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") saveGoal(key, parseInt(goalInput) || 0); if (e.key === "Escape") setEditingGoal(null); }}
                      className="w-16 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400"
                      autoFocus
                    />
                    <button onClick={() => saveGoal(key, parseInt(goalInput) || 0)} className="text-xs text-gray-600 hover:text-gray-900">✓</button>
                    <button onClick={() => setEditingGoal(null)} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
                  </div>
                ) : (
                  <WeeklyBar
                    label={label}
                    actual={goals.actuals[actKey] ?? 0}
                    target={goals.targets[key] ?? 0}
                    onEdit={() => { setEditingGoal(key); setGoalInput(String(goals.targets[key] ?? 0)); }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Section D: Three-column operational surface ── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">

        {/* HITL Reply Queue card */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <Inbox className="h-4 w-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Reply Queue</h3>
              {hitlStats && hitlStats.pending > 0 && (
                <span className="rounded-full bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-[10px] font-bold text-red-700 dark:text-red-300">
                  {hitlStats.pending}
                </span>
              )}
            </div>
            <Link href="/hitl" className="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">Review Replies →</Link>
          </div>
          <div className="px-4 py-4">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            ) : hitlStats ? (
              <div className="space-y-3">
                {/* Stats grid */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-gray-50 dark:bg-gray-800 px-3 py-2">
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Pending</p>
                    <p className="text-xl font-bold text-gray-900 dark:text-gray-100">{hitlStats.pending}</p>
                  </div>
                  {hitlStats.avg_response_time_hours > 0 && (
                    <div className="rounded-lg bg-gray-50 dark:bg-gray-800 px-3 py-2">
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Avg Response</p>
                      <p className="text-xl font-bold text-gray-900 dark:text-gray-100">
                        {hitlStats.avg_response_time_hours}h
                      </p>
                    </div>
                  )}
                </div>
                {/* Classification breakdown */}
                {Object.keys(hitlStats.by_classification).length > 0 && (
                  <div className="space-y-1.5">
                    {Object.entries(hitlStats.by_classification)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 4)
                      .map(([clf, count]) => (
                        <div key={clf} className="flex items-center justify-between text-xs">
                          <span className="capitalize text-gray-600 dark:text-gray-400">
                            {clf.replace(/_/g, " ")}
                          </span>
                          <span className="font-medium text-gray-900 dark:text-gray-100">{count}</span>
                        </div>
                      ))}
                  </div>
                )}
                {hitlStats.pending === 0 && (
                  <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                    <CheckCircle2 className="h-4 w-4" />
                    <span className="text-sm">Queue is clear</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-6 text-gray-400">
                <CheckCircle2 className="h-6 w-6 mb-1" />
                <p className="text-sm">No replies pending</p>
              </div>
            )}
          </div>
        </div>

        {/* Reply Queue (Threads) */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Threads</h3>
              {data?.reply_queue && data.reply_queue.length > 0 && (
                <span className="rounded-full bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-[10px] font-bold text-red-700 dark:text-red-300">{data.reply_queue.length}</span>
              )}
            </div>
            <Link href="/threads" className="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">See all →</Link>
          </div>
          <div className="divide-y divide-gray-50 dark:divide-gray-800">
            {loading
              ? Array.from({ length: 3 }).map((_, i) => <div key={i} className="p-4"><Skeleton className="h-4 w-32 mb-2" /><Skeleton className="h-3 w-48" /></div>)
              : !data?.reply_queue || data.reply_queue.length === 0
                ? (<div className="flex flex-col items-center justify-center py-10 text-gray-400"><CheckCircle2 className="h-8 w-8 mb-2" /><p className="text-sm">No replies pending</p></div>)
                : data.reply_queue.slice(0, 5).map((thread) => {
                  const classification = thread.last_message?.classification;
                  return (
                    <div key={thread.id} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{thread.companies?.name ?? "Unknown"}</span>
                          <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium", CLASSIFICATION_COLORS[classification ?? ""] ?? "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400")}>{classificationLabel(classification)}</span>
                        </div>
                        <p className="truncate text-xs text-gray-500 dark:text-gray-500">{thread.contacts?.full_name} · {timeSince(thread.last_message?.sent_at)}</p>
                      </div>
                      <Link href={`/threads?selected=${thread.id}`} className="shrink-0 rounded-md bg-gray-100 dark:bg-gray-800 px-2.5 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">Review →</Link>
                    </div>
                  );
                })
            }
          </div>
        </div>

        {/* Draft Approvals */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Draft Approvals</h3>
              {data?.draft_queue && data.draft_queue.length > 0 && (
                <span className="rounded-full bg-amber-100 dark:bg-amber-900/30 px-1.5 py-0.5 text-[10px] font-bold text-amber-700 dark:text-amber-300">{data.draft_queue.length}</span>
              )}
            </div>
            <Link href="/outreach" className="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">See all →</Link>
          </div>
          <div className="divide-y divide-gray-50 dark:divide-gray-800">
            {loading
              ? Array.from({ length: 3 }).map((_, i) => <div key={i} className="p-4"><Skeleton className="h-4 w-32 mb-2" /><Skeleton className="h-3 w-48" /></div>)
              : !data?.draft_queue || data.draft_queue.length === 0
                ? (<div className="flex flex-col items-center justify-center py-10 text-gray-400"><CheckCircle2 className="h-8 w-8 mb-2" /><p className="text-sm">No drafts pending</p></div>)
                : data.draft_queue.slice(0, 5).map((draft) => {
                  const pqs = draft.companies?.pqs_total ?? 0;
                  const qs = draft.quality_score;
                  return (
                    <div key={draft.id} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{draft.companies?.name ?? "Unknown"}</span>
                          <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold", getPQSColor(pqs))}>PQS {pqs}</span>
                        </div>
                        <p className="truncate text-xs text-gray-500 dark:text-gray-500">{draft.subject}</p>
                        {qs !== undefined && <span className={cn("mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium", qualityBadgeClass(qs))}>Q:{qs}</span>}
                      </div>
                      <Link href="/outreach" className="shrink-0 rounded-md bg-gray-900 dark:bg-white px-2.5 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100">Approve</Link>
                    </div>
                  );
                })
            }
          </div>
        </div>

        {/* Hot Signals */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Hot Signals</h3>
            </div>
            <Link href="/signals" className="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">See all →</Link>
          </div>
          <div className="divide-y divide-gray-50 dark:divide-gray-800">
            {loading
              ? Array.from({ length: 3 }).map((_, i) => <div key={i} className="p-4"><Skeleton className="h-4 w-32 mb-2" /><Skeleton className="h-3 w-48" /></div>)
              : !data?.hot_signals || data.hot_signals.length === 0
                ? (<div className="flex flex-col items-center justify-center py-10 text-gray-400"><Zap className="h-8 w-8 mb-2" /><p className="text-sm">No hot signals yet</p></div>)
                : data.hot_signals.slice(0, 5).map((sig) => (
                  <div key={sig.company_id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{sig.company_name}</span>
                        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase", sig.intent_level === "hot" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300")}>{sig.intent_level}</span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-500">Intent {sig.intent_score} pts · PQS {sig.pqs_total}</p>
                    </div>
                    <Link href="/sequences" className="shrink-0 rounded-md bg-gray-100 dark:bg-gray-800 px-2.5 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 whitespace-nowrap">Sequence →</Link>
                  </div>
                ))
            }
          </div>
        </div>

      </div>

      {/* ── Section E: Pipeline Funnel ── */}
      {!loading && data?.funnel_summary && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="h-4 w-4 text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Pipeline Funnel (30 days)</h3>
          </div>
          <div className="flex items-stretch gap-1 overflow-x-auto pb-2">
            {([
              { key: "discovered", label: "Discovered" },
              { key: "enriched", label: "Enriched" },
              { key: "sequenced", label: "Sequenced" },
              { key: "touch_1_sent", label: "Touch 1" },
              { key: "replied", label: "Replied" },
              { key: "demo_scheduled", label: "Demo" },
              { key: "closed_won", label: "Won" },
            ] as const).map((stage, i, arr) => {
              const funnel = data.funnel_summary as Record<string, unknown>;
              const count = (funnel[stage.key] as number) ?? 0;
              const rates = (funnel.conversion_rates as Record<string, number>) ?? {};
              const prevKey = i > 0 ? arr[i - 1].key : null;
              const rate = prevKey ? rates[`${prevKey}_to_${stage.key}`] : null;
              return (
                <div key={stage.key} className="flex items-center gap-1 shrink-0">
                  <Link href={`/pipeline?status=${stage.key}`} className="flex flex-col items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors min-w-[90px]">
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">{stage.label}</span>
                    <span className="text-xl font-bold text-gray-900 dark:text-gray-100">{count}</span>
                  </Link>
                  {i < arr.length - 1 && (
                    <div className="flex flex-col items-center shrink-0">
                      <ArrowRight className="h-4 w-4 text-gray-300 dark:text-gray-600" />
                      {rate !== null && rate !== undefined && <span className="text-[9px] text-gray-400 dark:text-gray-500">{rate}%</span>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Section F: Revenue Intelligence Card ── */}
      {!loading && analyticsSummary && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <DollarSign className="h-4 w-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Revenue Intelligence</h3>
              <span className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
                analyticsSummary.pipeline_health === "green"
                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                  : analyticsSummary.pipeline_health === "amber"
                  ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                  : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300"
              )}>
                {analyticsSummary.pipeline_health}
              </span>
            </div>
            <Link href="/analytics/revenue" className="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">
              Full analytics →
            </Link>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Projected ARR (90d)</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                {formatCurrencyShort(analyticsSummary.projected_arr_90d)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Replied</p>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                {analyticsSummary.total_replied.toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Conversion Rate</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                {analyticsSummary.overall_conversion_rate.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Best Cluster</p>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
                {analyticsSummary.best_cluster || "—"}
              </p>
            </div>
          </div>

          {analyticsSummary.stuck_in_research_14d > 0 && (
            <div className="flex items-center gap-2 rounded-md bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 px-3 py-2">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
              <span className="text-xs text-amber-700 dark:text-amber-300">
                <strong>{analyticsSummary.stuck_in_research_14d}</strong>{" "}
                {analyticsSummary.stuck_in_research_14d === 1 ? "company" : "companies"} stuck in research for &gt;14 days
              </span>
              <Link href="/pipeline?status=researched" className="ml-auto shrink-0 text-xs font-medium text-amber-700 dark:text-amber-300 hover:underline">
                Review →
              </Link>
            </div>
          )}
        </div>
      )}

      {/* Refresh */}
      <div className="flex justify-end">
        <button onClick={doFetch} disabled={loading} className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 transition-colors">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          Refresh
        </button>
      </div>
    </div>
  );
}
