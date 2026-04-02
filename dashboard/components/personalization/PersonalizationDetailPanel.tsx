"use client";

/**
 * PersonalizationDetailPanel — 480px slide-over showing full personalization
 * intelligence for a company: readiness score, triggers, hooks, contacts/personas,
 * and action buttons.
 */

import { useState, useEffect } from "react";
import {
  X,
  RefreshCw,
  Copy,
  Check,
  Plus,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertTriangle,
  Pencil,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ReadinessScore } from "./ReadinessScore";
import { TriggerCard, TriggerEvent } from "./TriggerCard";
import {
  runPersonalization,
  getPersonalizationStatus,
  addManualTrigger,
  PersonalizationResult,
  PersonalizationStatus,
} from "@/lib/api";

// ─── Types ─────────────────────────────────────────────────────────────────

interface Contact {
  id: string;
  full_name?: string;
  title?: string;
  persona_type?: string;
}

interface PersonalizationHook {
  hook_text: string;
  persona_target: string;
  trigger_reference: string;
  tone: string;
  confidence: number;
}

interface Company {
  id: string;
  name: string;
  campaign_cluster?: string;
  tier?: string;
  pqs_total?: number;
}

interface PersonalizationDetailPanelProps {
  company: Company;
  contacts?: Contact[];
  onClose: () => void;
  onRefreshed?: () => void;
}

// ─── Persona badge ──────────────────────────────────────────────────────────

const PERSONA_LABELS: Record<string, string> = {
  vp_ops: "VP Ops",
  plant_manager: "Plant Mgr",
  engineer: "Engineer",
  procurement: "Procurement",
  executive: "Executive",
  operations_general: "Operations",
};

const TONE_STYLES: Record<string, string> = {
  specific: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
  empathetic: "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  provocative: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400",
};

// ─── Hook Card ──────────────────────────────────────────────────────────────

function HookCard({ hook }: { hook: PersonalizationHook }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(hook.hook_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-lg p-3 group hover:border-zinc-300 dark:hover:border-zinc-600 transition-colors">
      <p className="text-sm text-zinc-800 dark:text-zinc-200 leading-relaxed mb-2">
        "{hook.hook_text}"
      </p>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 rounded text-zinc-600 dark:text-zinc-400">
            {PERSONA_LABELS[hook.persona_target] || hook.persona_target}
          </span>
          {hook.tone && (
            <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded capitalize", TONE_STYLES[hook.tone] || TONE_STYLES.specific)}>
              {hook.tone}
            </span>
          )}
          {hook.confidence > 0 && (
            <span className="text-[10px] text-zinc-400">
              {Math.round(hook.confidence * 100)}%
            </span>
          )}
        </div>
        <button
          onClick={copy}
          className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors"
          title="Copy hook"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}

// ─── Manual Trigger Form ─────────────────────────────────────────────────────

function ManualTriggerForm({
  companyId,
  onAdded,
}: {
  companyId: string;
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    trigger_type: "growth",
    description: "",
    urgency: "near_term",
  });

  const submit = async () => {
    if (!form.description.trim()) return;
    setLoading(true);
    try {
      await addManualTrigger(companyId, { ...form, source: "manual" });
      setOpen(false);
      setForm({ trigger_type: "growth", description: "", urgency: "near_term" });
      onAdded();
    } catch (e) {
      console.error("Failed to add trigger:", e);
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
      >
        <Plus className="w-3.5 h-3.5" />
        Add manual trigger
      </button>
    );
  }

  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-lg p-3 space-y-2">
      <div className="flex gap-2">
        <select
          value={form.trigger_type}
          onChange={(e) => setForm((f) => ({ ...f, trigger_type: e.target.value }))}
          className="text-xs border border-zinc-200 dark:border-zinc-700 rounded px-2 py-1 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 flex-1"
        >
          <option value="growth">Growth</option>
          <option value="pain">Pain</option>
          <option value="tech">Tech</option>
          <option value="timing">Timing</option>
        </select>
        <select
          value={form.urgency}
          onChange={(e) => setForm((f) => ({ ...f, urgency: e.target.value }))}
          className="text-xs border border-zinc-200 dark:border-zinc-700 rounded px-2 py-1 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 flex-1"
        >
          <option value="immediate">Immediate</option>
          <option value="near_term">Near Term</option>
          <option value="background">Background</option>
        </select>
      </div>
      <textarea
        value={form.description}
        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        placeholder="Describe the trigger..."
        rows={2}
        className="w-full text-xs border border-zinc-200 dark:border-zinc-700 rounded px-2 py-1.5 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 resize-none"
      />
      <div className="flex gap-2 justify-end">
        <button
          onClick={() => setOpen(false)}
          className="text-xs text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 px-2 py-1"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={loading || !form.description.trim()}
          className="text-xs bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-3 py-1 rounded disabled:opacity-50"
        >
          {loading ? "Adding..." : "Add"}
        </button>
      </div>
    </div>
  );
}

// ─── Main Panel ─────────────────────────────────────────────────────────────

