"use client";

import { useEffect, useState, useCallback } from "react";
import {
  BarChart3,
  DollarSign,
  Loader2,
  ArrowRight,
  Coins,
  FileInput,
  FileOutput,
  MailOpen,
  MessageSquareReply,
  ThumbsUp,
  CalendarCheck,
  TrendingUp,
} from "lucide-react";
import { getPipelineOverview, getCosts, StatusCount } from "@/lib/api";
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
  { key: "discovered", label: "Discovered", color: "bg-gray-400" },
  { key: "researched", label: "Researched", color: "bg-blue-500" },
  { key: "qualified", label: "Qualified", color: "bg-green-500" },
  { key: "contacted", label: "Contacted", color: "bg-indigo-500" },
  { key: "engaged", label: "Engaged", color: "bg-purple-500" },
  { key: "meeting_scheduled", label: "Meeting", color: "bg-pink-500" },
  { key: "pilot_discussion", label: "Pilot", color: "bg-orange-500" },
];

export default function AnalyticsPage() {
  const [pipeline, setPipeline] = useState<StatusCount[]>([]);
  const [costs, setCosts] = useState<CostData | null>(null);
  const [loadingPipeline, setLoadingPipeline] = useState(true);
  const [loadingCosts, setLoadingCosts] = useState(true);

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

  useEffect(() => {
    fetchPipeline();
    fetchCosts();
  }, [fetchPipeline, fetchCosts]);

  // Build funnel data from pipeline status counts
  const funnelData = FUNNEL_STAGES.map((stage) => {
    const match = pipeline.find((p) => p.status === stage.key);
    return { ...stage, count: match?.count ?? 0 };
  });
  const maxCount = Math.max(...funnelData.map((s) => s.count), 1);

  const costEntries: CostEntry[] = costs?.data ?? [];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Analytics</h2>
        <p className="mt-1 text-sm text-gray-500">
          Pipeline performance, costs, and outreach metrics
        </p>
      </div>

      {/* Section 1: Pipeline Funnel */}
      <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-6">
          <TrendingUp className="h-5 w-5 text-indigo-600" />
          <h3 className="text-lg font-semibold text-gray-900">
            Pipeline Funnel
          </h3>
        </div>

        {loadingPipeline ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
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
                      <span className="text-sm font-medium text-gray-700">
                        {stage.label}
                      </span>
                    </div>
                    <div className="relative flex-1 h-9 rounded-lg bg-gray-100">
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
                        <span className="text-xs text-gray-500">
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
      <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-6">
          <DollarSign className="h-5 w-5 text-green-600" />
          <h3 className="text-lg font-semibold text-gray-900">API Costs</h3>
        </div>

        {loadingCosts ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid gap-4 sm:grid-cols-3 mb-6">
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <Coins className="h-4 w-4" />
                  Total Cost
                </div>
                <p className="mt-2 text-2xl font-bold text-gray-900">
                  ${(costs?.total_cost ?? 0).toFixed(4)}
                </p>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <FileInput className="h-4 w-4" />
                  Input Tokens
                </div>
                <p className="mt-2 text-2xl font-bold text-gray-900">
                  {(costs?.total_input_tokens ?? 0).toLocaleString()}
                </p>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <FileOutput className="h-4 w-4" />
                  Output Tokens
                </div>
                <p className="mt-2 text-2xl font-bold text-gray-900">
                  {(costs?.total_output_tokens ?? 0).toLocaleString()}
                </p>
              </div>
            </div>

            {/* Cost Table */}
            {costEntries.length > 0 ? (
              <div className="overflow-x-auto rounded-lg border border-gray-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="px-4 py-3 text-left font-medium text-gray-600">
                        Provider
                      </th>
                      <th className="px-4 py-3 text-left font-medium text-gray-600">
                        Model
                      </th>
                      <th className="px-4 py-3 text-right font-medium text-gray-600">
                        Tokens
                      </th>
                      <th className="px-4 py-3 text-right font-medium text-gray-600">
                        Cost
                      </th>
                      <th className="px-4 py-3 text-right font-medium text-gray-600">
                        Date
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {costEntries.map((entry, idx) => (
                      <tr
                        key={idx}
                        className="hover:bg-gray-50 transition-colors"
                      >
                        <td className="px-4 py-3 text-gray-900">
                          {entry.provider ?? "-"}
                        </td>
                        <td className="px-4 py-3">
                          <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">
                            {entry.model ?? "-"}
                          </code>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {(
                            (entry.input_tokens ?? 0) +
                            (entry.output_tokens ?? 0)
                          ).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right font-medium text-gray-900">
                          ${(entry.cost ?? 0).toFixed(4)}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-500">
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
              <p className="text-center text-sm text-gray-400 py-4">
                No cost data recorded yet.
              </p>
            )}
          </>
        )}
      </section>

      {/* Section 3: Performance Metrics */}
      <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-6">
          <BarChart3 className="h-5 w-5 text-purple-600" />
          <h3 className="text-lg font-semibold text-gray-900">
            Performance Metrics
          </h3>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              label: "Open Rate",
              value: "--",
              icon: MailOpen,
              color: "text-blue-600",
              bg: "bg-blue-50",
            },
            {
              label: "Reply Rate",
              value: "--",
              icon: MessageSquareReply,
              color: "text-green-600",
              bg: "bg-green-50",
            },
            {
              label: "Positive Reply Rate",
              value: "--",
              icon: ThumbsUp,
              color: "text-purple-600",
              bg: "bg-purple-50",
            },
            {
              label: "Meetings Booked",
              value: "--",
              icon: CalendarCheck,
              color: "text-orange-600",
              bg: "bg-orange-50",
            },
          ].map((metric) => {
            const Icon = metric.icon;
            return (
              <div
                key={metric.label}
                className="rounded-lg border border-gray-100 bg-white p-5"
              >
                <div
                  className={cn(
                    "inline-flex rounded-lg p-2",
                    metric.bg
                  )}
                >
                  <Icon className={cn("h-5 w-5", metric.color)} />
                </div>
                <p className="mt-3 text-2xl font-bold text-gray-900">
                  {metric.value}
                </p>
                <p className="mt-0.5 text-sm text-gray-500">{metric.label}</p>
              </div>
            );
          })}
        </div>

        <p className="mt-4 text-center text-xs text-gray-400">
          Data will populate as outreach progresses
        </p>
      </section>
    </div>
  );
}
