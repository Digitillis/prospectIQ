"use client";

/**
 * Visual Sequence Builder — full step editor for V2 sequences.
 * Supports email, wait, condition, linkedin, and task steps.
 * Loads an existing sequence via ?id= param, or starts blank.
 */

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft, ArrowDown, ArrowUp, ChevronDown, ChevronRight,
  Mail, Clock, GitBranch, Linkedin, CheckSquare, Plus, Trash2,
  Save, Eye, Loader2, GripVertical, AlertCircle, CheckCircle2,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  createSequenceV2, getSequenceV2, updateSequenceV2,
  type SequenceStepV2, type SequenceV2,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type StepType = "email" | "wait" | "condition" | "linkedin" | "task";

const STEP_PALETTE: { type: StepType; label: string; icon: React.ElementType; color: string }[] = [
  { type: "email",     label: "Email",     icon: Mail,        color: "text-blue-500" },
  { type: "wait",      label: "Wait",      icon: Clock,       color: "text-amber-500" },
  { type: "condition", label: "Condition", icon: GitBranch,   color: "text-purple-500" },
  { type: "linkedin",  label: "LinkedIn",  icon: Linkedin,    color: "text-sky-500" },
  { type: "task",      label: "Task",      icon: CheckSquare, color: "text-green-500" },
];

const CONDITION_TYPES = [
  { value: "if_opened",    label: "If email opened" },
  { value: "if_replied",   label: "If replied" },
  { value: "if_clicked",   label: "If link clicked" },
  { value: "if_pqs_above", label: "If PQS score ≥ value" },
];

const WAIT_CONDITIONS = [
  { value: "no_reply", label: "No reply received" },
  { value: "no_open",  label: "No open detected" },
  { value: "any",      label: "Any (always continue)" },
];

function makeStep(type: StepType, order: number): SequenceStepV2 {
  const base: SequenceStepV2 = {
    step_id: crypto.randomUUID(),
    step_type: type,
    step_order: order,
  };
  if (type === "wait")      return { ...base, wait_days: 3, wait_condition: "no_reply" };
  if (type === "condition") return { ...base, condition_type: "if_opened" };
  if (type === "task")      return { ...base, task_description: "", task_due_offset_days: 1 };
  return base;
}

// ---------------------------------------------------------------------------
// Step icon
// ---------------------------------------------------------------------------
function StepIcon({ type }: { type: StepType }) {
  const p = STEP_PALETTE.find((s) => s.type === type) ?? STEP_PALETTE[0];
  const Icon = p.icon;
  return <Icon className={cn("h-4 w-4", p.color)} />;
}

// ---------------------------------------------------------------------------
// Step editor card
// ---------------------------------------------------------------------------
interface StepEditorProps {
  step: SequenceStepV2;
  index: number;
  total: number;
  allSteps: SequenceStepV2[];
  onChange: (updated: SequenceStepV2) => void;
  onDelete: () => void;
  onMove: (dir: "up" | "down") => void;
}

