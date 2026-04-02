"use client";

/**
 * Signal Monitor — Buying signals and hot prospects dashboard.
 *
 * Tab 1: Hot Prospects — companies ranked by composite signal score
 * Tab 2: Signal Feed  — chronological feed with filters
 */

import { useCallback, useEffect, useState } from "react";
import {
  Zap,
  RefreshCw,
  Loader2,
  AlertTriangle,
  CheckCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  getSignals,
  getHotProspects,
  getSignalStats,
  scanBatchSignals,
  markSignalRead,
  markSignalActioned,
  CompanySignal,
  SignalSummary,
  SignalStats,
  BatchScanResult,
} from "@/lib/api";
import { cn, formatTimeAgo } from "@/lib/utils";
import { SignalStats as SignalStatsBar } from "@/components/signals/SignalStats";
import { HotProspectCard } from "@/components/signals/HotProspectCard";
import { SignalCard } from "@/components/signals/SignalCard";

// ─── Signal type options for filter ───────────────────────────────────────────

const SIGNAL_TYPES = [
  { value: "job_posting",       label: "Hiring" },
  { value: "funding",           label: "Funding" },
  { value: "tech_change",       label: "Tech Change" },
  { value: "news_mention",      label: "News" },
  { value: "leadership_change", label: "Leadership" },
  { value: "expansion",         label: "Expansion" },
  { value: "pain_signal",       label: "Pain Signal" },
  { value: "regulatory",        label: "Regulatory" },
  { value: "partnership",       label: "Partnership" },
];

