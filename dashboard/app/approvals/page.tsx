"use client";

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
} from "lucide-react";
import { getPendingDrafts, approveDraft, rejectDraft, OutreachDraft } from "@/lib/api";
import { cn, TIER_LABELS, getPQSColor } from "@/lib/utils";

export default function ApprovalsPage() {
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);

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
      setDrafts((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setActionLoading(null);
    }
  };

  const handleEditApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await approveDraft(id, editBody);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setEditingId(null);
      setEditBody("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve");
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

  const startRejecting = (id: string) => {
    setRejectingId(id);
    setRejectReason("");
    setEditingId(null);
    setEditBody("");
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold text-gray-900">Approval Queue</h2>
          <span className="inline-flex items-center rounded-full bg-indigo-100 px-3 py-1 text-sm font-medium text-indigo-700">
            {drafts.length} pending
          </span>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Empty State */}
      {drafts.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 bg-white py-16">
          <Inbox className="h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">
            No pending approvals
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            All outreach drafts have been reviewed. Check back later.
          </p>
        </div>
      )}

      {/* Draft Cards */}
      <div className="space-y-4">
        {drafts.map((draft) => (
          <div
            key={draft.id}
            className="rounded-xl border border-gray-200 bg-white shadow-sm transition-shadow hover:shadow-md"
          >
            {/* Company Header */}
            <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
              <div className="flex items-center gap-3">
                <Building2 className="h-5 w-5 text-gray-400" />
                <span className="text-lg font-semibold text-gray-900">
                  {draft.companies?.name ?? "Unknown Company"}
                </span>
                {draft.companies?.tier && (
                  <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                    {TIER_LABELS[draft.companies.tier] ?? draft.companies.tier}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-gray-400">
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

            <div className="px-6 py-4 space-y-4">
              {/* Contact Info */}
              <div className="flex items-center gap-4 text-sm text-gray-600">
                <div className="flex items-center gap-1.5">
                  <User className="h-4 w-4 text-gray-400" />
                  <span className="font-medium">
                    {draft.contacts?.full_name ?? "Unknown Contact"}
                  </span>
                  {draft.contacts?.title && (
                    <span className="text-gray-400">
                      &middot; {draft.contacts.title}
                    </span>
                  )}
                </div>
                {draft.contacts?.email && (
                  <div className="flex items-center gap-1.5">
                    <Mail className="h-4 w-4 text-gray-400" />
                    <span>{draft.contacts.email}</span>
                  </div>
                )}
              </div>

              {/* Message Preview */}
              <div className="rounded-lg bg-gray-50 p-4">
                <p className="text-sm font-semibold text-gray-900">
                  {draft.subject}
                </p>
                {editingId === draft.id ? (
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    rows={6}
                    className="mt-2 w-full rounded-md border border-gray-300 p-3 text-sm text-gray-700 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                ) : (
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                    {draft.body}
                  </p>
                )}
              </div>

              {/* Personalization Notes */}
              {draft.personalization_notes && (
                <p className="text-xs italic text-gray-500">
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
                    className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleReject(draft.id);
                    }}
                  />
                  <button
                    onClick={() => handleReject(draft.id)}
                    disabled={
                      !rejectReason.trim() || actionLoading === draft.id
                    }
                    className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                  >
                    {actionLoading === draft.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      "Confirm Reject"
                    )}
                  </button>
                  <button
                    onClick={() => setRejectingId(null)}
                    className="rounded-md px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
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
                      onClick={() => handleEditApprove(draft.id)}
                      disabled={actionLoading === draft.id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {actionLoading === draft.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4" />
                      )}
                      Save & Approve
                    </button>
                    <button
                      onClick={() => {
                        setEditingId(null);
                        setEditBody("");
                      }}
                      className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => handleApprove(draft.id)}
                      disabled={actionLoading === draft.id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
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
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                    >
                      <Pencil className="h-4 w-4" />
                      Edit & Approve
                    </button>
                    <button
                      onClick={() => startRejecting(draft.id)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
                    >
                      <XCircle className="h-4 w-4" />
                      Reject
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
