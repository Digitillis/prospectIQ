"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Loader2,
  Calendar,
  Pause,
  Play,
  StopCircle,
  MessageSquareReply,
  CheckCircle2,
} from "lucide-react";
import {
  getSequenceTimeline,
  logReply,
  rescheduleStep as apiRescheduleStep,
  patchEnrollment,
  type TimelineRow,
  type LogReplyPayload,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const INTENT_LABELS: Record<string, string> = {
  interested: "Interested",
  not_interested: "Not Interested",
  question: "Question",
  referral: "Referral",
  objection: "Objection",
};

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  paused: "bg-yellow-100 text-yellow-700",
  completed: "bg-gray-100 text-gray-500",
  stopped: "bg-red-100 text-red-600",
};

type FilterTab = "all" | "active" | "replied" | "paused" | "completed";

function formatDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function SequenceTimelinePage() {
  const [rows, setRows] = useState<TimelineRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<FilterTab>("all");

  // Reply form state
  const [replyRowId, setReplyRowId] = useState<string | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [replyIntent, setReplyIntent] = useState<LogReplyPayload["intent"]>("interested");
  const [replyNotes, setReplyNotes] = useState("");
  const [replyLoading, setReplyLoading] = useState<string | null>(null);

  // Reschedule state
  const [rescheduleRowId, setRescheduleRowId] = useState<string | null>(null);
  const [rescheduleStep, setRescheduleStepVal] = useState(2);
  const [rescheduleDate, setRescheduleDate] = useState("");
  const [rescheduleLoading, setRescheduleLoading] = useState<string | null>(null);

  // Action loading (pause/resume/stop)
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchTimeline = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getSequenceTimeline();
      setRows(res.data || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load timeline");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTimeline();
  }, [fetchTimeline]);

  const handleLogReply = async (row: TimelineRow) => {
    if (!replyBody.trim()) return;
    setReplyLoading(row.enrollment_id);
    try {
      await logReply(row.contact_id, {
        body: replyBody,
        intent: replyIntent,
        notes: replyNotes || undefined,
        sequence_enrollment_id: row.enrollment_id,
      });
      setRows((prev) =>
        prev.map((r) =>
          r.enrollment_id === row.enrollment_id
            ? { ...r, reply_received: true, reply_intent: replyIntent }
            : r
        )
      );
      setReplyRowId(null);
      setReplyBody("");
      setReplyNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log reply");
    } finally {
      setReplyLoading(null);
    }
  };

  const handleReschedule = async (row: TimelineRow) => {
    if (!rescheduleDate) return;
    setRescheduleLoading(row.enrollment_id);
    try {
      await apiRescheduleStep(row.enrollment_id, rescheduleStep, new Date(rescheduleDate).toISOString());
      setRows((prev) =>
        prev.map((r) =>
          r.enrollment_id === row.enrollment_id
            ? { ...r, next_action_at: new Date(rescheduleDate).toISOString() }
            : r
        )
      );
      setRescheduleRowId(null);
      setRescheduleDate("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reschedule");
    } finally {
      setRescheduleLoading(null);
    }
  };

  const handlePatchStatus = async (
    enrollmentId: string,
    status: "paused" | "active" | "stopped"
  ) => {
    setActionLoading(enrollmentId);
    try {
      await patchEnrollment(enrollmentId, status);
      setRows((prev) =>
        prev.map((r) =>
          r.enrollment_id === enrollmentId ? { ...r, status } : r
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update enrollment");
    } finally {
      setActionLoading(null);
    }
  };

  const filtered = rows.filter((r) => {
    if (tab === "all") return true;
    if (tab === "replied") return r.reply_received;
    return r.status === tab;
  });

  const tabCounts: Record<FilterTab, number> = {
    all: rows.length,
    active: rows.filter((r) => r.status === "active").length,
    replied: rows.filter((r) => r.reply_received).length,
    paused: rows.filter((r) => r.status === "paused").length,
    completed: rows.filter((r) => r.status === "completed").length,
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
            Sequence Timeline
          </h2>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-500">
            {rows.length} enrolled · track per-contact step schedule, replies, and due dates
          </p>
        </div>
        <button
          onClick={fetchTimeline}
          className="rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700">
        {(["all", "active", "replied", "paused", "completed"] as FilterTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-3 py-2 text-xs font-medium capitalize transition-colors border-b-2 -mb-px",
              tab === t
                ? "border-gray-900 text-gray-900 dark:text-gray-100 dark:border-gray-100"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500"
            )}
          >
            {t} <span className="ml-1 text-[10px] text-gray-400">({tabCounts[t]})</span>
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Contact</th>
              <th className="px-4 py-2.5 text-left font-medium">Company</th>
              <th className="px-4 py-2.5 text-left font-medium">Step</th>
              <th className="px-4 py-2.5 text-left font-medium">Step 1</th>
              <th className="px-4 py-2.5 text-left font-medium">Step 2</th>
              <th className="px-4 py-2.5 text-left font-medium">Step 3</th>
              <th className="px-4 py-2.5 text-left font-medium">Step 4</th>
              <th className="px-4 py-2.5 text-left font-medium">Status</th>
              <th className="px-4 py-2.5 text-left font-medium">Reply</th>
              <th className="px-4 py-2.5 text-left font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {filtered.length === 0 && (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-gray-400">
                  No enrollments found.
                </td>
              </tr>
            )}
            {filtered.map((row) => (
              <>
                <tr
                  key={row.enrollment_id}
                  className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800/50"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900 dark:text-gray-100">
                      {row.contact_name ?? row.contact_id.slice(0, 8)}
                    </div>
                    {row.contact_email && (
                      <div className="text-[10px] text-gray-400 dark:text-gray-500">{row.contact_email}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                    {row.company_name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                    {row.current_step}/{row.total_steps}
                  </td>
                  {/* Step date cells */}
                  {([1, 2, 3, 4] as const).map((step) => {
                    const key = `step${step}_due_at` as keyof TimelineRow;
                    const due = row[key] as string | undefined;
                    const isSent = step < (row.current_step ?? 1) || (step === 1 && row.step1_sent_at);
                    return (
                      <td key={step} className="px-4 py-3">
                        {due ? (
                          <span className={cn("inline-flex items-center gap-1", isSent ? "text-gray-400 line-through" : "text-gray-700 dark:text-gray-300")}>
                            {formatDate(due)}
                            {!isSent && step > 1 && (
                              <button
                                onClick={() => {
                                  setRescheduleRowId(row.enrollment_id);
                                  setRescheduleStepVal(step);
                                  setRescheduleDate(due.slice(0, 10));
                                }}
                                className="ml-1 text-gray-400 hover:text-gray-600"
                                title="Reschedule"
                              >
                                <Calendar className="h-3 w-3" />
                              </button>
                            )}
                          </span>
                        ) : (
                          <span className="text-gray-300 dark:text-gray-600">—</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="px-4 py-3">
                    <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium capitalize", STATUS_STYLES[row.status] ?? "bg-gray-100 text-gray-500")}>
                      {row.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {row.reply_received ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                        ↩ {row.reply_intent ? INTENT_LABELS[row.reply_intent] ?? row.reply_intent : "Replied"}
                      </span>
                    ) : (
                      <span className="text-gray-300 dark:text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      {row.status === "active" && (
                        <button
                          onClick={() => handlePatchStatus(row.enrollment_id, "paused")}
                          disabled={actionLoading === row.enrollment_id}
                          title="Pause"
                          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-40"
                        >
                          {actionLoading === row.enrollment_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pause className="h-3.5 w-3.5" />}
                        </button>
                      )}
                      {row.status === "paused" && (
                        <button
                          onClick={() => handlePatchStatus(row.enrollment_id, "active")}
                          disabled={actionLoading === row.enrollment_id}
                          title="Resume"
                          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-green-700 disabled:opacity-40"
                        >
                          {actionLoading === row.enrollment_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                        </button>
                      )}
                      {row.status !== "stopped" && row.status !== "completed" && (
                        <button
                          onClick={() => handlePatchStatus(row.enrollment_id, "stopped")}
                          disabled={actionLoading === row.enrollment_id}
                          title="Stop"
                          className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                        >
                          <StopCircle className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {!row.reply_received && (
                        <button
                          onClick={() => {
                            setReplyRowId(replyRowId === row.enrollment_id ? null : row.enrollment_id);
                            setReplyBody("");
                            setReplyNotes("");
                            setReplyIntent("interested");
                          }}
                          title="Log Reply"
                          className="rounded p-1 text-gray-400 hover:bg-amber-50 hover:text-amber-600"
                        >
                          <MessageSquareReply className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>

                {/* Inline Reply Form */}
                {replyRowId === row.enrollment_id && (
                  <tr key={`${row.enrollment_id}-reply`} className="bg-amber-50/60">
                    <td colSpan={10} className="px-4 py-3">
                      <div className="flex items-start gap-3">
                        <textarea
                          value={replyBody}
                          onChange={(e) => setReplyBody(e.target.value)}
                          rows={2}
                          placeholder="Paste reply text..."
                          className="flex-1 rounded-md border border-amber-200 bg-white p-2 text-xs text-gray-700 focus:outline-none"
                        />
                        <select
                          value={replyIntent}
                          onChange={(e) => setReplyIntent(e.target.value as LogReplyPayload["intent"])}
                          className="rounded-md border border-amber-200 bg-white px-2 py-1.5 text-xs"
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
                          placeholder="Notes"
                          className="w-32 rounded-md border border-amber-200 bg-white px-2 py-1.5 text-xs"
                        />
                        <button
                          onClick={() => handleLogReply(row)}
                          disabled={!replyBody.trim() || replyLoading === row.enrollment_id}
                          className="inline-flex items-center gap-1 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                        >
                          {replyLoading === row.enrollment_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                          Save
                        </button>
                        <button onClick={() => setReplyRowId(null)} className="text-xs text-gray-500 hover:text-gray-700">
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                )}

                {/* Inline Reschedule Form */}
                {rescheduleRowId === row.enrollment_id && (
                  <tr key={`${row.enrollment_id}-reschedule`} className="bg-blue-50/60">
                    <td colSpan={10} className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-gray-700">Reschedule Step {rescheduleStep} for <strong>{row.contact_name}</strong>:</span>
                        <input
                          type="date"
                          value={rescheduleDate}
                          onChange={(e) => setRescheduleDate(e.target.value)}
                          className="rounded-md border border-blue-200 bg-white px-2 py-1.5 text-xs"
                        />
                        <button
                          onClick={() => handleReschedule(row)}
                          disabled={!rescheduleDate || rescheduleLoading === row.enrollment_id}
                          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                        >
                          {rescheduleLoading === row.enrollment_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                          Confirm
                        </button>
                        <button onClick={() => setRescheduleRowId(null)} className="text-xs text-gray-500 hover:text-gray-700">
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
