"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Mail,
  MailOpen,
  MailCheck,
  Reply,
  AlertTriangle,
  Linkedin,
  Phone,
  Calendar,
  StickyNote,
  RefreshCw,
  Star,
  Flag,
  ChevronDown,
  Loader2,
  AlertCircle,
  Send,
  Clock,
  CheckCircle2,
  XCircle,
  User,
  Cpu,
  Wrench,
  Wifi,
  Settings,
  Lightbulb,
  Sparkles,
  FileText,
  ExternalLink,
} from "lucide-react";

import {
  getCompany,
  updateCompany,
  type CompanyDetail,
  type Contact,
  type Research,
  type Interaction,
} from "@/lib/api";
import {
  cn,
  formatDate,
  formatTimeAgo,
  STATUS_COLORS,
  TIER_LABELS,
  getPQSColor,
} from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TABS = ["Overview", "Contacts", "Timeline", "Outreach"] as const;
type Tab = (typeof TABS)[number];

const STATUS_OPTIONS = [
  "discovered",
  "researched",
  "qualified",
  "disqualified",
  "outreach_pending",
  "contacted",
  "engaged",
  "meeting_scheduled",
  "pilot_discussion",
  "pilot_signed",
  "active_pilot",
  "converted",
  "not_interested",
  "paused",
  "bounced",
];

// ---------------------------------------------------------------------------
// Interaction type -> icon mapping
// ---------------------------------------------------------------------------

function InteractionIcon({ type }: { type: string }) {
  const cls = "h-4 w-4";
  switch (type) {
    case "email_sent":
      return <Mail className={cn(cls, "text-blue-500")} />;
    case "email_opened":
      return <MailOpen className={cn(cls, "text-indigo-500")} />;
    case "email_clicked":
      return <MailCheck className={cn(cls, "text-green-500")} />;
    case "email_replied":
      return <Reply className={cn(cls, "text-purple-500")} />;
    case "email_bounced":
      return <AlertTriangle className={cn(cls, "text-red-500")} />;
    case "linkedin_connection":
      return <Linkedin className={cn(cls, "text-blue-600")} />;
    case "linkedin_message":
      return <Linkedin className={cn(cls, "text-blue-500")} />;
    case "phone_call":
      return <Phone className={cn(cls, "text-green-600")} />;
    case "meeting":
      return <Calendar className={cn(cls, "text-pink-500")} />;
    case "note":
      return <StickyNote className={cn(cls, "text-yellow-600")} />;
    case "status_change":
      return <RefreshCw className={cn(cls, "text-gray-500")} />;
    default:
      return <Mail className={cn(cls, "text-gray-400")} />;
  }
}

// ---------------------------------------------------------------------------
// PQS Breakdown Bar
// ---------------------------------------------------------------------------

