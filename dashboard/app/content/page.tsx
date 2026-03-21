"use client";

import { useState, useEffect, useCallback } from "react";
import { PenTool, RefreshCw, Copy, Check, Edit2, CheckCircle2, Loader2, Calendar, ChevronDown, ChevronUp } from "lucide-react";
import { getContentCalendar, generateContent, getContentDrafts, markContentPosted } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CalendarEntry {
  week: number;
  day: string;
  format: string;
  pillar: string;
  topic: string;
}

interface ContentDraft {
  id: string;
  topic: string;
  pillar: string;
  format: string;
  post_text: string;
  char_count: number;
  generated_at: string;
  approval_status: string;
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
  predictive_maintenance: "Mfg",
  ops_excellence: "Ops",
  leadership: "Leadership",
};

const PILLAR_COLORS: Record<string, string> = {
  food_safety: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  predictive_maintenance: "bg-blue-900/40 text-blue-300 border-blue-700/40",
  ops_excellence: "bg-violet-900/40 text-violet-300 border-violet-700/40",
  leadership: "bg-amber-900/40 text-amber-300 border-amber-700/40",
};

const FORMAT_COLORS: Record<string, string> = {
  data_insight: "bg-slate-800 text-slate-300",
  framework: "bg-slate-800 text-slate-300",
  contrarian: "bg-slate-800 text-slate-300",
  benchmark: "bg-slate-800 text-slate-300",
};

const CHAR_LIMIT = 1300;
const CHAR_WARN = 1100;

// ─── Week selector ────────────────────────────────────────────────────────────

function getCurrentWeek(): number {
  // Rotate through weeks 1–4 based on ISO week number
  const now = new Date();
  const startOfYear = new Date(now.getFullYear(), 0, 1);
  const weekNumber = Math.ceil(((now.getTime() - startOfYear.getTime()) / 86400000 + startOfYear.getDay() + 1) / 7);
  return ((weekNumber - 1) % 4) + 1;
}

function getWeekLabel(week: number): string {
  const now = new Date();
  // Find next Monday
  const day = now.getDay();
  const daysToMonday = day === 0 ? 1 : 8 - day;
  const monday = new Date(now);
  monday.setDate(now.getDate() + daysToMonday - 7); // this week's Monday
  monday.setDate(monday.getDate() + (week - 1) * 7);
  return monday.toLocaleDateString("en-US", { month: "long", day: "numeric" });
}

// ─── Draft card ───────────────────────────────────────────────────────────────

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
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback for non-HTTPS
      const el = document.createElement("textarea");
      el.value = currentText;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
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
          <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${FORMAT_COLORS[draft.format] || "bg-slate-800 text-slate-300"}`}>
            {FORMAT_LABELS[draft.format] || draft.format}
          </span>
          <span className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${PILLAR_COLORS[draft.pillar] || "bg-slate-800 text-slate-300"}`}>
            {PILLAR_LABELS[draft.pillar] || draft.pillar}
          </span>
          <span className="truncate text-sm font-medium text-slate-200 ml-1">{draft.topic}</span>
        </div>
        <span className="shrink-0 text-xs text-slate-500">
          {new Date(draft.generated_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
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
        {/* Char counter */}
        <span className={`text-sm font-mono tabular-nums ${
          isOver ? "text-red-400 font-semibold" : isWarning ? "text-amber-400" : "text-slate-500"
        }`}>
          {charCount.toLocaleString()} / {CHAR_LIMIT.toLocaleString()} chars
          {isOver && " — over limit"}
        </span>

        {/* Actions */}
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
              if (editing) setEditedText(draft.post_text); // cancel restores original
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

// ─── Calendar row ─────────────────────────────────────────────────────────────

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
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${FORMAT_COLORS[entry.format] || "bg-slate-800 text-slate-300"}`}>
          {FORMAT_LABELS[entry.format] || entry.format}
        </span>
      </td>
      <td className="px-4 py-3 w-28">
        <span className={`rounded border px-2 py-0.5 text-xs font-medium ${PILLAR_COLORS[entry.pillar] || "bg-slate-800 text-slate-300"}`}>
          {PILLAR_LABELS[entry.pillar] || entry.pillar}
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

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ContentPage() {
  const [calendar, setCalendar] = useState<CalendarEntry[]>([]);
  const [drafts, setDrafts] = useState<ContentDraft[]>([]);
  const [activeWeek, setActiveWeek] = useState<number>(getCurrentWeek());
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDrafts, setShowDrafts] = useState(true);

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

  // Map topic → draft for quick lookup
  const draftByTopic = new Map<string, ContentDraft>(
    drafts.map((d) => [d.topic, d])
  );

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
      // Replace existing draft for this topic
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
    } catch (e) {
      setError(`Failed to mark as posted: ${(e as Error).message}`);
    }
  };

  // Stats
  const generated = weekEntries.filter((e) => draftByTopic.has(e.topic)).length;
  const posted = weekEntries.filter((e) => {
    const d = draftByTopic.get(e.topic);
    return d?.approval_status === "approved";
  }).length;

  // Drafts for this week's topics (not yet posted)
  const weekDrafts = drafts.filter(
    (d) =>
      weekEntries.some((e) => e.topic === d.topic) &&
      d.approval_status !== "approved"
  );

  return (
    <div className="flex flex-col gap-6 p-6 min-h-0">
      {/* Header */}
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

      {error && (
        <div className="rounded-lg border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Calendar card */}
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
            <span className="text-blue-400 font-medium">{generated}</span>/{weekEntries.length} generated
          </span>
          <span>·</span>
          <span>
            <span className="text-green-400 font-medium">{posted}</span>/{weekEntries.length} posted
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
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">Day</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">Format</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">Pillar</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">Topic</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-500 uppercase tracking-wide">Status</th>
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

      {/* Drafts section */}
      {weekDrafts.length > 0 && (
        <div>
          <button
            onClick={() => setShowDrafts((v) => !v)}
            className="flex items-center gap-2 mb-3 text-sm font-medium text-slate-300 hover:text-white transition-colors"
          >
            {showDrafts ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Generated Drafts ({weekDrafts.length})
          </button>

          {showDrafts && (
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

      {/* All drafts (not this week) */}
      {drafts.filter((d) => !weekEntries.some((e) => e.topic === d.topic) && d.approval_status !== "approved").length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-medium text-slate-400">Other Drafts</h2>
          <div className="flex flex-col gap-4">
            {drafts
              .filter((d) => !weekEntries.some((e) => e.topic === d.topic) && d.approval_status !== "approved")
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

      {!loading && drafts.length === 0 && weekEntries.length > 0 && (
        <div className="rounded-xl border border-slate-700/40 bg-slate-800/20 px-6 py-12 text-center">
          <PenTool className="mx-auto mb-3 h-8 w-8 text-slate-600" />
          <p className="text-slate-400 text-sm">No drafts yet. Click Generate on any topic above to create your first post.</p>
        </div>
      )}
    </div>
  );
}
