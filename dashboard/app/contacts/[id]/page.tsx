"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  Linkedin,
  Loader2,
  Mail,
  MapPin,
  MessageSquare,
  Pencil,
  Phone,
  Star,
  Zap,
} from "lucide-react";
import {
  getContact,
  getContactEvents,
  createContactEvent,
  updateNextAction,
  type Contact,
  type ContactEvent,
  type LinkedInIntel,
} from "@/lib/api";
import { cn, formatTimeAgo, STATUS_COLORS, getPQSColor } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContactDetail = Contact & {
  companies?: {
    id: string;
    name: string;
    tier?: string;
    status: string;
    pqs_total: number;
    domain?: string;
    sub_sector?: string;
    industry?: string;
    employee_count?: number;
    revenue_printed?: string;
    headcount_growth_6m?: number;
    is_public?: boolean;
    pain_signals?: string[];
  };
  research?: {
    products_services?: string[];
    recent_news?: string[];
    pain_points?: string[];
    known_systems?: string[];
  } | null;
  outreach_drafts?: Array<{
    id: string;
    channel: string;
    sequence_name: string;
    body: string;
    subject?: string;
    approval_status: string;
  }>;
  city?: string;
  state?: string;
};

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

function formatEventType(type: string): string {
  const labels: Record<string, string> = {
    outreach_sent: "Message Sent",
    response_received: "Response Received",
    connection_accepted: "Connection Accepted",
    connection_sent: "Connection Sent",
    note_added: "Note",
    meeting_scheduled: "Meeting Scheduled",
    meeting_held: "Meeting Held",
    phone_call: "Phone Call",
    email_reply: "Email Reply",
    email_opened: "Email Opened",
    link_clicked: "Link Clicked",
    profile_viewed: "Profile Viewed",
    status_change: "Status Changed",
    system_action: "System",
  };
  return labels[type] || type.replace(/_/g, " ");
}

