"use client";

// Win/Loss Analysis — Feature 30
// Fetches companies with terminal statuses (converted, not_interested, bounced)
// and shows side-by-side comparison: avg PQS, tier distribution, pipeline time

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Trophy,
  XCircle,
  Clock,
  Loader2,
  BarChart3,
  Target,
  Users,
  TrendingDown,
} from "lucide-react";
import { getCompanies, type Company } from "@/lib/api";
import { cn, TIER_LABELS } from "@/lib/utils";

interface OutcomeGroup {
  companies: Company[];
  count: number;
}

function avg(nums: number[]): number {
  if (nums.length === 0) return 0;
  return Math.round(nums.reduce((a, b) => a + b, 0) / nums.length);
}

function tierDistribution(companies: Company[]): Record<string, number> {
  const dist: Record<string, number> = {};
  for (const c of companies) {
    const t = c.tier ?? "unknown";
    dist[t] = (dist[t] ?? 0) + 1;
  }
  return dist;
}

function avgDaysInPipeline(companies: Company[]): number {
  const withBoth = companies.filter((c) => c.created_at && c.updated_at);
  if (withBoth.length === 0) return 0;
  const days = withBoth.map((c) => {
    const ms = new Date(c.updated_at).getTime() - new Date(c.created_at!).getTime();
    return Math.round(ms / (1000 * 60 * 60 * 24));
  });
  return avg(days);
}

// Collect tiers dynamically from data rather than hardcoding
function allTierKeys(wonTiers: Record<string, number>, lostTiers: Record<string, number>): string[] {
  return Array.from(new Set([...Object.keys(wonTiers), ...Object.keys(lostTiers)])).sort();
}

