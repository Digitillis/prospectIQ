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
  ChevronRight,
  Sparkles,
  AlertCircle,
  Zap,
  Archive,
  ExternalLink,
  BarChart2,
  X,
} from "lucide-react";
import {
  getContentCalendar,
  generateContent,
  generateContentBatch,
  getContentDrafts,
  markContentPosted,
  autoGenerateCalendar,
  getContentArchive,
  archiveContent,
  updateEngagement,
  getContentAnalytics,
  type ContentDraft,
  type ContentQualityReport,
  type AutoCalendarPost,
  type AutoCalendarResponse,
  type ContentArchiveEntry,
  type ContentAnalytics,
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
  manufacturing_intelligence: "Mfg Intelligence",
  manufacturing_strategy: "Strategy",
  manufacturing_operations: "Operations",
  food_safety_compliance: "F&B",
};

const PILLAR_COLORS: Record<string, string> = {
  manufacturing_intelligence: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
  manufacturing_strategy: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
  manufacturing_operations: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
  food_safety_compliance: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
};

const FORMAT_COLORS: Record<string, string> = {
  data_insight: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500",
  framework: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500",
  contrarian: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500",
  benchmark: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500",
};

const CHAR_LIMIT = 1300;
const CHAR_WARN = 1100;

// Dropdown option sets
const PILLAR_OPTIONS = [
  { value: "", label: "All Themes" },
  // Manufacturing Intelligence (Tuesday)
  { value: "manufacturing_intelligence", label: "Manufacturing Intelligence & AI (all)" },
  { value: "manufacturing_intelligence:pdm", label: "Predictive Maintenance & CBM" },
  { value: "manufacturing_intelligence:sensors", label: "Sensors & Data Infrastructure" },
  { value: "manufacturing_intelligence:oee", label: "OEE & Downtime Analysis" },
  { value: "manufacturing_intelligence:rul", label: "Remaining Useful Life & Prognostics" },
  // Manufacturing Strategy (Thursday, alternating)
  { value: "manufacturing_strategy", label: "Manufacturing Strategy & Leadership (all)" },
  { value: "manufacturing_strategy:capex", label: "Capital Allocation & ROI" },
  { value: "manufacturing_strategy:pilots", label: "Technology Pilot Programs" },
  { value: "manufacturing_strategy:workforce", label: "Workforce & Skills Gap" },
  { value: "manufacturing_strategy:culture", label: "Data-Driven Culture" },
  // Manufacturing Operations (Thursday, alternating)
  { value: "manufacturing_operations", label: "Operations Excellence & Performance (all)" },
  { value: "manufacturing_operations:quality", label: "Quality Management & SPC" },
  { value: "manufacturing_operations:energy", label: "Energy & Sustainability" },
  { value: "manufacturing_operations:i40", label: "Industry 4.0 & Digital Transformation" },
  { value: "manufacturing_operations:supply_chain", label: "Supply Chain Resilience" },
  // Food Safety (Saturday)
  { value: "food_safety_compliance", label: "Food Safety & Compliance (all)" },
  { value: "food_safety_compliance:fsma", label: "FSMA & FDA Enforcement" },
  { value: "food_safety_compliance:haccp", label: "HACCP & CCP Management" },
  { value: "food_safety_compliance:allergen", label: "Allergen Control & Traceability" },
  { value: "food_safety_compliance:audit", label: "Audit Readiness & SQF/BRC" },
  { value: "food_safety_compliance:cold_chain", label: "Cold Chain & Temperature Control" },
];

const TIME_HORIZON_OPTIONS = [
  { value: "single", label: "Single Post" },
  { value: "1_week", label: "1 Week (3 posts)" },
  { value: "30_days", label: "30 Days (12 posts)" },
  { value: "60_days", label: "60 Days (24 posts)" },
];

const FORMAT_OPTIONS = [
  { value: "", label: "All Formats" },
  { value: "data_insight", label: "Data Insight" },
  { value: "framework", label: "Framework" },
  { value: "contrarian", label: "Contrarian Take" },
  { value: "benchmark", label: "Industry Benchmark" },
];

