"use client";

/**
 * Analytics Dashboard — Pipeline funnel metrics, PQS distribution, and API costs
 *
 * Expected actions:
 * Monitor conversion rates at each stage, identify bottlenecks, track cost per qualified prospect
 */


import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  BarChart3,
  Copy,
  DollarSign,
  Loader2,
  ArrowRight,
  Coins,
  FileInput,
  FileOutput,
  MailOpen,
  MessageSquareReply,
  ShieldAlert,
  ThumbsUp,
  CalendarCheck,
  TrendingUp,
  Trophy,
  XCircle,
  Clock,
} from "lucide-react";
import {
  getPipelineOverview,
  getCosts,
  getDuplicates,
  getCompetitiveRisks,
  getPipelineVelocity,
  StatusCount,
  DuplicateGroup,
  CompetitiveRisk,
  type PipelineVelocityStage,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

interface CostEntry {
  provider?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost?: number;
  created_at?: string;
}

interface CostData {
  data?: CostEntry[];
  total_cost?: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
}

const FUNNEL_STAGES = [
  { key: "discovered", label: "Discovered", color: "bg-gray-300" },
  { key: "researched", label: "Researched", color: "bg-gray-400" },
  { key: "qualified", label: "Qualified", color: "bg-gray-50 dark:bg-gray-8000" },
  { key: "contacted", label: "Contacted", color: "bg-gray-600" },
  { key: "engaged", label: "Engaged", color: "bg-gray-700" },
  { key: "meeting_scheduled", label: "Meeting", color: "bg-gray-800" },
  { key: "pilot_discussion", label: "Pilot", color: "bg-gray-900" },
];

export default function AnalyticsPage() {
  const [pipeline, setPipeline] = useState<StatusCount[]>([]);
  const [costs, setCosts] = useState<CostData | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateGroup[]>([]);
  const [risks, setRisks] = useState<CompetitiveRisk[]>([]);
  const [velocity, setVelocity] = useState<Record<string, PipelineVelocityStage>>({});
  const [loadingPipeline, setLoadingPipeline] = useState(true);
  const [loadingCosts, setLoadingCosts] = useState(true);
  const [loadingDuplicates, setLoadingDuplicates] = useState(true);
  const [loadingRisks, setLoadingRisks] = useState(true);
  const [loadingVelocity, setLoadingVelocity] = useState(true);

  const fetchPipeline = useCallback(async () => {
    try {
      const res = await getPipelineOverview();
      setPipeline(res.data);
    } catch {
      // Leave empty
    } finally {
      setLoadingPipeline(false);
    }
  }, []);

  const fetchCosts = useCallback(async () => {
    try {
      const res = await getCosts();
      setCosts(res as CostData);
    } catch {
      // Leave empty
    } finally {
      setLoadingCosts(false);
    }
  }, []);

  const fetchDuplicates = useCallback(async () => {
    try {
      const res = await getDuplicates();
      setDuplicates(res.data);
    } catch {
      // Leave empty
    } finally {
      setLoadingDuplicates(false);
    }
  }, []);

  const fetchRisks = useCallback(async () => {
    try {
      const res = await getCompetitiveRisks();
      setRisks(res.data);
    } catch {
      // Leave empty
    } finally {
      setLoadingRisks(false);
    }
  }, []);

  const fetchVelocity = useCallback(async () => {
    try {
      const res = await getPipelineVelocity();
      setVelocity(res.data);
    } catch {
      // Leave empty
    } finally {
      setLoadingVelocity(false);
    }
  }, []);

  useEffect(() => {
    fetchPipeline();
    fetchCosts();
    fetchDuplicates();
    fetchRisks();
    fetchVelocity();
  }, [fetchPipeline, fetchCosts, fetchDuplicates, fetchRisks, fetchVelocity]);

  // Build funnel data from pipeline status counts
  const funnelData = FUNNEL_STAGES.map((stage) => {
    const match = pipeline.find((p) => p.status === stage.key);
    return { ...stage, count: match?.count ?? 0 };
  });
  const maxCount = Math.max(...funnelData.map((s) => s.count), 1);

  // Compute performance metrics from pipeline data
  const contacted = pipeline.find((p) => p.status === "contacted")?.count ?? 0;
  const engaged = pipeline.find((p) => p.status === "engaged")?.count ?? 0;
  const meetings = pipeline.find((p) => p.status === "meeting_scheduled")?.count ?? 0;
  const pilots = pipeline.find((p) => p.status === "pilot_discussion")?.count ?? 0;
  const pilotSigned = pipeline.find((p) => p.status === "pilot_signed")?.count ?? 0;
  const disqualified = pipeline.find((p) => p.status === "disqualified")?.count ?? 0;
  const totalProspects = pipeline.reduce((sum, p) => sum + (p.count ?? 0), 0);
  const converted = meetings + pilots + pilotSigned;

  const replyRate = contacted > 0 ? `${Math.round((engaged / contacted) * 100)}%` : "0%";
  const positiveRate = engaged > 0 ? `${Math.round((meetings / engaged) * 100)}%` : "0%";
  const meetingsBooked = meetings + pilots;
  const conversionRate = totalProspects > 0 ? `${Math.round((converted / totalProspects) * 100)}%` : "0%";

  const costEntries: CostEntry[] = costs?.data ?? [];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Analytics</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">
          Pipeline performance, costs, and outreach metrics
        </p>
      </div>

      {/* Section 1: Pipeline Funnel */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 mb-6">
          <TrendingUp className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
            Pipeline Funnel
          </h3>
        </div>

        {loadingPipeline ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : (
          <div className="space-y-3">
            {funnelData.map((stage, idx) => {
              const prev = idx > 0 ? funnelData[idx - 1].count : null;
              const pct =
                prev !== null && prev > 0
                  ? Math.round((stage.count / prev) * 100)
                  : null;
              const barWidth = Math.max(
                (stage.count / maxCount) * 100,
                stage.count > 0 ? 4 : 0
              );

              return (
                <div key={stage.key}>
                  {/* Arrow between stages */}
                  {idx > 0 && (
                    <div className="flex items-center justify-center py-1">
                      <ArrowRight className="h-3.5 w-3.5 text-gray-300 rotate-90" />
                    </div>
                  )}
                  <div className="flex items-center gap-4">
                    <div className="w-28 shrink-0 text-right">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        {stage.label}
                      </span>
                    </div>
                    <div className="relative flex-1 h-9 rounded-lg bg-gray-100 dark:bg-gray-800">
                      <div
                        className={cn(
                          "h-full rounded-lg transition-all duration-500",
                          stage.color
                        )}
                        style={{ width: `${barWidth}%` }}
                      />
                      <div className="absolute inset-0 flex items-center px-3">
                        <span className="text-sm font-semibold text-white mix-blend-difference">
                          {stage.count}
                        </span>
                      </div>
                    </div>
                    <div className="w-16 shrink-0">
                      {pct !== null ? (
                        <span className="text-xs text-gray-500 dark:text-gray-500">
                          {pct}%
                        </span>
                      ) : (
                        <span className="text-xs text-gray-300">&mdash;</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Section 2: API Costs */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 mb-6">
          <DollarSign className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">API Costs</h3>
        </div>

        {loadingCosts ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid gap-4 sm:grid-cols-3 mb-6">
              <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 p-4">
                <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-500">
                  <Coins className="h-4 w-4" />
                  Total Cost
                </div>
                <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-100">
                  ${(costs?.total_cost ?? 0).toFixed(4)}
                </p>
              </div>
              <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 p-4">
                <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-500">
                  <FileInput className="h-4 w-4" />
                  Input Tokens
                </div>
                <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-100">
                  {(costs?.total_input_tokens ?? 0).toLocaleString()}
                </p>
              </div>
              <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 p-4">
                <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-500">
                  <FileOutput className="h-4 w-4" />
                  Output Tokens
                </div>
                <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-100">
                  {(costs?.total_output_tokens ?? 0).toLocaleString()}
                </p>
              </div>
            </div>

            {/* Cost Table */}
            {costEntries.length > 0 ? (
              <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                      <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
                        Provider
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
                        Model
                      </th>
                      <th className="px-4 py-3 text-right text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
                        Tokens
                      </th>
                      <th className="px-4 py-3 text-right text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
                        Cost
                      </th>
                      <th className="px-4 py-3 text-right text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
                        Date
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {costEntries.map((entry, idx) => (
                      <tr
                        key={idx}
                        className="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                      >
                        <td className="px-4 py-3 text-gray-900 dark:text-gray-100">
                          {entry.provider ?? "-"}
                        </td>
                        <td className="px-4 py-3">
                          <code className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs text-gray-700 dark:text-gray-300">
                            {entry.model ?? "-"}
                          </code>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600 dark:text-gray-500">
                          {(
                            (entry.input_tokens ?? 0) +
                            (entry.output_tokens ?? 0)
                          ).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right font-medium text-gray-900 dark:text-gray-100">
                          ${(entry.cost ?? 0).toFixed(4)}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-500 dark:text-gray-500">
                          {entry.created_at
                            ? formatDate(entry.created_at)
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-center text-sm text-gray-400 dark:text-gray-500 py-4">
                No cost data recorded yet.
              </p>
            )}
          </>
        )}
      </section>

      {/* Section 3: Duplicate Detection */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 mb-6">
          <Copy className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Potential Duplicates</h3>
          <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
            {duplicates.length} groups
          </span>
        </div>

        {loadingDuplicates ? (
          <div className="flex h-24 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : duplicates.length === 0 ? (
          <p className="text-center text-sm text-gray-400 dark:text-gray-500 py-4">
            No duplicate domains detected.
          </p>
        ) : (
          <div className="space-y-3">
            {duplicates.map((group) => (
              <div
                key={group.key}
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4"
              >
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Domain: <code className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs">{group.key}</code>
                  {" "}— {group.companies.length} companies
                </p>
                <div className="space-y-1">
                  {group.companies.map((c) => (
                    <div key={c.id} className="flex items-center gap-3 text-sm">
                      <Link
                        href={`/prospects/${c.id}`}
                        className="font-medium text-gray-900 dark:text-gray-100 hover:underline"
                      >
                        {c.name}
                      </Link>
                      <span className="text-gray-400 dark:text-gray-500">tier: {c.tier || "—"}</span>
                      <span className="text-gray-400 dark:text-gray-500">status: {c.status}</span>
                      <span className="text-gray-400 dark:text-gray-500">PQS: {c.pqs_total}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Section 4: Competitive Intelligence */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 mb-2">
          <ShieldAlert className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Competitive Intelligence</h3>
          <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
            {risks.length} companies
          </span>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-500 mb-6">
          These companies already use AI/ML platforms — adjust your pitch to displace or complement existing solutions.
        </p>

        {loadingRisks ? (
          <div className="flex h-24 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : risks.length === 0 ? (
          <p className="text-center text-sm text-gray-400 dark:text-gray-500 py-4">
            No competitive risks found in researched companies.
          </p>
        ) : (
          <div className="divide-y divide-gray-100">
            {risks.map((risk) => (
              <div
                key={risk.company_id}
                className="flex items-center justify-between py-3"
              >
                <div className="flex items-center gap-3">
                  <Link
                    href={`/prospects/${risk.company_id}`}
                    className="text-sm font-medium text-gray-900 dark:text-gray-100 hover:underline"
                  >
                    {risk.company?.name ?? risk.company_id}
                  </Link>
                  {risk.company?.tier && (
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      Tier {risk.company.tier}
                    </span>
                  )}
                  {risk.company?.pqs_total !== undefined && (
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      PQS {risk.company.pqs_total}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap gap-1">
                  {risk.existing_solutions.map((s) => (
                    <span
                      key={s}
                      className="rounded bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Section 4b: Pipeline Value Summary */}
      {!loadingPipeline && (
        <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="h-4 w-4 text-gray-400 dark:text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Pipeline Value</h3>
            <Link
              href="/analytics/win-loss"
              className="ml-auto flex items-center gap-1 text-xs font-medium text-gray-600 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 hover:underline"
            >
              Win/Loss Analysis
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-500">
            To track total pipeline value, assign deal values to companies on their detail pages. Use the Win/Loss Analysis to see patterns in outcomes.
          </p>
        </section>
      )}

      {/* Section 5: Performance Metrics */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 mb-6">
          <BarChart3 className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
            Performance Metrics
          </h3>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              label: "Open Rate",
              value: "--",
              subtext: "Tracking via Instantly",
              icon: MailOpen,
            },
            {
              label: "Reply Rate",
              value: replyRate,
              subtext: `${engaged} engaged / ${contacted} contacted`,
              icon: MessageSquareReply,
            },
            {
              label: "Positive Reply Rate",
              value: positiveRate,
              subtext: `${meetings} meetings / ${engaged} engaged`,
              icon: ThumbsUp,
            },
            {
              label: "Meetings Booked",
              value: String(meetingsBooked),
              subtext: `${meetings} scheduled + ${pilots} in pilot`,
              icon: CalendarCheck,
            },
            {
              label: "Disqualified",
              value: String(disqualified),
              subtext: "Removed from pipeline",
              icon: BarChart3,
            },
            {
              label: "Conversion Rate",
              value: conversionRate,
              subtext: `${converted} converted / ${totalProspects} total`,
              icon: TrendingUp,
            },
          ].map((metric) => {
            const Icon = metric.icon;
            return (
              <div
                key={metric.label}
                className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 p-5"
              >
                <div className="inline-flex rounded-md p-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700">
                  <Icon className="h-4 w-4 text-gray-400 dark:text-gray-500" />
                </div>
                <p className="mt-3 text-2xl font-semibold text-gray-900 dark:text-gray-100">
                  {metric.value}
                </p>
                <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-500">{metric.label}</p>
                {metric.subtext && (
                  <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">{metric.subtext}</p>
                )}
              </div>
            );
          })}
        </div>

        <p className="mt-4 text-center text-xs text-gray-400 dark:text-gray-500">
          Reply and meeting rates computed from pipeline data. Open rate requires Instantly integration.
        </p>
      </section>

      {/* Pipeline Velocity */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 mb-2">
          <Clock className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Pipeline Velocity</h3>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-500 mb-6">Average days companies spend in each stage</p>

        {loadingVelocity ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : Object.keys(velocity).length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">No velocity data yet.</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(velocity)
              .sort((a, b) => b[1].avg_days - a[1].avg_days)
              .map(([status, stats]) => {
                const maxAvg = Math.max(...Object.values(velocity).map((v) => v.avg_days), 1);
                const barWidth = Math.max((stats.avg_days / maxAvg) * 100, 4);
                return (
                  <div key={status} className="flex items-center gap-4">
                    <div className="w-36 shrink-0 text-right">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300 capitalize">
                        {status.replace(/_/g, " ")}
                      </span>
                    </div>
                    <div className="relative flex-1 h-8 rounded-lg bg-gray-100 dark:bg-gray-800">
                      <div
                        className="h-full rounded-lg bg-gray-600 transition-all duration-500"
                        style={{ width: `${barWidth}%` }}
                      />
                      <div className="absolute inset-0 flex items-center px-3">
                        <span className="text-xs font-semibold text-white mix-blend-difference">
                          {stats.avg_days}d avg
                        </span>
                      </div>
                    </div>
                    <div className="w-32 shrink-0 text-xs text-gray-400 dark:text-gray-500">
                      {stats.min_days}–{stats.max_days}d range · {stats.count} co.
                    </div>
                  </div>
                );
              })}
          </div>
        )}
      </section>
    </div>
  );
}
