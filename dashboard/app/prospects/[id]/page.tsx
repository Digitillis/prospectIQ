"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
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
  Building2,
  Plus,
  DollarSign,
  Users,
  MapPin,
  FileSearch,
  Filter,
  MessageSquare,
  Ban,
  CalendarCheck,
  Clipboard,
  Printer,
  Trophy,
  Target,
  Bell,
  X,
  Tag,
  type LucideIcon,
} from "lucide-react";

import {
  getCompany,
  updateCompany,
  addNote,
  createContact,
  enrichCompany,
  runAgent,
  recordOutcome,
  updateTags,
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
import { useReminders } from "@/lib/use-reminders";

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
// ActionButton sub-component
// ---------------------------------------------------------------------------

function ActionButton({
  label,
  icon: Icon,
  onClick,
  loading,
  variant = "default",
}: {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  loading: boolean;
  variant?: "default" | "danger";
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50",
        variant === "danger"
          ? "border-red-200 text-red-600 hover:bg-red-50"
          : "border-gray-300 text-gray-700 hover:bg-gray-50"
      )}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Icon className="h-4 w-4" />
      )}
      {label}
    </button>
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
  const [noteModalOpen, setNoteModalOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [outcomeLoading, setOutcomeLoading] = useState<string | null>(null);
  const [outcomeModal, setOutcomeModal] = useState<"won" | "lost" | "no_response" | null>(null);
  const [outcomeNotes, setOutcomeNotes] = useState("");
  const [outcomeSubmitLoading, setOutcomeSubmitLoading] = useState(false);
  const [outcomeSuccess, setOutcomeSuccess] = useState<string | null>(null);
  const [enrichLoading, setEnrichLoading] = useState(false);
  const [enrichResult, setEnrichResult] = useState<string | null>(null);
  const [agentLoading, setAgentLoading] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [disqualifyConfirm, setDisqualifyConfirm] = useState(false);

  // Deal value state — Feature 28
  const [dealValue, setDealValue] = useState("");
  const [dealValueSaving, setDealValueSaving] = useState(false);
  const [dealValueSuccess, setDealValueSuccess] = useState<string | null>(null);

  // Tag state
  const [showTagInput, setShowTagInput] = useState(false);
  const [newTag, setNewTag] = useState("");
  const [tagSaving, setTagSaving] = useState(false);

  // Brief generator state
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefContent, setBriefContent] = useState<string | null>(null);

  // Reminder state
  const { reminders, addReminder, dismissReminder } = useReminders();
  const [showReminderForm, setShowReminderForm] = useState(false);
  const [reminderDays, setReminderDays] = useState(7);
  const [reminderNote, setReminderNote] = useState("");
  const [reminderSuccess, setReminderSuccess] = useState<string | null>(null);
  const companyReminders = reminders.filter((r) => r.companyId === id);

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

  // Sync deal value from loaded company data
  useEffect(() => {
    if (company?.estimated_deal_value != null) {
      setDealValue(String(company.estimated_deal_value));
    }
  }, [company?.estimated_deal_value]);

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

  const handleAddNote = async () => {
    if (!company || !noteText.trim()) return;
    setSaving(true);
    try {
      await addNote(id, noteText.trim());
      setNoteText("");
      setNoteModalOpen(false);
      await fetchCompany();
    } catch {
      // silent for now
    } finally {
      setSaving(false);
    }
  };

  const handleOutcome = (outcome: "won" | "lost" | "no_response") => {
    setOutcomeModal(outcome);
    setOutcomeNotes("");
    setOutcomeSuccess(null);
  };

  const submitOutcome = async () => {
    if (!outcomeModal || !company) return;
    setOutcomeSubmitLoading(true);
    try {
      const res = await recordOutcome(id, outcomeModal, outcomeNotes || undefined);
      setCompany((prev) =>
        prev ? { ...prev, status: res.data.new_status } : prev
      );
      setOutcomeSuccess(
        outcomeModal === "won"
          ? "Outcome recorded — marked as Won."
          : outcomeModal === "lost"
          ? "Outcome recorded — marked as Lost."
          : "Outcome recorded — marked as No Response."
      );
      setOutcomeModal(null);
      setOutcomeNotes("");
      await fetchCompany();
    } catch {
      // silent for now
    } finally {
      setOutcomeSubmitLoading(false);
    }
  };

  const handleEnrich = async () => {
    setEnrichLoading(true);
    setEnrichResult(null);
    try {
      const res = await enrichCompany(id);
      const { contacts_enriched, errors } = res.data;
      if (contacts_enriched > 0) {
        setEnrichResult(`${contacts_enriched} contact email(s) found.`);
        await fetchCompany();
      } else if (errors > 0) {
        setEnrichResult("Apollo enrichment failed. Check API key.");
      } else {
        setEnrichResult("No new emails found (contacts may already be enriched or have no Apollo profile).");
      }
    } catch {
      setEnrichResult("Enrichment failed. Check Apollo API key.");
    } finally {
      setEnrichLoading(false);
    }
  };

  // --- Tag handlers ---
  const addTag = async () => {
    if (!company || !newTag.trim()) return;
    const trimmed = newTag.trim().toLowerCase().replace(/\s+/g, "-");
    const currentTags: string[] = company.custom_tags ?? [];
    if (currentTags.includes(trimmed)) {
      setNewTag("");
      setShowTagInput(false);
      return;
    }
    const nextTags = [...currentTags, trimmed];
    setTagSaving(true);
    try {
      await updateTags(id, nextTags);
      setCompany((prev) => prev ? { ...prev, custom_tags: nextTags } : prev);
    } catch {
      // silent
    } finally {
      setTagSaving(false);
      setNewTag("");
      setShowTagInput(false);
    }
  };

  const removeTag = async (tag: string) => {
    if (!company) return;
    const nextTags = (company.custom_tags ?? []).filter((t) => t !== tag);
    setTagSaving(true);
    try {
      await updateTags(id, nextTags);
      setCompany((prev) => prev ? { ...prev, custom_tags: nextTags } : prev);
    } catch {
      // silent
    } finally {
      setTagSaving(false);
    }
  };

  // --- Agent action handlers ---
  const handleRunAgent = async (agentName: string, label: string) => {
    setAgentLoading(agentName);
    setActionResult(null);
    try {
      await runAgent(agentName, { company_ids: [id] });
      setActionResult({ type: "success", message: `${label} completed successfully.` });
      await fetchCompany();
    } catch {
      setActionResult({ type: "error", message: `${label} failed. Please try again.` });
    } finally {
      setAgentLoading(null);
    }
  };

  const handleEnrichAction = async () => {
    setAgentLoading("enrich");
    setActionResult(null);
    try {
      const res = await enrichCompany(id);
      const { contacts_enriched, errors } = res.data;
      if (contacts_enriched > 0) {
        setActionResult({ type: "success", message: `${contacts_enriched} contact email(s) found via Apollo.` });
        await fetchCompany();
      } else if (errors > 0) {
        setActionResult({ type: "error", message: "Apollo enrichment failed. Check API key." });
      } else {
        setActionResult({ type: "success", message: "No new emails found (contacts may already be enriched)." });
      }
    } catch {
      setActionResult({ type: "error", message: "Enrichment failed. Check Apollo API key." });
    } finally {
      setAgentLoading(null);
    }
  };

  const handleDisqualify = async () => {
    if (!disqualifyConfirm) {
      setDisqualifyConfirm(true);
      return;
    }
    setAgentLoading("disqualify");
    setActionResult(null);
    setDisqualifyConfirm(false);
    try {
      await updateCompany(id, { status: "disqualified" });
      setActionResult({ type: "success", message: "Company marked as disqualified." });
      await fetchCompany();
    } catch {
      setActionResult({ type: "error", message: "Failed to disqualify company." });
    } finally {
      setAgentLoading(null);
    }
  };

  // --- Deal value save handler — Feature 28 ---
  const saveDealValue = async () => {
    if (!company) return;
    setDealValueSaving(true);
    setDealValueSuccess(null);
    try {
      await updateCompany(id, { estimated_deal_value: dealValue ? Number(dealValue) : null });
      setCompany((prev) =>
        prev ? { ...prev, estimated_deal_value: dealValue ? Number(dealValue) : undefined } : prev
      );
      setDealValueSuccess("Deal value saved.");
      setTimeout(() => setDealValueSuccess(null), 3000);
    } catch {
      // silent for now
    } finally {
      setDealValueSaving(false);
    }
  };

  // --- Brief generator ---
  const generateBrief = () => {
    if (!company) return;
    setBriefLoading(true);
    setTimeout(() => {
      const techList = (company.technology_stack || []).map((t) => `<li>${t}</li>`).join("");
      const painList = (company.pain_signals || []).map((p) => `<li>${p}</li>`).join("");
      const hookList = (company.personalization_hooks || []).map((h) => `<li>${h}</li>`).join("");
      const contactList =
        company.contacts
          ?.map(
            (c) =>
              `<p style="margin:2px 0">• ${c.full_name || "Unknown"} — ${c.title || "No title"}${c.is_decision_maker ? " <strong>(Decision Maker)</strong>" : ""}</p>`
          )
          .join("") || "<p>No contacts found</p>";

      const brief = `
        <h2 style="font-size:1.25rem;font-weight:700;margin-bottom:0.25rem">${company.name} — Sales Brief</h2>
        <p style="color:#6b7280;font-size:0.85rem;margin-bottom:1rem">Generated ${new Date().toLocaleDateString()}</p>
        <hr style="border-color:#e5e7eb;margin-bottom:1rem"/>
        <p><strong>Industry:</strong> ${company.industry || "Manufacturing"}</p>
        <p><strong>Location:</strong> ${[company.city, company.state].filter(Boolean).join(", ") || "—"}</p>
        <p><strong>Size:</strong> ${company.employee_count?.toLocaleString() || "?"} employees · ${company.revenue_range || "—"}</p>
        <h3 style="font-size:1rem;font-weight:600;margin-top:1rem;margin-bottom:0.25rem">Company Overview</h3>
        <p>${company.research_summary || "No research summary available. Run the Research agent to generate insights."}</p>
        ${techList ? `<h3 style="font-size:1rem;font-weight:600;margin-top:1rem;margin-bottom:0.25rem">Technology Stack</h3><ul style="list-style:disc;padding-left:1.25rem">${techList}</ul>` : ""}
        ${painList ? `<h3 style="font-size:1rem;font-weight:600;margin-top:1rem;margin-bottom:0.25rem">Pain Points</h3><ul style="list-style:disc;padding-left:1.25rem">${painList}</ul>` : ""}
        ${hookList ? `<h3 style="font-size:1rem;font-weight:600;margin-top:1rem;margin-bottom:0.25rem">Personalization Hooks</h3><ul style="list-style:disc;padding-left:1.25rem">${hookList}</ul>` : ""}
        <h3 style="font-size:1rem;font-weight:600;margin-top:1rem;margin-bottom:0.25rem">Key Contacts</h3>
        ${contactList}
        <h3 style="font-size:1rem;font-weight:600;margin-top:1rem;margin-bottom:0.25rem">Prospect Quality Score</h3>
        <p>PQS Total: <strong>${company.pqs_total}/100</strong></p>
        <p style="color:#6b7280;font-size:0.85rem">Firmographic ${company.pqs_firmographic}/25 · Technographic ${company.pqs_technographic}/25 · Timing ${company.pqs_timing}/25 · Engagement ${company.pqs_engagement}/25</p>
      `;
      setBriefContent(brief);
      setBriefLoading(false);
    }, 500);
  };

  // --- Reminder handler ---
  const handleSetReminder = () => {
    if (!company || !reminderNote.trim()) return;
    addReminder(id, company.name, reminderNote.trim(), reminderDays);
    setReminderNote("");
    setShowReminderForm(false);
    setReminderSuccess("Reminder set successfully.");
    setTimeout(() => setReminderSuccess(null), 3000);
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
            {company.domain && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`https://logo.clearbit.com/${company.domain}`}
                alt=""
                className="h-8 w-8 rounded-lg"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            )}
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

          {/* Custom Tags */}
          <div className="flex flex-wrap items-center gap-1.5">
            <Tag className="h-3.5 w-3.5 shrink-0 text-gray-400" />
            {(company.custom_tags ?? []).map((tag: string) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-700"
              >
                {tag}
                <button
                  onClick={() => removeTag(tag)}
                  disabled={tagSaving}
                  className="hover:text-red-500 disabled:opacity-50"
                  aria-label={`Remove tag ${tag}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {showTagInput ? (
              <input
                autoFocus
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); addTag(); }
                  if (e.key === "Escape") { setShowTagInput(false); setNewTag(""); }
                }}
                disabled={tagSaving}
                placeholder="Tag name..."
                className="rounded-full border border-indigo-300 bg-white px-2.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400 w-24 disabled:opacity-50"
              />
            ) : (
              <button
                onClick={() => setShowTagInput(true)}
                className="rounded-full border border-dashed border-gray-300 px-2.5 py-0.5 text-xs text-gray-400 hover:border-gray-400 hover:text-gray-600 transition-colors"
              >
                + Add tag
              </button>
            )}
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
          <button
            onClick={() => setNoteModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <StickyNote className="h-4 w-4 text-gray-400" />
            Add Note
          </button>

          {/* Set Reminder */}
          <button
            onClick={() => setShowReminderForm((o) => !o)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
              showReminderForm
                ? "border-orange-300 bg-orange-50 text-orange-700 hover:bg-orange-100"
                : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
            )}
          >
            <Bell className="h-4 w-4 text-gray-400" />
            Set Reminder
          </button>

          {/* Inline reminder form */}
          {showReminderForm && (
            <div className="rounded-lg border border-orange-200 bg-orange-50 p-3 space-y-2">
              <p className="text-xs font-semibold text-orange-700">New Reminder</p>
              <div className="flex items-center gap-2">
                <select
                  className="rounded border border-orange-200 bg-white px-2 py-1 text-sm text-gray-700 focus:outline-none"
                  value={reminderDays}
                  onChange={(e) => setReminderDays(Number(e.target.value))}
                >
                  <option value={1}>Tomorrow</option>
                  <option value={3}>In 3 days</option>
                  <option value={7}>In 1 week</option>
                  <option value={14}>In 2 weeks</option>
                  <option value={30}>In 1 month</option>
                </select>
              </div>
              <input
                placeholder="Reminder note..."
                className="w-full rounded border border-orange-200 bg-white px-2 py-1 text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none"
                value={reminderNote}
                onChange={(e) => setReminderNote(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSetReminder(); }}
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSetReminder}
                  disabled={!reminderNote.trim()}
                  className="rounded-md bg-orange-600 px-3 py-1 text-xs font-semibold text-white hover:bg-orange-700 disabled:opacity-50"
                >
                  Set
                </button>
                <button
                  onClick={() => { setShowReminderForm(false); setReminderNote(""); }}
                  className="rounded-md border border-orange-200 px-3 py-1 text-xs font-medium text-orange-700 hover:bg-orange-100"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {reminderSuccess && (
            <p className="text-xs text-green-600">{reminderSuccess}</p>
          )}

          {/* Enrich Contacts */}
          <button
            onClick={handleEnrich}
            disabled={enrichLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            title="Find emails for contacts via Apollo.io (consumes credits)"
          >
            {enrichLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Users className="h-4 w-4" />
            )}
            Enrich Contacts
          </button>
          {enrichResult && (
            <p className="text-xs text-gray-500">{enrichResult}</p>
          )}

          {/* Outcome buttons — show when company has been contacted */}
          {["contacted", "engaged", "meeting_scheduled", "pilot_discussion", "pilot_signed", "active_pilot"].includes(
            company.status
          ) && (
            <div className="flex flex-col gap-1.5">
              <p className="text-xs font-medium text-gray-500">Record Outcome</p>
              <div className="flex gap-2">
                <button
                  onClick={() => handleOutcome("won")}
                  disabled={outcomeLoading !== null}
                  className="inline-flex items-center gap-1 rounded-md bg-green-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {outcomeLoading === "won" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  Won
                </button>
                <button
                  onClick={() => handleOutcome("lost")}
                  disabled={outcomeLoading !== null}
                  className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                >
                  {outcomeLoading === "lost" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  Lost
                </button>
                <button
                  onClick={() => handleOutcome("no_response")}
                  disabled={outcomeLoading !== null}
                  className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                >
                  {outcomeLoading === "no_response" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Clock className="h-3.5 w-3.5" />
                  )}
                  No Response
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ---- Note modal ---- */}
      {noteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="mb-3 text-lg font-semibold text-gray-900">Add Note</h3>
            <textarea
              autoFocus
              rows={4}
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Write a note about this prospect..."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setNoteModalOpen(false); setNoteText(""); }}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAddNote}
                disabled={saving || !noteText.trim()}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Note"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Agent Actions Bar ---- */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Agent Actions
          </span>

          {company.status === "discovered" && (
            <ActionButton
              label="Run Research"
              icon={FileSearch}
              onClick={() => handleRunAgent("research", "Research")}
              loading={agentLoading === "research"}
            />
          )}

          {company.status === "researched" && (
            <ActionButton
              label="Run Qualification"
              icon={Filter}
              onClick={() => handleRunAgent("qualification", "Qualification")}
              loading={agentLoading === "qualification"}
            />
          )}

          {(company.status === "qualified" || company.status === "outreach_pending") && (
            <ActionButton
              label="Generate Outreach"
              icon={MessageSquare}
              onClick={() => handleRunAgent("outreach", "Outreach generation")}
              loading={agentLoading === "outreach"}
            />
          )}

          <ActionButton
            label="Enrich Contacts"
            icon={Users}
            onClick={handleEnrichAction}
            loading={agentLoading === "enrich"}
          />

          {company.status !== "disqualified" && (
            <ActionButton
              label={disqualifyConfirm ? "Confirm Disqualify?" : "Disqualify"}
              icon={Ban}
              onClick={handleDisqualify}
              loading={agentLoading === "disqualify"}
              variant="danger"
            />
          )}
        </div>

        {actionResult && (
          <div
            className={cn(
              "mt-2 rounded-lg border px-4 py-2 text-sm",
              actionResult.type === "success"
                ? "border-green-200 bg-green-50 text-green-700"
                : "border-red-200 bg-red-50 text-red-700"
            )}
          >
            {actionResult.message}
          </div>
        )}
      </div>

      {/* ================================================================ */}
      {/* Outcome Tracking — Feature 20                                   */}
      {/* ================================================================ */}
      {["contacted", "engaged", "meeting_scheduled", "pilot_discussion", "pilot_signed", "active_pilot"].includes(company.status) && (
        <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <Target className="h-5 w-5 text-indigo-500" />
            <h3 className="text-lg font-semibold text-gray-900">Record Outcome</h3>
          </div>
          <p className="text-sm text-gray-500 mb-4">
            Close the loop — record what happened with this prospect to improve future scoring.
          </p>

          {outcomeSuccess && (
            <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
              {outcomeSuccess}
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => handleOutcome("won")}
              className="inline-flex items-center gap-2 rounded-lg border-2 border-green-200 bg-green-50 px-4 py-3 text-sm font-medium text-green-700 hover:bg-green-100 transition-colors"
            >
              <Trophy className="h-5 w-5" />
              <div className="text-left">
                <p className="font-semibold">Won</p>
                <p className="text-xs text-green-600">Converted to customer</p>
              </div>
            </button>

            <button
              onClick={() => handleOutcome("lost")}
              className="inline-flex items-center gap-2 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700 hover:bg-red-100 transition-colors"
            >
              <XCircle className="h-5 w-5" />
              <div className="text-left">
                <p className="font-semibold">Lost</p>
                <p className="text-xs text-red-600">Chose competitor or declined</p>
              </div>
            </button>

            <button
              onClick={() => handleOutcome("no_response")}
              className="inline-flex items-center gap-2 rounded-lg border-2 border-gray-200 bg-gray-50 px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors"
            >
              <Clock className="h-5 w-5" />
              <div className="text-left">
                <p className="font-semibold">No Response</p>
                <p className="text-xs text-gray-500">Never replied or went dark</p>
              </div>
            </button>
          </div>

          {outcomeModal && (
            <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
              <p className="text-sm font-medium text-gray-700 mb-2">
                Recording:{" "}
                <span className="capitalize font-semibold">
                  {outcomeModal === "no_response" ? "No Response" : outcomeModal}
                </span>
              </p>
              <textarea
                value={outcomeNotes}
                onChange={(e) => setOutcomeNotes(e.target.value)}
                placeholder="Optional notes — why did we win/lose? What did we learn?"
                rows={3}
                className="w-full rounded-md border border-gray-300 p-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <div className="mt-3 flex gap-2">
                <button
                  onClick={submitOutcome}
                  disabled={outcomeSubmitLoading}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                >
                  {outcomeSubmitLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                  {outcomeSubmitLoading ? "Saving..." : "Confirm"}
                </button>
                <button
                  onClick={() => { setOutcomeModal(null); setOutcomeNotes(""); }}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>
      )}

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
        {activeTab === "Contacts" && <ContactsTab contacts={company.contacts} companyId={id} onRefresh={fetchCompany} />}
        {activeTab === "Timeline" && <TimelineTab interactions={company.interactions} />}
        {activeTab === "Outreach" && <OutreachTab company={company} />}
      </div>

      {/* ================================================================ */}
      {/* Company Brief Generator — Feature 11                             */}
      {/* ================================================================ */}
      <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-indigo-500" />
            <h3 className="text-lg font-semibold text-gray-900">Sales Brief</h3>
          </div>
          <button
            onClick={generateBrief}
            disabled={briefLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {briefLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            {briefContent ? "Regenerate Brief" : "Generate Brief"}
          </button>
        </div>

        {!briefContent && !briefLoading && (
          <p className="mt-3 text-sm text-gray-400 italic">
            Generate a one-page sales brief compiled from all available research, contacts, pain signals, and technology data for this prospect.
          </p>
        )}

        {briefLoading && (
          <div className="mt-4 flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
            Compiling brief from prospect data…
          </div>
        )}

        {briefContent && (
          <>
            <div
              className="mt-4 rounded-lg border border-gray-100 bg-gray-50 p-4 text-sm text-gray-700 leading-relaxed"
              dangerouslySetInnerHTML={{ __html: briefContent }}
            />
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => {
                  const tmp = document.createElement("div");
                  tmp.innerHTML = briefContent;
                  navigator.clipboard.writeText(tmp.textContent || "").catch(() => {});
                }}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                <Clipboard className="h-3.5 w-3.5" />
                Copy to Clipboard
              </button>
              <button
                onClick={() => {
                  const win = window.open("", "_blank");
                  if (!win) return;
                  win.document.write(
                    `<html><head><title>${company.name} — Sales Brief</title><style>body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#111}</style></head><body>${briefContent}</body></html>`
                  );
                  win.document.close();
                  win.print();
                }}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                <Printer className="h-3.5 w-3.5" />
                Print
              </button>
            </div>
          </>
        )}
      </section>

      {/* ================================================================ */}
      {/* Deal Value — Feature 28                                          */}
      {/* ================================================================ */}
      {["qualified","outreach_pending","contacted","engaged","meeting_scheduled","pilot_discussion","pilot_signed","active_pilot","converted"].includes(company.status) && (
        <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="h-5 w-5 text-green-600" />
            <h3 className="text-lg font-semibold">Deal Value</h3>
          </div>
          <p className="text-sm text-gray-500 mb-4">
            Assign an estimated annual contract value to track pipeline value across your funnel.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
              <input
                type="number"
                value={dealValue}
                onChange={(e) => setDealValue(e.target.value)}
                placeholder="50000"
                min="0"
                className="w-40 rounded-lg border border-gray-300 pl-7 pr-3 py-2 text-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
              />
            </div>
            <button
              onClick={saveDealValue}
              disabled={dealValueSaving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {dealValueSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <DollarSign className="h-4 w-4" />}
              {dealValueSaving ? "Saving…" : "Save"}
            </button>
            {dealValue && Number(dealValue) > 0 && (
              <span className="text-sm text-gray-500">
                = <span className="font-medium text-gray-700">${Number(dealValue).toLocaleString()}</span>/yr estimated
              </span>
            )}
          </div>
          {dealValueSuccess && (
            <p className="mt-2 text-sm text-green-600">{dealValueSuccess}</p>
          )}
        </section>
      )}

      {/* ================================================================ */}
      {/* Meeting Prep — Feature 13 (only shown when meeting is scheduled)  */}
      {/* ================================================================ */}
      {company.status === "meeting_scheduled" && (
        <section className="rounded-xl border border-purple-200 bg-purple-50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <CalendarCheck className="h-5 w-5 text-purple-600" />
            <h3 className="text-lg font-semibold text-gray-900">Meeting Prep</h3>
            <span className="ml-auto rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-700">
              Meeting Scheduled
            </span>
          </div>

          <div className="space-y-5">
            {/* Talking Points */}
            {((company.pain_signals && company.pain_signals.length > 0) ||
              (company.personalization_hooks && company.personalization_hooks.length > 0)) && (
              <div>
                <h4 className="text-sm font-semibold text-gray-700">Talking Points</h4>
                <ul className="mt-2 space-y-1.5 text-sm text-gray-600">
                  {company.pain_signals?.map((p, i) => (
                    <li key={`pain-${i}`} className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                      <span>Address: {p}</span>
                    </li>
                  ))}
                  {company.personalization_hooks?.map((h, i) => (
                    <li key={`hook-${i}`} className="flex items-start gap-2">
                      <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-purple-400" />
                      <span>Reference: {h}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Technology Stack */}
            {company.technology_stack && company.technology_stack.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-gray-700">Their Technology</h4>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {company.technology_stack.map((t) => (
                    <span
                      key={t}
                      className="rounded-md bg-white px-2.5 py-0.5 text-xs font-medium text-gray-700 border border-purple-100 shadow-sm"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Decision Makers */}
            <div>
              <h4 className="text-sm font-semibold text-gray-700">Decision Makers</h4>
              {company.contacts?.filter((c) => c.is_decision_maker).length ? (
                <ul className="mt-2 space-y-2">
                  {company.contacts
                    .filter((c) => c.is_decision_maker)
                    .map((c) => (
                      <li key={c.id} className="flex items-center gap-2 text-sm text-gray-700">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-purple-100">
                          <User className="h-3.5 w-3.5 text-purple-600" />
                        </div>
                        <span>
                          <span className="font-medium">{c.full_name || "Unknown"}</span>
                          {c.title && (
                            <span className="text-gray-500"> — {c.title}</span>
                          )}
                          {c.email && (
                            <a
                              href={`mailto:${c.email}`}
                              className="ml-2 text-xs text-indigo-600 hover:underline"
                            >
                              {c.email}
                            </a>
                          )}
                        </span>
                      </li>
                    ))}
                </ul>
              ) : (
                <p className="mt-1 text-sm text-gray-400 italic">
                  No decision makers tagged yet. Mark contacts in the Contacts tab.
                </p>
              )}
            </div>

            {/* PQS recap */}
            <div className="rounded-lg border border-purple-100 bg-white px-4 py-3">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Prospect Score</p>
              <p className="mt-1 text-sm text-gray-700">
                PQS{" "}
                <span className="font-bold text-indigo-600">{company.pqs_total}/100</span>
                <span className="ml-2 text-gray-400">
                  · F {company.pqs_firmographic} · T {company.pqs_technographic} · Ti {company.pqs_timing} · E {company.pqs_engagement}
                </span>
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

// ===========================================================================
// Helpers
// ===========================================================================

function getClassificationLabel(pqs: number): string {
  if (pqs >= 85) return "Hot Prospect";
  if (pqs >= 70) return "High Priority";
  if (pqs >= 46) return "Qualified";
  if (pqs >= 30) return "Research Needed";
  return "Unqualified";
}

function getNextAction(status: string, pqs: number): string {
  switch (status) {
    case "discovered":
      return "Run Research → Qualification agents to score this company";
    case "researched":
      return "Run Qualification agent to compute full PQS score";
    case "qualified":
      return pqs >= 46
        ? "Generate a personalized outreach draft"
        : "Review — consider disqualifying due to low PQS";
    case "disqualified":
      return "No further action needed";
    case "outreach_pending":
      return "Review and approve the pending outreach draft";
    case "contacted":
      return "Monitor for engagement; follow-up sequence is active";
    case "engaged":
      return "Schedule a discovery call or meeting";
    case "meeting_scheduled":
      return "Prepare discovery call materials & Digitillis demo";
    case "pilot_discussion":
      return "Send pilot proposal and timeline";
    case "pilot_signed":
      return "Kick off the pilot program";
    case "active_pilot":
      return "Track pilot KPIs and document early wins";
    case "converted":
      return "Onboard and begin expansion conversations";
    case "not_interested":
      return "Closed — no further outreach";
    case "paused":
      return "Revisit in 30–60 days";
    case "bounced":
      return "Find an alternative contact email address";
    default:
      return "Review and determine next step";
  }
}

// ===========================================================================
// InsightsBox
// ===========================================================================

function InsightsBox({ company }: { company: CompanyDetail }) {
  const research = company.research;
  const classification = getClassificationLabel(company.pqs_total);
  const nextAction = getNextAction(company.status, company.pqs_total);
  const confidence = research?.confidence_level;

  // Gather the 3 best signals to surface
  const keySignals: string[] = [
    ...(company.personalization_hooks?.slice(0, 2) ?? []),
    ...(research?.opportunities?.slice(0, 2) ?? []),
    ...(company.pain_signals?.slice(0, 2) ?? []),
  ].filter(Boolean).slice(0, 3);

  const scoreBreakdown = [
    { label: "Firmographic", value: company.pqs_firmographic, max: 25 },
    { label: "Technographic", value: company.pqs_technographic, max: 25 },
    { label: "Timing", value: company.pqs_timing, max: 25 },
    { label: "Engagement", value: company.pqs_engagement, max: 25 },
  ];

  return (
    <div className="rounded-xl border-2 border-indigo-200 bg-gradient-to-br from-indigo-50 to-purple-50 p-5 lg:col-span-2">
      <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-900">
        <Sparkles className="h-4 w-4 text-indigo-500" />
        AI Prospect Assessment
      </h3>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        {/* Fit classification */}
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
            Fit Assessment
          </p>
          <div className={cn("text-xl font-bold", getPQSColor(company.pqs_total))}>
            {classification}
          </div>
          <p className="text-xs text-gray-500">
            PQS {company.pqs_total}/100
          </p>
          {confidence && (
            <span
              className={cn(
                "inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
                confidence === "high"
                  ? "bg-green-100 text-green-700"
                  : confidence === "medium"
                  ? "bg-amber-100 text-amber-700"
                  : "bg-gray-100 text-gray-600"
              )}
            >
              {confidence} research confidence
            </span>
          )}
          {/* Score breakdown */}
          <div className="mt-2 space-y-1">
            {scoreBreakdown.map((d) => (
              <div key={d.label} className="flex items-center gap-2 text-xs text-gray-500">
                <span className="w-20 shrink-0">{d.label}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200">
                  <div
                    className="h-full rounded-full bg-indigo-400"
                    style={{ width: `${(d.value / d.max) * 100}%` }}
                  />
                </div>
                <span className="w-8 text-right font-medium text-gray-700">
                  {d.value}/{d.max}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Why this prospect */}
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
            Why This Prospect
          </p>
          {keySignals.length > 0 ? (
            <ul className="space-y-2">
              {keySignals.map((signal, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-400" />
                  {signal}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-400 italic">
              Run the Research agent to unlock AI-generated insights for this prospect.
            </p>
          )}
        </div>

        {/* Recommended next action */}
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
            Recommended Next Action
          </p>
          <p className="text-sm font-medium leading-relaxed text-indigo-800">
            {nextAction}
          </p>
          {company.qualification_notes && (
            <div className="mt-3 rounded-md bg-white/70 px-3 py-2 text-xs text-gray-600 border border-indigo-100">
              <span className="font-medium text-gray-700">Qualification note: </span>
              {company.qualification_notes}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// FirmographicsCard
// ===========================================================================

function FirmographicsCard({ company }: { company: CompanyDetail }) {
  const hq = [company.city, company.state].filter(Boolean).join(", ");

  const plantCount =
    (company.manufacturing_profile as Record<string, unknown> | undefined)?.plant_count ??
    (company.manufacturing_profile as Record<string, unknown> | undefined)?.facilities_count ??
    null;

  const rows: { label: string; value: string; icon?: ReactNode }[] = [
    hq ? { label: "HQ", value: hq, icon: <MapPin className="h-3.5 w-3.5" /> } : null,
    company.territory ? { label: "Territory", value: company.territory } : null,
    company.employee_count
      ? {
          label: "Employees",
          value: company.employee_count.toLocaleString(),
          icon: <Users className="h-3.5 w-3.5" />,
        }
      : null,
    company.revenue_range
      ? { label: "Revenue", value: company.revenue_range, icon: <DollarSign className="h-3.5 w-3.5" /> }
      : company.estimated_revenue
      ? {
          label: "Est. Revenue",
          value: `$${(company.estimated_revenue / 1e6).toFixed(0)}M`,
          icon: <DollarSign className="h-3.5 w-3.5" />,
        }
      : null,
    company.founded_year
      ? { label: "Founded", value: String(company.founded_year) }
      : null,
    typeof company.is_private === "boolean"
      ? { label: "Type", value: company.is_private ? "Private" : "Public" }
      : null,
    plantCount ? { label: "Plants", value: String(plantCount) } : null,
    company.phone ? { label: "Phone", value: company.phone, icon: <Phone className="h-3.5 w-3.5" /> } : null,
  ].filter(Boolean) as { label: string; value: string; icon?: React.ReactNode }[];

  const websiteUrl = company.website || (company.domain ? `https://${company.domain}` : null);

  if (!rows.length && !websiteUrl && !company.linkedin_url) return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-900">
        <Building2 className="h-4 w-4 text-gray-500" />
        Company Profile
      </h3>

      <dl className="space-y-2.5 text-sm">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between gap-2">
            <dt className="flex items-center gap-1.5 text-gray-500">
              {row.icon}
              {row.label}
            </dt>
            <dd className="text-right font-medium text-gray-900">{row.value}</dd>
          </div>
        ))}
      </dl>

      {(websiteUrl || company.linkedin_url) && (
        <div className="mt-3 flex flex-wrap gap-3 border-t border-gray-100 pt-3">
          {websiteUrl && (
            <a
              href={websiteUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-indigo-600 hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              Website
            </a>
          )}
          {company.linkedin_url && (
            <a
              href={company.linkedin_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
            >
              <Linkedin className="h-3 w-3" />
              LinkedIn
            </a>
          )}
        </div>
      )}
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
      {/* AI Insights */}
      <InsightsBox company={company} />

      {/* Firmographics */}
      <FirmographicsCard company={company} />

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

    </div>
  );
}

// ===========================================================================
// Tab 2 - Contacts
// ===========================================================================

const PERSONA_OPTIONS = [
  { value: "vp_ops", label: "VP Operations" },
  { value: "coo", label: "COO" },
  { value: "plant_manager", label: "Plant Manager" },
  { value: "digital_transformation", label: "Digital Transformation" },
  { value: "vp_supply_chain", label: "VP Supply Chain" },
  { value: "director_ops", label: "Director of Operations" },
  { value: "cio", label: "CIO / CTO" },
];

const SENIORITY_OPTIONS = ["C-Level", "VP", "Director", "Manager", "Senior", "Individual Contributor"];

function ContactsTab({
  contacts,
  companyId,
  onRefresh,
}: {
  contacts: Contact[];
  companyId: string;
  onRefresh: () => void;
}) {
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    full_name: "",
    title: "",
    email: "",
    phone: "",
    linkedin_url: "",
    seniority: "",
    persona_type: "",
    is_decision_maker: false,
  });

  const handleAdd = async () => {
    if (!form.full_name.trim() && !form.email.trim()) return;
    setSaving(true);
    try {
      await createContact(companyId, {
        ...form,
        full_name: form.full_name.trim() || undefined,
        title: form.title.trim() || undefined,
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
        linkedin_url: form.linkedin_url.trim() || undefined,
        seniority: form.seniority || undefined,
        persona_type: form.persona_type || undefined,
      });
      setAddModalOpen(false);
      setForm({ full_name: "", title: "", email: "", phone: "", linkedin_url: "", seniority: "", persona_type: "", is_decision_maker: false });
      onRefresh();
    } catch {
      // silent
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {contacts.length} contact{contacts.length !== 1 ? "s" : ""}
        </p>
        <button
          onClick={() => setAddModalOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus className="h-4 w-4" />
          Add Contact
        </button>
      </div>

      {/* Contact cards */}
      {contacts.length === 0 ? (
        <div className="py-12 text-center text-sm text-gray-400">
          No contacts found. Add one manually or run the Discovery agent.
        </div>
      ) : (
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
                    {contact.seniority && (
                      <p className="text-xs text-gray-400">{contact.seniority}</p>
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
                  <a
                    href={`mailto:${contact.email}`}
                    className="flex items-center gap-2 text-gray-600 hover:text-indigo-600"
                  >
                    <Mail className="h-3.5 w-3.5 text-gray-400" />
                    <span className="truncate">{contact.email}</span>
                  </a>
                )}
                {contact.phone && (
                  <div className="flex items-center gap-2 text-gray-600">
                    <Phone className="h-3.5 w-3.5 text-gray-400" />
                    <span>{contact.phone}</span>
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
      )}

      {/* Add Contact Modal */}
      {addModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">Add Contact</h3>

            <div className="space-y-3">
              {/* Name + Title row */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">
                    Full Name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.full_name}
                    onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                    placeholder="Jane Smith"
                    className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Title</label>
                  <input
                    type="text"
                    value={form.title}
                    onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                    placeholder="VP of Operations"
                    className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>

              {/* Email + Phone row */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Email</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                    placeholder="jane@company.com"
                    className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Phone</label>
                  <input
                    type="tel"
                    value={form.phone}
                    onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                    placeholder="+1 312 555 0100"
                    className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>

              {/* LinkedIn */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">LinkedIn URL</label>
                <input
                  type="url"
                  value={form.linkedin_url}
                  onChange={(e) => setForm((f) => ({ ...f, linkedin_url: e.target.value }))}
                  placeholder="https://linkedin.com/in/janesmith"
                  className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              {/* Seniority + Persona row */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Seniority</label>
                  <select
                    value={form.seniority}
                    onChange={(e) => setForm((f) => ({ ...f, seniority: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  >
                    <option value="">Select…</option>
                    {SENIORITY_OPTIONS.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Persona</label>
                  <select
                    value={form.persona_type}
                    onChange={(e) => setForm((f) => ({ ...f, persona_type: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  >
                    <option value="">Select…</option>
                    {PERSONA_OPTIONS.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Decision maker checkbox */}
              <label className="flex cursor-pointer items-center gap-2.5 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_decision_maker}
                  onChange={(e) => setForm((f) => ({ ...f, is_decision_maker: e.target.checked }))}
                  className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                Mark as Decision Maker
                <Star className="h-3.5 w-3.5 text-yellow-400" />
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => { setAddModalOpen(false); }}
                className="rounded-md border border-gray-300 px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAdd}
                disabled={saving || (!form.full_name.trim() && !form.email.trim())}
                className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Add Contact"}
              </button>
            </div>
          </div>
        </div>
      )}
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

  const { reminders, dismissReminder } = useReminders();
  const companyReminders = reminders.filter((r) => r.companyId === company.id);

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

      {/* ---- Reminders Section ---- */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Bell className="h-4 w-4 text-orange-500" />
            Reminders
          </h3>
          {companyReminders.length === 0 && (
            <p className="text-xs text-gray-400">No reminders set for this company.</p>
          )}
        </div>

        {companyReminders.length > 0 && (
          <div className="space-y-2 mb-4">
            {companyReminders.map((r) => {
              const isDue = new Date(r.dueDate) <= new Date();
              return (
                <div
                  key={r.id}
                  className={cn(
                    "flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5",
                    isDue
                      ? "border-orange-200 bg-orange-50"
                      : "border-gray-200 bg-gray-50"
                  )}
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-800">{r.note}</p>
                    <p
                      className={cn(
                        "mt-0.5 text-xs",
                        isDue ? "font-semibold text-orange-600" : "text-gray-400"
                      )}
                    >
                      {isDue ? "Due: " : ""}
                      {new Date(r.dueDate).toLocaleDateString(undefined, {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                      })}
                    </p>
                  </div>
                  <button
                    onClick={() => dismissReminder(r.id)}
                    className="shrink-0 rounded px-2 py-0.5 text-xs text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                    title="Dismiss reminder"
                  >
                    Dismiss
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
