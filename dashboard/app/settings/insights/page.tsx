"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Lightbulb,
  Loader2,
  AlertCircle,
  ArrowLeft,
  Settings,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { getCompanies, type Company } from "@/lib/api";
import { cn, getPQSColor, TIER_LABELS } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types & helpers
// ---------------------------------------------------------------------------

interface DimensionAverages {
  total: number;
  firmographic: number;
  technographic: number;
  timing: number;
  engagement: number;
}

interface InsightsData {
  successfulCount: number;
  unsuccessfulCount: number;
  successfulAvg: DimensionAverages;
  unsuccessfulAvg: DimensionAverages;
  tierDistribution: Record<string, number>;
  topTierAmongQualified: string | null;
  topTierConversionRate: number | null;
}

const SUCCESS_STATUSES = ["engaged", "meeting_scheduled", "pilot_discussion", "pilot_signed", "active_pilot", "converted"];
const UNSUCCESSFUL_STATUSES = ["disqualified", "not_interested", "bounced"];

function avg(companies: Company[], field: keyof Company): number {
  if (!companies.length) return 0;
  const sum = companies.reduce((acc, c) => acc + ((c[field] as number) ?? 0), 0);
  return Math.round((sum / companies.length) * 10) / 10;
}

function computeDimensionAvg(companies: Company[]): DimensionAverages {
  return {
    total: avg(companies, "pqs_total"),
    firmographic: avg(companies, "pqs_firmographic"),
    technographic: avg(companies, "pqs_technographic"),
    timing: avg(companies, "pqs_timing"),
    engagement: avg(companies, "pqs_engagement"),
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DimensionBar({
  label,
  successVal,
  failVal,
  max,
}: {
  label: string;
  successVal: number;
  failVal: number;
  max: number;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="font-medium text-gray-700">{label}</span>
        <span className="tabular-nums">
          Successful: <span className="font-semibold text-green-700">{successVal}</span> ·
          Unsuccessful: <span className="font-semibold text-red-600">{failVal}</span>
        </span>
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-gray-100">
        {/* Unsuccessful bar (background) */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-red-200"
          style={{ width: `${(failVal / max) * 100}%` }}
        />
        {/* Successful bar (foreground) */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-green-500"
          style={{ width: `${(successVal / max) * 100}%` }}
        />
      </div>
    </div>
  );
}

function InsightCard({
  icon: Icon,
  iconColor,
  title,
  description,
}: {
  icon: typeof Lightbulb;
  iconColor: string;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3">
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconColor)} />
      <div>
        <p className="text-sm font-semibold text-gray-900">{title}</p>
        <p className="mt-0.5 text-sm text-gray-600">{description}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function SettingsInsightsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [insights, setInsights] = useState<InsightsData | null>(null);

  const computeInsights = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch all companies in parallel across status groups
      const [allRes] = await Promise.all([
        getCompanies({ limit: "500" } as Record<string, string>),
      ]);

      const all: Company[] = allRes.data;

      const successful = all.filter((c) => SUCCESS_STATUSES.includes(c.status));
      const unsuccessful = all.filter((c) => UNSUCCESSFUL_STATUSES.includes(c.status));

      // Tier distribution among qualified/successful companies
      const tierDist: Record<string, number> = {};
      successful.forEach((c) => {
        if (c.tier) {
          tierDist[c.tier] = (tierDist[c.tier] ?? 0) + 1;
        }
      });

      // Top tier among qualified
      let topTier: string | null = null;
      let topTierCount = 0;
      for (const [tier, count] of Object.entries(tierDist)) {
        if (count > topTierCount) {
          topTierCount = count;
          topTier = tier;
        }
      }

      // Conversion rate comparison for top tier vs others
      let topTierConversionRate: number | null = null;
      if (topTier) {
        const topTierAll = all.filter((c) => c.tier === topTier);
        const topTierConverted = topTierAll.filter((c) => SUCCESS_STATUSES.includes(c.status));
        if (topTierAll.length > 0) {
          topTierConversionRate = Math.round((topTierConverted.length / topTierAll.length) * 100);
        }
      }

      setInsights({
        successfulCount: successful.length,
        unsuccessfulCount: unsuccessful.length,
        successfulAvg: computeDimensionAvg(successful),
        unsuccessfulAvg: computeDimensionAvg(unsuccessful),
        tierDistribution: tierDist,
        topTierAmongQualified: topTier,
        topTierConversionRate,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load pipeline data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    computeInsights();
  }, [computeInsights]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">ICP Scoring Insights</h2>
          <p className="mt-1 text-sm text-gray-500">
            Data-driven analysis of your pipeline to identify scoring optimisations.
          </p>
        </div>
        <button
          onClick={computeInsights}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <BarChart3 className="h-4 w-4" />}
          {loading ? "Analysing…" : "Refresh"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-gray-100" />
          ))}
        </div>
      )}

      {/* Main content */}
      {!loading && insights && (
        <>
          {/* Summary row */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-xl border border-gray-200 bg-white p-4 text-center shadow-sm">
              <p className="text-2xl font-bold text-green-600">{insights.successfulCount}</p>
              <p className="mt-1 text-xs font-medium text-gray-500">Successful Prospects</p>
              <p className="text-[10px] text-gray-400">(engaged → converted)</p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-4 text-center shadow-sm">
              <p className="text-2xl font-bold text-red-500">{insights.unsuccessfulCount}</p>
              <p className="mt-1 text-xs font-medium text-gray-500">Unsuccessful Prospects</p>
              <p className="text-[10px] text-gray-400">(disqualified / not interested / bounced)</p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-4 text-center shadow-sm">
              <p className={cn("text-2xl font-bold", getPQSColor(insights.successfulAvg.total))}>
                {insights.successfulAvg.total}
              </p>
              <p className="mt-1 text-xs font-medium text-gray-500">Avg PQS (Successful)</p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-4 text-center shadow-sm">
              <p className={cn("text-2xl font-bold", getPQSColor(insights.unsuccessfulAvg.total))}>
                {insights.unsuccessfulAvg.total}
              </p>
              <p className="mt-1 text-xs font-medium text-gray-500">Avg PQS (Unsuccessful)</p>
            </div>
          </div>

          {/* PQS Dimension Comparison */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="mb-1 flex items-center gap-2 text-base font-semibold text-gray-900">
              <BarChart3 className="h-5 w-5 text-indigo-500" />
              PQS Dimension Comparison
            </h3>
            <p className="mb-4 text-sm text-gray-500">
              Average scores per dimension across successful (green) vs unsuccessful (red) prospects.
            </p>

            {insights.successfulCount === 0 && insights.unsuccessfulCount === 0 ? (
              <p className="text-sm text-gray-400 italic">
                Not enough data yet. More prospects need to be progressed or disqualified.
              </p>
            ) : (
              <div className="space-y-4">
                <DimensionBar
                  label="Total PQS"
                  successVal={insights.successfulAvg.total}
                  failVal={insights.unsuccessfulAvg.total}
                  max={100}
                />
                <DimensionBar
                  label="Firmographic"
                  successVal={insights.successfulAvg.firmographic}
                  failVal={insights.unsuccessfulAvg.firmographic}
                  max={25}
                />
                <DimensionBar
                  label="Technographic"
                  successVal={insights.successfulAvg.technographic}
                  failVal={insights.unsuccessfulAvg.technographic}
                  max={25}
                />
                <DimensionBar
                  label="Timing"
                  successVal={insights.successfulAvg.timing}
                  failVal={insights.unsuccessfulAvg.timing}
                  max={25}
                />
                <DimensionBar
                  label="Engagement"
                  successVal={insights.successfulAvg.engagement}
                  failVal={insights.unsuccessfulAvg.engagement}
                  max={25}
                />
              </div>
            )}
          </div>

          {/* Tier distribution */}
          {Object.keys(insights.tierDistribution).length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <h3 className="mb-1 flex items-center gap-2 text-base font-semibold text-gray-900">
                <BarChart3 className="h-5 w-5 text-purple-500" />
                Tier Distribution Among Successful Prospects
              </h3>
              <p className="mb-4 text-sm text-gray-500">
                Which tiers are most commonly found among your engaged and converted prospects.
              </p>
              <div className="space-y-2">
                {Object.entries(insights.tierDistribution)
                  .sort(([, a], [, b]) => b - a)
                  .map(([tier, count]) => {
                    const pct = Math.round((count / insights.successfulCount) * 100);
                    return (
                      <div key={tier} className="flex items-center gap-3">
                        <span className="w-28 shrink-0 rounded bg-indigo-50 px-2 py-0.5 text-center text-xs font-medium text-indigo-700">
                          {tier} — {TIER_LABELS[tier] ?? tier}
                        </span>
                        <div className="flex-1 h-2.5 overflow-hidden rounded-full bg-gray-100">
                          <div
                            className="h-full rounded-full bg-indigo-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="w-16 text-right text-xs tabular-nums text-gray-500">
                          {count} ({pct}%)
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* AI-style suggestions */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="mb-4 flex items-center gap-2 text-base font-semibold text-gray-900">
              <Lightbulb className="h-5 w-5 text-amber-500" />
              Scoring Recommendations
            </h3>
            <div className="space-y-3">
              {/* Always show the PQS gap insight if data exists */}
              {insights.successfulCount > 0 && insights.unsuccessfulCount > 0 && (
                <InsightCard
                  icon={
                    insights.successfulAvg.total > insights.unsuccessfulAvg.total
                      ? TrendingUp
                      : TrendingDown
                  }
                  iconColor={
                    insights.successfulAvg.total > insights.unsuccessfulAvg.total
                      ? "text-green-600"
                      : "text-red-500"
                  }
                  title={`Average PQS gap: ${Math.abs(insights.successfulAvg.total - insights.unsuccessfulAvg.total)} points`}
                  description={`Successful prospects average ${insights.successfulAvg.total}/100 vs ${insights.unsuccessfulAvg.total}/100 for unsuccessful ones. ${
                    insights.successfulAvg.total - insights.unsuccessfulAvg.total >= 20
                      ? "The gap is significant — your scoring model is working well."
                      : "The gap is narrow — consider tightening your qualification threshold."
                  }`}
                />
              )}

              {/* Firmographic signal */}
              {insights.successfulAvg.firmographic > insights.unsuccessfulAvg.firmographic + 3 && (
                <InsightCard
                  icon={TrendingUp}
                  iconColor="text-green-600"
                  title="Firmographic signals are strong differentiators"
                  description={`Successful prospects score ${insights.successfulAvg.firmographic}/25 vs ${insights.unsuccessfulAvg.firmographic}/25. Consider increasing firmographic weight in your ICP config.`}
                />
              )}

              {/* Technographic signal */}
              {insights.successfulAvg.technographic > insights.unsuccessfulAvg.technographic + 2 && (
                <InsightCard
                  icon={TrendingUp}
                  iconColor="text-green-600"
                  title="Technology stack is a strong predictor of fit"
                  description={`Successful prospects average ${insights.successfulAvg.technographic}/25 technographic vs ${insights.unsuccessfulAvg.technographic}/25. Prioritising tech-matched leads may improve pipeline quality.`}
                />
              )}

              {/* Timing signal */}
              {insights.successfulAvg.timing > insights.unsuccessfulAvg.timing + 2 && (
                <InsightCard
                  icon={TrendingUp}
                  iconColor="text-amber-500"
                  title="Timing signals indicate high buying intent"
                  description={`Successful prospects average ${insights.successfulAvg.timing}/25 timing vs ${insights.unsuccessfulAvg.timing}/25. Prospects with strong timing signals are converting better.`}
                />
              )}

              {/* Top tier insight */}
              {insights.topTierAmongQualified && insights.topTierConversionRate !== null && (
                <InsightCard
                  icon={CheckCircle2}
                  iconColor="text-indigo-500"
                  title={`Tier ${insights.topTierAmongQualified} (${TIER_LABELS[insights.topTierAmongQualified] ?? insights.topTierAmongQualified}) is your strongest segment`}
                  description={`${insights.topTierConversionRate}% of tier ${insights.topTierAmongQualified} prospects reach an engaged or later stage. This tier makes up ${Math.round((insights.tierDistribution[insights.topTierAmongQualified] / insights.successfulCount) * 100)}% of your successful pipeline. Consider focusing outreach here.`}
                />
              )}

              {/* Low engagement warning */}
              {insights.successfulAvg.engagement < 10 && insights.successfulCount > 0 && (
                <InsightCard
                  icon={XCircle}
                  iconColor="text-red-500"
                  title="Engagement scores are low across all prospects"
                  description={`Even successful prospects average only ${insights.successfulAvg.engagement}/25 for engagement. This often means email opens and clicks aren't being tracked — verify your sequence tracking is configured correctly.`}
                />
              )}

              {/* Not enough data */}
              {insights.successfulCount < 3 && insights.unsuccessfulCount < 3 && (
                <InsightCard
                  icon={Lightbulb}
                  iconColor="text-gray-400"
                  title="Not enough data for meaningful insights yet"
                  description="Progress at least 3 prospects to an engaged/converted stage and disqualify at least 3 to see reliable scoring recommendations."
                />
              )}
            </div>
          </div>

          {/* Back to settings note card */}
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-5">
            <div className="flex items-start gap-3">
              <Settings className="mt-0.5 h-5 w-5 shrink-0 text-gray-400" />
              <div>
                <p className="text-sm font-semibold text-gray-700">
                  Apply these recommendations in Settings
                </p>
                <p className="mt-1 text-sm text-gray-500">
                  Adjust your ICP criteria, scoring weights, and sequences from the Settings page. After making changes, return here to see how your pipeline distribution evolves.
                </p>
                <Link
                  href="/settings"
                  className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back to Settings
                </Link>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
