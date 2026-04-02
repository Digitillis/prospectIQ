"use client";

/**
 * Visual Sequence Builder — /sequences/builder?id={id} (edit) or /sequences/builder (new)
 *
 * 3-panel layout:
 *   Left  (200px): Step type palette — click to add step
 *   Center       : Vertical sequence flow canvas
 *   Right (320px): Inspector — step configuration
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Mail, Clock, GitBranch, ClipboardList, Linkedin,
  ChevronUp, ChevronDown, Trash2, Plus, Loader2, Eye, Save,
  ArrowLeft, Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  createSequenceV2, updateSequenceV2, getSequenceById,
  type SequenceStepV2, type SequenceDefinitionV2,
} from "@/lib/api";
import type { StepType, WaitCondition, ConditionType } from "@/types/sequence";
import { TEMPLATE_VARIABLES } from "@/types/sequence";
import { SequencePreview } from "@/components/sequences/SequencePreview";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function newStepId() {
  return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
}

function makeStep(type: StepType, order: number): SequenceStepV2 {
  const base = { step_id: newStepId(), step_type: type, step_order: order, metadata: {} };
  switch (type) {
    case "email":
      return { ...base, subject_template: "", body_template: "", persona_variants: undefined };
    case "wait":
      return { ...base, wait_days: 3, wait_condition: "no_reply" as WaitCondition };
    case "condition":
      return { ...base, condition_type: "if_replied" as ConditionType, condition_value: undefined, branch_yes: undefined, branch_no: undefined };
    case "task":
      return { ...base, task_description: "", task_due_offset_days: 1 };
    case "linkedin":
      return { ...base, body_template: "" };
    default:
      return base as SequenceStepV2;
  }
}

const STEP_TYPE_META: Record<StepType, { label: string; Icon: React.ElementType; colorClass: string; bgClass: string }> = {
  email:     { label: "Email Step",       Icon: Mail,          colorClass: "text-blue-600 dark:text-blue-400",   bgClass: "bg-blue-50 dark:bg-blue-900/20" },
  wait:      { label: "Wait",             Icon: Clock,         colorClass: "text-gray-500 dark:text-gray-400",   bgClass: "bg-gray-100 dark:bg-gray-700" },
  condition: { label: "Condition Branch", Icon: GitBranch,     colorClass: "text-purple-600 dark:text-purple-400", bgClass: "bg-purple-50 dark:bg-purple-900/20" },
  task:      { label: "Task Reminder",    Icon: ClipboardList, colorClass: "text-orange-600 dark:text-orange-400", bgClass: "bg-orange-50 dark:bg-orange-900/20" },
  linkedin:  { label: "LinkedIn Message", Icon: Linkedin,      colorClass: "text-sky-600 dark:text-sky-400",     bgClass: "bg-sky-50 dark:bg-sky-900/20" },
};

const STEP_PALETTE: StepType[] = ["email", "wait", "condition", "task", "linkedin"];

const WAIT_CONDITIONS: { value: WaitCondition; label: string }[] = [
  { value: "no_reply", label: "No reply received" },
  { value: "no_open",  label: "No email open" },
  { value: "any",      label: "Unconditional" },
];

const CONDITION_TYPES: { value: ConditionType; label: string }[] = [
  { value: "if_replied",   label: "If Replied" },
  { value: "if_opened",    label: "If Email Opened" },
  { value: "if_clicked",   label: "If Clicked" },
  { value: "if_pqs_above", label: "If PQS Above" },
];

// ---------------------------------------------------------------------------
// Variable Chips component
// ---------------------------------------------------------------------------

function VariableChips({ onInsert }: { onInsert: (variable: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5 mb-2">
      {TEMPLATE_VARIABLES.map((v) => (
        <button
          key={v.name}
          type="button"
          title={v.desc}
          onClick={() => onInsert(v.name)}
          className="rounded bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 font-mono text-[10px] text-gray-700 dark:text-gray-300 hover:bg-blue-100 dark:hover:bg-blue-900/30 hover:text-blue-700 dark:hover:text-blue-300 transition-colors"
        >
          {v.name}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step summary (one-line in the canvas card)
// ---------------------------------------------------------------------------

function stepSummary(step: SequenceStepV2): string {
  switch (step.step_type) {
    case "email":
      return step.subject_template
        ? step.subject_template.slice(0, 60) + (step.subject_template.length > 60 ? "…" : "")
        : "(no subject)";
    case "wait": {
      const cond = WAIT_CONDITIONS.find((w) => w.value === step.wait_condition)?.label ?? "unconditional";
      return `Wait ${step.wait_days ?? "?"} day${(step.wait_days ?? 0) !== 1 ? "s" : ""} — ${cond.toLowerCase()}`;
    }
    case "condition":
      return CONDITION_TYPES.find((c) => c.value === step.condition_type)?.label ?? "Condition";
    case "task":
      return (step.task_description || "(no description)").slice(0, 60);
    case "linkedin":
      return (step.body_template || "(no message)").slice(0, 60);
    default:
      return "";
  }
}

// ---------------------------------------------------------------------------
// Connector arrow between steps
// ---------------------------------------------------------------------------

function Connector({ label }: { label?: string }) {
  return (
    <div className="flex items-center ml-[22px] my-1 gap-2">
      <div className="h-5 w-px border-l-2 border-dashed border-gray-300 dark:border-gray-600" />
      {label && <span className="text-[10px] text-gray-400 dark:text-gray-500">{label}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step card (canvas)
// ---------------------------------------------------------------------------

interface StepCardProps {
  step: SequenceStepV2;
  isSelected: boolean;
  isFirst: boolean;
  isLast: boolean;
  onClick: () => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

function StepCard({ step, isSelected, isFirst, isLast, onClick, onDelete, onMoveUp, onMoveDown }: StepCardProps) {
  const meta = STEP_TYPE_META[step.step_type as StepType];
  const Icon = meta.Icon;

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label={`${meta.label}: ${stepSummary(step)}`}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick(); }}
      className={cn(
        "rounded-lg border bg-white dark:bg-gray-900 shadow-sm cursor-pointer transition-all duration-200",
        isSelected
          ? "border-blue-500 ring-2 ring-blue-500 ring-offset-1 shadow-md"
          : "border-gray-200 dark:border-gray-700 hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600"
      )}
    >
      <div className="flex items-center gap-3 px-3 py-2.5">
        <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", meta.bgClass)}>
          <Icon className={cn("h-3.5 w-3.5", meta.colorClass)} aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className={cn("text-[10px] font-semibold uppercase tracking-wide", meta.colorClass)}>{meta.label}</p>
          <p className="truncate text-xs text-gray-700 dark:text-gray-300">{stepSummary(step)}</p>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 ml-1">
          {/* Reorder buttons — always visible so no hover needed */}
        </div>
        <div className="flex shrink-0 items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
          <button
            aria-label="Move step up"
            disabled={isFirst}
            onClick={onMoveUp}
            className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-20 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <ChevronUp className="h-3.5 w-3.5" />
          </button>
          <button
            aria-label="Move step down"
            disabled={isLast}
            onClick={onMoveDown}
            className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-20 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          <button
            aria-label="Delete step"
            onClick={onDelete}
            className="rounded p-1 text-gray-400 hover:text-red-500 focus:outline-none focus:ring-1 focus:ring-red-400"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Condition branch sub-rows */}
      {step.step_type === "condition" && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-3 py-2 flex gap-3 text-[10px]">
          <div className="flex items-center gap-1 text-green-600 dark:text-green-400">
            <Check className="h-3 w-3" />
            <span>YES</span>
            <span className="text-gray-400">→ {step.branch_yes ? `step` : "End / add step"}</span>
          </div>
          <div className="flex items-center gap-1 text-gray-400 dark:text-gray-500">
            <span className="font-bold">✕</span>
            <span>NO</span>
            <span className="text-gray-400">→ {step.branch_no ? `step` : "End / add step"}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inspector panels per step type
// ---------------------------------------------------------------------------

function EmailInspector({
  step,
  onChange,
}: {
  step: SequenceStepV2;
  onChange: (patch: Partial<SequenceStepV2>) => void;
}) {
  const subjectRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  const insertVariable = (target: "subject" | "body", variable: string) => {
    if (target === "subject" && subjectRef.current) {
      const el = subjectRef.current;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      const newVal = el.value.slice(0, start) + variable + el.value.slice(end);
      onChange({ subject_template: newVal });
      requestAnimationFrame(() => {
        el.setSelectionRange(start + variable.length, start + variable.length);
        el.focus();
      });
    } else if (target === "body" && bodyRef.current) {
      const el = bodyRef.current;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      const newVal = el.value.slice(0, start) + variable + el.value.slice(end);
      onChange({ body_template: newVal });
      requestAnimationFrame(() => {
        el.setSelectionRange(start + variable.length, start + variable.length);
        el.focus();
      });
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Subject Line
        </label>
        <VariableChips onInsert={(v) => insertVariable("subject", v)} />
        <input
          ref={subjectRef}
          type="text"
          value={step.subject_template ?? ""}
          onChange={(e) => onChange({ subject_template: e.target.value })}
          placeholder="{company_name} — quick question"
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Email Body
        </label>
        <VariableChips onInsert={(v) => insertVariable("body", v)} />
        <textarea
          ref={bodyRef}
          value={step.body_template ?? ""}
          onChange={(e) => onChange({ body_template: e.target.value })}
          rows={8}
          placeholder={"Hi {first_name},\n\nI noticed {company_name} has been..."}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
        />
      </div>

      <div>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!step.persona_variants}
            onChange={(e) =>
              onChange({ persona_variants: e.target.checked ? {} : undefined })
            }
            className="h-3.5 w-3.5 rounded"
          />
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Per-persona body variants</span>
        </label>
        <p className="text-[10px] text-gray-400 dark:text-gray-500 ml-5">
          Configure a different body for VP Ops, Plant Manager, etc.
        </p>
      </div>

      {step.persona_variants !== undefined && (
        <div className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 space-y-3">
          {["vp_ops", "plant_manager", "engineer"].map((persona) => (
            <div key={persona}>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
                {persona.replace("_", " ")}
              </label>
              <textarea
                value={step.persona_variants?.[persona] ?? ""}
                onChange={(e) =>
                  onChange({
                    persona_variants: { ...(step.persona_variants || {}), [persona]: e.target.value },
                  })
                }
                rows={4}
                placeholder={`Body for ${persona}...`}
                className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WaitInspector({
  step,
  onChange,
}: {
  step: SequenceStepV2;
  onChange: (patch: Partial<SequenceStepV2>) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Wait (days)
        </label>
        <input
          type="number"
          min={1}
          max={90}
          value={step.wait_days ?? 3}
          onChange={(e) => onChange({ wait_days: parseInt(e.target.value) || 1 })}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Trigger condition
        </label>
        <select
          value={step.wait_condition ?? "no_reply"}
          onChange={(e) => onChange({ wait_condition: e.target.value as WaitCondition })}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {WAIT_CONDITIONS.map((w) => (
            <option key={w.value} value={w.value}>{w.label}</option>
          ))}
        </select>
      </div>
      <div className="rounded bg-gray-50 dark:bg-gray-800 px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
        Wait <strong className="text-gray-900 dark:text-gray-100">{step.wait_days ?? 3} day{(step.wait_days ?? 3) !== 1 ? "s" : ""}</strong>{" "}
        if <strong className="text-gray-900 dark:text-gray-100">
          {WAIT_CONDITIONS.find((w) => w.value === step.wait_condition)?.label.toLowerCase() ?? "no reply"}
        </strong>
      </div>
    </div>
  );
}

function ConditionInspector({
  step,
  allSteps,
  onChange,
}: {
  step: SequenceStepV2;
  allSteps: SequenceStepV2[];
  onChange: (patch: Partial<SequenceStepV2>) => void;
}) {
  const otherSteps = allSteps.filter((s) => s.step_id !== step.step_id);
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Condition type
        </label>
        <select
          value={step.condition_type ?? "if_replied"}
          onChange={(e) => onChange({ condition_type: e.target.value as ConditionType })}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {CONDITION_TYPES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      </div>

      {step.condition_type === "if_pqs_above" && (
        <div>
          <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
            PQS threshold
          </label>
          <input
            type="number"
            min={0}
            max={100}
            value={typeof step.condition_value === "number" ? step.condition_value : 70}
            onChange={(e) => onChange({ condition_value: parseInt(e.target.value) || 70 })}
            className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}

      <div>
        <label className="block text-xs font-semibold text-green-600 dark:text-green-400 mb-1">
          YES branch — jump to
        </label>
        <select
          value={step.branch_yes ?? ""}
          onChange={(e) => onChange({ branch_yes: e.target.value || undefined })}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-green-500"
        >
          <option value="">End sequence</option>
          {otherSteps.map((s) => (
            <option key={s.step_id} value={s.step_id}>
              Step {s.step_order}: {STEP_TYPE_META[s.step_type as StepType].label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">
          NO branch — jump to
        </label>
        <select
          value={step.branch_no ?? ""}
          onChange={(e) => onChange({ branch_no: e.target.value || undefined })}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Continue to next step</option>
          {otherSteps.map((s) => (
            <option key={s.step_id} value={s.step_id}>
              Step {s.step_order}: {STEP_TYPE_META[s.step_type as StepType].label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function TaskInspector({
  step,
  onChange,
}: {
  step: SequenceStepV2;
  onChange: (patch: Partial<SequenceStepV2>) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Task description
        </label>
        <textarea
          value={step.task_description ?? ""}
          onChange={(e) => onChange({ task_description: e.target.value })}
          rows={4}
          placeholder="Follow up with {first_name} via LinkedIn..."
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          Due offset (days after step fires)
        </label>
        <input
          type="number"
          min={0}
          max={30}
          value={step.task_due_offset_days ?? 1}
          onChange={(e) => onChange({ task_due_offset_days: parseInt(e.target.value) || 1 })}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
    </div>
  );
}

function LinkedInInspector({
  step,
  onChange,
}: {
  step: SequenceStepV2;
  onChange: (patch: Partial<SequenceStepV2>) => void;
}) {
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const insertVariable = (variable: string) => {
    if (bodyRef.current) {
      const el = bodyRef.current;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      const newVal = el.value.slice(0, start) + variable + el.value.slice(end);
      onChange({ body_template: newVal });
      requestAnimationFrame(() => {
        el.setSelectionRange(start + variable.length, start + variable.length);
        el.focus();
      });
    }
  };
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
          LinkedIn message
        </label>
        <VariableChips onInsert={insertVariable} />
        <textarea
          ref={bodyRef}
          value={step.body_template ?? ""}
          onChange={(e) => onChange({ body_template: e.target.value })}
          rows={6}
          placeholder={"Hi {first_name}, I noticed {company_name}..."}
          className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
        />
        <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-1">
          LinkedIn connection request messages are limited to 300 characters.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main builder page
// ---------------------------------------------------------------------------

export default function SequenceBuilderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sequenceId = searchParams.get("id");
  const isEdit = !!sequenceId;

  const [name, setName] = useState("Untitled Sequence");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<SequenceStepV2[]>([makeStep("email", 1)]);
  const [selectedStepId, setSelectedStepId] = useState<string>(steps[0].step_id);
  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedOk, setSavedOk] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(sequenceId);

  // Load existing sequence if editing
  useEffect(() => {
    if (!isEdit || !sequenceId) return;
    setLoading(true);
    getSequenceById(sequenceId)
      .then((res) => {
        const seq = res.data as SequenceDefinitionV2 & { steps: SequenceStepV2[] };
        setName(seq.name);
        setDescription(seq.description ?? "");
        const loaded = (seq.steps || []).map((s: SequenceStepV2, i: number) => ({
          ...s,
          step_id: s.step_id || newStepId(),
          step_order: s.step_order ?? i + 1,
        }));
        setSteps(loaded.length > 0 ? loaded : [makeStep("email", 1)]);
        if (loaded.length > 0) setSelectedStepId(loaded[0].step_id);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isEdit, sequenceId]);

  const selectedStep = steps.find((s) => s.step_id === selectedStepId) ?? steps[0];

  // Normalize step_order after mutations
  const reorder = (arr: SequenceStepV2[]) =>
    arr.map((s, i) => ({ ...s, step_order: i + 1 }));

  const addStep = (type: StepType) => {
    const next = makeStep(type, steps.length + 1);
    setSteps((prev) => reorder([...prev, next]));
    setSelectedStepId(next.step_id);
  };

  const deleteStep = (id: string) => {
    setSteps((prev) => {
      const filtered = reorder(prev.filter((s) => s.step_id !== id));
      if (selectedStepId === id && filtered.length > 0) setSelectedStepId(filtered[0].step_id);
      return filtered;
    });
  };

  const moveStep = (id: string, dir: "up" | "down") => {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.step_id === id);
      if (idx < 0) return prev;
      const targetIdx = dir === "up" ? idx - 1 : idx + 1;
      if (targetIdx < 0 || targetIdx >= prev.length) return prev;
      const arr = [...prev];
      [arr[idx], arr[targetIdx]] = [arr[targetIdx], arr[idx]];
      return reorder(arr);
    });
  };

  const patchStep = useCallback((id: string, patch: Partial<SequenceStepV2>) => {
    setSteps((prev) => prev.map((s) => (s.step_id === id ? { ...s, ...patch } : s)));
  }, []);

  const handleSave = async (andNavigate = false) => {
    setSaving(true);
    setSaveError(null);
    setSavedOk(false);
    try {
      const payload: Partial<SequenceDefinitionV2> = {
        name: name.trim() || "Untitled Sequence",
        description,
        steps,
        is_template: false,
        tags: [],
      };
      if (isEdit && sequenceId) {
        await updateSequenceV2(sequenceId, payload);
        setSavedOk(true);
      } else {
        const res = await createSequenceV2(payload);
        const created = res.data as SequenceDefinitionV2;
        setSavedId(created.id ?? null);
        setSavedOk(true);
        if (andNavigate) {
          router.push("/sequences");
          return;
        }
        // Update URL without navigation so user can keep editing
        if (created.id) {
          window.history.replaceState({}, "", `/sequences/builder?id=${created.id}`);
        }
      }
      if (andNavigate) router.push("/sequences");
      else setTimeout(() => setSavedOk(false), 3000);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-56px)] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  const emailStepCount = steps.filter((s) => s.step_type === "email").length;

  return (
    <>
      <div className="flex h-[calc(100vh-56px)] flex-col overflow-hidden -m-6">
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="flex shrink-0 items-center gap-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-3">
          <button
            aria-label="Back to sequences"
            onClick={() => router.push("/sequences")}
            className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>

          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Sequence name"
            className="flex-1 bg-transparent text-sm font-semibold text-gray-900 dark:text-gray-100 focus:outline-none border-b border-transparent hover:border-gray-300 dark:hover:border-gray-600 focus:border-blue-500 transition-colors pb-0.5"
          />

          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400 dark:text-gray-500">
              {steps.length} step{steps.length !== 1 ? "s" : ""} · {emailStepCount} email{emailStepCount !== 1 ? "s" : ""}
            </span>

            {savedOk && (
              <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                <Check className="h-3.5 w-3.5" /> Saved
              </span>
            )}
            {saveError && (
              <span className="text-xs text-red-600 dark:text-red-400 max-w-[200px] truncate">{saveError}</span>
            )}

            {(isEdit || savedId) && (
              <button
                onClick={() => setPreviewOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-400"
              >
                <Eye className="h-3.5 w-3.5" /> Preview
              </button>
            )}

            <button
              onClick={() => handleSave(false)}
              disabled={saving}
              aria-label="Save draft"
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-gray-400"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              Save Draft
            </button>

            <button
              onClick={() => handleSave(true)}
              disabled={saving}
              aria-label="Publish sequence"
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Publish
            </button>
          </div>
        </div>

        {/* ── Body: 3 panels ──────────────────────────────────────────────── */}
        <div className="flex min-h-0 flex-1">
          {/* Left panel: Step palette */}
          <aside
            aria-label="Step type palette"
            className="w-[200px] shrink-0 overflow-y-auto border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 space-y-2"
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">
              Add Step
            </p>
            {STEP_PALETTE.map((type) => {
              const meta = STEP_TYPE_META[type];
              const Icon = meta.Icon;
              return (
                <button
                  key={type}
                  onClick={() => addStep(type)}
                  aria-label={`Add ${meta.label} step`}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2.5 text-left transition-all duration-200",
                    "hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  )}
                >
                  <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", meta.bgClass)}>
                    <Icon className={cn("h-3.5 w-3.5", meta.colorClass)} aria-hidden />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-900 dark:text-gray-100 truncate">{meta.label}</p>
                  </div>
                  <Plus className="ml-auto h-3.5 w-3.5 text-gray-400 shrink-0" />
                </button>
              );
            })}
            <p className="mt-3 text-[10px] text-gray-400 dark:text-gray-500 text-center leading-relaxed">
              Click any type to add to the end of the sequence
            </p>
          </aside>

          {/* Center panel: Canvas */}
          <main
            aria-label="Sequence flow canvas"
            className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-800/30 p-6"
          >
            <div className="mx-auto max-w-lg">
              {/* START node */}
              <div className="flex items-center gap-2 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-[10px] font-bold shrink-0">
                  S
                </div>
                <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Start</span>
              </div>
              <Connector />

              {steps.length === 0 && (
                <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 py-16">
                  <p className="text-sm text-gray-400 dark:text-gray-500 mb-2">No steps yet</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">Click a step type on the left to begin</p>
                </div>
              )}

              {steps.map((step, idx) => (
                <div key={step.step_id}>
                  <StepCard
                    step={step}
                    isSelected={step.step_id === selectedStepId}
                    isFirst={idx === 0}
                    isLast={idx === steps.length - 1}
                    onClick={() => setSelectedStepId(step.step_id)}
                    onDelete={() => deleteStep(step.step_id)}
                    onMoveUp={() => moveStep(step.step_id, "up")}
                    onMoveDown={() => moveStep(step.step_id, "down")}
                  />
                  {idx < steps.length - 1 && <Connector />}
                </div>
              ))}

              {steps.length > 0 && <Connector />}

              {/* END node */}
              {steps.length > 0 && (
                <div className="flex items-center gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-gray-300 dark:border-gray-600 text-gray-400 text-[10px] font-bold shrink-0">
                    E
                  </div>
                  <span className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide">End</span>
                </div>
              )}

              {/* Add step shortcut */}
              <button
                onClick={() => addStep("email")}
                className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 py-3 text-xs font-medium text-gray-400 dark:text-gray-500 hover:border-blue-400 dark:hover:border-blue-500 hover:text-blue-500 dark:hover:text-blue-400 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <Plus className="h-3.5 w-3.5" /> Add Email Step
              </button>
            </div>
          </main>

          {/* Right panel: Inspector */}
          <aside
            aria-label="Step inspector"
            className="w-[320px] shrink-0 overflow-y-auto border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5"
          >
            {selectedStep ? (
              <>
                <div className="mb-4 flex items-center gap-2">
                  {(() => {
                    const meta = STEP_TYPE_META[selectedStep.step_type as StepType];
                    const Icon = meta.Icon;
                    return (
                      <>
                        <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", meta.bgClass)}>
                          <Icon className={cn("h-3.5 w-3.5", meta.colorClass)} aria-hidden />
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-gray-900 dark:text-gray-100">{meta.label}</p>
                          <p className="text-[10px] text-gray-400 dark:text-gray-500">Step {selectedStep.step_order}</p>
                        </div>
                      </>
                    );
                  })()}
                </div>

                {selectedStep.step_type === "email" && (
                  <EmailInspector
                    step={selectedStep}
                    onChange={(patch) => patchStep(selectedStep.step_id, patch)}
                  />
                )}
                {selectedStep.step_type === "wait" && (
                  <WaitInspector
                    step={selectedStep}
                    onChange={(patch) => patchStep(selectedStep.step_id, patch)}
                  />
                )}
                {selectedStep.step_type === "condition" && (
                  <ConditionInspector
                    step={selectedStep}
                    allSteps={steps}
                    onChange={(patch) => patchStep(selectedStep.step_id, patch)}
                  />
                )}
                {selectedStep.step_type === "task" && (
                  <TaskInspector
                    step={selectedStep}
                    onChange={(patch) => patchStep(selectedStep.step_id, patch)}
                  />
                )}
                {selectedStep.step_type === "linkedin" && (
                  <LinkedInInspector
                    step={selectedStep}
                    onChange={(patch) => patchStep(selectedStep.step_id, patch)}
                  />
                )}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">Select a step to configure it</p>
              </div>
            )}

            {/* Description field (always shown at bottom) */}
            <div className="mt-6 border-t border-gray-100 dark:border-gray-800 pt-4">
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
                Sequence description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                placeholder="Optional description..."
                className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400 resize-none"
              />
            </div>
          </aside>
        </div>
      </div>

      {previewOpen && (savedId || sequenceId) && (
        <SequencePreview
          sequenceId={(savedId || sequenceId)!}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </>
  );
}
