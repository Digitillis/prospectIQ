"use client";

/**
 * TriggerCard — displays a single buying trigger event.
 *
 * Urgency colors: immediate=red, near_term=amber, background=gray
 * Type icons:     growth=TrendingUp, pain=AlertTriangle, tech=Cpu, timing=Clock
 */

import { useState } from "react";
import { TrendingUp, AlertTriangle, Cpu, Clock, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TriggerEvent {
  trigger_type: string;    // growth | pain | tech | timing
  description: string;
  urgency: string;         // immediate | near_term | background
  confidence: number;
  source_text: string;
  priority_rank: number;
}

interface TriggerCardProps {
  trigger: TriggerEvent;
  companyName?: string;
  showCompany?: boolean;
  compact?: boolean;
}

const URGENCY_STYLES: Record<string, { badge: string; dot: string; label: string }> = {
  immediate: {
    badge: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800",
    dot: "bg-red-500",
    label: "Immediate",
  },
  near_term: {
    badge: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800",
    dot: "bg-amber-500",
    label: "Near Term",
  },
  background: {
    badge: "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-700",
    dot: "bg-zinc-400",
    label: "Background",
  },
};

const TYPE_CONFIG: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  growth: {
    icon: <TrendingUp className="w-3.5 h-3.5" />,
    color: "text-emerald-600 dark:text-emerald-400",
    label: "Growth",
  },
  pain: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: "text-rose-600 dark:text-rose-400",
    label: "Pain",
  },
  tech: {
    icon: <Cpu className="w-3.5 h-3.5" />,
    color: "text-blue-600 dark:text-blue-400",
    label: "Tech",
  },
  timing: {
    icon: <Clock className="w-3.5 h-3.5" />,
    color: "text-violet-600 dark:text-violet-400",
    label: "Timing",
  },
};

export function TriggerCard({
  trigger,
  companyName,
  showCompany = false,
  compact = false,
}: TriggerCardProps) {
  const [expanded, setExpanded] = useState(false);

  const urgencyStyle = URGENCY_STYLES[trigger.urgency] || URGENCY_STYLES.background;
  const typeConfig = TYPE_CONFIG[trigger.trigger_type] || TYPE_CONFIG.tech;
  const hasSourceText = trigger.source_text && trigger.source_text.length > 0;

  if (compact) {
    return (
      <div className="flex items-start gap-2.5 py-2">
        <div className={cn("mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0", urgencyStyle.dot)} />
        <div className="flex-1 min-w-0">
          <p className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">
            {trigger.description}
          </p>
          {showCompany && companyName && (
            <p className="text-[10px] text-zinc-400 mt-0.5">{companyName}</p>
          )}
        </div>
        <span className={cn("flex-shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded-full border", urgencyStyle.badge)}>
          {urgencyStyle.label}
        </span>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 flex items-start gap-3">
        {/* Type icon */}
        <div className={cn("mt-0.5 flex-shrink-0", typeConfig.color)}>
          {typeConfig.icon}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {showCompany && companyName && (
            <p className="text-[11px] font-medium text-zinc-500 dark:text-zinc-400 mb-0.5 uppercase tracking-wide">
              {companyName}
            </p>
          )}
          <p className="text-sm text-zinc-800 dark:text-zinc-200 leading-relaxed">
            {trigger.description}
          </p>

          {/* Metadata row */}
          <div className="flex items-center gap-2 mt-2">
            <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded-full border", urgencyStyle.badge)}>
              {urgencyStyle.label}
            </span>
            <span className="text-[10px] text-zinc-400 capitalize">
              {typeConfig.label}
            </span>
            {trigger.confidence > 0 && (
              <span className="text-[10px] text-zinc-400">
                {Math.round(trigger.confidence * 100)}% confident
              </span>
            )}
            {trigger.priority_rank > 0 && (
              <span className="text-[10px] text-zinc-400">
                #{trigger.priority_rank}
              </span>
            )}
          </div>
        </div>

        {/* Expand toggle (only if source text exists) */}
        {hasSourceText && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="flex-shrink-0 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        )}
      </div>

      {/* Source text (expanded) */}
      {expanded && hasSourceText && (
        <div className="px-4 pb-3 border-t border-zinc-100 dark:border-zinc-800">
          <p className="text-[11px] text-zinc-500 dark:text-zinc-400 italic mt-2 leading-relaxed">
            "{trigger.source_text}"
          </p>
        </div>
      )}
    </div>
  );
}