function HorizontalBar({
  value,
  max,
  color,
  label,
}: {
  value: number;
  max: number;
  color: string;
  label: string;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-20 shrink-0 text-gray-600">{label}</span>
      <div className="relative flex-1 h-5 rounded bg-gray-100">
        <div
          className={cn("h-full rounded transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
        />
        <span className="absolute inset-0 flex items-center px-2 text-xs font-medium text-gray-700 mix-blend-difference">
          {value}
        </span>
      </div>
      <span className="w-8 shrink-0 text-right text-xs text-gray-500">{pct}%</span>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
  bg,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
}) {
  return (
    <div className="rounded-lg border border-gray-100 bg-white p-4">
      <div className={cn("inline-flex rounded-lg p-2 mb-2", bg)}>
        <Icon className={cn("h-5 w-5", color)} />
      </div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-sm text-gray-500">{label}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

export default function WinLossPage() {
  const [won, setWon] = useState<OutcomeGroup>({ companies: [], count: 0 });
  const [lost, setLost] = useState<OutcomeGroup>({ companies: [], count: 0 });
  const [noResponse, setNoResponse] = useState<OutcomeGroup>({ companies: [], count: 0 });
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [wonRes, lostRes, bouncedRes] = await Promise.all([
        getCompanies({ status: "converted", limit: "200" }).catch(() => ({ data: [], count: 0 })),
        getCompanies({ status: "not_interested", limit: "200" }).catch(() => ({ data: [], count: 0 })),
        getCompanies({ status: "bounced", limit: "200" }).catch(() => ({ data: [], count: 0 })),
      ]);
      setWon({ companies: wonRes.data, count: wonRes.count });
      setLost({ companies: lostRes.data, count: lostRes.count });
      setNoResponse({ companies: bouncedRes.data, count: bouncedRes.count });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const totalOutcomes = won.count + lost.count + noResponse.count;
  const hasData = totalOutcomes > 0;

  // Computed stats
  const wonAvgPQS = avg(won.companies.map((c) => c.pqs_total));
  const lostAvgPQS = avg(lost.companies.map((c) => c.pqs_total));
  const noResponseAvgPQS = avg(noResponse.companies.map((c) => c.pqs_total));

  const wonDays = avgDaysInPipeline(won.companies);
  const lostDays = avgDaysInPipeline(lost.companies);

  const wonTiers = tierDistribution(won.companies);
  const lostTiers = tierDistribution(lost.companies);
  const dynamicTiers = allTierKeys(wonTiers, lostTiers);
  const maxTierCount = Math.max(
    ...dynamicTiers.map((t) => Math.max(wonTiers[t] ?? 0, lostTiers[t] ?? 0)),
    1
  );

  const winRate =
    totalOutcomes > 0 ? Math.round((won.count / totalOutcomes) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href="/analytics"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Analytics
      </Link>

      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-indigo-500" />
          <h2 className="text-2xl font-bold text-gray-900">Win / Loss Analysis</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          Patterns from companies with recorded outcomes — Won, Lost, and No Response.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          <span className="ml-2 text-sm text-gray-500">Loading outcomes…</span>
        </div>
      ) : !hasData ? (
        /* Empty state */
        <div className="rounded-xl border border-gray-200 bg-white p-12 text-center shadow-sm">
          <BarChart3 className="mx-auto h-10 w-10 text-gray-300 mb-4" />
          <h3 className="text-lg font-semibold text-gray-700">No outcomes recorded yet</h3>
          <p className="mt-2 text-sm text-gray-500 max-w-sm mx-auto">
            Use the "Record Outcome" section on a company's detail page to log Won, Lost, or No Response results.
            Patterns will appear here once you have data.
          </p>
          <Link
            href="/prospects"
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
          >
            Go to Prospects
          </Link>
        </div>
      ) : (
        <>
          {/* Summary overview */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Total Outcomes"
              value={totalOutcomes}
              sub="across all outcome types"
              icon={Users}
              color="text-indigo-600"
              bg="bg-indigo-50"
            />
            <StatCard
              label="Won"
              value={won.count}
              sub={`${winRate}% win rate`}
              icon={Trophy}
              color="text-green-600"
              bg="bg-green-50"
            />
            <StatCard
              label="Lost"
              value={lost.count}
              sub={lost.count > 0 ? `avg PQS ${lostAvgPQS}` : "none recorded"}
              icon={XCircle}
              color="text-red-500"
              bg="bg-red-50"
            />
            <StatCard
              label="No Response"
              value={noResponse.count}
              sub={noResponse.count > 0 ? `avg PQS ${noResponseAvgPQS}` : "none recorded"}
              icon={Clock}
              color="text-amber-600"
              bg="bg-amber-50"
            />
          </div>

          {/* Win rate bar */}
          <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="text-base font-semibold text-gray-900 mb-4">Outcome Distribution</h3>
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="flex items-center gap-1.5 text-green-700 font-medium">
                    <Trophy className="h-4 w-4" /> Won
                  </span>
                  <span className="text-gray-500">{won.count} ({Math.round((won.count / totalOutcomes) * 100)}%)</span>
                </div>
                <div className="h-4 w-full rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-green-500 transition-all duration-500"
                    style={{ width: `${(won.count / totalOutcomes) * 100}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="flex items-center gap-1.5 text-red-700 font-medium">
                    <XCircle className="h-4 w-4" /> Lost
                  </span>
                  <span className="text-gray-500">{lost.count} ({Math.round((lost.count / totalOutcomes) * 100)}%)</span>
                </div>
                <div className="h-4 w-full rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-red-400 transition-all duration-500"
                    style={{ width: `${(lost.count / totalOutcomes) * 100}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="flex items-center gap-1.5 text-amber-700 font-medium">
                    <Clock className="h-4 w-4" /> No Response
                  </span>
                  <span className="text-gray-500">{noResponse.count} ({Math.round((noResponse.count / totalOutcomes) * 100)}%)</span>
                </div>
                <div className="h-4 w-full rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-amber-400 transition-all duration-500"
                    style={{ width: `${(noResponse.count / totalOutcomes) * 100}%` }}
                  />
                </div>
              </div>
            </div>
          </section>

          {/* PQS comparison */}
          <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-6">
              <Target className="h-5 w-5 text-indigo-500" />
              <h3 className="text-base font-semibold text-gray-900">Average PQS by Outcome</h3>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {[
                { label: "Won", value: wonAvgPQS, color: "bg-green-500", textColor: "text-green-700", count: won.count },
                { label: "Lost", value: lostAvgPQS, color: "bg-red-400", textColor: "text-red-700", count: lost.count },
                { label: "No Response", value: noResponseAvgPQS, color: "bg-amber-400", textColor: "text-amber-700", count: noResponse.count },
              ].map((item) => (
                <div key={item.label} className="rounded-lg border border-gray-100 p-4 text-center">
                  <p className={cn("text-3xl font-bold", item.textColor)}>{item.count > 0 ? item.value : "—"}</p>
                  <p className="mt-1 text-sm text-gray-500">Avg PQS</p>
                  <p className="text-xs font-medium text-gray-700 mt-0.5">{item.label}</p>
                  {item.count > 0 && (
                    <div className="mt-3 h-2 w-full rounded-full bg-gray-100 overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", item.color)}
                        style={{ width: `${item.value}%` }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
            {wonAvgPQS > 0 && lostAvgPQS > 0 && (
              <p className="mt-4 text-sm text-gray-500 text-center">
                Won deals averaged{" "}
                <span className={cn("font-semibold", wonAvgPQS >= lostAvgPQS ? "text-green-700" : "text-red-600")}>
                  {wonAvgPQS > lostAvgPQS ? `+${wonAvgPQS - lostAvgPQS}` : `${wonAvgPQS - lostAvgPQS}`} PQS points
                </span>{" "}
                {wonAvgPQS >= lostAvgPQS ? "higher" : "lower"} than lost deals.
              </p>
            )}
          </section>

          {/* Tier distribution */}
          {(won.count > 0 || lost.count > 0) && (
            <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-2 mb-6">
                <BarChart3 className="h-5 w-5 text-purple-500" />
                <h3 className="text-base font-semibold text-gray-900">Tier Distribution — Won vs Lost</h3>
              </div>
              <div className="grid gap-8 sm:grid-cols-2">
                <div>
                  <p className="mb-3 text-sm font-semibold text-green-700 flex items-center gap-1.5">
                    <Trophy className="h-4 w-4" /> Won ({won.count})
                  </p>
                  <div className="space-y-2">
                    {dynamicTiers.filter((t) => (wonTiers[t] ?? 0) > 0).map((tier) => (
                      <HorizontalBar
                        key={tier}
                        label={TIER_LABELS[tier] ?? tier}
                        value={wonTiers[tier] ?? 0}
                        max={maxTierCount}
                        color="bg-green-400"
                      />
                    ))}
                    {Object.keys(wonTiers).length === 0 && (
                      <p className="text-sm text-gray-400 italic">No tier data available.</p>
                    )}
                  </div>
                </div>
                <div>
                  <p className="mb-3 text-sm font-semibold text-red-700 flex items-center gap-1.5">
                    <XCircle className="h-4 w-4" /> Lost ({lost.count})
                  </p>
                  <div className="space-y-2">
                    {dynamicTiers.filter((t) => (lostTiers[t] ?? 0) > 0).map((tier) => (
                      <HorizontalBar
                        key={tier}
                        label={TIER_LABELS[tier] ?? tier}
                        value={lostTiers[tier] ?? 0}
                        max={maxTierCount}
                        color="bg-red-400"
                      />
                    ))}
                    {Object.keys(lostTiers).length === 0 && (
                      <p className="text-sm text-gray-400 italic">No tier data available.</p>
                    )}
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Time in pipeline */}
          {(wonDays > 0 || lostDays > 0) && (
            <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-2 mb-6">
                <TrendingDown className="h-5 w-5 text-blue-500" />
                <h3 className="text-base font-semibold text-gray-900">Time to Outcome (days)</h3>
                <span className="ml-auto text-xs text-gray-400">From discovered → outcome</span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border border-green-100 bg-green-50 p-4 text-center">
                  <p className="text-3xl font-bold text-green-700">{wonDays > 0 ? wonDays : "—"}</p>
                  <p className="mt-1 text-sm text-gray-500">Avg days to Win</p>
                  <p className="mt-0.5 text-xs text-gray-400">{won.count} companies</p>
                </div>
                <div className="rounded-lg border border-red-100 bg-red-50 p-4 text-center">
                  <p className="text-3xl font-bold text-red-600">{lostDays > 0 ? lostDays : "—"}</p>
                  <p className="mt-1 text-sm text-gray-500">Avg days to Loss</p>
                  <p className="mt-0.5 text-xs text-gray-400">{lost.count} companies</p>
                </div>
              </div>
              {wonDays > 0 && lostDays > 0 && (
                <p className="mt-4 text-sm text-gray-500 text-center">
                  Won deals closed{" "}
                  <span className={cn("font-semibold", wonDays <= lostDays ? "text-green-700" : "text-amber-600")}>
                    {Math.abs(wonDays - lostDays)} days {wonDays <= lostDays ? "faster" : "slower"}
                  </span>{" "}
                  than lost deals on average.
                </p>
              )}
            </section>
          )}

          {/* Company lists */}
          <div className="grid gap-6 lg:grid-cols-3">
            {[
              { group: won, label: "Won", icon: Trophy, borderColor: "border-green-200", bgColor: "bg-green-50", textColor: "text-green-700" },
              { group: lost, label: "Lost", icon: XCircle, borderColor: "border-red-200", bgColor: "bg-red-50", textColor: "text-red-700" },
              { group: noResponse, label: "No Response", icon: Clock, borderColor: "border-amber-200", bgColor: "bg-amber-50", textColor: "text-amber-700" },
            ].map(({ group, label, icon: Icon, borderColor, bgColor, textColor }) => (
              <section key={label} className={cn("rounded-xl border p-5 shadow-sm", borderColor, bgColor)}>
                <div className="flex items-center gap-2 mb-3">
                  <Icon className={cn("h-4 w-4", textColor)} />
                  <h3 className={cn("text-sm font-semibold", textColor)}>{label} ({group.count})</h3>
                </div>
                {group.companies.length === 0 ? (
                  <p className="text-xs text-gray-400 italic">None recorded yet.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {group.companies.slice(0, 8).map((c) => (
                      <li key={c.id}>
                        <Link
                          href={`/prospects/${c.id}`}
                          className="flex items-center justify-between rounded-md bg-white/60 px-2.5 py-1.5 text-sm hover:bg-white transition-colors"
                        >
                          <span className="font-medium text-gray-800 truncate">{c.name}</span>
                          <span className="ml-2 shrink-0 text-xs text-gray-500">PQS {c.pqs_total}</span>
                        </Link>
                      </li>
                    ))}
                    {group.count > 8 && (
                      <li className="pt-1">
                        <Link
                          href={`/prospects?status=${label === "Won" ? "converted" : label === "Lost" ? "not_interested" : "bounced"}`}
                          className={cn("text-xs font-medium hover:underline", textColor)}
                        >
                          View all {group.count} &rarr;
                        </Link>
                      </li>
                    )}
                  </ul>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
