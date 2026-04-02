"use client";

/**
 * SignalCard — Reusable card for a single buying signal.
 * Displays signal type icon, urgency badge, title, description,
 * source, time, and Mark Read / Action buttons.
 */

import {
  Briefcase,
  DollarSign,
  Wrench,
  Newspaper,
  UserCheck,
  Building2,
  AlertTriangle,
  ClipboardList,
  Handshake,
  CheckCircle2,
  Eye,
  ExternalLink,
} from "lucide-react";
import { cn, formatTimeAgo } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CompanySignal {
  id: string;
  company_id: string;
  workspace_id: string;
  signal_type: string;
  urgency: string;
  title: string;
  description: string;
  source_url?: string | null;
  source_name: string;
  signal_score: number;
  is_read: boolean;
  is_actioned: boolean;
  actioned_at?: string | null;
  detected_at: string;
  expires_at?: string | null;
}

export interface SignalCardProps {
  signal: CompanySignal;
  showCompany?: boolean;
  companyName?: string;
  onRead: (id: string) => void;
  onAction: (id: string) => void;
  compact?: boolean;
}

// ─── Signal type metadata ─────────────────────────────────────────────────────

const SIGNAL_META: Record<string, { icon: React.ComponentType<{ className?: string }>; label: string }> = {
  job_posting:       { icon: Briefcase,      label: "Hiring" },
  funding:           { icon: DollarSign,     label: "Funding" },
  tech_change:       { icon: Wrench,         label: "Tech Change" },
  news_mention:      { icon: Newspaper,      label: "News" },
  leadership_change: { icon: UserCheck,      label: "Leadership" },
  expansion:         { icon: Building2,      label: "Expansion" },
  pain_signal:       { icon: AlertTriangle,  label: "Pain Signal" },
  regulatory:        { icon: ClipboardList,  label: "Regulatory" },
  partnership:       { icon: Handshake,      label: "Partnership" },
};

// ─── Urgency badge config ─────────────────────────────────────────────────────

const URGENCY_CONFIG: Record<string, { dot: string; badge: string; label: string }> = {
  immediate: {
    dot:   "bg-red-500",
    badge: "bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-400",
    label: "Immediate",
  },
  near_term: {
    dot:   "bg-amber-500",
    badge: "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
    label: "Near-term",
  },
  background: {
    dot:   "bg-gray-400",
    badge: "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400",
    label: "Background",
  },
};

// ─── Component ────────────────────────────────────────────────────────────────

export function SignalCard({
  signal,
  showCompany = false,
  companyName,
  onRead,
  onAction,
  compact = false,
}: SignalCardProps) {
  const meta = SIGNAL_META[signal.signal_type] ?? {
    icon: AlertTriangle,
    label: signal.signal_type,
  };
  const urgency = URGENCY_CONFIG[signal.urgency] ?? URGENCY_CONFIG.background;
  const Icon = meta.icon;

  const detectedAt = (() => {
    try {
      return formatTimeAgo(signal.detected_at);
    } catch {
      return "recently";
    }
  })();

  if (signal.is_actioned) {
    return null;
  }

  return (
    <div
      className={cn(
        "rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm",
        "hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-200",
        signal.is_read && "opacity-75",
        compact ? "p-3" : "p-4"
      )}
    >
      {/* Header row */}
      <div className="flex items-start gap-3 mb-2">
        {/* Type icon */}
        <div
          className={cn(
            "flex-shrink-0 rounded-md flex items-center justify-center",
            compact ? "w-7 h-7" : "w-8 h-8",
            signal.urgency === "immediate"
              ? "bg-red-50 dark:bg-red-950/30"
              : signal.urgency === "near_term"
              ? "bg-amber-50 dark:bg-amber-950/30"
              : "bg-gray-100 dark:bg-gray-800"
          )}
        >
          <Icon
            className={cn(
              compact ? "w-3.5 h-3.5" : "w-4 h-4",
              signal.urgency === "immediate"
                ? "text-red-500"
                : signal.urgency === "near_term"
                ? "text-amber-500"
                : "text-gray-400 dark:text-gray-500"
            )}
          />
        </div>

        {/* Title + urgency */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {showCompany && companyName && (
              <span className="text-xs font-semibold text-blue-600 dark:text-blue-400 truncate max-w-[120px]">
                {companyName}
              </span>
            )}
            <span
              className={cn(
                "font-semibold text-gray-900 dark:text-gray-100 leading-snug",
                compact ? "text-xs" : "text-sm"
              )}
            >
              {signal.title}
            </span>
          </div>
          {/* Meta row */}
          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
            {/* Urgency dot + label */}
            <span className={cn("flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full", urgency.badge)}>
              <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", urgency.dot)} />
              {urgency.label}
            </span>
            {/* Signal type */}
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
              {meta.label}
            </span>
            {/* Score */}
            <span className="text-[10px] text-gray-400 dark:text-gray-500">
              {Math.round(signal.signal_score * 100)}%
            </span>
          </div>
        </div>

        {/* Unread indicator */}
        {!signal.is_read && (
          <span className="flex-shrink-0 w-2 h-2 rounded-full bg-blue-500 mt-1" aria-label="Unread" />
        )}
      </div>

      {/* Description */}
      {!compact && signal.description && (
        <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed mb-3 line-clamp-2">
          {signal.description}
        </p>
      )}

      {/* Footer */}
      <div className={cn("flex items-center justify-between", compact ? "mt-2" : "mt-3")}>
        {/* Source + time */}
        <div className="flex items-center gap-2 text-[10px] text-gray-400 dark:text-gray-500">
          <span className="font-medium">{signal.source_name}</span>
          <span>·</span>
          <span>{detectedAt}</span>
          {signal.source_url && (
            <a
              href={signal.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-500 hover:text-blue-700 dark:hover:text-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-500 rounded"
              aria-label="Open source"
            >
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1">
          {!signal.is_read && (
            <button
              onClick={() => onRead(signal.id)}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500"
              aria-label="Mark read"
            >
              <Eye className="w-3 h-3" />
              {!compact && "Read"}
            </button>
          )}
          <button
            onClick={() => onAction(signal.id)}
            className="flex items-center gap-1 text-[10px] px-2 py-1 rounded text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label="Mark actioned"
          >
            <CheckCircle2 className="w-3 h-3" />
            {!compact && "Action"}
          </button>
        </div>
      </div>
    </div>
  );
}
