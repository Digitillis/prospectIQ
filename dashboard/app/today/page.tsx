"use client";

/**
 * Daily Cockpit — Morning command center for Avanish
 *
 * The ONE page to open every morning. Shows exactly what to do today,
 * in priority order. Updates dynamically every 30 seconds. Optimistic
 * UI: actions register instantly without waiting for the server.
 *
 * Sections (in priority order):
 *   1. RESPOND NOW      — Hot signals needing immediate response
 *   2. SEND CONNECTIONS — LinkedIn connection requests (target: 10/day)
 *   3. SEND DMs         — Opening DMs to accepted connections
 *   4. APPROVE EMAILS   — Email drafts pending review
 *   5. POST CONTENT     — Today's thought leadership post
 *   6. LOG RESPONSES    — Record outcomes from recent outreach
 *   7. GROW PIPELINE    — Run discovery / research / qualification
 */

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  Flame,
  UserPlus,
  MessageCircle,
  MailCheck,
  PenTool,
  ClipboardCheck,
  TrendingUp,
  Brain,
  Copy,
  Check,
  ExternalLink,
  CheckCircle2,
  Loader2,
  Play,
  ArrowRight,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Pencil,
  Mail,
  Sun,
  Moon,
  Sunset,
  XCircle,
  Building2,
  User,
} from "lucide-react";
import {
  getTodayData,
  logOutcome,
  markDone,
  approveDraft,
  rejectDraft,
  testSendDraft,
  runAgent,
  updateNextAction,
  type TodayData,
  type TodayHotSignal,
  type TodayInteraction,
  type OutreachDraft,
  type LinkedInTask,
  type LinkedInActionItem,
  type LinkedInIntel,
  type ContentItem,
  type ProgressDetail,
} from "@/lib/api";
import { cn, TIER_LABELS, getPQSColor } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(d: Date): string {
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function interactionLabel(type: string): string {
  const labels: Record<string, string> = {
    email_replied: "replied to your email",
    email_opened: "opened your email",
    email_clicked: "clicked a link in your email",
    linkedin_message: "responded to your LinkedIn DM",
    linkedin_connection: "accepted your connection request",
  };
  return labels[type] ?? type.replace(/_/g, " ");
}

function getGreetingIcon() {
  const h = new Date().getHours();
  if (h < 12) return <Sun className="h-5 w-5 text-gray-400" />;
  if (h < 17) return <Sunset className="h-5 w-5 text-gray-400" />;
  return <Moon className="h-5 w-5 text-gray-400" />;
}

// ---------------------------------------------------------------------------
// CopyButton — with 2-second "Copied!" feedback
// ---------------------------------------------------------------------------

function CopyButton({ text, className }: { text: string; className?: string }) {
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
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all duration-200",
        copied
          ? "border-green-200 bg-green-50 text-green-700"
          : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-900",
        className
      )}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// IntelPanel — collapsible research/intel panel for LinkedIn cards
// ---------------------------------------------------------------------------

