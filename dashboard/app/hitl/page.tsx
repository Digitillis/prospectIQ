"use client";

/**
 * HITL Review Queue — Two-panel email-client UX for reviewing classified replies.
 *
 * Left panel:  Queue list with filter tabs and priority indicators
 * Right panel: Full thread history, classification card, research context, action panel
 */

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  Inbox, Loader2, RefreshCw, Building2, User, Clock,
  ChevronDown, ChevronRight, CheckCircle2, X, Calendar,
  MessageSquare, AlertTriangle,
} from "lucide-react";
import {
  getHitlQueue, getHitlDetail, actionHitlItem, getHitlStats,
  type HitlQueueItem, type HitlDetailResponse, type HitlStats,
} from "@/lib/api";
import { cn, getPQSColor } from "@/lib/utils";
import { ClassificationBadge, priorityLabel, priorityBadgeClass } from "@/components/hitl/ClassificationBadge";
import { ReplyComposer } from "@/components/hitl/ReplyComposer";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeSince(iso?: string | null): string {
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

const FILTER_TABS = [
  { key: null, label: "All" },
  { key: "interested", label: "Interested" },
  { key: "objection", label: "Objections" },
  { key: "referral", label: "Referrals" },
  { key: "out_of_office", label: "OOO" },
  { key: "soft_no", label: "Soft No" },
] as const;

// ---------------------------------------------------------------------------
// Queue List Item
// ---------------------------------------------------------------------------

function QueueListItem({
  item,
  selected,
  onClick,
}: {
  item: HitlQueueItem;
  selected: boolean;
  onClick: () => void;
}) {
  const company = item.company;
  const contact = item.contact;
  const message = item.message;

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-4 py-3 border-b border-gray-50 dark:border-gray-800 transition-colors",
        selected
          ? "bg-gray-50 dark:bg-gray-800"
          : "hover:bg-gray-50 dark:hover:bg-gray-800/50"
      )}
    >
      <div className="flex items-start gap-2">
        {/* Priority dot */}
        <span
          className={cn(
            "mt-1 shrink-0 rounded px-1 py-0.5 text-[9px] font-bold",
            priorityBadgeClass(item.priority)
          )}
        >
          {priorityLabel(item.priority)}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
              {company?.name ?? "Unknown Company"}
            </span>
            <ClassificationBadge
              intent={item.classification ?? "other"}
              confidence={item.classification_confidence ?? undefined}
              showConfidence={false}
            />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-500 mb-1">
            {contact?.full_name ?? "Unknown"}{contact?.title ? ` · ${contact.title}` : ""}
          </p>
          {message?.body && (
            <p className="text-xs text-gray-400 dark:text-gray-600 truncate">
              {message.body.slice(0, 100)}
            </p>
          )}
          <p className="mt-1 text-[10px] text-gray-400 dark:text-gray-600">
            {timeSince(item.created_at)}
          </p>
        </div>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

