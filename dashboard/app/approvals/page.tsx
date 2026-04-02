"use client";

/**
 * Outreach Approval Queue — Review AI-generated drafts before sending
 *
 * Expected actions:
 * Read each draft, approve/edit/reject, check quality score, ensure personalization is genuine
 */


import { useEffect, useState, useCallback } from "react";
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
} from "lucide-react";
import { getPendingDrafts, approveDraft, saveDraftEdit, rejectDraft, testSendDraft, scoreDraft, OutreachDraft, type DraftQualityScore } from "@/lib/api";
import { cn, TIER_LABELS, getPQSColor } from "@/lib/utils";
import DraftQualityBadge from "@/components/outreach/DraftQualityBadge";

export default function ApprovalsPage() {
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
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
  const TEST_EMAIL = "avi@digitillis.com";

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

  const handleApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await approveDraft(id);
      setDrafts((prev) => {
        const next = prev.filter((d) => d.id !== id);
        return next;
      });
      setFocusedIndex((i) => Math.min(i, drafts.length - 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setActionLoading(null);
    }
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
    setEditBody(draft.body);
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
            {drafts.length} pending
          </span>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4 text-sm text-gray-700 dark:text-gray-300">
          {error}
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
                </div>
                {draft.contacts?.email && (
                  <div className="flex items-center gap-1.5">
                    <Mail className="h-4 w-4 text-gray-400 dark:text-gray-500" />
                    <span>{draft.contacts.email}</span>
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
                    onChange={(e) => setEditBody(e.target.value)}
                    rows={6}
                    className="mt-2 w-full rounded-md border border-gray-200 dark:border-gray-700 p-3 text-sm text-gray-700 dark:text-gray-300 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
                  />
                ) : (
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-700 dark:text-gray-300">
                    {draft.body}
                  </p>
                )}
              </div>

              {/* Personalization Notes */}
              {draft.personalization_notes && (
                <p className="text-xs italic text-gray-500 dark:text-gray-500">
                  {draft.personalization_notes}
                </p>
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
                  </>
                )}
                {testSendResult?.id === draft.id && (
                  <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                    {testSendResult.message}
                  </span>
                )}
              </div>
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
