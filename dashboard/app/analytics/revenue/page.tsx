"use client";

/**
 * Revenue Intelligence — Full-funnel analytics dashboard.
 *
 * Sections:
 *   1. KPI row (5 cards)
 *   2. Funnel visualization
 *   3. Cohort performance table
 *   4. Revenue attribution + Activity ROI
 *   5. Velocity trends
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  TrendingUp,
  Users,
  MessageSquare,
  DollarSign,
  RefreshCw,
  BarChart3,
  Zap,
  Clock,
  Target,
} from "lucide-react";
import {
  getFunnelData,
  getCohortAnalysis,
  getVelocityMetrics,
  getRevenueAttribution,
  getActivityROI,
  type FunnelData,
  type CohortAnalysis,
  type VelocityMetrics,
  type RevenueAttributionData,
  type ActivityROIData,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { FunnelChart } from "@/components/analytics/FunnelChart";
import { CohortTable } from "@/components/analytics/CohortTable";
import { RevenueProjection } from "@/components/analytics/RevenueProjection";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn("animate-pulse rounded bg-gray-100 dark:bg-gray-800", className)} style={style} />;
}

function formatCurrency(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${Math.round(v).toLocaleString()}`;
}

const PERIOD_OPTIONS = [
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
  { label: "180d", value: 180 },
];

const COHORT_TABS = [
  { label: "By Cluster", value: "cluster" },
  { label: "By Tranche", value: "tranche" },
  { label: "By Persona", value: "persona" },
  { label: "By Sequence", value: "sequence_name" },
];

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

interface KPICardProps {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ReactNode;
  borderColor: string;
  loading?: boolean;
}

function KPICard({ label, value, sub, icon, borderColor, loading }: KPICardProps) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-200 overflow-hidden">
      <div className={cn("h-1 w-full", borderColor)} />
      <div className="p-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="text-gray-400 dark:text-gray-500">{icon}</div>
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-500">{label}</p>
        </div>
        {loading ? (
          <>
            <Skeleton className="h-8 w-24 mb-1" />
            <Skeleton className="h-3 w-32" />
          </>
        ) : (
          <>
            <p className="text-3xl font-bold text-gray-900 dark:text-gray-100">{value}</p>
            {sub && <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{sub}</p>}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({
  title,
  icon,
  children,
  className,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm", className)}>
      <div className="flex items-center gap-2 border-b border-gray-100 dark:border-gray-800 px-5 py-3.5">
        {icon && <div className="text-gray-400">{icon}</div>}
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RevenueIntelligencePage() {
  const [period, setPeriod] = useState(90);
  const [cohortTab, setCohortTab] = useState("cluster");

  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [cohorts, setCohorts] = useState<CohortAnalysis | null>(null);
  const [velocity, setVelocity] = useState<VelocityMetrics | null>(null);
  const [revenue, setRevenue] = useState<RevenueAttributionData | null>(null);
  const [roi, setRoi] = useState<ActivityROIData | null>(null);

  const [loadingFunnel, setLoadingFunnel] = useState(true);
  const [loadingCohorts, setLoadingCohorts] = useState(true);
  const [loadingOther, setLoadingOther] = useState(true);

  const fetchFunnel = useCallback(async () => {
    setLoadingFunnel(true);
    try {
      const data = await getFunnelData(period);
      setFunnel(data);
    } catch { /* graceful */ }
    finally { setLoadingFunnel(false); }
  }, [period]);

  const fetchCohorts = useCallback(async () => {
    setLoadingCohorts(true);
    try {
      const data = await getCohortAnalysis(cohortTab, period);
      setCohorts(data);
    } catch { /* graceful */ }
    finally { setLoadingCohorts(false); }
  }, [cohortTab, period]);

  const fetchOther = useCallback(async () => {
    setLoadingOther(true);
    try {
      const [vel, rev, roiData] = await Promise.allSettled([
        getVelocityMetrics(),
        getRevenueAttribution(),
        getActivityROI(),
      ]);
      if (vel.status === "fulfilled") setVelocity(vel.value);
      if (rev.status === "fulfilled") setRevenue(rev.value);
      if (roiData.status === "fulfilled") setRoi(roiData.value);
    } catch { /* graceful */ }
    finally { setLoadingOther(false); }
  }, []);

  useEffect(() => { fetchFunnel(); }, [fetchFunnel]);
  useEffect(() => { fetchCohorts(); }, [fetchCohorts]);
  useEffect(() => { fetchOther(); }, [fetchOther]);

  const refresh = () => { fetchFunnel(); fetchCohorts(); fetchOther(); };

  // Derived KPIs
  const totalPipeline = funnel?.total_entered ?? 0;
  const totalContacted = funnel?.stages.find((s) => s.stage_key === "touch_1_sent")?.count ?? 0;
  const totalReplied = funnel?.stages.find((s) => s.stage_key === "replied")?.count ?? 0;
  const totalInterested = funnel?.stages.find((s) => s.stage_key === "demo_scheduled")?.count ?? 0;
  const projectedARR = revenue?.projected_arr_90d ?? 0;
  const loading = loadingFunnel && loadingOther;

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Revenue Intelligence</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Full-funnel analytics — discovery to booked revenue
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setPeriod(opt.value)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium transition-colors",
                  period === opt.value
                    ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900"
                    : "text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800",
                )}
                aria-pressed={period === opt.value}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            onClick={refresh}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 transition-colors"
            aria-label="Refresh analytics data"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Section 1: KPI Row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <KPICard
          label="Total Pipeline"
          value={totalPipeline.toLocaleString()}
          sub="companies discovered"
          icon={<Users className="h-4 w-4" />}
          borderColor="bg-blue-500"
          loading={loadingFunnel}
        />
        <KPICard
          label="Contacted"
          value={totalContacted.toLocaleString()}
          sub={totalPipeline > 0 ? `${((totalContacted / totalPipeline) * 100).toFixed(0)}% of pipeline` : "—"}
          icon={<MessageSquare className="h-4 w-4" />}
          borderColor="bg-blue-400"
          loading={loadingFunnel}
        />
        <KPICard
          label="Replied"
          value={totalReplied.toLocaleString()}
          sub={totalContacted > 0 ? `${((totalReplied / totalContacted) * 100).toFixed(1)}% reply rate` : "—"}
          icon={<TrendingUp className="h-4 w-4" />}
          borderColor="bg-green-500"
          loading={loadingFunnel}
        />
        <KPICard
          label="Interested"
          value={totalInterested.toLocaleString()}
          sub={totalReplied > 0 ? `${((totalInterested / totalReplied) * 100).toFixed(0)}% of replies` : "—"}
          icon={<Target className="h-4 w-4" />}
          borderColor="bg-green-400"
          loading={loadingFunnel}
        />
        <KPICard
          label="Projected ARR"
          value={formatCurrency(projectedARR)}
          sub="90-day estimate"
          icon={<DollarSign className="h-4 w-4" />}
          borderColor="bg-amber-500"
          loading={loadingOther}
        />
      </div>

      {/* Section 2: Funnel Visualization */}
      <Section title={`Pipeline Funnel (${period}d)`} icon={<BarChart3 className="h-4 w-4" />}>
        {loadingFunnel ? (
          <div className="space-y-2">
            {Array.from({ length: 7 }).map((_, i) => (
              <Skeleton key={i} className="h-10" style={{ width: `${100 - i * 8}%` }} />
            ))}
          </div>
        ) : funnel ? (
          <>
            <FunnelChart stages={funnel.stages} />
            <div className="mt-4 grid grid-cols-3 gap-4 border-t border-gray-100 dark:border-gray-800 pt-4">
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Total Entered</p>
                <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{funnel.total_entered.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Total Converted</p>
                <p className="text-lg font-bold text-green-600 dark:text-green-400">{funnel.total_converted.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Overall Conversion</p>
                <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{funnel.overall_conversion_rate.toFixed(1)}%</p>
              </div>
            </div>
          </>
        ) : (
          <p className="py-8 text-center text-sm text-gray-400">No funnel data available</p>
        )}
      </Section>

      {/* Section 3: Cohort Performance */}
      <Section title="Cohort Performance" icon={<Users className="h-4 w-4" />}>
        <div className="flex gap-1 mb-4 border-b border-gray-100 dark:border-gray-800 -mt-1 -mx-1 px-1">
          {COHORT_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setCohortTab(tab.value)}
              className={cn(
                "px-3 py-2 text-xs font-medium border-b-2 transition-colors",
                cohortTab === tab.value
                  ? "border-blue-500 text-blue-600 dark:text-blue-400"
                  : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100",
              )}
              aria-selected={cohortTab === tab.value}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {loadingCohorts ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
          </div>
        ) : cohorts ? (
          <CohortTable cohorts={cohorts.rows} groupBy={cohortTab} />
        ) : (
          <p className="py-8 text-center text-sm text-gray-400">No cohort data available</p>
        )}
      </Section>

      {/* Section 4: Revenue Attribution + Activity ROI */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section title="Revenue Attribution" icon={<DollarSign className="h-4 w-4" />}>
          {loadingOther ? (
            <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
          ) : revenue ? (
            <RevenueProjection attribution={revenue} />
          ) : (
            <p className="py-8 text-center text-sm text-gray-400">No revenue data available</p>
          )}
        </Section>

        <Section title="Activity ROI" icon={<Zap className="h-4 w-4" />}>
          {loadingOther ? (
            <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
          ) : roi ? (
            <div className="space-y-6">
              {/* By channel */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
                  Reply Rate by Channel
                </p>
                {roi.by_channel.length === 0 ? (
                  <p className="text-sm text-gray-400">No channel data yet</p>
                ) : (
                  <div className="space-y-2">
                    {roi.by_channel.map((ch) => (
                      <div key={ch.channel} className="flex items-center gap-3">
                        <span className="w-20 shrink-0 text-sm font-medium text-gray-700 dark:text-gray-300 capitalize">{ch.channel}</span>
                        <div className="flex-1 h-5 rounded bg-gray-100 dark:bg-gray-800 relative overflow-hidden">
                          <div
                            className="absolute inset-y-0 left-0 rounded bg-blue-200 dark:bg-blue-800 transition-all"
                            style={{ width: `${Math.min(ch.reply_rate_pct * 4, 100)}%` }}
                          />
                        </div>
                        <span className="w-12 shrink-0 text-right text-sm font-semibold text-gray-900 dark:text-gray-100">
                          {ch.reply_rate_pct.toFixed(1)}%
                        </span>
                        <span className="w-16 shrink-0 text-right text-xs text-gray-400">n={ch.total_sent}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Top sequences */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
                  Top Sequences by Reply Rate
                </p>
                {roi.by_sequence.length === 0 ? (
                  <p className="text-sm text-gray-400">No sequence data yet</p>
                ) : (
                  <div className="space-y-2">
                    {roi.by_sequence.slice(0, 5).map((seq, i) => (
                      <div key={seq.sequence_name} className="flex items-center gap-3">
                        <span className="w-5 shrink-0 text-xs font-bold text-gray-400">{i + 1}</span>
                        <span className="flex-1 text-sm text-gray-700 dark:text-gray-300 truncate" title={seq.sequence_name}>
                          {seq.sequence_name}
                        </span>
                        <span className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold",
                          seq.reply_rate_pct >= 5
                            ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300"
                            : seq.reply_rate_pct >= 2
                            ? "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300"
                            : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
                        )}>
                          {seq.reply_rate_pct.toFixed(1)}%
                        </span>
                        <span className="w-12 shrink-0 text-right text-xs text-gray-400">n={seq.total_sent}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-gray-400">No ROI data available</p>
          )}
        </Section>
      </div>

      {/* Section 5: Velocity Trends */}
      <Section title="Pipeline Velocity" icon={<Clock className="h-4 w-4" />}>
        {loadingOther ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
          </div>
        ) : velocity && velocity.stages.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {velocity.stages.map((stage) => {
              const trendInfo =
                stage.trend === "faster" ? { icon: "↓", color: "text-green-500" } :
                stage.trend === "slower" ? { icon: "↑", color: "text-red-500" } :
                stage.trend === "stable" ? { icon: "→", color: "text-gray-400" } :
                { icon: "—", color: "text-gray-300" };

              return (
                <div key={stage.stage_name} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4">
                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">{stage.stage_name}</p>
                  <div className="flex items-end gap-2">
                    <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                      {stage.avg_days.toFixed(1)}
                      <span className="text-sm font-normal text-gray-500 ml-1">days</span>
                    </p>
                    <span className={cn("text-lg font-bold mb-0.5", trendInfo.color)}>{trendInfo.icon}</span>
                  </div>
                  {stage.trend !== "no_data" && stage.trend_delta_days !== 0 && (
                    <p className={cn("text-xs mt-1", trendInfo.color)}>
                      {Math.abs(stage.trend_delta_days).toFixed(1)}d {stage.trend} vs last period
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-gray-400">No velocity data available</p>
        )}
      </Section>

      {/* Footer */}
      <div className="flex justify-between items-center text-xs text-gray-400 dark:text-gray-500">
        <Link href="/" className="hover:text-gray-700 dark:hover:text-gray-300">← Command Center</Link>
        <Link href="/analytics" className="hover:text-gray-700 dark:hover:text-gray-300">Analytics →</Link>
      </div>
    </div>
  );
}
