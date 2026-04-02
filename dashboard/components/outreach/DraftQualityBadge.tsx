"use client";

/**
 * DraftQualityBadge — Compact quality score indicator for outreach drafts.
 *
 * Shows a color-coded badge (green >= 4.0, yellow >= 3.0, red < 3.0)
 * with a hover tooltip displaying per-dimension scores.
 */

import { useState, useRef } from "react";
import { Star, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { scoreDraft } from "@/lib/api";
import type { DraftQualityScore } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getBadgeClass(score: number | null): string {
  if (score === null) return "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400";
  if (score >= 4.0) return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300";
  if (score >= 3.0) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
}

function scoreLabel(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(1);
}

const DIMENSION_LABELS: Record<string, string> = {
  specificity:  "Specificity",
  relevance:    "Relevance",
  tone_match:   "Tone Match",
  cta_clarity:  "CTA Clarity",
};

function DimensionRow({ label, score }: { label: string; score: number }) {
  const dots = Array.from({ length: 5 }, (_, i) => i + 1);
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-gray-600 dark:text-gray-400 w-24 shrink-0">{label}</span>
      <div className="flex items-center gap-0.5">
        {dots.map((d) => (
          <span
            key={d}
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              d <= score
                ? "bg-indigo-500 dark:bg-indigo-400"
                : "bg-gray-200 dark:bg-gray-600"
            )}
          />
        ))}
      </div>
      <span className="text-xs font-medium text-gray-700 dark:text-gray-300 w-4 text-right">
        {score}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface DraftQualityBadgeProps {
  draftId: string;
  /** Pre-loaded score data — if not provided, a "Score" button is shown */
  initialScore?: DraftQualityScore | null;
  onScored?: (result: DraftQualityScore) => void;
}

// ---------------------------------------------------------------------------
// DraftQualityBadge
// ---------------------------------------------------------------------------

export default function DraftQualityBadge({
  draftId,
  initialScore = null,
  onScored,
}: DraftQualityBadgeProps) {
  const [scoring, setScoring] = useState(false);
  const [result, setResult] = useState<DraftQualityScore | null>(initialScore);
  const [error, setError] = useState<string | null>(null);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const handleScore = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setScoring(true);
    setError(null);
    try {
      const res = await scoreDraft(draftId);
      setResult(res);
      onScored?.(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scoring failed");
    } finally {
      setScoring(false);
    }
  };

  const overall = result?.overall ?? null;
  const badgeClass = getBadgeClass(overall);

  // No score yet — show Score button
  if (!result) {
    return (
      <button
        onClick={handleScore}
        disabled={scoring}
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
          "bg-gray-100 text-gray-500 hover:bg-gray-200 transition-colors",
          "dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600",
          "disabled:opacity-50 disabled:cursor-not-allowed"
        )}
        title={error || "Score this draft"}
      >
        {scoring ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Star className="h-3 w-3" />
        )}
        {scoring ? "Scoring..." : error ? "Retry" : "Score Draft"}
      </button>
    );
  }

  // Has score — show badge with hover tooltip
  return (
    <div className="relative inline-block">
      <button
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold",
          badgeClass,
          "cursor-pointer"
        )}
        onMouseEnter={() => setTooltipVisible(true)}
        onMouseLeave={() => setTooltipVisible(false)}
        onFocus={() => setTooltipVisible(true)}
        onBlur={() => setTooltipVisible(false)}
        onClick={(e) => { e.stopPropagation(); setTooltipVisible(!tooltipVisible); }}
        aria-label={`Quality score: ${scoreLabel(overall)} out of 5`}
      >
        <Star className="h-3 w-3" />
        {scoreLabel(overall)}
      </button>

      {tooltipVisible && (
        <div
          ref={tooltipRef}
          role="tooltip"
          className={cn(
            "absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50",
            "w-52 rounded-xl border border-gray-200 bg-white shadow-lg p-3",
            "dark:border-gray-700 dark:bg-gray-900"
          )}
        >
          <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
            Quality Breakdown
          </p>
          <div className="space-y-1.5">
            {Object.entries(result.scores).map(([key, val]) => (
              <DimensionRow
                key={key}
                label={DIMENSION_LABELS[key] ?? key}
                score={val}
              />
            ))}
          </div>
          {result.suggestions && result.suggestions.length > 0 && (
            <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Suggestions
              </p>
              <ul className="space-y-0.5">
                {result.suggestions.slice(0, 2).map((s, i) => (
                  <li key={i} className="text-xs text-gray-600 dark:text-gray-400">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {/* Tooltip arrow */}
          <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-px">
            <div className="border-4 border-transparent border-t-white dark:border-t-gray-900" />
          </div>
        </div>
      )}
    </div>
  );
}
