"use client";

/**
 * Sequence Builder — Create a new sequence or template.
 */

import { useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus, Trash2, ChevronDown, ChevronUp, Copy, Loader2 } from "lucide-react";
import { saveSequenceTemplate, type SequenceStep } from "@/lib/api";
import { cn } from "@/lib/utils";

const CLUSTERS = ["machinery", "auto", "chemicals", "metals", "process", "fb", "other", "general"];
const PERSONAS = ["vp_ops", "coo", "plant_manager", "director_ops", "maintenance_leader", "digital_transformation", "general"];
const CHANNELS = ["email", "linkedin", "mixed"];

const VARIABLES = [
  { name: "{{company_name}}", desc: "Company name" },
  { name: "{{contact_name}}", desc: "Contact first name" },
  { name: "{{contact_title}}", desc: "Contact title" },
  { name: "{{pain_hook}}", desc: "AI-generated pain angle" },
  { name: "{{sub_sector}}", desc: "Industry sub-sector" },
  { name: "{{avi_sig}}", desc: "Avi's signature block" },
  { name: "{{value_prop}}", desc: "Digitillis value prop" },
  { name: "{{pilot_offer}}", desc: "6-8 week pilot offer" },
  { name: "{{roi_stat}}", desc: "ROI statistic from research" },
];

function emptyStep(stepNum: number): SequenceStep {
  return {
    step: stepNum,
    name: `step_${stepNum}`,
    channel: "email",
    delay_days: stepNum === 1 ? 0 : 3,
    subject_template: "",
    instructions: { description: "", tone: "Expert peer, not vendor", max_words: 120, anti_patterns: [] },
  };
}

