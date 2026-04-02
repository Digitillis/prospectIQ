"use client";

/**
 * FunnelChart — CSS-based horizontal funnel visualization.
 * No external chart library required.
 */

import { cn } from "@/lib/utils";

export interface FunnelStage {
  stage_name: string;
  stage_key: string;
  count: number;
  conversion_rate: number;
  avg_days_in_stage: number;
  drop_off: number;
  is_bottleneck: boolean;
}

interface FunnelChartProps {
  stages: FunnelStage[];
  className?: string;
}

function formatCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function FunnelChart({ stages, className }: FunnelChartProps) {
  if (!stages || stages.length === 0) {
    return (
      <div className={cn("flex items-center justify-center py-12 text-gray-400 dark:text-gray-600", className)}>
        No funnel data available
      </div>
    );
  }

  const maxCount = Math.max(...stages.map((s) => s.count), 1);

  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <div className="min-w-[640px] space-y-1.5">
        {stages.map((stage, i) => {
          const widthPct = Math.max((stage.count / maxCount) * 100, 4);
          const isFirst = i === 0;

          return (
            <div key={stage.stage_key}>
              {/* Conversion arrow between stages */}
              {!isFirst && (
                <div className="flex items-center gap-2 py-0.5 pl-4">
                  <span className="text-gray-300 dark:text-gray-600 text-xs">↓</span>
                  <span
                    className={cn(
                      "text-[10px] font-medium",
                      stage.conversion_rate >= 50
                        ? "text-green-500 dark:text-green-400"
                        : stage.conversion_rate >= 20
                        ? "text-amber-500 dark:text-amber-400"
                        : "text-red-500 dark:text-red-400"
                    )}
                  >
                    {stage.conversion_rate.toFixed(1)}% converted
                  </span>
                  {stage.drop_off > 0 && (
                    <span className="text-[10px] text-gray-400 dark:text-gray-500">
                      ({stage.drop_off.toLocaleString()} dropped)
                    </span>
                  )}
                </div>
              )}

              {/* Stage bar */}
              <div
                className="group relative flex items-center gap-3 cursor-default"
                aria-label={`${stage.stage_name}: ${stage.count} contacts`}
              >
                {/* Stage label */}
                <div className="shrink-0 w-32 text-right">
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                    {stage.stage_name}
                  </span>
                </div>

                {/* Bar */}
                <div className="flex-1 relative h-9">
                  <div
                    className={cn(
                      "h-full rounded-md flex items-center px-3 transition-all duration-300",
                      stage.is_bottleneck
                        ? "bg-amber-100 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700"
                        : "bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800",
                    )}
                    style={{ width: `${widthPct}%` }}
                  >
                    <span
                      className={cn(
                        "text-sm font-bold",
                        stage.is_bottleneck
                          ? "text-amber-700 dark:text-amber-300"
                          : "text-blue-700 dark:text-blue-300"
                      )}
                    >
                      {formatCount(stage.count)}
                    </span>
                    {stage.is_bottleneck && (
                      <span className="ml-2 text-[9px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400 bg-amber-200 dark:bg-amber-800/50 px-1.5 py-0.5 rounded">
                        Bottleneck
                      </span>
                    )}
                  </div>
                </div>

                {/* Tooltip on hover */}
                <div className="absolute left-36 top-10 z-10 hidden group-hover:block w-48 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg p-3 text-xs space-y-1">
                  <p className="font-semibold text-gray-900 dark:text-gray-100">{stage.stage_name}</p>
                  <p className="text-gray-600 dark:text-gray-400">Count: <span className="font-medium text-gray-900 dark:text-gray-100">{stage.count.toLocaleString()}</span></p>
                  <p className="text-gray-600 dark:text-gray-400">
                    Conversion from prev:{" "}
                    <span className="font-medium text-gray-900 dark:text-gray-100">{stage.conversion_rate.toFixed(1)}%</span>
                  </p>
                  {stage.avg_days_in_stage > 0 && (
                    <p className="text-gray-600 dark:text-gray-400">
                      Avg days in stage:{" "}
                      <span className="font-medium text-gray-900 dark:text-gray-100">{stage.avg_days_in_stage.toFixed(1)}d</span>
                    </p>
                  )}
                  {stage.drop_off > 0 && (
                    <p className="text-red-500 dark:text-red-400">
                      Drop-off: {stage.drop_off.toLocaleString()}
                    </p>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
