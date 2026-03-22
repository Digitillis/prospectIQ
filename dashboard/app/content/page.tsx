"use client";

import { useState, useEffect, useCallback } from "react";
import {
  PenTool,
  RefreshCw,
  Copy,
  Check,
  Edit2,
  CheckCircle2,
  Loader2,
  Calendar,
  ChevronDown,
  ChevronUp,
  Sparkles,
  AlertCircle,
  Zap,
} from "lucide-react";
import {
  getContentCalendar,
  generateContent,
  generateContentBatch,
  getContentDrafts,
  markContentPosted,
  autoGenerateCalendar,
  type ContentDraft,
  type AutoCalendarPost,
  type AutoCalendarResponse,
} from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CalendarEntry {
  week: number;
  day: string;
  format: string;
  pillar: string;
  topic: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const FORMAT_LABELS: Record<string, string> = {
  data_insight: "Data Insight",
  framework: "Framework",
  contrarian: "Contrarian",
  benchmark: "Benchmark",
};

const PILLAR_LABELS: Record<string, string> = {
  food_safety: "F&B",
  food_safety_compliance: "F&B",
  predictive_maintenance: "Mfg",
  ops_excellence: "Ops",
  leadership: "Leadership",
  leadership_strategy: "Leadership",
};

const PILLAR_COLORS: Record<string, string> = {
  food_safety: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  food_safety_compliance: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  predictive_maintenance: "bg-blue-900/40 text-blue-300 border-blue-700/40",
  ops_excellence: "bg-violet-900/40 text-violet-300 border-violet-700/40",
  leadership: "bg-amber-900/40 text-amber-300 border-amber-700/40",
  leadership_strategy: "bg-amber-900/40 text-amber-300 border-amber-700/40",
};

const FORMAT_COLORS: Record<string, string> = {
  data_insight: "bg-slate-800 text-slate-300",
  framework: "bg-slate-800 text-slate-300",
  contrarian: "bg-slate-800 text-slate-300",
  benchmark: "bg-slate-800 text-slate-300",
};

const CHAR_LIMIT = 1300;
const CHAR_WARN = 1100;

// Dropdown option sets
const PILLAR_OPTIONS = [
  { value: "", label: "All Themes" },
  // Food & Beverage
  { value: "food_safety", label: "Food Safety & Compliance (all)" },
  { value: "food_safety:fsma", label: "FSMA & FDA Enforcement" },
  { value: "food_safety:haccp", label: "HACCP & CCP Management" },
  { value: "food_safety:allergen", label: "Allergen Control & Traceability" },
  { value: "food_safety:audit", label: "Audit Readiness & SQF/BRC" },
  { value: "food_safety:cold_chain", label: "Cold Chain & Temperature Control" },
  // Manufacturing
  { value: "predictive_maintenance", label: "Predictive Maintenance (all)" },
  { value: "predictive_maintenance:oee", label: "OEE & Downtime Analysis" },
  { value: "predictive_maintenance:cbm", label: "Condition-Based Monitoring" },
  { value: "predictive_maintenance:sensors", label: "Sensors & Data Infrastructure" },
  { value: "predictive_maintenance:rul", label: "Remaining Useful Life & Prognostics" },
  // Operations
  { value: "ops_excellence", label: "Manufacturing Operations (all)" },
  { value: "ops_excellence:i40", label: "Industry 4.0 & Digital Transformation" },
  { value: "ops_excellence:energy", label: "Energy & Sustainability" },
  { value: "ops_excellence:quality", label: "Quality Management & SPC" },
  { value: "ops_excellence:supply_chain", label: "Supply Chain Resilience" },
  // Leadership
  { value: "leadership", label: "Manufacturing Leadership (all)" },
  { value: "leadership:workforce", label: "Workforce & Skills Gap" },
  { value: "leadership:culture", label: "Data-Driven Culture" },
  { value: "leadership:capex", label: "Capital Allocation & ROI" },
  { value: "leadership:pilots", label: "Technology Pilot Programs" },
];

const TIME_HORIZON_OPTIONS = [
  { value: "single", label: "Single Post" },
  { value: "1_week", label: "1 Week (4 posts)" },
  { value: "30_days", label: "30 Days (16 posts)" },
  { value: "60_days", label: "60 Days (32 posts)" },
];

const FORMAT_OPTIONS = [
  { value: "", label: "All Formats" },
  { value: "data_insight", label: "Data Insight" },
  { value: "framework", label: "Framework" },
  { value: "contrarian", label: "Contrarian Take" },
  { value: "benchmark", label: "Industry Benchmark" },
];

const TIME_HORIZON_COUNTS: Record<string, number> = {
  "1_week": 4,
  "30_days": 16,
  "60_days": 32,
};

// ─── Week selector helpers ─────────────────────────────────────────────────────

function getCurrentWeek(): number {
  const now = new Date();
  const startOfYear = new Date(now.getFullYear(), 0, 1);
  const weekNumber = Math.ceil(
    ((now.getTime() - startOfYear.getTime()) / 86400000 + startOfYear.getDay() + 1) / 7
  );
  return ((weekNumber - 1) % 4) + 1;
}

function getWeekLabel(week: number): string {
  const now = new Date();
  const day = now.getDay();
  const daysToMonday = day === 0 ? 1 : 8 - day;
  const monday = new Date(now);
  monday.setDate(now.getDate() + daysToMonday - 7);
  monday.setDate(monday.getDate() + (week - 1) * 7);
  return monday.toLocaleDateString("en-US", { month: "long", day: "numeric" });
}

/** Compute a posting date string (Mon/Wed/Fri pattern) for a given post index. */
function getScheduledDate(postIndex: number): string {
  const now = new Date();
  const day = now.getDay();
  const daysToMonday = day === 0 ? 1 : day === 1 ? 0 : 8 - day;
  const nextMonday = new Date(now);
  nextMonday.setDate(now.getDate() + daysToMonday);

  // Posts go Mon/Tue/Thu/Fri within each week
  const POSTING_DAYS = [0, 1, 3, 4]; // offsets from Monday
  const weekOffset = Math.floor(postIndex / 4) * 7;
  const dayOffset = POSTING_DAYS[postIndex % 4];

  const postDate = new Date(nextMonday);
  postDate.setDate(nextMonday.getDate() + weekOffset + dayOffset);
  return postDate.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

// ─── Shared Select component ──────────────────────────────────────────────────

function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  label: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:outline-none"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ─── Batch Draft Card ─────────────────────────────────────────────────────────

function BatchDraftCard({
  draft,
  index,
  onRegenerate,
  onMarkPosted,
}: {
  draft: ContentDraft;
  index: number;
  onRegenerate: (topic: string, pillar: string, format: string) => void;
  onMarkPosted: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState(draft.post_text);
  const [copied, setCopied] = useState(false);
  const [markingPosted, setMarkingPosted] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const currentText = editing ? editedText : draft.post_text;
  const charCount = currentText.length;
  const isOver = charCount > CHAR_LIMIT;
  const isWarning = charCount > CHAR_WARN && !isOver;
  const scheduledDate = getScheduledDate(index);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(currentText);
    } catch {
      const el = document.createElement("textarea");
      el.value = currentText;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-700/40">
        <div className="flex items-center gap-2 min-w-0">
          <span className="shrink-0 text-xs font-medium text-slate-500 tabular-nums">
            #{index + 1}
          </span>
          <span className="shrink-0 text-xs text-slate-400">{scheduledDate}</span>
          <span
            className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${
              PILLAR_COLORS[draft.pillar] ?? "bg-slate-800 text-slate-300"
            }`}
          >
            {PILLAR_LABELS[draft.pillar] ?? draft.pillar}
          </span>
          <span
            className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${
              FORMAT_COLORS[draft.format] ?? "bg-slate-800 text-slate-300"
            }`}
          >
            {FORMAT_LABELS[draft.format] ?? draft.format}
          </span>
          <span className="truncate text-sm font-medium text-slate-200 ml-1">
            {draft.topic}
          </span>
        </div>
      </div>

      {/* Post body */}
      <div className="px-4 py-3">
        {editing ? (
          <textarea
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            className="w-full min-h-[180px] resize-y rounded-lg bg-slate-900 border border-slate-600 p-3 text-sm text-slate-200 font-mono leading-relaxed focus:outline-none focus:border-blue-500"
            autoFocus
          />
        ) : (
          <pre className="whitespace-pre-wrap text-sm text-slate-300 leading-relaxed font-sans">
            {draft.post_text}
          </pre>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-slate-700/40 bg-slate-900/30">
        <span
          className={`text-sm font-mono tabular-nums ${
            isOver
              ? "text-red-400 font-semibold"
              : isWarning
              ? "text-amber-400"
              : "text-slate-500"
          }`}
        >
          {charCount.toLocaleString()} / {CHAR_LIMIT.toLocaleString()} chars
          {isOver && " — over limit"}
        </span>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-400" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? "Copied!" : "Copy"}
          </button>

          <button
            onClick={() => {
              if (editing) setEditedText(draft.post_text);
              setEditing(!editing);
            }}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              editing
                ? "bg-slate-700 hover:bg-slate-600 text-slate-400"
                : "bg-slate-700 hover:bg-slate-600 text-slate-200"
            }`}
          >
            <Edit2 className="h-3.5 w-3.5" />
            {editing ? "Cancel" : "Edit"}
          </button>

          <button
            onClick={async () => {
              setRegenerating(true);
              try {
                await onRegenerate(draft.topic, draft.pillar, draft.format);
              } finally {
                setRegenerating(false);
              }
            }}
            disabled={regenerating}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} />
            Regenerate
          </button>

          <button
            onClick={async () => {
              setMarkingPosted(true);
              try {
                await onMarkPosted(draft.id);
              } finally {
                setMarkingPosted(false);
              }
            }}
            disabled={markingPosted}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-green-700 hover:bg-green-600 text-white transition-colors disabled:opacity-50"
          >
            {markingPosted ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            Mark Posted
          </button>
        </div>
      </div>

      {/* Intel / Verification Panel */}
      {draft.intel && draft.intel.report && (
        <ContentIntelPanel intel={draft.intel} credibility={draft.credibility_score} publishReady={draft.publish_ready} />
      )}
    </div>
  );
}

function ContentIntelPanel({ intel, credibility, publishReady }: { intel: any; credibility?: number | null; publishReady?: boolean | null }) {
  const [open, setOpen] = useState(false);
  if (!intel || !intel.report) return null;

  const score = credibility ?? intel.credibility_score ?? 0;
  const ready = publishReady ?? intel.publish_ready ?? false;
  const scoreColor = score >= 8 ? "text-green-400" : score >= 6 ? "text-yellow-400" : "text-red-400";
  const readyBadge = ready
    ? "bg-green-900/50 text-green-300 border-green-700"
    : "bg-yellow-900/50 text-yellow-300 border-yellow-700";

  return (
    <div className="border-t border-slate-700 px-4 py-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 transition-colors w-full"
      >
        <span className={`font-semibold ${scoreColor}`}>Credibility: {score}/10</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium border ${readyBadge}`}>
          {ready ? "PUBLISH READY" : "REVIEW NEEDED"}
        </span>
        <span className="text-slate-500 text-[10px]">3-round verification</span>
        <span className="ml-auto">{open ? "Hide" : "View"} Intel</span>
      </button>

      {open && (
        <div className="mt-2 rounded-lg bg-slate-900 border border-slate-700 p-3 text-xs text-slate-300 whitespace-pre-wrap max-h-[400px] overflow-y-auto">
          {intel.report}
        </div>
      )}
    </div>
  );
}

// ─── Draft card (calendar-based) ──────────────────────────────────────────────

function DraftCard({
  draft,
  onRegenerate,
  onMarkPosted,
}: {
  draft: ContentDraft;
  onRegenerate: (topic: string, pillar: string, format: string) => void;
  onMarkPosted: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState(draft.post_text);
  const [copied, setCopied] = useState(false);
  const [markingPosted, setMarkingPosted] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const currentText = editing ? editedText : draft.post_text;
  const charCount = currentText.length;
  const isOver = charCount > CHAR_LIMIT;
  const isWarning = charCount > CHAR_WARN && !isOver;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(currentText);
    } catch {
      const el = document.createElement("textarea");
      el.value = currentText;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleMarkPosted = async () => {
    setMarkingPosted(true);
    try {
      await onMarkPosted(draft.id);
    } finally {
      setMarkingPosted(false);
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await onRegenerate(draft.topic, draft.pillar, draft.format);
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-700/40">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${
              FORMAT_COLORS[draft.format] ?? "bg-slate-800 text-slate-300"
            }`}
          >
            {FORMAT_LABELS[draft.format] ?? draft.format}
          </span>
          <span
            className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${
              PILLAR_COLORS[draft.pillar] ?? "bg-slate-800 text-slate-300"
            }`}
          >
            {PILLAR_LABELS[draft.pillar] ?? draft.pillar}
          </span>
          <span className="truncate text-sm font-medium text-slate-200 ml-1">
            {draft.topic}
          </span>
        </div>
        <span className="shrink-0 text-xs text-slate-500">
          {new Date(draft.generated_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </span>
      </div>

      {/* Post body */}
      <div className="px-4 py-3">
        {editing ? (
          <textarea
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            className="w-full min-h-[200px] resize-y rounded-lg bg-slate-900 border border-slate-600 p-3 text-sm text-slate-200 font-mono leading-relaxed focus:outline-none focus:border-blue-500"
            autoFocus
          />
        ) : (
          <pre className="whitespace-pre-wrap text-sm text-slate-300 leading-relaxed font-sans">
            {draft.post_text}
          </pre>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-slate-700/40 bg-slate-900/30">
        <span
          className={`text-sm font-mono tabular-nums ${
            isOver
              ? "text-red-400 font-semibold"
              : isWarning
              ? "text-amber-400"
              : "text-slate-500"
          }`}
        >
          {charCount.toLocaleString()} / {CHAR_LIMIT.toLocaleString()} chars
          {isOver && " — over limit"}
        </span>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied!" : "Copy"}
          </button>

          <button
            onClick={() => {
              if (editing) setEditedText(draft.post_text);
              setEditing(!editing);
            }}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              editing
                ? "bg-slate-700 hover:bg-slate-600 text-slate-400"
                : "bg-slate-700 hover:bg-slate-600 text-slate-200"
            }`}
          >
            <Edit2 className="h-3.5 w-3.5" />
            {editing ? "Cancel" : "Edit"}
          </button>

          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} />
            Regenerate
          </button>

          <button
            onClick={handleMarkPosted}
            disabled={markingPosted}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-green-700 hover:bg-green-600 text-white transition-colors disabled:opacity-50"
          >
            {markingPosted ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            Mark Posted
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Calendar row ──────────────────────────────────────────────────────────────

function CalendarRow({
  entry,
  draft,
  generating,
  onGenerate,
}: {
  entry: CalendarEntry;
  draft: ContentDraft | null;
  generating: boolean;
  onGenerate: (entry: CalendarEntry) => void;
}) {
  const status = draft
    ? draft.approval_status === "approved"
      ? "posted"
      : "generated"
    : "pending";

  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/30 transition-colors">
      <td className="px-4 py-3 text-sm font-medium text-slate-300 w-24">{entry.day}</td>
      <td className="px-4 py-3 w-32">
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            FORMAT_COLORS[entry.format] ?? "bg-slate-800 text-slate-300"
          }`}
        >
          {FORMAT_LABELS[entry.format] ?? entry.format}
        </span>
      </td>
      <td className="px-4 py-3 w-28">
        <span
          className={`rounded border px-2 py-0.5 text-xs font-medium ${
            PILLAR_COLORS[entry.pillar] ?? "bg-slate-800 text-slate-300"
          }`}
        >
          {PILLAR_LABELS[entry.pillar] ?? entry.pillar}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-slate-300">{entry.topic}</td>
      <td className="px-4 py-3 text-right w-36">
        {status === "posted" ? (
          <span className="flex items-center justify-end gap-1.5 text-xs text-green-400 font-medium">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Posted
          </span>
        ) : status === "generated" ? (
          <span className="flex items-center justify-end gap-1.5 text-xs text-blue-400 font-medium">
            <Check className="h-3.5 w-3.5" />
            Generated
          </span>
        ) : (
          <button
            onClick={() => onGenerate(entry)}
            disabled={generating}
            className="flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-blue-700 hover:bg-blue-600 text-white transition-colors disabled:opacity-50 ml-auto"
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <PenTool className="h-3.5 w-3.5" />
            )}
            Generate
          </button>
        )}
      </td>
    </tr>
  );
}

// ─── Auto-Calendar Row ────────────────────────────────────────────────────────

const AUTO_PILLAR_COLORS: Record<string, string> = {
  food_safety: "bg-emerald-100 text-emerald-800 border-emerald-300",
  predictive_maintenance: "bg-blue-100 text-blue-800 border-blue-300",
  ops_excellence: "bg-violet-100 text-violet-800 border-violet-300",
  leadership: "bg-amber-100 text-amber-800 border-amber-300",
};

function AutoCalendarRow({
  post,
  onMarkPosted,
}: {
  post: AutoCalendarPost;
  onMarkPosted: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState(post.body);
  const [markingPosted, setMarkingPosted] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [currentBody, setCurrentBody] = useState(post.body);
  const [status, setStatus] = useState(post.status);

  const displayText = editing ? editedText : currentBody;
  const charCount = displayText.length;
  const isOver = charCount > CHAR_LIMIT;
  const isWarning = charCount > CHAR_WARN && !isOver;

  const formattedDate = (() => {
    try {
      const d = new Date(post.scheduled_date + "T00:00:00");
      return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    } catch {
      return post.scheduled_date;
    }
  })();

  const handleCopy = async () => {
    const text = displayText;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const res = await generateContent({
        topic: post.topic,
        pillar: post.pillar,
        format_type: post.format,
      });
      const newDraft = (res as { data: ContentDraft }).data;
      setCurrentBody(newDraft.post_text);
      setEditedText(newDraft.post_text);
    } catch {
      // silently ignore — user sees no change
    } finally {
      setRegenerating(false);
    }
  };

  const handleMarkPosted = async () => {
    setMarkingPosted(true);
    try {
      await onMarkPosted(post.id);
      setStatus("posted");
    } finally {
      setMarkingPosted(false);
    }
  };

  const pillarColor =
    AUTO_PILLAR_COLORS[post.pillar] ?? "bg-gray-100 text-gray-700 border-gray-300";

  return (
    <div className="border-b border-gray-100 last:border-b-0">
      {/* Row summary */}
      <div
        className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Date */}
        <span className="w-28 shrink-0 text-sm font-medium text-gray-700">{formattedDate}</span>

        {/* Pillar badge */}
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${pillarColor}`}
        >
          {post.pillar_display}
        </span>

        {/* Format badge */}
        <span className="shrink-0 rounded border border-gray-300 bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-600">
          {post.format_display}
        </span>

        {/* Topic */}
        <span className="flex-1 truncate text-sm text-gray-700">{post.topic}</span>

        {/* Char count */}
        <span
          className={`shrink-0 text-xs tabular-nums ${
            isOver ? "text-red-500 font-semibold" : isWarning ? "text-amber-500" : "text-gray-400"
          }`}
        >
          {charCount}
        </span>

        {/* Status */}
        {status === "posted" ? (
          <span className="shrink-0 flex items-center gap-1 text-xs text-green-600 font-medium">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Posted
          </span>
        ) : (
          <span className="shrink-0 flex items-center gap-1 text-xs text-blue-600 font-medium">
            <Check className="h-3.5 w-3.5" />
            Generated
          </span>
        )}

        {/* Expand toggle */}
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-gray-400" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
        )}
      </div>

      {/* Expanded post body */}
      {expanded && (
        <div className="px-4 pb-4 bg-gray-50/50">
          {editing ? (
            <textarea
              value={editedText}
              onChange={(e) => setEditedText(e.target.value)}
              className="w-full min-h-[180px] resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 font-mono leading-relaxed focus:outline-none focus:border-blue-500"
              autoFocus
            />
          ) : (
            <pre className="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed font-sans mb-3">
              {currentBody}
            </pre>
          )}

          {/* Footer with char counter and action buttons */}
          <div className="flex items-center justify-between gap-2 mt-3">
            <span
              className={`text-xs font-mono tabular-nums ${
                isOver
                  ? "text-red-500 font-semibold"
                  : isWarning
                  ? "text-amber-500"
                  : "text-gray-400"
              }`}
            >
              {charCount.toLocaleString()} / {CHAR_LIMIT.toLocaleString()} chars
              {isOver && " — over limit"}
            </span>

            <div className="flex items-center gap-2">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  void handleCopy();
                }}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-gray-200 hover:bg-gray-300 text-gray-700 transition-colors"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-green-600" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? "Copied!" : "Copy"}
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (editing) setEditedText(currentBody);
                  setEditing(!editing);
                }}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                  editing
                    ? "bg-gray-200 hover:bg-gray-300 text-gray-500"
                    : "bg-gray-200 hover:bg-gray-300 text-gray-700"
                }`}
              >
                <Edit2 className="h-3.5 w-3.5" />
                {editing ? "Cancel" : "Edit"}
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  void handleRegenerate();
                }}
                disabled={regenerating}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-gray-200 hover:bg-gray-300 text-gray-700 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} />
                Regenerate
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  void handleMarkPosted();
                }}
                disabled={markingPosted || status === "posted"}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-green-600 hover:bg-green-700 text-white transition-colors disabled:opacity-50"
              >
                {markingPosted ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                {status === "posted" ? "Posted" : "Mark Posted"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Generator Panel ──────────────────────────────────────────────────────────

interface GeneratorPanelProps {
  onSingleGenerated: (draft: ContentDraft) => void;
  onBatchGenerated: (drafts: ContentDraft[]) => void;
}

function GeneratorPanel({ onSingleGenerated, onBatchGenerated }: GeneratorPanelProps) {
  const [pillar, setPillar] = useState("");
  const [timeHorizon, setTimeHorizon] = useState("single");
  const [formatType, setFormatType] = useState("");
  const [commentary, setCommentary] = useState("");
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  const isBatch = timeHorizon !== "single";
  const batchCount = TIME_HORIZON_COUNTS[timeHorizon] ?? 0;

  const handleSingle = async () => {
    setGenerating(true);
    setGenError(null);
    setProgress(null);
    try {
      const res = await generateContent({
        pillar: pillar || undefined,
        format_type: formatType || undefined,
        commentary: commentary.trim() || undefined,
      });
      onSingleGenerated((res as { data: ContentDraft }).data);
    } catch (e) {
      setGenError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const handleBatch = async () => {
    setGenerating(true);
    setGenError(null);
    setProgress({ current: 0, total: batchCount });
    try {
      // Fire the batch request. Since it's synchronous on the backend we
      // show an indeterminate spinner; once resolved we surface all drafts.
      const res = await generateContentBatch({
        pillar: pillar || undefined,
        format_type: formatType || undefined,
        time_horizon: timeHorizon,
        commentary: commentary.trim() || undefined,
      });
      const result = res as {
        data: ContentDraft[];
        count: number;
        requested: number;
        errors: string[];
      };
      setProgress({ current: result.count, total: result.requested });
      onBatchGenerated(result.data);
      if (result.errors.length > 0) {
        setGenError(
          `${result.errors.length} post(s) failed to generate. ${result.count} succeeded.`
        );
      }
    } catch (e) {
      setGenError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Sparkles className="h-4 w-4 text-violet-400" />
        <h2 className="text-sm font-semibold text-slate-200">Generate Content</h2>
      </div>

      {/* Controls row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
        <Select
          label="Theme Focus"
          value={pillar}
          onChange={setPillar}
          options={PILLAR_OPTIONS}
        />
        <Select
          label="Time Horizon"
          value={timeHorizon}
          onChange={setTimeHorizon}
          options={TIME_HORIZON_OPTIONS}
        />
        <Select
          label="Format"
          value={formatType}
          onChange={setFormatType}
          options={FORMAT_OPTIONS}
        />
      </div>

      {/* Commentary textarea */}
      <div className="flex flex-col gap-1.5 mb-4">
        <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
          Commentary / Brief{" "}
          <span className="normal-case text-slate-500">(optional)</span>
        </label>
        <textarea
          value={commentary}
          onChange={(e) => setCommentary(e.target.value)}
          placeholder="Focus on FSMA enforcement trends and recent FDA 483s in meat processing..."
          rows={3}
          className="w-full resize-none rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:outline-none leading-relaxed"
        />
      </div>

      {/* Error */}
      {genError && (
        <div className="flex items-start gap-2 rounded-lg border border-red-700/50 bg-red-900/20 px-3 py-2 mb-4 text-sm text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{genError}</span>
        </div>
      )}

      {/* Progress */}
      {generating && progress && (
        <div className="flex items-center gap-2 mb-4 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
          {progress.current === 0
            ? `Generating ${progress.total} post${progress.total !== 1 ? "s" : ""}...`
            : `Generated ${progress.current} of ${progress.total} posts`}
        </div>
      )}
      {generating && !progress && (
        <div className="flex items-center gap-2 mb-4 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
          Generating...
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSingle}
          disabled={generating}
          className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors disabled:opacity-50"
        >
          {generating && !isBatch ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <PenTool className="h-4 w-4" />
          )}
          Generate Single Post
        </button>

        {isBatch && (
          <button
            onClick={handleBatch}
            disabled={generating}
            className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium bg-violet-700 hover:bg-violet-600 text-white transition-colors disabled:opacity-50"
          >
            {generating && isBatch ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Generate Batch ({batchCount} posts)
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ContentPage() {
  const [calendar, setCalendar] = useState<CalendarEntry[]>([]);
  const [drafts, setDrafts] = useState<ContentDraft[]>([]);
  const [batchDrafts, setBatchDrafts] = useState<ContentDraft[]>([]);
  const [activeWeek, setActiveWeek] = useState<number>(getCurrentWeek());
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCalendarDrafts, setShowCalendarDrafts] = useState(true);
  const [showBatchDrafts, setShowBatchDrafts] = useState(true);

  // ── Auto-calendar state ────────────────────────────────────────────────────
  const [autoStartDate, setAutoStartDate] = useState(() => {
    const now = new Date();
    const day = now.getDay(); // 0 = Sunday
    const daysUntilMonday = day === 0 ? 1 : day === 1 ? 0 : 8 - day;
    const nextMonday = new Date(now);
    nextMonday.setDate(now.getDate() + daysUntilMonday);
    return nextMonday.toISOString().split("T")[0];
  });
  const [autoCommentary, setAutoCommentary] = useState("");
  const [autoGenerating, setAutoGenerating] = useState(false);
  const [autoProgress, setAutoProgress] = useState(0);
  const [autoCalendar, setAutoCalendar] = useState<AutoCalendarResponse | null>(null);
  const [autoError, setAutoError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [calRes, draftsRes] = await Promise.all([
        getContentCalendar(),
        getContentDrafts(),
      ]);
      setCalendar((calRes as { data: CalendarEntry[] }).data || []);
      setDrafts(((draftsRes as { data: ContentDraft[] }).data) || []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const weekEntries = calendar.filter((e) => e.week === activeWeek);

  const draftByTopic = new Map<string, ContentDraft>(drafts.map((d) => [d.topic, d]));

  // ── Calendar generate handlers ────────────────────────────────────────────

  const handleGenerate = async (entry: CalendarEntry) => {
    setGeneratingFor(entry.topic);
    setError(null);
    try {
      const res = await generateContent({
        topic: entry.topic,
        pillar: entry.pillar,
        format_type: entry.format,
      });
      const newDraft = (res as { data: ContentDraft }).data;
      setDrafts((prev) => [newDraft, ...prev]);
    } catch (e) {
      setError(`Generation failed: ${(e as Error).message}`);
    } finally {
      setGeneratingFor(null);
    }
  };

  const handleRegenerate = async (topic: string, pillar: string, format: string) => {
    setGeneratingFor(topic);
    setError(null);
    try {
      const res = await generateContent({ topic, pillar, format_type: format });
      const newDraft = (res as { data: ContentDraft }).data;
      setDrafts((prev) => [newDraft, ...prev.filter((d) => d.topic !== topic)]);
    } catch (e) {
      setError(`Regeneration failed: ${(e as Error).message}`);
    } finally {
      setGeneratingFor(null);
    }
  };

  const handleMarkPosted = async (id: string) => {
    try {
      await markContentPosted(id);
      setDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, approval_status: "approved" } : d))
      );
      setBatchDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, approval_status: "approved" } : d))
      );
    } catch (e) {
      setError(`Failed to mark as posted: ${(e as Error).message}`);
    }
  };

  // ── Auto-calendar handler ─────────────────────────────────────────────────

  const handleAutoGenerate = async () => {
    setAutoGenerating(true);
    setAutoError(null);
    setAutoProgress(0);
    setAutoCalendar(null);

    // Simulate progress updates (the backend runs sequentially for ~2-3 min)
    const progressInterval = setInterval(() => {
      setAutoProgress((prev) => Math.min(prev + 1, 15));
    }, 8000);

    try {
      const res = await autoGenerateCalendar({
        start_date: autoStartDate || undefined,
        commentary: autoCommentary.trim() || undefined,
        weeks: 4,
      });
      const data = (res as { data: AutoCalendarResponse }).data;
      setAutoCalendar(data);
      setAutoProgress(data.posts.length);
    } catch (e) {
      setAutoError((e as Error).message);
    } finally {
      clearInterval(progressInterval);
      setAutoGenerating(false);
    }
  };

  const handleAutoMarkPosted = async (id: string) => {
    try {
      await markContentPosted(id);
    } catch (e) {
      setError(`Failed to mark as posted: ${(e as Error).message}`);
    }
  };

  // ── Generator panel callbacks ─────────────────────────────────────────────

  const handleSingleGenerated = (draft: ContentDraft) => {
    setDrafts((prev) => [draft, ...prev]);
  };

  const handleBatchGenerated = (newDrafts: ContentDraft[]) => {
    setBatchDrafts((prev) => [...newDrafts, ...prev]);
    setShowBatchDrafts(true);
  };

  // Stats
  const generated = weekEntries.filter((e) => draftByTopic.has(e.topic)).length;
  const posted = weekEntries.filter((e) => {
    const d = draftByTopic.get(e.topic);
    return d?.approval_status === "approved";
  }).length;

  const weekDrafts = drafts.filter(
    (d) =>
      weekEntries.some((e) => e.topic === d.topic) && d.approval_status !== "approved"
  );

  const activeBatchDrafts = batchDrafts.filter((d) => d.approval_status !== "approved");

  return (
    <div className="flex flex-col gap-6 p-6 min-h-0">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-600/20">
            <PenTool className="h-5 w-5 text-violet-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white">Content Calendar</h1>
            <p className="text-sm text-slate-400">LinkedIn thought leadership posts</p>
          </div>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Global error banner */}
      {error && (
        <div className="rounded-lg border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* ── Auto-Generate Calendar ── */}
      <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-6">
        <div className="flex items-center gap-3 mb-3">
          <Zap className="h-6 w-6 text-blue-600" />
          <h2 className="text-lg font-semibold text-gray-900">Auto-Generate 4-Week Calendar</h2>
        </div>
        <p className="text-sm text-gray-600 mb-4">
          16 posts across all themes. Balanced rotation: Food Safety, Predictive Maintenance,
          Operations Excellence, Leadership. Mix of data insights, frameworks, contrarian takes,
          and benchmarks. Estimated cost: ~$0.80.
        </p>

        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
            <input
              type="date"
              value={autoStartDate}
              onChange={(e) => setAutoStartDate(e.target.value)}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Commentary (optional)
            </label>
            <input
              type="text"
              value={autoCommentary}
              onChange={(e) => setAutoCommentary(e.target.value)}
              placeholder="e.g., Focus on FSMA enforcement trends this month"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <button
            onClick={() => void handleAutoGenerate()}
            disabled={autoGenerating}
            className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {autoGenerating
              ? `Generating... (${autoProgress}/16)`
              : "Generate 4-Week Calendar"}
          </button>
        </div>

        {/* Auto-calendar error */}
        {autoError && (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{autoError}</span>
          </div>
        )}

        {/* Generating spinner */}
        {autoGenerating && (
          <div className="mt-4 flex items-center gap-2 text-sm text-blue-600">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>
              Generating {16} posts sequentially — this takes 2-3 minutes. Please keep this
              tab open.
            </span>
          </div>
        )}
      </div>

      {/* ── Auto-calendar results ── */}
      {autoCalendar && (
        <div className="space-y-6">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <h3 className="text-lg font-semibold text-slate-200">
              Content Calendar:{" "}
              <span className="text-slate-400 font-normal text-base">
                {autoCalendar.start_date} to {autoCalendar.end_date}
              </span>
            </h3>
            <div className="flex gap-4 text-sm text-slate-400 flex-wrap">
              <span>
                <span className="mr-1">🍎</span>Food Safety:{" "}
                <span className="text-slate-200 font-medium">
                  {autoCalendar.coverage["food_safety"] ?? 0}
                </span>
              </span>
              <span>
                <span className="mr-1">🔧</span>PdM:{" "}
                <span className="text-slate-200 font-medium">
                  {autoCalendar.coverage["predictive_maintenance"] ?? 0}
                </span>
              </span>
              <span>
                <span className="mr-1">⚙️</span>Ops:{" "}
                <span className="text-slate-200 font-medium">
                  {autoCalendar.coverage["ops_excellence"] ?? 0}
                </span>
              </span>
              <span>
                <span className="mr-1">👔</span>Leadership:{" "}
                <span className="text-slate-200 font-medium">
                  {autoCalendar.coverage["leadership"] ?? 0}
                </span>
              </span>
              <span className="text-slate-500">
                Generated in {autoCalendar.generation_time_seconds}s
              </span>
            </div>
          </div>

          {[1, 2, 3, 4].map((weekNum) => {
            const weekPosts = autoCalendar.posts.filter((p) => p.week_number === weekNum);
            if (weekPosts.length === 0) return null;
            return (
              <div
                key={weekNum}
                className="rounded-lg border border-gray-200 bg-white overflow-hidden shadow-sm"
              >
                <div className="bg-gray-50 px-4 py-2 font-medium text-sm text-gray-700 border-b border-gray-200">
                  Week {weekNum}
                </div>
                <div className="divide-y divide-gray-100">
                  {weekPosts.map((post) => (
                    <AutoCalendarRow
                      key={post.id || `${weekNum}-${post.scheduled_date}`}
                      post={post}
                      onMarkPosted={handleAutoMarkPosted}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Generator panel ── */}
      <GeneratorPanel
        onSingleGenerated={handleSingleGenerated}
        onBatchGenerated={handleBatchGenerated}
      />

      {/* ── Batch results ── */}
      {activeBatchDrafts.length > 0 && (
        <div>
          <button
            onClick={() => setShowBatchDrafts((v) => !v)}
            className="flex items-center gap-2 mb-3 text-sm font-medium text-slate-300 hover:text-white transition-colors"
          >
            {showBatchDrafts ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            <Sparkles className="h-4 w-4 text-violet-400" />
            Batch Results ({activeBatchDrafts.length} posts)
          </button>

          {showBatchDrafts && (
            <div className="flex flex-col gap-4">
              {activeBatchDrafts.map((draft, idx) => (
                <BatchDraftCard
                  key={draft.id || `batch-${idx}`}
                  draft={draft}
                  index={idx}
                  onRegenerate={handleRegenerate}
                  onMarkPosted={handleMarkPosted}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Calendar card ── */}
      <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 overflow-hidden">
        {/* Week tabs */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-slate-400" />
            <span className="text-sm font-medium text-slate-300">
              Week {activeWeek} — {getWeekLabel(activeWeek)}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {[1, 2, 3, 4].map((w) => (
              <button
                key={w}
                onClick={() => setActiveWeek(w)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  activeWeek === w
                    ? "bg-blue-600 text-white"
                    : "text-slate-400 hover:text-white hover:bg-slate-700"
                }`}
              >
                W{w}
              </button>
            ))}
          </div>
        </div>

        {/* Status bar */}
        <div className="flex items-center gap-4 px-4 py-2.5 bg-slate-900/30 border-b border-slate-700/30 text-xs text-slate-400">
          <span>
            <span className="text-blue-400 font-medium">{generated}</span>/
            {weekEntries.length} generated
          </span>
          <span>·</span>
          <span>
            <span className="text-green-400 font-medium">{posted}</span>/
            {weekEntries.length} posted
          </span>
          <span>·</span>
          <span>
            Next:{" "}
            {weekEntries.find((e) => !draftByTopic.has(e.topic))?.day ?? "All done"}
          </span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/40">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">
                  Day
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">
                  Format
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">
                  Pillar
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">
                  Topic
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-500 uppercase tracking-wide">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {weekEntries.map((entry) => (
                <CalendarRow
                  key={entry.topic}
                  entry={entry}
                  draft={draftByTopic.get(entry.topic) ?? null}
                  generating={generatingFor === entry.topic}
                  onGenerate={handleGenerate}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Calendar-based drafts ── */}
      {weekDrafts.length > 0 && (
        <div>
          <button
            onClick={() => setShowCalendarDrafts((v) => !v)}
            className="flex items-center gap-2 mb-3 text-sm font-medium text-slate-300 hover:text-white transition-colors"
          >
            {showCalendarDrafts ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            Generated Drafts ({weekDrafts.length})
          </button>

          {showCalendarDrafts && (
            <div className="flex flex-col gap-4">
              {weekDrafts.map((draft) => (
                <DraftCard
                  key={draft.id}
                  draft={draft}
                  onRegenerate={handleRegenerate}
                  onMarkPosted={handleMarkPosted}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Other drafts (not this week) ── */}
      {drafts.filter(
        (d) =>
          !weekEntries.some((e) => e.topic === d.topic) &&
          d.approval_status !== "approved"
      ).length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-medium text-slate-400">Other Drafts</h2>
          <div className="flex flex-col gap-4">
            {drafts
              .filter(
                (d) =>
                  !weekEntries.some((e) => e.topic === d.topic) &&
                  d.approval_status !== "approved"
              )
              .slice(0, 5)
              .map((draft) => (
                <DraftCard
                  key={draft.id}
                  draft={draft}
                  onRegenerate={handleRegenerate}
                  onMarkPosted={handleMarkPosted}
                />
              ))}
          </div>
        </div>
      )}

      {!loading && drafts.length === 0 && weekEntries.length > 0 && batchDrafts.length === 0 && (
        <div className="rounded-xl border border-slate-700/40 bg-slate-800/20 px-6 py-12 text-center">
          <PenTool className="mx-auto mb-3 h-8 w-8 text-slate-600" />
          <p className="text-slate-400 text-sm">
            No drafts yet. Use the generator above or click Generate on any calendar topic.
          </p>
        </div>
      )}
    </div>
  );
}
