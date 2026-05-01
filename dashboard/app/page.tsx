"use client";

/**
 * Command Center — tabbed daily work surface.
 *
 * Tabs:
 *   Approvals — full inline draft review / approve / edit / reject
 *   Threads   — reply thread list with detail panel
 *   Overview  — KPI cards, funnel, signals, weekly cadence
 */

import { Suspense, useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  CheckCircle2, XCircle, Pencil, Mail, User, Building2, Loader2,
  Inbox, Shuffle, MessageSquareReply, MessageSquare, RefreshCw,
  RotateCcw, Send, ChevronDown, AlertTriangle, ArrowRight,
  FileText, Zap, TrendingUp, DollarSign, X,
} from "lucide-react";
import {
  getPendingDrafts, approveDraft, saveDraftEdit, rejectDraft,
  testSendDraft, logReply, listThreads, getThread,
  confirmThreadClassification, sendThreadDraft, regenerateThreadDraft,
  getCommandCenter, updateIntelligenceGoals, getHitlStats, getAnalyticsSummary,
  type OutreachDraft, type DraftQualityScore, type LogReplyPayload,
  type CampaignThread, type ThreadMessage, type CommandCenterData,
  type HitlStats, type AnalyticsSummary,
} from "@/lib/api";
import { cn, TIER_LABELS, getPQSColor } from "@/lib/utils";
import DraftQualityBadge from "@/components/outreach/DraftQualityBadge";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function timeSince(iso?: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-gray-100 dark:bg-gray-800", className)} />;
}

// ---------------------------------------------------------------------------
// KPI helpers (Overview tab)
// ---------------------------------------------------------------------------

function KPICard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={cn("text-2xl font-bold text-gray-900 dark:text-gray-100", color)}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{sub}</p>}
    </div>
  );
}

