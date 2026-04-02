// Copyright © 2026 ProspectIQ. All rights reserved.
// Authors: Avanish Mehrotra & ProspectIQ Technical Team
"use client";

/**
 * Voice of Prospect — reply corpus intelligence report.
 *
 * Surfaces what messaging resonates, what objections repeat,
 * which personas engage most, and where sequences drop off.
 */

import { useEffect, useState, useCallback } from "react";
import {
  MessageSquare,
  RefreshCw,
  Loader2,
  TrendingUp,
  AlertTriangle,
  Users,
  GitBranch,
  Sparkles,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MessagingTheme {
  theme: string;
  frequency: number;
  sentiment: "positive" | "negative" | "neutral";
  example_quote: string;
}

interface PersonaEngagement {
  persona_type: string;
  reply_count: number;
  reply_rate: number;
  avg_intent_score: number;
}

interface SequenceStepMetrics {
  step_number: number;
  step_type: "email" | "linkedin";
  sends: number;
  replies: number;
  reply_rate: number;
  avg_days_to_reply: number;
  drop_off: boolean;
}

interface VoiceInsights {
  workspace_id: string;
  analysed_at: string;
  total_replies_analysed: number;
  data_quality: "rich" | "moderate" | "limited" | "demo";
  resonance_themes: MessagingTheme[];
  objection_themes: MessagingTheme[];
  top_performing_angle: string;
  top_objection: string;
  recommended_adjustment: string;
  persona_engagement: PersonaEngagement[];
  sequence_dropoff: SequenceStepMetrics[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function qualityBadge(quality: string) {
  const map: Record<string, { label: string; cls: string }> = {
    rich: { label: "Rich data", cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400" },
    moderate: { label: "Moderate data", cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" },
    limited: { label: "Limited data", cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" },
    demo: { label: "Demo data", cls: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-400" },
  };
  const d = map[quality] ?? map.demo;
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", d.cls)}>
      {d.label}
    </span>
  );
}

function pct(rate: number) {
  return `${Math.round(rate * 100)}%`;
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ThemeCard({
  theme,
  variant,
}: {
  theme: MessagingTheme;
  variant: "resonance" | "objection";
}) {
  const borderCls =
    variant === "resonance"
      ? "border-l-green-400 dark:border-l-green-500"
      : "border-l-red-400 dark:border-l-red-500";

  return (
    <div
      className={cn(
        "rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 border-l-4",
        borderCls
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug">
          {theme.theme}
        </span>
        <span className="shrink-0 rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs font-semibold text-gray-600 dark:text-gray-400">
          {theme.frequency}×
        </span>
      </div>
      {theme.example_quote && (
        <p className="mt-2 text-xs italic text-gray-500 dark:text-gray-400 leading-relaxed">
          &ldquo;{theme.example_quote}&rdquo;
        </p>
      )}
    </div>
  );
}

function PersonaRow({
  persona,
  isTop,
  maxRate,
}: {
  persona: PersonaEngagement;
  isTop: boolean;
  maxRate: number;
}) {
  const barWidth = maxRate > 0 ? Math.round((persona.reply_rate / maxRate) * 100) : 0;

  return (
    <tr
      className={cn(
        "border-b border-gray-100 dark:border-gray-800 last:border-b-0",
        isTop && "bg-green-50 dark:bg-green-900/10"
      )}
    >
      <td className="py-3 pl-4 pr-3 text-sm">
        <div className="flex items-center gap-2">
          {isTop && (
            <span className="text-[10px] font-semibold text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/30 rounded-full px-2 py-0.5">
              Best
            </span>
          )}
          <span className="font-medium text-gray-900 dark:text-gray-100">
            {persona.persona_type}
          </span>
        </div>
      </td>
      <td className="py-3 px-3 text-sm text-center text-gray-600 dark:text-gray-400">
        {persona.reply_count}
      </td>
      <td className="py-3 px-3 min-w-[140px]">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full"
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <span className="text-xs text-gray-600 dark:text-gray-400 w-9 text-right shrink-0">
            {pct(persona.reply_rate)}
          </span>
        </div>
      </td>
      <td className="py-3 px-3 text-sm text-center text-gray-600 dark:text-gray-400">
        {persona.avg_intent_score.toFixed(1)}
      </td>
    </tr>
  );
}

function StepFunnelBlock({
  step,
  maxRate,
}: {
  step: SequenceStepMetrics;
  maxRate: number;
}) {
  const widthPct = maxRate > 0 ? Math.max(8, Math.round((step.reply_rate / maxRate) * 100)) : 8;
  return (
    <div className="flex flex-col items-center gap-1 min-w-0 flex-1">
      <div
        className={cn(
          "w-full rounded-lg flex flex-col items-center justify-center py-3 px-2 text-center transition-all",
          step.drop_off
            ? "bg-amber-100 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-600"
            : "bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700"
        )}
        style={{ minHeight: `${Math.max(48, widthPct * 1.2)}px` }}
      >
        <span
          className={cn(
            "text-xs font-semibold",
            step.drop_off
              ? "text-amber-700 dark:text-amber-400"
              : "text-blue-700 dark:text-blue-300"
          )}
        >
          Step {step.step_number}
        </span>
        <span className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5 capitalize">
          {step.step_type}
        </span>
        <span
          className={cn(
            "mt-1 text-sm font-bold",
            step.drop_off
              ? "text-amber-700 dark:text-amber-300"
              : "text-blue-600 dark:text-blue-400"
          )}
        >
          {pct(step.reply_rate)}
        </span>
        {step.drop_off && (
          <span className="mt-1 text-[10px] font-medium text-amber-600 dark:text-amber-400 flex items-center gap-0.5">
            <AlertTriangle className="h-3 w-3" />
            Drop-off
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function VoiceOfProspectPage() {
  const [insights, setInsights] = useState<VoiceInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInsights = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/voice-of-prospect/insights`);
      if (res.status === 204) {
        // No cached snapshot — auto-trigger first analysis
        await runAnalysis(false);
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setInsights(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load insights");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const runAnalysis = useCallback(async (withLoadingState = true) => {
    if (withLoadingState) setAnalysing(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/voice-of-prospect/analyse`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setInsights(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalysing(false);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInsights();
  }, [loadInsights]);

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const maxPersonaRate =
    insights?.persona_engagement?.length
      ? Math.max(...insights.persona_engagement.map((p) => p.reply_rate))
      : 1;

  const maxStepRate =
    insights?.sequence_dropoff?.length
      ? Math.max(...insights.sequence_dropoff.map((s) => s.reply_rate))
      : 1;

  return (
    <div className="min-h-full bg-gray-50 dark:bg-gray-950 p-6 space-y-6">
      {/* ------------------------------------------------------------------ */}
      {/* Header */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600">
            <MessageSquare className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              Voice of Prospect
            </h1>
            {insights && (
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Last analysed {fmtDate(insights.analysed_at)} &middot;{" "}
                {insights.total_replies_analysed} replies
              </p>
            )}
          </div>
          {insights && <div className="ml-2">{qualityBadge(insights.data_quality)}</div>}
        </div>

        <button
          onClick={() => runAnalysis(true)}
          disabled={analysing}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
        >
          {analysing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          {analysing ? "Analysing…" : "Analyse Now"}
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {insights && (
        <>
          {/* --------------------------------------------------------------- */}
          {/* Section 1 — Resonating vs Blocking */}
          {/* --------------------------------------------------------------- */}
          <section>
            <div className="mb-3 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-gray-400" />
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                What's Resonating vs What's Blocking
              </h2>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Resonating */}
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-green-400" />
                  <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                    Resonating
                  </span>
                </div>
                <div className="space-y-2">
                  {insights.resonance_themes.length > 0 ? (
                    insights.resonance_themes.map((t, i) => (
                      <ThemeCard key={i} theme={t} variant="resonance" />
                    ))
                  ) : (
                    <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                      No resonance themes detected yet.
                    </p>
                  )}
                </div>
              </div>

              {/* Blocking */}
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                    Blocking
                  </span>
                </div>
                <div className="space-y-2">
                  {insights.objection_themes.length > 0 ? (
                    insights.objection_themes.map((t, i) => (
                      <ThemeCard key={i} theme={t} variant="objection" />
                    ))
                  ) : (
                    <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                      No objection themes detected yet.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* --------------------------------------------------------------- */}
          {/* Section 2 — ARIA Recommendation */}
          {/* --------------------------------------------------------------- */}
          {(insights.top_performing_angle || insights.recommended_adjustment) && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-gray-400" />
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  ARIA Recommendation
                </h2>
              </div>

              <div className="rounded-xl border-2 border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-900/10 p-5 space-y-3">
                {insights.top_performing_angle && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-400 mb-1">
                      Top Performing Angle
                    </p>
                    <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-snug">
                      {insights.top_performing_angle}
                    </p>
                  </div>
                )}

                {insights.top_objection && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Top Objection
                    </span>
                    <span className="rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 px-2.5 py-0.5 text-xs font-medium">
                      {insights.top_objection}
                    </span>
                  </div>
                )}

                {insights.recommended_adjustment && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1.5">
                      Recommended Adjustment
                    </p>
                    <div className="flex items-start gap-2">
                      <ChevronRight className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                      <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                        {insights.recommended_adjustment}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* --------------------------------------------------------------- */}
          {/* Section 3 — Persona Engagement */}
          {/* --------------------------------------------------------------- */}
          {insights.persona_engagement.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Users className="h-4 w-4 text-gray-400" />
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Persona Engagement
                </h2>
              </div>

              <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50/80 dark:bg-gray-800/60">
                      <th className="py-2.5 pl-4 pr-3 text-xs font-semibold text-gray-500 dark:text-gray-400">
                        Persona
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 text-center">
                        Replies
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 min-w-[160px]">
                        Reply Rate
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 text-center">
                        Avg Intent
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {insights.persona_engagement.map((p, i) => (
                      <PersonaRow
                        key={p.persona_type}
                        persona={p}
                        isTop={i === 0}
                        maxRate={maxPersonaRate}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* --------------------------------------------------------------- */}
          {/* Section 4 — Sequence Drop-off */}
          {/* --------------------------------------------------------------- */}
          {insights.sequence_dropoff.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-gray-400" />
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Sequence Drop-off
                </h2>
              </div>

              {/* Funnel visual */}
              <div className="mb-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
                <div className="flex items-end gap-2">
                  {insights.sequence_dropoff.map((step, i) => (
                    <div key={step.step_number} className="flex items-center gap-2 flex-1 min-w-0">
                      <StepFunnelBlock step={step} maxRate={maxStepRate} />
                      {i < insights.sequence_dropoff.length - 1 && (
                        <ChevronRight className="h-4 w-4 text-gray-300 dark:text-gray-600 shrink-0" />
                      )}
                    </div>
                  ))}
                </div>

                {insights.sequence_dropoff.some((s) => s.drop_off) && (
                  <div className="mt-3 flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    Drop-off detected — reply rate fell by more than 50% compared to prior step.
                  </div>
                )}
              </div>

              {/* Step detail table */}
              <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50/80 dark:bg-gray-800/60">
                      <th className="py-2.5 pl-4 pr-3 text-xs font-semibold text-gray-500 dark:text-gray-400">
                        Step
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400">
                        Type
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 text-right">
                        Sends
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 text-right">
                        Replies
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 text-right">
                        Reply Rate
                      </th>
                      <th className="py-2.5 px-3 text-xs font-semibold text-gray-500 dark:text-gray-400 text-right">
                        Avg Days
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {insights.sequence_dropoff.map((step) => (
                      <tr
                        key={step.step_number}
                        className={cn(
                          "border-b border-gray-100 dark:border-gray-800 last:border-b-0",
                          step.drop_off && "bg-amber-50/60 dark:bg-amber-900/10"
                        )}
                      >
                        <td className="py-3 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-gray-100">
                          {step.drop_off ? (
                            <span className="flex items-center gap-1.5">
                              Step {step.step_number}
                              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                            </span>
                          ) : (
                            `Step ${step.step_number}`
                          )}
                        </td>
                        <td className="py-3 px-3 text-sm capitalize text-gray-600 dark:text-gray-400">
                          {step.step_type}
                        </td>
                        <td className="py-3 px-3 text-sm text-right text-gray-600 dark:text-gray-400">
                          {step.sends.toLocaleString()}
                        </td>
                        <td className="py-3 px-3 text-sm text-right text-gray-600 dark:text-gray-400">
                          {step.replies.toLocaleString()}
                        </td>
                        <td className="py-3 px-3 text-sm text-right font-semibold text-gray-900 dark:text-gray-100">
                          {pct(step.reply_rate)}
                        </td>
                        <td className="py-3 px-3 text-sm text-right text-gray-600 dark:text-gray-400">
                          {step.avg_days_to_reply.toFixed(1)}d
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