function IntelPanel({ intel }: { intel: LinkedInIntel | undefined }) {
  const [open, setOpen] = useState(false);

  if (!intel) return null;

  const hasAnyContent =
    intel.personalization_notes ||
    intel.research?.products_services?.length ||
    intel.research?.recent_news?.length ||
    intel.research?.pain_points?.length ||
    (intel.company?.pain_signals?.length ?? 0) > 0 ||
    intel.research?.known_systems?.length ||
    intel.contact?.title ||
    intel.contact?.seniority ||
    intel.contact?.city ||
    intel.contact?.state ||
    intel.company?.industry ||
    intel.company?.employee_count ||
    intel.company?.revenue_printed;

  if (!hasAnyContent) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {open ? "Hide Intel" : "View Intel"}
      </button>

      {open && (
        <div className="mt-2 rounded-lg bg-gray-50 border border-gray-200 p-3 text-xs space-y-3">
          {/* RESEARCH SUMMARY — full narrative from Perplexity/Claude research */}
          {intel.company?.research_summary && (
            <div>
              <div className="font-semibold text-gray-700 mb-1">RESEARCH SUMMARY</div>
              <p className="text-gray-600 whitespace-pre-wrap">{intel.company.research_summary}</p>
            </div>
          )}

          {/* KEY FINDINGS — structured research data */}
          {(intel.research || intel.company?.pain_signals?.length || intel.company?.personalization_hooks?.length) ? (
            <div>
              <div className="font-semibold text-gray-700 mb-1">KEY FINDINGS</div>
              <div className="space-y-1.5 text-gray-600">
                {intel.research?.company_description && (
                  <div><span className="font-medium text-gray-700">Description:</span> {intel.research.company_description}</div>
                )}
                {intel.research?.manufacturing_type && (
                  <div><span className="font-medium text-gray-700">Manufacturing Type:</span> {intel.research.manufacturing_type}</div>
                )}
                {(intel.research?.equipment_types?.length ?? 0) > 0 && (
                  <div><span className="font-medium text-gray-700">Equipment:</span> {intel.research!.equipment_types!.join(", ")}</div>
                )}
                {intel.research?.maintenance_approach && (
                  <div><span className="font-medium text-gray-700">Maintenance Approach:</span> {intel.research.maintenance_approach}</div>
                )}
                {intel.research?.iot_maturity && (
                  <div><span className="font-medium text-gray-700">IoT/Digital Maturity:</span> {intel.research.iot_maturity}</div>
                )}
                {((intel.research?.pain_points?.length ?? 0) > 0 ||
                  (intel.company?.pain_signals?.length ?? 0) > 0) && (
                  <div><span className="font-medium text-gray-700">Pain Points:</span>{(
                      intel.research?.pain_points ||
                      intel.company?.pain_signals ||
                      []
                    ).map((p: string, i: number) => <span key={i} className="block ml-3">• {p}</span>)}</div>
                )}
                {(intel.research?.opportunities?.length ?? 0) > 0 && (
                  <div><span className="font-medium text-gray-700">Opportunities:</span>{intel.research!.opportunities!.map((o: string, i: number) => <span key={i} className="block ml-3">• {o}</span>)}</div>
                )}
                {(intel.research?.known_systems?.length ?? 0) > 0 && (
                  <div><span className="font-medium text-gray-700">Known Systems/Tech:</span> {intel.research!.known_systems!.join(", ")}</div>
                )}
                {(intel.research?.existing_solutions?.length ?? 0) > 0 && (
                  <div><span className="font-medium text-gray-700">Existing Solutions:</span> {intel.research!.existing_solutions!.join(", ")}</div>
                )}
                {(intel.company?.personalization_hooks?.length ?? 0) > 0 && (
                  <div><span className="font-medium text-gray-700">Outreach Hooks:</span>{(intel.company!.personalization_hooks as string[]).map((h: string, i: number) => <span key={i} className="block ml-3">• {h}</span>)}</div>
                )}
                {intel.research?.confidence && (
                  <div><span className="font-medium text-gray-700">Research Confidence:</span> {intel.research.confidence}</div>
                )}
              </div>
            </div>
          ) : null}

          {/* CONTACT */}
          {(intel.contact?.title ||
            intel.contact?.seniority ||
            intel.contact?.city ||
            intel.contact?.state) && (
            <div>
              <div className="font-semibold text-gray-700 mb-1">CONTACT</div>
              <div className="space-y-0.5 text-gray-600">
                {intel.contact?.title && <p>Title: {intel.contact.title}</p>}
                {intel.contact?.seniority && (
                  <p>Seniority: {intel.contact.seniority}</p>
                )}
                {(intel.contact?.city || intel.contact?.state) && (
                  <p>
                    Location:{" "}
                    {[intel.contact.city, intel.contact.state]
                      .filter(Boolean)
                      .join(", ")}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* COMPANY */}
          {(intel.company?.industry ||
            intel.company?.employee_count ||
            intel.company?.revenue_printed ||
            intel.company?.headcount_growth_6m != null) && (
            <div>
              <div className="font-semibold text-gray-700 mb-1">COMPANY</div>
              <div className="space-y-0.5 text-gray-600">
                {intel.company?.industry && (
                  <p>Industry: {intel.company.industry}</p>
                )}
                {intel.company?.employee_count && (
                  <p>
                    Employees: {intel.company.employee_count.toLocaleString()}
                  </p>
                )}
                {intel.company?.revenue_printed && (
                  <p>Revenue: {intel.company.revenue_printed}</p>
                )}
                {intel.company?.headcount_growth_6m != null && (
                  <p>
                    Headcount growth (6mo):{" "}
                    {(intel.company.headcount_growth_6m * 100).toFixed(0)}%
                  </p>
                )}
                <p>
                  {intel.company?.is_public ? "Public" : "Private"}
                </p>
                <p>
                  Parent:{" "}
                  {intel.company?.parent_company_name || "Independent"}
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// InlineEditableMessage — edit message text in-place
// ---------------------------------------------------------------------------

function InlineEditableMessage({
  text,
  onSave,
}: {
  text: string;
  onSave: (t: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(text);

  if (editing) {
    return (
      <div className="mt-2 space-y-2">
        <textarea
          className="w-full rounded-md border border-gray-300 p-3 text-sm text-gray-700 leading-relaxed focus:border-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-300 resize-none"
          rows={4}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          autoFocus
        />
        <div className="flex gap-2">
          <button
            onClick={() => { onSave(val); setEditing(false); }}
            className="rounded-md bg-gray-900 px-3 py-1 text-xs font-medium text-white hover:bg-gray-800"
          >
            Save
          </button>
          <button
            onClick={() => { setVal(text); setEditing(false); }}
            className="rounded-md border border-gray-200 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2 group relative">
      <div className="rounded-md bg-gray-50 border border-gray-100 p-3 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
        {val}
      </div>
      <button
        onClick={() => setEditing(true)}
        className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 rounded-md border border-gray-200 bg-white p-1 text-gray-400 hover:text-gray-600 transition-opacity"
        title="Edit message"
      >
        <Pencil className="h-3 w-3" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function ProgressBar({
  completed,
  target,
  breakdown,
}: {
  completed: number;
  target: number;
  breakdown?: ProgressDetail["breakdown"];
}) {
  const pct = Math.min(100, Math.round((completed / Math.max(target, 1)) * 100));

  const barColor = "bg-gray-900";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {getGreetingIcon()}
          <div>
            <h2 className="text-sm font-semibold text-gray-900">
              Good morning, Avanish
            </h2>
            <p className="text-xs text-gray-400">{formatDate(new Date())}</p>
          </div>
        </div>
        <div className="text-right">
          <span className="text-2xl font-semibold text-gray-900 tabular-nums">
            {completed}
          </span>
          <span className="text-sm text-gray-400">/{target}</span>
          <p className="text-xs text-gray-400 mt-0.5">
            {pct >= 100 ? "Target hit" : `${target - completed} to go`}
          </p>
        </div>
      </div>

      {/* Main bar */}
      <div className="h-1.5 rounded-full bg-gray-200 overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-700", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Confetti flash at 100% */}
      {pct >= 100 && (
        <p className="mt-2 text-center text-xs font-medium text-green-600">
          All done for today — outstanding work!
        </p>
      )}

      {/* Breakdown row */}
      {breakdown && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            <UserPlus className="h-3.5 w-3.5 text-gray-400" />
            <span>
              <strong className="text-gray-700">{breakdown.linkedin_connections.done}</strong>
              /{breakdown.linkedin_connections.target} connections
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <MessageCircle className="h-3.5 w-3.5 text-gray-400" />
            <span>
              <strong className="text-gray-700">{breakdown.linkedin_dms.done}</strong>
              /{breakdown.linkedin_dms.target} DMs
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <MailCheck className="h-3.5 w-3.5 text-gray-400" />
            <span>
              <strong className="text-gray-700">{breakdown.emails_approved.done}</strong>
              /{breakdown.emails_approved.target} emails
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <ClipboardCheck className="h-3.5 w-3.5 text-gray-400" />
            <span>
              <strong className="text-gray-700">{breakdown.outcomes_logged.done}</strong>
              /{breakdown.outcomes_logged.target} outcomes
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <PenTool className="h-3.5 w-3.5 text-gray-400" />
            <span>
              <strong className="text-gray-700">{breakdown.content_posted.done}</strong>
              /{breakdown.content_posted.target} posts
            </span>
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionWrapper — collapsible section with header
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  flame: Flame,
  "user-plus": UserPlus,
  "message-circle": MessageCircle,
  "mail-check": MailCheck,
  "pen-tool": PenTool,
  "clipboard-check": ClipboardCheck,
  "trending-up": TrendingUp,
  brain: Brain,
};

function SectionWrapper({
  id,
  icon,
  title,
  subtitle,
  count,
  countDone,
  countTarget,
  defaultCollapsed,
  accentColor,
  children,
}: {
  id: string;
  icon: string;
  title: string;
  subtitle: string;
  count?: number;
  countDone?: number;
  countTarget?: number;
  defaultCollapsed?: boolean;
  accentColor?: string;
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed ?? false);
  const Icon = ICON_MAP[icon] ?? Flame;

  const progress =
    countTarget && countTarget > 0 && countDone !== undefined
      ? Math.round((countDone / countTarget) * 100)
      : null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      {/* Section header */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <Icon className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-medium uppercase tracking-widest text-gray-500">{title}</h3>
              {count !== undefined && (
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                    count === 0
                      ? "bg-gray-100 text-gray-400"
                      : "bg-gray-900 text-white"
                  )}
                >
                  {count}
                </span>
              )}
              {progress !== null && (
                <span className="text-[10px] font-medium text-gray-400">
                  {countDone}/{countTarget}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-0.5 truncate">{subtitle}</p>
          </div>
        </div>
        {collapsed ? (
          <ChevronDown className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
        ) : (
          <ChevronUp className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
        )}
      </button>

      {/* Progress mini-bar for sections with targets */}
      {!collapsed && progress !== null && (
        <div className="h-0.5 bg-gray-100">
          <div
            className="h-full bg-gray-900 transition-all duration-700"
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
      )}

      {/* Content */}
      {!collapsed && <div className="px-4 pb-4 pt-3 space-y-3">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HotSignalCard
// ---------------------------------------------------------------------------

const OUTCOME_OPTIONS = [
  { value: "interested", label: "Interested", cls: "bg-gray-900 hover:bg-gray-800" },
  { value: "not_now", label: "Not Now", cls: "bg-gray-100 hover:bg-gray-200 !text-gray-700" },
  { value: "not_interested", label: "Not Interested", cls: "bg-gray-100 hover:bg-gray-200 !text-gray-700" },
  { value: "wrong_person", label: "Wrong Person", cls: "bg-gray-100 hover:bg-gray-200 !text-gray-700" },
  { value: "meeting_booked", label: "Meeting Booked", cls: "bg-gray-900 hover:bg-gray-800" },
];

function HotSignalCard({
  signal,
  isDone,
  onDone,
}: {
  signal: TodayHotSignal;
  isDone: boolean;
  onDone: (id: string) => void;
}) {
  const [logging, setLogging] = useState(false);
  const [notes, setNotes] = useState("");
  const [showNotes, setShowNotes] = useState(false);
  const [pendingOutcome, setPendingOutcome] = useState<string | null>(null);
  const primaryContact = signal.contacts?.[0];

  const handleOutcome = async (outcome: string) => {
    setLogging(true);
    setPendingOutcome(outcome);
    try {
      await logOutcome({
        company_id: signal.id,
        contact_id: primaryContact?.id,
        channel: signal.last_interaction?.type.startsWith("linkedin") ? "linkedin" : "email",
        outcome,
        notes: notes || undefined,
      });
      onDone(signal.id);
    } catch (e) {
      console.error("Failed to log outcome:", e);
    } finally {
      setLogging(false);
      setPendingOutcome(null);
    }
  };

  return (
    <div
      className={cn(
        "rounded-lg border p-3.5 transition-all duration-300",
        isDone
          ? "opacity-40 border-gray-100 bg-gray-50"
          : "border-gray-200 bg-white"
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {signal.domain && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`https://logo.clearbit.com/${signal.domain}`}
                alt=""
                className="h-4 w-4 rounded shrink-0"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            )}
            <Link
              href={`/prospects/${signal.id}`}
              className="font-medium text-gray-900 hover:text-gray-600 text-sm"
            >
              {signal.name}
            </Link>
            {signal.tier && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">
                {TIER_LABELS[signal.tier] ?? signal.tier}
              </span>
            )}
            <span className={cn("text-xs font-medium text-gray-500")}>
              PQS {signal.pqs_total}
            </span>
          </div>

          {primaryContact && (
            <p className="mt-0.5 text-xs text-gray-500">
              {primaryContact.full_name}
              {primaryContact.title && (
                <span className="text-gray-400"> · {primaryContact.title}</span>
              )}
            </p>
          )}

          {signal.last_interaction && (
            <p className="mt-1.5 text-xs text-gray-600">
              <span className="font-medium">{interactionLabel(signal.last_interaction.type)}</span>{" "}
              <span className="text-gray-400">
                {formatTimeAgo(signal.last_interaction.created_at)}
              </span>
            </p>
          )}

          {signal.last_interaction?.body && signal.last_interaction.type === "email_replied" && (
            <p className="mt-2 rounded-md bg-gray-50 border border-gray-100 p-2.5 text-sm text-gray-700 line-clamp-2 italic">
              &ldquo;{signal.last_interaction.body}&rdquo;
            </p>
          )}
        </div>

        <Link
          href={`/prospects/${signal.id}`}
          className="shrink-0 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          View
        </Link>
      </div>

      {!isDone && (
        <div className="mt-3">
          {!showNotes ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-gray-500">Log outcome:</span>
              {OUTCOME_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => { setPendingOutcome(opt.value); setShowNotes(true); }}
                  disabled={logging}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium text-white transition-opacity disabled:opacity-50",
                    opt.cls
                  )}
                >
                  {logging && pendingOutcome === opt.value ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    opt.label
                  )}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 mt-2">
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Notes (optional)..."
                className="flex-1 rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-gray-400 focus:outline-none"
                onKeyDown={(e) => { if (e.key === "Enter" && pendingOutcome) handleOutcome(pendingOutcome); }}
                autoFocus
              />
              <button
                onClick={() => pendingOutcome && handleOutcome(pendingOutcome)}
                disabled={logging || !pendingOutcome}
                className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              >
                {logging ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                Save {pendingOutcome ? `(${OUTCOME_OPTIONS.find(o => o.value === pendingOutcome)?.label})` : ""}
              </button>
              <button
                onClick={() => { setShowNotes(false); setPendingOutcome(null); setNotes(""); }}
                className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs text-gray-500 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LinkedInConnectionCard
// ---------------------------------------------------------------------------

function LinkedInConnectionCard({
  item,
  isDone,
  onDone,
}: {
  item: LinkedInActionItem;
  isDone: boolean;
  onDone: (contactId: string) => void;
}) {
  const [msgText, setMsgText] = useState(
    item.message_text ??
      `Hi ${item.full_name?.split(" ")[0] ?? "there"}, I noticed you work at ${item.company_name ?? "your company"} — would love to connect and share some ideas around predictive maintenance for manufacturing.`
  );
  const [loading, setLoading] = useState(false);

  const actionId = item.contact_id;

  const handleSent = async () => {
    setLoading(true);
    try {
      await markDone({
        action_type: "linkedin_connection",
        contact_id: item.contact_id,
        company_id: item.company_id,
      });
      onDone(actionId);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-all duration-300",
        isDone ? "opacity-40 border-gray-100 bg-gray-50" : "border-gray-200 bg-white"
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {item.company_domain && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`https://logo.clearbit.com/${item.company_domain}`}
                alt=""
                className="h-4 w-4 rounded shrink-0"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            )}
            <span className="font-medium text-gray-900 text-sm">{item.full_name ?? "Unknown"}</span>
            {item.title && <span className="text-xs text-gray-500">{item.title}</span>}
            <span className="text-xs text-gray-300">·</span>
            <span className="text-xs text-gray-500">{item.company_name}</span>
            {item.company_tier && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                {TIER_LABELS[item.company_tier] ?? item.company_tier}
              </span>
            )}
            <span className="text-xs font-medium text-gray-400 ml-auto">
              PQS {item.pqs_total}
            </span>
          </div>

          <InlineEditableMessage text={msgText} onSave={setMsgText} />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <CopyButton text={msgText} />
        {item.linkedin_url && (
          <a
            href={item.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-blue-500 hover:bg-gray-50"
          >
            <ExternalLink className="h-3 w-3" />
            Open LinkedIn
          </a>
        )}
        <button
          onClick={handleSent}
          disabled={loading || isDone}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            isDone
              ? "bg-gray-100 text-gray-500"
              : "bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50"
          )}
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Check className="h-3 w-3" />
          )}
          {isDone ? "Sent" : "Mark Sent"}
        </button>
      </div>
      <IntelPanel intel={item.intel} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// LinkedInDMCard
// ---------------------------------------------------------------------------

function LinkedInDMCard({
  item,
  isDone,
  onDone,
}: {
  item: LinkedInActionItem;
  isDone: boolean;
  onDone: (contactId: string) => void;
}) {
  const [msgText, setMsgText] = useState(
    item.message_text ??
      `Hi ${item.full_name?.split(" ")[0] ?? "there"}, glad we're connected! I work with manufacturing companies on predictive maintenance — would love to share a quick insight relevant to ${item.company_name ?? "your team"}. Mind if I ask a quick question?`
  );
  const [loading, setLoading] = useState(false);

  const handleSent = async () => {
    setLoading(true);
    try {
      await markDone({
        action_type: "linkedin_dm",
        contact_id: item.contact_id,
        company_id: item.company_id,
      });
      onDone(item.contact_id);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-all duration-300",
        isDone ? "opacity-40 border-gray-100 bg-gray-50" : "border-gray-200 bg-white"
      )}
    >
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <span className="font-medium text-gray-900 text-sm">{item.full_name ?? "Unknown"}</span>
        {item.title && <span className="text-xs text-gray-500">{item.title}</span>}
        <span className="text-xs text-gray-300">·</span>
        <span className="text-xs text-gray-500">{item.company_name}</span>
        <span className="ml-auto text-xs text-gray-400 font-medium">Connected</span>
      </div>

      <InlineEditableMessage text={msgText} onSave={setMsgText} />

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <CopyButton text={msgText} />
        {item.linkedin_url && (
          <a
            href={item.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-blue-500 hover:bg-gray-50"
          >
            <ExternalLink className="h-3 w-3" />
            Open LinkedIn
          </a>
        )}
        <button
          onClick={handleSent}
          disabled={loading || isDone}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            isDone
              ? "bg-gray-100 text-gray-500"
              : "bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-50"
          )}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          {isDone ? "Sent" : "Mark Sent"}
        </button>
      </div>
      <IntelPanel intel={item.intel} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ApprovalCard
// ---------------------------------------------------------------------------

function ApprovalCard({
  draft,
  isDone,
  onDone,
}: {
  draft: OutreachDraft;
  isDone: boolean;
  onDone: (id: string, action: "approve" | "reject") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [testSending, setTestSending] = useState(false);
  const [testMsg, setTestMsg] = useState<string | null>(null);

  const handleApprove = async () => {
    setLoading(true);
    try {
      await approveDraft(draft.id);
      onDone(draft.id, "approve");
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    setLoading(true);
    try {
      await rejectDraft(draft.id, "Rejected from Daily Cockpit");
      onDone(draft.id, "reject");
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleTestSend = async () => {
    setTestSending(true);
    setTestMsg(null);
    try {
      const res = await testSendDraft(draft.id, "avi@digitillis.com");
      setTestMsg(res.message);
      setTimeout(() => setTestMsg(null), 5000);
    } catch (e) {
      setTestMsg(e instanceof Error ? e.message : "Failed");
    } finally {
      setTestSending(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-all duration-300",
        isDone ? "opacity-40 border-gray-100 bg-gray-50" : "border-gray-200 bg-white"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-gray-900">{draft.companies?.name ?? "Unknown"}</span>
            {draft.companies?.tier && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">
                {TIER_LABELS[draft.companies.tier] ?? draft.companies.tier}
              </span>
            )}
            <span className={cn("text-sm font-bold", getPQSColor(draft.companies?.pqs_total ?? 0))}>
              PQS {draft.companies?.pqs_total ?? 0}
            </span>
            {draft.contacts?.full_name && (
              <span className="text-sm text-gray-500">· {draft.contacts.full_name}</span>
            )}
          </div>
          <p className="mt-1 text-sm font-medium text-gray-800">{draft.subject}</p>
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="shrink-0 text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide" : "Preview"}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
          {draft.body}
        </div>
      )}

      {!isDone && (
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <button
            onClick={handleApprove}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
            Approve
          </button>
          <button
            onClick={handleReject}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 disabled:opacity-50"
          >
            <XCircle className="h-3 w-3" />
            Reject
          </button>
          <Link
            href="/approvals"
            className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            <Pencil className="h-3 w-3" />
            Edit
          </Link>
          <button
            onClick={handleTestSend}
            disabled={testSending}
            className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            {testSending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Mail className="h-3 w-3" />}
            Test Send
          </button>
          {testMsg && (
            <span className={cn("text-xs font-medium", testMsg.startsWith("Test email sent") ? "text-green-600" : "text-gray-500")}>
              {testMsg}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ContentCard
// ---------------------------------------------------------------------------

function ContentCard({
  item,
  isDone,
  onDone,
}: {
  item: ContentItem;
  isDone: boolean;
  onDone: (id: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(item.post_text);
    } catch {
      /* ignore */
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleMarkPosted = () => {
    if (item.draft_id) onDone(item.draft_id);
  };

  return (
    <div
      className={cn(
        "rounded-lg border p-3.5 transition-all duration-300",
        isDone ? "opacity-40 border-gray-100 bg-gray-50" : "border-gray-200 bg-white"
      )}
    >
      <div className="flex items-center gap-2 mb-2">
        <PenTool className="h-3.5 w-3.5 text-gray-400" />
        <span className="font-medium text-gray-900 text-sm">{item.topic}</span>
        {item.approval_status === "approved" && (
          <span className="rounded bg-gray-100 text-gray-500 px-1.5 py-0.5 text-[10px] font-medium">Approved</span>
        )}
      </div>
      <div className="rounded-md bg-gray-50 border border-gray-100 p-3 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
        {item.post_text}
      </div>
      {!isDone && (
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={handleCopy}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-all",
              copied ? "border-green-200 bg-white text-green-600" : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
            )}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied!" : "Copy Post"}
          </button>
          <a
            href="https://www.linkedin.com/post/new/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-blue-500 hover:bg-gray-50"
          >
            <ExternalLink className="h-3 w-3" />
            Open LinkedIn
          </a>
          <button
            onClick={handleMarkPosted}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-800"
          >
            <CheckCircle2 className="h-3 w-3" />
            Mark Posted
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OutcomeLoggerCard
// ---------------------------------------------------------------------------

function OutcomeLoggerCard({
  interaction,
  isDone,
  onDone,
}: {
  interaction: TodayInteraction;
  isDone: boolean;
  onDone: (id: string) => void;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const channel = interaction.type.startsWith("linkedin") ? "linkedin" : "email";

  const outcomes =
    channel === "linkedin"
      ? [
          { value: "interested", label: "Interested", cls: "border-gray-300 bg-gray-900 text-white hover:bg-gray-800" },
          { value: "not_now", label: "Not Now", cls: "border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200" },
          { value: "not_interested", label: "Not Interested", cls: "border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200" },
          { value: "meeting_booked", label: "Meeting Booked", cls: "border-gray-300 bg-gray-900 text-white hover:bg-gray-800" },
        ]
      : [
          { value: "interested", label: "Interested", cls: "border-gray-300 bg-gray-900 text-white hover:bg-gray-800" },
          { value: "not_now", label: "Not Now", cls: "border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200" },
          { value: "not_interested", label: "Not Interested", cls: "border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200" },
          { value: "wrong_person", label: "Wrong Person", cls: "border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200" },
          { value: "bounce", label: "Bounce", cls: "border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200" },
          { value: "meeting_booked", label: "Meeting Booked", cls: "border-gray-300 bg-gray-900 text-white hover:bg-gray-800" },
        ];

  const handleSave = async () => {
    if (!selectedOutcome || !interaction.company_id) return;
    setSaving(true);
    try {
      await logOutcome({
        company_id: interaction.company_id,
        contact_id: interaction.contact_id,
        channel,
        outcome: selectedOutcome,
        notes: notes || undefined,
      });
      onDone(interaction.id);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-all duration-300",
        isDone ? "opacity-40 border-gray-100 bg-gray-50" : "border-gray-200 bg-white"
      )}
    >
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Building2 className="h-4 w-4 text-gray-400" />
        <span className="font-medium text-gray-900">
          {interaction.companies?.name ?? "Unknown Company"}
        </span>
        {interaction.contacts?.full_name && (
          <>
            <span className="text-gray-300">·</span>
            <User className="h-3.5 w-3.5 text-gray-400" />
            <span className="text-sm text-gray-600">{interaction.contacts.full_name}</span>
          </>
        )}
        <span className="ml-auto text-xs text-gray-400">
          {interactionLabel(interaction.type)} · {formatTimeAgo(interaction.created_at)}
        </span>
      </div>

      {!isDone && (
        <>
          <div className="flex flex-wrap gap-2">
            {outcomes.map((o) => (
              <button
                key={o.value}
                onClick={() => setSelectedOutcome(o.value)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-xs font-medium transition-all",
                  o.cls,
                  selectedOutcome === o.value ? "ring-2 ring-offset-1 ring-current" : ""
                )}
              >
                {o.label}
              </button>
            ))}
          </div>

          {selectedOutcome && (
            <div className="mt-3 flex items-center gap-2">
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Notes (optional)..."
                className="flex-1 rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-300"
                onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
              />
              <button
                onClick={handleSave}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                Save
              </button>
            </div>
          )}
        </>
      )}

      {isDone && (
        <p className="text-sm text-green-600 flex items-center gap-1.5">
          <Check className="h-3.5 w-3.5" /> Outcome logged
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PipelineRow
// ---------------------------------------------------------------------------

interface PipelineRowProps {
  label: string;
  count: number;
  nextAction?: string;
  agentName?: string;
  agentLabel?: string;
  limit?: number;
}

function PipelineRow({ label, count, nextAction, agentName, agentLabel, limit = 10 }: PipelineRowProps) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const handleRun = async () => {
    if (!agentName) return;
    setRunning(true);
    setResult(null);
    try {
      await runAgent(agentName, { limit });
      setResult("✓ Started");
      setTimeout(() => setResult(null), 4000);
    } catch (e) {
      setResult(e instanceof Error ? e.message : "Error");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <div className="flex items-center gap-3">
        <span className="text-2xl font-bold text-gray-900 tabular-nums w-12 text-right">{count}</span>
        <span className="text-sm text-gray-600">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {result && <span className="text-xs font-medium text-green-600">{result}</span>}
        {agentName && count > 0 ? (
          <button
            onClick={handleRun}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            {agentLabel ?? `Run (${limit})`}
          </button>
        ) : nextAction ? (
          <Link
            href={nextAction}
            className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            Go <ArrowRight className="h-3 w-3" />
          </Link>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// NextActionCard — AI-recommended next action from contact_events
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function NextActionCard({ action, onDone, onSkip }: { action: any; onDone: (id: string) => void; onSkip: (id: string) => void }) {
  const [copied, setCopied] = useState(false);

  // Supabase joins may return arrays or objects depending on cardinality
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let contact: any = action.contacts || {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let company: any = action.companies || {};
  if (Array.isArray(contact)) contact = contact[0] || {};
  if (Array.isArray(company)) company = company[0] || {};

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3.5">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm text-gray-900">{contact.full_name || "Unknown contact"}</span>
          {contact.title && (
            <span className="text-xs text-gray-500">{contact.title}</span>
          )}
          {company.name && (
            <>
              <span className="text-xs text-gray-400">·</span>
              <span className="text-xs text-gray-500">{company.name}</span>
            </>
          )}
        </div>
        {action.next_action_date && (
          <span className="text-xs text-gray-500 font-medium">Due: {action.next_action_date}</span>
        )}
      </div>

      {/* What triggered this */}
      <div className="text-xs text-gray-400 mb-2">
        Based on:{" "}
        {action.event_type === "response_received" ? "Their response" : (action.event_type || "event").replace(/_/g, " ")}
        {action.sentiment && ` (${action.sentiment})`}
        {action.channel && ` via ${action.channel}`}
      </div>

      {/* The recommendation */}
      <div className="bg-gray-50 rounded-md p-3 border border-gray-100 mb-2">
        <p className="text-sm text-gray-700">{action.next_action}</p>
      </div>

      {/* Suggested message */}
      {action.suggested_message && (
        <div className="bg-gray-50 rounded-md p-3 border border-gray-100 mb-2">
          <div className="text-xs font-medium text-gray-500 mb-1">Suggested message:</div>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{action.suggested_message}</p>
          <button
            onClick={() => {
              navigator.clipboard.writeText(action.suggested_message).catch(() => {
                const el = document.createElement("textarea");
                el.value = action.suggested_message;
                document.body.appendChild(el);
                el.select();
                document.execCommand("copy");
                document.body.removeChild(el);
              });
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
            className="mt-2 flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
          >
            {copied ? <span className="text-green-600">Copied!</span> : "Copy message"}
          </button>
        </div>
      )}

      {/* Reasoning (collapsible) */}
      {action.action_reasoning && (
        <details className="text-xs text-gray-400 mb-2">
          <summary className="cursor-pointer hover:text-gray-600">Why this recommendation</summary>
          <p className="mt-1 pl-2 border-l-2 border-gray-200 text-gray-500">{action.action_reasoning}</p>
        </details>
      )}

      {/* Actions */}
      <div className="flex gap-2 flex-wrap mt-2">
        {contact.linkedin_url && (
          <a
            href={contact.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="px-2.5 py-1 text-xs border border-gray-200 text-blue-500 rounded-md hover:bg-gray-50"
          >
            Open LinkedIn
          </a>
        )}
        <button
          onClick={() => onDone(action.id)}
          className="px-2.5 py-1 text-xs bg-gray-900 text-white rounded-md hover:bg-gray-800"
        >
          Done
        </button>
        <button
          onClick={() => onSkip(action.id)}
          className="px-2.5 py-1 text-xs bg-gray-100 text-gray-600 rounded-md hover:bg-gray-200"
        >
          Skip
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TodayCockpitPage() {
  const [data, setData] = useState<TodayData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Optimistic "done" sets — keyed by item id
  const [doneHotSignals, setDoneHotSignals] = useState<Set<string>>(new Set());
  const [doneConnections, setDoneConnections] = useState<Set<string>>(new Set());
  const [doneDMs, setDoneDMs] = useState<Set<string>>(new Set());
  const [doneApprovals, setDoneApprovals] = useState<Set<string>>(new Set());
  const [doneContent, setDoneContent] = useState<Set<string>>(new Set());
  const [doneOutcomes, setDoneOutcomes] = useState<Set<string>>(new Set());
  const [doneNextActions, setDoneNextActions] = useState<Set<string>>(new Set());

  // Local progress delta (optimistic)
  const [localExtraDone, setLocalExtraDone] = useState(0);

  const fetchData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const res = await getTodayData();
      setData(res.data);
      setLastRefresh(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load today's data");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 30 seconds (silent, no spinner)
  useEffect(() => {
    const interval = setInterval(() => fetchData(true), 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Optimistic helpers
  const markHotSignalDone = (id: string) => {
    setDoneHotSignals((prev) => new Set([...prev, id]));
    setLocalExtraDone((n) => n + 1);
  };
  const markConnectionDone = (id: string) => {
    setDoneConnections((prev) => new Set([...prev, id]));
    setLocalExtraDone((n) => n + 1);
  };
  const markDMDone = (id: string) => {
    setDoneDMs((prev) => new Set([...prev, id]));
    setLocalExtraDone((n) => n + 1);
  };
  const markApprovalDone = (id: string, _action: "approve" | "reject") => {
    setDoneApprovals((prev) => new Set([...prev, id]));
    setLocalExtraDone((n) => n + 1);
  };
  const markContentDone = (id: string) => {
    setDoneContent((prev) => new Set([...prev, id]));
    setLocalExtraDone((n) => n + 1);
  };
  const markOutcomeDone = (id: string) => {
    setDoneOutcomes((prev) => new Set([...prev, id]));
    setLocalExtraDone((n) => n + 1);
  };

  const handleNextActionDone = async (eventId: string) => {
    // Optimistic update first
    setDoneNextActions((prev) => new Set([...prev, eventId]));
    setLocalExtraDone((n) => n + 1);
    try {
      await updateNextAction(eventId, "done");
      fetchData(true); // Refresh in background
    } catch (e) {
      console.error("Failed to mark action done:", e);
      // Revert optimistic update on error
      setDoneNextActions((prev) => { const s = new Set(prev); s.delete(eventId); return s; });
      setLocalExtraDone((n) => n - 1);
    }
  };

  const handleNextActionSkip = async (eventId: string) => {
    // Optimistic update first
    setDoneNextActions((prev) => new Set([...prev, eventId]));
    try {
      await updateNextAction(eventId, "skipped");
      fetchData(true); // Refresh in background
    } catch (e) {
      console.error("Failed to skip action:", e);
      // Revert optimistic update on error
      setDoneNextActions((prev) => { const s = new Set(prev); s.delete(eventId); return s; });
    }
  };

  if (loading && !data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        <span className="ml-3 text-sm text-gray-400">Loading your day...</span>
      </div>
    );
  }

  // Data from API
  const hotSignals = data?.hot_signals ?? [];
  const pendingApprovals = data?.pending_approvals ?? [];
  const pipelineSummary = data?.pipeline_summary ?? {};
  const recentInteractions = data?.recent_interactions ?? [];
  const progressDetail = data?.progress_detail;
  const pendingNextActions = (data?.pending_next_actions ?? []).filter((a) => !doneNextActions.has(a.id));

  // LinkedIn items from daily_plan sections
  const linkedInConnectSection = data?.daily_plan?.sections.find((s) => s.id === "linkedin_connect");
  const linkedInDMSection = data?.daily_plan?.sections.find((s) => s.id === "linkedin_dm");
  const contentSection = data?.daily_plan?.sections.find((s) => s.id === "content");

  const connectItems: LinkedInActionItem[] = linkedInConnectSection?.items ?? [];
  const dmItems: LinkedInActionItem[] = linkedInDMSection?.items ?? [];
  const contentItems: ContentItem[] = contentSection?.items ?? [];

  // Computed progress
  const baseCompleted = progressDetail?.completed ?? data?.progress.completed ?? 0;
  const target = progressDetail?.target ?? data?.progress.target ?? 20;
  const completed = Math.min(target, baseCompleted + localExtraDone);

  // Live breakdown (merge optimistic)
  const breakdown = progressDetail?.breakdown
    ? {
        linkedin_connections: {
          done: (progressDetail.breakdown.linkedin_connections.done ?? 0) + doneConnections.size,
          target: progressDetail.breakdown.linkedin_connections.target,
        },
        linkedin_dms: {
          done: (progressDetail.breakdown.linkedin_dms.done ?? 0) + doneDMs.size,
          target: progressDetail.breakdown.linkedin_dms.target,
        },
        emails_approved: {
          done: (progressDetail.breakdown.emails_approved.done ?? 0) + doneApprovals.size,
          target: progressDetail.breakdown.emails_approved.target,
        },
        outcomes_logged: {
          done: (progressDetail.breakdown.outcomes_logged.done ?? 0) + doneOutcomes.size,
          target: progressDetail.breakdown.outcomes_logged.target,
        },
        content_posted: {
          done: (progressDetail.breakdown.content_posted.done ?? 0) + doneContent.size,
          target: progressDetail.breakdown.content_posted.target,
        },
      }
    : undefined;

  // Counts that appear in section headers (subtract already-done items)
  const urgentCount = hotSignals.filter((s) => !doneHotSignals.has(s.id)).length;
  const connectCount = connectItems.filter((i) => !doneConnections.has(i.contact_id)).length;
  const connectDone = (linkedInConnectSection?.completed ?? 0) + doneConnections.size;
  const connectTarget = linkedInConnectSection?.target ?? 10;
  const dmCount = dmItems.filter((i) => !doneDMs.has(i.contact_id)).length;
  const approvalsCount = pendingApprovals.filter((d) => !doneApprovals.has(d.id)).length;
  const contentCount = contentItems.filter((c) => !doneContent.has(c.draft_id ?? "")).length;
  const outcomesCount = recentInteractions.filter((i) => !doneOutcomes.has(i.id)).length;

  return (
    <div className="space-y-3 pb-16 max-w-4xl mx-auto">
      {/* ------------------------------------------------------------------ */}
      {/* PROGRESS BAR + HEADER                                               */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {pendingNextActions.length > 0 && (
            <span className="flex items-center gap-1 rounded bg-gray-100 px-2 py-1 font-medium text-gray-600">
              <Brain className="h-3 w-3 text-gray-400" />
              {pendingNextActions.length} AI action{pendingNextActions.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          {lastRefresh && (
            <span>Updated {formatTimeAgo(lastRefresh.toISOString())}</span>
          )}
          <button
            onClick={() => fetchData()}
            disabled={loading}
            className="flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-50 disabled:opacity-40"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
          {error}
        </div>
      )}

      <ProgressBar completed={completed} target={target} breakdown={breakdown} />

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 1: RESPOND NOW                                              */}
      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="urgent"
        icon="flame"
        title="Respond Now"
        subtitle="Hot signals and replies that need immediate attention"
        count={urgentCount}
        defaultCollapsed={urgentCount === 0}
      >
        {urgentCount === 0 ? (
          <p className="py-4 text-center text-sm text-gray-400">
            No urgent signals right now. Check back throughout the day.
          </p>
        ) : (
          hotSignals.map((signal) => (
            <HotSignalCard
              key={signal.id}
              signal={signal}
              isDone={doneHotSignals.has(signal.id)}
              onDone={markHotSignalDone}
            />
          ))
        )}
      </SectionWrapper>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 2: AI-RECOMMENDED NEXT ACTIONS                              */}
      {/* ------------------------------------------------------------------ */}
      {(data?.pending_next_actions?.length ?? 0) > 0 && (
        <SectionWrapper
          id="next_actions"
          icon="brain"
          title="AI-Recommended Actions"
          subtitle={`${pendingNextActions.length} action${pendingNextActions.length !== 1 ? "s" : ""} due today`}
          count={pendingNextActions.length}
          defaultCollapsed={pendingNextActions.length === 0}
        >
          {pendingNextActions.length === 0 ? (
            <p className="py-4 text-center text-sm text-gray-400">
              All AI-recommended actions are done for today.
            </p>
          ) : (
            <div className="space-y-3">
              {pendingNextActions.map((action) => (
                <NextActionCard
                  key={action.id}
                  action={action}
                  onDone={handleNextActionDone}
                  onSkip={handleNextActionSkip}
                />
              ))}
            </div>
          )}
        </SectionWrapper>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 3: SEND CONNECTION REQUESTS                                 */}
      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="linkedin_connect"
        icon="user-plus"
        title="Send Connection Requests"
        subtitle={`Target: 10/day — ${connectDone} done today`}
        count={connectCount}
        countDone={connectDone}
        countTarget={connectTarget}
        defaultCollapsed={connectCount === 0}
      >
        {connectCount === 0 && connectItems.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-400">
            No contacts queued for connection requests.{" "}
            <Link href="/actions" className="text-gray-600 underline hover:text-gray-900">
              Run LinkedIn outreach
            </Link>{" "}
            to generate messages.
          </p>
        ) : connectItems.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-500">
            All {connectDone} connection requests sent today.
          </p>
        ) : (
          connectItems.map((item) => (
            <LinkedInConnectionCard
              key={item.contact_id}
              item={item}
              isDone={doneConnections.has(item.contact_id)}
              onDone={markConnectionDone}
            />
          ))
        )}
      </SectionWrapper>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 3: SEND OPENING DMs                                         */}
      {/* ------------------------------------------------------------------ */}
      {/* SECTION: MARK ACCEPTANCES                                          */}
      {/* ------------------------------------------------------------------ */}
      {(data?.pending_acceptances?.length ?? 0) > 0 && (
        <SectionWrapper
          id="mark_acceptances"
          icon="user-check"
          title="Mark Acceptances"
          subtitle="Check LinkedIn — did any of these prospects accept your connection?"
          count={data?.pending_acceptances?.length ?? 0}
          defaultCollapsed={false}
        >
          {data!.pending_acceptances!.map((c: any) => (
            <div
              key={c.contact_id}
              className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-3 mb-2"
            >
              <div className="flex-1 min-w-0">
                <span className="font-medium text-sm text-gray-900">
                  {c.full_name}
                </span>
                <span className="ml-2 text-xs text-gray-500">
                  {c.title} · {c.company_name}
                </span>
                {c.linkedin_url && (
                  <a
                    href={c.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-2 text-xs text-blue-500 hover:underline inline-flex items-center gap-1"
                  >
                    Open LinkedIn
                  </a>
                )}
              </div>
              <div className="flex gap-2 ml-3 shrink-0">
                <button
                  onClick={async () => {
                    try {
                      await markDone({
                        action_type: "connection_accepted",
                        contact_id: c.contact_id,
                        company_id: c.company_id,
                      });
                      fetchData(true);
                    } catch {}
                  }}
                  className="rounded-md bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700"
                >
                  Accepted
                </button>
                <button
                  onClick={async () => {
                    try {
                      await markDone({
                        action_type: "connection_ignored",
                        contact_id: c.contact_id,
                        company_id: c.company_id,
                      });
                      fetchData(true);
                    } catch {}
                  }}
                  className="rounded-md bg-gray-200 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-300"
                >
                  Ignored
                </button>
              </div>
            </div>
          ))}
        </SectionWrapper>
      )}

      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="linkedin_dm"
        icon="message-circle"
        title="Send Opening DMs"
        subtitle="Connections who accepted 2+ days ago — start conversations"
        count={dmCount}
        defaultCollapsed={dmCount === 0}
      >
        {dmItems.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-400">
            No accepted connections awaiting DMs.
          </p>
        ) : (
          dmItems.map((item) => (
            <LinkedInDMCard
              key={item.contact_id}
              item={item}
              isDone={doneDMs.has(item.contact_id)}
              onDone={markDMDone}
            />
          ))
        )}
      </SectionWrapper>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 4: APPROVE EMAILS                                           */}
      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="approve_emails"
        icon="mail-check"
        title="Review & Approve Emails"
        subtitle={`${approvalsCount} draft${approvalsCount !== 1 ? "s" : ""} waiting for your review`}
        count={approvalsCount}
        defaultCollapsed={approvalsCount === 0}
      >
        {pendingApprovals.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-400">
            No pending drafts.{" "}
            <Link href="/actions" className="text-gray-600 underline hover:text-gray-900">
              Run Outreach
            </Link>{" "}
            to generate new ones.
          </p>
        ) : (
          <>
            {pendingApprovals.map((draft) => (
              <ApprovalCard
                key={draft.id}
                draft={draft}
                isDone={doneApprovals.has(draft.id)}
                onDone={markApprovalDone}
              />
            ))}
            <Link
              href="/approvals"
              className="flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-gray-200 py-3 text-xs text-gray-500 hover:bg-gray-50"
            >
              View all in Approvals <ArrowRight className="h-3 w-3" />
            </Link>
          </>
        )}
      </SectionWrapper>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 5: POST TODAY'S CONTENT                                     */}
      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="content"
        icon="pen-tool"
        title="Post Today's Content"
        subtitle="Thought leadership for LinkedIn"
        count={contentCount}
        defaultCollapsed={contentItems.length === 0}
      >
        {contentItems.length === 0 ? (
          <div className="py-4 text-center">
            <p className="text-sm text-gray-400 mb-3">No content draft ready for today.</p>
            <Link
              href="/actions"
              className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
            >
              <PenTool className="h-3.5 w-3.5" />
              Generate Content
            </Link>
          </div>
        ) : (
          contentItems.map((item) => (
            <ContentCard
              key={item.draft_id ?? item.topic}
              item={item}
              isDone={doneContent.has(item.draft_id ?? "")}
              onDone={markContentDone}
            />
          ))
        )}
      </SectionWrapper>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 6: LOG RESPONSES                                            */}
      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="log_outcomes"
        icon="clipboard-check"
        title="Log Responses"
        subtitle="Record outcomes from recent outreach"
        count={outcomesCount}
        defaultCollapsed={outcomesCount === 0}
      >
        {recentInteractions.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-400">
            No interactions to log in the last 24 hours.
          </p>
        ) : (
          <>
            {recentInteractions.map((interaction) => (
              <OutcomeLoggerCard
                key={interaction.id}
                interaction={interaction}
                isDone={doneOutcomes.has(interaction.id)}
                onDone={markOutcomeDone}
              />
            ))}
            <p className="pt-1 text-center text-xs text-gray-400">
              Had a conversation not tracked here?{" "}
              <Link href="/prospects?status=engaged" className="text-gray-600 underline hover:text-gray-900">
                Find the prospect
              </Link>{" "}
              and log it manually.
            </p>
          </>
        )}
      </SectionWrapper>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 7: GROW PIPELINE                                            */}
      {/* ------------------------------------------------------------------ */}
      <SectionWrapper
        id="pipeline"
        icon="trending-up"
        title="Grow Pipeline"
        subtitle="Run discovery, research, and qualification"
        defaultCollapsed={false}
      >
        <div className="rounded-md border border-gray-100 px-4 py-1">
          <PipelineRow
            label="discovered — waiting for research"
            count={pipelineSummary["discovered"] ?? 0}
            agentName="research"
            agentLabel="Run Research: 10"
            limit={10}
          />
          <PipelineRow
            label="researched — waiting for qualification"
            count={pipelineSummary["researched"] ?? 0}
            agentName="qualification"
            agentLabel="Run Qualification"
          />
          <PipelineRow
            label="qualified — waiting for enrichment"
            count={pipelineSummary["qualified"] ?? 0}
            agentName="enrichment"
            agentLabel="Run Enrichment"
          />
          <PipelineRow
            label="outreach pending — drafts to approve"
            count={pipelineSummary["outreach_pending"] ?? approvalsCount}
            nextAction="/approvals"
          />
          <PipelineRow
            label="contacted — no reply yet"
            count={pipelineSummary["contacted"] ?? 0}
            nextAction="/prospects?status=contacted"
          />
        </div>
      </SectionWrapper>
    </div>
  );
}