export default function NewSequencePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isTemplate = searchParams.get("mode") === "template";

  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [cluster, setCluster] = useState("machinery");
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [channel, setChannel] = useState("email");
  const [replyAdaptive, setReplyAdaptive] = useState(true);
  const [dailyLimit, setDailyLimit] = useState(10);
  const [status, setStatus] = useState<"draft" | "active">("draft");
  const [steps, setSteps] = useState<SequenceStep[]>([emptyStep(1)]);
  const [collapsedSteps, setCollapsedSteps] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addStep = () => {
    setSteps((prev) => [...prev, emptyStep(prev.length + 1)]);
  };

  const removeStep = (stepNum: number) => {
    setSteps((prev) => {
      const filtered = prev.filter((s) => s.step !== stepNum);
      return filtered.map((s, i) => ({ ...s, step: i + 1, name: `step_${i + 1}` }));
    });
  };

  const updateStep = (stepNum: number, patch: Partial<SequenceStep>) => {
    setSteps((prev) => prev.map((s) => s.step === stepNum ? { ...s, ...patch } : s));
  };

  const updateInstruction = (stepNum: number, key: string, value: unknown) => {
    setSteps((prev) => prev.map((s) => s.step === stepNum ? { ...s, instructions: { ...s.instructions, [key]: value } } : s));
  };

  const toggleCollapse = (stepNum: number) => {
    setCollapsedSteps((prev) => { const n = new Set(prev); n.has(stepNum) ? n.delete(stepNum) : n.add(stepNum); return n; });
  };

  const handleSave = async (activate = false) => {
    if (!name.trim() || !displayName.trim()) {
      setError("Name and display name are required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveSequenceTemplate({
        name: name.trim().toLowerCase().replace(/\s+/g, "_"),
        display_name: displayName.trim(),
        description,
        channel,
        steps,
        cluster,
        personas: selectedPersonas,
      });
      router.push("/sequences");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const copyVariable = (v: string) => {
    navigator.clipboard.writeText(v).catch(() => {});
  };

  return (
    <div className="flex h-[calc(100vh-56px)] overflow-hidden -m-6">
      {/* Left sidebar */}
      <div className="w-60 shrink-0 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-y-auto p-5 space-y-5">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">
            {isTemplate ? "Template Settings" : "Sequence Settings"}
          </h2>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Sequence Key <span className="text-red-500">*</span></label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="machinery_vp_ops" className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Display Name <span className="text-red-500">*</span></label>
              <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Machinery VP Ops" className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Cluster</label>
              <select value={cluster} onChange={(e) => setCluster(e.target.value)} className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none">
                {CLUSTERS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Persona</label>
              <div className="space-y-1">
                {PERSONAS.map((p) => (
                  <label key={p} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedPersonas.includes(p)}
                      onChange={(e) => setSelectedPersonas((prev) => e.target.checked ? [...prev, p] : prev.filter((x) => x !== p))}
                      className="h-3.5 w-3.5 rounded"
                    />
                    <span className="text-xs text-gray-700 dark:text-gray-300">{p}</span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400 resize-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Channel</label>
              <select value={channel} onChange={(e) => setChannel(e.target.value)} className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs focus:outline-none">
                {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={replyAdaptive} onChange={(e) => setReplyAdaptive(e.target.checked)} className="h-3.5 w-3.5 rounded" />
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Reply-adaptive</span>
              </label>
              <p className="text-[10px] text-gray-400 dark:text-gray-500 ml-5 mt-0.5">Auto-classify replies and route to response template</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Daily send limit</label>
              <input type="number" value={dailyLimit} onChange={(e) => setDailyLimit(parseInt(e.target.value) || 10)} min={1} max={100} className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Status</label>
              <div className="flex items-center gap-3">
                {(["draft", "active"] as const).map((s) => (
                  <label key={s} className="flex items-center gap-1.5 cursor-pointer">
                    <input type="radio" value={s} checked={status === s} onChange={() => setStatus(s)} className="h-3.5 w-3.5" />
                    <span className="text-xs text-gray-700 dark:text-gray-300 capitalize">{s}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
          <button onClick={() => handleSave(false)} disabled={saving} className="w-full rounded-md bg-gray-900 dark:bg-white px-3 py-2 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-50">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin mx-auto" /> : "Save"}
          </button>
          <button onClick={() => router.push("/sequences")} className="w-full rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
            Cancel
          </button>
        </div>
      </div>

      {/* Center: Step timeline */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {isTemplate ? "Build Template" : "Build Sequence"} — {steps.length} step{steps.length !== 1 ? "s" : ""}
            </h1>
          </div>

          <div className="space-y-4">
            {steps.map((step, idx) => {
              const collapsed = collapsedSteps.has(step.step);
              return (
                <div key={step.step}>
                  <div className="flex items-stretch gap-3">
                    {/* Step indicator */}
                    <div className="flex flex-col items-center">
                      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-[10px] font-bold shrink-0">{step.step}</div>
                      {idx < steps.length - 1 && <div className="flex-1 w-px bg-gray-200 dark:bg-gray-700 mt-2" />}
                    </div>

                    {/* Step card */}
                    <div className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 mb-4">
                      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                        <div className="flex items-center gap-3">
                          <span className="font-medium text-sm text-gray-900 dark:text-gray-100">Step {step.step}</span>
                          <span className="text-xs text-gray-400 dark:text-gray-500">Day {step.delay_days}</span>
                          <select value={step.channel} onChange={(e) => updateStep(step.step, { channel: e.target.value })} className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-0.5 text-xs focus:outline-none">
                            {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        </div>
                        <div className="flex items-center gap-1">
                          <button onClick={() => removeStep(step.step)} disabled={steps.length === 1} className="rounded p-1 text-gray-400 hover:text-red-500 disabled:opacity-30">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                          <button onClick={() => toggleCollapse(step.step)} className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                            {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
                          </button>
                        </div>
                      </div>

                      {!collapsed && (
                        <div className="p-4 space-y-3">
                          <div>
                            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Subject A</label>
                            <input
                              type="text"
                              value={step.subject_template ?? ""}
                              onChange={(e) => updateStep(step.step, { subject_template: e.target.value })}
                              placeholder="{{company_name}} — {{pain_hook}}"
                              className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400"
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">AI Instructions</label>
                            <textarea
                              value={typeof step.instructions.description === "string" ? step.instructions.description : ""}
                              onChange={(e) => updateInstruction(step.step, "description", e.target.value)}
                              rows={3}
                              placeholder="Lead with the specific operational cost of unplanned downtime..."
                              className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400 resize-none"
                            />
                          </div>
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Tone</label>
                              <input
                                type="text"
                                value={typeof step.instructions.tone === "string" ? step.instructions.tone : "Expert peer, not vendor"}
                                onChange={(e) => updateInstruction(step.step, "tone", e.target.value)}
                                className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs focus:outline-none"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Max words</label>
                              <input
                                type="number"
                                value={typeof step.instructions.max_words === "number" ? step.instructions.max_words : 120}
                                onChange={(e) => updateInstruction(step.step, "max_words", parseInt(e.target.value) || 120)}
                                className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs focus:outline-none"
                              />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Gap between steps */}
                  {idx < steps.length - 1 && (
                    <div className="flex items-center gap-3 mb-2 ml-9">
                      <span className="text-xs text-gray-400 dark:text-gray-500">Gap:</span>
                      <input
                        type="number"
                        value={steps[idx + 1]?.delay_days ?? 3}
                        onChange={(e) => updateStep(steps[idx + 1].step, { delay_days: parseInt(e.target.value) || 0 })}
                        min={0}
                        className="w-16 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-0.5 text-xs focus:outline-none"
                      />
                      <span className="text-xs text-gray-400 dark:text-gray-500">days</span>
                    </div>
                  )}
                </div>
              );
            })}

            <button onClick={addStep} className="ml-9 inline-flex items-center gap-1.5 rounded-md border-2 border-dashed border-gray-300 dark:border-gray-600 px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500 hover:text-gray-700 dark:hover:text-gray-200">
              <Plus className="h-3.5 w-3.5" /> Add Step
            </button>
          </div>
        </div>
      </div>

      {/* Right sidebar: Variables */}
      <div className="w-56 shrink-0 border-l border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/30 overflow-y-auto p-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">Variables</p>
        <div className="space-y-2">
          {VARIABLES.map((v) => (
            <button
              key={v.name}
              onClick={() => copyVariable(v.name)}
              className="block w-full text-left rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2.5 py-2 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              title={`Click to copy ${v.name}`}
            >
              <p className="font-mono text-[10px] text-gray-700 dark:text-gray-300">{v.name}</p>
              <p className="text-[10px] text-gray-400 dark:text-gray-500">{v.desc}</p>
            </button>
          ))}
        </div>
        <p className="mt-3 text-[10px] text-gray-400 dark:text-gray-500 text-center">Click any variable to copy</p>
      </div>
    </div>
  );
}
