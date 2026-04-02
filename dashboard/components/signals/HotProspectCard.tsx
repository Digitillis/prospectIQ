"use client";

/**
 * HotProspectCard — Company-level card showing aggregated signal summary.
 * Displays cluster badge, urgency indicators, signal count chips,
 * composite score bar, and action buttons.
 */

import { ArrowRight, PenLine, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { cn, formatTimeAgo } from "@/lib/utils";
import type { CompanySignal } from "./SignalCard";
import { SignalCard } from "./SignalCard";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SignalSummary {
  company_id: string;
  company_name: string;
  cluster: string;
  total_signals: number;
  unread_signals: number;
  max_urgency: string;
  composite_score: number;
  latest_signal_at: string;
  signals: CompanySignal[];
}

export interface HotProspectCardProps {
  summary: SignalSummary;
  onViewSignals: (companyId: string) => void;
  onGenerateDraft: (companyId: string) => void;
  onSignalRead: (signalId: string) => void;
  onSignalAction: (signalId: string) => void;
}

// ─── Cluster badge color map ──────────────────────────────────────────────────

const CLUSTER_COLORS: Record<string, string> = {
  machinery:           "bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400",
  automotive:          "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
  auto:                "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
  chemicals:           "bg-purple-100 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400",
  metals:              "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400",
  "food_and_beverage": "bg-green-100 dark:bg-green-950/40 text-green-700 dark:text-green-400",
  fb:                  "bg-green-100 dark:bg-green-950/40 text-green-700 dark:text-green-400",
  process:             "bg-teal-100 dark:bg-teal-950/40 text-teal-700 dark:text-teal-400",
};

function clusterColor(cluster: string): string {
  const key = cluster.toLowerCase().replace(/\s+/g, "_");
  for (const [pattern, color] of Object.entries(CLUSTER_COLORS)) {
    if (key.includes(pattern)) return color;
  }
  return "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400";
}

// ─── Urgency dot config ───────────────────────────────────────────────────────

const URGENCY_DOT: Record<string, string> = {
  immediate:  "bg-red-500",
  near_term:  "bg-amber-500",
  background: "bg-gray-400",
};

// ─── Component ────────────────────────────────────────────────────────────────

export function HotProspectCard({
  summary,
  onViewSignals,
  onGenerateDraft,
  onSignalRead,
  onSignalAction,
}: HotProspectCardProps) {
  const [expanded, setExpanded] = useState(false);

  const latestAt = (() => {
    try {
      return formatTimeAgo(summary.latest_signal_at);
    } catch {
      return "recently";
    }
  })();

  // Count signals by urgency
  const immediateCount = summary.signals.filter((s) => s.urgency === "immediate").length;
  const nearTermCount = summary.signals.filter((s) => s.urgency === "near_term").length;
  const backgroundCount = summary.signals.filter((s) => s.urgency === "background").length;

  // Score bar color
  const scoreColor =
    summary.composite_score >= 2
      ? "bg-green-500"
      : summary.composite_score >= 1
      ? "bg-amber-500"
      : "bg-gray-400";

  // Normalize composite score to 0–100% for the bar (cap at 5.0 = 100%)
  const scoreBarWidth = Math.min(100, (summary.composite_score / 5) * 100);

  // Top signal for preview
  const topSignal = summary.signals.find((s) => s.urgency === "immediate")
    ?? summary.signals.find((s) => s.urgency === "near_term")
    ?? summary.signals[0];

  const urgencyDot = URGENCY_DOT[summary.max_urgency] ?? URGENCY_DOT.background;

  return (
    <div
      className={cn(
        "rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm",
        "hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-200",
        "flex flex-col"
      )}
    >
      {/* Card body */}
      <div className="p-4 flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-start gap-2">
          {/* Avatar */}
          <div className="w-9 h-9 rounded-lg bg-blue-100 dark:bg-blue-950/40 flex items-center justify-center flex-shrink-0">
            <span className="text-sm font-bold text-blue-600 dark:text-blue-400">
              {(summary.company_name || "?")[0].toUpperCase()}
            </span>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {/* Urgency dot */}
              <span className={cn("w-2 h-2 rounded-full flex-shrink-0", urgencyDot)} aria-hidden="true" />
              {/* Company name */}
              <span className="font-semibold text-sm text-gray-900 dark:text-gray-100 truncate">
                {summary.company_name}
              </span>
            </div>
            <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
              {/* Cluster badge */}
              <span
                className={cn(
                  "text-[10px] font-medium px-2 py-0.5 rounded-full",
                  clusterColor(summary.cluster)
                )}
              >
                {summary.cluster.replace(/_/g, " ")}
              </span>
              {/* Updated time */}
              <span className="text-[10px] text-gray-400 dark:text-gray-500">{latestAt}</span>
            </div>
          </div>

          {/* Unread count */}
          {summary.unread_signals > 0 && (
            <span className="flex-shrink-0 rounded-full bg-blue-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
              {summary.unread_signals}
            </span>
          )}
        </div>

        {/* Signal count chips */}
        <div className="flex flex-wrap gap-1.5">
          {immediateCount > 0 && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-400">
              {immediateCount} immediate
            </span>
          )}
          {nearTermCount > 0 && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400">
              {nearTermCount} near-term
            </span>
          )}
          {backgroundCount > 0 && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
              {backgroundCount} background
            </span>
          )}
        </div>

        {/* Latest signal preview */}
        {topSignal && (
          <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed line-clamp-1">
            <span className="font-medium text-gray-700 dark:text-gray-300">Latest: </span>
            {topSignal.title}
          </p>
        )}

        {/* Composite score bar */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-gray-400 dark:text-gray-500">Signal strength</span>
            <span className="text-[10px] font-semibold text-gray-700 dark:text-gray-300">
              {summary.composite_score.toFixed(1)}
            </span>
          </div>
          <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all", scoreColor)}
              style={{ width: `${scoreBarWidth}%` }}
            />
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex-1 flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse signals" : "View signals"}
          >
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {expanded ? "Collapse" : `View ${summary.total_signals} signal${summary.total_signals === 1 ? "" : "s"}`}
          </button>
          <button
            onClick={() => onGenerateDraft(summary.company_id)}
            className="flex-1 flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Generate outreach draft"
          >
            <PenLine className="w-3.5 h-3.5" />
            Draft
          </button>
          <button
            onClick={() => onViewSignals(summary.company_id)}
            className="p-1.5 rounded-md border border-gray-200 dark:border-gray-700 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="View company profile"
          >
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Expanded signals list */}
      {expanded && summary.signals.length > 0 && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-3 flex flex-col gap-2">
          {summary.signals.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              compact
              onRead={onSignalRead}
              onAction={onSignalAction}
            />
          ))}
        </div>
      )}
    </div>
  );
}
