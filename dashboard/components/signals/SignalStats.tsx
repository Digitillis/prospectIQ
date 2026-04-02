"use client";

/**
 * SignalStats — Four-stat row for the Signal Monitor header.
 * Calls GET /api/signals/stats on mount and auto-refreshes every 60s.
 */

import { useEffect, useState, useCallback } from "react";
import { Bell, Zap, Clock, Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { getSignalStats, SignalStats as SignalStatsType } from "@/lib/api";

interface StatChipProps {
  icon: React.ReactNode;
  value: number | string;
  label: string;
  highlight?: "red" | "amber" | "blue" | "gray";
}

function StatChip({ icon, value, label, highlight }: StatChipProps) {
  const colorMap: Record<string, { icon: string; value: string; bg: string }> = {
    red:   { icon: "text-red-500",   value: "text-red-600 dark:text-red-400",   bg: "bg-red-50 dark:bg-red-950/20" },
    amber: { icon: "text-amber-500", value: "text-amber-600 dark:text-amber-400", bg: "bg-amber-50 dark:bg-amber-950/20" },
    blue:  { icon: "text-blue-500",  value: "text-blue-600 dark:text-blue-400",  bg: "bg-blue-50 dark:bg-blue-950/20" },
    gray:  { icon: "text-gray-400",  value: "text-gray-700 dark:text-gray-300",  bg: "bg-gray-50 dark:bg-gray-900" },
  };
  const colors = colorMap[highlight ?? "gray"];

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-3 rounded-lg border border-gray-200 dark:border-gray-700",
        "bg-white dark:bg-gray-900 shadow-sm",
        colors.bg
      )}
    >
      <div className={cn("flex-shrink-0", colors.icon)}>{icon}</div>
      <div>
        <div className={cn("text-xl font-bold leading-tight", colors.value)}>{value}</div>
        <div className="text-[10px] text-gray-500 dark:text-gray-400 font-medium">{label}</div>
      </div>
    </div>
  );
}

interface SignalStatsProps {
  /** Optional override — if provided, won't auto-fetch */
  stats?: SignalStatsType;
}

export function SignalStats({ stats: statsProp }: SignalStatsProps) {
  const [stats, setStats] = useState<SignalStatsType | null>(statsProp ?? null);

  const fetchStats = useCallback(async () => {
    if (statsProp) return;
    try {
      const s = await getSignalStats();
      setStats(s);
    } catch {
      // Silently fail — stats are non-critical
    }
  }, [statsProp]);

  useEffect(() => {
    fetchStats();
    if (!statsProp) {
      const interval = setInterval(fetchStats, 60_000);
      return () => clearInterval(interval);
    }
  }, [fetchStats, statsProp]);

  const totalUnread = stats?.total_unread ?? 0;
  const immediate = stats?.by_urgency?.immediate ?? 0;
  const nearTerm = stats?.by_urgency?.near_term ?? 0;
  const hotCompanies = stats?.hot_companies ?? 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <StatChip
        icon={<Bell className="w-4 h-4" />}
        value={totalUnread}
        label="Unread signals"
        highlight="blue"
      />
      <StatChip
        icon={<Zap className="w-4 h-4" />}
        value={immediate}
        label="Immediate (48h)"
        highlight={immediate > 0 ? "red" : "gray"}
      />
      <StatChip
        icon={<Clock className="w-4 h-4" />}
        value={nearTerm}
        label="Near-term (2wk)"
        highlight={nearTerm > 0 ? "amber" : "gray"}
      />
      <StatChip
        icon={<Building2 className="w-4 h-4" />}
        value={hotCompanies}
        label="Hot companies"
        highlight={hotCompanies > 0 ? "red" : "gray"}
      />
    </div>
  );
}