function DetailPanel({
  hitlId,
  onActioned,
}: {
  hitlId: string;
  onActioned: () => void;
}) {
  const [detail, setDetail] = useState<HitlDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [snoozeDate, setSnoozeDate] = useState("");
  const [showResearch, setShowResearch] = useState(false);
  const [showComposer, setShowComposer] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getHitlDetail(hitlId);
      setDetail(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [hitlId]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const handleAction = async (action: string) => {
    if (!detail) return;
    setActionLoading(action);
    try {
      await actionHitlItem(hitlId, action, notes || undefined, snoozeDate || undefined);
      onActioned();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Action failed");
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 flex-col gap-4 p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex flex-1 items-center justify-center text-gray-400">
        <p className="text-sm">{error ?? "Not found"}</p>
      </div>
    );
  }

  const company = detail.company;
  const contact = detail.contact;
  const messages = detail.messages ?? [];
  const research = detail.research;
  const inbound = messages.find((m) => m.direction === "inbound");

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Thread header */}
      <div className="border-b border-gray-100 dark:border-gray-800 px-6 py-4 shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Building2 className="h-4 w-4 text-gray-400 shrink-0" />
              <span className="font-semibold text-gray-900 dark:text-gray-100">
                {company?.name ?? "Unknown Company"}
              </span>
              {company?.pqs_total !== undefined && (
                <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold", getPQSColor(company.pqs_total))}>
                  PQS {company.pqs_total}
                </span>
              )}
              <span className="text-xs text-gray-400">T{company?.tier ?? "—"}</span>
            </div>
            <div className="flex items-center gap-3">
              <User className="h-3.5 w-3.5 text-gray-400 shrink-0" />
              <span className="text-sm text-gray-600 dark:text-gray-400">
                {contact?.full_name ?? "Unknown"}{contact?.title ? `, ${contact.title}` : ""}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {detail.classification && (
              <ClassificationBadge
                intent={detail.classification}
                confidence={detail.classification_confidence ?? undefined}
                size="md"
              />
            )}
          </div>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">

        {/* Classification card */}
        {inbound && (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
              Classification
            </h3>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <ClassificationBadge
                  intent={detail.classification ?? "other"}
                  confidence={detail.classification_confidence ?? undefined}
                  size="md"
                />
              </div>
              {inbound.summary && (
                <p className="text-sm text-gray-700 dark:text-gray-300 italic">
                  &ldquo;{inbound.summary}&rdquo;
                </p>
              )}
              {/* Extracted entities */}
              {inbound.extracted_entities && (
                <div className="mt-3 space-y-1.5">
                  {(() => {
                    const entities = inbound.extracted_entities as Record<string, unknown>;
                    const competitors = entities.competitors as string[] | undefined;
                    return competitors && competitors.length > 0 ? (
                      <div className="flex items-start gap-2 text-xs">
                        <span className="shrink-0 text-gray-400">Competitors:</span>
                        <span className="text-gray-700 dark:text-gray-300">
                          {competitors.join(", ")}
                        </span>
                      </div>
                    ) : null;
                  })()}
                  {(() => {
                    const entities = inbound.extracted_entities as Record<string, unknown>;
                    const timeline = entities.timeline;
                    return timeline ? (
                      <div className="flex items-start gap-2 text-xs">
                        <span className="shrink-0 text-gray-400">Timeline:</span>
                        <span className="text-gray-700 dark:text-gray-300">
                          {String(timeline)}
                        </span>
                      </div>
                    ) : null;
                  })()}
                  {(() => {
                    const entities = inbound.extracted_entities as Record<string, unknown>;
                    const painPoints = entities.pain_points as string[] | undefined;
                    return painPoints && painPoints.length > 0 ? (
                      <div className="flex items-start gap-2 text-xs">
                        <span className="shrink-0 text-gray-400">Pain points:</span>
                        <span className="text-gray-700 dark:text-gray-300">
                          {painPoints.join(", ")}
                        </span>
                      </div>
                    ) : null;
                  })()}
                </div>
              )}
              {inbound.next_action_suggestion && (
                <div className="mt-3 rounded-md bg-gray-50 dark:bg-gray-800 px-3 py-2">
                  <p className="text-xs text-gray-600 dark:text-gray-400">
                    <span className="font-medium text-gray-800 dark:text-gray-200">Suggested: </span>
                    {inbound.next_action_suggestion}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Thread history */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
            Thread History ({messages.length} messages)
          </h3>
          <div className="space-y-3">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "rounded-lg px-4 py-3 text-sm",
                  msg.direction === "outbound"
                    ? "ml-8 bg-gray-900 dark:bg-gray-700 text-gray-100"
                    : "mr-8 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                )}
              >
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <span className="text-xs font-medium opacity-70">
                    {msg.direction === "outbound" ? "You → " : "← Prospect"}
                    {msg.subject && ` · ${msg.subject}`}
                  </span>
                  <span className="text-[10px] opacity-50 shrink-0">{timeSince(msg.sent_at)}</span>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.body}</p>
                {msg.classification && (
                  <div className="mt-2">
                    <ClassificationBadge intent={msg.classification} showConfidence={false} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Research context (collapsible) */}
        {(research || company?.research_summary) && (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
            <button
              onClick={() => setShowResearch(!showResearch)}
              className="flex w-full items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
            >
              Research Context
              {showResearch ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
            {showResearch && (
              <div className="border-t border-gray-100 dark:border-gray-800 px-4 pb-4 pt-3 space-y-3">
                {company?.research_summary && (
                  <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                    {company.research_summary}
                  </p>
                )}
                {research?.company_description && research.company_description !== company?.research_summary && (
                  <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                    {research.company_description}
                  </p>
                )}
                {company?.personalization_hooks && (company.personalization_hooks as string[]).length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">Personalization Hooks</p>
                    <ul className="space-y-1">
                      {(company.personalization_hooks as string[]).slice(0, 5).map((h, i) => (
                        <li key={i} className="text-xs text-gray-600 dark:text-gray-400">· {h}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {research?.manufacturing_type && (
                  <div className="flex gap-4 text-xs text-gray-500 dark:text-gray-400">
                    <span>Manufacturing: <strong className="text-gray-700 dark:text-gray-300">{research.manufacturing_type}</strong></span>
                    {research?.maintenance_approach && (
                      <span>Maintenance: <strong className="text-gray-700 dark:text-gray-300">{research.maintenance_approach}</strong></span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Notes textarea */}
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
            Notes (optional)
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="Add context for this decision..."
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 dark:focus:ring-gray-600 resize-none"
          />
        </div>
      </div>

      {/* Action panel — sticky bottom */}
      <div className="border-t border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center gap-2">

          {/* Continue Sequence */}
          <button
            onClick={() => handleAction("continue_sequence")}
            disabled={actionLoading !== null}
            className="inline-flex items-center gap-1.5 rounded-md bg-green-600 hover:bg-green-700 disabled:opacity-50 px-3 py-2 text-xs font-medium text-white"
          >
            {actionLoading === "continue_sequence" && <Loader2 className="h-3 w-3 animate-spin" />}
            Continue Sequence
          </button>

          {/* Draft Reply */}
          <button
            onClick={() => setShowComposer(true)}
            disabled={actionLoading !== null}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-3 py-2 text-xs font-medium text-white"
          >
            <MessageSquare className="h-3 w-3" />
            Draft Reply
          </button>

          {/* Mark Converted */}
          <button
            onClick={() => {
              if (confirm("Mark this company as converted? This cannot be undone.")) {
                handleAction("mark_converted");
              }
            }}
            disabled={actionLoading !== null}
            className="inline-flex items-center gap-1.5 rounded-md bg-violet-600 hover:bg-violet-700 disabled:opacity-50 px-3 py-2 text-xs font-medium text-white"
          >
            {actionLoading === "mark_converted" && <Loader2 className="h-3 w-3 animate-spin" />}
            Mark Converted
          </button>

          {/* Snooze */}
          <div className="flex items-center gap-1">
            <input
              type="date"
              value={snoozeDate}
              onChange={(e) => setSnoozeDate(e.target.value)}
              className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-400"
            />
            <button
              onClick={() => {
                if (!snoozeDate) { alert("Pick a snooze date first"); return; }
                handleAction("snooze");
              }}
              disabled={actionLoading !== null || !snoozeDate}
              className="inline-flex items-center gap-1.5 rounded-md bg-amber-500 hover:bg-amber-600 disabled:opacity-50 px-3 py-2 text-xs font-medium text-white"
            >
              {actionLoading === "snooze" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Calendar className="h-3 w-3" />}
              Snooze
            </button>
          </div>

          {/* Archive */}
          <button
            onClick={() => handleAction("archive")}
            disabled={actionLoading !== null}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 disabled:opacity-50 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-300"
          >
            {actionLoading === "archive" && <Loader2 className="h-3 w-3 animate-spin" />}
            Archive
          </button>

        </div>
      </div>

      {/* Reply Composer modal */}
      {showComposer && (
        <ReplyComposer
          hitlId={hitlId}
          contactName={contact?.full_name}
          companyName={company?.name}
          inboundSubject={inbound?.subject ?? ""}
          onClose={() => setShowComposer(false)}
          onSend={(_subject, _body) => {
            // Future: wire to Instantly send API
            setShowComposer(false);
            handleAction("manual_reply");
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function HitlQueuePage() {
  const searchParams = useSearchParams();
  const [queue, setQueue] = useState<HitlQueueItem[]>([]);
  const [stats, setStats] = useState<HitlStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(
    searchParams.get("selected")
  );
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("pending");

  const doFetch = useCallback(async () => {
    setLoading(true);
    try {
      const [qRes, sRes] = await Promise.all([
        getHitlQueue({ status: statusFilter, classification: activeFilter ?? undefined }),
        getHitlStats(),
      ]);
      setQueue(qRes.data ?? []);
      setStats(sRes);
    } catch {
      /* graceful empty */
    } finally {
      setLoading(false);
    }
  }, [statusFilter, activeFilter]);

  useEffect(() => { doFetch(); }, [doFetch]);

  // Alert: interested replies > 24h old
  const staleInterested = queue.filter((item) => {
    if (item.classification !== "interested") return false;
    const age = Date.now() - new Date(item.created_at).getTime();
    return age > 24 * 60 * 60 * 1000;
  });

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">

      {/* Page header */}
      <div className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Inbox className="h-5 w-5 text-gray-400" />
            <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100">Reply Queue</h1>
            {stats && (
              <div className="flex items-center gap-2">
                {stats.pending > 0 && (
                  <span className="rounded-full bg-red-100 dark:bg-red-900/30 px-2 py-0.5 text-xs font-bold text-red-700 dark:text-red-300">
                    {stats.pending} pending
                  </span>
                )}
                {stats.by_classification.interested > 0 && (
                  <span className="rounded-full bg-green-100 dark:bg-green-900/30 px-2 py-0.5 text-xs font-medium text-green-700 dark:text-green-300">
                    {stats.by_classification.interested} interested
                  </span>
                )}
              </div>
            )}
          </div>
          <button
            onClick={doFetch}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        {/* Stale interested alert */}
        {staleInterested.length > 0 && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-4 py-2.5">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-sm text-amber-800 dark:text-amber-300">
              <strong>{staleInterested.length}</strong> interested {staleInterested.length === 1 ? "reply" : "replies"} over 24 hours without action.
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* Left panel — Queue list */}
        <div className="flex w-80 flex-col border-r border-gray-200 dark:border-gray-800 shrink-0 overflow-hidden">

          {/* Filter tabs */}
          <div className="flex gap-0.5 overflow-x-auto border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 px-2 py-2 scrollbar-none shrink-0">
            {FILTER_TABS.map(({ key, label }) => (
              <button
                key={String(key)}
                onClick={() => setActiveFilter(key)}
                className={cn(
                  "shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  activeFilter === key
                    ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900"
                    : "text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-200"
                )}
              >
                {label}
                {key && stats?.by_classification[key] ? (
                  <span className="ml-1 opacity-70">({stats.by_classification[key]})</span>
                ) : null}
              </button>
            ))}
          </div>

          {/* Status sub-filter */}
          <div className="flex gap-1 border-b border-gray-100 dark:border-gray-800 px-3 py-2 shrink-0">
            {["pending", "reviewing", "snoozed"].map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={cn(
                  "rounded px-2 py-0.5 text-[10px] font-medium capitalize transition-colors",
                  statusFilter === s
                    ? "bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                    : "text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
                )}
              >
                {s}
              </button>
            ))}
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex flex-col gap-2 p-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="rounded-lg p-3 border border-gray-100 dark:border-gray-800">
                    <Skeleton className="h-4 w-32 mb-2" />
                    <Skeleton className="h-3 w-48 mb-1" />
                    <Skeleton className="h-3 w-40" />
                  </div>
                ))}
              </div>
            ) : queue.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                <CheckCircle2 className="h-8 w-8 mb-2" />
                <p className="text-sm">Queue is clear</p>
              </div>
            ) : (
              queue.map((item) => (
                <QueueListItem
                  key={item.id}
                  item={item}
                  selected={selectedId === item.id}
                  onClick={() => setSelectedId(item.id)}
                />
              ))
            )}
          </div>
        </div>

        {/* Right panel — Detail */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {selectedId ? (
            <DetailPanel
              key={selectedId}
              hitlId={selectedId}
              onActioned={() => {
                setSelectedId(null);
                doFetch();
              }}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-gray-400">
              <Inbox className="h-12 w-12" />
              <p className="text-sm">Select a reply to review</p>
              {queue.length > 0 && (
                <p className="text-xs">{queue.length} item{queue.length !== 1 ? "s" : ""} in queue</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