function formatRelativeTime(iso: string): string {
  const now = new Date();
  const date = new Date(iso);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// CopyButton
// ---------------------------------------------------------------------------

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-300 transition-colors"
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-500" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
      {copied ? "Copied!" : label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// TierBadge
// ---------------------------------------------------------------------------

function TierBadge({ tier }: { tier?: string }) {
  if (!tier) return null;
  const colors: Record<string, string> = {
    fb_1: "bg-emerald-100 text-emerald-700 border-emerald-200",
    fb_2: "bg-emerald-50 text-emerald-600 border-emerald-200",
    mfg_1: "bg-blue-100 text-blue-700 border-blue-200",
    mfg_2: "bg-blue-50 text-blue-600 border-blue-200",
    "1": "bg-blue-100 text-blue-700 border-blue-200",
    "2": "bg-blue-50 text-blue-600 border-blue-200",
  };
  const cls = colors[tier] ?? "bg-gray-100 text-gray-600 border-gray-200";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      Tier {tier}
    </span>
  );
}

// ---------------------------------------------------------------------------
// IntelPanel
// ---------------------------------------------------------------------------

function IntelPanel({
  intel,
  research,
}: {
  intel?: LinkedInIntel;
  research?: ContactDetail["research"];
}) {
  const [open, setOpen] = useState(false);

  const hasContent =
    intel?.personalization_notes ||
    (research?.products_services?.length ?? 0) > 0 ||
    (research?.recent_news?.length ?? 0) > 0 ||
    (research?.pain_points?.length ?? 0) > 0 ||
    (intel?.company?.pain_signals?.length ?? 0) > 0 ||
    (research?.known_systems?.length ?? 0) > 0 ||
    intel?.company?.industry ||
    intel?.company?.employee_count ||
    intel?.company?.revenue_printed;

  if (!hasContent) return null;

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {open ? "Hide Intel" : "View Company Intel"}
      </button>

      {open && (
        <div className="mt-2 rounded-lg bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-3 text-xs space-y-3">
          {intel?.personalization_notes && (
            <div>
              <div className="font-semibold text-gray-500 mb-1 uppercase tracking-wide text-[10px]">
                WHY THIS CONTACT
              </div>
              <p className="text-gray-700 dark:text-gray-300">{intel.personalization_notes}</p>
            </div>
          )}

          {((research?.products_services?.length ?? 0) > 0 ||
            (research?.recent_news?.length ?? 0) > 0 ||
            (research?.pain_points?.length ?? 0) > 0 ||
            (intel?.company?.pain_signals?.length ?? 0) > 0 ||
            (research?.known_systems?.length ?? 0) > 0) && (
            <div>
              <div className="font-semibold text-gray-500 mb-1 uppercase tracking-wide text-[10px]">
                COMPANY RESEARCH
              </div>
              <div className="space-y-1 text-gray-500">
                {(research?.products_services?.length ?? 0) > 0 && (
                  <p>Products: {research!.products_services!.join(", ")}</p>
                )}
                {(research?.recent_news?.length ?? 0) > 0 && (
                  <p>Recent: {research!.recent_news!.join("; ")}</p>
                )}
                {((research?.pain_points?.length ?? 0) > 0 ||
                  (intel?.company?.pain_signals?.length ?? 0) > 0) && (
                  <p>
                    Pain points:{" "}
                    {(
                      research?.pain_points ||
                      intel?.company?.pain_signals ||
                      []
                    ).join(", ")}
                  </p>
                )}
                {(research?.known_systems?.length ?? 0) > 0 && (
                  <p>Systems: {research!.known_systems!.join(", ")}</p>
                )}
              </div>
            </div>
          )}

          {(intel?.company?.industry ||
            intel?.company?.employee_count ||
            intel?.company?.revenue_printed) && (
            <div>
              <div className="font-semibold text-gray-500 mb-1 uppercase tracking-wide text-[10px]">
                FIRMOGRAPHICS
              </div>
              <div className="space-y-0.5 text-gray-500">
                {intel.company?.industry && <p>Industry: {intel.company.industry}</p>}
                {intel.company?.employee_count && (
                  <p>Employees: {intel.company.employee_count.toLocaleString()}</p>
                )}
                {intel.company?.revenue_printed && (
                  <p>Revenue: {intel.company.revenue_printed}</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageDraftBlock
// ---------------------------------------------------------------------------

function MessageDraftBlock({
  label,
  body,
}: {
  label: string;
  body: string;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(body);

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          {label}
        </span>
        <div className="flex items-center gap-1">
          <CopyButton text={value} />
          <button
            onClick={() => setEditing((e) => !e)}
            className={cn(
              "flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors hover:bg-gray-200 dark:hover:bg-gray-700",
              editing ? "text-amber-600" : "text-gray-400"
            )}
          >
            <Pencil className="h-3 w-3" />
            {editing ? "Done" : "Edit"}
          </button>
        </div>
      </div>
      {editing ? (
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1.5 text-sm text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-400"
          rows={4}
        />
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700 dark:text-gray-300">{value}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EventCard
// ---------------------------------------------------------------------------

function EventCard({
  event,
  onMarkDone,
  onSkip,
}: {
  event: ContactEvent;
  onMarkDone: (id: string) => void;
  onSkip: (id: string) => void;
}) {
  const isOutbound = event.direction === "outbound";
  const isInbound = event.direction === "inbound";

  return (
    <div className="flex gap-3 mb-4">
      {/* Timeline dot + line */}
      <div className="flex flex-col items-center flex-shrink-0">
        <div
          className={cn(
            "w-3 h-3 rounded-full mt-1.5 flex-shrink-0 ring-2 ring-white dark:ring-gray-900",
            isOutbound
              ? "bg-blue-500"
              : isInbound
              ? "bg-green-500"
              : "bg-gray-300 dark:bg-gray-600"
          )}
        />
        <div className="w-px flex-1 bg-gray-100 dark:bg-gray-800 mt-1" />
      </div>

      {/* Card */}
      <div className="flex-1 min-w-0 rounded-xl p-3.5 text-sm bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 shadow-sm mb-1">
        {/* Header row */}
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mb-2">
          <span className="font-semibold text-gray-800 dark:text-gray-100">
            {formatEventType(event.event_type)}
          </span>
          {event.channel && (
            <span className="capitalize text-gray-400">· {event.channel}</span>
          )}
          <span className="text-gray-400">· {formatRelativeTime(event.created_at)}</span>
          {event.ai_analyzed && (
            <span title="AI analyzed" className="text-purple-500">
              <Zap className="w-3 h-3 inline" />
            </span>
          )}
          {event.sentiment && (
            <span
              className={cn(
                "px-1.5 py-0.5 rounded-full text-xs font-medium",
                event.sentiment === "positive"
                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                  : event.sentiment === "negative"
                  ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                  : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
              )}
            >
              {event.sentiment}
            </span>
          )}
        </div>

        {/* Body */}
        {event.body && (
          <p className="text-gray-800 dark:text-gray-200 whitespace-pre-wrap leading-relaxed">
            {event.body}
          </p>
        )}

        {/* Sentiment reason */}
        {event.sentiment_reason && (
          <p className="text-xs text-gray-400 mt-1.5 italic">{event.sentiment_reason}</p>
        )}

        {/* Signal tags */}
        {(event.signals?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {event.signals!.map((s, i) => (
              <span
                key={i}
                className="px-2 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 rounded-full text-xs font-medium"
              >
                {s}
              </span>
            ))}
          </div>
        )}

        {/* General tags */}
        {(event.tags?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {event.tags!.map((t, i) => (
              <span
                key={i}
                className="px-2 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 rounded-full text-xs"
              >
                {t}
              </span>
            ))}
          </div>
        )}

        {/* Pending next action */}
        {event.next_action && event.next_action_status === "pending" && (
          <div className="mt-3 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-amber-800 dark:text-amber-400 uppercase tracking-wide">
                Recommended Next Action
              </span>
              {event.next_action_date && (
                <span className="text-xs text-amber-600 dark:text-amber-500">
                  {event.next_action_date}
                </span>
              )}
            </div>
            <p className="text-sm text-amber-900 dark:text-amber-300">{event.next_action}</p>

            {event.suggested_message && (
              <div className="mt-2 p-2.5 bg-white dark:bg-gray-900 rounded-lg border border-amber-100 dark:border-amber-800/50">
                <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed">
                  {event.suggested_message}
                </p>
                <button
                  className="mt-1.5 text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
                  onClick={() =>
                    navigator.clipboard.writeText(event.suggested_message!)
                  }
                >
                  <Copy className="w-3 h-3" /> Copy suggested message
                </button>
              </div>
            )}

            {event.action_reasoning && (
              <p className="text-xs text-amber-600 dark:text-amber-500 mt-1.5 italic">
                {event.action_reasoning}
              </p>
            )}

            <div className="flex gap-2 mt-2.5">
              <button
                onClick={() => onMarkDone(event.id)}
                className="px-3 py-1 text-xs bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium"
              >
                Mark Done
              </button>
              <button
                onClick={() => onSkip(event.id)}
                className="px-3 py-1 text-xs bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors font-medium"
              >
                Skip
              </button>
            </div>
          </div>
        )}

        {/* Completed next action */}
        {event.next_action && event.next_action_status === "done" && (
          <div className="mt-2 flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
            <Check className="w-3 h-3" /> Action completed
          </div>
        )}

        {/* Skipped next action */}
        {event.next_action && event.next_action_status === "skipped" && (
          <div className="mt-2 text-xs text-gray-400 italic">Action skipped</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AddEventForm
// ---------------------------------------------------------------------------

const EVENT_TYPES = [
  { value: "response_received", label: "Response Received" },
  { value: "connection_accepted", label: "Connection Accepted" },
  { value: "note_added", label: "Note Added" },
  { value: "meeting_scheduled", label: "Meeting Scheduled" },
  { value: "meeting_held", label: "Meeting Held" },
  { value: "phone_call", label: "Phone Call" },
  { value: "email_reply", label: "Email Reply" },
] as const;

const CHANNELS = [
  { value: "", label: "— none —" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "in_person", label: "In Person" },
] as const;

const INBOUND_TYPES = new Set([
  "response_received",
  "email_reply",
  "connection_accepted",
]);

function AddEventForm({
  contactId,
  onSaved,
}: {
  contactId: string;
  onSaved: (event: ContactEvent) => void;
}) {
  const [eventType, setEventType] = useState<string>("response_received");
  const [channel, setChannel] = useState<string>("linkedin");
  const [body, setBody] = useState("");
  const [analyze, setAnalyze] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isInbound = INBOUND_TYPES.has(eventType);

  const handleSubmit = async () => {
    setError(null);
    setSaving(true);
    try {
      const res = await createContactEvent(contactId, {
        event_type: eventType,
        channel: channel || undefined,
        body: body.trim() || undefined,
        analyze: analyze && isInbound,
      });
      onSaved(res.data);
      setBody("");
      setAnalyze(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save event");
    } finally {
      setSaving(false);
    }
  };

  const selectCls =
    "w-full border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 text-sm text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400";

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
        Add Event
      </h3>

      <div className="space-y-2.5">
        {/* Event type */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Type</label>
          <select
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
            className={selectCls}
          >
            {EVENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        {/* Channel */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Channel</label>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            className={selectCls}
          >
            {CHANNELS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>

        {/* Body */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            {isInbound ? "Their message" : "Your notes"}
          </label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={
              isInbound
                ? "Paste their reply or message here…"
                : "Add notes about this interaction…"
            }
            rows={3}
            className="w-full border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 text-sm text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
          />
        </div>

        {/* AI analysis — only shown for inbound events */}
        {isInbound && (
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={analyze}
              onChange={(e) => setAnalyze(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-400"
            />
            <span className="text-xs text-gray-600 dark:text-gray-400 flex items-center gap-1">
              <Zap className="w-3 h-3 text-purple-500" />
              Run AI analysis
            </span>
          </label>
        )}

        {/* Error */}
        {error && (
          <p className="text-xs text-red-500">{error}</p>
        )}

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={saving}
          className="w-full py-2 rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-sm font-medium hover:bg-gray-700 dark:hover:bg-gray-300 transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
        >
          {saving ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              {analyze && isInbound ? "Analyzing…" : "Saving…"}
            </>
          ) : (
            "Save Event"
          )}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();

  const [contact, setContact] = useState<ContactDetail | null>(null);
  const [events, setEvents] = useState<ContactEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // -------------------------------------------------------------------------
  // Data fetching
  // -------------------------------------------------------------------------

  const fetchContact = useCallback(async () => {
    try {
      const res = await getContact(id);
      setContact(res.data as ContactDetail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load contact");
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchEvents = useCallback(async () => {
    try {
      const res = await getContactEvents(id);
      setEvents(res.data);
    } catch {
      // contact_events table may not exist yet — show empty thread
    } finally {
      setEventsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchContact();
    fetchEvents();

    // Auto-refresh events every 30 seconds
    refreshTimerRef.current = setInterval(fetchEvents, 30_000);
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    };
  }, [fetchContact, fetchEvents]);

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  const handleEventSaved = (newEvent: ContactEvent) => {
    // Optimistic prepend — newest event at top
    setEvents((prev) => [newEvent, ...prev]);
  };

  const handleMarkDone = async (eventId: string) => {
    try {
      const res = await updateNextAction(eventId, "done");
      setEvents((prev) =>
        prev.map((e) => (e.id === eventId ? res.data : e))
      );
    } catch (err) {
      console.error("Failed to mark action done:", err);
    }
  };

  const handleSkipAction = async (eventId: string) => {
    try {
      const res = await updateNextAction(eventId, "skipped");
      setEvents((prev) =>
        prev.map((e) => (e.id === eventId ? res.data : e))
      );
    } catch (err) {
      console.error("Failed to skip action:", err);
    }
  };

  // -------------------------------------------------------------------------
  // Render states
  // -------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-950">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error || !contact) {
    return (
      <div className="p-8 text-center min-h-screen bg-gray-50 dark:bg-gray-950">
        <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
        <p className="text-gray-600 dark:text-gray-400">{error ?? "Contact not found"}</p>
        <Link
          href="/contacts"
          className="mt-4 inline-flex items-center gap-1 text-blue-600 text-sm hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Contacts
        </Link>
      </div>
    );
  }

  const company = contact.companies;
  const logoUrl = company?.domain
    ? `https://logo.clearbit.com/${company.domain}`
    : null;

  // Outreach drafts
  const drafts = contact.outreach_drafts ?? [];
  const connectionNote = drafts.find(
    (d) =>
      d.channel === "linkedin" &&
      (d.sequence_name?.toLowerCase().includes("connection") ||
        d.sequence_name?.toLowerCase().includes("connect"))
  );
  const openingDm = drafts.find(
    (d) =>
      d.channel === "linkedin" &&
      (d.sequence_name?.toLowerCase().includes("opening") ||
        d.sequence_name?.toLowerCase().includes("dm"))
  );
  const followupDm = drafts.find(
    (d) =>
      d.channel === "linkedin" &&
      d.sequence_name?.toLowerCase().includes("follow")
  );
  const emailDraft = drafts.find((d) => d.channel === "email");

  const intel: LinkedInIntel | undefined = company
    ? {
        company: {
          industry: company.industry,
          employee_count: company.employee_count,
          revenue_printed: company.revenue_printed,
          headcount_growth_6m: company.headcount_growth_6m,
          is_public: company.is_public,
          pain_signals: company.pain_signals,
        },
      }
    : undefined;

  // Pending next actions count for badge
  const pendingActionsCount = events.filter(
    (e) => e.next_action && e.next_action_status === "pending"
  ).length;

  // -------------------------------------------------------------------------
  // Main render — two-panel layout
  // -------------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">

        {/* Back nav */}
        <Link
          href="/contacts"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 mb-5 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Contacts
        </Link>

        <div className="flex gap-6 items-start">

          {/* ==============================================================
              LEFT PANEL — 40% width, sticky
          ============================================================== */}
          <div
            className="w-[40%] flex-shrink-0 sticky top-6 max-h-[calc(100vh-5rem)] overflow-y-auto space-y-4"
            style={{ scrollbarWidth: "thin" }}
          >

            {/* ── Contact header card ── */}
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-5">

              {/* Avatar + name */}
              <div className="flex items-start gap-3 mb-4">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center flex-shrink-0 text-white font-semibold text-lg select-none">
                  {(contact.full_name ?? "?")[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100 leading-tight">
                    {contact.full_name || "Unknown Contact"}
                  </h1>
                  {contact.title && (
                    <p className="text-sm text-gray-500 dark:text-gray-400">{contact.title}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 mt-1.5">
                    {contact.is_decision_maker && (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
                        <Star className="w-3 h-3" /> Decision Maker
                      </span>
                    )}
                    {company && <TierBadge tier={company.tier} />}
                    {contact.status && (
                      <span
                        className={cn(
                          "text-xs font-medium rounded-full px-2 py-0.5",
                          STATUS_COLORS[contact.status] ?? "bg-gray-100 text-gray-500"
                        )}
                      >
                        {contact.status}
                      </span>
                    )}
                  </div>
                </div>

                {/* PQS score */}
                {company && (
                  <div className="flex-shrink-0 text-right">
                    <div className={cn("text-xl font-bold tabular-nums", getPQSColor(company.pqs_total))}>
                      {company.pqs_total}
                    </div>
                    <div className="text-[10px] text-gray-400 uppercase tracking-wide">PQS</div>
                  </div>
                )}
              </div>

              {/* Company link */}
              {company && (
                <Link
                  href={`/prospects/${company.id}`}
                  className="flex items-center gap-2.5 p-2.5 rounded-xl bg-gray-50 dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors group mb-4"
                >
                  {logoUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={logoUrl}
                      alt={company.name}
                      className="w-7 h-7 rounded object-contain"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                  ) : (
                    <Building2 className="w-5 h-5 text-gray-400 flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 dark:text-gray-200 group-hover:text-blue-700 dark:group-hover:text-blue-400 truncate">
                      {company.name}
                    </p>
                    {company.sub_sector && (
                      <p className="text-xs text-gray-400 truncate">{company.sub_sector}</p>
                    )}
                  </div>
                  <ExternalLink className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-400 flex-shrink-0" />
                </Link>
              )}

              {/* Contact info */}
              <div className="space-y-2">
                {contact.email && (
                  <a
                    href={`mailto:${contact.email}`}
                    className="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                  >
                    <Mail className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <span className="truncate">{contact.email}</span>
                  </a>
                )}
                {contact.linkedin_url && (
                  <a
                    href={contact.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2.5 text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 transition-colors"
                  >
                    <Linkedin className="w-4 h-4 flex-shrink-0" />
                    LinkedIn Profile
                    <ExternalLink className="w-3 h-3 text-gray-400 ml-auto" />
                  </a>
                )}
                {contact.phone && (
                  <a
                    href={`tel:${contact.phone}`}
                    className="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 transition-colors"
                  >
                    <Phone className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    {contact.phone}
                  </a>
                )}
                {(contact.city || contact.state) && (
                  <div className="flex items-center gap-2.5 text-sm text-gray-500 dark:text-gray-400">
                    <MapPin className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    {[contact.city, contact.state].filter(Boolean).join(", ")}
                  </div>
                )}
              </div>

              {/* LinkedIn channel status */}
              {contact.linkedin_status && contact.linkedin_status !== "not_sent" && (
                <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                  <div className="flex items-center gap-2 text-xs">
                    <Linkedin className="w-3.5 h-3.5 text-blue-500" />
                    <span className="text-gray-400">LinkedIn:</span>
                    <span className="font-medium text-blue-600 dark:text-blue-400 capitalize">
                      {contact.linkedin_status.replace(/_/g, " ")}
                    </span>
                  </div>
                </div>
              )}

              {/* Intel panel */}
              <IntelPanel intel={intel} research={contact.research} />
            </div>

            {/* ── Prepared messages card ── */}
            {(connectionNote || openingDm || followupDm || emailDraft) && (
              <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-5">
                <h2 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
                  Prepared Messages
                </h2>
                <div className="space-y-3">
                  {connectionNote && (
                    <MessageDraftBlock
                      label="Connection Note"
                      body={connectionNote.body}
                    />
                  )}
                  {openingDm && (
                    <MessageDraftBlock
                      label="Opening DM"
                      body={openingDm.body}
                    />
                  )}
                  {followupDm && (
                    <MessageDraftBlock
                      label="Follow-up DM"
                      body={followupDm.body}
                    />
                  )}
                  {emailDraft && (
                    <MessageDraftBlock
                      label={emailDraft.subject ? `Email: ${emailDraft.subject}` : "Email Draft"}
                      body={emailDraft.body}
                    />
                  )}
                </div>
              </div>
            )}

            {/* ── Add Event form card ── */}
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-5">
              <AddEventForm contactId={id} onSaved={handleEventSaved} />
            </div>
          </div>

          {/* ==============================================================
              RIGHT PANEL — 60% width, scrollable event thread
          ============================================================== */}
          <div className="flex-1 min-w-0">
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-5">

              {/* Thread header */}
              <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-2.5">
                  <MessageSquare className="w-4 h-4 text-gray-400" />
                  <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                    Event Thread
                  </h2>
                  {events.length > 0 && (
                    <span className="text-xs text-gray-400 font-normal bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
                      {events.length}
                    </span>
                  )}
                  {pendingActionsCount > 0 && (
                    <span className="text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
                      {pendingActionsCount} action{pendingActionsCount !== 1 ? "s" : ""} pending
                    </span>
                  )}
                </div>

                {/* Legend */}
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-blue-400 inline-block" />
                    Outbound
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
                    Inbound
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600 inline-block" />
                    Internal
                  </span>
                </div>
              </div>

              {/* Events list */}
              {eventsLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-300" />
                </div>
              ) : events.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <MessageSquare className="w-10 h-10 text-gray-200 dark:text-gray-700 mb-3" />
                  <p className="text-gray-400 dark:text-gray-500 font-medium">No events yet</p>
                  <p className="text-sm text-gray-300 dark:text-gray-600 mt-1">
                    Use the form on the left to log the first interaction.
                  </p>
                </div>
              ) : (
                <div>
                  {events.map((event) => (
                    <EventCard
                      key={event.id}
                      event={event}
                      onMarkDone={handleMarkDone}
                      onSkip={handleSkipAction}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