const URGENCY_FILTERS = [
  { value: "",           label: "All urgency" },
  { value: "immediate",  label: "Immediate" },
  { value: "near_term",  label: "Near-term" },
  { value: "background", label: "Background" },
];

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="h-56 bg-gray-200 dark:bg-gray-800 rounded-lg animate-pulse" />
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState({ message, action }: { message: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <Zap className="w-10 h-10 text-gray-300 dark:text-gray-700 mb-3" />
      <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs mb-4">{message}</p>
      {action}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function SignalMonitorPage() {
  const [activeTab, setActiveTab] = useState<"hot" | "feed">("hot");

  // Hot prospects state
  const [hotProspects, setHotProspects] = useState<SignalSummary[]>([]);
  const [hotLoading, setHotLoading] = useState(true);

  // Signal feed state
  const [signals, setSignals] = useState<CompanySignal[]>([]);
  const [feedLoading, setFeedLoading] = useState(false);
  const [feedLoaded, setFeedLoaded] = useState(false);

  // Stats state
  const [stats, setStats] = useState<SignalStats | null>(null);

  // Scan state
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<BatchScanResult | null>(null);
  const [lastScanAt, setLastScanAt] = useState<Date | null>(null);

  // Feed filters
  const [urgencyFilter, setUrgencyFilter] = useState("");
  const [typeFilters, setTypeFilters] = useState<string[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);

  // ── Error state ──
  const [error, setError] = useState<string | null>(null);

  // ── Load hot prospects + stats ────────────────────────────────────────────

  const loadHotProspects = useCallback(async () => {
    setHotLoading(true);
    setError(null);
    try {
      const [hotRes, statsRes] = await Promise.all([
        getHotProspects(30),
        getSignalStats(),
      ]);
      setHotProspects(hotRes.data ?? []);
      setStats(statsRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load signals");
    } finally {
      setHotLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHotProspects();
  }, [loadHotProspects]);

  // ── Load signal feed (lazy — on tab switch) ───────────────────────────────

  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    try {
      const params: Record<string, string> = { limit: "100" };
      if (urgencyFilter) params.urgency = urgencyFilter;
      if (typeFilters.length === 1) params.signal_type = typeFilters[0];
      if (unreadOnly) params.is_read = "false";
      const res = await getSignals(params);
      setSignals(res.data ?? []);
      setFeedLoaded(true);
    } catch {
      // Non-fatal
    } finally {
      setFeedLoading(false);
    }
  }, [urgencyFilter, typeFilters, unreadOnly]);

  useEffect(() => {
    if (activeTab === "feed") {
      loadFeed();
    }
  }, [activeTab, loadFeed]);

  // ── Scan now ──────────────────────────────────────────────────────────────

  const handleScanNow = async () => {
    setScanning(true);
    setScanResult(null);
    try {
      const result = await scanBatchSignals(50);
      setScanResult(result);
      setLastScanAt(new Date());
      // Reload hot prospects after scan
      await loadHotProspects();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  // ── Signal actions ────────────────────────────────────────────────────────

  const handleRead = useCallback(async (signalId: string) => {
    try {
      await markSignalRead(signalId);
      // Update local state
      setSignals((prev) =>
        prev.map((s) => (s.id === signalId ? { ...s, is_read: true } : s))
      );
      setHotProspects((prev) =>
        prev.map((hp) => ({
          ...hp,
          signals: hp.signals.map((s) => (s.id === signalId ? { ...s, is_read: true } : s)),
          unread_signals: hp.signals.filter((s) => !s.is_read && s.id !== signalId).length,
        }))
      );
      setStats((prev) =>
        prev ? { ...prev, total_unread: Math.max(0, prev.total_unread - 1) } : prev
      );
    } catch {
      // Non-fatal
    }
  }, []);

  const handleAction = useCallback(async (signalId: string) => {
    try {
      await markSignalActioned(signalId);
      setSignals((prev) => prev.filter((s) => s.id !== signalId));
      setHotProspects((prev) =>
        prev
          .map((hp) => ({
            ...hp,
            signals: hp.signals.filter((s) => s.id !== signalId),
            total_signals: hp.signals.filter((s) => s.id !== signalId).length,
          }))
          .filter((hp) => hp.total_signals > 0)
      );
    } catch {
      // Non-fatal
    }
  }, []);

  const handleMarkAllRead = async () => {
    const unread = signals.filter((s) => !s.is_read);
    for (const s of unread) {
      await handleRead(s.id);
    }
  };

  const toggleTypeFilter = (type: string) => {
    setTypeFilters((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
    );
  };

  const filteredFeed = signals.filter((s) => {
    if (typeFilters.length > 0 && !typeFilters.includes(s.signal_type)) return false;
    return true;
  });

  // ── Error screen ──────────────────────────────────────────────────────────

  if (error && hotLoading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-amber-500" />
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">{error}</p>
          <button
            onClick={() => { setError(null); loadHotProspects(); }}
            className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">

      {/* ── Header ── */}
      <div className="px-6 py-5 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
              Signal Monitor
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              Buying signals across your prospect universe
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Last scan timestamp */}
            {lastScanAt && (
              <span className="text-xs text-gray-400 dark:text-gray-500">
                Scanned {formatTimeAgo(lastScanAt.toISOString())}
              </span>
            )}
            {/* Scan result pill */}
            {scanResult && (
              <span className="text-xs px-2 py-1 rounded-full bg-green-100 dark:bg-green-950/40 text-green-700 dark:text-green-400">
                +{scanResult.signals_created} new
              </span>
            )}
            {/* Scan Now button */}
            <button
              onClick={handleScanNow}
              disabled={scanning}
              className="flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-60 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
              aria-label="Run signal scan"
            >
              {scanning ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              {scanning ? "Scanning…" : "Scan Now"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Stats bar ── */}
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <SignalStatsBar stats={stats ?? undefined} />
      </div>

      {/* ── Tabs ── */}
      <div className="px-6 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="flex gap-0">
          {[
            { id: "hot",  label: "Hot Prospects",  count: hotProspects.length },
            { id: "feed", label: "Signal Feed",    count: stats?.total_unread ?? 0 },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as "hot" | "feed")}
              className={cn(
                "flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset",
                activeTab === tab.id
                  ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
                  : "border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              )}
            >
              {tab.label}
              {tab.count > 0 && (
                <span
                  className={cn(
                    "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                    activeTab === tab.id
                      ? "bg-blue-600 text-white dark:bg-blue-500"
                      : "bg-gray-100 dark:bg-gray-800 text-gray-500"
                  )}
                >
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Content ── */}
      <div className="px-6 py-6">

        {/* ─── Hot Prospects Tab ─── */}
        {activeTab === "hot" && (
          <>
            {hotLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <CardSkeleton key={i} />
                ))}
              </div>
            ) : hotProspects.length === 0 ? (
              <EmptyState
                message="No hot prospects yet. Run a scan to detect buying signals across your prospect database."
                action={
                  <button
                    onClick={handleScanNow}
                    disabled={scanning}
                    className="flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-60"
                  >
                    {scanning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
                    {scanning ? "Scanning…" : "Run First Scan"}
                  </button>
                }
              />
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {hotProspects.map((summary) => (
                  <HotProspectCard
                    key={summary.company_id}
                    summary={summary}
                    onViewSignals={(id) => window.location.href = `/companies/${id}`}
                    onGenerateDraft={(id) => window.location.href = `/outreach?company=${id}`}
                    onSignalRead={handleRead}
                    onSignalAction={handleAction}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* ─── Signal Feed Tab ─── */}
        {activeTab === "feed" && (
          <>
            {/* Filter bar */}
            <div className="flex items-center gap-3 mb-5 flex-wrap">
              {/* Urgency filter */}
              <select
                value={urgencyFilter}
                onChange={(e) => setUrgencyFilter(e.target.value)}
                className="text-xs rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Filter by urgency"
              >
                {URGENCY_FILTERS.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>

              {/* Signal type chips */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <SlidersHorizontal className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                {SIGNAL_TYPES.map((t) => (
                  <button
                    key={t.value}
                    onClick={() => toggleTypeFilter(t.value)}
                    className={cn(
                      "text-[10px] px-2 py-1 rounded-full border transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500",
                      typeFilters.includes(t.value)
                        ? "bg-blue-600 text-white border-blue-600"
                        : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-gray-400"
                    )}
                  >
                    {t.label}
                  </button>
                ))}
                {typeFilters.length > 0 && (
                  <button
                    onClick={() => setTypeFilters([])}
                    className="text-[10px] text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-0.5"
                  >
                    <X className="w-3 h-3" />
                    Clear
                  </button>
                )}
              </div>

              {/* Unread toggle */}
              <button
                onClick={() => setUnreadOnly((v) => !v)}
                className={cn(
                  "text-[10px] px-2 py-1 rounded-full border transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500",
                  unreadOnly
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700"
                )}
              >
                Unread only
              </button>

              {/* Spacer */}
              <div className="flex-1" />

              {/* Mark all read */}
              {filteredFeed.some((s) => !s.is_read) && (
                <button
                  onClick={handleMarkAllRead}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500 rounded"
                  aria-label="Mark all signals as read"
                >
                  <CheckCheck className="w-3.5 h-3.5" />
                  Mark all read
                </button>
              )}

              <span className="text-xs text-gray-400 dark:text-gray-500">
                {filteredFeed.length} signal{filteredFeed.length !== 1 ? "s" : ""}
              </span>
            </div>

            {/* Feed */}
            {feedLoading ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-24 bg-gray-200 dark:bg-gray-800 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : !feedLoaded ? null : filteredFeed.length === 0 ? (
              <EmptyState message="No signals match the current filters. Try adjusting the urgency or type filter." />
            ) : (
              <div className="flex flex-col gap-3">
                {filteredFeed.map((signal) => (
                  <SignalCard
                    key={signal.id}
                    signal={signal}
                    showCompany
                    onRead={handleRead}
                    onAction={handleAction}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
