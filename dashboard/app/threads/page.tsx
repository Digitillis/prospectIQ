"use client";

/**
 * Threads — Campaign reply thread management with split-pane layout.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import {
  MessageSquare, ChevronRight, Loader2, RefreshCw, CheckCircle2,
  RotateCcw, Send, ChevronDown, ChevronRight as ChevronR, X,
  Building2, User, Clock,
} from "lucide-react";
import {
  listThreads, getThread, confirmThreadClassification, sendThreadDraft,
  regenerateThreadDraft, approveDraft,
  type CampaignThread, type ThreadMessage, type OutreachDraft,
} from "@/lib/api";
import { cn, getPQSColor } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Classification helpers
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
  interested: "Interested",
  objection: "Objection",
  out_of_office: "Out of Office",
  soft_no: "Soft No",
  unsubscribe: "Unsubscribe",
  referral: "Referral",
  bounce: "Bounce",
  other: "Other",
};

const ALL_CLASSIFICATIONS = [
  "interested", "objection", "soft_no", "out_of_office",
  "referral", "unsubscribe", "bounce", "other",
];

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
// Thread List Item
// ---------------------------------------------------------------------------
function ThreadListItem({
  thread,
  selected,
  onClick,
}: {
  thread: CampaignThread;
  selected: boolean;
  onClick: () => void;
}) {
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
        <span className="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">
          {company?.name ?? "Unknown Company"}
        </span>
        <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500 whitespace-nowrap">
          {timeSince(lastMsg?.sent_at)}
        </span>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-500 mb-1.5 truncate">
        {contact?.full_name ?? "Unknown"} · {contact?.persona_type ?? contact?.title ?? ""}
      </p>
      {lastMsg && (
        <p className="text-xs text-gray-400 dark:text-gray-600 truncate mb-1.5">
          {lastMsg.body?.slice(0, 80) ?? "(no body)"}
        </p>
      )}
      <div className="flex items-center justify-between gap-2">
        {classification ? (
          <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-medium", CLASSIFICATION_COLORS[classification] ?? CLASSIFICATION_COLORS.other)}>
            {CLASSIFICATION_LABELS[classification] ?? classification}
          </span>
        ) : (
          <span className="rounded border border-dashed border-gray-300 dark:border-gray-600 px-1.5 py-0.5 text-[10px] font-medium text-gray-400 dark:text-gray-500">
            Unclassified
          </span>
        )}
        <span className="text-[10px] text-gray-400 dark:text-gray-500">
          {thread.step_display ?? `Step ${thread.current_step ?? 1}`}
        </span>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Classification Card (shown below inbound messages)
// ---------------------------------------------------------------------------
function ClassificationCard({
  message,
  threadId,
  onConfirmed,
}: {
  message: ThreadMessage;
  threadId: string;
  onConfirmed: (classification: string, draftId?: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  const classification = message.classification;
  const confidence = message.classification_confidence ?? 0;

  const confirm = async (override?: string) => {
    const cls = override || classification;
    if (!cls) return;
    setLoading(true);
    try {
      const res = await confirmThreadClassification(threadId, {
        message_id: message.id,
        classification: cls,
        override: !!override,
      });
      onConfirmed(cls, res.draft_id);
    } catch { /* noop */ }
    finally { setLoading(false); setShowOverride(false); }
  };

  return (
    <div className="mt-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">AI Classification</span>
        {message.classification_confirmed_by && (
          <span className="text-[10px] text-gray-400">Confirmed by {message.classification_confirmed_by}</span>
        )}
      </div>
      {classification ? (
        <>
          <div className="flex items-center gap-3 mb-2">
            <span className={cn("rounded border px-2 py-0.5 text-xs font-semibold", CLASSIFICATION_COLORS[classification] ?? CLASSIFICATION_COLORS.other)}>
              {CLASSIFICATION_LABELS[classification] ?? classification}
            </span>
            <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-gray-700">
              <div className="h-2 rounded-full bg-gray-700 dark:bg-gray-300 transition-all" style={{ width: `${Math.round(confidence * 100)}%` }} />
            </div>
            <span className="text-xs font-medium text-gray-600 dark:text-gray-400">{Math.round(confidence * 100)}%</span>
          </div>
          {message.classification_reasoning && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">{message.classification_reasoning}</p>
          )}
        </>
      ) : (
        <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">No classification yet.</p>
      )}

      {!message.classification_confirmed_by && (
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => confirm()}
            disabled={loading || !classification}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
            Confirm
          </button>
          <div className="relative">
            <button
              onClick={() => setShowOverride(!showOverride)}
              className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              Override <ChevronDown className="h-3 w-3" />
            </button>
            {showOverride && (
              <div className="absolute bottom-full mb-1 left-0 z-10 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg py-1 min-w-[160px]">
                {ALL_CLASSIFICATIONS.map((cls) => (
                  <button
                    key={cls}
                    onClick={() => confirm(cls)}
                    className="block w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
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

// ---------------------------------------------------------------------------
// Draft Panel (pinned to bottom)
// ---------------------------------------------------------------------------
function DraftPanel({
  draft,
  threadId,
  onSent,
  onRegenerate,
}: {
  draft: OutreachDraft;
  threadId: string;
  onSent: () => void;
  onRegenerate: (instruction?: string) => Promise<void>;
}) {
  const [editedBody, setEditedBody] = useState(draft.body);
  const [editing, setEditing] = useState(false);
  const [sendLoading, setSendLoading] = useState(false);
  const [regenLoading, setRegenLoading] = useState(false);
  const [showInstruction, setShowInstruction] = useState(false);
  const [instruction, setInstruction] = useState("");

  const handleSend = async () => {
    setSendLoading(true);
    try {
      await sendThreadDraft(threadId, { draft_id: draft.id, edited_body: editing ? editedBody : undefined });
      onSent();
    } catch { /* noop */ }
    finally { setSendLoading(false); }
  };

  const handleRegen = async () => {
    setRegenLoading(true);
    try {
      await onRegenerate(showInstruction ? instruction : undefined);
      setInstruction("");
      setShowInstruction(false);
    } catch { /* noop */ }
    finally { setRegenLoading(false); }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">AI Draft Response</span>
        <button onClick={() => setEditing(!editing)} className="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
          {editing ? "Done editing" : "Edit"}
        </button>
      </div>
      <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
        Subject: {draft.subject}
      </p>
      <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 mb-3">
        {editing ? (
          <textarea
            value={editedBody}
            onChange={(e) => setEditedBody(e.target.value)}
            rows={6}
            className="w-full rounded-md bg-transparent px-3 py-2 text-xs text-gray-700 dark:text-gray-300 font-mono focus:outline-none resize-none"
          />
        ) : (
          <pre className="px-3 py-2 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono leading-relaxed max-h-40 overflow-y-auto">
            {editedBody}
          </pre>
        )}
      </div>
      {showInstruction && (
        <input
          type="text"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="Instruction for regeneration..."
          onKeyDown={(e) => { if (e.key === "Enter") handleRegen(); if (e.key === "Escape") setShowInstruction(false); }}
          className="w-full mb-2 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-400"
          autoFocus
        />
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={handleSend}
          disabled={sendLoading}
          className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-50"
        >
          {sendLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
          Approve & Send
        </button>
        <button
          onClick={handleRegen}
          disabled={regenLoading}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
        >
          {regenLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
          Regenerate
        </button>
        <button
          onClick={() => setShowInstruction(!showInstruction)}
          className="text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline underline-offset-2"
        >
          {showInstruction ? "Cancel instruction" : "Regenerate with instruction..."}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thread Detail
// ---------------------------------------------------------------------------
function ThreadDetail({
  threadId,
  onRefreshList,
}: {
  threadId: string;
  onRefreshList: () => void;
}) {
  const [thread, setThread] = useState<(CampaignThread & { messages: ThreadMessage[]; pending_draft: OutreachDraft | null }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const loadThread = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getThread(threadId);
      setThread(res.data as typeof thread);
    } catch {
      setThread(null);
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  useEffect(() => { loadThread(); }, [loadThread]);

  const handleClassificationConfirmed = (classification: string, draftId?: string) => {
    if (draftId) loadThread(); // reload to show new draft
  };

  const handleSent = () => {
    loadThread();
    onRefreshList();
  };

  const handleRegenerate = async (instruction?: string) => {
    try {
      await regenerateThreadDraft(threadId, { instruction });
      await loadThread();
    } catch { /* noop */ }
  };

  if (loading) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
        <div className="flex-1 space-y-4">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}
        </div>
      </div>
    );
  }

  if (!thread) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center text-gray-400">
          <X className="h-8 w-8 mx-auto mb-2" />
          <p className="text-sm">Thread not found</p>
        </div>
      </div>
    );
  }

  const company = thread.companies;
  const contact = thread.contacts;
  const research = (thread as Record<string, unknown>).research as Record<string, unknown> | null;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-4 py-3 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-gray-900 dark:text-gray-100 truncate">{company?.name ?? "Unknown"}</span>
              <span className="text-gray-400">·</span>
              <span className="text-sm text-gray-600 dark:text-gray-400 truncate">{contact?.full_name} {contact?.persona_type ? `· ${contact.persona_type}` : ""}</span>
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-gray-500 dark:text-gray-500">{thread.sequence_name ?? "Email Sequence"}</span>
              <span className="text-gray-300 dark:text-gray-700">·</span>
              <span className="text-xs text-gray-500 dark:text-gray-500">{thread.step_display ?? `Step ${thread.current_step ?? 1}`}</span>
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium uppercase", thread.status === "active" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" : thread.status === "paused" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400")}>
                {thread.status}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={loadThread} className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            <RefreshCw className="h-4 w-4" />
          </button>
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" title="Toggle company sidebar">
            {sidebarOpen ? <ChevronR className="h-4 w-4" /> : <Building2 className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Body: messages + right sidebar */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* Conversation thread */}
        <div className="flex flex-1 flex-col overflow-hidden min-w-0">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {thread.messages.length === 0 && (
              <div className="text-center text-gray-400 py-8 text-sm">No messages in this thread yet.</div>
            )}
            {thread.messages.map((msg) => (
              <div key={msg.id} className={cn("rounded-lg border p-4", msg.direction === "outbound" ? "border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/30" : "border-blue-100 dark:border-blue-900/30 bg-blue-50/50 dark:bg-blue-950/10")}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                      {msg.direction === "outbound" ? "→ Outbound" : "← Inbound"}
                    </span>
                    <span className="text-xs text-gray-400 dark:text-gray-600">
                      {new Date(msg.sent_at).toLocaleString()}
                    </span>
                  </div>
                  {msg.subject && (
                    <span className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate max-w-xs">{msg.subject}</span>
                  )}
                </div>
                <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
                  {msg.body}
                </pre>
                {msg.direction === "inbound" && (
                  <ClassificationCard
                    message={msg}
                    threadId={threadId}
                    onConfirmed={handleClassificationConfirmed}
                  />
                )}
              </div>
            ))}
          </div>

          {/* Draft panel */}
          {thread.pending_draft && (
            <DraftPanel
              draft={thread.pending_draft}
              threadId={threadId}
              onSent={handleSent}
              onRegenerate={handleRegenerate}
            />
          )}
        </div>

        {/* Right sidebar: company snapshot */}
        {sidebarOpen && (
          <div className="w-56 shrink-0 border-l border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/30 overflow-y-auto p-4 space-y-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-2">Company Snapshot</p>
              <div className="flex items-center gap-2 mb-2">
                <span className={cn("rounded px-2 py-0.5 text-sm font-bold", getPQSColor(company?.pqs_total ?? 0))}>PQS {company?.pqs_total ?? 0}</span>
              </div>
              {company?.campaign_cluster && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  Cluster: <span className="font-medium text-gray-700 dark:text-gray-300">{company.campaign_cluster}</span>
                </p>
              )}
              {company?.status && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  Status: <span className="font-medium text-gray-700 dark:text-gray-300">{company.status}</span>
                </p>
              )}
            </div>

            {company?.research_summary && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1">Research Summary</p>
                <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
                  {company.research_summary.slice(0, 200)}
                  {company.research_summary.length > 200 && "…"}
                </p>
              </div>
            )}

            {company?.pain_signals && company.pain_signals.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1">Pain Signals</p>
                <ul className="space-y-1">
                  {company.pain_signals.slice(0, 3).map((signal, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-gray-600 dark:text-gray-400">
                      <span className="text-amber-400 mt-0.5 shrink-0">●</span>
                      <span>{signal}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {company?.intent_score !== undefined && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1">Intent</p>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-gray-900 dark:text-gray-100">{company.intent_score} pts</span>
                  <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium uppercase",
                    (company.intent_score ?? 0) >= 20 ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" :
                    (company.intent_score ?? 0) >= 12 ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" :
                    "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400"
                  )}>
                    {(company.intent_score ?? 0) >= 20 ? "hot" : (company.intent_score ?? 0) >= 12 ? "warm" : "cold"}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function ThreadsPage() {
  const searchParams = useSearchParams();
  const initialSelected = searchParams.get("selected");

  const [threads, setThreads] = useState<CampaignThread[]>([]);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState(false);
  const [activeTab, setActiveTab] = useState<"needs_action" | "active" | "paused" | "all">("needs_action");
  const [selectedId, setSelectedId] = useState<string | null>(initialSelected);

  const loadThreads = useCallback(async () => {
    setLoading(true);
    try {
      const params: Parameters<typeof listThreads>[0] = {};
      if (activeTab === "needs_action") {
        params.needs_action = true;
      } else if (activeTab !== "all") {
        params.status = activeTab;
      }
      const res = await listThreads(params);
      setThreads(res.data);
      setTableError(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("not accessible") || msg.includes("does not exist") || msg.includes("503")) {
        setTableError(true);
      }
      setThreads([]);
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => { loadThreads(); }, [loadThreads]);

  const tabs = [
    { key: "needs_action" as const, label: "Needs Action" },
    { key: "active" as const, label: "Active" },
    { key: "paused" as const, label: "Paused" },
    { key: "all" as const, label: "All" },
  ];

  const needsActionCount = threads.filter((t) => t.needs_action).length;

  return (
    <div className="flex h-[calc(100vh-56px)] overflow-hidden -m-6">
      {/* Left pane: Thread list */}
      <div className="flex w-80 shrink-0 flex-col border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-gray-400" />
            <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Threads</h1>
          </div>
          <button onClick={loadThreads} className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-100 dark:border-gray-800 shrink-0">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "flex-1 px-2 py-2 text-[10px] font-medium transition-colors",
                activeTab === tab.key
                  ? "border-b-2 border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100"
                  : "text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              )}
            >
              {tab.label}
              {tab.key === "needs_action" && needsActionCount > 0 && (
                <span className="ml-1 rounded-full bg-red-500 px-1 text-[9px] text-white">{needsActionCount}</span>
              )}
            </button>
          ))}
        </div>

        {/* Thread list */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="p-4 border-b border-gray-100 dark:border-gray-800">
                <Skeleton className="h-4 w-32 mb-2" />
                <Skeleton className="h-3 w-48 mb-1" />
                <Skeleton className="h-3 w-40" />
              </div>
            ))
          ) : tableError ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center text-gray-400">
              <MessageSquare className="h-10 w-10 mb-3" />
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Reply tracking not yet set up</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Threads will appear once reply tracking is configured.</p>
            </div>
          ) : threads.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center text-gray-400">
              <CheckCircle2 className="h-10 w-10 mb-3" />
              <p className="text-sm">No threads {activeTab === "needs_action" ? "needing action" : `in ${activeTab}`}</p>
            </div>
          ) : (
            threads.map((thread) => (
              <ThreadListItem
                key={thread.id}
                thread={thread}
                selected={selectedId === thread.id}
                onClick={() => setSelectedId(thread.id)}
              />
            ))
          )}
        </div>
      </div>

      {/* Right pane: Thread detail */}
      <div className="flex flex-1 flex-col overflow-hidden bg-white dark:bg-gray-900">
        {selectedId ? (
          <ThreadDetail
            threadId={selectedId}
            onRefreshList={loadThreads}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-gray-400">
              <MessageSquare className="h-12 w-12 mx-auto mb-3" />
              <p className="text-sm font-medium">Select a thread to view conversation</p>
              <p className="text-xs mt-1">Choose a thread from the left panel</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
