"use client";

/**
 * IntelligenceCard — Personalization intelligence display for a contact.
 *
 * Shows persona badge, personalization hooks, pain signals, trigger events,
 * research freshness, and a "Generate Draft" action button.
 */

import { useState } from "react";
import Link from "next/link";
import {
  Zap, Tag, AlertTriangle, Clock, Loader2, CheckCircle2, User,
  ChevronDown, ChevronUp, Copy, Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { generateOutreachDraft } from "@/lib/api";
import type { IntelligenceData } from "@/lib/api";

// ---------------------------------------------------------------------------
// Persona badge config
// ---------------------------------------------------------------------------

const PERSONA_CONFIG: Record<string, { label: string; color: string }> = {
  vp_ops:        { label: "VP Operations",   color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  plant_manager: { label: "Plant Manager",   color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  engineer:      { label: "Engineer",        color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300" },
  procurement:   { label: "Procurement",     color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300" },
  executive:     { label: "Executive",       color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  default:       { label: "Manufacturing",   color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
};

function getPersonaConfig(personaType: string) {
  return PERSONA_CONFIG[personaType] ?? PERSONA_CONFIG.default;
}

// ---------------------------------------------------------------------------
// CopyChip — hook chip with click-to-copy
// ---------------------------------------------------------------------------

function CopyChip({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API not available
    }
  };

  return (
    <button
      onClick={handleCopy}
      title="Click to copy"
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium",
        "bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors",
        "dark:bg-indigo-900/20 dark:text-indigo-300 dark:hover:bg-indigo-900/40",
        "max-w-[220px] truncate cursor-pointer"
      )}
    >
      {copied ? (
        <Check className="h-3 w-3 shrink-0 text-green-500" />
      ) : (
        <Copy className="h-3 w-3 shrink-0 opacity-50" />
      )}
      <span className="truncate">{text}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Research freshness
// ---------------------------------------------------------------------------

function researchFreshnessDays(updatedAt?: string | null): number | null {
  if (!updatedAt) return null;
  const then = new Date(updatedAt).getTime();
  const now = Date.now();
  return Math.floor((now - then) / (1000 * 60 * 60 * 24));
}

function FreshnessBadge({ days }: { days: number | null }) {
  if (days === null) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
        <Clock className="h-3 w-3" />
        No research date
      </span>
    );
  }
  const color =
    days <= 14
      ? "text-green-600 dark:text-green-400"
      : days <= 60
      ? "text-amber-600 dark:text-amber-400"
      : "text-red-500 dark:text-red-400";

  return (
    <span className={cn("inline-flex items-center gap-1 text-xs", color)}>
      <Clock className="h-3 w-3" />
      Research {days === 0 ? "today" : `${days}d ago`}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface IntelligenceCardProps {
  contactId: string;
  intelligence: IntelligenceData;
  compact?: boolean;
  onDraftCreated?: (draftId: string, subject: string) => void;
}

// ---------------------------------------------------------------------------
// IntelligenceCard
// ---------------------------------------------------------------------------

export default function IntelligenceCard({
  contactId,
  intelligence,
  compact = false,
  onDraftCreated,
}: IntelligenceCardProps) {
  const [generating, setGenerating] = useState(false);
  const [generatedSubject, setGeneratedSubject] = useState<string | null>(null);
  const [generatedDraftId, setGeneratedDraftId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(!compact);

  const {
    contact,
    company,
    personalization_hooks,
    pain_signals,
    trigger_events,
    persona_type,
    recommended_hooks,
  } = intelligence;

  const personaConfig = getPersonaConfig(persona_type);
  const freshnessDays = researchFreshnessDays(company.research_updated_at);
  const triggerCount = trigger_events?.length ?? 0;

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await generateOutreachDraft(
        company.id,
        contactId,
        "touch_1"
      );
      const draft = res.data;
      setGeneratedSubject(draft.subject ?? "Draft created");
      setGeneratedDraftId(draft.id ?? null);
      if (onDraftCreated && draft.id) {
        onDraftCreated(draft.id, draft.subject ?? "");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate draft");
    } finally {
      setGenerating(false);
    }
  };

  if (compact && !expanded) {
    return (
      <div className="flex items-center gap-2">
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", personaConfig.color)}>
          {personaConfig.label}
        </span>
        {triggerCount > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
            <Zap className="h-3 w-3" />
            {triggerCount} trigger{triggerCount !== 1 ? "s" : ""}
          </span>
        )}
        <button
          onClick={() => setExpanded(true)}
          className="ml-auto text-xs text-indigo-600 hover:text-indigo-800 dark:text-indigo-400"
        >
          View intel <ChevronDown className="inline h-3 w-3" />
        </button>
      </div>
    );
  }

  return (
    <div className={cn(
      "rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900",
      compact && "text-sm"
    )}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2 flex-wrap">
          <User className="h-4 w-4 text-gray-400 shrink-0" />
          <span className="font-medium text-gray-900 dark:text-gray-100 text-sm truncate max-w-[160px]">
            {contact.full_name || "Contact"}
          </span>
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", personaConfig.color)}>
            {personaConfig.label}
          </span>
          {triggerCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
              <Zap className="h-3 w-3" />
              {triggerCount} trigger{triggerCount !== 1 ? "s" : ""} — hot lead
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <FreshnessBadge days={freshnessDays} />
          {compact && (
            <button
              onClick={() => setExpanded(false)}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Personalization Hooks */}
        {personalization_hooks && personalization_hooks.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
              Personalization Hooks
            </p>
            <div className="flex flex-wrap gap-1.5">
              {personalization_hooks.slice(0, 3).map((hook, i) => (
                <CopyChip key={i} text={hook} />
              ))}
            </div>
          </div>
        )}

        {/* Pain Signals */}
        {pain_signals && pain_signals.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
              Pain Signals
            </p>
            <div className="flex flex-wrap gap-1.5">
              {pain_signals.slice(0, 4).map((pain, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs text-red-700 dark:bg-red-900/20 dark:text-red-300"
                >
                  <AlertTriangle className="h-3 w-3 shrink-0" />
                  <span className="truncate max-w-[180px]">{pain}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Trigger Events */}
        {trigger_events && trigger_events.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
              Trigger Events
            </p>
            <div className="space-y-1.5">
              {trigger_events.slice(0, 3).map((te, i) => {
                const desc = te.description || te.type || "";
                const relevance = te.outreach_relevance || "";
                const date = te.date_approx || "";
                return (
                  <div
                    key={i}
                    className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 dark:bg-amber-900/10 dark:border-amber-800/30"
                  >
                    <p className="text-xs font-medium text-amber-800 dark:text-amber-300 flex items-start gap-1">
                      <Zap className="h-3 w-3 mt-0.5 shrink-0" />
                      <span>{desc}{date ? ` (${date})` : ""}</span>
                    </p>
                    {relevance && (
                      <p className="mt-0.5 text-xs text-amber-700/80 dark:text-amber-400/80 pl-4">
                        {relevance}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recommended hooks */}
        {recommended_hooks && recommended_hooks.length > 0 && !personalization_hooks?.length && !trigger_events?.length && (
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
              Recommended Hooks
            </p>
            <div className="flex flex-wrap gap-1.5">
              {recommended_hooks.slice(0, 3).map((hook, i) => (
                <CopyChip key={i} text={hook} />
              ))}
            </div>
          </div>
        )}

        {/* No research message */}
        {!personalization_hooks?.length && !pain_signals?.length && !trigger_events?.length && (
          <p className="text-xs text-gray-400 dark:text-gray-500 italic">
            No research intelligence available. Run the Research Agent on this company first.
          </p>
        )}
      </div>

      {/* Footer — Generate Draft */}
      <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800">
        {generatedSubject ? (
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
              <span className="text-xs text-gray-600 dark:text-gray-300 truncate">
                <span className="font-medium">Draft created:</span> {generatedSubject}
              </span>
            </div>
            {generatedDraftId && (
              <Link
                href="/approvals"
                className="shrink-0 text-xs font-medium text-indigo-600 hover:text-indigo-800 dark:text-indigo-400"
              >
                View in Approvals
              </Link>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={handleGenerate}
              disabled={generating}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                "bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {generating ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Tag className="h-3.5 w-3.5" />
                  Generate Draft
                </>
              )}
            </button>
            {error && (
              <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
