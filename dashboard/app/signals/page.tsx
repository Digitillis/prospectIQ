"use client";

/**
 * Signals — Intent signals and buying signals dashboard
 * Shows companies with high intent scores and contacts showing buying behavior
 */

import { useEffect, useState } from "react";
import {
  Zap,
  TrendingUp,
  Mail,
  Eye,
  BarChart3,
  User,
  ChevronRight,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Star,
  ArrowUpRight,
} from "lucide-react";
import { getIntelligenceSignals, IntentSignal, BuyingSignal } from "@/lib/api";
import { cn, getPQSColor, TIER_LABELS } from "@/lib/utils";
import Link from "next/link";

// ─── Intent Signal Card ───────────────────────────────────────────────────────

function IntentSignalCard({ signal }: { signal: IntentSignal }) {
  const score = signal.intent_score;
  const heat =
    score >= 80 ? "hot" :
    score >= 60 ? "warm" : "mild";

  return (
    <div className={cn(
      "bg-white dark:bg-zinc-900 border rounded-xl p-4 hover:shadow-md transition-shadow",
      heat === "hot" ? "border-orange-200 dark:border-orange-900/40" :
      heat === "warm" ? "border-amber-200 dark:border-amber-900/40" :
      "border-zinc-200 dark:border-zinc-800"
    )}>
      {/* Company header */}
      <div className="flex items-start gap-3 mb-3">
        <div className={cn(
          "w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-bold",
          heat === "hot" ? "bg-orange-100 dark:bg-orange-950 text-orange-600 dark:text-orange-400" :
          heat === "warm" ? "bg-amber-100 dark:bg-amber-950 text-amber-600 dark:text-amber-400" :
          "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
        )}>
          {(signal.company_name || "?")[0].toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100 truncate">
              {signal.company_name}
            </span>
            {heat === "hot" && (
              <span className="flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded bg-orange-100 dark:bg-orange-950 text-orange-600 dark:text-orange-400">
                HOT
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-xs text-zinc-400">
            {signal.tier && <span>{TIER_LABELS[signal.tier] || signal.tier}</span>}
            {signal.cluster && <span>· {signal.cluster.replace(/_/g, " ")}</span>}
            {signal.status && <span>· {signal.status}</span>}
          </div>
        </div>
        {/* Intent score */}
        <div className="flex-shrink-0 text-right">
          <div className={cn(
            "text-2xl font-bold",
            heat === "hot" ? "text-orange-500" :
            heat === "warm" ? "text-amber-500" :
            "text-zinc-500"
          )}>
            {score}
          </div>
          <div className="text-[10px] text-zinc-400">intent</div>
        </div>
      </div>

      {/* Intent score bar */}
      <div className="mb-3">
        <div className="h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              heat === "hot" ? "bg-orange-500" :
              heat === "warm" ? "bg-amber-500" : "bg-zinc-400"
            )}
            style={{ width: `${Math.min(score, 100)}%` }}
          />
        </div>
      </div>

      {/* Signals */}
      {signal.pain_signals && signal.pain_signals.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {signal.pain_signals.slice(0, 3).map((s: string, i: number) => (
            <span
              key={i}
              className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
            >
              {s}
            </span>
          ))}
          {signal.pain_signals.length > 3 && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-400">
              +{signal.pain_signals.length - 3}
            </span>
          )}
        </div>
      )}

      {/* PQS + actions */}
      <div className="flex items-center justify-between pt-2 border-t border-zinc-100 dark:border-zinc-800">
        <span className={cn("text-sm font-bold", getPQSColor(signal.pqs_total))}>
          PQS {signal.pqs_total}
        </span>
        <Link
          href={`/companies/${signal.company_id}`}
          className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          View company <ArrowUpRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}

// ─── Buying Signal Card ───────────────────────────────────────────────────────

