"use client";

/**
 * Pipeline Run History — Log of all agent executions with results and costs
 *
 * Expected actions:
 * Review past discovery/research/qualification runs, check error rates, monitor API spend
 */


import { useEffect, useState, useCallback } from "react";
import {
  History,
  DollarSign,
  Loader2,
  Search,
  Building2,
  Phone,
  ClipboardCheck,
  Mail,
  Users,
  HelpCircle,
} from "lucide-react";
import { getAgentRuns, AgentRun } from "@/lib/api";
import { cn, formatDate, formatTimeAgo } from "@/lib/utils";

// ---------------------------------------------------------------
// Agent display config
// ---------------------------------------------------------------

const AGENT_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; dot: string; icon: React.ComponentType<{ className?: string }> }
> = {
  discovery: {
    label: "Discovery",
    color: "text-slate-700",
    bg: "bg-slate-100",
    dot: "bg-slate-500",
    icon: Search,
  },
  research: {
    label: "Research",
    color: "text-blue-700",
    bg: "bg-blue-100",
    dot: "bg-blue-500",
    icon: Building2,
  },
  qualification: {
    label: "Qualification",
    color: "text-green-700",
    bg: "bg-green-100",
    dot: "bg-green-500",
    icon: ClipboardCheck,
  },
  outreach: {
    label: "Outreach",
    color: "text-purple-700",
    bg: "bg-purple-100",
    dot: "bg-purple-500",
    icon: Mail,
  },
  engagement: {
    label: "Engagement",
    color: "text-pink-700",
    bg: "bg-pink-100",
    dot: "bg-pink-500",
    icon: Users,
  },
  anthropic: {
    label: "Anthropic",
    color: "text-indigo-700",
    bg: "bg-indigo-100",
    dot: "bg-indigo-400",
    icon: Phone,
  },
};

const DEFAULT_CONFIG = {
  label: "Agent",
  color: "text-gray-700",
  bg: "bg-gray-100",
  dot: "bg-gray-400",
  icon: HelpCircle,
};

function agentConfig(agent: string) {
  return AGENT_CONFIG[agent.toLowerCase()] ?? DEFAULT_CONFIG;
}

// ---------------------------------------------------------------
// AgentBadge
// ---------------------------------------------------------------

function AgentBadge({ agent }: { agent: string }) {
  const cfg = agentConfig(agent);
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
        cfg.bg,
        cfg.color
      )}
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------
// Page
// ---------------------------------------------------------------

