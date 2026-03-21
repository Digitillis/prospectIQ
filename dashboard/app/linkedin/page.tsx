"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Linkedin,
  ExternalLink,
  Copy,
  Check,
  Pencil,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { runAgent, getLinkedInMessages, updateLinkedInStatus } from "@/lib/api";
import type { LinkedInContact, LinkedInIntel } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

type LinkedInStatus =
  | "not_sent"
  | "connection_sent"
  | "accepted"
  | "dm_sent"
  | "responded"
  | "meeting_booked";

const STATUS_LABELS: Record<LinkedInStatus, string> = {
  not_sent: "Not Sent",
  connection_sent: "Connection Sent",
  accepted: "Accepted",
  dm_sent: "DM Sent",
  responded: "Responded",
  meeting_booked: "Meeting Booked",
};

const STATUS_COLORS: Record<LinkedInStatus, string> = {
  not_sent: "text-slate-400",
  connection_sent: "text-blue-400",
  accepted: "text-teal-400",
  dm_sent: "text-violet-400",
  responded: "text-amber-400",
  meeting_booked: "text-green-400",
};

// ─────────────────────────────────────────────────────────────────────────────
// Tier badge
// ─────────────────────────────────────────────────────────────────────────────

function TierBadge({ tier }: { tier?: string }) {
  if (!tier) return null;
  const colors: Record<string, string> = {
    "fb_1": "bg-emerald-900/40 text-emerald-300 border-emerald-700",
    "fb_2": "bg-emerald-900/30 text-emerald-400 border-emerald-800",
    "mfg_1": "bg-blue-900/40 text-blue-300 border-blue-700",
    "mfg_2": "bg-blue-900/30 text-blue-400 border-blue-800",
    "1": "bg-blue-900/40 text-blue-300 border-blue-700",
    "2": "bg-blue-900/30 text-blue-400 border-blue-800",
  };
  const cls = colors[tier] ?? "bg-slate-800 text-slate-300 border-slate-600";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      Tier {tier}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Copy button with checkmark flash
// ─────────────────────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Fallback for non-secure contexts
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-400" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Message block (with inline edit)
// ─────────────────────────────────────────────────────────────────────────────

function MessageBlock({
  label,
  text,
}: {
  label: string;
  text: string;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(text);

  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
          {label}
        </span>
        <div className="flex items-center gap-1">
          <CopyButton text={value} />
          <button
            onClick={() => setEditing((e) => !e)}
            className={`flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors hover:bg-white/10 hover:text-white ${
              editing ? "text-amber-400" : "text-slate-400"
            }`}
            title={editing ? "Close editor" : "Edit message"}
          >
            <Pencil className="h-3.5 w-3.5" />
            {editing ? "Done" : "Edit"}
          </button>
        </div>
      </div>

      {editing ? (
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-full rounded bg-black/30 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          rows={5}
        />
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
          {value}
        </p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Intel panel
// ─────────────────────────────────────────────────────────────────────────────

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
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {open ? "Hide Intel" : "View Intel"}
      </button>

      {open && (
        <div className="mt-2 rounded-lg bg-white/5 border border-white/10 p-3 text-xs space-y-3">
          {/* WHY THIS MESSAGE */}
          {intel.personalization_notes && (
            <div>
              <div className="font-semibold text-slate-400 mb-1 uppercase tracking-wide text-[10px]">
                WHY THIS MESSAGE
              </div>
              <p className="text-slate-300">{intel.personalization_notes}</p>
            </div>
          )}

          {/* COMPANY RESEARCH */}
          {(intel.research?.products_services?.length ||
            intel.research?.recent_news?.length ||
            intel.research?.pain_points?.length ||
            (intel.company?.pain_signals?.length ?? 0) > 0 ||
            intel.research?.known_systems?.length) ? (
            <div>
              <div className="font-semibold text-slate-400 mb-1 uppercase tracking-wide text-[10px]">
                COMPANY RESEARCH
              </div>
              <div className="space-y-1 text-slate-400">
                {(intel.research?.products_services?.length ?? 0) > 0 && (
                  <p>Products: {intel.research!.products_services!.join(", ")}</p>
                )}
                {(intel.research?.recent_news?.length ?? 0) > 0 && (
                  <p>Recent: {intel.research!.recent_news!.join("; ")}</p>
                )}
                {((intel.research?.pain_points?.length ?? 0) > 0 ||
                  (intel.company?.pain_signals?.length ?? 0) > 0) && (
                  <p>
                    Pain points:{" "}
                    {(
                      intel.research?.pain_points ||
                      intel.company?.pain_signals ||
                      []
                    ).join(", ")}
                  </p>
                )}
                {(intel.research?.known_systems?.length ?? 0) > 0 && (
                  <p>Systems: {intel.research!.known_systems!.join(", ")}</p>
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
              <div className="font-semibold text-slate-400 mb-1 uppercase tracking-wide text-[10px]">
                CONTACT
              </div>
              <div className="space-y-0.5 text-slate-400">
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
              <div className="font-semibold text-slate-400 mb-1 uppercase tracking-wide text-[10px]">
                COMPANY
              </div>
              <div className="space-y-0.5 text-slate-400">
                {intel.company?.industry && (
                  <p>Industry: {intel.company.industry}</p>
                )}
                {intel.company?.employee_count && (
                  <p>
                    Employees:{" "}
                    {intel.company.employee_count.toLocaleString()}
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
                <p>{intel.company?.is_public ? "Public" : "Private"}</p>
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

// ─────────────────────────────────────────────────────────────────────────────
// Contact card
// ─────────────────────────────────────────────────────────────────────────────

function ContactCard({ item }: { item: LinkedInContact }) {
  const { contact, company, drafts, intel } = item;
  const [status, setStatus] = useState<LinkedInStatus>(
    (contact.linkedin_status as LinkedInStatus) || "not_sent"
  );
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const handleStatusChange = async (newStatus: LinkedInStatus) => {
    setStatus(newStatus);
    setSaving(true);
    try {
      await updateLinkedInStatus(contact.id, newStatus, notes);
    } catch (err) {
      console.error("Failed to update LinkedIn status:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleNotesSave = async () => {
    if (!notes.trim()) return;
    setSaving(true);
    try {
      await updateLinkedInStatus(contact.id, status, notes);
    } catch (err) {
      console.error("Failed to save notes:", err);
    } finally {
      setSaving(false);
    }
  };

  const connectionNote = drafts["linkedin_connection"];
  const openingDm = drafts["linkedin_dm_opening"];
  const followupDm = drafts["linkedin_dm_followup"];

  return (
    <div className="rounded-xl border border-white/10 bg-digitillis-card p-5">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white truncate">
              {contact.full_name || `${contact.first_name ?? ""} ${contact.last_name ?? ""}`.trim() || "Unknown"}
            </span>
            <TierBadge tier={company.tier} />
            {contact.is_decision_maker && (
              <span className="rounded border border-amber-700 bg-amber-900/30 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                DM
              </span>
            )}
          </div>
          <div className="mt-0.5 text-sm text-slate-400">
            {contact.title} &middot; {company.name}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            PQS {company.pqs_total}
            {company.sub_sector ? ` · ${company.sub_sector}` : ""}
          </div>
        </div>

        {/* LinkedIn profile link */}
        {contact.linkedin_url && (
          <a
            href={contact.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-blue-700 bg-blue-900/30 px-3 py-1.5 text-xs font-medium text-blue-300 transition-colors hover:bg-blue-800/40 hover:text-blue-200"
          >
            <Linkedin className="h-3.5 w-3.5" />
            Profile
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      {/* Messages */}
      <div className="space-y-3">
        {connectionNote && (
          <MessageBlock label="Connection Note" text={connectionNote.body} />
        )}
        {openingDm && (
          <MessageBlock label="Opening DM" text={openingDm.body} />
        )}
        {followupDm && (
          <MessageBlock label="Follow-up DM" text={followupDm.body} />
        )}
      </div>

      {/* Intel panel */}
      <IntelPanel intel={intel} />

      {/* Status + Notes */}
      <div className="mt-4 border-t border-white/10 pt-4">
        <div className="mb-3">
          <div className="mb-2 text-xs font-medium text-slate-500">Status</div>
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(STATUS_LABELS) as LinkedInStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => handleStatusChange(s)}
                disabled={saving}
                className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-all ${
                  status === s
                    ? "border-blue-500 bg-blue-500/20 text-blue-300"
                    : "border-white/10 text-slate-500 hover:border-white/20 hover:text-slate-300"
                }`}
              >
                {STATUS_LABELS[s]}
              </button>
            ))}
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-500" />}
          </div>
          {status !== "not_sent" && (
            <div className={`mt-1 text-xs ${STATUS_COLORS[status]}`}>
              {STATUS_LABELS[status]}
            </div>
          )}
        </div>

        {/* Notes */}
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">
            Notes (conversation context)
          </div>
          <div className="flex gap-2">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes about the conversation..."
              rows={2}
              className="flex-1 rounded bg-black/30 px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            {notes.trim() && (
              <button
                onClick={handleNotesSave}
                disabled={saving}
                className="self-end rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
              >
                Save
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function LinkedInPage() {
  const [items, setItems] = useState<LinkedInContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [verticalFilter, setVerticalFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);

  const fetchMessages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (statusFilter && statusFilter !== "all") params.status = statusFilter;
      if (verticalFilter && verticalFilter !== "all") {
        // Map vertical label to tier prefix
        params.tier = verticalFilter === "fb" ? "fb_1" : "mfg_1";
      }
      const res = await getLinkedInMessages(params);
      setItems(res.data);
    } catch (err) {
      console.error(err);
      setError("Failed to load LinkedIn messages.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, verticalFilter]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      await runAgent("linkedin", { limit: 20, regenerate: false });
      await fetchMessages();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to generate LinkedIn messages.";
      setError(message);
    } finally {
      setGenerating(false);
    }
  };

  // Derive vertical display filter from tier prefix
  const filteredItems =
    verticalFilter === "all"
      ? items
      : items.filter((item) => {
          const tier = item.company.tier ?? "";
          if (verticalFilter === "fb") return tier.startsWith("fb");
          if (verticalFilter === "mfg") return !tier.startsWith("fb");
          return true;
        });

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-white/10 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Linkedin className="h-6 w-6 text-blue-400" />
            <div>
              <h1 className="text-xl font-semibold text-white">LinkedIn Outreach</h1>
              <p className="text-xs text-slate-500">
                Copy-paste personalized messages for each contact
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchMessages}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-400 transition-colors hover:bg-white/5 hover:text-white disabled:opacity-50"
              title="Refresh"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-60"
            >
              {generating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Linkedin className="h-4 w-4" />
              )}
              {generating ? "Generating..." : "Generate Messages"}
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {/* Status filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">Status:</span>
            <div className="flex flex-wrap gap-1">
              {["all", "not_sent", "connection_sent", "accepted", "dm_sent", "responded", "meeting_booked"].map(
                (s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                      statusFilter === s
                        ? "bg-blue-600 text-white"
                        : "bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white"
                    }`}
                  >
                    {s === "all"
                      ? "All"
                      : STATUS_LABELS[s as LinkedInStatus] ?? s}
                  </button>
                )
              )}
            </div>
          </div>

          {/* Vertical filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">Vertical:</span>
            <div className="flex gap-1">
              {[
                { value: "all", label: "All" },
                { value: "fb", label: "F&B" },
                { value: "mfg", label: "Mfg" },
              ].map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setVerticalFilter(value)}
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                    verticalFilter === value
                      ? "bg-blue-600 text-white"
                      : "bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Count badge */}
          {!loading && (
            <span className="ml-auto text-xs text-slate-500">
              {filteredItems.length} contact{filteredItems.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-6 mt-4 rounded-lg border border-red-700 bg-red-900/20 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-slate-500" />
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Linkedin className="mb-4 h-12 w-12 text-slate-700" />
            <p className="text-slate-400">No LinkedIn messages yet.</p>
            <p className="mt-1 text-sm text-slate-600">
              Click "Generate Messages" to create personalized LinkedIn messages
              for your qualified contacts.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filteredItems.map((item) => (
              <ContactCard key={item.contact.id} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