function BuyingSignalCard({ signal }: { signal: BuyingSignal }) {
  return (
    <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-950 flex items-center justify-center flex-shrink-0">
          <User className="w-4 h-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100 truncate">
            {signal.contact_name || "Unknown"}
          </div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400 truncate">
            {signal.title} · {signal.company_name}
          </div>
        </div>
        {/* Engagement score */}
        <div className="flex-shrink-0">
          <div className="flex items-center gap-1">
            {Array.from({ length: 3 }).map((_, i) => (
              <Star
                key={i}
                className={cn(
                  "w-3 h-3",
                  i < Math.min(Math.ceil(signal.open_count / 2), 3)
                    ? "text-amber-400 fill-amber-400"
                    : "text-zinc-300 dark:text-zinc-700"
                )}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Signal pills */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {signal.open_count > 0 && (
          <div className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400">
            <Eye className="w-2.5 h-2.5" />
            {signal.open_count} opens
          </div>
        )}
        {signal.click_count > 0 && (
          <div className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-green-50 dark:bg-green-950/30 text-green-600 dark:text-green-400">
            <TrendingUp className="w-2.5 h-2.5" />
            {signal.click_count} clicks
          </div>
        )}
        {signal.signal_description && (
          <div className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-500">
            {signal.signal_description}
          </div>
        )}
        {signal.outreach_state && (
          <div className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/30 text-indigo-500">
            {signal.outreach_state}
          </div>
        )}
      </div>

      {/* Action */}
      {signal.company_id && (
        <div className="mt-3 pt-2 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <span className={cn("text-xs font-bold", getPQSColor(signal.pqs_total))}>
            PQS {signal.pqs_total}
          </span>
          <Link
            href={`/threads?contact=${signal.contact_id}`}
            className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            View thread <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
      )}
    </div>
  );
}

// ─── Summary Stats ─────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 flex items-center gap-3">
      <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center", color)}>
        {icon}
      </div>
      <div>
        <div className="text-xl font-bold text-zinc-900 dark:text-zinc-100">{value}</div>
        <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      </div>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [intentSignals, setIntentSignals] = useState<IntentSignal[]>([]);
  const [buyingSignals, setBuyingSignals] = useState<BuyingSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"intent" | "buying">("intent");
  const [intentFilter, setIntentFilter] = useState<"all" | "hot" | "warm">("all");
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const res = await getIntelligenceSignals();
      setIntentSignals(res.intent_signals || []);
      setBuyingSignals(res.buying_signals || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load signals");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const filteredIntent = intentSignals.filter((s) => {
    if (intentFilter === "hot") return s.intent_score >= 80;
    if (intentFilter === "warm") return s.intent_score >= 60 && s.intent_score < 80;
    return true;
  });

  const hotCount = intentSignals.filter((s) => s.intent_score >= 80).length;
  const warmCount = intentSignals.filter((s) => s.intent_score >= 60 && s.intent_score < 80).length;
  const avgIntent =
    intentSignals.length > 0
      ? Math.round(intentSignals.reduce((sum, s) => sum + s.intent_score, 0) / intentSignals.length)
      : 0;

  // ── Loading skeleton ──
  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 p-6">
        <div className="h-8 w-48 bg-zinc-200 dark:bg-zinc-800 rounded animate-pulse mb-6" />
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 bg-zinc-200 dark:bg-zinc-800 rounded-xl animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-40 bg-zinc-200 dark:bg-zinc-800 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error ──
  if (error) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-amber-500" />
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-4">{error}</p>
          <button
            onClick={() => loadData()}
            className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-sm text-white dark:text-zinc-900"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <div className="px-6 py-5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Signals</h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
              Intent signals and buying signals from your prospect universe
            </p>
          </div>
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", refreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary stats */}
      <div className="px-6 py-5 border-b border-zinc-200 dark:border-zinc-800">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            label="Hot Intent (≥80)"
            value={hotCount}
            icon={<Zap className="w-4 h-4 text-orange-600" />}
            color="bg-orange-50 dark:bg-orange-950/30"
          />
          <StatCard
            label="Warm Intent (≥60)"
            value={warmCount}
            icon={<TrendingUp className="w-4 h-4 text-amber-600" />}
            color="bg-amber-50 dark:bg-amber-950/30"
          />
          <StatCard
            label="Avg Intent Score"
            value={avgIntent}
            icon={<BarChart3 className="w-4 h-4 text-blue-600" />}
            color="bg-blue-50 dark:bg-blue-950/30"
          />
          <StatCard
            label="Buying Signals"
            value={buyingSignals.length}
            icon={<Mail className="w-4 h-4 text-purple-600" />}
            color="bg-purple-50 dark:bg-purple-950/30"
          />
        </div>
      </div>

      {/* Tabs */}
      <div className="px-6 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
        <div className="flex gap-1">
          {[
            { id: "intent", label: "Intent Signals", count: intentSignals.length, icon: <Zap className="w-3.5 h-3.5" /> },
            { id: "buying", label: "Buying Signals", count: buyingSignals.length, icon: <TrendingUp className="w-3.5 h-3.5" /> },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as "intent" | "buying")}
              className={cn(
                "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
                activeTab === tab.id
                  ? "border-zinc-900 dark:border-zinc-100 text-zinc-900 dark:text-zinc-100"
                  : "border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
              )}
            >
              {tab.icon}
              {tab.label}
              <span className={cn(
                "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                activeTab === tab.id
                  ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900"
                  : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500"
              )}>
                {tab.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="px-6 py-5">
        {/* Intent Signals */}
        {activeTab === "intent" && (
          <>
            {/* Filter bar */}
            <div className="flex items-center gap-2 mb-4">
              <span className="text-xs text-zinc-500 dark:text-zinc-400">Filter:</span>
              {(["all", "hot", "warm"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setIntentFilter(f)}
                  className={cn(
                    "px-3 py-1 rounded-full text-xs font-medium transition-colors",
                    intentFilter === f
                      ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900"
                      : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                  )}
                >
                  {f === "all" ? "All" : f === "hot" ? "Hot (≥80)" : "Warm (60-79)"}
                </button>
              ))}
              <span className="ml-auto text-xs text-zinc-400">{filteredIntent.length} companies</span>
            </div>

            {filteredIntent.length === 0 ? (
              <div className="text-center py-16">
                <Zap className="w-8 h-8 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  {intentSignals.length === 0
                    ? "No intent signals found. Signals appear when companies have an intent score above 0."
                    : "No companies match this filter."}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {filteredIntent.map((signal) => (
                  <IntentSignalCard key={signal.company_id} signal={signal} />
                ))}
              </div>
            )}
          </>
        )}

        {/* Buying Signals */}
        {activeTab === "buying" && (
          <>
            {buyingSignals.length === 0 ? (
              <div className="text-center py-16">
                <TrendingUp className="w-8 h-8 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  No buying signals yet. Signals appear when contacts open, click, or reply to your outreach.
                </p>
                <Link
                  href="/outreach"
                  className="mt-4 inline-flex items-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                >
                  <Mail className="w-4 h-4" />
                  Go to Outreach Hub
                </Link>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {buyingSignals.map((signal) => (
                  <BuyingSignalCard key={signal.contact_id} signal={signal} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