const TIME_HORIZON_COUNTS: Record<string, number> = {
  "1_week": 3,
  "30_days": 12,
  "60_days": 24,
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

  // Posts go Tue/Thu/Sat within each week
  const POSTING_DAYS = [1, 3, 5]; // offsets from Monday: Tue, Thu, Sat
  const weekOffset = Math.floor(postIndex / 3) * 7;
  const dayOffset = POSTING_DAYS[postIndex % 3];

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
      <label className="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
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

// ─── Quality Report helpers ───────────────────────────────────────────────────

function parseQualityReport(draft: ContentDraft): ContentQualityReport | null {
  // Prefer the structured field returned directly from the API
  if (draft.quality_report) return draft.quality_report;
  return null;
}

function CheckOrX({ value }: { value: boolean }) {
  return value ? (
    <span className="text-green-600 dark:text-green-500 ml-1">Yes ✓</span>
  ) : (
    <span className="text-red-500 dark:text-red-400 ml-1">No ✗</span>
  );
}

function QualityReportPanel({ report }: { report: ContentQualityReport | null }) {
  const [open, setOpen] = useState(false);
  if (!report) return null;

  const score = report.score || 0;
  const verdict = report.verdict || "Unknown";
  const isReady = score >= 7 || verdict.toLowerCase().includes("ready");
  const verdictColor = isReady
    ? "text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
    : "text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800";

  return (
    <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-2">
      {/* Always-visible summary line */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
        >
          {open ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          Quality Report
        </button>
        <span className={`text-xs px-2 py-0.5 rounded border font-medium ${verdictColor}`}>
          {verdict} ({score}/10)
        </span>
      </div>

      {open && (
        <div className="mt-2 rounded-lg bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-3 text-xs space-y-3 max-h-[500px] overflow-y-auto">

          {/* FACT CHECK */}
          <div>
            <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">FACT CHECK</div>
            <div className="flex items-center gap-2">
              <span
                className={
                  report.fact_check?.result === "PASS"
                    ? "text-green-600 dark:text-green-500"
                    : "text-red-500 dark:text-red-400"
                }
              >
                {report.fact_check?.result === "PASS" ? "PASS ✓" : "FAIL ✗"}
              </span>
              {report.fact_check?.note && (
                <span className="text-gray-500 dark:text-gray-400">{report.fact_check.note}</span>
              )}
            </div>
            {report.fact_check?.sources && report.fact_check.sources.length > 0 && (
              <div className="text-gray-500 dark:text-gray-400 mt-1">
                Sources: {report.fact_check.sources.join(", ")}
              </div>
            )}
          </div>

          {/* PUBLICATION STANDARD */}
          <div>
            <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">PUBLICATION STANDARD</div>
            <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
              <div>McKinsey partner would share? <CheckOrX value={!!report.publication_standard?.mckinsey_share} /></div>
              <div>Free of fluff? <CheckOrX value={!!report.publication_standard?.fluff_free} /></div>
              <div>Claims supported? <CheckOrX value={!!report.publication_standard?.claims_supported} /></div>
              <div>Worth sharing internally? <CheckOrX value={!!report.publication_standard?.worth_sharing} /></div>
            </div>
          </div>

          {/* CONTENT OBJECTIVE */}
          {report.content_objective && report.content_objective.length > 0 && (
            <div>
              <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">CONTENT OBJECTIVE</div>
              {report.content_objective.map((obj: string, i: number) => (
                <div key={i} className="text-gray-600 dark:text-gray-400">✓ {obj}</div>
              ))}
            </div>
          )}

          {/* POSITIONING */}
          <div>
            <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">POSITIONING</div>
            <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
              <div>Systems thinker? <CheckOrX value={!!report.positioning?.systems_thinker} /></div>
              <div>Pattern recognizer? <CheckOrX value={!!report.positioning?.pattern_recognizer} /></div>
              <div>Builder? <CheckOrX value={!!report.positioning?.builder} /></div>
            </div>
          </div>

          {/* DIFFERENTIATION */}
          <div>
            <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">DIFFERENTIATION</div>
            <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
              <div>Unique — others couldn&apos;t write this? <CheckOrX value={!report.differentiation?.could_100_write} /></div>
              <div>Original insight? <CheckOrX value={!!report.differentiation?.original_insight} /></div>
              {report.differentiation?.note && (
                <div className="italic text-gray-500 dark:text-gray-400">{report.differentiation.note}</div>
              )}
            </div>
          </div>

          {/* CRAFT */}
          <div>
            <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">CRAFT</div>
            <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
              <div>
                Banned phrases:{" "}
                {report.craft?.banned_phrases && report.craft.banned_phrases.length > 0 ? (
                  <span className="text-red-500 dark:text-red-400">{report.craft.banned_phrases.join(", ")}</span>
                ) : (
                  <span className="text-green-600 dark:text-green-500">None ✓</span>
                )}
              </div>
              <div>No em dashes? <CheckOrX value={!report.craft?.em_dashes} /></div>
              <div>Character count OK? <CheckOrX value={!!report.craft?.char_count_ok} /></div>
              <div>Mobile formatting? <CheckOrX value={!!report.craft?.mobile_format} /></div>
            </div>
          </div>

          {/* READER VALUE */}
          <div>
            <div className="font-semibold text-gray-700 dark:text-gray-300 mb-1">READER VALUE</div>
            <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
              <div>Actionable or shifts thinking? <CheckOrX value={!!report.reader_value?.actionable} /></div>
              <div>Explains WHY not just WHAT? <CheckOrX value={!!report.reader_value?.explains_why} /></div>
            </div>
          </div>

          {/* FLAGS */}
          {report.flags && report.flags.length > 0 && (
            <div>
              <div className="font-semibold text-amber-700 dark:text-amber-400 mb-1">FLAGS</div>
              {report.flags.map((flag: string, i: number) => (
                <div key={i} className="text-amber-600 dark:text-amber-400">⚠ {flag}</div>
              ))}
            </div>
          )}
        </div>
      )}
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
  onMarkPosted: (id: string, linkedinUrl?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState(draft.post_text);
  const [copied, setCopied] = useState(false);
  const [markingPosted, setMarkingPosted] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [showUrlPrompt, setShowUrlPrompt] = useState(false);
  const [linkedinUrl, setLinkedinUrl] = useState("");

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
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2 min-w-0">
          <span className="shrink-0 text-xs font-medium text-gray-400 dark:text-gray-500 tabular-nums">
            #{index + 1}
          </span>
          <span className="shrink-0 text-xs text-gray-500 dark:text-gray-500">{scheduledDate}</span>
          <span
            className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${
              PILLAR_COLORS[draft.pillar] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700"
            }`}
          >
            {PILLAR_LABELS[draft.pillar] ?? draft.pillar}
          </span>
          <span
            className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${
              FORMAT_COLORS[draft.format] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500"
            }`}
          >
            {FORMAT_LABELS[draft.format] ?? draft.format}
          </span>
          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100 ml-1">
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
            className="w-full min-h-[180px] resize-y rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 text-sm text-gray-800 font-mono leading-relaxed focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
            autoFocus
          />
        ) : (
          <pre className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300 leading-relaxed font-sans">
            {draft.post_text}
          </pre>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
        <span
          className={`text-sm font-mono tabular-nums ${
            isOver
              ? "text-gray-900 dark:text-gray-100 font-semibold"
              : isWarning
              ? "text-gray-600 dark:text-gray-500"
              : "text-gray-400 dark:text-gray-500"
          }`}
        >
          {charCount.toLocaleString()} / {CHAR_LIMIT.toLocaleString()} chars
          {isOver && " — over limit"}
        </span>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-gray-600 dark:text-gray-500" />
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
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              editing
                ? "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-500"
                : "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
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
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} />
            Regenerate
          </button>

          <button
            onClick={() => setShowUrlPrompt(true)}
            disabled={markingPosted}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors disabled:opacity-50"
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

      {/* LinkedIn URL prompt */}
      {showUrlPrompt && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-3 bg-gray-50 dark:bg-gray-800">
          <p className="text-xs text-gray-500 dark:text-gray-500 mb-2">LinkedIn post URL (optional):</p>
          <div className="flex items-center gap-2">
            <input
              type="url"
              value={linkedinUrl}
              onChange={(e) => setLinkedinUrl(e.target.value)}
              placeholder="https://www.linkedin.com/posts/..."
              className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
            />
            <button
              onClick={async () => {
                setMarkingPosted(true);
                setShowUrlPrompt(false);
                try {
                  await onMarkPosted(draft.id, linkedinUrl || undefined);
                } finally {
                  setMarkingPosted(false);
                }
              }}
              className="rounded-md px-3 py-1.5 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setShowUrlPrompt(false)}
              className="rounded-md px-2 py-1.5 text-xs text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Intel / Verification Panel */}
      {draft.intel && draft.intel.report && (
        <ContentIntelPanel intel={draft.intel} credibility={draft.credibility_score} publishReady={draft.publish_ready} />
      )}

      {/* Quality Report Panel */}
      <QualityReportPanel report={parseQualityReport(draft)} />
    </div>
  );
}

function ContentIntelPanel({ intel, credibility, publishReady }: { intel: any; credibility?: number | null; publishReady?: boolean | null }) {
  const [open, setOpen] = useState(false);
  if (!intel || !intel.report) return null;

  const score = credibility ?? intel.credibility_score ?? 0;
  const ready = publishReady ?? intel.publish_ready ?? false;
  const readyBadge = ready
    ? "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-300"
    : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700";

  return (
    <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 transition-colors w-full"
      >
        <span className="font-semibold text-gray-700 dark:text-gray-300">Credibility: {score}/10</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium border ${readyBadge}`}>
          {ready ? "PUBLISH READY" : "REVIEW NEEDED"}
        </span>
        <span className="text-gray-400 dark:text-gray-500 text-[10px]">3-round verification</span>
        <span className="ml-auto">{open ? "Hide" : "View"} Intel</span>
      </button>

      {open && (
        <div className="mt-2 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap max-h-[400px] overflow-y-auto">
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
  onMarkPosted: (id: string, linkedinUrl?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState(draft.post_text);
  const [copied, setCopied] = useState(false);
  const [markingPosted, setMarkingPosted] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [showUrlPrompt, setShowUrlPrompt] = useState(false);
  const [linkedinUrl, setLinkedinUrl] = useState("");

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

  const handleMarkPosted = async (url?: string) => {
    setMarkingPosted(true);
    try {
      await onMarkPosted(draft.id, url);
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
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${
              FORMAT_COLORS[draft.format] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500"
            }`}
          >
            {FORMAT_LABELS[draft.format] ?? draft.format}
          </span>
          <span
            className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${
              PILLAR_COLORS[draft.pillar] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700"
            }`}
          >
            {PILLAR_LABELS[draft.pillar] ?? draft.pillar}
          </span>
          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100 ml-1">
            {draft.topic}
          </span>
        </div>
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">
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
            className="w-full min-h-[200px] resize-y rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 text-sm text-gray-800 font-mono leading-relaxed focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
            autoFocus
          />
        ) : (
          <pre className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300 leading-relaxed font-sans">
            {draft.post_text}
          </pre>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
        <span
          className={`text-sm font-mono tabular-nums ${
            isOver
              ? "text-gray-900 dark:text-gray-100 font-semibold"
              : isWarning
              ? "text-gray-600 dark:text-gray-500"
              : "text-gray-400 dark:text-gray-500"
          }`}
        >
          {charCount.toLocaleString()} / {CHAR_LIMIT.toLocaleString()} chars
          {isOver && " — over limit"}
        </span>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-gray-600 dark:text-gray-500" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied!" : "Copy"}
          </button>

          <button
            onClick={() => {
              if (editing) setEditedText(draft.post_text);
              setEditing(!editing);
            }}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              editing
                ? "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-500"
                : "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
            }`}
          >
            <Edit2 className="h-3.5 w-3.5" />
            {editing ? "Cancel" : "Edit"}
          </button>

          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} />
            Regenerate
          </button>

          <button
            onClick={() => setShowUrlPrompt(true)}
            disabled={markingPosted}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors disabled:opacity-50"
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

      {/* LinkedIn URL prompt */}
      {showUrlPrompt && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-3 bg-gray-50 dark:bg-gray-800">
          <p className="text-xs text-gray-500 dark:text-gray-500 mb-2">LinkedIn post URL (optional):</p>
          <div className="flex items-center gap-2">
            <input
              type="url"
              value={linkedinUrl}
              onChange={(e) => setLinkedinUrl(e.target.value)}
              placeholder="https://www.linkedin.com/posts/..."
              className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
            />
            <button
              onClick={async () => {
                setShowUrlPrompt(false);
                await handleMarkPosted(linkedinUrl || undefined);
              }}
              className="rounded-md px-3 py-1.5 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setShowUrlPrompt(false)}
              className="rounded-md px-2 py-1.5 text-xs text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Intel / Verification Panel */}
      {draft.intel && draft.intel.report && (
        <ContentIntelPanel intel={draft.intel} credibility={draft.credibility_score} publishReady={draft.publish_ready} />
      )}

      {/* Quality Report Panel */}
      <QualityReportPanel report={parseQualityReport(draft)} />
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
    <tr className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
      <td className="px-4 py-3 text-sm font-medium text-gray-700 dark:text-gray-300 w-24">{entry.day}</td>
      <td className="px-4 py-3 w-32">
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            FORMAT_COLORS[entry.format] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500"
          }`}
        >
          {FORMAT_LABELS[entry.format] ?? entry.format}
        </span>
      </td>
      <td className="px-4 py-3 w-28">
        <span
          className={`rounded border px-2 py-0.5 text-xs font-medium ${
            PILLAR_COLORS[entry.pillar] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700"
          }`}
        >
          {PILLAR_LABELS[entry.pillar] ?? entry.pillar}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">{entry.topic}</td>
      <td className="px-4 py-3 text-right w-36">
        {status === "posted" ? (
          <span className="flex items-center justify-end gap-1.5 text-xs text-gray-600 dark:text-gray-500 font-medium">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Posted
          </span>
        ) : status === "generated" ? (
          <span className="flex items-center justify-end gap-1.5 text-xs text-gray-500 dark:text-gray-500 font-medium">
            <Check className="h-3.5 w-3.5" />
            Generated
          </span>
        ) : (
          <button
            onClick={() => onGenerate(entry)}
            disabled={generating}
            className="flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors disabled:opacity-50 ml-auto"
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
  food_safety: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
  predictive_maintenance: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
  ops_excellence: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
  leadership: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700",
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
    AUTO_PILLAR_COLORS[post.pillar] ?? "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-300";

  return (
    <div className="border-b border-gray-100 dark:border-gray-800 last:border-b-0">
      {/* Row summary */}
      <div
        className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Date */}
        <span className="w-28 shrink-0 text-sm font-medium text-gray-700 dark:text-gray-300">{formattedDate}</span>

        {/* Pillar badge */}
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${pillarColor}`}
        >
          {post.pillar_display}
        </span>

        {/* Format badge */}
        <span className="shrink-0 rounded border border-gray-300 bg-gray-50 dark:bg-gray-800 px-2 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-500">
          {post.format_display}
        </span>

        {/* Topic */}
        <span className="flex-1 truncate text-sm text-gray-700 dark:text-gray-300">{post.topic}</span>

        {/* Char count */}
        <span
          className={`shrink-0 text-xs tabular-nums ${
            isOver ? "text-gray-900 dark:text-gray-100 font-semibold" : isWarning ? "text-gray-600 dark:text-gray-500" : "text-gray-400 dark:text-gray-500"
          }`}
        >
          {charCount}
        </span>

        {/* Status */}
        {status === "posted" ? (
          <span className="shrink-0 flex items-center gap-1 text-xs text-gray-600 dark:text-gray-500 font-medium">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Posted
          </span>
        ) : (
          <span className="shrink-0 flex items-center gap-1 text-xs text-gray-500 dark:text-gray-500 font-medium">
            <Check className="h-3.5 w-3.5" />
            Generated
          </span>
        )}

        {/* Expand toggle */}
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500" />
        )}
      </div>

      {/* Expanded post body */}
      {expanded && (
        <div className="px-4 pb-4 bg-gray-50 dark:bg-gray-800">
          {editing ? (
            <textarea
              value={editedText}
              onChange={(e) => setEditedText(e.target.value)}
              className="w-full min-h-[180px] resize-y rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-800 font-mono leading-relaxed focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
              autoFocus
            />
          ) : (
            <pre className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300 leading-relaxed font-sans mb-3">
              {currentBody}
            </pre>
          )}

          {/* Footer with char counter and action buttons */}
          <div className="flex items-center justify-between gap-2 mt-3">
            <span
              className={`text-xs font-mono tabular-nums ${
                isOver
                  ? "text-gray-900 dark:text-gray-100 font-semibold"
                  : isWarning
                  ? "text-gray-600 dark:text-gray-500"
                  : "text-gray-400 dark:text-gray-500"
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
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-gray-600 dark:text-gray-500" />
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
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  editing
                    ? "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-500"
                    : "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
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
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors disabled:opacity-50"
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
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors disabled:opacity-50"
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

// ─── Engagement Form ──────────────────────────────────────────────────────────

function EngagementForm({
  entry,
  onSaved,
}: {
  entry: ContentArchiveEntry;
  onSaved: (updated: ContentArchiveEntry) => void;
}) {
  const [open, setOpen] = useState(false);
  const [impressions, setImpressions] = useState(String(entry.impressions ?? ""));
  const [likes, setLikes] = useState(String(entry.likes ?? ""));
  const [comments, setComments] = useState(String(entry.comments ?? ""));
  const [shares, setShares] = useState(String(entry.shares ?? ""));
  const [linkedinUrl, setLinkedinUrl] = useState(entry.linkedin_post_url ?? "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await updateEngagement(entry.id, {
        impressions: impressions ? parseInt(impressions) : undefined,
        likes: likes ? parseInt(likes) : undefined,
        comments: comments ? parseInt(comments) : undefined,
        shares: shares ? parseInt(shares) : undefined,
        linkedin_post_url: linkedinUrl || undefined,
      });
      const updated = (res as { data: ContentArchiveEntry }).data;
      onSaved({ ...entry, ...updated });
      setOpen(false);
    } catch {
      // silently ignore
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 transition-colors flex items-center gap-1"
      >
        <BarChart2 className="h-3 w-3" />
        {open ? "Hide" : "Update metrics"}
      </button>
      {open && (
        <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { label: "Impressions", value: impressions, set: setImpressions },
            { label: "Likes", value: likes, set: setLikes },
            { label: "Comments", value: comments, set: setComments },
            { label: "Shares", value: shares, set: setShares },
          ].map(({ label, value, set }) => (
            <div key={label} className="flex flex-col gap-1">
              <label className="text-[10px] text-gray-400 dark:text-gray-500 uppercase">{label}</label>
              <input
                type="number"
                min="0"
                value={value}
                onChange={(e) => set(e.target.value)}
                className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 w-full focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
              />
            </div>
          ))}
          <div className="col-span-2 sm:col-span-4 flex flex-col gap-1">
            <label className="text-[10px] text-gray-400 dark:text-gray-500 uppercase">LinkedIn URL</label>
            <div className="flex gap-2">
              <input
                type="url"
                value={linkedinUrl}
                onChange={(e) => setLinkedinUrl(e.target.value)}
                placeholder="https://www.linkedin.com/posts/..."
                className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
              />
              <button
                onClick={handleSave}
                disabled={saving}
                className="rounded-md px-3 py-1 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Archive Section ──────────────────────────────────────────────────────────

function ArchiveSection() {
  const [archive, setArchive] = useState<ContentArchiveEntry[]>([]);
  const [analytics, setAnalytics] = useState<ContentAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [showArchive, setShowArchive] = useState(true);

  const fetchArchive = useCallback(async () => {
    try {
      const [archRes, analyticsRes] = await Promise.all([
        getContentArchive({ limit: 100 }),
        getContentAnalytics(),
      ]);
      setArchive((archRes as { data: ContentArchiveEntry[] }).data || []);
      setAnalytics((analyticsRes as { data: ContentAnalytics }).data);
    } catch {
      // silently degrade
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchArchive();
  }, [fetchArchive]);

  const handleEngagementSaved = (updated: ContentArchiveEntry) => {
    setArchive((prev) =>
      prev.map((e) => (e.id === updated.id ? { ...e, ...updated } : e))
    );
  };

  const bestPillar = analytics
    ? Object.entries(analytics.by_pillar).sort((a, b) => b[1].avg_rate - a[1].avg_rate)[0]
    : null;
  const bestFormat = analytics
    ? Object.entries(analytics.by_format).sort((a, b) => b[1].avg_rate - a[1].avg_rate)[0]
    : null;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setShowArchive((v) => !v)}
        className="flex items-center justify-between w-full px-4 py-3 border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Archive className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
            Content Archive ({analytics?.total_posts ?? archive.length} posted)
          </span>
        </div>
        {showArchive ? (
          <ChevronUp className="h-4 w-4 text-gray-400 dark:text-gray-500" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-400 dark:text-gray-500" />
        )}
      </button>

      {showArchive && (
        <>
          {/* Analytics summary */}
          {analytics && analytics.total_posts > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-4 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
              <div>
                <p className="text-[10px] uppercase text-gray-400 dark:text-gray-500 mb-0.5">Total Posts</p>
                <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{analytics.total_posts}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase text-gray-400 dark:text-gray-500 mb-0.5">Avg Credibility</p>
                <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{analytics.avg_credibility}/10</p>
              </div>
              <div>
                <p className="text-[10px] uppercase text-gray-400 dark:text-gray-500 mb-0.5">Best Pillar</p>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {bestPillar
                    ? `${PILLAR_LABELS[bestPillar[0]] ?? bestPillar[0]} (${(bestPillar[1].avg_rate * 100).toFixed(1)}%)`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase text-gray-400 dark:text-gray-500 mb-0.5">Best Format</p>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {bestFormat
                    ? `${FORMAT_LABELS[bestFormat[0]] ?? bestFormat[0]} (${(bestFormat[1].avg_rate * 100).toFixed(1)}%)`
                    : "—"}
                </p>
              </div>
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-gray-400 dark:text-gray-500" />
            </div>
          ) : archive.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
              No archived posts yet. Use "Mark Posted" on a draft to archive it.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Date</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Topic</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Pillar</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Format</th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Score</th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">👍</th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">💬</th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">🔄</th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Rate</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Link / Metrics</th>
                  </tr>
                </thead>
                <tbody>
                  {archive.map((entry) => (
                    <tr key={entry.id} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors align-top">
                      <td className="px-3 py-2 text-gray-500 dark:text-gray-500 whitespace-nowrap">
                        {entry.posted_at
                          ? new Date(entry.posted_at).toLocaleDateString("en-US", {
                              month: "short",
                              day: "numeric",
                              year: "2-digit",
                            })
                          : "—"}
                      </td>
                      <td className="px-3 py-2 text-gray-700 dark:text-gray-300 max-w-[200px]">
                        <span className="line-clamp-2">{entry.topic}</span>
                      </td>
                      <td className="px-3 py-2">
                        {entry.pillar && (
                          <span
                            className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${
                              PILLAR_COLORS[entry.pillar] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500 border-gray-200 dark:border-gray-700"
                            }`}
                          >
                            {PILLAR_LABELS[entry.pillar] ?? entry.pillar}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {entry.format && (
                          <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-600 dark:text-gray-500">
                            {FORMAT_LABELS[entry.format] ?? entry.format}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300 tabular-nums">
                        {entry.credibility_score != null ? `${entry.credibility_score}/10` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300 tabular-nums">{entry.likes ?? 0}</td>
                      <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300 tabular-nums">{entry.comments ?? 0}</td>
                      <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300 tabular-nums">{entry.shares ?? 0}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {entry.engagement_rate != null ? (
                          <span className="text-gray-700 dark:text-gray-300">{(entry.engagement_rate * 100).toFixed(1)}%</span>
                        ) : (
                          <span className="text-gray-400 dark:text-gray-500">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-col gap-1">
                          {entry.linkedin_post_url && (
                            <a
                              href={entry.linkedin_post_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 transition-colors"
                            >
                              <ExternalLink className="h-3 w-3" />
                              View
                            </a>
                          )}
                          <EngagementForm entry={entry} onSaved={handleEngagementSaved} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
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
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Sparkles className="h-4 w-4 text-gray-400 dark:text-gray-500" />
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Generate Content</h2>
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
        <label className="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
          Commentary / Brief{" "}
          <span className="normal-case text-gray-400 dark:text-gray-500">(optional)</span>
        </label>
        <textarea
          value={commentary}
          onChange={(e) => setCommentary(e.target.value)}
          placeholder="Focus on FSMA enforcement trends and recent FDA 483s in meat processing..."
          rows={3}
          className="w-full resize-none rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-600 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200 leading-relaxed"
        />
      </div>

      {/* Error */}
      {genError && (
        <div className="flex items-start gap-2 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 mb-4 text-sm text-gray-700 dark:text-gray-300">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-gray-400 dark:text-gray-500" />
          <span>{genError}</span>
        </div>
      )}

      {/* Progress */}
      {generating && progress && (
        <div className="flex items-center gap-2 mb-4 text-sm text-gray-500 dark:text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin text-gray-400 dark:text-gray-500" />
          {progress.current === 0
            ? `Generating ${progress.total} post${progress.total !== 1 ? "s" : ""}...`
            : `Generated ${progress.current} of ${progress.total} posts`}
        </div>
      )}
      {generating && !progress && (
        <div className="flex items-center gap-2 mb-4 text-sm text-gray-500 dark:text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin text-gray-400 dark:text-gray-500" />
          Generating...
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSingle}
          disabled={generating}
          className="flex items-center gap-2 rounded-md px-4 py-2 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors disabled:opacity-50"
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
            className="flex items-center gap-2 rounded-md px-4 py-2 text-xs font-medium bg-gray-900 hover:bg-gray-800 text-white transition-colors disabled:opacity-50"
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

  const handleMarkPosted = async (id: string, linkedinUrl?: string) => {
    try {
      await markContentPosted(id);
      setDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, approval_status: "approved" } : d))
      );
      setBatchDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, approval_status: "approved" } : d))
      );
      // Archive the post — fire-and-forget, non-blocking
      archiveContent(id, {
        linkedin_post_url: linkedinUrl || undefined,
        posted_at: new Date().toISOString(),
      }).catch(() => {
        // Silently degrade if archive table doesn't exist yet
      });
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
      archiveContent(id, { posted_at: new Date().toISOString() }).catch(() => {});
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
    <div className="flex flex-col gap-6 min-h-0">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Content Calendar</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">LinkedIn thought leadership posts</p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Global error banner */}
      {error && (
        <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
          {error}
        </div>
      )}

      {/* ── Auto-Generate Calendar ── */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Auto-Generate 4-Week Calendar</h2>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-500 mb-4">
          16 posts across all themes. Balanced rotation: Food Safety, Predictive Maintenance,
          Operations Excellence, Leadership. Mix of data insights, frameworks, contrarian takes,
          and benchmarks. Estimated cost: ~$0.80.
        </p>

        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="block text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-1">Start Date</label>
            <input
              type="date"
              value={autoStartDate}
              onChange={(e) => setAutoStartDate(e.target.value)}
              className="rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm bg-white dark:bg-gray-900 focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
            />
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="block text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-1">
              Commentary (optional)
            </label>
            <input
              type="text"
              value={autoCommentary}
              onChange={(e) => setAutoCommentary(e.target.value)}
              placeholder="e.g., Focus on FSMA enforcement trends this month"
              className="w-full rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm bg-white dark:bg-gray-900 focus:outline-none focus:border-gray-300 focus:ring-1 focus:ring-gray-200"
            />
          </div>
          <button
            onClick={() => void handleAutoGenerate()}
            disabled={autoGenerating}
            className="rounded-md bg-gray-900 px-4 py-2 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50 transition-colors"
          >
            {autoGenerating
              ? `Generating... (${autoProgress}/16)`
              : "Generate 4-Week Calendar"}
          </button>
        </div>

        {/* Auto-calendar error */}
        {autoError && (
          <div className="mt-4 flex items-start gap-2 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 text-sm text-gray-700 dark:text-gray-300">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-gray-400 dark:text-gray-500" />
            <span>{autoError}</span>
          </div>
        )}

        {/* Generating spinner */}
        {autoGenerating && (
          <div className="mt-4 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin text-gray-400 dark:text-gray-500" />
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
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
              Content Calendar:{" "}
              <span className="text-gray-500 dark:text-gray-500 font-normal normal-case">
                {autoCalendar.start_date} to {autoCalendar.end_date}
              </span>
            </h3>
            <div className="flex gap-4 text-xs text-gray-500 dark:text-gray-500 flex-wrap">
              <span>
                <span className="mr-1">🍎</span>Food Safety:{" "}
                <span className="text-gray-900 dark:text-gray-100 font-medium">
                  {autoCalendar.coverage["food_safety"] ?? 0}
                </span>
              </span>
              <span>
                <span className="mr-1">🔧</span>PdM:{" "}
                <span className="text-gray-900 dark:text-gray-100 font-medium">
                  {autoCalendar.coverage["predictive_maintenance"] ?? 0}
                </span>
              </span>
              <span>
                <span className="mr-1">⚙️</span>Ops:{" "}
                <span className="text-gray-900 dark:text-gray-100 font-medium">
                  {autoCalendar.coverage["ops_excellence"] ?? 0}
                </span>
              </span>
              <span>
                <span className="mr-1">👔</span>Leadership:{" "}
                <span className="text-gray-900 dark:text-gray-100 font-medium">
                  {autoCalendar.coverage["leadership"] ?? 0}
                </span>
              </span>
              <span className="text-gray-400 dark:text-gray-500">
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
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden"
              >
                <div className="bg-gray-50 dark:bg-gray-800 px-4 py-2 text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest border-b border-gray-100 dark:border-gray-800">
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
            className="flex items-center gap-2 mb-3 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:text-gray-100 transition-colors"
          >
            {showBatchDrafts ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            <Sparkles className="h-4 w-4 text-gray-400 dark:text-gray-500" />
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
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
        {/* Week tabs */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-gray-400 dark:text-gray-500" />
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
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
                    ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                    : "text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800"
                }`}
              >
                W{w}
              </button>
            ))}
          </div>
        </div>

        {/* Status bar */}
        <div className="flex items-center gap-4 px-4 py-2.5 bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-500">
          <span>
            <span className="text-gray-700 dark:text-gray-300 font-medium">{generated}</span>/
            {weekEntries.length} generated
          </span>
          <span>·</span>
          <span>
            <span className="text-gray-700 dark:text-gray-300 font-medium">{posted}</span>/
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
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                <th className="px-4 py-2.5 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Day
                </th>
                <th className="px-4 py-2.5 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Format
                </th>
                <th className="px-4 py-2.5 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Pillar
                </th>
                <th className="px-4 py-2.5 text-left text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Topic
                </th>
                <th className="px-4 py-2.5 text-right text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">
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
            className="flex items-center gap-2 mb-3 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:text-gray-100 transition-colors"
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
          <h2 className="mb-3 text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-widest">Other Drafts</h2>
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
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-6 py-12 text-center">
          <PenTool className="mx-auto mb-3 h-8 w-8 text-gray-300" />
          <p className="text-gray-400 dark:text-gray-500 text-sm">
            No drafts yet. Use the generator above or click Generate on any calendar topic.
          </p>
        </div>
      )}

      {/* ── Content Archive ── */}
      <ArchiveSection />
    </div>
  );
}
