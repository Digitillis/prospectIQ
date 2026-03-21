"use client";

/**
 * Daily Cockpit — Morning command center for Avanish
 *
 * Opens every morning. Shows exactly what to do today, in priority order,
 * with messages pre-written and ready to copy/send.
 *
 * Sections:
 *   1. URGENT    — Hot signals, replies needing immediate action
 *   2. APPROVE   — Email drafts pending approval (inline)
 *   3. LINKEDIN  — Today's connection requests, opening DMs, follow-up DMs
 *   4. PIPELINE  — Quick one-click pipeline actions
 *   5. LOG       — Outcome logging for recent interactions
 */

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  Zap,
  Mail,
  Linkedin,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Pencil,
  Loader2,
  Play,
  ArrowRight,
  RefreshCw,
  MessageSquare,
  AlertCircle,
  Building2,
  User,
  Sun,
} from "lucide-react";
import {
  getTodayData,
  logOutcome,
  markDone,
  approveDraft,
  rejectDraft,
  testSendDraft,
  runAgent,
  type TodayData,
  type TodayHotSignal,
  type TodayInteraction,
  type OutreachDraft,
  type LinkedInTask,
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
  });
}

function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
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

// ---------------------------------------------------------------------------
// CopyButton — single click copy with checkmark feedback
// ---------------------------------------------------------------------------

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback for non-secure contexts
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium transition-colors",
        copied
          ? "border-green-200 bg-green-50 text-green-700"
          : "bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-900",
        className
      )}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied!" : "📋 Copy"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// MetricCard
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  icon: Icon,
  color,
  subtext,
}: {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  subtext?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500">{label}</p>
        <div className={cn("rounded-lg p-2", color)}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
      {subtext && <p className="mt-0.5 text-xs text-gray-400">{subtext}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionHeader
// ---------------------------------------------------------------------------

function SectionHeader({
  icon: Icon,
  title,
  count,
  badge,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  count?: number;
  badge?: "urgent" | "info" | "success";
}) {
  const badgeClasses = {
    urgent: "bg-red-100 text-red-700",
    info: "bg-blue-100 text-digitillis-accent",
    success: "bg-green-100 text-green-700",
  };
  return (
    <div className="flex items-center gap-3 border-b border-gray-100 pb-3">
      <Icon className="h-5 w-5 text-gray-500" />
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {count !== undefined && (
        <span
          className={cn(
            "rounded-full px-2.5 py-0.5 text-xs font-medium",
            badge ? badgeClasses[badge] : "bg-gray-100 text-gray-600"
          )}
        >
          {count}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 1: Hot Signals
// ---------------------------------------------------------------------------

const OUTCOME_OPTIONS = [
  { value: "interested", label: "Interested ✓", cls: "bg-green-600" },
  { value: "not_now", label: "Not Now", cls: "bg-amber-500" },
  { value: "not_interested", label: "Not Interested", cls: "bg-red-600" },
  { value: "wrong_person", label: "Wrong Person", cls: "bg-gray-600" },
  { value: "meeting_booked", label: "Meeting Booked 🎉", cls: "bg-digitillis-accent" },
];

function HotSignalCard({
  signal,
  onOutcomeLogged,
}: {
  signal: TodayHotSignal;
  onOutcomeLogged: () => void;
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [loggingOutcome, setLoggingOutcome] = useState(false);
  const [notes, setNotes] = useState("");
  const [showNotes, setShowNotes] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const primaryContact = signal.contacts?.[0];

  const handleOutcome = async (outcome: string) => {
    setLoggingOutcome(true);
    setDropdownOpen(false);
    try {
      await logOutcome({
        company_id: signal.id,
        contact_id: primaryContact?.id,
        channel: signal.last_interaction?.type.startsWith("linkedin") ? "linkedin" : "email",
        outcome,
        notes: notes || undefined,
      });
      onOutcomeLogged();
    } catch (e) {
      console.error("Failed to log outcome:", e);
    } finally {
      setLoggingOutcome(false);
    }
  };

  return (
    <div className="rounded-xl border border-orange-100 bg-orange-50 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {signal.domain && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`https://logo.clearbit.com/${signal.domain}`}
                alt=""
                className="h-5 w-5 shrink-0 rounded"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            )}
            <Link
              href={`/prospects/${signal.id}`}
              className="font-semibold text-gray-900 hover:text-digitillis-accent"
            >
              {signal.name}
            </Link>
            {signal.tier && (
              <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                {TIER_LABELS[signal.tier] ?? signal.tier}
              </span>
            )}
            <span className={cn("text-sm font-bold", getPQSColor(signal.pqs_total))}>
              PQS {signal.pqs_total}
            </span>
          </div>

          {primaryContact && (
            <p className="mt-1 text-sm text-gray-600">
              {primaryContact.full_name}
              {primaryContact.title && (
                <span className="text-gray-400"> · {primaryContact.title}</span>
              )}
            </p>
          )}

          {signal.last_interaction && (
            <p className="mt-1.5 text-sm text-orange-800">
              🔥 {primaryContact?.full_name ?? "Contact"}{" "}
              <span className="font-medium">{interactionLabel(signal.last_interaction.type)}</span>
              {" "}
              <span className="text-gray-400 text-xs">
                {formatTimeAgo(signal.last_interaction.created_at)}
              </span>
            </p>
          )}

          {signal.last_interaction?.body && signal.last_interaction.type === "email_replied" && (
            <p className="mt-1.5 rounded-lg bg-white border border-orange-100 p-2.5 text-sm text-gray-700 line-clamp-2 italic">
              "{signal.last_interaction.body}"
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Link
            href={`/prospects/${signal.id}`}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            View
          </Link>

          {/* Log Outcome dropdown */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen((o) => !o)}
              disabled={loggingOutcome}
              className="inline-flex items-center gap-1 rounded-lg bg-digitillis-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {loggingOutcome ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Log Outcome
              <ChevronDown className="h-3 w-3" />
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 w-52 rounded-xl border border-gray-200 bg-white py-1 shadow-lg">
                {OUTCOME_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => {
                      setDropdownOpen(false);
                      setShowNotes(true);
                      // Store chosen outcome for notes step
                      void handleOutcome(opt.value);
                    }}
                    className="flex w-full items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                  >
                    <span className={cn("h-2 w-2 rounded-full", opt.cls)} />
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 2: Approval Card (inline)
// ---------------------------------------------------------------------------

function ApprovalCard({
  draft,
  onAction,
}: {
  draft: OutreachDraft;
  onAction: (id: string, action: "approve" | "reject") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [testSending, setTestSending] = useState(false);
  const [testMsg, setTestMsg] = useState<string | null>(null);

  const handleApprove = async () => {
    setLoading(true);
    try {
      await approveDraft(draft.id);
      onAction(draft.id, "approve");
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
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-gray-900">
              {draft.companies?.name ?? "Unknown"}
            </span>
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
          className="shrink-0 text-xs text-digitillis-accent hover:underline flex items-center gap-1"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide" : "Preview"}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
          {draft.body}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <button
          onClick={handleApprove}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
          Approve
        </button>
        <Link
          href={`/approvals`}
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
        >
          <Pencil className="h-3 w-3" />
          Edit
        </Link>
        <button
          onClick={handleTestSend}
          disabled={testSending}
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          {testSending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Mail className="h-3 w-3" />}
          Test Email
        </button>
        {testMsg && (
          <span className={cn("text-xs font-medium", testMsg.startsWith("Test email sent") ? "text-green-600" : "text-red-500")}>
            {testMsg}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 3: LinkedIn Task Card
// ---------------------------------------------------------------------------

function LinkedInCard({
  task,
  onDone,
}: {
  task: LinkedInTask;
  onDone: (id: string) => void;
}) {
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  // Extract the message body from task metadata if available
  const messageText =
    (task as unknown as { message_text?: string }).message_text ??
    `Hi ${task.contacts?.full_name?.split(" ")[0] ?? "there"}, I noticed you work at ${
      task.companies?.name ?? "your company"
    } — would love to connect and share some ideas around predictive maintenance.`;

  const handleDone = async () => {
    setLoading(true);
    try {
      await markDone({
        action_type: task.next_action_type ?? "linkedin_connection",
        contact_id: task.contact_id,
        company_id: task.company_id,
      });
      setDone(true);
      setTimeout(() => onDone(task.id), 600);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-4 transition-opacity",
        done ? "opacity-40" : "border-gray-200"
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900">
              {task.contacts?.full_name ?? "Unknown"}
            </span>
            {task.contacts?.title && (
              <span className="text-xs text-gray-500">{task.contacts.title}</span>
            )}
            <span className="text-xs text-gray-400">·</span>
            <span className="text-xs text-gray-600">{task.companies?.name}</span>
            {task.companies?.tier && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                {TIER_LABELS[task.companies.tier] ?? task.companies.tier}
              </span>
            )}
          </div>

          {/* Message text */}
          <div className="mt-2 rounded-lg bg-blue-50 border border-blue-100 p-3 text-sm text-gray-700 leading-relaxed">
            {messageText}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <CopyButton text={messageText} />
        {task.contacts?.linkedin_url && (
          <a
            href={task.contacts.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            <ExternalLink className="h-3 w-3" />
            Open LinkedIn
          </a>
        )}
        <button
          onClick={handleDone}
          disabled={loading || done}
          className={cn(
            "inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
            done
              ? "bg-green-100 text-green-700"
              : "border border-gray-200 bg-white text-gray-600 hover:bg-green-50 hover:border-green-200 hover:text-green-700 disabled:opacity-50"
          )}
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : done ? (
            <Check className="h-3 w-3" />
          ) : (
            <Check className="h-3 w-3" />
          )}
          {done ? "Done ✓" : "✓ Done"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 4: Pipeline Quick Actions
// ---------------------------------------------------------------------------

interface PipelineRowProps {
  status: string;
  label: string;
  count: number;
  nextAction?: string;
  agentName?: string;
  agentLabel?: string;
  limit?: number;
}

function PipelineRow({
  label,
  count,
  nextAction,
  agentName,
  agentLabel,
  limit = 10,
}: PipelineRowProps) {
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
        <span className="text-2xl font-bold text-gray-900 tabular-nums w-12 text-right">
          {count}
        </span>
        <span className="text-sm text-gray-600">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {result && (
          <span className="text-xs font-medium text-green-600">{result}</span>
        )}
        {agentName && count > 0 ? (
          <button
            onClick={handleRun}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-lg bg-digitillis-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {running ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            {agentLabel ?? `Run (${limit})`}
          </button>
        ) : nextAction ? (
          <Link
            href={nextAction}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
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
// Section 5: Outcome Logger
// ---------------------------------------------------------------------------

function OutcomeLoggerCard({
  interaction,
  onLogged,
}: {
  interaction: TodayInteraction;
  onLogged: () => void;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const channel = interaction.type.startsWith("linkedin") ? "linkedin" : "email";

  const outcomes =
    channel === "linkedin"
      ? [
          { value: "interested", label: "Interested", cls: "border-green-300 bg-green-50 text-green-800 hover:bg-green-100" },
          { value: "not_now", label: "Not Now", cls: "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100" },
          { value: "not_interested", label: "Not Interested", cls: "border-red-200 bg-red-50 text-red-700 hover:bg-red-100" },
          { value: "meeting_booked", label: "Meeting Booked", cls: "border-blue-300 bg-blue-50 text-blue-800 hover:bg-blue-100" },
        ]
      : [
          { value: "interested", label: "Interested", cls: "border-green-300 bg-green-50 text-green-800 hover:bg-green-100" },
          { value: "not_now", label: "Not Now", cls: "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100" },
          { value: "not_interested", label: "Not Interested", cls: "border-red-200 bg-red-50 text-red-700 hover:bg-red-100" },
          { value: "wrong_person", label: "Wrong Person", cls: "border-gray-300 bg-gray-50 text-gray-700 hover:bg-gray-100" },
          { value: "bounce", label: "Bounce", cls: "border-orange-300 bg-orange-50 text-orange-800 hover:bg-orange-100" },
          { value: "meeting_booked", label: "Meeting Booked 🎉", cls: "border-blue-300 bg-blue-50 text-blue-800 hover:bg-blue-100" },
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
      setSaved(true);
      setTimeout(() => onLogged(), 800);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  if (saved) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
        <Check className="h-4 w-4" />
        Outcome logged for {interaction.companies?.name}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-center gap-2 mb-3">
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

      <div className="flex flex-wrap gap-2">
        {outcomes.map((o) => (
          <button
            key={o.value}
            onClick={() => setSelectedOutcome(o.value)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-medium transition-all",
              o.cls,
              selectedOutcome === o.value
                ? "ring-2 ring-offset-1 ring-current"
                : ""
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
            className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent"
            onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
          />
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-digitillis-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Save
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function TodayCockpitPage() {
  const [data, setData] = useState<TodayData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Draft approval tracking
  const [approvals, setApprovals] = useState<OutreachDraft[]>([]);
  // LinkedIn tasks
  const [linkedInTasks, setLinkedInTasks] = useState<LinkedInTask[]>([]);
  // Hot signals
  const [hotSignals, setHotSignals] = useState<TodayHotSignal[]>([]);
  // Recent interactions for outcome logging
  const [recentInteractions, setRecentInteractions] = useState<TodayInteraction[]>([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTodayData();
      setData(res.data);
      setApprovals(res.data.pending_approvals);
      setLinkedInTasks(res.data.linkedin_queue);
      setHotSignals(res.data.hot_signals);
      setRecentInteractions(res.data.recent_interactions);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load today's data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleApprovalAction = (id: string, _action: "approve" | "reject") => {
    setApprovals((prev) => prev.filter((d) => d.id !== id));
  };

  const handleLinkedInDone = (id: string) => {
    setLinkedInTasks((prev) => prev.filter((t) => t.id !== id));
  };

  const handleOutcomeLogged = () => {
    // Refetch to update counts
    fetchData();
  };

  const handleInteractionLogged = (id: string) => {
    setRecentInteractions((prev) => prev.filter((i) => i.id !== id));
  };

  // Counts for header metric cards
  const hotCount = hotSignals.length;
  const approvalsCount = approvals.length;
  const linkedInCount = linkedInTasks.length;
  const doneCount = data?.progress.completed ?? 0;
  const doneTarget = data?.progress.target ?? 20;

  const pipelineSummary = data?.pipeline_summary ?? {};

  // Group linkedin tasks by sub-type
  const connectionRequests = linkedInTasks.filter(
    (t) => t.next_action_type === "linkedin_connection" || t.sequence_name === "linkedin_connection"
  );
  const openingDMs = linkedInTasks.filter(
    (t) => t.next_action_type === "linkedin_dm_opening" || t.sequence_name?.includes("opening")
  );
  const followupDMs = linkedInTasks.filter(
    (t) =>
      !connectionRequests.includes(t) &&
      !openingDMs.includes(t)
  );

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-digitillis-accent" />
        <span className="ml-3 text-gray-500">Loading your day...</span>
      </div>
    );
  }

  return (
    <div className="space-y-8 pb-12">
      {/* ------------------------------------------------------------------ */}
      {/* HEADER                                                               */}
      {/* ------------------------------------------------------------------ */}
      <div>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2.5">
              <Sun className="h-6 w-6 text-amber-400" />
              <h2 className="text-2xl font-bold text-gray-900">
                Good morning, Avanish
              </h2>
            </div>
            <p className="mt-0.5 text-sm text-gray-500">{formatDate(new Date())}</p>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Metric cards */}
        <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetricCard
            label="Hot Signals"
            value={hotCount}
            icon={Zap}
            color="bg-orange-50 text-orange-500"
            subtext={hotCount > 0 ? "Act now" : "All clear"}
          />
          <MetricCard
            label="Pending Approvals"
            value={approvalsCount}
            icon={Mail}
            color="bg-amber-50 text-amber-500"
            subtext={approvalsCount > 0 ? "Waiting for you" : "All reviewed"}
          />
          <MetricCard
            label="LinkedIn Queue"
            value={linkedInCount}
            icon={Linkedin}
            color="bg-blue-50 text-digitillis-accent"
            subtext={linkedInCount > 0 ? "Ready to send" : "Queue empty"}
          />
          <MetricCard
            label="Done Today"
            value={`${doneCount}/${doneTarget}`}
            icon={CheckCircle2}
            color={doneCount >= doneTarget ? "bg-green-50 text-green-600" : "bg-gray-50 text-gray-500"}
            subtext={doneCount >= doneTarget ? "Target hit! 🎉" : `${doneTarget - doneCount} to go`}
          />
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 1: URGENT — Hot Signals                                     */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-3">
        <SectionHeader
          icon={Zap}
          title="Urgent — Act Now"
          count={hotSignals.length}
          badge="urgent"
        />

        {hotSignals.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 py-8 text-center text-sm text-gray-400">
            No urgent signals right now. Check back throughout the day.
          </div>
        ) : (
          <div className="space-y-3">
            {hotSignals.map((signal) => (
              <HotSignalCard
                key={signal.id}
                signal={signal}
                onOutcomeLogged={handleOutcomeLogged}
              />
            ))}
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 2: APPROVE — Email Drafts                                   */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-3">
        <SectionHeader
          icon={Mail}
          title="Approve — Email Drafts"
          count={approvals.length}
          badge="info"
        />

        {approvals.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 py-8 text-center text-sm text-gray-400">
            No pending drafts.{" "}
            <Link href="/actions" className="text-digitillis-accent hover:underline">
              Run Outreach
            </Link>{" "}
            to generate new ones.
          </div>
        ) : (
          <div className="space-y-3">
            {approvals.map((draft) => (
              <ApprovalCard
                key={draft.id}
                draft={draft}
                onAction={handleApprovalAction}
              />
            ))}
            <Link
              href="/approvals"
              className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-gray-200 py-3 text-sm text-digitillis-accent hover:bg-blue-50"
            >
              View all in Approvals page <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 3: LINKEDIN — Today's touches                               */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-4">
        <SectionHeader
          icon={Linkedin}
          title="LinkedIn — Today's Touches"
          count={linkedInTasks.length}
          badge="info"
        />

        {linkedInTasks.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 py-8 text-center text-sm text-gray-400">
            LinkedIn queue is empty.{" "}
            <Link href="/actions" className="text-digitillis-accent hover:underline">
              Run outreach
            </Link>{" "}
            to generate LinkedIn messages.
          </div>
        ) : (
          <div className="space-y-5">
            {/* Connection Requests */}
            {connectionRequests.length > 0 && (
              <div className="space-y-2.5">
                <h4 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <span className="h-5 w-5 rounded-full bg-blue-100 text-digitillis-accent flex items-center justify-center text-xs font-bold">
                    +
                  </span>
                  Send Connection Requests ({connectionRequests.length} remaining)
                </h4>
                {connectionRequests.map((task) => (
                  <LinkedInCard key={task.id} task={task} onDone={handleLinkedInDone} />
                ))}
              </div>
            )}

            {/* Opening DMs */}
            {openingDMs.length > 0 && (
              <div className="space-y-2.5">
                <h4 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-blue-500" />
                  Send Opening DMs ({openingDMs.length} — accepted your connection)
                </h4>
                {openingDMs.map((task) => (
                  <LinkedInCard key={task.id} task={task} onDone={handleLinkedInDone} />
                ))}
              </div>
            )}

            {/* Follow-up DMs */}
            {followupDMs.length > 0 && (
              <div className="space-y-2.5">
                <h4 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-green-500" />
                  Send Follow-up DMs ({followupDMs.length} — responded to your DM)
                </h4>
                {followupDMs.map((task) => (
                  <LinkedInCard key={task.id} task={task} onDone={handleLinkedInDone} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 4: PIPELINE — Quick Actions                                 */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-3">
        <SectionHeader icon={Play} title="Pipeline — Quick Actions" />

        <div className="rounded-xl border border-gray-200 bg-white px-5 py-2">
          <PipelineRow
            status="discovered"
            label="discovered waiting for research"
            count={pipelineSummary["discovered"] ?? 0}
            agentName="research"
            agentLabel="Run Research: 10"
            limit={10}
          />
          <PipelineRow
            status="researched"
            label="researched waiting for qualification"
            count={pipelineSummary["researched"] ?? 0}
            agentName="qualification"
            agentLabel="Run Qualification"
          />
          <PipelineRow
            status="qualified"
            label="qualified waiting for enrichment"
            count={pipelineSummary["qualified"] ?? 0}
            agentName="enrichment"
            agentLabel="Run Enrichment"
          />
          <PipelineRow
            status="outreach_pending"
            label="drafts pending approval"
            count={pipelineSummary["outreach_pending"] ?? approvalsCount}
            nextAction="/approvals"
          />
          <PipelineRow
            status="contacted"
            label="contacted with no reply yet"
            count={pipelineSummary["contacted"] ?? 0}
            nextAction="/prospects?status=contacted"
          />
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* SECTION 5: LOG OUTCOMES                                             */}
      {/* ------------------------------------------------------------------ */}
      <div className="space-y-3">
        <SectionHeader
          icon={CheckCircle2}
          title="Log Outcomes — What Happened Today?"
          count={recentInteractions.length}
        />

        {recentInteractions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 py-8 text-center text-sm text-gray-400">
            No interactions to log in the last 24 hours.
          </div>
        ) : (
          <div className="space-y-3">
            {recentInteractions.map((interaction) => (
              <OutcomeLoggerCard
                key={interaction.id}
                interaction={interaction}
                onLogged={() => handleInteractionLogged(interaction.id)}
              />
            ))}
          </div>
        )}

        {/* Quick nav to prospects for manual outcome logging */}
        <div className="rounded-xl border border-dashed border-gray-100 p-4 text-center">
          <p className="text-xs text-gray-400">
            Had a conversation not tracked here?{" "}
            <Link href="/prospects?status=engaged" className="text-digitillis-accent hover:underline">
              Find the prospect
            </Link>{" "}
            and log it manually.
          </p>
        </div>
      </div>
    </div>
  );
}