function StepEditor({ step, index, total, allSteps, onChange, onDelete, onMove }: StepEditorProps) {
  const [open, setOpen] = useState(true);
  const set = (patch: Partial<SequenceStepV2>) => onChange({ ...step, ...patch });
  const paletteItem = STEP_PALETTE.find((p) => p.type === step.step_type)!;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <div
        className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800 cursor-pointer select-none"
        onClick={() => setOpen(!open)}
      >
        <GripVertical className="h-4 w-4 text-gray-300 shrink-0" />
        <StepIcon type={step.step_type} />
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 flex-1">
          Step {index + 1} — {paletteItem?.label ?? step.step_type}
        </span>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => onMove("up")} disabled={index === 0} className="rounded p-0.5 text-gray-400 hover:text-gray-600 disabled:opacity-30">
            <ArrowUp className="h-3 w-3" />
          </button>
          <button onClick={() => onMove("down")} disabled={index === total - 1} className="rounded p-0.5 text-gray-400 hover:text-gray-600 disabled:opacity-30">
            <ArrowDown className="h-3 w-3" />
          </button>
          <button onClick={onDelete} className="rounded p-0.5 text-red-400 hover:text-red-600 ml-1">
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
        {open ? <ChevronDown className="h-3 w-3 text-gray-400" /> : <ChevronRight className="h-3 w-3 text-gray-400" />}
      </div>

      {open && (
        <div className="p-4 space-y-3 text-sm">
          {step.step_type === "email" && (
            <>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Subject template</span>
                <input
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={step.subject_template ?? ""}
                  onChange={(e) => set({ subject_template: e.target.value })}
                  placeholder="{first_name}, quick question about {company_name}"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Body template</span>
                <textarea
                  rows={5}
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y"
                  value={step.body_template ?? ""}
                  onChange={(e) => set({ body_template: e.target.value })}
                  placeholder={"Hi {first_name},\n\nI noticed {company_name} is..."}
                />
              </label>
              <p className="text-[11px] text-gray-400">
                Variables: {["{first_name}", "{company_name}", "{title}", "{industry}"].map((v) => (
                  <code key={v} className="mx-0.5 bg-gray-100 dark:bg-gray-800 px-1 rounded">{v}</code>
                ))}
              </p>
            </>
          )}

          {step.step_type === "wait" && (
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Wait days</span>
                <input
                  type="number" min={1} max={60}
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={step.wait_days ?? 3}
                  onChange={(e) => set({ wait_days: Number(e.target.value) })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Condition</span>
                <select
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={step.wait_condition ?? "no_reply"}
                  onChange={(e) => set({ wait_condition: e.target.value })}
                >
                  {WAIT_CONDITIONS.map((wc) => <option key={wc.value} value={wc.value}>{wc.label}</option>)}
                </select>
              </label>
            </div>
          )}

          {step.step_type === "condition" && (
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Condition type</span>
                <select
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={step.condition_type ?? "if_opened"}
                  onChange={(e) => set({ condition_type: e.target.value })}
                >
                  {CONDITION_TYPES.map((ct) => <option key={ct.value} value={ct.value}>{ct.label}</option>)}
                </select>
              </label>
              {step.condition_type === "if_pqs_above" && (
                <label className="block">
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-400">PQS threshold</span>
                  <input
                    type="number" min={0} max={100}
                    className="mt-1 w-32 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    value={typeof step.condition_value === "number" ? step.condition_value : 50}
                    onChange={(e) => set({ condition_value: Number(e.target.value) })}
                  />
                </label>
              )}
              <div className="grid grid-cols-2 gap-3">
                {(["branch_yes", "branch_no"] as const).map((branch) => (
                  <label key={branch} className="block">
                    <span className={cn("text-xs font-medium", branch === "branch_yes" ? "text-green-600" : "text-red-500")}>
                      {branch === "branch_yes" ? "If YES → step" : "If NO → step"}
                    </span>
                    <select
                      className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      value={step[branch] ?? ""}
                      onChange={(e) => set({ [branch]: e.target.value || undefined })}
                    >
                      <option value="">Next step</option>
                      {allSteps.filter((s) => s.step_id !== step.step_id).map((s, i) => (
                        <option key={s.step_id} value={s.step_id}>Step {i + 1} ({s.step_type})</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}

          {step.step_type === "linkedin" && (
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Message / connection note</span>
              <textarea
                rows={4}
                className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y"
                value={step.body_template ?? ""}
                onChange={(e) => set({ body_template: e.target.value })}
                placeholder={"Hi {first_name}, I came across {company_name} and…"}
              />
            </label>
          )}

          {step.step_type === "task" && (
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Task description</span>
                <input
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={step.task_description ?? ""}
                  onChange={(e) => set({ task_description: e.target.value })}
                  placeholder="Call {first_name} at {company_name} to follow up"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Due (days after trigger)</span>
                <input
                  type="number" min={0} max={30}
                  className="mt-1 w-24 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={step.task_due_offset_days ?? 1}
                  onChange={(e) => set({ task_due_offset_days: Number(e.target.value) })}
                />
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page — useSearchParams requires Suspense in Next.js 15
// ---------------------------------------------------------------------------
function SequenceBuilderInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const editId = searchParams.get("id");

  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [cluster, setCluster] = useState("");
  const [persona, setPersona] = useState("");
  const [isTemplate, setIsTemplate] = useState(false);
  const [steps, setSteps] = useState<SequenceStepV2[]>([makeStep("email", 0)]);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(!!editId);

  useEffect(() => {
    if (!editId) return;
    setLoading(true);
    getSequenceV2(editId)
      .then(({ data }) => {
        setName(data.name);
        setDisplayName(data.display_name ?? "");
        setDescription(data.description ?? "");
        setCluster(data.cluster ?? "");
        setPersona(data.persona ?? "");
        setIsTemplate(data.is_template);
        setSteps(data.steps.map((s, i) => ({ ...s, step_order: i })));
      })
      .catch(() => setLoadError("Failed to load sequence."))
      .finally(() => setLoading(false));
  }, [editId]);

  const addStep = (type: StepType) =>
    setSteps((prev) => [...prev, makeStep(type, prev.length)]);

  const updateStep = (index: number, updated: SequenceStepV2) =>
    setSteps((prev) => prev.map((s, i) => (i === index ? updated : s)));

  const deleteStep = (index: number) =>
    setSteps((prev) => prev.filter((_, i) => i !== index).map((s, i) => ({ ...s, step_order: i })));

  const moveStep = (index: number, dir: "up" | "down") =>
    setSteps((prev) => {
      const next = [...prev];
      const swap = dir === "up" ? index - 1 : index + 1;
      [next[index], next[swap]] = [next[swap], next[index]];
      return next.map((s, i) => ({ ...s, step_order: i }));
    });

  const handleSave = async (publish: boolean) => {
    if (!name.trim()) { setSaveError("Sequence name is required."); return; }
    const hasContent = steps.some((s) => s.step_type === "email" || s.step_type === "linkedin");
    if (!hasContent) { setSaveError("Add at least one email or LinkedIn step."); return; }

    setSaving(true);
    setSaveError(null);
    const payload: Omit<SequenceV2, "id" | "created_at" | "updated_at"> = {
      name: name.trim(),
      display_name: displayName.trim() || name.trim(),
      description: description.trim(),
      cluster: cluster.trim() || undefined,
      persona: persona.trim() || undefined,
      steps,
      is_template: isTemplate,
      tags: [],
      is_active: publish,
    };

    try {
      if (editId) {
        await updateSequenceV2(editId, payload);
      } else {
        const res = await createSequenceV2(payload);
        router.replace(`/sequences/builder?id=${res.data.id}`);
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <AlertCircle className="h-10 w-10 text-red-400" />
        <p className="text-sm text-gray-600 dark:text-gray-400">{loadError}</p>
        <Link href="/sequences" className="text-xs text-blue-600 underline">← Back to sequences</Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* Top bar */}
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-4 py-3">
        <div className="flex items-center gap-3">
          <Link href="/sequences" className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <input
            className="text-sm font-semibold text-gray-900 dark:text-gray-100 bg-transparent border-none outline-none focus:ring-0 w-56 placeholder:text-gray-400"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Sequence display name…"
          />
          {editId && <span className="text-[10px] bg-gray-100 dark:bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded">editing</span>}
        </div>
        <div className="flex items-center gap-2">
          {saveError && (
            <span className="flex items-center gap-1 text-xs text-red-500">
              <AlertCircle className="h-3 w-3" /> {saveError}
            </span>
          )}
          {saved && (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <CheckCircle2 className="h-3 w-3" /> Saved
            </span>
          )}
          <button
            onClick={() => handleSave(false)}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            Save draft
          </button>
          <button
            onClick={() => handleSave(true)}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
            Publish
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-6 grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6">
        {/* Settings sidebar */}
        <aside className="space-y-4">
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 space-y-3">
            <h2 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">Settings</h2>
            <label className="block">
              <span className="text-xs text-gray-500">Internal name <span className="text-red-400">*</span></span>
              <input
                className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                value={name}
                onChange={(e) => setName(e.target.value.toLowerCase().replace(/\s+/g, "_"))}
                placeholder="my_sequence_name"
              />
            </label>
            <label className="block">
              <span className="text-xs text-gray-500">Description</span>
              <textarea
                rows={2}
                className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this sequence does…"
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="text-xs text-gray-500">Cluster</span>
                <input
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={cluster}
                  onChange={(e) => setCluster(e.target.value)}
                  placeholder="mfg, fb…"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Persona</span>
                <input
                  className="mt-1 w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={persona}
                  onChange={(e) => setPersona(e.target.value)}
                  placeholder="vp_ops…"
                />
              </label>
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isTemplate}
                onChange={(e) => setIsTemplate(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-xs text-gray-600 dark:text-gray-400">Save as reusable template</span>
            </label>
          </div>

          {/* Step palette */}
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 space-y-2">
            <h2 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">Add step</h2>
            {STEP_PALETTE.map(({ type, label, icon: Icon, color }) => (
              <button
                key={type}
                onClick={() => addStep(type)}
                className="flex w-full items-center gap-2 rounded border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                <Icon className={cn("h-3.5 w-3.5", color)} />
                {label}
                <Plus className="h-3 w-3 ml-auto text-gray-400" />
              </button>
            ))}
          </div>
        </aside>

        {/* Step canvas */}
        <div className="space-y-3">
          <h2 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            {steps.length} step{steps.length !== 1 ? "s" : ""}
          </h2>

          {steps.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-20 gap-3">
              <Plus className="h-10 w-10 text-gray-300" />
              <p className="text-sm text-gray-500">Add your first step from the palette →</p>
            </div>
          ) : (
            <div className="space-y-2">
              {steps.map((step, index) => (
                <div key={step.step_id}>
                  <StepEditor
                    step={step}
                    index={index}
                    total={steps.length}
                    allSteps={steps}
                    onChange={(updated) => updateStep(index, updated)}
                    onDelete={() => deleteStep(index)}
                    onMove={(dir) => moveStep(index, dir)}
                  />
                  {index < steps.length - 1 && (
                    <div className="flex justify-center py-1">
                      <ArrowDown className="h-3.5 w-3.5 text-gray-300" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function SequenceBuilderPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-screen"><Loader2 className="h-8 w-8 animate-spin text-blue-500" /></div>}>
      <SequenceBuilderInner />
    </Suspense>
  );
}
