"use client";

/**
 * ClassificationBadge — Color-coded badge for HITL reply classifications.
 *
 * Usage:
 *   <ClassificationBadge intent="interested" confidence={0.92} />
 *   <ClassificationBadge intent="objection" showConfidence={false} />
 */

import { cn } from "@/lib/utils";

export type ClassificationIntent =
  | "interested"
  | "objection"
  | "referral"
  | "soft_no"
  | "out_of_office"
  | "unsubscribe"
  | "bounce"
  | "other";

interface ClassificationBadgeProps {
  intent: string;
  confidence?: number;
  showConfidence?: boolean;
  size?: "sm" | "md";
  className?: string;
}

const INTENT_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  interested: {
    label: "Interested",
    className:
      "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border-green-200 dark:border-green-800",
  },
  objection: {
    label: "Objection",
    className:
      "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800",
  },
  referral: {
    label: "Referral",
    className:
      "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300 border-sky-200 dark:border-sky-800",
  },
  soft_no: {
    label: "Soft No",
    className:
      "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-600",
  },
  out_of_office: {
    label: "OOO",
    className:
      "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-600",
  },
  unsubscribe: {
    label: "Unsubscribe",
    className:
      "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800",
  },
  bounce: {
    label: "Bounce",
    className:
      "bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400 border-red-100 dark:border-red-900",
  },
  other: {
    label: "Other",
    className:
      "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 border-gray-200 dark:border-gray-600",
  },
};

export function ClassificationBadge({
  intent,
  confidence,
  showConfidence = true,
  size = "sm",
  className,
}: ClassificationBadgeProps) {
  const config = INTENT_CONFIG[intent] ?? INTENT_CONFIG.other;
  const sizeClass = size === "md" ? "px-2 py-1 text-xs" : "px-1.5 py-0.5 text-[10px]";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border font-medium",
        sizeClass,
        config.className,
        className
      )}
    >
      {config.label}
      {showConfidence && confidence !== undefined && (
        <span className="opacity-70">{Math.round(confidence * 100)}%</span>
      )}
    </span>
  );
}

export function priorityLabel(priority: number): string {
  const map: Record<number, string> = { 1: "P1", 2: "P2", 3: "P3", 4: "P4", 5: "P5" };
  return map[priority] ?? `P${priority}`;
}

export function priorityBadgeClass(priority: number): string {
  if (priority <= 1) return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
  if (priority <= 2) return "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300";
  if (priority <= 3) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400";
}