export default function HistoryPage() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [totals, setTotals] = useState<{ runs: number; cost_usd: number }>({
    runs: 0,
    cost_usd: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getAgentRuns();
      setRuns(res.data ?? []);
      setTotals(res.totals ?? { runs: 0, cost_usd: 0 });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Distinct agent types for filter tabs
  const agentTypes = Array.from(new Set(runs.map((r) => r.agent.toLowerCase()))).sort();

  const filteredRuns =
    filter === "all" ? runs : runs.filter((r) => r.agent.toLowerCase() === filter);

  const totalCompanies = runs.reduce((s, r) => s + r.companies_processed, 0);
  const totalCalls = runs.reduce((s, r) => s + r.total_calls, 0);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Agent Run History</h2>
        <p className="mt-1 text-sm text-gray-500">
          Past agent executions grouped by batch — cost, companies processed, and API calls
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            label: "Total Runs",
            value: totals.runs.toLocaleString(),
            icon: History,
            iconColor: "text-digitillis-accent",
            iconBg: "bg-blue-50",
          },
          {
            label: "Total Cost",
            value: `$${totals.cost_usd.toFixed(4)}`,
            icon: DollarSign,
            iconColor: "text-digitillis-success",
            iconBg: "bg-green-50",
          },
          {
            label: "Companies Processed",
            value: totalCompanies.toLocaleString(),
            icon: Building2,
            iconColor: "text-purple-600",
            iconBg: "bg-purple-50",
          },
          {
            label: "API Calls Made",
            value: totalCalls.toLocaleString(),
            icon: Phone,
            iconColor: "text-amber-600",
            iconBg: "bg-amber-50",
          },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
            >
              <div className={cn("inline-flex rounded-lg p-2", card.iconBg)}>
                <Icon className={cn("h-5 w-5", card.iconColor)} />
              </div>
              <p className="mt-3 text-2xl font-bold text-gray-900">{card.value}</p>
              <p className="mt-0.5 text-sm text-gray-500">{card.label}</p>
            </div>
          );
        })}
      </div>

      {/* Runs Table */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        {/* Table header + filter tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <History className="h-5 w-5 text-digitillis-accent" />
            <h3 className="text-lg font-semibold text-gray-900">Run Log</h3>
          </div>

          {/* Agent filter tabs */}
          {!loading && agentTypes.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setFilter("all")}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                  filter === "all"
                    ? "bg-digitillis-accent text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                )}
              >
                All
              </button>
              {agentTypes.map((agent) => {
                const cfg = agentConfig(agent);
                return (
                  <button
                    key={agent}
                    onClick={() => setFilter(agent)}
                    className={cn(
                      "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                      filter === agent
                        ? `${cfg.bg} ${cfg.color} ring-1 ring-inset ring-current/30`
                        : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    )}
                  >
                    {cfg.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Body */}
        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : error ? (
          <div className="px-6 py-10 text-center">
            <p className="text-sm text-red-500">{error}</p>
            <button
              onClick={fetchRuns}
              className="mt-3 text-xs text-digitillis-accent hover:underline"
            >
              Retry
            </button>
          </div>
        ) : filteredRuns.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <History className="mx-auto h-10 w-10 text-gray-200" />
            <p className="mt-3 text-sm font-medium text-gray-500">
              No agent runs recorded yet.
            </p>
            <p className="mt-1 text-xs text-gray-400">
              Run an agent from the Actions page to see history here.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-left">
                  <th className="px-6 py-3 font-medium text-gray-600">Agent</th>
                  <th className="px-4 py-3 font-medium text-gray-600">Date</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-600">
                    Companies
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-600">
                    API Calls
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-600">
                    Cost
                  </th>
                  <th className="px-4 py-3 font-medium text-gray-600">Providers</th>
                  <th className="px-4 py-3 font-medium text-gray-600 text-right">
                    Batch ID
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredRuns.map((run) => {
                  const cfg = agentConfig(run.agent);
                  return (
                    <tr
                      key={run.batch_id}
                      className="group hover:bg-gray-50 transition-colors"
                    >
                      {/* Agent badge */}
                      <td className="px-6 py-3">
                        <AgentBadge agent={run.agent} />
                      </td>

                      {/* Date */}
                      <td className="px-4 py-3">
                        {run.started_at ? (
                          <div>
                            <span className="text-gray-900">
                              {formatDate(run.started_at)}
                            </span>
                            <span className="ml-2 text-xs text-gray-400">
                              {formatTimeAgo(run.started_at)}
                            </span>
                          </div>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>

                      {/* Companies */}
                      <td className="px-4 py-3 text-right">
                        <span
                          className={cn(
                            "font-semibold",
                            run.companies_processed > 0
                              ? "text-gray-900"
                              : "text-gray-400"
                          )}
                        >
                          {run.companies_processed > 0
                            ? run.companies_processed.toLocaleString()
                            : "—"}
                        </span>
                      </td>

                      {/* API Calls */}
                      <td className="px-4 py-3 text-right text-gray-700">
                        {run.total_calls.toLocaleString()}
                      </td>

                      {/* Cost */}
                      <td className="px-4 py-3 text-right">
                        <span
                          className={cn(
                            "font-semibold",
                            run.total_cost > 0.01
                              ? "text-gray-900"
                              : "text-gray-400"
                          )}
                        >
                          ${run.total_cost.toFixed(4)}
                        </span>
                      </td>

                      {/* Providers */}
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {run.providers.length > 0 ? (
                            run.providers.map((p) => (
                              <span
                                key={p}
                                className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600"
                              >
                                {p}
                              </span>
                            ))
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </div>
                      </td>

                      {/* Batch ID */}
                      <td className="px-4 py-3 text-right">
                        <code
                          className={cn(
                            "rounded px-1.5 py-0.5 text-xs",
                            cfg.bg,
                            cfg.color
                          )}
                          title={run.batch_id}
                        >
                          {run.batch_id === "unknown"
                            ? "—"
                            : run.batch_id.length > 20
                            ? `…${run.batch_id.slice(-16)}`
                            : run.batch_id}
                        </code>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Footer count */}
            <div className="border-t border-gray-100 px-6 py-3 text-xs text-gray-400">
              {filteredRuns.length === runs.length
                ? `${runs.length} run${runs.length !== 1 ? "s" : ""} total`
                : `${filteredRuns.length} of ${runs.length} runs`}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
