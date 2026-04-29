"use client";

import { useState } from "react";
import {
  Wand2, ChevronRight, Loader2, CheckCircle2, AlertCircle,
  Target, Mail, Linkedin, BarChart2, Calendar, ArrowLeft,
  Play,
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const HEADERS = { "Content-Type": "application/json" };

type Step = "compose" | "review_plan" | "review_variants" | "confirm" | "done";

export default function ComposerPage() {
  const [step, setStep] = useState<Step>("compose");
  const [request, setRequest] = useState("");
  const [plan, setPlan] = useState<any>(null);
  const [variants, setVariants] = useState<any[]>([]);
  const [sequenceName, setSequenceName] = useState("");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function composePlan() {
    if (request.trim().length < 10) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/composer/plan`, {
        method: "POST",
        headers: HEADERS,
        credentials: "include",
        body: JSON.stringify({ request }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || "Plan generation failed.");
      }
      const d = await res.json();
      setPlan(d.plan);
      setSequenceName(d.plan.hypothesis?.slice(0, 60) || "New Campaign");
      setStep("review_plan");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function generateVariants() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/composer/variants`, {
        method: "POST",
        headers: HEADERS,
        credentials: "include",
        body: JSON.stringify({ plan }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || "Variant generation failed.");
      }
      const d = await res.json();
      setVariants(d.variants || []);
      setStep("review_variants");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function confirmCampaign() {
    if (!sequenceName.trim()) {
      setError("Sequence name is required.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/composer/confirm`, {
        method: "POST",
        headers: HEADERS,
        credentials: "include",
        body: JSON.stringify({ plan, variants, sequence_name: sequenceName }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || "Confirmation failed.");
      }
      const d = await res.json();
      setResult(d);
      setStep("done");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setStep("compose");
    setRequest("");
    setPlan(null);
    setVariants([]);
    setResult(null);
    setError(null);
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Wand2 className="w-6 h-6 text-purple-600" />
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Campaign Composer</h1>
          <p className="text-sm text-gray-500">Describe what you want to achieve — Claude plans and writes it.</p>
        </div>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 text-sm">
        {(["compose", "review_plan", "review_variants", "confirm", "done"] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
              s === step ? "bg-purple-600 text-white" :
              ["compose", "review_plan", "review_variants", "confirm", "done"].indexOf(step) > i
                ? "bg-green-500 text-white" : "bg-gray-200 text-gray-500"
            }`}>{i + 1}</span>
            <span className={`hidden sm:block capitalize ${s === step ? "text-gray-900 font-medium" : "text-gray-400"}`}>
              {s.replace("_", " ")}
            </span>
            {i < 4 && <ChevronRight className="w-3 h-3 text-gray-300" />}
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-center gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
          <button onClick={() => setError(null)} className="ml-auto">×</button>
        </div>
      )}

      {/* Step: Compose */}
      {step === "compose" && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
          <label className="block text-sm font-medium text-gray-700">
            Describe your campaign
          </label>
          <textarea
            className="w-full border border-gray-300 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
            rows={5}
            placeholder={`Examples:\n"Find 20 Tier 1 discrete manufacturers in the Midwest that recently posted a Maintenance Manager job and send a 3-step email sequence about predictive maintenance ROI"\n\n"Target COOs at mid-size F&B companies with a LinkedIn outreach about FSMA compliance automation"`}
            value={request}
            onChange={e => setRequest(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) composePlan();
            }}
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-400">⌘ + Enter to generate</p>
            <button
              onClick={composePlan}
              disabled={loading || request.trim().length < 10}
              className="flex items-center gap-2 px-5 py-2.5 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {loading ? "Planning..." : "Generate Plan"}
            </button>
          </div>
        </div>
      )}

      {/* Step: Review plan */}
      {step === "review_plan" && plan && (
        <div className="space-y-4">
          <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
            <h2 className="font-medium text-gray-900">Review Campaign Plan</h2>

            <div className="space-y-1">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Hypothesis</p>
              <p className="text-sm text-gray-900 italic">"{plan.hypothesis}"</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="bg-gray-50 rounded-lg p-4 space-y-1">
                <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <Target className="w-3.5 h-3.5" /> Target Segment
                </div>
                <p className="text-sm text-gray-900">{plan.target_segment?.description}</p>
                <p className="text-xs text-gray-400">
                  ~{plan.target_segment?.actual_reach ?? plan.target_segment?.estimated_reach ?? "?"} contacts
                </p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4 space-y-1">
                <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <BarChart2 className="w-3.5 h-3.5" /> Success Metrics
                </div>
                <p className="text-sm text-gray-900 capitalize">
                  {plan.success_metrics?.primary?.replace("_", " ")}:{" "}
                  <span className="font-medium">{plan.success_metrics?.target_pct}%</span>
                </p>
                <p className="text-xs text-gray-400">
                  {plan.success_metrics?.secondary?.replace("_", " ")}: {plan.success_metrics?.target_secondary_pct}%
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <Calendar className="w-3.5 h-3.5" /> Schedule
                </div>
                <p className="text-sm text-gray-900">
                  {plan.schedule?.sequence_steps} steps ·{" "}
                  {plan.schedule?.send_days?.join(", ")}
                </p>
                <p className="text-xs text-gray-400">
                  Waits: {plan.schedule?.step_wait_days?.join(", ")} days
                </p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Channels
                </div>
                <div className="flex gap-2">
                  {plan.channels?.includes("email") && (
                    <span className="flex items-center gap-1 text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded-full">
                      <Mail className="w-3 h-3" /> Email
                    </span>
                  )}
                  {plan.channels?.includes("linkedin") && (
                    <span className="flex items-center gap-1 text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full">
                      <Linkedin className="w-3 h-3" /> LinkedIn
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400">{plan.n_variants} variants (A/B)</p>
              </div>
            </div>

            {plan.variant_themes?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Variant Themes</p>
                <div className="flex gap-2 flex-wrap">
                  {plan.variant_themes.map((theme: string, i: number) => (
                    <span key={i} className="text-sm bg-purple-50 text-purple-700 px-3 py-1 rounded-full border border-purple-200">
                      {String.fromCharCode(65 + i)}: {theme}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <p className="text-xs text-gray-500 italic border-t pt-3">{plan.rationale}</p>
          </div>

          <div className="flex gap-3">
            <button onClick={reset} className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-lg hover:bg-gray-50">
              <ArrowLeft className="w-4 h-4" /> Start Over
            </button>
            <button
              onClick={generateVariants}
              disabled={loading}
              className="flex items-center gap-2 px-5 py-2 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-700 disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {loading ? "Writing templates..." : "Generate Templates"}
            </button>
          </div>
        </div>
      )}

      {/* Step: Review variants */}
      {step === "review_variants" && variants.length > 0 && (
        <div className="space-y-4">
          <h2 className="font-medium text-gray-900">Review Message Templates</h2>
          {variants.map((v: any) => (
            <div key={v.variant} className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-900">Variant {v.variant}: {v.theme}</span>
                {v.valid ? (
                  <span className="flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-1 rounded-full">
                    <CheckCircle2 className="w-3 h-3" /> Valid
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-red-600 bg-red-50 px-2 py-1 rounded-full">
                    <AlertCircle className="w-3 h-3" /> Issues
                  </span>
                )}
              </div>

              {v.validation_warnings?.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700">
                  {v.validation_warnings.map((w: string, i: number) => <p key={i}>⚠ {w}</p>)}
                </div>
              )}

              {v.email && (
                <div className="space-y-3">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1">
                    <Mail className="w-3 h-3" /> Email Templates
                  </p>
                  <div className="bg-gray-50 rounded-lg p-3 text-xs space-y-1">
                    <p className="font-medium text-gray-700">Subject A: {v.email.subject_a}</p>
                    <p className="text-gray-500">Subject B: {v.email.subject_b}</p>
                  </div>
                  {[1, 2, 3].map(step => v.email[`body_step${step}`] && (
                    <div key={step} className="bg-gray-50 rounded-lg p-3">
                      <p className="text-xs font-medium text-gray-500 mb-1">Step {step}</p>
                      <p className="text-xs text-gray-700 whitespace-pre-wrap line-clamp-4">
                        {v.email[`body_step${step}`]}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {v.linkedin && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1">
                    <Linkedin className="w-3 h-3" /> LinkedIn Templates
                  </p>
                  <div className="bg-gray-50 rounded-lg p-3 text-xs">
                    <p className="font-medium text-gray-700 mb-1">Connect note ({v.linkedin.connect_note?.length} chars):</p>
                    <p className="text-gray-700 italic">"{v.linkedin.connect_note}"</p>
                  </div>
                </div>
              )}
            </div>
          ))}

          <div className="flex gap-3">
            <button onClick={() => setStep("review_plan")} className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-lg hover:bg-gray-50">
              <ArrowLeft className="w-4 h-4" /> Back to Plan
            </button>
            <button
              onClick={generateVariants}
              disabled={loading}
              className="px-4 py-2 border border-purple-300 text-purple-700 text-sm rounded-lg hover:bg-purple-50 disabled:opacity-50"
            >
              Regenerate
            </button>
            <button
              onClick={() => setStep("confirm")}
              disabled={variants.some(v => !v.valid)}
              className="flex items-center gap-2 px-5 py-2 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-700 disabled:opacity-50"
            >
              <ChevronRight className="w-4 h-4" /> Approve Templates
            </button>
          </div>
        </div>
      )}

      {/* Step: Confirm */}
      {step === "confirm" && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="font-medium text-gray-900">Launch Campaign</h2>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Sequence name</label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              value={sequenceName}
              onChange={e => setSequenceName(e.target.value)}
              placeholder="Name your sequence..."
            />
          </div>
          <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 text-sm text-purple-800 space-y-1">
            <p className="font-medium">What happens when you confirm:</p>
            <p>· Sequence created with {plan?.schedule?.sequence_steps} steps</p>
            <p>· {variants.length} variant{variants.length !== 1 ? "s" : ""} ready for A/B testing</p>
            <p>· Matching contacts enrolled (sends start at next scheduled window)</p>
          </div>
          <div className="flex gap-3">
            <button onClick={() => setStep("review_variants")} className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-lg hover:bg-gray-50">
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            <button
              onClick={confirmCampaign}
              disabled={loading || !sequenceName.trim()}
              className="flex items-center gap-2 px-5 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {loading ? "Launching..." : "Launch Campaign"}
            </button>
          </div>
        </div>
      )}

      {/* Step: Done */}
      {step === "done" && result && (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center space-y-4">
          <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto" />
          <h2 className="text-xl font-semibold text-gray-900">Campaign Launched</h2>
          <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 space-y-2 text-left max-w-sm mx-auto">
            <p>Sequence: <span className="font-medium">{result.sequence_name}</span></p>
            <p>Contacts enrolled: <span className="font-medium">{result.enrolled_contacts}</span></p>
            <p>Variants: <span className="font-medium">{result.variants_created}</span></p>
          </div>
          <p className="text-xs text-gray-400 italic max-w-sm mx-auto">"{result.hypothesis}"</p>
          <div className="flex gap-3 justify-center pt-2">
            <button onClick={reset} className="px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded-lg hover:bg-gray-50">
              New Campaign
            </button>
            <a href="/sequences" className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700">
              View Sequences
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
