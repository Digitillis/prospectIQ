"use client";

/**
 * Outreach Approval Queue — Review AI-generated drafts before sending
 *
 * Expected actions:
 * Read each draft, approve/edit/reject, check quality score, ensure personalization is genuine
 */


import { useEffect, useState, useCallback, useRef } from "react";
import {
  CheckCircle2,
  XCircle,
  Pencil,
  Mail,
  User,
  Building2,
  Loader2,
  Inbox,
  Shuffle,
  MessageSquareReply,
  AlertTriangle,
  X,
  ChevronDown,
  ChevronRight,
  History,
  FileSearch,
} from "lucide-react";
import { getPendingDrafts, approveDraft, saveDraftEdit, rejectDraft, testSendDraft, scoreDraft, logReply, getDraftThread, getDraftResearch, OutreachDraft, type DraftQualityScore, type LogReplyPayload, type SentEmail, type ResearchIntelligence } from "@/lib/api";
import { cn, TIER_LABELS, getPQSColor } from "@/lib/utils";
import DraftQualityBadge from "@/components/outreach/DraftQualityBadge";

export default function ApprovalsPage() {
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [totalPending, setTotalPending] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
  const [alerts, setAlerts] = useState<{ id: string; assertion: string; detail: string; contact_name: string; evaluated_at: string }[]>([]);
  const [alertsDismissed, setAlertsDismissed] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkApproving, setBulkApproving] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const TEST_EMAIL = "avi@digitillis.com";
  const [expandedThread, setExpandedThread] = useState<Set<string>>(new Set());
  const [expandedResearch, setExpandedResearch] = useState<Set<string>>(new Set());
  const [threadData, setThreadData] = useState<Record<string, SentEmail[]>>({});
  const [researchData, setResearchData] = useState<Record<string, ResearchIntelligence | null>>({});
  const [threadLoading, setThreadLoading] = useState<Set<string>>(new Set());
  const [researchLoading, setResearchLoading] = useState<Set<string>>(new Set());

  const toggleThread = async (draftId: string) => {
    const next = new Set(expandedThread);
    if (next.has(draftId)) {
      next.delete(draftId);
      setExpandedThread(next);
      return;
    }
    next.add(draftId);
    setExpandedThread(next);
    if (threadData[draftId] !== undefined) return;
    setThreadLoading((prev) => new Set(prev).add(draftId));
    try {
      const res = await getDraftThread(draftId);
      setThreadData((prev) => ({ ...prev, [draftId]: res.data }));
    } catch {
      setThreadData((prev) => ({ ...prev, [draftId]: [] }));
    } finally {
      setThreadLoading((prev) => { const n = new Set(prev); n.delete(draftId); return n; });
    }
  };

  const toggleResearch = async (draftId: string) => {
    const next = new Set(expandedResearch);
    if (next.has(draftId)) {
      next.delete(draftId);
      setExpandedResearch(next);
      return;
    }
    next.add(draftId);
    setExpandedResearch(next);
    if (researchData[draftId] !== undefined) return;
    setResearchLoading((prev) => new Set(prev).add(draftId));
    try {
      const res = await getDraftResearch(draftId);
      setResearchData((prev) => ({ ...prev, [draftId]: res.data }));
    } catch {
      setResearchData((prev) => ({ ...prev, [draftId]: null }));
    } finally {
      setResearchLoading((prev) => { const n = new Set(prev); n.delete(draftId); return n; });
    }
  };

  const handleLogReply = async (draft: OutreachDraft) => {
    if (!replyBody.trim()) return;
    setReplyLoading(draft.id);
    try {
      const res = await logReply(draft.contact_id, {
        body: replyBody,
        intent: replyIntent,
        notes: replyNotes || undefined,
      });
      setReplySuccess((prev) => ({ ...prev, [draft.id]: res.intent }));
      setReplyFormId(null);
      setReplyBody("");
      setReplyNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log reply");
    } finally {
      setReplyLoading(null);
    }
  };

  const handleTestSend = async (id: string) => {
    setTestSendingId(id);
    setTestSendResult(null);
    try {
      const res = await testSendDraft(id, TEST_EMAIL);
      setTestSendResult({ id, message: res.message });
      setTimeout(() => setTestSendResult(null), 5000);
    } catch (err) {
      setTestSendResult({ id, message: err instanceof Error ? err.message : "Failed to send test" });
    } finally {
      setTestSendingId(null);
    }
  };

  const fetchDrafts = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getPendingDrafts();
      const sorted = [...res.data].sort(
        (a, b) => (b.companies?.pqs_total ?? 0) - (a.companies?.pqs_total ?? 0)
      );
      setDrafts(sorted);
      setTotalPending(res.total_pending ?? res.count ?? sorted.length);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load drafts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDrafts();
  }, [fetchDrafts]);

  useEffect(() => {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";
    fetch(`${API_BASE}/api/approvals/alerts`)
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => { if (json?.items) setAlerts(json.items); })
      .catch(() => {});
  }, []);

  const handleApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await approveDraft(id);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
      setFocusedIndex((i) => Math.min(i, drafts.length - 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setActionLoading(null);
    }
  };

  const handleBulkApprove = async (ids: string[]) => {
    if (ids.length === 0) return;
    setBulkApproving(true);
    setBulkProgress({ done: 0, total: ids.length });
    let done = 0;
    const BATCH = 5;
    for (let i = 0; i < ids.length; i += BATCH) {
      const batch = ids.slice(i, i + BATCH);
      await Promise.all(
        batch.map(async (id) => {
          try {
            await approveDraft(id);
            setDrafts((prev) => prev.filter((d) => d.id !== id));
            setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
          } catch {
            // leave failed drafts visible
          }
          done++;
          setBulkProgress({ done, total: ids.length });
        })
      );
    }
    setBulkApproving(false);
    setBulkProgress(null);
  };

  const allVisibleIds = drafts.map((d) => d.id);
  const allSelected = allVisibleIds.length > 0 && allVisibleIds.every((id) => selected.has(id));
  const someSelected = allVisibleIds.some((id) => selected.has(id)) && !allSelected;
  const highQCount = drafts.filter((d) => (d.quality_score ?? 0) >= 80).length;

  const handleSelectAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(allVisibleIds));
  };

  const handleSaveEdit = async (id: string) => {
    setActionLoading(id);
    try {
      await saveDraftEdit(id, editBody);
      // Update the draft in-place with the edited body (stays in queue)
      setDrafts((prev) =>
        prev.map((d) =>
          d.id === id ? { ...d, edited_body: editBody, body: editBody } : d
        )
      );
      setEditingId(null);
      setEditBody("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save edit");
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (id: string) => {
    if (!rejectReason.trim()) return;
    setActionLoading(id);
    try {
      await rejectDraft(id, rejectReason);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setRejectingId(null);
      setRejectReason("");
      setFocusedIndex((i) => Math.min(i, drafts.length - 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject");
    } finally {
      setActionLoading(null);
    }
  };

  const startEditing = (draft: OutreachDraft) => {
    setEditingId(draft.id);
    setEditBody(draft.edited_body || draft.body);
    setRejectingId(null);
    setRejectReason("");
  };

  const generateVariant = (draft: OutreachDraft) => {
    setAbLoading(draft.id);
    setTimeout(() => {
      const original = draft.subject;
      let variant = original;

      // Strategy 1: Question format
      if (!original.endsWith("?")) {
        if (original.toLowerCase().startsWith("re:") || original.toLowerCase().includes("follow")) {
          variant = `Quick question about ${draft.companies?.name || "your team"}`;
        } else {
          variant = `${original.split(" ").slice(0, 4).join(" ")}?`;
        }
      }
      // Strategy 2: Shorter version
      else {
        variant = original.split(" ").slice(0, 5).join(" ");
      }

      // Strategy 3: Add personalization if variant unchanged
      if (variant === original && draft.companies?.name) {
        variant = `${draft.companies.name} — ${original}`;
      }

      setAbVariants((prev) => ({
        ...prev,
        [draft.id]: { a: original, b: variant, selected: "a" },
      }));
      setAbLoading(null);
    }, 300);
  };

  const startRejecting = (id: string) => {
    setRejectingId(id);
    setRejectReason("");
    setEditingId(null);
    setEditBody("");
  };

  // Keyboard shortcut handler
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't capture when editing (textarea or input focused)
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;

      switch (e.key) {
        case "j": // Next draft
          setFocusedIndex((i) => Math.min(i + 1, drafts.length - 1));
          break;
        case "k": // Previous draft
          setFocusedIndex((i) => Math.max(i - 1, 0));
          break;
        case "a": // Approve current
          if (drafts[focusedIndex] && !editingId && !rejectingId) {
            handleApprove(drafts[focusedIndex].id);
          }
          break;
        case "e": // Edit current
          if (drafts[focusedIndex] && !editingId && !rejectingId) {
            startEditing(drafts[focusedIndex]);
          }
          break;
        case "r": // Reject current
          if (drafts[focusedIndex] && !editingId && !rejectingId) {
            startRejecting(drafts[focusedIndex].id);
          }
          break;
        case "Escape":
          if (editingId) { setEditingId(null); setEditBody(""); }
          if (rejectingId) { setRejectingId(null); setRejectReason(""); }
          break;
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [drafts, focusedIndex, editingId, rejectingId]);

  // Scroll focused draft into view
  useEffect(() => {
    const el = document.getElementById(`draft-${drafts[focusedIndex]?.id}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedIndex, drafts]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400 dark:text-gray-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Approval Queue</h2>
          <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
            {drafts.length}{totalPending > drafts.length ? ` of ${totalPending}` : ""} pending
          </span>
        </div>
      </div>

      {/* Pre-send assertion failures — shown until dismissed */}
      {alerts.length > 0 && !alertsDismissed && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/20 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <div>
                <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
                  {alerts.length} email{alerts.length !== 1 ? "s" : ""} held — pre-send check failed
                </p>
                <ul className="mt-1.5 space-y-1">
                  {alerts.slice(0, 5).map((a) => (
                    <li key={a.id} className="text-xs text-amber-700 dark:text-amber-300">
                      <span className="font-medium">{a.assertion.replace(/_/g, " ")}</span>
                      {a.contact_name ? ` · ${a.contact_name}` : ""}
                      {" — "}
                      {a.detail}
                    </li>
                  ))}
                  {alerts.length > 5 && (
                    <li className="text-xs text-amber-600 dark:text-amber-400">
                      +{alerts.length - 5} more in the last 24h
                    </li>
                  )}
                </ul>
              </div>
            </div>
            <button
              onClick={() => setAlertsDismissed(true)}
              className="shrink-0 rounded p-0.5 text-amber-500 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-200"
              title="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4 text-sm text-gray-700 dark:text-gray-300">
          {error}
        </div>
      )}

      {/* Bulk action bar */}
      {!loading && drafts.length > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-2">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={allSelected}
              ref={(el) => { if (el) el.indeterminate = someSelected; }}
              onChange={handleSelectAll}
              className="h-4 w-4 rounded"
            />
            <span className="text-xs text-gray-600 dark:text-gray-400">
              {allSelected ? "Deselect all" : someSelected ? `${selected.size} selected` : "Select all"}
            </span>
          </label>
          {selected.size > 0 && (
            <>
              <span className="text-gray-300 dark:text-gray-600">|</span>
              <button
                onClick={() => handleBulkApprove([...selected])}
                disabled={bulkApproving}
                className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-50"
              >
                {bulkApproving ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                Approve {selected.size}
                {bulkProgress && ` (${bulkProgress.done}/${bulkProgress.total})`}
              </button>
              <button
                onClick={() => setSelected(new Set())}
                className="text-xs text-gray-400 hover:text-gray-700"
              >
                Clear
              </button>
            </>
          )}
          {highQCount > 0 && (
            <>
              <span className="text-gray-300 dark:text-gray-600 ml-auto">|</span>
              <button
                onClick={() => handleBulkApprove(drafts.filter((d) => (d.quality_score ?? 0) >= 80).map((d) => d.id))}
                disabled={bulkApproving}
                className="rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-700 disabled:opacity-50"
              >
                Approve all ≥80 ({highQCount})
              </button>
            </>
          )}
        </div>
      )}

      {/* Empty State */}
      {drafts.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 py-16">
          <Inbox className="h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-gray-100">
            No pending approvals
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">
            All outreach drafts have been reviewed. Check back later.
          </p>
        </div>
      )}

      {/* Draft Cards */}
      <div className="space-y-4">
        {drafts.map((draft, idx) => (
          <div
            id={`draft-${draft.id}`}
            key={draft.id}
            className={cn(
              "rounded-lg border bg-white dark:bg-gray-900 transition-all",
              idx === focusedIndex
                ? "border-gray-900 ring-1 ring-gray-900/10"
                : "border-gray-200 dark:border-gray-700"
            )}
          >
            {/* Company Header */}
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-6 py-4">
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={selected.has(draft.id)}
                  onChange={(e) =>
                    setSelected((prev) => {
                      const n = new Set(prev);
                      e.target.checked ? n.add(draft.id) : n.delete(draft.id);
                      return n;
                    })
                  }
                  className="h-4 w-4 rounded"
                />
                <Building2 className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                <span className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  {draft.companies?.name ?? "Unknown Company"}
                </span>
                {draft.companies?.tier && (
                  <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2.5 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-500">
                    {TIER_LABELS[draft.companies.tier] ?? draft.companies.tier}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-4">
                {/* Draft position indicator */}
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  {idx + 1} of {drafts.length}
                </span>
                {/* Quality badge */}
                <DraftQualityBadge
                  draftId={draft.id}
                  initialScore={qualityScores[draft.id] ?? null}
                  onScored={(result) => setQualityScores((prev) => ({ ...prev, [draft.id]: result }))}
                />
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
                    PQS
                  </span>
                  <span
                    className={cn(
                      "text-xl font-bold",
                      getPQSColor(draft.companies?.pqs_total ?? 0)
                    )}
                  >
                    {draft.companies?.pqs_total ?? 0}
                  </span>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 space-y-4">
              {/* Contact Info */}
              <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-500">
                <div className="flex items-center gap-1.5">
                  <User className="h-4 w-4 text-gray-400 dark:text-gray-500" />
                  <span className="font-medium">
                    {draft.contacts?.full_name ?? "Unknown Contact"}
                  </span>
                  {draft.contacts?.title && (
                    <span className="text-gray-400 dark:text-gray-500">
                      &middot; {draft.contacts.title}
                    </span>
                  )}
                  {draft.sequence_step && (
                    <span className="ml-1 rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-500 dark:text-gray-400">
                      Step {draft.sequence_step}
                    </span>
                  )}
                </div>
                {draft.contacts?.email && (
                  <div className="flex items-center gap-1.5">
                    <Mail className="h-4 w-4 text-gray-400 dark:text-gray-500" />
                    <span>{draft.contacts.email}</span>
                  </div>
                )}
                {/* Engagement signals from prior steps */}
                {draft.sequence_step > 1 && (
                  <div className="flex items-center gap-1.5">
                    {(draft.contacts?.click_count ?? 0) > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-green-50 dark:bg-green-900/20 px-2 py-0.5 text-xs font-medium text-green-700 dark:text-green-400">
                        Clicked step {draft.sequence_step - 1}
                      </span>
                    ) : (draft.contacts?.open_count ?? 0) > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 dark:bg-blue-900/20 px-2 py-0.5 text-xs font-medium text-blue-600 dark:text-blue-400">
                        Opened step {draft.sequence_step - 1}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-gray-50 dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-400 dark:text-gray-500">
                        No engagement on step {draft.sequence_step - 1}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Message Preview */}
              <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-4">
                {/* Subject with A/B test option */}
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex-1">{draft.subject}</p>
                  {!abVariants[draft.id] && (
                    <button
                      onClick={(e) => { e.stopPropagation(); generateVariant(draft); }}
                      disabled={abLoading === draft.id}
                      className="inline-flex items-center gap-1 rounded border border-gray-200 dark:border-gray-700 px-2 py-0.5 text-xs text-gray-500 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                    >
                      {abLoading === draft.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Shuffle className="h-3 w-3" />
                      )}
                      A/B Test
                    </button>
                  )}
                </div>

                {/* A/B variant selector */}
                {abVariants[draft.id] && (
                  <div className="mt-2 space-y-2">
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-500">Choose a subject line:</p>
                    {(["a", "b"] as const).map((variant) => (
                      <button
                        key={variant}
                        onClick={() =>
                          setAbVariants((prev) => ({
                            ...prev,
                            [draft.id]: { ...prev[draft.id], selected: variant },
                          }))
                        }
                        className={cn(
                          "flex w-full items-center gap-2 rounded-lg border p-2.5 text-left text-sm transition-colors",
                          abVariants[draft.id].selected === variant
                            ? "border-gray-900 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                            : "border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
                        )}
                      >
                        <span
                          className={cn(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                            abVariants[draft.id].selected === variant
                              ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                              : "bg-gray-200 text-gray-500 dark:text-gray-500"
                          )}
                        >
                          {variant.toUpperCase()}
                        </span>
                        <span className="flex-1">{abVariants[draft.id][variant]}</span>
                        {variant === "a" && (
                          <span className="text-xs text-gray-400 dark:text-gray-500">Original</span>
                        )}
                        {variant === "b" && (
                          <span className="text-xs text-gray-400 dark:text-gray-500">Variant</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}

                {editingId === draft.id ? (
                  <textarea
                    value={editBody}
                    onChange={(e) => {
                      setEditBody(e.target.value);
                      e.target.style.height = "auto";
                      e.target.style.height = `${e.target.scrollHeight}px`;
                    }}
                    ref={(el) => {
                      if (el) {
                        el.style.height = "auto";
                        el.style.height = `${el.scrollHeight}px`;
                      }
                    }}
                    rows={20}
                    className="mt-2 w-full resize-none overflow-hidden rounded-md border border-gray-200 dark:border-gray-700 p-3 text-sm text-gray-700 dark:text-gray-300 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
                  />
                ) : (
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-700 dark:text-gray-300">
                    {draft.edited_body || draft.body}
                  </p>
                )}
              </div>

              {/* Personalization Notes */}
              {draft.personalization_notes && (
                <p className="text-xs italic text-gray-500 dark:text-gray-500">
                  {draft.personalization_notes}
                </p>
              )}

              {/* Prior Emails + Research Notes expandable toggles */}
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() => toggleThread(draft.id)}
                  className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  {threadLoading.has(draft.id) ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : expandedThread.has(draft.id) ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                  <History className="h-3.5 w-3.5" />
                  Prior emails
                  {threadData[draft.id] !== undefined && !threadLoading.has(draft.id) && (
                    <span className="rounded bg-gray-100 dark:bg-gray-800 px-1 py-px text-[10px] font-medium text-gray-500 dark:text-gray-400">
                      {threadData[draft.id]?.length ?? 0}
                    </span>
                  )}
                </button>
                <button
                  onClick={() => toggleResearch(draft.id)}
                  className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  {researchLoading.has(draft.id) ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : expandedResearch.has(draft.id) ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                  <FileSearch className="h-3.5 w-3.5" />
                  Research notes
                </button>
              </div>

              {/* Prior emails panel */}
              {expandedThread.has(draft.id) && (
                <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 p-4 space-y-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                    Prior emails sent to {draft.contacts?.full_name ?? "this contact"}
                  </p>
                  {threadLoading.has(draft.id) ? (
                    <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                  ) : !threadData[draft.id] || threadData[draft.id].length === 0 ? (
                    <p className="text-xs text-gray-400 dark:text-gray-500">No prior emails found.</p>
                  ) : (
                    <div className="space-y-3">
                      {threadData[draft.id].map((email, i) => (
                        <div key={email.id} className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3">
                          <div className="flex items-center justify-between mb-1.5">
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                                #{i + 1}
                              </span>
                              {email.sequence_step && (
                                <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-px text-[10px] font-medium text-gray-500 dark:text-gray-400">
                                  Step {email.sequence_step}
                                </span>
                              )}
                              <span className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate max-w-[300px]">
                                {email.subject}
                              </span>
                            </div>
                            <span className="text-[10px] text-gray-400 dark:text-gray-500 shrink-0 ml-2">
                              {new Date(email.sent_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                            </span>
                          </div>
                          <p className="whitespace-pre-wrap text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                            {email.edited_body || email.body}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Research notes panel */}
              {expandedResearch.has(draft.id) && (
                <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 p-4 space-y-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                    Research — {draft.companies?.name ?? "Company"}
                  </p>
                  {researchLoading.has(draft.id) ? (
                    <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                  ) : !researchData[draft.id] ? (
                    <p className="text-xs text-gray-400 dark:text-gray-500">No research data available.</p>
                  ) : (
                    <div className="grid grid-cols-1 gap-3 text-xs">
                      {researchData[draft.id]?.company_description && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Overview</p>
                          <p className="text-gray-700 dark:text-gray-300 leading-relaxed">{researchData[draft.id]!.company_description}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.pain_points && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Pain Points</p>
                          <p className="text-gray-700 dark:text-gray-300 leading-relaxed">{researchData[draft.id]!.pain_points}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.opportunities && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Opportunities</p>
                          <p className="text-gray-700 dark:text-gray-300 leading-relaxed">{researchData[draft.id]!.opportunities}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.equipment_types && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Equipment</p>
                          <p className="text-gray-700 dark:text-gray-300">{researchData[draft.id]!.equipment_types}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.known_systems && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Known Systems</p>
                          <p className="text-gray-700 dark:text-gray-300">{researchData[draft.id]!.known_systems}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.maintenance_approach && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Maintenance Approach</p>
                          <p className="text-gray-700 dark:text-gray-300">{researchData[draft.id]!.maintenance_approach}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.existing_solutions && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">Existing Solutions</p>
                          <p className="text-gray-700 dark:text-gray-300">{researchData[draft.id]!.existing_solutions}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.iot_maturity && (
                        <div>
                          <p className="font-medium text-gray-500 dark:text-gray-400 mb-0.5">IoT Maturity</p>
                          <p className="text-gray-700 dark:text-gray-300">{researchData[draft.id]!.iot_maturity}</p>
                        </div>
                      )}
                      {researchData[draft.id]?.researched_at && (
                        <p className="text-[10px] text-gray-400 dark:text-gray-500 pt-1">
                          Researched {new Date(researchData[draft.id]!.researched_at!).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                          {researchData[draft.id]?.confidence_level && ` · Confidence: ${researchData[draft.id]!.confidence_level}`}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Reject Reason Input */}
              {rejectingId === draft.id && (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    placeholder="Rejection reason..."
                    className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleReject(draft.id);
                    }}
                  />
                  <button
                    onClick={() => handleReject(draft.id)}
                    disabled={
                      !rejectReason.trim() || actionLoading === draft.id
                    }
                    className="rounded-md bg-gray-900 px-4 py-2 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                  >
                    {actionLoading === draft.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      "Confirm Reject"
                    )}
                  </button>
                  <button
                    onClick={() => setRejectingId(null)}
                    className="rounded-md px-3 py-2 text-sm text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:text-gray-300"
                  >
                    Cancel
                  </button>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pt-2">
                {editingId === draft.id ? (
                  <>
                    <button
                      onClick={() => handleSaveEdit(draft.id)}
                      disabled={actionLoading === draft.id}
                      className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                    >
                      {actionLoading === draft.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4" />
                      )}
                      Save
                    </button>
                    <button
                      onClick={() => {
                        setEditingId(null);
                        setEditBody("");
                      }}
                      className="rounded-md px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => handleApprove(draft.id)}
                      disabled={actionLoading === draft.id}
                      className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                    >
                      {actionLoading === draft.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4" />
                      )}
                      Approve
                    </button>
                    <button
                      onClick={() => startEditing(draft)}
                      className="inline-flex items-center gap-1.5 rounded-md bg-gray-100 dark:bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                    >
                      <Pencil className="h-4 w-4" />
                      Edit
                    </button>
                    <button
                      onClick={() => startRejecting(draft.id)}
                      className="inline-flex items-center gap-1.5 rounded-md bg-gray-100 dark:bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                    >
                      <XCircle className="h-4 w-4" />
                      Reject
                    </button>
                    <button
                      onClick={() => handleTestSend(draft.id)}
                      disabled={testSendingId === draft.id}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                    >
                      {testSendingId === draft.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Mail className="h-4 w-4" />
                      )}
                      Send Test to Me
                    </button>
                    {draft.sent_at && !replySuccess[draft.id] && (
                      <button
                        onClick={() => {
                          setReplyFormId(replyFormId === draft.id ? null : draft.id);
                          setReplyBody("");
                          setReplyNotes("");
                          setReplyIntent("interested");
                        }}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
                      >
                        <MessageSquareReply className="h-4 w-4" />
                        Log Reply
                      </button>
                    )}
                    {replySuccess[draft.id] && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
                        ↩ Replied · {replySuccess[draft.id]}
                      </span>
                    )}
                  </>
                )}
                {testSendResult?.id === draft.id && (
                  <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                    {testSendResult.message}
                  </span>
                )}
              </div>
              {/* Log Reply inline form */}
              {replyFormId === draft.id && (
                <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-4 space-y-3">
                  <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">Log Reply from Prospect</p>
                  <textarea
                    value={replyBody}
                    onChange={(e) => setReplyBody(e.target.value)}
                    rows={3}
                    placeholder="Paste the reply text here..."
                    className="w-full rounded-md border border-amber-200 bg-white p-2.5 text-sm text-gray-700 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-300"
                  />
                  <div className="flex items-center gap-3">
                    <select
                      value={replyIntent}
                      onChange={(e) => setReplyIntent(e.target.value as LogReplyPayload["intent"])}
                      className="rounded-md border border-amber-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 focus:outline-none"
                    >
                      <option value="interested">Interested</option>
                      <option value="not_interested">Not Interested</option>
                      <option value="question">Question</option>
                      <option value="referral">Referral</option>
                      <option value="objection">Objection</option>
                    </select>
                    <input
                      type="text"
                      value={replyNotes}
                      onChange={(e) => setReplyNotes(e.target.value)}
                      placeholder="Notes (optional)"
                      className="flex-1 rounded-md border border-amber-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 focus:outline-none"
                    />
                    <button
                      onClick={() => handleLogReply(draft)}
                      disabled={!replyBody.trim() || replyLoading === draft.id}
                      className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                    >
                      {replyLoading === draft.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                      Save Reply
                    </button>
                    <button
                      onClick={() => setReplyFormId(null)}
                      className="text-xs text-gray-500 hover:text-gray-700"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Keyboard Shortcut Legend */}
      {drafts.length > 0 && (
        <div className="flex items-center justify-center gap-4 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 px-4 py-2 text-xs text-gray-400 dark:text-gray-500">
          <span>
            <kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono">j</kbd>
            {" / "}
            <kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono">k</kbd>
            {" Navigate"}
          </span>
          <span>
            <kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono">a</kbd>
            {" Approve"}
          </span>
          <span>
            <kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono">e</kbd>
            {" Edit"}
          </span>
          <span>
            <kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono">r</kbd>
            {" Reject"}
          </span>
          <span>
            <kbd className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-1.5 py-0.5 font-mono">esc</kbd>
            {" Cancel"}
          </span>
        </div>
      )}
    </div>
  );
}