export function PersonalizationDetailPanel({
  company,
  contacts = [],
  onClose,
  onRefreshed,
}: PersonalizationDetailPanelProps) {
  const [status, setStatus] = useState<PersonalizationStatus | null>(null);
  const [result, setResult] = useState<PersonalizationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [triggersExpanded, setTriggersExpanded] = useState(true);
  const [hooksExpanded, setHooksExpanded] = useState(true);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getPersonalizationStatus(company.id);
      setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [company.id]);

  const runPipeline = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await runPersonalization(company.id);
      setResult(r);
      setStatus({
        company_id: company.id,
        readiness_score: r.readiness_score,
        triggers: r.triggers,
        hooks: [],
        personas_found: r.personas_found,
        last_run_at: r.generated_at,
        contacts_count: contacts.length,
      });
      onRefreshed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline failed");
    } finally {
      setRunning(false);
    }
  };

  const triggers = result?.triggers ?? status?.triggers ?? [];
  const hooks = result?.hooks ?? [];
  const readinessScore = result?.readiness_score ?? status?.readiness_score ?? 0;
  const breakdown = result?.readiness_breakdown ?? {};
  const personasFound = result?.personas_found ?? status?.personas_found ?? [];
  const lastRunAt = result?.generated_at ?? status?.last_run_at;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 dark:bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-[480px] bg-white dark:bg-zinc-900 shadow-2xl z-50 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 truncate">
                {company.name}
              </h2>
              {company.campaign_cluster && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded-full whitespace-nowrap">
                  {company.campaign_cluster}
                </span>
              )}
            </div>
            {readinessScore > 0 && (
              <ReadinessScore
                score={readinessScore}
                breakdown={Object.keys(breakdown).length ? breakdown : undefined}
                size="sm"
              />
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 flex-shrink-0 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
            </div>
          ) : error ? (
            <div className="p-5 text-center">
              <AlertTriangle className="w-5 h-5 mx-auto mb-2 text-amber-500" />
              <p className="text-sm text-zinc-500">{error}</p>
            </div>
          ) : (
            <div className="p-5 space-y-5">
              {/* Triggers section */}
              <div>
                <button
                  onClick={() => setTriggersExpanded((e) => !e)}
                  className="w-full flex items-center justify-between mb-2"
                >
                  <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
                    Buying Triggers
                    <span className="ml-1.5 text-zinc-400 font-normal normal-case">
                      ({triggers.length})
                    </span>
                  </h3>
                  {triggersExpanded ? (
                    <ChevronUp className="w-3.5 h-3.5 text-zinc-400" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
                  )}
                </button>

                {triggersExpanded && (
                  <div className="space-y-2">
                    {triggers.length === 0 ? (
                      <p className="text-xs text-zinc-400 italic">
                        No triggers identified yet. Run personalization to extract them.
                      </p>
                    ) : (
                      triggers.map((t, i) => (
                        <TriggerCard key={i} trigger={t} compact />
                      ))
                    )}
                    <div className="pt-1">
                      <ManualTriggerForm
                        companyId={company.id}
                        onAdded={load}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Hooks section */}
              {hooks.length > 0 && (
                <div>
                  <button
                    onClick={() => setHooksExpanded((e) => !e)}
                    className="w-full flex items-center justify-between mb-2"
                  >
                    <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
                      Personalization Hooks
                      <span className="ml-1.5 text-zinc-400 font-normal normal-case">
                        ({hooks.length})
                      </span>
                    </h3>
                    {hooksExpanded ? (
                      <ChevronUp className="w-3.5 h-3.5 text-zinc-400" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
                    )}
                  </button>

                  {hooksExpanded && (
                    <div className="space-y-2">
                      {hooks.map((h, i) => (
                        <HookCard key={i} hook={h} />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Contacts & personas */}
              {contacts.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
                    Contacts & Personas
                    <span className="ml-1.5 text-zinc-400 font-normal normal-case">
                      ({contacts.length})
                    </span>
                  </h3>
                  <div className="space-y-1.5">
                    {contacts.map((c) => (
                      <div key={c.id} className="flex items-center justify-between py-1">
                        <div className="min-w-0">
                          <p className="text-sm text-zinc-800 dark:text-zinc-200 truncate">
                            {c.full_name || "Unknown"}
                          </p>
                          {c.title && (
                            <p className="text-xs text-zinc-400 truncate">{c.title}</p>
                          )}
                        </div>
                        {c.persona_type && (
                          <span className="ml-2 flex-shrink-0 text-[10px] font-medium px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded">
                            {PERSONA_LABELS[c.persona_type] || c.persona_type}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Personas summary (from run result) */}
              {personasFound.length > 0 && contacts.length === 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
                    Personas Covered
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {personasFound.map((p) => (
                      <span
                        key={p}
                        className="text-[10px] font-medium px-2 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded-full"
                      >
                        {PERSONA_LABELS[p] || p}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Actions footer */}
        <div className="border-t border-zinc-200 dark:border-zinc-800 p-4 space-y-2">
          {lastRunAt && (
            <p className="text-[10px] text-zinc-400 text-center">
              Last run: {new Date(lastRunAt).toLocaleString()}
              {result && ` · Cost: $${result.cost_usd.toFixed(4)}`}
            </p>
          )}
          <button
            onClick={runPipeline}
            disabled={running}
            className="w-full flex items-center justify-center gap-2 bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-sm font-medium py-2.5 rounded-lg hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50 transition-colors"
          >
            {running ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Running Pipeline...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                {lastRunAt ? "Re-run Personalization" : "Run Personalization"}
              </>
            )}
          </button>
        </div>
      </div>
    </>
  );
}
