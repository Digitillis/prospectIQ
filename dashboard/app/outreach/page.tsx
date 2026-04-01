"use client";

/**
 * Outreach Hub — Draft Queue, Send Queue, In-Flight, Sent History
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Send, CheckCircle2, XCircle, Pencil, Loader2, Inbox,
  RefreshCw, ChevronDown, ChevronUp, Mail, Shuffle,
} from "lucide-react";
import {
  getPendingDrafts, approveDraft, rejectDraft, saveDraftEdit, testSendDraft,
  getCompanies, listActiveEnrollments,
  type OutreachDraft,
} from "@/lib/api";
import { cn, getPQSColor, TIER_LABELS } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-gray-100 dark:bg-gray-800", className)} />;
}

function qualityBadgeClass(score?: number): string {
  if (!score) return "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400";
  if (score >= 80) return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300";
  if (score >= 60) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
}

// ---------------------------------------------------------------------------
// Draft Queue Tab
// ---------------------------------------------------------------------------
function DraftQueueTab() {
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filterQuality, setFilterQuality] = useState<"all" | "high" | "low">("all");
  const [filterSequence, setFilterSequence] = useState("");
  const [testSendingId, setTestSendingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; message: string } | null>(null);

  const loadDrafts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getPendingDrafts();
      const sorted = [...res.data].sort((a, b) => (b.companies?.pqs_total ?? 0) - (a.companies?.pqs_total ?? 0));
      setDrafts(sorted);
    } catch {
      setDrafts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDrafts(); }, [loadDrafts]);

  const filteredDrafts = drafts.filter((d) => {
    const qs = (d as Record<string, unknown>).quality_score as number | undefined;
    if (filterQuality === "high" && (qs === undefined || qs < 80)) return false;
    if (filterQuality === "low" && (qs === undefined || qs >= 80)) return false;
    if (filterSequence && !d.sequence_name?.toLowerCase().includes(filterSequence.toLowerCase())) return false;
    return true;
  });

  const handleApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await approveDraft(id);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
    } catch { /* noop */ }
    finally { setActionLoading(null); }
  };

  const handleApproveSelected = async () => {
    const ids = Array.from(selected);
    for (const id of ids) {
      await handleApprove(id);
    }
  };

  const handleApproveHighQuality = async () => {
    const highQ = drafts.filter((d) => {
      const qs = (d as Record<string, unknown>).quality_score as number | undefined;
      return qs !== undefined && qs >= 80;
    });
    for (const d of highQ) { await handleApprove(d.id); }
  };

  const handleReject = async (id: string) => {
    if (!rejectReason.trim()) return;
    setActionLoading(id);
    try {
      await rejectDraft(id, rejectReason);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setRejectingId(null);
      setRejectReason("");
    } catch { /* noop */ }
    finally { setActionLoading(null); }
  };

  const handleSaveEdit = async (id: string) => {
    setActionLoading(id);
    try {
      await saveDraftEdit(id, editBody);
      setDrafts((prev) => prev.map((d) => d.id === id ? { ...d, body: editBody } : d));
      setEditingId(null);
    } catch { /* noop */ }
    finally { setActionLoading(null); }
  };

  const handleTestSend = async (id: string) => {
    setTestSendingId(id);
    try {
      const res = await testSendDraft(id, "avi@digitillis.com");
      setTestResult({ id, message: res.message });
      setTimeout(() => setTestResult(null), 5000);
    } catch (e) {
      setTestResult({ id, message: e instanceof Error ? e.message : "Failed" });
    } finally { setTestSendingId(null); }
  };

  const highQCount = drafts.filter((d) => {
    const qs = (d as Record<string, unknown>).quality_score as number | undefined;
    return qs !== undefined && qs >= 80;
  }).length;

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Filter by sequence..."
          value={filterSequence}
          onChange={(e) => setFilterSequence(e.target.value)}
          className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-400"
        />
        <div className="flex items-center gap-1">
          {(["all", "high", "low"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilterQuality(f)}
              className={cn("rounded-md px-3 py-1.5 text-xs font-medium transition-colors", filterQuality === f ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900" : "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700")}
            >
              {f === "all" ? "All Quality" : f === "high" ? "≥80" : "<80"}
            </button>
          ))}
        </div>
        <button onClick={loadDrafts} className="ml-auto rounded-md border border-gray-200 dark:border-gray-700 p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
      </div>

      {/* Bulk actions */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-2">
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{selected.size} selected</span>
          <button onClick={handleApproveSelected} className="rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100">
            Approve {selected.size} selected
          </button>
          {highQCount > 0 && (
            <button onClick={handleApproveHighQuality} className="rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-900">
              Approve all quality ≥80 ({highQCount})
            </button>
          )}
          <button onClick={() => setSelected(new Set())} className="ml-auto text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">Clear</button>
        </div>
      )}

      {loading ? (
        Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-32 w-full" />)
      ) : filteredDrafts.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 py-16">
          <Inbox className="h-12 w-12 text-gray-300" />
          <p className="mt-4 text-sm font-medium text-gray-900 dark:text-gray-100">No drafts pending</p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">All outreach drafts have been reviewed.</p>
        </div>
      ) : (
        filteredDrafts.map((draft) => {
          const qs = (draft as Record<string, unknown>).quality_score as number | undefined;
          const pqs = draft.companies?.pqs_total ?? 0;
          const isExpanded = expandedId === draft.id;
          return (
            <div key={draft.id} className={cn("rounded-lg border bg-white dark:bg-gray-900", selected.has(draft.id) ? "border-gray-900 dark:border-gray-100" : "border-gray-200 dark:border-gray-700")}>
              <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                <input
                  type="checkbox"
                  checked={selected.has(draft.id)}
                  onChange={(e) => setSelected((prev) => { const n = new Set(prev); e.target.checked ? n.add(draft.id) : n.delete(draft.id); return n; })}
                  className="h-4 w-4 rounded"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm text-gray-900 dark:text-gray-100 truncate">{draft.companies?.name ?? "Unknown"}</span>
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold", getPQSColor(pqs))}>PQS {pqs}</span>
                    {qs !== undefined && <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", qualityBadgeClass(qs))}>Q:{qs}</span>}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-500 truncate">
                    {draft.contacts?.full_name} · {draft.sequence_name} · Step {draft.sequence_step}
                  </p>
                </div>
                <button onClick={() => setExpandedId(isExpanded ? null : draft.id)} className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                  {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </button>
              </div>

              {isExpanded && (
                <div className="px-4 py-3 space-y-3">
                  <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                    <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">{draft.subject}</p>
                    {editingId === draft.id ? (
                      <textarea
                        value={editBody}
                        onChange={(e) => setEditBody(e.target.value)}
                        rows={5}
                        className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2 text-xs text-gray-700 dark:text-gray-300 focus:outline-none"
                      />
                    ) : (
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-gray-700 dark:text-gray-300">{draft.body}</p>
                    )}
                  </div>

                  {/* Reject input */}
                  {rejectingId === draft.id && (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        placeholder="Rejection reason..."
                        onKeyDown={(e) => { if (e.key === "Enter") handleReject(draft.id); }}
                        className="flex-1 rounded border border-gray-200 dark:border-gray-700 px-2 py-1.5 text-xs focus:outline-none"
                        autoFocus
                      />
                      <button onClick={() => handleReject(draft.id)} disabled={!rejectReason.trim()} className="rounded bg-gray-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">Reject</button>
                      <button onClick={() => setRejectingId(null)} className="text-xs text-gray-400">Cancel</button>
                    </div>
                  )}

                  <div className="flex items-center gap-2 flex-wrap">
                    {editingId === draft.id ? (
                      <>
                        <button onClick={() => handleSaveEdit(draft.id)} disabled={actionLoading === draft.id} className="inline-flex items-center gap-1 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
                          {actionLoading === draft.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />} Save
                        </button>
                        <button onClick={() => setEditingId(null)} className="rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400">Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => handleApprove(draft.id)} disabled={actionLoading === draft.id} className="inline-flex items-center gap-1 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-50">
                          {actionLoading === draft.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />} Approve
                        </button>
                        <button onClick={() => { setEditingId(draft.id); setEditBody(draft.body); }} className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                          <Pencil className="h-3 w-3" /> Edit
                        </button>
                        <button onClick={() => { setRejectingId(draft.id); setRejectReason(""); }} className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                          <XCircle className="h-3 w-3" /> Reject
                        </button>
                        <button onClick={() => handleTestSend(draft.id)} disabled={testSendingId === draft.id} className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 disabled:opacity-50">
                          {testSendingId === draft.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Mail className="h-3 w-3" />} Test Send
                        </button>
                        {testResult?.id === draft.id && (
                          <span className="text-xs text-gray-600 dark:text-gray-400">{testResult.message}</span>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Send Queue Tab
// ---------------------------------------------------------------------------
function SendQueueTab() {
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [pushing, setPushing] = useState(false);
  const [pushResult, setPushResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/approvals?status=approved`);
      if (res.ok) {
        const json = await res.json();
        setDrafts(json.data || []);
      }
    } catch { setDrafts([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const pushAll = async () => {
    setPushing(true);
    try {
      const res = await fetch(`${API_BASE}/api/sequences/send-approved`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const json = await res.json();
      if (res.ok) {
        setPushResult(`${json.processed ?? 0} sent, ${json.skipped ?? 0} skipped`);
        load();
      } else {
        setPushResult(json.detail || "Failed");
      }
    } catch (e) {
      setPushResult(e instanceof Error ? e.message : "Failed");
    } finally { setPushing(false); setTimeout(() => setPushResult(null), 5000); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500 dark:text-gray-500">{drafts.length} approved draft{drafts.length !== 1 ? "s" : ""} ready to send</p>
        <div className="flex items-center gap-3">
          {pushResult && <span className="text-xs text-gray-600 dark:text-gray-400">{pushResult}</span>}
          <button onClick={pushAll} disabled={pushing || drafts.length === 0} className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-50">
            {pushing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
            Push All to Instantly
          </button>
        </div>
      </div>
      {loading ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />) :
        drafts.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-16 text-gray-400">
            <CheckCircle2 className="h-10 w-10 mb-2" />
            <p className="text-sm">No approved drafts in queue</p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                  {["Company", "Contact", "Sequence", "Step", "Scheduled", ""].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {drafts.map((d) => (
                  <tr key={d.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-4 py-2 font-medium text-gray-900 dark:text-gray-100">{d.companies?.name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{d.contacts?.full_name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{d.sequence_name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{d.sequence_step ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">Scheduled</td>
                    <td className="px-4 py-2">
                      <button className="text-xs font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100">Send Now</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  );
}

// ---------------------------------------------------------------------------
// In-Flight Tab
// ---------------------------------------------------------------------------
function InFlightTab() {
  const [enrollments, setEnrollments] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listActiveEnrollments(100).then((res) => setEnrollments(res.data)).catch(() => setEnrollments([])).finally(() => setLoading(false));
  }, []);

  type Enrollment = {
    id: string;
    sequence_name?: string;
    current_step?: number;
    total_steps?: number;
    last_action_at?: string;
    next_action_at?: string;
    companies?: { name?: string };
    contacts?: { full_name?: string; email?: string };
  };

  return (
    <div>
      {loading ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12 w-full mb-2" />) :
        (enrollments as Enrollment[]).length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-16 text-gray-400">
            <Send className="h-10 w-10 mb-2" />
            <p className="text-sm">No active sequences in flight</p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                  {["Company", "Contact", "Sequence", "Step", "Last Touch", "Next Touch"].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {(enrollments as Enrollment[]).map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-4 py-2 font-medium text-gray-900 dark:text-gray-100">{e.companies?.name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{e.contacts?.full_name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{e.sequence_name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{e.current_step ?? "—"} of {e.total_steps ?? 6}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{e.last_action_at ? new Date(e.last_action_at).toLocaleDateString() : "—"}</td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{e.next_action_at ? new Date(e.next_action_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sent History Tab
// ---------------------------------------------------------------------------
function SentHistoryTab() {
  const [sent, setSent] = useState<OutreachDraft[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/approvals?status=sent&limit=100`)
      .then((r) => r.ok ? r.json() : { data: [] })
      .then((json) => setSent(json.data || []))
      .catch(() => setSent([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      {loading ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12 w-full mb-2" />) :
        sent.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-16 text-gray-400">
            <Mail className="h-10 w-10 mb-2" />
            <p className="text-sm">No sent emails yet</p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                  {["Company", "Subject", "Sent", "Opened", "Clicked", "Replied"].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {sent.map((d) => {
                  const meta = d as Record<string, unknown>;
                  return (
                    <tr key={d.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                      <td className="px-4 py-2 font-medium text-gray-900 dark:text-gray-100">{d.companies?.name ?? "—"}</td>
                      <td className="px-4 py-2 text-gray-600 dark:text-gray-400 max-w-xs truncate">{d.subject}</td>
                      <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{d.created_at ? new Date(d.created_at).toLocaleDateString() : "—"}</td>
                      <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{(meta.open_count as number | undefined) ?? "—"}</td>
                      <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{(meta.click_count as number | undefined) ?? "—"}</td>
                      <td className="px-4 py-2">{(meta.replied as boolean | undefined) ? <span className="text-green-600 font-medium">Yes</span> : <span className="text-gray-400">No</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
type TabKey = "drafts" | "queue" | "inflight" | "history";

const TABS: { key: TabKey; label: string }[] = [
  { key: "drafts", label: "Draft Queue" },
  { key: "queue", label: "Send Queue" },
  { key: "inflight", label: "In-Flight" },
  { key: "history", label: "Sent History" },
];

export default function OutreachHubPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("drafts");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Outreach Hub</h1>
        <Link href="/approvals" className="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">Classic view →</Link>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 dark:border-gray-700">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors",
              activeTab === tab.key
                ? "border-b-2 border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100"
                : "text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "drafts" && <DraftQueueTab />}
      {activeTab === "queue" && <SendQueueTab />}
      {activeTab === "inflight" && <InFlightTab />}
      {activeTab === "history" && <SentHistoryTab />}
    </div>
  );
}
