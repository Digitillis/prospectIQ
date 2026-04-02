"use client";

/**
 * Sequence Editor — Edit an existing sequence template
 * Mirrors the /sequences/new builder but pre-populates from existing sequence data
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ChevronLeft,
  Plus,
  Trash2,
  ChevronDown,
  ChevronUp,
  Copy,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { getSequenceTemplates, saveSequenceTemplate, SequenceTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface StepState {
  step: number;
  name: string;
  channel: string;
  delay_days: number;
  subject_template: string;
  ai_instructions: string;
  tone: string;
  max_words: number;
  collapsed: boolean;
}

const CLUSTERS = [
  "machinery_industrial",
  "food_beverage",
  "chemical_process",
  "automotive_oem",
  "aerospace_defense",
  "pharma_biotech",
  "energy_utilities",
  "general_manufacturing",
];

const PERSONAS = [
  "operations_director",
  "maintenance_manager",
  "plant_manager",
  "cto_vp_engineering",
  "procurement",
  "c_suite",
];

const CHANNELS = ["email", "linkedin_connection", "linkedin_dm", "phone"];
const TONES = ["professional", "conversational", "direct", "consultative", "urgent"];

const TEMPLATE_VARS = [
  { name: "{{first_name}}", desc: "Contact first name" },
  { name: "{{company_name}}", desc: "Company name" },
  { name: "{{title}}", desc: "Contact job title" },
  { name: "{{industry}}", desc: "Industry vertical" },
  { name: "{{pain_points}}", desc: "Identified pain points" },
  { name: "{{research_summary}}", desc: "AI research summary" },
  { name: "{{technology_stack}}", desc: "Known tech stack" },
  { name: "{{sender_name}}", desc: "Your name" },
  { name: "{{sender_title}}", desc: "Your title" },
  { name: "{{company}}", desc: "Your company" },
];

// ─── Step Card ────────────────────────────────────────────────────────────────

function StepCard({
  step,
  stepIndex,
  totalSteps,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: {
  step: StepState;
  stepIndex: number;
  totalSteps: number;
  onChange: (partial: Partial<StepState>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  return (
    <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
      {/* Step header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-100 dark:border-zinc-800">
        <div className="w-6 h-6 rounded-full bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold flex items-center justify-center flex-shrink-0">
          {stepIndex + 1}
        </div>
        <input
          value={step.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder={`Step ${stepIndex + 1} name`}
          className="flex-1 text-sm font-medium bg-transparent text-zinc-900 dark:text-zinc-100 focus:outline-none placeholder-zinc-400"
        />
        <div className="flex items-center gap-1 ml-auto">
          <button
            onClick={onMoveUp}
            disabled={stepIndex === 0}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 disabled:opacity-30"
          >
            <ChevronUp className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onMoveDown}
            disabled={stepIndex === totalSteps - 1}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 disabled:opacity-30"
          >
            <ChevronDown className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onChange({ collapsed: !step.collapsed })}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400"
          >
            {step.collapsed ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronUp className="w-3.5 h-3.5" />
            )}
          </button>
          {totalSteps > 1 && (
            <button
              onClick={onRemove}
              className="p-1 rounded hover:bg-rose-50 dark:hover:bg-rose-950/20 text-zinc-400 hover:text-rose-500"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {!step.collapsed && (
        <div className="p-4 space-y-4">
          {/* Row 1: channel + delay */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
                Channel
              </label>
              <select
                value={step.channel}
                onChange={(e) => onChange({ channel: e.target.value })}
                className="w-full px-3 py-1.5 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
              >
                {CHANNELS.map((c) => (
                  <option key={c} value={c}>{c.replace(/_/g, " ")}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
                Delay (days after previous)
              </label>
              <input
                type="number"
                min={0}
                max={90}
                value={step.delay_days}
                onChange={(e) => onChange({ delay_days: parseInt(e.target.value) || 0 })}
                className="w-full px-3 py-1.5 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
              />
            </div>
          </div>

          {/* Subject template */}
          {(step.channel === "email") && (
            <div>
              <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
                Subject Template
              </label>
              <input
                value={step.subject_template}
                onChange={(e) => onChange({ subject_template: e.target.value })}
                placeholder="e.g. Quick question about {{company_name}}'s maintenance ops"
                className="w-full px-3 py-1.5 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
              />
            </div>
          )}

          {/* AI instructions */}
          <div>
            <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
              AI Instructions
            </label>
            <textarea
              value={step.ai_instructions}
              onChange={(e) => onChange({ ai_instructions: e.target.value })}
              rows={3}
              placeholder="Guide the AI on what this step should accomplish, what angle to take, what to reference..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100 resize-none"
            />
          </div>

          {/* Row 2: tone + max_words */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
                Tone
              </label>
              <select
                value={step.tone}
                onChange={(e) => onChange({ tone: e.target.value })}
                className="w-full px-3 py-1.5 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                {TONES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
                Max Words
              </label>
              <input
                type="number"
                min={50}
                max={500}
                step={25}
                value={step.max_words}
                onChange={(e) => onChange({ max_words: parseInt(e.target.value) || 150 })}
                className="w-full px-3 py-1.5 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function SequenceEditPage() {
  const params = useParams();
  const router = useRouter();
  const sequenceId = params.id as string;

  const [loadingSequence, setLoadingSequence] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [cluster, setCluster] = useState(CLUSTERS[0]);
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [channel, setChannel] = useState("email");
  const [replyAdaptive, setReplyAdaptive] = useState(true);
  const [dailyLimit, setDailyLimit] = useState(50);
  const [status, setStatus] = useState<"active" | "draft" | "archived">("draft");
  const [steps, setSteps] = useState<StepState[]>([
    {
      step: 1,
      name: "Opening Email",
      channel: "email",
      delay_days: 0,
      subject_template: "",
      ai_instructions: "",
      tone: "professional",
      max_words: 150,
      collapsed: false,
    },
  ]);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Load existing sequence
  useEffect(() => {
    const load = async () => {
      try {
        const res = await getSequenceTemplates();
        const all = [...res.built_in, ...res.custom];
        const found = all.find(
          (s) => s.name === sequenceId || s.id === sequenceId
        );
        if (!found) {
          setNotFound(true);
          return;
        }

        setName(found.name);
        setDisplayName(found.display_name || "");
        setDescription(found.description || "");
        setChannel(found.channel || "email");

        if (found.steps && found.steps.length > 0) {
          setSteps(
            found.steps.map((s, i) => ({
              step: s.step,
              name: s.name || `Step ${i + 1}`,
              channel: s.channel || found.channel || "email",
              delay_days: s.delay_days || 0,
              subject_template: (s.instructions?.subject_template as string) || "",
              ai_instructions: (s.instructions?.ai_instructions as string) || "",
              tone: (s.instructions?.tone as string) || "professional",
              max_words: (s.instructions?.max_words as number) || 150,
              collapsed: false,
            }))
          );
        }
      } catch {
        setNotFound(true);
      } finally {
        setLoadingSequence(false);
      }
    };
    load();
  }, [sequenceId]);

  const addStep = () => {
    setSteps((prev) => [
      ...prev,
      {
        step: prev.length + 1,
        name: `Step ${prev.length + 1}`,
        channel,
        delay_days: 3,
        subject_template: "",
        ai_instructions: "",
        tone: "professional",
        max_words: 150,
        collapsed: false,
      },
    ]);
  };

  const removeStep = (idx: number) => {
    setSteps((prev) =>
      prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, step: i + 1 }))
    );
  };

  const updateStep = (idx: number, partial: Partial<StepState>) => {
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...partial } : s)));
  };

  const moveStep = (idx: number, dir: "up" | "down") => {
    const newSteps = [...steps];
    const target = dir === "up" ? idx - 1 : idx + 1;
    if (target < 0 || target >= newSteps.length) return;
    [newSteps[idx], newSteps[target]] = [newSteps[target], newSteps[idx]];
    setSteps(newSteps.map((s, i) => ({ ...s, step: i + 1 })));
  };

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveSequenceTemplate({
        name: name.trim(),
        display_name: displayName.trim() || name.trim(),
        description: description.trim(),
        channel,
        cluster: cluster || undefined,
        personas: selectedPersonas.length > 0 ? selectedPersonas : undefined,
        steps: steps.map((s) => ({
          step: s.step,
          name: s.name,
          channel: s.channel,
          delay_days: s.delay_days,
          subject_template: s.subject_template || undefined,
          instructions: {
            subject_template: s.subject_template,
            ai_instructions: s.ai_instructions,
            tone: s.tone,
            max_words: s.max_words,
          },
        })),
      });
      router.push("/sequences");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const togglePersona = (p: string) => {
    setSelectedPersonas((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
    );
  };

  if (loadingSequence) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-amber-500" />
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-4">
            Sequence &quot;{sequenceId}&quot; not found.
          </p>
          <button
            onClick={() => router.push("/sequences")}
            className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-sm text-white dark:text-zinc-900"
          >
            Back to Sequences
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex items-center gap-3">
        <button
          onClick={() => router.push("/sequences")}
          className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="flex-1">
          <h1 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            Edit Sequence
          </h1>
          <p className="text-xs text-zinc-400">{name}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => router.push("/sequences")}
            className="px-3 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-sm font-medium text-white dark:text-zinc-900 hover:bg-zinc-700 dark:hover:bg-zinc-300 disabled:opacity-50"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save Changes
          </button>
        </div>
      </div>

      {saveError && (
        <div className="mx-6 mt-4 p-3 rounded-lg bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800 text-sm text-rose-600 dark:text-rose-400 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {saveError}
        </div>
      )}

      {/* Three-column layout */}
      <div className="flex h-[calc(100vh-64px)]">
        {/* Left sidebar — Settings */}
        <div className="w-60 flex-shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-y-auto p-5 space-y-5">
          <div>
            <label className="block text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-3">
              Sequence Settings
            </label>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Internal Name</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. machinery_tier1_v2"
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
                />
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Display Name</label>
                <input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="e.g. Machinery Tier 1"
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
                />
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Cluster</label>
                <select
                  value={cluster}
                  onChange={(e) => setCluster(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  <option value="">— Any cluster —</option>
                  {CLUSTERS.map((c) => (
                    <option key={c} value={c}>{c.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Target Personas</label>
                <div className="space-y-1">
                  {PERSONAS.map((p) => (
                    <label key={p} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedPersonas.includes(p)}
                        onChange={() => togglePersona(p)}
                        className="w-3 h-3 rounded"
                      />
                      <span className="text-xs text-zinc-600 dark:text-zinc-400">
                        {p.replace(/_/g, " ")}
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Description</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  placeholder="What this sequence is for..."
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none resize-none"
                />
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Primary Channel</label>
                <select
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  {CHANNELS.map((c) => (
                    <option key={c} value={c}>{c.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={replyAdaptive}
                    onChange={(e) => setReplyAdaptive(e.target.checked)}
                    className="w-3 h-3 rounded"
                  />
                  <span className="text-xs text-zinc-600 dark:text-zinc-400">
                    Reply-adaptive (pause on reply)
                  </span>
                </label>
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Daily Send Limit</label>
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={dailyLimit}
                  onChange={(e) => setDailyLimit(parseInt(e.target.value) || 50)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs text-zinc-500 mb-1">Status</label>
                <div className="space-y-1">
                  {(["active", "draft", "archived"] as const).map((s) => (
                    <label key={s} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="status"
                        value={s}
                        checked={status === s}
                        onChange={() => setStatus(s)}
                        className="w-3 h-3"
                      />
                      <span className="text-xs text-zinc-600 dark:text-zinc-400 capitalize">{s}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Center — Step timeline */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-2xl mx-auto space-y-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                Steps ({steps.length})
              </h2>
              <button
                onClick={addStep}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Step
              </button>
            </div>

            {steps.map((step, idx) => (
              <div key={idx} className="relative">
                {idx > 0 && (
                  <div className="flex items-center gap-2 mb-3 px-2">
                    <div className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800" />
                    <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800">
                      <span className="text-[10px] text-zinc-500">wait</span>
                      <input
                        type="number"
                        min={0}
                        max={90}
                        value={step.delay_days}
                        onChange={(e) =>
                          updateStep(idx, { delay_days: parseInt(e.target.value) || 0 })
                        }
                        className="w-8 text-center text-xs bg-transparent text-zinc-700 dark:text-zinc-300 focus:outline-none"
                      />
                      <span className="text-[10px] text-zinc-500">days</span>
                    </div>
                    <div className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800" />
                  </div>
                )}
                <StepCard
                  step={step}
                  stepIndex={idx}
                  totalSteps={steps.length}
                  onChange={(partial) => updateStep(idx, partial)}
                  onRemove={() => removeStep(idx)}
                  onMoveUp={() => moveStep(idx, "up")}
                  onMoveDown={() => moveStep(idx, "down")}
                />
              </div>
            ))}

            <button
              onClick={addStep}
              className="w-full py-3 border-2 border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl text-sm text-zinc-400 hover:border-zinc-400 dark:hover:border-zinc-600 hover:text-zinc-600 dark:hover:text-zinc-400 transition-colors flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              Add Step
            </button>
          </div>
        </div>

        {/* Right sidebar — Variables */}
        <div className="w-52 flex-shrink-0 border-l border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-y-auto p-4">
          <div className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-3">
            Template Variables
          </div>
          <p className="text-[10px] text-zinc-400 mb-3">Click to copy to clipboard</p>
          <div className="space-y-1.5">
            {TEMPLATE_VARS.map((v) => (
              <button
                key={v.name}
                onClick={() => {
                  navigator.clipboard.writeText(v.name).catch(() => {});
                }}
                className="w-full text-left p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 group"
              >
                <div className="text-xs font-mono text-indigo-600 dark:text-indigo-400 group-hover:text-indigo-700 dark:group-hover:text-indigo-300 flex items-center gap-1">
                  {v.name}
                  <Copy className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100" />
                </div>
                <div className="text-[10px] text-zinc-400 mt-0.5">{v.desc}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
