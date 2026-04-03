"use client";

/**
 * Sequences — My Sequences, Template Library, Routing Config
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  GitBranch, Plus, CheckCircle2, Loader2, RefreshCw, Pencil, Copy, Wand2,
} from "lucide-react";
import {
  getSequenceTemplates, getSequenceRouting, updateRoutingEntry, provisionInstantlyCampaigns,
  duplicateSequenceV2,
  type SequenceTemplate, type RoutingEntry,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-gray-100 dark:bg-gray-800", className)} />;
}

// ---------------------------------------------------------------------------
// My Sequences Tab
// ---------------------------------------------------------------------------
type FilterKey = "all" | "templates" | "custom" | "active";

function MySequencesTab() {
  const [sequences, setSequences] = useState<SequenceTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [duplicating, setDuplicating] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSequenceTemplates();
      setSequences([...res.custom, ...res.built_in]);
    } catch { setSequences([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDuplicate = async (seq: SequenceTemplate) => {
    if (!seq.id) return;
    setDuplicating(seq.id);
    try {
      await duplicateSequenceV2(seq.id);
      await load();
    } catch { /* noop */ }
    finally { setDuplicating(null); }
  };

  const FILTER_TABS: { key: FilterKey; label: string }[] = [
    { key: "all",       label: "All" },
    { key: "templates", label: "Templates" },
    { key: "custom",    label: "Custom" },
    { key: "active",    label: "Active" },
  ];

  const filtered = sequences.filter((seq) => {
    if (filter === "templates") return seq.is_template === true || seq.source === "yaml";
    if (filter === "custom")    return seq.source === "custom";
    if (filter === "active")    return seq.is_active;
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-0.5">
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                filter === tab.key
                  ? "bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 shadow-sm"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} aria-label="Refresh sequences" className="rounded border border-gray-200 dark:border-gray-700 p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 focus:outline-none focus:ring-1 focus:ring-gray-400">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </button>
          <Link
            href="/sequences/builder"
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <Wand2 className="h-3.5 w-3.5" /> Visual Builder
          </Link>
          <Link href="/sequences/new" className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
            <Plus className="h-3.5 w-3.5" /> New Sequence
          </Link>
        </div>
      </div>

      <p className="text-xs text-gray-500 dark:text-gray-500">{filtered.length} sequence{filtered.length !== 1 ? "s" : ""}</p>

      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-40" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-20">
          <GitBranch className="h-12 w-12 text-gray-300 mb-4" />
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">No sequences yet</p>
          <Link href="/sequences/builder" className="mt-3 text-xs text-blue-600 underline underline-offset-2 hover:text-blue-700">
            Build your first sequence with the visual editor →
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((seq) => (
            <SequenceCard
              key={seq.name}
              seq={seq}
              duplicating={duplicating === seq.id}
              onDuplicate={() => handleDuplicate(seq)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface SequenceCardProps {
  seq: SequenceTemplate;
  duplicating: boolean;
  onDuplicate: () => void;
}

function SequenceCard({ seq, duplicating, onDuplicate }: SequenceCardProps) {
  const sourceLabel =
    seq.source === "custom" ? "Custom"
    : (seq.is_template ? "Template" : "Built-in");

  const sourceBadge =
    seq.source === "custom"
      ? "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300"
      : seq.is_template
      ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
      : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400";

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-200">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={cn("h-2 w-2 rounded-full shrink-0", seq.is_active ? "bg-green-500" : "bg-gray-300")} />
          <span className="font-semibold text-sm text-gray-900 dark:text-gray-100 truncate">{seq.display_name || seq.name}</span>
        </div>
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ml-2", sourceBadge)}>
          {sourceLabel}
        </span>
      </div>

      {seq.description && (
        <p className="text-xs text-gray-500 dark:text-gray-500 mb-3 leading-relaxed line-clamp-2">{seq.description}</p>
      )}
      <p className="text-xs text-gray-500 dark:text-gray-500 mb-4">
        {seq.total_steps} steps · {seq.channel}
      </p>

      <div className="grid grid-cols-3 gap-2 mb-4 text-center text-xs">
        {[["Enrolled", "—"], ["Open", "—"], ["Reply", "—"]].map(([label, val]) => (
          <div key={label} className="rounded bg-gray-50 dark:bg-gray-800 p-2">
            <p className="font-semibold text-gray-900 dark:text-gray-100">{val}</p>
            <p className="text-gray-400 dark:text-gray-500">{label}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {/* Visual builder edit — for v2 sequences with UUID id */}
        {seq.id && seq.source === "custom" && (
          <Link
            href={`/sequences/builder?id=${seq.id}`}
            className="inline-flex items-center gap-1 rounded border border-gray-200 dark:border-gray-700 px-2 py-1 text-[11px] text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <Wand2 className="h-3 w-3" /> Builder
          </Link>
        )}
        {/* Legacy edit for non-v2 custom sequences */}
        {seq.source === "custom" && !seq.id?.includes("-") && (
          <Link
            href={`/sequences/${seq.name}/edit`}
            className="inline-flex items-center gap-1 rounded border border-gray-200 dark:border-gray-700 px-2 py-1 text-[11px] text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <Pencil className="h-3 w-3" /> Edit
          </Link>
        )}
        {seq.id && (
          <button
            onClick={onDuplicate}
            disabled={duplicating}
            className="inline-flex items-center gap-1 rounded border border-gray-200 dark:border-gray-700 px-2 py-1 text-[11px] text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            {duplicating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Copy className="h-3 w-3" />}
            Duplicate
          </button>
        )}
        <Link
          href="/sequences/builder"
          className="ml-auto inline-flex items-center gap-1 rounded bg-blue-600 hover:bg-blue-700 px-2 py-1 text-[11px] text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          New from Builder
        </Link>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Template Library Tab
// ---------------------------------------------------------------------------
function TemplateLibraryTab() {
  const [templates, setTemplates] = useState<{ built_in: SequenceTemplate[]; custom: SequenceTemplate[] }>({ built_in: [], custom: [] });
  const [loading, setLoading] = useState(true);
  const [previewSeq, setPreviewSeq] = useState<SequenceTemplate | null>(null);
  const [filterUseCase, setFilterUseCase] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSequenceTemplates();
      setTemplates(res);
    } catch { setTemplates({ built_in: [], custom: [] }); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = [...templates.custom, ...templates.built_in].filter((t) => {
    if (filterUseCase && !t.name.includes(filterUseCase) && !t.description?.includes(filterUseCase)) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Filter templates..."
          value={filterUseCase}
          onChange={(e) => setFilterUseCase(e.target.value)}
          className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-gray-400"
        />
        <Link href="/sequences/builder" className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <Wand2 className="h-3.5 w-3.5" /> Visual Builder
        </Link>
        <Link href="/sequences/new?mode=template" className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
          <Plus className="h-3.5 w-3.5" /> Add Custom Template
        </Link>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-48" />)}
        </div>
      ) : (
        <div className="space-y-6">
          {templates.custom.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">My Templates</h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {templates.custom.map((t) => (
                  <TemplateCard key={t.name} template={t} onPreview={() => setPreviewSeq(t)} isCustom />
                ))}
              </div>
            </div>
          )}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">Built-in Templates</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {templates.built_in.filter((t) => !filterUseCase || filtered.includes(t)).map((t) => (
                <TemplateCard key={t.name} template={t} onPreview={() => setPreviewSeq(t)} />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Preview slide-over */}
      {previewSeq && (
        <div className="fixed inset-0 z-50 flex items-center justify-end">
          <div className="absolute inset-0 bg-black/30" onClick={() => setPreviewSeq(null)} />
          <div className="relative w-full max-w-md bg-white dark:bg-gray-900 h-full shadow-xl overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900 dark:text-gray-100">{previewSeq.display_name}</h2>
              <button onClick={() => setPreviewSeq(null)} className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">✕</button>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-500 mb-4">{previewSeq.description}</p>
            <div className="space-y-3">
              {previewSeq.steps.map((step) => (
                <div key={step.step} className="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="rounded-full bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 h-5 w-5 flex items-center justify-center text-[10px] font-bold shrink-0">{step.step}</span>
                    <span className="text-xs font-medium text-gray-900 dark:text-gray-100">Day {step.delay_days}</span>
                    <span className="text-xs text-gray-400">{step.channel}</span>
                  </div>
                  {step.subject_template && (
                    <p className="text-xs text-gray-700 dark:text-gray-300 font-medium mb-1">{step.subject_template}</p>
                  )}
                  {typeof step.instructions?.description === "string" && (
                    <p className="text-xs text-gray-500 dark:text-gray-500">{step.instructions.description}</p>
                  )}
                </div>
              ))}
            </div>
            <Link
              href={`/sequences/builder`}
              className="mt-6 block w-full rounded-md bg-blue-600 hover:bg-blue-700 px-4 py-2.5 text-center text-sm font-medium text-white"
            >
              Build from Scratch →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function TemplateCard({ template, onPreview, isCustom }: { template: SequenceTemplate; onPreview: () => void; isCustom?: boolean }) {
  const firstStep = template.steps[0];
  const totalDays = template.steps.reduce((max, s) => Math.max(max, s.delay_days), 0);
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <div className="flex items-start justify-between mb-2">
        <span className="font-semibold text-sm text-gray-900 dark:text-gray-100">{template.display_name}</span>
        {isCustom && <span className="rounded bg-purple-100 dark:bg-purple-900/30 px-1.5 py-0.5 text-[10px] font-medium text-purple-700 dark:text-purple-300">custom</span>}
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-500 mb-2 line-clamp-2">{template.description}</p>
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">{template.total_steps} steps · {totalDays} days · {template.channel}</p>
      {firstStep && (
        <div className="rounded bg-gray-50 dark:bg-gray-800 p-2 mb-3">
          <p className="text-[10px] text-gray-400 dark:text-gray-500 mb-0.5">Step 1 (Day 0):</p>
          <p className="text-xs text-gray-700 dark:text-gray-300 truncate">{firstStep.subject_template ?? firstStep.name}</p>
        </div>
      )}
      <div className="flex items-center gap-2">
        <button onClick={onPreview} className="flex-1 rounded border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
          Preview
        </button>
        <Link href="/sequences/builder" className="flex-1 rounded bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-center text-xs font-medium text-white focus:outline-none focus:ring-1 focus:ring-blue-500">
          Build →
        </Link>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Routing Config Tab
// ---------------------------------------------------------------------------
function RoutingConfigTab() {
  const [routing, setRouting] = useState<RoutingEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingRow, setEditingRow] = useState<{ cluster: string; persona: string } | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  const [provisionResult, setProvisionResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSequenceRouting();
      setRouting(res.data);
    } catch { setRouting([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveRow = async () => {
    if (!editingRow) return;
    setSaving(true);
    try {
      await updateRoutingEntry({ cluster: editingRow.cluster, persona: editingRow.persona, campaign_id: editValue });
      setRouting((prev) => prev.map((r) => r.cluster === editingRow.cluster && r.persona === editingRow.persona ? { ...r, campaign_id: editValue, linked: !!editValue } : r));
    } catch { /* noop */ }
    finally { setSaving(false); setEditingRow(null); setEditValue(""); }
  };

  const handleProvisionAll = async () => {
    setProvisioning(true);
    try {
      const res = await provisionInstantlyCampaigns({ dry_run: true });
      setProvisionResult(`${res.provisioned} linked, ${res.pending} pending`);
      setTimeout(() => setProvisionResult(null), 5000);
    } catch { setProvisionResult("Failed — check API key"); }
    finally { setProvisioning(false); }
  };

  // Group by cluster
  const clusters = Array.from(new Set(routing.map((r) => r.cluster)));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500 dark:text-gray-500">
          {routing.filter((r) => r.linked).length} of {routing.length} routing entries linked to Instantly campaigns
        </p>
        <div className="flex items-center gap-2">
          {provisionResult && <span className="text-xs text-gray-600 dark:text-gray-400">{provisionResult}</span>}
          <button onClick={handleProvisionAll} disabled={provisioning} className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50">
            {provisioning ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
            Auto-Provision All
          </button>
        </div>
      </div>

      {loading ? <Skeleton className="h-64 w-full" /> : (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                {["Cluster", "Persona", "Env Var", "Instantly Campaign ID", "Status"].map((h) => (
                  <th key={h} className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {routing.map((row) => {
                const isEditing = editingRow?.cluster === row.cluster && editingRow?.persona === row.persona;
                return (
                  <tr key={`${row.cluster}-${row.persona}`} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-4 py-2 font-medium text-gray-900 dark:text-gray-100 capitalize">{row.cluster}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{row.persona}</td>
                    <td className="px-4 py-2 font-mono text-[10px] text-gray-400 dark:text-gray-500">{row.env_var}</td>
                    <td className="px-4 py-2">
                      {isEditing ? (
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") saveRow(); if (e.key === "Escape") { setEditingRow(null); setEditValue(""); } }}
                            className="rounded border border-gray-300 dark:border-gray-600 px-2 py-0.5 text-xs font-mono focus:outline-none"
                            autoFocus
                            placeholder="Instantly campaign ID..."
                          />
                          <button onClick={saveRow} disabled={saving} className="text-xs text-gray-600 hover:text-gray-900">{saving ? "…" : "✓"}</button>
                          <button onClick={() => { setEditingRow(null); setEditValue(""); }} className="text-xs text-gray-400">✕</button>
                        </div>
                      ) : (
                        <button
                          onClick={() => { setEditingRow({ cluster: row.cluster, persona: row.persona }); setEditValue(row.campaign_id ?? ""); }}
                          className="font-mono text-xs text-gray-700 dark:text-gray-300 hover:underline underline-offset-2"
                        >
                          {row.campaign_id ?? <span className="text-gray-400 italic">not set — click to add</span>}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", row.linked ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400")}>
                        {row.linked ? "✓ Linked" : "○ Not linked"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
type TabKey = "sequences" | "templates" | "routing";
const TABS: { key: TabKey; label: string }[] = [
  { key: "sequences", label: "My Sequences" },
  { key: "templates", label: "Template Library" },
  { key: "routing", label: "Routing Config" },
];

export default function SequencesPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("sequences");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Sequences</h1>
      </div>

      <div className="flex border-b border-gray-200 dark:border-gray-700">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn("px-4 py-2 text-sm font-medium transition-colors", activeTab === tab.key ? "border-b-2 border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100" : "text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "sequences" && <MySequencesTab />}
      {activeTab === "templates" && <TemplateLibraryTab />}
      {activeTab === "routing" && <RoutingConfigTab />}
    </div>
  );
}
