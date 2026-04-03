"use client";

/**
 * RevenueProjection — Projected ARR card with confidence range gauge
 * and pipeline value waterfall.
 */

import { cn } from "@/lib/utils";

export interface DealStage {
  stage: string;
  count: number;
  est_value_usd: number;
}

export interface RevenueAttributionData {
  pipeline_stages: DealStage[];
  projected_arr_90d: number;
  projected_arr_180d: number;
  confidence_range: [number, number];
  best_performing_cluster: string;
  best_performing_sequence: string;
  avg_deal_size_assumption: number;
  weighted_pipeline_value: number;
}

interface RevenueProjectionProps {
  attribution: RevenueAttributionData;
  className?: string;
}

const STAGE_LABELS: Record<string, string> = {
  outreach_sent: "Outreach Sent",
  replied: "Replied",
  interested: "Interested",
  demo_booked: "Demo Booked",
  proposal: "Proposal",
  closed_won: "Closed Won",
  closed_lost: "Closed Lost",
};

function formatCurrency(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${Math.round(v).toLocaleString()}`;
}

export function RevenueProjection({ attribution, className }: RevenueProjectionProps) {
  const { pipeline_stages, projected_arr_90d, projected_arr_180d, confidence_range, weighted_pipeline_value } = attribution;

  const maxValue = Math.max(...pipeline_stages.map((s) => s.est_value_usd), 1);
  const [low, high] = confidence_range;
  const range = high - low;

  // Gauge: position of projected value within confidence range
  const gaugePosition = range > 0
    ? Math.min(Math.max(((projected_arr_90d - low) / range) * 100, 0), 100)
    : 50;

  return (
    <div className={cn("space-y-6", className)}>
      {/* Pipeline Waterfall */}
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
          Pipeline Value by Stage
        </h4>
        <div className="space-y-2">
          {pipeline_stages
            .filter((s) => s.stage !== "closed_lost" && s.est_value_usd > 0)
            .map((stage) => {
              const pct = Math.max((stage.est_value_usd / maxValue) * 100, 3);
              return (
                <div key={stage.stage} className="flex items-center gap-3">
                  <div className="w-28 shrink-0 text-right">
                    <span className="text-xs text-gray-600 dark:text-gray-400">
                      {STAGE_LABELS[stage.stage] ?? stage.stage}
                    </span>
                  </div>
                  <div className="flex-1 relative h-7">
                    <div
                      className="h-full rounded flex items-center px-2 bg-blue-100 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 transition-all duration-300"
                      style={{ width: `${pct}%` }}
                    >
                      <span className="text-xs font-semibold text-blue-700 dark:text-blue-300 whitespace-nowrap">
                        {formatCurrency(stage.est_value_usd)}
                      </span>
                    </div>
                  </div>
                  <div className="w-16 shrink-0 text-right">
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {stage.count} deals
                    </span>
                  </div>
                </div>
              );
            })}
        </div>
        <div className="mt-3 flex items-center justify-between border-t border-gray-100 dark:border-gray-800 pt-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">Weighted Pipeline Total</span>
          <span className="text-sm font-bold text-gray-900 dark:text-gray-100">
            {formatCurrency(weighted_pipeline_value)}
          </span>
        </div>
      </div>

      {/* ARR Projection Card */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gradient-to-br from-blue-50 to-white dark:from-blue-950/20 dark:to-gray-900 p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
          Projected ARR
        </p>
        <div className="flex items-end gap-4 mb-4">
          <div>
            <p className="text-3xl font-bold text-gray-900 dark:text-gray-100">
              {formatCurrency(projected_arr_90d)}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">in 90 days</p>
          </div>
          <div className="pb-1">
            <p className="text-xl font-semibold text-gray-500 dark:text-gray-400">
              {formatCurrency(projected_arr_180d)}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">in 180 days</p>
          </div>
        </div>

        {/* Confidence range gauge */}
        <div>
          <div className="flex justify-between text-[10px] text-gray-400 dark:text-gray-500 mb-1">
            <span>{formatCurrency(low)} low</span>
            <span className="text-gray-600 dark:text-gray-300 font-medium">
              {formatCurrency(projected_arr_90d)} projected
            </span>
            <span>{formatCurrency(high)} high</span>
          </div>
          <div className="relative h-2.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
            {/* Confidence range fill */}
            <div
              className="absolute inset-y-0 bg-blue-100 dark:bg-blue-900/30"
              style={{ left: 0, right: 0 }}
            />
            {/* Projected marker */}
            <div
              className="absolute top-0 bottom-0 w-1 bg-blue-500 rounded-full"
              style={{ left: `calc(${gaugePosition}% - 2px)` }}
              aria-label={`Projected: ${formatCurrency(projected_arr_90d)}`}
            />
          </div>
          <p className="mt-1.5 text-[10px] text-gray-400 dark:text-gray-500">
            Confidence range based on historical conversion variance (±40%)
          </p>
        </div>
      </div>
    </div>
  );
}
