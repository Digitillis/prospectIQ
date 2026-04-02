"use client";

/**
 * ReadinessScore — colored progress bar with breakdown tooltip.
 *
 * Usage:
 *   <ReadinessScore score={82} breakdown={{ research: 25, contacts: 20, triggers: 22, hooks: 15 }} />
 */

import { useState } from "react";
import { cn } from "@/lib/utils";

interface ReadinessScoreProps {
  score: number;
  breakdown?: Record<string, number>;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}

function scoreColor(score: number): string {
  if (score >= 76) return "bg-green-500";
  if (score >= 51) return "bg-blue-500";
  if (score >= 26) return "bg-amber-400";
  return "bg-zinc-400";
}

function scoreBadgeColor(score: number): string {
  if (score >= 76) return "text-green-700 dark:text-green-400";
  if (score >= 51) return "text-blue-700 dark:text-blue-400";
  if (score >= 26) return "text-amber-700 dark:text-amber-400";
  return "text-zinc-500 dark:text-zinc-400";
}

function scoreLabel(score: number): string {
  if (score >= 91) return "Excellent";
  if (score >= 76) return "Ready";
  if (score >= 51) return "Good";
  if (score >= 26) return "Fair";
  if (score > 0) return "Minimal";
  return "Not Run";
}

export function ReadinessScore({
  score,
  breakdown,
  size = "md",
  showLabel = true,
}: ReadinessScoreProps) {
  const [showTooltip, setShowTooltip] = useState(false);

  const barHeight = size === "sm" ? "h-1.5" : size === "lg" ? "h-3" : "h-2";
  const textSize = size === "sm" ? "text-xs" : size === "lg" ? "text-base" : "text-sm";

  const hasBreakdown = breakdown && Object.keys(breakdown).length > 0;

  return (
    <div
      className="relative w-full"
      onMouseEnter={() => hasBreakdown && setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {/* Score number + label */}
      {showLabel && (
        <div className="flex items-center justify-between mb-1">
          <span className={cn("font-semibold", textSize, scoreBadgeColor(score))}>
            {score}/100
          </span>
          <span className={cn("font-medium", size === "sm" ? "text-[10px]" : "text-xs", "text-zinc-400")}>
            {scoreLabel(score)}
          </span>
        </div>
      )}

      {/* Progress bar */}
      <div className={cn("w-full bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden", barHeight)}>
        <div
          className={cn("h-full rounded-full transition-all duration-500", scoreColor(score))}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>

      {/* Breakdown tooltip */}
      {showTooltip && hasBreakdown && (
        <div className="absolute bottom-full mb-2 left-0 z-50 w-48 bg-zinc-900 dark:bg-zinc-800 text-white rounded-lg shadow-xl p-3 text-xs">
          <div className="font-semibold mb-2 text-zinc-200">Score Breakdown</div>
          {Object.entries(breakdown!).map(([key, val]) => (
            <div key={key} className="flex justify-between items-center mb-1">
              <span className="capitalize text-zinc-300">{key}</span>
              <span className="font-semibold text-white">+{val}</span>
            </div>
          ))}
          <div className="border-t border-zinc-700 mt-2 pt-2 flex justify-between font-semibold">
            <span className="text-zinc-300">Total</span>
            <span className="text-white">{score}</span>
          </div>
          {/* Tooltip arrow */}
          <div className="absolute top-full left-4 w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-zinc-900 dark:border-t-zinc-800" />
        </div>
      )}
    </div>
  );
}