function WeeklyBar({ label, actual, target, onEdit }: { label: string; actual: number; target: number; onEdit: () => void }) {
  const pct = target > 0 ? Math.min((actual / target) * 100, 100) : 0;
  const dayOfWeek = new Date().getDay();
  const daysIn = Math.max(dayOfWeek === 0 ? 7 : dayOfWeek, 1);
  const pace = (actual / daysIn) * 7;
  const barColor = pace >= target ? "bg-green-500" : pace >= target * 0.8 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{label}</span>
        <div className="flex items-center gap-1">
          <span className="text-xs font-semibold text-gray-900 dark:text-gray-100">{actual}</span>
          <span className="text-xs text-gray-400">/</span>
          <button onClick={onEdit} className="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:underline underline-offset-2">{target}</button>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800">
        <div className={cn("h-1.5 rounded-full transition-all", barColor)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function qualityBadgeClass(score?: number): string {
  if (!score) return "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400";
  if (score >= 80) return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300";
  if (score >= 60) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
}

// ---------------------------------------------------------------------------
// Thread helpers
// ---------------------------------------------------------------------------

const CLASSIFICATION_COLORS: Record<string, string> = {
  interested: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 border-green-200 dark:border-green-800",
  objection: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800",
  out_of_office: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-800",
  soft_no: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-600",
  unsubscribe: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800",
  referral: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300 border-purple-200 dark:border-purple-800",
  bounce: "bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400 border-red-100 dark:border-red-900",
  other: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 border-gray-200 dark:border-gray-600",
};

const CLASSIFICATION_LABELS: Record<string, string> = {
  interested: "Interested", objection: "Objection", out_of_office: "Out of Office",
  soft_no: "Soft No", unsubscribe: "Unsubscribe", referral: "Referral",
  bounce: "Bounce", other: "Other",
};

const ALL_CLASSIFICATIONS = ["interested", "objection", "soft_no", "out_of_office", "referral", "unsubscribe", "bounce", "other"];

// ---------------------------------------------------------------------------
// Threads sub-components
// ---------------------------------------------------------------------------

function ThreadListItem({ thread, selected, onClick }: { thread: CampaignThread; selected: boolean; onClick: () => void }) {
  const company = thread.companies;
  const contact = thread.contacts;
  const lastMsg = thread.last_message;
  const classification = lastMsg?.classification;
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors",
        selected && "bg-gray-50 dark:bg-gray-800/50 border-l-2 border-l-gray-900 dark:border-l-gray-100"
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">{company?.name ?? "Unknown"}</span>
        <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500 whitespace-nowrap">{timeSince(lastMsg?.sent_at)}</span>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-500 mb-1.5 truncate">{contact?.full_name ?? "Unknown"}</p>
      {lastMsg && <p className="text-xs text-gray-400 dark:text-gray-600 truncate mb-1.5">{lastMsg.body?.slice(0, 80) ?? "(no body)"}</p>}
      <div className="flex items-center justify-between gap-2">
        {classification ? (
          <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-medium", CLASSIFICATION_COLORS[classification] ?? CLASSIFICATION_COLORS.other)}>
            {CLASSIFICATION_LABELS[classification] ?? classification}
          </span>
        ) : (
          <span className="rounded border border-dashed border-gray-300 dark:border-gray-600 px-1.5 py-0.5 text-[10px] font-medium text-gray-400 dark:text-gray-500">Unclassified</span>
        )}
        <span className="text-[10px] text-gray-400 dark:text-gray-500">{thread.step_display ?? `Step ${thread.current_step ?? 1}`}</span>
      </div>
    </button>
  );
}

function ClassificationCard({ message, threadId, onConfirmed }: { message: ThreadMessage; threadId: string; onConfirmed: (cls: string, draftId?: string) => void }) {
  const [loading, setLoading] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  const classification = message.classification;
  const confidence = message.classification_confidence ?? 0;

  const confirm = async (override?: string) => {
    const cls = override || classification;
    if (!cls) return;
    setLoading(true);
    try {
      const res = await confirmThreadClassification(threadId, { message_id: message.id, classification: cls, override: !!override });
      onConfirmed(cls, res.draft_id);
    } catch { /* noop */ } finally { setLoading(false); setShowOverride(false); }
  };

  return (
    <div className="mt-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">AI Classification</span>
        {message.classification_confirmed_by && <span className="text-[10px] text-gray-400">Confirmed</span>}
      </div>
      {classification ? (
        <div className="flex items-center gap-3 mb-2">
          <span className={cn("rounded border px-2 py-0.5 text-xs font-semibold", CLASSIFICATION_COLORS[classification] ?? CLASSIFICATION_COLORS.other)}>{CLASSIFICATION_LABELS[classification] ?? classification}</span>
          <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-gray-700">
            <div className="h-2 rounded-full bg-gray-700 dark:bg-gray-300" style={{ width: `${Math.round(confidence * 100)}%` }} />
          </div>
          <span className="text-xs font-medium text-gray-600 dark:text-gray-400">{Math.round(confidence * 100)}%</span>
        </div>
      ) : (
        <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">No classification yet.</p>
      )}
      {message.classification_reasoning && <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">{message.classification_reasoning}</p>}
      {!message.classification_confirmed_by && (
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => confirm()} disabled={loading || !classification}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 disabled:opacity-50">
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />} Confirm
          </button>
          <div className="relative">
            <button onClick={() => setShowOverride(!showOverride)}
              className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700">
              Override <ChevronDown className="h-3 w-3" />
            </button>
            {showOverride && (
              <div className="absolute bottom-full mb-1 left-0 z-10 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg py-1 min-w-[160px]">
                {ALL_CLASSIFICATIONS.map((cls) => (
                  <button key={cls} onClick={() => confirm(cls)}
                    className="block w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
                    {CLASSIFICATION_LABELS[cls]}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function DraftPanel({ draft, threadId, onSent, onRegenerate }: {
  draft: OutreachDraft; threadId: string; onSent: () => void; onRegenerate: (instruction?: string) => Promise<void>;
}) {
  const [editedBody, setEditedBody] = useState(draft.body);
  const [editing, setEditing] = useState(false);
  const [sendLoading, setSendLoading] = useState(false);
  const [regenLoading, setRegenLoading] = useState(false);
  const [showInstruction, setShowInstruction] = useState(false);
  const [instruction, setInstruction] = useState("");

  const handleSend = async () => {
    setSendLoading(true);
    try { await sendThreadDraft(threadId, { draft_id: draft.id, edited_body: editing ? editedBody : undefined }); onSent(); }
    catch { /* noop */ } finally { setSendLoading(false); }
  };

  const handleRegen = async () => {
    setRegenLoading(true);
    try { await onRegenerate(showInstruction ? instruction : undefined); setInstruction(""); setShowInstruction(false); }
    catch { /* noop */ } finally { setRegenLoading(false); }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">AI Draft Response</span>
        <button onClick={() => setEditing(!editing)} className="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">{editing ? "Done editing" : "Edit"}</button>
      </div>
      <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">Subject: {draft.subject}</p>
      <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 mb-3">
        {editing ? (
          <textarea value={editedBody} onChange={(e) => setEditedBody(e.target.value)} rows={6}
            className="w-full rounded-md bg-transparent px-3 py-2 text-xs text-gray-700 dark:text-gray-300 font-mono focus:outline-none resize-none" />
        ) : (
          <pre className="px-3 py-2 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono leading-relaxed max-h-40 overflow-y-auto">{editedBody}</pre>
        )}
      </div>
      {showInstruction && (
        <input type="text" value={instruction} onChange={(e) => setInstruction(e.target.value)}
          placeholder="Instruction for regeneration..."
          onKeyDown={(e) => { if (e.key === "Enter") handleRegen(); if (e.key === "Escape") setShowInstruction(false); }}
          className="w-full mb-2 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-400"
          autoFocus />
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={handleSend} disabled={sendLoading}
          className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 disabled:opacity-50">
          {sendLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />} Approve &amp; Send
        </button>
        <button onClick={handleRegen} disabled={regenLoading}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50">
          {regenLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />} Regenerate
        </button>
        <button onClick={() => setShowInstruction(!showInstruction)} className="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline underline-offset-2">
          {showInstruction ? "Cancel" : "Regenerate with instruction..."}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type Tab = "approvals" | "threads" | "overview";

function CommandCenterInner() {
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") as Tab) ?? "approvals";

  const [activeTab, setActiveTab] = useState<Tab>(initialTab);

  // ── Overview state ──────────────────────────────────────────────────────
  const [overviewData, setOverviewData] = useState<CommandCenterData | null>(null);
  const [hitlStats, setHitlStats] = useState<HitlStats | null>(null);
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsSummary | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [editingGoal, setEditingGoal] = useState<string | null>(null);
  const [goalInput, setGoalInput] = useState("");

  // ── Approvals state ─────────────────────────────────────────────────────
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [totalPending, setTotalPending] = useState<number>(0);
  const [draftsLoading, setDraftsLoading] = useState(true);
  const [draftsError, setDraftsError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [abVariants, setAbVariants] = useState<Record<string, { a: string; b: string; selected: "a" | "b" }>>({});
  const [abLoading, setAbLoading] = useState<string | null>(null);
  const [testSendingId, setTestSendingId] = useState<string | null>(null);
  const [testSendResult, setTestSendResult] = useState<{ id: string; message: string } | null>(null);
  const [qualityScores, setQualityScores] = useState<Record<string, DraftQualityScore>>({});
  const [replyFormId, setReplyFormId] = useState<string | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [replyIntent, setReplyIntent] = useState<LogReplyPayload["intent"]>("interested");
  const [replyNotes, setReplyNotes] = useState("");
  const [replyLoading, setReplyLoading] = useState<string | null>(null);
  const [replySuccess, setReplySuccess] = useState<Record<string, string>>({});
  const TEST_EMAIL = "avi@digitillis.com";

  // ── Threads state ────────────────────────────────────────────────────────
  const [threads, setThreads] = useState<CampaignThread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  const [threadDetail, setThreadDetail] = useState<(CampaignThread & { messages: ThreadMessage[]; pending_draft: OutreachDraft | null }) | null>(null);
  const [threadDetailLoading, setThreadDetailLoading] = useState(false);
  const [threadsNeedsAction, setThreadsNeedsAction] = useState(0);
  const [threadsBadge, setThreadsBadge] = useState(0);

  // ── Fetch overview ──────────────────────────────────────────────────────
  const fetchOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      const [res, hStats, aSum] = await Promise.allSettled([getCommandCenter(), getHitlStats(), getAnalyticsSummary()]);
      if (res.status === "fulfilled") setOverviewData(res.value);
      if (hStats.status === "fulfilled") setHitlStats(hStats.value);
      if (aSum.status === "fulfilled") setAnalyticsSummary(aSum.value);
    } catch { /* noop */ } finally { setOverviewLoading(false); }
  }, []);

  // ── Fetch drafts ────────────────────────────────────────────────────────
  const fetchDrafts = useCallback(async () => {
    setDraftsLoading(true);
    try {
      const res = await getPendingDrafts();
      const sorted = [...res.data].sort((a, b) => (b.companies?.pqs_total ?? 0) - (a.companies?.pqs_total ?? 0));
      setDrafts(sorted);
      setTotalPending(res.total_pending ?? res.count ?? sorted.length);
      setDraftsError(null);
    } catch (err) {
      setDraftsError(err instanceof Error ? err.message : "Failed to load drafts");
    } finally { setDraftsLoading(false); }
  }, []);

  // ── Fetch threads ────────────────────────────────────────────────────────
  const fetchThreads = useCallback(async () => {
    setThreadsLoading(true);
    try {
      const res = await listThreads({ needs_action: true, limit: 200 });
      setThreads(res.data ?? []);
      setThreadsNeedsAction(res.needs_action_count ?? 0);
      setThreadsBadge(res.needs_action_count ?? 0);
    } catch { /* noop */ } finally { setThreadsLoading(false); }
  }, []);

  // ── Fetch thread detail ──────────────────────────────────────────────────
  const fetchThreadDetail = useCallback(async (id: string) => {
    setThreadDetailLoading(true);
    try {
      const res = await getThread(id);
      setThreadDetail(res.data as typeof threadDetail);
    } catch { setThreadDetail(null); } finally { setThreadDetailLoading(false); }
  }, []);

  useEffect(() => {
    fetchOverview();
    fetchDrafts();
  }, [fetchOverview, fetchDrafts]);

  // Lazy-load threads when tab is activated
  useEffect(() => {
    if (activeTab === "threads" && threads.length === 0) {
      fetchThreads();
    }
  }, [activeTab, threads.length, fetchThreads]);

  useEffect(() => {
    if (selectedThreadId) fetchThreadDetail(selectedThreadId);
  }, [selectedThreadId, fetchThreadDetail]);

  // ── Approval handlers ────────────────────────────────────────────────────
  const handleApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await approveDraft(id);
      setDrafts((prev) => { const next = prev.filter((d) => d.id !== id); return next; });
      setFocusedIndex((i) => Math.min(i, drafts.length - 2));
    } catch (err) { setDraftsError(err instanceof Error ? err.message : "Failed to approve"); }
    finally { setActionLoading(null); }
  };

  const handleSaveEdit = async (id: string) => {
    setActionLoading(id);
    try {
      await saveDraftEdit(id, editBody);
      setDrafts((prev) => prev.map((d) => d.id === id ? { ...d, edited_body: editBody, body: editBody } : d));
      setEditingId(null); setEditBody("");
    } catch (err) { setDraftsError(err instanceof Error ? err.message : "Failed to save edit"); }
    finally { setActionLoading(null); }
  };

  const handleReject = async (id: string) => {
    if (!rejectReason.trim()) return;
    setActionLoading(id);
    try {
      await rejectDraft(id, rejectReason);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setRejectingId(null); setRejectReason("");
      setFocusedIndex((i) => Math.min(i, drafts.length - 2));
    } catch (err) { setDraftsError(err instanceof Error ? err.message : "Failed to reject"); }
    finally { setActionLoading(null); }
  };

  const handleLogReply = async (draft: OutreachDraft) => {
    if (!replyBody.trim()) return;
    setReplyLoading(draft.id);
    try {
      const res = await logReply(draft.contact_id, { body: replyBody, intent: replyIntent, notes: replyNotes || undefined });
      setReplySuccess((prev) => ({ ...prev, [draft.id]: res.intent }));
      setReplyFormId(null); setReplyBody(""); setReplyNotes("");
    } catch (err) { setDraftsError(err instanceof Error ? err.message : "Failed to log reply"); }
    finally { setReplyLoading(null); }
  };

  const handleTestSend = async (id: string) => {
    setTestSendingId(id); setTestSendResult(null);
    try {
      const res = await testSendDraft(id, TEST_EMAIL);
      setTestSendResult({ id, message: res.message });
      setTimeout(() => setTestSendResult(null), 5000);
    } catch (err) { setTestSendResult({ id, message: err instanceof Error ? err.message : "Failed" }); }
    finally { setTestSendingId(null); }
  };

  const startEditing = (draft: OutreachDraft) => { setEditingId(draft.id); setEditBody(draft.edited_body || draft.body); setRejectingId(null); setRejectReason(""); };
  const startRejecting = (id: string) => { setRejectingId(id); setRejectReason(""); setEditingId(null); setEditBody(""); };

  const generateVariant = (draft: OutreachDraft) => {
    setAbLoading(draft.id);
    setTimeout(() => {
      const original = draft.subject;
      let variant = original.endsWith("?") ? original.split(" ").slice(0, 5).join(" ") :
        (original.toLowerCase().startsWith("re:") || original.toLowerCase().includes("follow"))
          ? `Quick question about ${draft.companies?.name || "your team"}`
          : `${original.split(" ").slice(0, 4).join(" ")}?`;
      if (variant === original && draft.companies?.name) variant = `${draft.companies.name} — ${original}`;
      setAbVariants((prev) => ({ ...prev, [draft.id]: { a: original, b: variant, selected: "a" } }));
      setAbLoading(null);
    }, 300);
  };

  // Keyboard shortcuts (Approvals tab only)
  useEffect(() => {
    if (activeTab !== "approvals") return;
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      switch (e.key) {
        case "j": setFocusedIndex((i) => Math.min(i + 1, drafts.length - 1)); break;
        case "k": setFocusedIndex((i) => Math.max(i - 1, 0)); break;
        case "a": if (drafts[focusedIndex] && !editingId && !rejectingId) handleApprove(drafts[focusedIndex].id); break;
        case "e": if (drafts[focusedIndex] && !editingId && !rejectingId) startEditing(drafts[focusedIndex]); break;
        case "r": if (drafts[focusedIndex] && !editingId && !rejectingId) startRejecting(drafts[focusedIndex].id); break;
        case "Escape":
          if (editingId) { setEditingId(null); setEditBody(""); }
          if (rejectingId) { setRejectingId(null); setRejectReason(""); }
          break;
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [activeTab, drafts, focusedIndex, editingId, rejectingId]);

  useEffect(() => {
    if (activeTab !== "approvals") return;
    const el = document.getElementById(`draft-${drafts[focusedIndex]?.id}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedIndex, drafts, activeTab]);

  // ── Thread handlers ───────────────────────────────────────────────────────
  const handleClassificationConfirmed = (_cls: string, draftId?: string) => {
    if (selectedThreadId) fetchThreadDetail(selectedThreadId);
  };

  const handleThreadSent = () => {
    if (selectedThreadId) fetchThreadDetail(selectedThreadId);
    fetchThreads();
  };

  const handleRegenerate = async (instruction?: string) => {
    if (!selectedThreadId) return;
    await regenerateThreadDraft(selectedThreadId, { instruction });
    if (selectedThreadId) fetchThreadDetail(selectedThreadId);
  };

  const saveGoal = async (key: string, value: number) => {
    if (!overviewData) return;
    try {
      await updateIntelligenceGoals({ [key]: value } as Parameters<typeof updateIntelligenceGoals>[0]);
      setOverviewData((prev) => prev ? { ...prev, weekly_goals: { ...prev.weekly_goals, targets: { ...prev.weekly_goals.targets, [key]: value } } } : prev);
    } catch { /* noop */ }
    setEditingGoal(null);
  };

  // ── Derived values ────────────────────────────────────────────────────────
  const kpis = overviewData?.kpis;
  const goals = overviewData?.weekly_goals;
  const billing = overviewData?.billing_status;

  return (
    <div className="flex flex-col -m-6">

      {/* ── Tab bar ── */}
      <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-4 py-0 shrink-0">
        <div className="flex items-center gap-0">
          {([
            { key: "approvals" as Tab, label: "Approvals", count: drafts.length > 0 ? drafts.length : totalPending || undefined },
            { key: "threads" as Tab, label: "Threads", count: threadsBadge > 0 ? threadsBadge : undefined },
            { key: "overview" as Tab, label: "Overview", count: undefined },
          ]).map(({ key, label, count }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={cn(
                "relative px-4 py-3 text-sm font-medium transition-colors border-b-2 -mb-px",
                activeTab === key
                  ? "border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100"
                  : "border-transparent text-gray-500 dark:text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
              )}
            >
              {label}
              {count !== undefined && (
                <span className={cn(
                  "ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold",
                  key === "approvals" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300"
                )}>
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>
        <button onClick={() => { fetchDrafts(); fetchOverview(); if (activeTab === "threads") fetchThreads(); }}
          className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800">
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </div>

      {/* ── Tab: Approvals ── */}
      {activeTab === "approvals" && (
        <div className="flex-1 overflow-y-auto">
          <div className="space-y-4 p-4">
            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Approval Queue</h2>
                {!draftsLoading && (
                  <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
                    {drafts.length}{totalPending > drafts.length ? ` of ${totalPending}` : ""} pending
                  </span>
                )}
              </div>
              {drafts.length > 0 && (
                <div className="hidden sm:flex items-center gap-3 text-[10px] text-gray-400 dark:text-gray-500">
                  {[["j/k", "Navigate"], ["a", "Approve"], ["e", "Edit"], ["r", "Reject"]].map(([key, label]) => (
                    <span key={key}><kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono text-[10px]">{key}</kbd> {label}</span>
                  ))}
                </div>
              )}
            </div>

            {draftsError && (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4 text-sm text-gray-700 dark:text-gray-300">{draftsError}</div>
            )}

            {draftsLoading ? (
              <div className="flex h-48 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>
            ) : drafts.length === 0 && !draftsError ? (
              <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 py-16">
                <Inbox className="h-12 w-12 text-gray-300" />
                <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-gray-100">No pending approvals</h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">All drafts have been reviewed. Check back later.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {drafts.map((draft, idx) => (
                  <div id={`draft-${draft.id}`} key={draft.id}
                    className={cn("rounded-lg border bg-white dark:bg-gray-900 transition-all",
                      idx === focusedIndex ? "border-gray-900 ring-1 ring-gray-900/10" : "border-gray-200 dark:border-gray-700"
                    )}>
                    {/* Header */}
                    <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-6 py-4">
                      <div className="flex items-center gap-3">
                        <Building2 className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                        <span className="text-lg font-semibold text-gray-900 dark:text-gray-100">{draft.companies?.name ?? "Unknown"}</span>
                        {draft.companies?.tier && (
                          <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2.5 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-500">
                            {TIER_LABELS[draft.companies.tier] ?? draft.companies.tier}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-xs text-gray-400 dark:text-gray-500">{idx + 1} of {drafts.length}</span>
                        <DraftQualityBadge draftId={draft.id} initialScore={qualityScores[draft.id] ?? null}
                          onScored={(result) => setQualityScores((prev) => ({ ...prev, [draft.id]: result }))} />
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">PQS</span>
                          <span className={cn("text-xl font-bold", getPQSColor(draft.companies?.pqs_total ?? 0))}>{draft.companies?.pqs_total ?? 0}</span>
                        </div>
                      </div>
                    </div>

                    <div className="px-6 py-4 space-y-4">
                      {/* Contact */}
                      <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-500">
                        <div className="flex items-center gap-1.5">
                          <User className="h-4 w-4 text-gray-400" />
                          <span className="font-medium">{draft.contacts?.full_name ?? "Unknown"}</span>
                          {draft.contacts?.title && <span className="text-gray-400">&middot; {draft.contacts.title}</span>}
                        </div>
                        {draft.contacts?.email && (
                          <div className="flex items-center gap-1.5">
                            <Mail className="h-4 w-4 text-gray-400" />
                            <span>{draft.contacts.email}</span>
                          </div>
                        )}
                      </div>

                      {/* Message */}
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-4">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex-1">{draft.subject}</p>
                          {!abVariants[draft.id] && (
                            <button onClick={() => generateVariant(draft)} disabled={abLoading === draft.id}
                              className="inline-flex items-center gap-1 rounded border border-gray-200 dark:border-gray-700 px-2 py-0.5 text-xs text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50">
                              {abLoading === draft.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Shuffle className="h-3 w-3" />} A/B
                            </button>
                          )}
                        </div>
                        {abVariants[draft.id] && (
                          <div className="mt-2 space-y-2">
                            <p className="text-xs font-medium text-gray-500">Choose a subject:</p>
                            {(["a", "b"] as const).map((v) => (
                              <button key={v}
                                onClick={() => setAbVariants((prev) => ({ ...prev, [draft.id]: { ...prev[draft.id], selected: v } }))}
                                className={cn("flex w-full items-center gap-2 rounded-lg border p-2.5 text-left text-sm transition-colors",
                                  abVariants[draft.id].selected === v ? "border-gray-900 bg-gray-50 dark:bg-gray-800 text-gray-900" : "border-gray-200 dark:border-gray-700 text-gray-600 hover:bg-gray-50")}>
                                <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                                  abVariants[draft.id].selected === v ? "bg-gray-900 text-white" : "bg-gray-200 text-gray-500")}>
                                  {v.toUpperCase()}
                                </span>
                                <span className="flex-1">{abVariants[draft.id][v]}</span>
                                {v === "a" && <span className="text-xs text-gray-400">Original</span>}
                              </button>
                            ))}
                          </div>
                        )}
                        {editingId === draft.id ? (
                          <textarea value={editBody} onChange={(e) => setEditBody(e.target.value)} rows={6}
                            className="mt-2 w-full rounded-md border border-gray-200 dark:border-gray-700 p-3 text-sm text-gray-700 dark:text-gray-300 focus:border-gray-300 focus:outline-none" />
                        ) : (
                          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-700 dark:text-gray-300">{draft.edited_body || draft.body}</p>
                        )}
                      </div>

                      {draft.personalization_notes && (
                        <p className="text-xs italic text-gray-500 dark:text-gray-500">{draft.personalization_notes}</p>
                      )}

                      {/* Reject reason input */}
                      {rejectingId === draft.id && (
                        <div className="flex items-center gap-2">
                          <input type="text" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
                            placeholder="Rejection reason..." onKeyDown={(e) => { if (e.key === "Enter") handleReject(draft.id); }}
                            className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm focus:outline-none" autoFocus />
                          <button onClick={() => handleReject(draft.id)} disabled={!rejectReason.trim() || actionLoading === draft.id}
                            className="rounded-md bg-gray-900 px-4 py-2 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50">
                            {actionLoading === draft.id ? <Loader2 className="h-4 w-4 animate-spin" /> : "Confirm"}
                          </button>
                          <button onClick={() => setRejectingId(null)} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                        </div>
                      )}

                      {/* Actions */}
                      <div className="flex items-center gap-2 pt-2">
                        {editingId === draft.id ? (
                          <>
                            <button onClick={() => handleSaveEdit(draft.id)} disabled={actionLoading === draft.id}
                              className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50">
                              {actionLoading === draft.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Save
                            </button>
                            <button onClick={() => { setEditingId(null); setEditBody(""); }}
                              className="rounded-md px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800">Cancel</button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => handleApprove(draft.id)} disabled={actionLoading === draft.id}
                              className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50">
                              {actionLoading === draft.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Approve
                            </button>
                            <button onClick={() => startEditing(draft)}
                              className="inline-flex items-center gap-1.5 rounded-md bg-gray-100 dark:bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
                              <Pencil className="h-4 w-4" /> Edit
                            </button>
                            <button onClick={() => startRejecting(draft.id)}
                              className="inline-flex items-center gap-1.5 rounded-md bg-gray-100 dark:bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
                              <XCircle className="h-4 w-4" /> Reject
                            </button>
                            <button onClick={() => handleTestSend(draft.id)} disabled={testSendingId === draft.id}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 disabled:opacity-50">
                              {testSendingId === draft.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />} Test Send
                            </button>
                            {draft.sent_at && !replySuccess[draft.id] && (
                              <button onClick={() => { setReplyFormId(replyFormId === draft.id ? null : draft.id); setReplyBody(""); setReplyNotes(""); setReplyIntent("interested"); }}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100">
                                <MessageSquareReply className="h-4 w-4" /> Log Reply
                              </button>
                            )}
                            {replySuccess[draft.id] && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
                                Replied &middot; {replySuccess[draft.id]}
                              </span>
                            )}
                          </>
                        )}
                        {testSendResult?.id === draft.id && (
                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{testSendResult.message}</span>
                        )}
                      </div>

                      {/* Log reply form */}
                      {replyFormId === draft.id && (
                        <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-4 space-y-3">
                          <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">Log Reply from Prospect</p>
                          <textarea value={replyBody} onChange={(e) => setReplyBody(e.target.value)} rows={3}
                            placeholder="Paste the reply text here..."
                            className="w-full rounded-md border border-amber-200 bg-white p-2.5 text-sm text-gray-700 focus:border-amber-400 focus:outline-none" />
                          <div className="flex items-center gap-3">
                            <select value={replyIntent} onChange={(e) => setReplyIntent(e.target.value as LogReplyPayload["intent"])}
                              className="rounded-md border border-amber-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 focus:outline-none">
                              <option value="interested">Interested</option>
                              <option value="not_interested">Not Interested</option>
                              <option value="question">Question</option>
                              <option value="referral">Referral</option>
                              <option value="objection">Objection</option>
                            </select>
                            <input type="text" value={replyNotes} onChange={(e) => setReplyNotes(e.target.value)}
                              placeholder="Notes (optional)"
                              className="flex-1 rounded-md border border-amber-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 focus:outline-none" />
                            <button onClick={() => handleLogReply(draft)} disabled={!replyBody.trim() || replyLoading === draft.id}
                              className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50">
                              {replyLoading === draft.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />} Save
                            </button>
                            <button onClick={() => setReplyFormId(null)} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab: Threads ── */}
      {activeTab === "threads" && (
        <div className="flex overflow-hidden" style={{ height: "calc(100vh - 12rem)" }}>
          {/* Thread list */}
          <div className="w-72 shrink-0 overflow-y-auto border-r border-gray-200 dark:border-gray-800">
            <div className="sticky top-0 z-10 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">Threads</span>
                  {threadsNeedsAction > 0 && (
                    <span className="rounded-full bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-[10px] font-bold text-red-700 dark:text-red-300">{threadsNeedsAction} need action</span>
                  )}
                </div>
                <button onClick={fetchThreads} className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                  <RefreshCw className="h-4 w-4" />
                </button>
              </div>
            </div>

            {threadsLoading ? (
              <div className="p-4 space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i}><Skeleton className="h-4 w-3/4 mb-1" /><Skeleton className="h-3 w-1/2" /></div>
                ))}
              </div>
            ) : threads.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                <CheckCircle2 className="h-8 w-8 mb-2" />
                <p className="text-sm">No threads needing action</p>
              </div>
            ) : (
              threads.map((thread) => (
                <ThreadListItem key={thread.id} thread={thread} selected={selectedThreadId === thread.id}
                  onClick={() => setSelectedThreadId(thread.id)} />
              ))
            )}
          </div>

          {/* Thread detail */}
          <div className="flex flex-1 flex-col overflow-hidden bg-white dark:bg-gray-900">
            {!selectedThreadId ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 text-gray-400">
                <MessageSquare className="h-10 w-10" />
                <p className="text-sm">Select a thread to review</p>
              </div>
            ) : threadDetailLoading ? (
              <div className="flex flex-1 flex-col gap-4 p-6">
                <Skeleton className="h-8 w-64" />
                <Skeleton className="h-4 w-96" />
                <div className="space-y-4 flex-1">
                  {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}
                </div>
              </div>
            ) : !threadDetail ? (
              <div className="flex flex-1 items-center justify-center text-gray-400">
                <p className="text-sm">Thread not found</p>
              </div>
            ) : (
              <div className="flex flex-1 flex-col overflow-hidden">
                {/* Thread top bar */}
                <div className="border-b border-gray-200 dark:border-gray-800 px-6 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">{threadDetail.companies?.name ?? "Unknown"}</h2>
                      <p className="text-sm text-gray-500 dark:text-gray-400">{threadDetail.contacts?.full_name} &middot; {threadDetail.contacts?.title}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2.5 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-400">
                        {threadDetail.step_display ?? `Step ${threadDetail.current_step ?? 1}`}
                      </span>
                      <span className={cn("rounded px-2 py-0.5 text-xs font-medium", getPQSColor(threadDetail.companies?.pqs_total ?? 0))}>
                        PQS {threadDetail.companies?.pqs_total ?? 0}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-6 space-y-4">
                  {threadDetail.messages.map((msg) => {
                    const isInbound = msg.direction === "inbound";
                    return (
                      <div key={msg.id} className={cn("flex", isInbound ? "justify-start" : "justify-end")}>
                        <div className={cn("max-w-[75%] rounded-xl px-4 py-3", isInbound ? "bg-gray-100 dark:bg-gray-800" : "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900")}>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-[10px] font-semibold uppercase tracking-wide opacity-60">{isInbound ? "Prospect" : "Sent"}</span>
                            <span className="text-[10px] opacity-50">{timeSince(msg.sent_at)}</span>
                          </div>
                          {msg.subject && <p className="text-xs font-semibold mb-1 opacity-80">{msg.subject}</p>}
                          <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.body}</p>
                          {isInbound && <ClassificationCard message={msg} threadId={threadDetail.id} onConfirmed={handleClassificationConfirmed} />}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Draft panel */}
                {threadDetail.pending_draft && (
                  <DraftPanel draft={threadDetail.pending_draft} threadId={threadDetail.id}
                    onSent={handleThreadSent} onRegenerate={handleRegenerate} />
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab: Overview ── */}
      {activeTab === "overview" && (
        <div className="flex-1 overflow-y-auto">
          <div className="space-y-6 p-4">
            {/* Attention bar */}
            {overviewLoading ? (
              <Skeleton className="h-12 w-full rounded-lg" />
            ) : overviewData?.attention_items && overviewData.attention_items.length > 0 ? (
              <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-4 py-3">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                  {overviewData.attention_items.map((item, i) => (
                    <span key={i} className="text-sm text-amber-800 dark:text-amber-300">
                      <Link href={item.href} className="font-medium hover:underline">{item.label}</Link>
                      {i < overviewData.attention_items.length - 1 && <span className="ml-4 text-amber-400">·</span>}
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20 px-4 py-3 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <span className="text-sm font-medium text-green-700 dark:text-green-400">All clear</span>
              </div>
            )}

            {/* KPI Cards */}
            {overviewLoading ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
                    <Skeleton className="h-3 w-24 mb-3" /><Skeleton className="h-8 w-16" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
                <KPICard label="Pipeline" value={kpis?.pipeline_total ?? 0} sub="total companies" />
                <KPICard label="Researched" value={kpis?.researched ?? 0} sub={`${kpis?.researched_pct ?? 0}% of pipeline`} />
                <KPICard label="Active Outreach" value={kpis?.active_outreach ?? 0} sub="in sequence" />
                <KPICard label="Replies This Week" value={kpis?.replies_this_week ?? 0} color={(kpis?.replies_this_week ?? 0) > 0 ? "text-green-600 dark:text-green-400" : undefined} />
                <KPICard label="Meetings Booked" value={kpis?.meetings_booked ?? 0} color={(kpis?.meetings_booked ?? 0) > 0 ? "text-green-600 dark:text-green-400" : undefined} />
                <KPICard label="AI Cost / Month" value={`$${(kpis?.ai_cost_month ?? 0).toFixed(2)}`} sub={`${kpis?.ai_cost_pct ?? 0}% of $${kpis?.ai_cost_cap ?? 200} cap`}
                  color={(kpis?.ai_cost_pct ?? 0) >= 90 ? "text-red-600 dark:text-red-400" : undefined} />
              </div>
            )}

            {/* Billing warning */}
            {!overviewLoading && billing && (billing.approaching_limit || billing.over_limit) && (
              <div className={cn("rounded-lg border px-4 py-3 flex items-center justify-between",
                billing.over_limit ? "border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20" : "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20")}>
                <span className="text-sm text-gray-800 dark:text-gray-200">
                  Used <strong>{billing.companies_this_month.toLocaleString()} / {billing.companies_limit.toLocaleString()}</strong> companies this month ({billing.usage_pct}%).
                </span>
                <Link href="/settings/billing" className="ml-4 shrink-0 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800">Upgrade</Link>
              </div>
            )}

            {/* Weekly cadence */}
            {!overviewLoading && goals && (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Weekly Cadence</h3>
                  <span className="text-xs text-gray-400 dark:text-gray-500">Click a target to edit</span>
                </div>
                <div className="flex flex-wrap gap-6">
                  {([
                    { key: "researched_target", actKey: "researched", label: "Researched" },
                    { key: "emails_sent_target", actKey: "emails_sent", label: "Emails Sent" },
                    { key: "replies_target", actKey: "replies", label: "Replies" },
                    { key: "meetings_target", actKey: "meetings", label: "Meetings" },
                  ] as const).map(({ key, actKey, label }) => (
                    <div key={key} className="flex-1 min-w-[140px]">
                      {editingGoal === key ? (
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{label}</span>
                          <input type="number" value={goalInput} onChange={(e) => setGoalInput(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") saveGoal(key, parseInt(goalInput) || 0); if (e.key === "Escape") setEditingGoal(null); }}
                            className="w-16 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none" autoFocus />
                          <button onClick={() => saveGoal(key, parseInt(goalInput) || 0)} className="text-xs text-gray-600 hover:text-gray-900">OK</button>
                          <button onClick={() => setEditingGoal(null)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                        </div>
                      ) : (
                        <WeeklyBar label={label} actual={goals.actuals[actKey] ?? 0} target={goals.targets[key] ?? 0}
                          onEdit={() => { setEditingGoal(key); setGoalInput(String(goals.targets[key] ?? 0)); }} />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pipeline funnel */}
            {!overviewLoading && overviewData?.funnel_summary && (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
                <div className="flex items-center gap-2 mb-4">
                  <TrendingUp className="h-4 w-4 text-gray-400" />
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Pipeline Funnel (30 days)</h3>
                </div>
                <div className="flex items-stretch gap-1 overflow-x-auto pb-2">
                  {([
                    { key: "discovered", label: "Discovered" }, { key: "enriched", label: "Enriched" },
                    { key: "sequenced", label: "Sequenced" }, { key: "touch_1_sent", label: "Touch 1" },
                    { key: "replied", label: "Replied" }, { key: "demo_scheduled", label: "Demo" }, { key: "closed_won", label: "Won" },
                  ] as const).map((stage, i, arr) => {
                    const funnel = overviewData.funnel_summary as Record<string, unknown>;
                    const count = (funnel[stage.key] as number) ?? 0;
                    const rates = (funnel.conversion_rates as Record<string, number>) ?? {};
                    const prevKey = i > 0 ? arr[i - 1].key : null;
                    const rate = prevKey ? rates[`${prevKey}_to_${stage.key}`] : null;
                    return (
                      <div key={stage.key} className="flex items-center gap-1 shrink-0">
                        <Link href={`/pipeline?status=${stage.key}`}
                          className="flex flex-col items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 hover:bg-gray-100 dark:hover:bg-gray-700 min-w-[90px]">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">{stage.label}</span>
                          <span className="text-xl font-bold text-gray-900 dark:text-gray-100">{count}</span>
                        </Link>
                        {i < arr.length - 1 && (
                          <div className="flex flex-col items-center shrink-0">
                            <ArrowRight className="h-4 w-4 text-gray-300 dark:text-gray-600" />
                            {rate !== null && rate !== undefined && <span className="text-[9px] text-gray-400">{rate}%</span>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Revenue intelligence */}
            {!overviewLoading && analyticsSummary && (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
                <div className="flex items-center gap-2 mb-3">
                  <DollarSign className="h-4 w-4 text-gray-400" />
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Revenue Intelligence</h3>
                  <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
                    analyticsSummary.pipeline_health === "green" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" :
                    analyticsSummary.pipeline_health === "amber" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" :
                    "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300")}>
                    {analyticsSummary.pipeline_health}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                    <p className="text-xs text-gray-500 mb-1">Projected ARR (90d)</p>
                    <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
                      ${((analyticsSummary.projected_arr_90d ?? 0) / 1000).toFixed(0)}K
                    </p>
                  </div>
                  <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                    <p className="text-xs text-gray-500 mb-1">Total Replied</p>
                    <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{analyticsSummary.total_replied ?? 0}</p>
                  </div>
                  <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                    <p className="text-xs text-gray-500 mb-1">Conversion Rate</p>
                    <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{analyticsSummary.overall_conversion_rate ?? 0}%</p>
                  </div>
                  <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                    <p className="text-xs text-gray-500 mb-1">Best Cluster</p>
                    <p className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate">{analyticsSummary.best_cluster ?? "—"}</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function CommandCenterPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>}>
      <CommandCenterInner />
    </Suspense>
  );
}
