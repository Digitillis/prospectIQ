"use client";

/**
 * Outreach Hub — Draft Queue, Send Queue, In-Flight, Sent History, Generator
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Send, CheckCircle2, XCircle, Pencil, Loader2, Inbox,
  RefreshCw, ChevronDown, ChevronUp, Mail, Shuffle, Sparkles,
} from "lucide-react";
import {
  getPendingDrafts, approveDraft, rejectDraft, saveDraftEdit, testSendDraft,
  getCompanies, listActiveEnrollments, getOutreachIntelligence, generateOutreachDraft,
  generateOutreachBatch,
  type OutreachDraft, type IntelligenceData,
} from "@/lib/api";
import { cn, getPQSColor, TIER_LABELS } from "@/lib/utils";
import IntelligenceCard from "@/components/outreach/IntelligenceCard";
import DraftQualityBadge from "@/components/outreach/DraftQualityBadge";

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
    const qs = d.quality_score;
    if (filterQuality === "high" && (qs === undefined || qs < 80)) return false;
    if (filterQuality === "low" && (qs === undefined || qs >= 80)) return false;
    if (filterSequence && !d.sequence_name?.toLowerCase().includes(filterSequence.toLowerCase())) return false;
    return true;
  });

  const handleApprove = async (id: string) => {
    // Capture next draft synchronously before the await — avoids stale closure
    const currentIndex = filteredDrafts.findIndex((d) => d.id === id);
    const nextId = filteredDrafts[currentIndex + 1]?.id ?? null;
    setActionLoading(id);
    try {
      await approveDraft(id);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
      setExpandedId(nextId);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("422")) {
        alert("This draft has quality errors and cannot be approved as-is.\nFix the body or use the edit button first.");
      } else {
        alert(`Approval failed: ${msg}`);
      }
    } finally { setActionLoading(null); }
  };

  const handleApproveSelected = async () => {
    const ids = Array.from(selected);
    for (const id of ids) {
      await handleApprove(id);
    }
  };

  const handleApproveHighQuality = async () => {
    const highQ = drafts.filter((d) => {
      const qs = d.quality_score;
      return qs !== undefined && qs >= 80;
    });
    for (const d of highQ) { await handleApprove(d.id); }
  };

  const handleReject = async (id: string) => {
    if (!rejectReason.trim()) return;
    const currentIndex = filteredDrafts.findIndex((d) => d.id === id);
    const nextId = filteredDrafts[currentIndex + 1]?.id ?? null;
    setActionLoading(id);
    try {
      await rejectDraft(id, rejectReason);
      setDrafts((prev) => prev.filter((d) => d.id !== id));
      setRejectingId(null);
      setRejectReason("");
      setExpandedId(nextId);
    } catch (err: unknown) {
      alert(`Reject failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally { setActionLoading(null); }
  };

  const handleSaveEdit = async (id: string) => {
    setActionLoading(id);
    try {
      await saveDraftEdit(id, editBody);
      setDrafts((prev) => prev.map((d) => d.id === id ? { ...d, body: editBody } : d));
      setEditingId(null);
    } catch (err: unknown) {
      alert(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally { setActionLoading(null); }
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
    const qs = d.quality_score;
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
        <div className="ml-auto flex items-center gap-2">
          {filteredDrafts.length > 0 && (
            <span className="text-[11px] tabular-nums text-gray-400 dark:text-gray-500 select-none">
              {expandedId
                ? `${filteredDrafts.findIndex((d) => d.id === expandedId) + 1} / ${filteredDrafts.length}`
                : `${filteredDrafts.length} drafts`}
            </span>
          )}
          <button onClick={loadDrafts} className="rounded-md border border-gray-200 dark:border-gray-700 p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </button>
        </div>
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
          const qs = draft.quality_score;
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
                        rows={18}
                        className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2 text-xs text-gray-700 dark:text-gray-300 focus:outline-none resize-y"
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
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/approvals/sent?limit=200`)
      .then((r) => r.ok ? r.json() : { data: [] })
      .then((json) => setSent(json.data || []))
      .catch(() => setSent([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = search.trim()
    ? sent.filter((d) => {
        const q = search.toLowerCase();
        return (
          d.companies?.name?.toLowerCase().includes(q) ||
          d.subject?.toLowerCase().includes(q) ||
          (d.contacts as Record<string, string> | undefined)?.full_name?.toLowerCase().includes(q)
        );
      })
    : sent;

  return (
    <div className="space-y-3">
      {/* Search bar */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Search by company, contact, or subject…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <span className="text-xs text-gray-400 whitespace-nowrap">
          {filtered.length} of {sent.length} sent
        </span>
      </div>

      {loading ? (
        Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-16 text-gray-400">
          <Mail className="h-10 w-10 mb-2" />
          <p className="text-sm">{sent.length === 0 ? "No sent emails yet" : "No results for your search"}</p>
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                {["Company", "Contact", "Subject", "Sent At", "Step", ""].map((h) => (
                  <th key={h} className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {filtered.map((d) => {
                const contact = d.contacts;
                const sentAt = d.sent_at;
                const isExpanded = expandedId === d.id;
                const bodyText = d.edited_body || d.body || "";
                return (
                  <>
                    <tr
                      key={d.id}
                      className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer"
                      onClick={() => setExpandedId(isExpanded ? null : d.id)}
                    >
                      <td className="px-4 py-2.5 font-medium text-gray-900 dark:text-gray-100 whitespace-nowrap">
                        {d.companies?.name ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400 whitespace-nowrap">
                        {contact?.full_name ?? "—"}
                        {contact?.title && (
                          <span className="ml-1 text-gray-400 dark:text-gray-500">· {contact.title}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-xs truncate">
                        {d.subject}
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                        {sentAt
                          ? new Date(sentAt).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                          + " " + new Date(sentAt).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-gray-400 whitespace-nowrap">
                        {d.sequence_name
                          ? `${d.sequence_name} · step ${d.sequence_step ?? 1}`
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-blue-500">
                        {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${d.id}-body`} className="bg-gray-50 dark:bg-gray-800/40">
                        <td colSpan={6} className="px-6 py-4">
                          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide">
                            Email Body
                          </div>
                          <pre className="whitespace-pre-wrap font-sans text-sm text-gray-800 dark:text-gray-200 leading-relaxed bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
                            {bodyText}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Generator Tab — Outreach Generator with IntelligenceCard per company-contact
// ---------------------------------------------------------------------------

interface CompanyContactRow {
  companyId: string;
  companyName: string;
  tier?: string;
  pqsTotal: number;
  campaignCluster?: string;
  tranche?: string;
  contactId: string;
  contactName?: string;
  contactTitle?: string;
  personaType?: string;
  intelligence: IntelligenceData | null;
  intelligenceLoading: boolean;
  draftsCount: number;
}

function GeneratorTab() {
  const [rows, setRows] = useState<CompanyContactRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterCluster, setFilterCluster] = useState("");
  const [filterPersona, setFilterPersona] = useState("");
  const [filterTranche, setFilterTranche] = useState("");
  const [batchGenerating, setBatchGenerating] = useState(false);
  const [batchResult, setBatchResult] = useState<string | null>(null);
  const [expandedContactId, setExpandedContactId] = useState<string | null>(null);
  const [generatedDraftIds, setGeneratedDraftIds] = useState<Set<string>>(new Set());

  const loadRows = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch companies that have research (pqs_total > 0 as a proxy)
      const res = await getCompanies({ limit: "100", min_pqs: "30" });
      const companies = res.data || [];

      const initialRows: CompanyContactRow[] = [];
      for (const co of companies) {
        const contacts = co.contacts;
        const primaryContact = contacts?.[0];
        if (!primaryContact) continue;

        initialRows.push({
          companyId: String(co.id),
          companyName: co.name,
          tier: co.tier,
          pqsTotal: co.pqs_total ?? 0,
          campaignCluster: co.campaign_cluster,
          tranche: co.tranche,
          contactId: String(primaryContact.id),
          contactName: primaryContact.full_name,
          contactTitle: primaryContact.title,
          personaType: primaryContact.persona_type,
          intelligence: null,
          intelligenceLoading: false,
          draftsCount: 0,
        });
      }
      setRows(initialRows);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRows(); }, [loadRows]);

  const loadIntelligence = async (contactId: string) => {
    setRows((prev) => prev.map((r) =>
      r.contactId === contactId ? { ...r, intelligenceLoading: true } : r
    ));
    try {
      const intel = await getOutreachIntelligence(contactId);
      setRows((prev) => prev.map((r) =>
        r.contactId === contactId
          ? { ...r, intelligence: intel, intelligenceLoading: false, personaType: intel.persona_type }
          : r
      ));
    } catch {
      setRows((prev) => prev.map((r) =>
        r.contactId === contactId ? { ...r, intelligenceLoading: false } : r
      ));
    }
  };

  const handleExpand = (contactId: string, row: CompanyContactRow) => {
    if (expandedContactId === contactId) {
      setExpandedContactId(null);
      return;
    }
    setExpandedContactId(contactId);
    if (!row.intelligence && !row.intelligenceLoading) {
      loadIntelligence(contactId);
    }
  };

  const handleGenerate = async (row: CompanyContactRow) => {
    try {
      const res = await generateOutreachDraft(row.companyId, row.contactId, "touch_1");
      if (res.data?.id) {
        setGeneratedDraftIds((prev) => new Set(prev).add(row.contactId));
        setRows((prev) => prev.map((r) =>
          r.contactId === row.contactId ? { ...r, draftsCount: r.draftsCount + 1 } : r
        ));
      }
    } catch { /* noop */ }
  };

  const handleBatchGenerate = async () => {
    const eligibleIds = filteredRows
      .filter((r) => !generatedDraftIds.has(r.contactId))
      .map((r) => r.companyId);

    if (!eligibleIds.length) return;
    setBatchGenerating(true);
    setBatchResult(null);
    try {
      const res = await generateOutreachBatch(eligibleIds, "touch_1");
      setBatchResult(`${res.created} drafts created`);
      setGeneratedDraftIds((prev) => {
        const next = new Set(prev);
        filteredRows.forEach((r) => next.add(r.contactId));
        return next;
      });
      setTimeout(() => setBatchResult(null), 5000);
    } catch (e) {
      setBatchResult(e instanceof Error ? e.message : "Batch failed");
    } finally {
      setBatchGenerating(false);
    }
  };

  const filteredRows = rows.filter((r) => {
    if (filterCluster && r.campaignCluster !== filterCluster) return false;
    if (filterPersona && r.personaType !== filterPersona) return false;
    if (filterTranche && r.tranche !== filterTranche) return false;
    return true;
  });

  const clusters = Array.from(new Set(rows.map((r) => r.campaignCluster).filter(Boolean)));
  const tranches = Array.from(new Set(rows.map((r) => r.tranche).filter(Boolean)));

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={filterCluster}
          onChange={(e) => setFilterCluster(e.target.value)}
          className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none"
        >
          <option value="">All Clusters</option>
          {clusters.map((c) => <option key={c} value={c!}>{c}</option>)}
        </select>
        <select
          value={filterPersona}
          onChange={(e) => setFilterPersona(e.target.value)}
          className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none"
        >
          <option value="">All Personas</option>
          {["vp_ops", "plant_manager", "engineer", "procurement", "executive", "default"].map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <select
          value={filterTranche}
          onChange={(e) => setFilterTranche(e.target.value)}
          className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none"
        >
          <option value="">All Tranches</option>
          {tranches.map((t) => <option key={t} value={t!}>{t}</option>)}
        </select>
        <button onClick={loadRows} className="rounded-md border border-gray-200 dark:border-gray-700 p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
        <div className="ml-auto flex items-center gap-2">
          {batchResult && <span className="text-xs text-gray-500 dark:text-gray-400">{batchResult}</span>}
          <button
            onClick={handleBatchGenerate}
            disabled={batchGenerating || filteredRows.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {batchGenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Generate All ({filteredRows.length})
          </button>
        </div>
      </div>

      {/* Rows */}
      {loading ? (
        Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-14 w-full animate-pulse rounded-lg bg-gray-100 dark:bg-gray-800" />
        ))
      ) : filteredRows.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 py-16">
          <Inbox className="h-10 w-10 text-gray-300" />
          <p className="mt-3 text-sm text-gray-500">No companies with research data found</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filteredRows.map((row) => {
            const isExpanded = expandedContactId === row.contactId;
            const hasDraft = generatedDraftIds.has(row.contactId) || row.draftsCount > 0;
            return (
              <div key={row.contactId} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
                {/* Row header */}
                <div className="flex items-center gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-sm text-gray-900 dark:text-gray-100">{row.companyName}</span>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold", getPQSColor(row.pqsTotal))}>
                        PQS {row.pqsTotal}
                      </span>
                      {row.tier && (
                        <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                          {TIER_LABELS[row.tier] ?? row.tier}
                        </span>
                      )}
                      {row.campaignCluster && (
                        <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400">
                          {row.campaignCluster}
                        </span>
                      )}
                      {hasDraft && (
                        <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
                          Draft created
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-500 mt-0.5">
                      {row.contactName && <>{row.contactName} · </>}
                      {row.contactTitle}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {!hasDraft && (
                      <button
                        onClick={() => handleGenerate(row)}
                        className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
                      >
                        <Sparkles className="h-3 w-3" />
                        Generate
                      </button>
                    )}
                    <button
                      onClick={() => handleExpand(row.contactId, row)}
                      className="rounded-md border border-gray-200 dark:border-gray-700 p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                    >
                      {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>

                {/* Intelligence card (expanded) */}
                {isExpanded && (
                  <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-3">
                    {row.intelligenceLoading ? (
                      <div className="flex items-center gap-2 text-xs text-gray-400">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Loading intelligence...
                      </div>
                    ) : row.intelligence ? (
                      <IntelligenceCard
                        contactId={row.contactId}
                        intelligence={row.intelligence}
                        compact
                        onDraftCreated={(draftId) => {
                          setGeneratedDraftIds((prev) => new Set(prev).add(row.contactId));
                        }}
                      />
                    ) : (
                      <p className="text-xs text-gray-400">No intelligence available.</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
type TabKey = "drafts" | "queue" | "inflight" | "history" | "generator";

const TABS: { key: TabKey; label: string; icon?: React.ReactNode }[] = [
  { key: "drafts", label: "Draft Queue" },
  { key: "queue", label: "Send Queue" },
  { key: "inflight", label: "In-Flight" },
  { key: "history", label: "Sent History" },
  { key: "generator", label: "Generator" },
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
            {tab.key === "generator" ? (
              <span className="flex items-center gap-1">
                <Sparkles className="h-3.5 w-3.5" />
                {tab.label}
              </span>
            ) : tab.label}
          </button>
        ))}
      </div>

      {activeTab === "drafts" && <DraftQueueTab />}
      {activeTab === "queue" && <SendQueueTab />}
      {activeTab === "inflight" && <InFlightTab />}
      {activeTab === "history" && <SentHistoryTab />}
      {activeTab === "generator" && <GeneratorTab />}
    </div>
  );
}
