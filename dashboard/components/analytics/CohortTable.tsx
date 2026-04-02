"use client";

/**
 * CohortTable — Sortable cohort performance table with color-coded conversion column.
 */

import { useState } from "react";
import { cn } from "@/lib/utils";

export interface CohortRow {
  cohort_name: string;
  count: number;
  contacted_pct: number;
  reply_rate: number;
  interested_pct: number;
  conversion_rate: number;
  avg_pqs: number;
}

interface CohortTableProps {
  cohorts: CohortRow[];
  groupBy: string;
  className?: string;
}

type SortKey = keyof CohortRow;

function conversionColor(rate: number): string {
  if (rate >= 5) return "text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20";
  if (rate >= 2) return "text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20";
  return "text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20";
}

export function CohortTable({ cohorts, groupBy, className }: CohortTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("conversion_rate");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  if (!cohorts || cohorts.length === 0) {
    return (
      <div className={cn("flex items-center justify-center py-12 text-gray-400 dark:text-gray-600 text-sm", className)}>
        No cohort data available for the selected group
      </div>
    );
  }

  const sorted = [...cohorts].sort((a, b) => {
    const av = a[sortKey] as number;
    const bv = b[sortKey] as number;
    return sortDir === "desc" ? bv - av : av - bv;
  });

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const SortIcon = ({ k }: { k: SortKey }) =>
    sortKey === k ? (
      <span className="ml-0.5 text-blue-500">{sortDir === "desc" ? "↓" : "↑"}</span>
    ) : (
      <span className="ml-0.5 text-gray-300 dark:text-gray-600">↕</span>
    );

  const groupLabel = {
    cluster: "Cluster",
    tranche: "Tranche",
    persona: "Persona",
    sequence_name: "Sequence",
  }[groupBy] ?? "Cohort";

  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-gray-100 dark:border-gray-800">
            <th className="text-left py-2 px-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {groupLabel}
            </th>
            {(
              [
                ["count", "Companies"],
                ["contacted_pct", "Contacted %"],
                ["reply_rate", "Reply Rate"],
                ["interested_pct", "Interested %"],
                ["conversion_rate", "Conversion"],
                ["avg_pqs", "Avg PQS"],
              ] as [SortKey, string][]
            ).map(([k, label]) => (
              <th
                key={k}
                className="text-right py-2 px-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 cursor-pointer select-none hover:text-gray-900 dark:hover:text-gray-100"
                onClick={() => handleSort(k)}
                aria-sort={sortKey === k ? (sortDir === "desc" ? "descending" : "ascending") : "none"}
              >
                {label}
                <SortIcon k={k} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={row.cohort_name}
              className={cn(
                "border-b border-gray-50 dark:border-gray-800/50 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors",
              )}
            >
              <td className="py-2.5 px-3 font-medium text-gray-900 dark:text-gray-100">
                <div className="flex items-center gap-2">
                  {i === 0 && sortKey === "conversion_rate" && (
                    <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
                      Best
                    </span>
                  )}
                  <span className="truncate max-w-[180px]" title={row.cohort_name}>
                    {row.cohort_name}
                  </span>
                </div>
              </td>
              <td className="py-2.5 px-3 text-right text-gray-700 dark:text-gray-300">
                {row.count.toLocaleString()}
              </td>
              <td className="py-2.5 px-3 text-right text-gray-700 dark:text-gray-300">
                {row.contacted_pct.toFixed(1)}%
              </td>
              <td className="py-2.5 px-3 text-right text-gray-700 dark:text-gray-300">
                {row.reply_rate.toFixed(1)}%
              </td>
              <td className="py-2.5 px-3 text-right text-gray-700 dark:text-gray-300">
                {row.interested_pct.toFixed(1)}%
              </td>
              <td className="py-2.5 px-3 text-right">
                <span
                  className={cn(
                    "inline-block rounded px-2 py-0.5 text-xs font-semibold",
                    conversionColor(row.conversion_rate),
                  )}
                >
                  {row.conversion_rate.toFixed(1)}%
                </span>
              </td>
              <td className="py-2.5 px-3 text-right text-gray-700 dark:text-gray-300">
                {row.avg_pqs.toFixed(0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