function PQSBreakdownBar({
  firmographic,
  technographic,
  timing,
  engagement,
}: {
  firmographic: number;
  technographic: number;
  timing: number;
  engagement: number;
}) {
  const segments = [
    { label: "F", value: firmographic, color: "bg-blue-500" },
    { label: "T", value: technographic, color: "bg-green-500" },
    { label: "Ti", value: timing, color: "bg-amber-500" },
    { label: "E", value: engagement, color: "bg-purple-500" },
  ];

  return (
    <div className="space-y-1">
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-gray-100">
        {segments.map((seg) => (
          <div
            key={seg.label}
            className={cn(seg.color, "transition-all")}
            style={{ width: `${(seg.value / 100) * 100}%` }}
            title={`${seg.label}: ${seg.value}/25`}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] font-medium text-gray-500">
        {segments.map((seg) => (
          <span key={seg.label}>
            {seg.label}: {seg.value}/25
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ProspectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const [saving, setSaving] = useState(false);
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);

  // --- Fetch company ---
  const fetchCompany = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getCompany(id);
      setCompany(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load company");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchCompany();
  }, [fetchCompany]);

  // --- Handlers ---
  const handleStatusChange = async (newStatus: string) => {
    if (!company) return;
    setSaving(true);
    try {
      await updateCompany(id, { status: newStatus });
      setCompany((prev) => (prev ? { ...prev, status: newStatus } : prev));
    } catch {
      // Revert silently for now
    } finally {
      setSaving(false);
      setStatusDropdownOpen(false);
    }
  };

  const handleTogglePriority = async () => {
    if (!company) return;
    setSaving(true);
    try {
      const next = !company.priority_flag;
      await updateCompany(id, { priority_flag: next });
      setCompany((prev) => (prev ? { ...prev, priority_flag: next } : prev));
    } catch {
      // Revert silently
    } finally {
      setSaving(false);
    }
  };

  // --- Loading / Error ---
  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
        <span className="ml-2 text-sm text-gray-500">Loading prospect...</span>
      </div>
    );
  }

  if (error || !company) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-32">
        <AlertCircle className="h-8 w-8 text-red-400" />
        <p className="text-sm text-red-600">{error ?? "Company not found"}</p>
        <button
          onClick={() => router.push("/prospects")}
          className="text-sm text-indigo-600 hover:underline"
        >
          Back to Prospects
        </button>
      </div>
    );
  }

  // --- Render ---
  return (
    <div className="space-y-6">
      {/* ---- Back button ---- */}
      <button
        onClick={() => router.push("/prospects")}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Prospects
      </button>

      {/* ---- Header ---- */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-gray-900">{company.name}</h2>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
                STATUS_COLORS[company.status] ?? "bg-gray-100 text-gray-600"
              )}
            >
              {company.status.replace(/_/g, " ")}
            </span>
            {company.priority_flag && (
              <Flag className="h-4 w-4 fill-orange-400 text-orange-400" />
            )}
          </div>

          {/* Meta row */}
          <div className="flex flex-wrap items-center gap-4 text-sm text-gray-500">
            {company.tier && (
              <span>
                Tier {company.tier} &mdash; {TIER_LABELS[company.tier] ?? company.tier}
              </span>
            )}
            {company.sub_sector && <span>{company.sub_sector}</span>}
            {company.state && <span>{company.state}</span>}
            {company.territory && <span>Territory: {company.territory}</span>}
            {company.domain && (
              <a
                href={`https://${company.domain}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-600 hover:underline"
              >
                {company.domain}
              </a>
            )}
          </div>

          {/* PQS Score + Breakdown */}
          <div className="max-w-md space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-medium text-gray-700">PQS Score:</span>
              <span className={cn("text-2xl font-bold", getPQSColor(company.pqs_total))}>
                {company.pqs_total}
              </span>
              <span className="text-sm text-gray-400">/100</span>
            </div>
            <PQSBreakdownBar
              firmographic={company.pqs_firmographic}
              technographic={company.pqs_technographic}
              timing={company.pqs_timing}
              engagement={company.pqs_engagement}
            />
          </div>
        </div>

        {/* ---- Sidebar actions ---- */}
        <div className="flex shrink-0 flex-col gap-2 lg:items-end">
          {/* Status change dropdown */}
          <div className="relative">
            <button
              onClick={() => setStatusDropdownOpen((o) => !o)}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Change Status
              <ChevronDown className="h-4 w-4" />
            </button>
            {statusDropdownOpen && (
              <div className="absolute right-0 z-20 mt-1 max-h-64 w-52 overflow-y-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg">
                {STATUS_OPTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => handleStatusChange(s)}
                    className={cn(
                      "block w-full px-3 py-1.5 text-left text-sm capitalize hover:bg-gray-50",
                      s === company.status
                        ? "font-semibold text-indigo-600"
                        : "text-gray-700"
                    )}
                  >
                    {s.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Priority flag */}
          <button
            onClick={handleTogglePriority}
            disabled={saving}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-50",
              company.priority_flag
                ? "border-orange-300 bg-orange-50 text-orange-700 hover:bg-orange-100"
                : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
            )}
          >
            <Flag
              className={cn(
                "h-4 w-4",
                company.priority_flag
                  ? "fill-orange-400 text-orange-400"
                  : "text-gray-400"
              )}
            />
            {company.priority_flag ? "Priority" : "Set Priority"}
          </button>

          {/* Add Note */}
          <button className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
            <StickyNote className="h-4 w-4 text-gray-400" />
            Add Note
          </button>
        </div>
      </div>

      {/* ---- Tab navigation ---- */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium transition-colors",
                activeTab === tab
                  ? "border-indigo-500 text-indigo-600"
                  : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
              )}
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>

      {/* ---- Tab content ---- */}
      <div>
        {activeTab === "Overview" && <OverviewTab company={company} />}
        {activeTab === "Contacts" && <ContactsTab contacts={company.contacts} />}
        {activeTab === "Timeline" && <TimelineTab interactions={company.interactions} />}
        {activeTab === "Outreach" && <OutreachTab company={company} />}
      </div>
    </div>
  );
}

// ===========================================================================
// Tab 1 - Overview
// ===========================================================================

function OverviewTab({ company }: { company: CompanyDetail }) {
  const research = company.research;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Research Summary */}
      {company.research_summary && (
        <div className="rounded-lg border border-gray-200 bg-white p-5 lg:col-span-2">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <FileText className="h-4 w-4 text-gray-500" />
            Research Summary
          </h3>
          <p className="text-sm leading-relaxed text-gray-600">
            {company.research_summary}
          </p>
        </div>
      )}

      {/* Manufacturing Profile */}
      {research && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Settings className="h-4 w-4 text-gray-500" />
            Manufacturing Profile
          </h3>
          <dl className="space-y-3 text-sm">
            {research.manufacturing_type && (
              <div className="flex justify-between">
                <dt className="flex items-center gap-1.5 text-gray-500">
                  <Cpu className="h-3.5 w-3.5" />
                  Type
                </dt>
                <dd className="font-medium capitalize text-gray-900">
                  {research.manufacturing_type}
                </dd>
              </div>
            )}
            {research.equipment_types && research.equipment_types.length > 0 && (
              <div>
                <dt className="mb-1 flex items-center gap-1.5 text-gray-500">
                  <Wrench className="h-3.5 w-3.5" />
                  Equipment
                </dt>
                <dd className="flex flex-wrap gap-1.5">
                  {research.equipment_types.map((eq, i) => (
                    <span
                      key={i}
                      className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
                    >
                      {eq}
                    </span>
                  ))}
                </dd>
              </div>
            )}
            {research.iot_maturity && (
              <div className="flex justify-between">
                <dt className="flex items-center gap-1.5 text-gray-500">
                  <Wifi className="h-3.5 w-3.5" />
                  IoT Maturity
                </dt>
                <dd className="font-medium capitalize text-gray-900">
                  {research.iot_maturity}
                </dd>
              </div>
            )}
            {research.maintenance_approach && (
              <div className="flex justify-between">
                <dt className="flex items-center gap-1.5 text-gray-500">
                  <Wrench className="h-3.5 w-3.5" />
                  Maintenance
                </dt>
                <dd className="font-medium capitalize text-gray-900">
                  {research.maintenance_approach.replace(/_/g, " ")}
                </dd>
              </div>
            )}
          </dl>
        </div>
      )}

      {/* Technology Stack */}
      {company.technology_stack && company.technology_stack.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Cpu className="h-4 w-4 text-gray-500" />
            Technology Stack
          </h3>
          <div className="flex flex-wrap gap-2">
            {company.technology_stack.map((tech, i) => (
              <span
                key={i}
                className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700"
              >
                {tech}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Pain Signals */}
      {company.pain_signals && company.pain_signals.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            Pain Signals
          </h3>
          <ul className="space-y-2">
            {company.pain_signals.map((signal, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                {signal}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Personalization Hooks */}
      {company.personalization_hooks && company.personalization_hooks.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Sparkles className="h-4 w-4 text-purple-500" />
            Personalization Hooks
          </h3>
          <ul className="space-y-2">
            {company.personalization_hooks.map((hook, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-md bg-purple-50 px-3 py-2 text-sm text-purple-800"
              >
                <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-purple-400" />
                {hook}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Qualification Notes */}
      {company.qualification_notes && (
        <div className="rounded-lg border border-gray-200 bg-white p-5 lg:col-span-2">
          <h3 className="mb-2 text-sm font-semibold text-gray-900">
            Qualification Notes
          </h3>
          <p className="text-sm text-gray-600">{company.qualification_notes}</p>
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Tab 2 - Contacts
// ===========================================================================

function ContactsTab({ contacts }: { contacts: Contact[] }) {
  if (!contacts || contacts.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-gray-500">
        No contacts found for this company.
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {contacts.map((contact) => (
        <div
          key={contact.id}
          className="rounded-lg border border-gray-200 bg-white p-4 transition-shadow hover:shadow-md"
        >
          <div className="mb-3 flex items-start justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-100">
                <User className="h-4 w-4 text-indigo-600" />
              </div>
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-semibold text-gray-900">
                    {contact.full_name || "Unknown"}
                  </span>
                  {contact.is_decision_maker && (
                    <Star className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
                  )}
                </div>
                {contact.title && (
                  <p className="text-xs text-gray-500">{contact.title}</p>
                )}
              </div>
            </div>
          </div>

          {/* Persona badge */}
          {contact.persona_type && (
            <span className="mb-3 inline-block rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium capitalize text-indigo-700">
              {contact.persona_type.replace(/_/g, " ")}
            </span>
          )}

          {/* Contact details */}
          <div className="space-y-1.5 text-sm">
            {contact.email && (
              <div className="flex items-center gap-2 text-gray-600">
                <Mail className="h-3.5 w-3.5 text-gray-400" />
                <span className="truncate">{contact.email}</span>
              </div>
            )}
            {contact.linkedin_url && (
              <a
                href={contact.linkedin_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-blue-600 hover:underline"
              >
                <Linkedin className="h-3.5 w-3.5" />
                <span className="truncate text-xs">LinkedIn Profile</span>
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ===========================================================================
// Tab 3 - Timeline
// ===========================================================================

function TimelineTab({ interactions }: { interactions: Interaction[] }) {
  if (!interactions || interactions.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-gray-500">
        No interactions recorded yet.
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {interactions.map((ix, idx) => (
        <div key={ix.id} className="relative flex gap-4 pb-6">
          {/* Vertical connector line */}
          {idx < interactions.length - 1 && (
            <div className="absolute left-[17px] top-8 h-full w-px bg-gray-200" />
          )}

          {/* Icon */}
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-gray-200 bg-white">
            <InteractionIcon type={ix.type} />
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium capitalize text-gray-700">
                  {ix.type.replace(/_/g, " ")}
                </span>
                {ix.channel && (
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] uppercase text-gray-500">
                    {ix.channel}
                  </span>
                )}
              </div>
              <span className="shrink-0 text-xs text-gray-400">
                {formatTimeAgo(ix.created_at)}
              </span>
            </div>

            {ix.subject && (
              <p className="text-sm font-medium text-gray-900">{ix.subject}</p>
            )}

            {ix.body && (
              <p className="mt-1 line-clamp-3 text-sm text-gray-500">{ix.body}</p>
            )}

            <p className="mt-1.5 text-[10px] text-gray-400">
              {formatDate(ix.created_at)}
              {ix.source && <> &middot; {ix.source}</>}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ===========================================================================
// Tab 4 - Outreach
// ===========================================================================

interface OutreachDraftItem {
  id: string;
  subject: string;
  body: string;
  approval_status: string;
  sequence_name?: string;
  sequence_step?: number;
  sent_at?: string;
  created_at?: string;
  channel?: string;
}

function OutreachTab({ company }: { company: CompanyDetail }) {
  // Derive outreach drafts from interactions that look like outreach,
  // plus any drafts embedded in the company detail.
  // The API returns interactions; outreach drafts can be inferred from
  // email_sent type interactions. We also show a sequence status summary.

  const emailInteractions = company.interactions.filter(
    (ix) =>
      ix.type === "email_sent" ||
      ix.type === "email_opened" ||
      ix.type === "email_replied" ||
      ix.type === "email_bounced"
  );

  // Compute a simple sequence status from interactions
  const sentCount = company.interactions.filter((ix) => ix.type === "email_sent").length;
  const openCount = company.interactions.filter((ix) => ix.type === "email_opened").length;
  const replyCount = company.interactions.filter(
    (ix) => ix.type === "email_replied"
  ).length;
  const bounceCount = company.interactions.filter(
    (ix) => ix.type === "email_bounced"
  ).length;

  const hasSequenceActivity = sentCount > 0;

  return (
    <div className="space-y-6">
      {/* Sequence status summary */}
      {hasSequenceActivity && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">
            Sequence Status
          </h3>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-md bg-blue-50 px-4 py-3 text-center">
              <Send className="mx-auto mb-1 h-4 w-4 text-blue-500" />
              <p className="text-lg font-bold text-blue-700">{sentCount}</p>
              <p className="text-xs text-blue-500">Sent</p>
            </div>
            <div className="rounded-md bg-indigo-50 px-4 py-3 text-center">
              <MailOpen className="mx-auto mb-1 h-4 w-4 text-indigo-500" />
              <p className="text-lg font-bold text-indigo-700">{openCount}</p>
              <p className="text-xs text-indigo-500">Opened</p>
            </div>
            <div className="rounded-md bg-green-50 px-4 py-3 text-center">
              <Reply className="mx-auto mb-1 h-4 w-4 text-green-500" />
              <p className="text-lg font-bold text-green-700">{replyCount}</p>
              <p className="text-xs text-green-500">Replied</p>
            </div>
            <div className="rounded-md bg-red-50 px-4 py-3 text-center">
              <AlertTriangle className="mx-auto mb-1 h-4 w-4 text-red-500" />
              <p className="text-lg font-bold text-red-700">{bounceCount}</p>
              <p className="text-xs text-red-500">Bounced</p>
            </div>
          </div>
        </div>
      )}

      {/* Outreach drafts / sent emails list */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-4 text-sm font-semibold text-gray-900">
          Outreach Messages
        </h3>

        {emailInteractions.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500">
            No outreach activity for this prospect yet.
          </p>
        ) : (
          <div className="divide-y divide-gray-100">
            {emailInteractions.map((ix) => {
              const statusBadge = (() => {
                switch (ix.type) {
                  case "email_sent":
                    return (
                      <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                        <CheckCircle2 className="h-3 w-3" />
                        Sent
                      </span>
                    );
                  case "email_opened":
                    return (
                      <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
                        <MailOpen className="h-3 w-3" />
                        Opened
                      </span>
                    );
                  case "email_replied":
                    return (
                      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                        <Reply className="h-3 w-3" />
                        Replied
                      </span>
                    );
                  case "email_bounced":
                    return (
                      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                        <XCircle className="h-3 w-3" />
                        Bounced
                      </span>
                    );
                  default:
                    return (
                      <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                        <Clock className="h-3 w-3" />
                        Pending
                      </span>
                    );
                }
              })();

              return (
                <div key={ix.id} className="flex items-start justify-between gap-4 py-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-gray-900">
                        {ix.subject || "No subject"}
                      </p>
                      {statusBadge}
                    </div>
                    {ix.body && (
                      <p className="mt-1 line-clamp-2 text-sm text-gray-500">
                        {ix.body}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 text-xs text-gray-400">
                    {formatTimeAgo(ix.created_at)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
