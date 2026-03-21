"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Building2, Mail, Zap, Loader2, RefreshCw, Clock } from "lucide-react";
import { getActivityFeed, Activity } from "@/lib/api";
import { formatTimeAgo } from "@/lib/utils";
import { cn } from "@/lib/utils";

type FilterTab = "all" | "status_change" | "outreach" | "agent_run";

const TABS: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "status_change", label: "Companies" },
  { key: "outreach", label: "Outreach" },
  { key: "agent_run", label: "Agent Runs" },
];

const TYPE_CONFIG: Record<
  string,
  {
    icon: React.ElementType;
    iconBg: string;
    iconColor: string;
    dotColor: string;
    badge: string;
    badgeColor: string;
  }
> = {
  status_change: {
    icon: Building2,
    iconBg: "bg-blue-50",
    iconColor: "text-blue-600",
    dotColor: "bg-blue-500",
    badge: "Company",
    badgeColor: "bg-blue-100 text-blue-700",
  },
  outreach: {
    icon: Mail,
    iconBg: "bg-purple-50",
    iconColor: "text-purple-600",
    dotColor: "bg-purple-500",
    badge: "Outreach",
    badgeColor: "bg-purple-100 text-purple-700",
  },
  agent_run: {
    icon: Zap,
    iconBg: "bg-green-50",
    iconColor: "text-green-600",
    dotColor: "bg-green-500",
    badge: "Agent",
    badgeColor: "bg-green-100 text-green-700",
  },
};

function fallbackConfig(type: string) {
  return (
    TYPE_CONFIG[type] ?? {
      icon: Clock,
      iconBg: "bg-gray-50",
      iconColor: "text-gray-500",
      dotColor: "bg-gray-400",
      badge: type,
      badgeColor: "bg-gray-100 text-gray-600",
    }
  );
}

const LOAD_STEP = 20;

export default function ActivityPage() {
  const [all, setAll] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState<FilterTab>("all");
  const [visibleCount, setVisibleCount] = useState(LOAD_STEP);

  const fetchData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const res = await getActivityFeed(100);
      setAll(res.data);
    } catch {
      // leave stale data on error
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => fetchData(), 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Filter by active tab
  const filtered =
    activeTab === "all" ? all : all.filter((a) => a.type === activeTab);

  const visible = filtered.slice(0, visibleCount);
  const hasMore = visibleCount < filtered.length;

  // Count per tab for badges
  const countFor = (key: FilterTab) =>
    key === "all" ? all.length : all.filter((a) => a.type === key).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Activity Feed</h2>
          <p className="mt-1 text-sm text-gray-500">
            Unified timeline of recent events across the system
          </p>
        </div>
        <button
          onClick={() => fetchData(true)}
          disabled={refreshing}
          className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 shadow-sm transition-colors hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw
            className={cn("h-4 w-4", refreshing && "animate-spin")}
          />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 rounded-xl border border-gray-200 bg-gray-50 p-1 w-fit">
        {TABS.map((tab) => {
          const count = countFor(tab.key);
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                setVisibleCount(LOAD_STEP);
              }}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              {tab.label}
              {count > 0 && (
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 text-xs font-semibold leading-none",
                    isActive
                      ? "bg-gray-100 text-gray-700"
                      : "bg-gray-200 text-gray-500"
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Timeline */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex h-48 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : visible.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-gray-400">
            <Clock className="h-8 w-8" />
            <p className="text-sm">No activity yet</p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {visible.map((activity, idx) => {
              const cfg = fallbackConfig(activity.type);
              const Icon = cfg.icon;

              const isCompanyLink =
                (activity.type === "status_change" ||
                  activity.type === "outreach") &&
                activity.entity_id;

              return (
                <li
                  key={`${activity.type}-${activity.entity_id}-${idx}`}
                  className="flex items-start gap-4 px-5 py-4 hover:bg-gray-50 transition-colors"
                >
                  {/* Icon */}
                  <div
                    className={cn(
                      "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                      cfg.iconBg
                    )}
                  >
                    <Icon className={cn("h-4 w-4", cfg.iconColor)} />
                  </div>

                  {/* Content */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Type badge */}
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          cfg.badgeColor
                        )}
                      >
                        {cfg.badge}
                      </span>

                      {/* Title — link for company/outreach events */}
                      {isCompanyLink ? (
                        <Link
                          href={`/prospects/${activity.entity_id}`}
                          className="text-sm font-semibold text-gray-900 hover:text-digitillis-accent hover:underline truncate"
                        >
                          {activity.title}
                        </Link>
                      ) : (
                        <span className="text-sm font-semibold text-gray-900 truncate">
                          {activity.title}
                        </span>
                      )}

                      {/* Tier pill */}
                      {activity.tier && (
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                          Tier {activity.tier}
                        </span>
                      )}
                    </div>

                    <p className="mt-0.5 text-sm text-gray-500 truncate">
                      {activity.description}
                    </p>
                  </div>

                  {/* Timestamp */}
                  <time
                    className="mt-0.5 shrink-0 text-xs text-gray-400"
                    title={activity.timestamp}
                  >
                    {formatTimeAgo(activity.timestamp)}
                  </time>
                </li>
              );
            })}
          </ul>
        )}

        {/* Load more */}
        {!loading && hasMore && (
          <div className="border-t border-gray-100 px-5 py-3">
            <button
              onClick={() => setVisibleCount((v) => v + LOAD_STEP)}
              className="w-full rounded-lg py-2 text-sm font-medium text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-700"
            >
              Load more ({filtered.length - visibleCount} remaining)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
