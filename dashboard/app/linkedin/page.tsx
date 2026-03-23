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

// ─────────────────────────────────────────────────────────────────────────────
// Tier badge
// ─────────────────────────────────────────────────────────────────────────────

function TierBadge({ tier }: { tier?: string }) {
  if (!tier) return null;
  return (
    <span className="rounded px-1.5 py-0.5 text-[10px] font-medium text-gray-500 bg-gray-100">
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
      className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-600" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {copied ? <span className="text-green-600">Copied!</span> : "Copy"}
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
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-medium tracking-widest uppercase text-gray-400 dark:text-gray-500">
          {label}
        </span>
        <div className="flex items-center gap-3">
          <CopyButton text={value} />
          <button
            onClick={() => setEditing((e) => !e)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 transition-colors"
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
          className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
          rows={5}
        />
      ) : (
        <div className="bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-md p-3 text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">
          {value}
        </div>
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
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 transition-colors"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {open ? "Hide Intel" : "View Intel"}
      </button>

      {open && (
        <div className="mt-2 rounded-md bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700 p-3 text-xs space-y-3">
          {/* RESEARCH SUMMARY */}
          {intel.company?.research_summary && (
            <div>
              <div className="font-medium text-gray-400 dark:text-gray-500 mb-1 uppercase tracking-widest text-[10px]">
                Research Summary
              </div>
              <p className="text-gray-600 dark:text-gray-400 whitespace-pre-wrap">{intel.company.research_summary}</p>
            </div>
          )}

          {/* KEY FINDINGS */}
          {(intel.research?.products_services?.length ||
            intel.research?.recent_news?.length ||
            intel.research?.pain_points?.length ||
            (intel.company?.pain_signals?.length ?? 0) > 0 ||
            intel.research?.known_systems?.length) ? (
            <div>
              <div className="font-medium text-gray-400 dark:text-gray-500 mb-1 uppercase tracking-widest text-[10px]">
                Key Findings
              </div>
              <div className="space-y-1 text-gray-600 dark:text-gray-400">
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
              <div className="font-medium text-gray-400 dark:text-gray-500 mb-1 uppercase tracking-widest text-[10px]">
                Contact
              </div>
              <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
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
              <div className="font-medium text-gray-400 dark:text-gray-500 mb-1 uppercase tracking-widest text-[10px]">
                Company
              </div>
              <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
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
  const [notes, setNotes] = useState(contact.linkedin_notes || "");
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
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-5">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
              {contact.full_name || `${contact.first_name ?? ""} ${contact.last_name ?? ""}`.trim() || "Unknown"}
            </span>
            <TierBadge tier={company.tier} />
            {contact.is_decision_maker && (
              <span className="rounded px-1.5 py-0.5 text-[10px] font-medium text-gray-500 bg-gray-100">
                DM
              </span>
            )}
          </div>
          <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            {contact.title} &middot; {company.name}
          </div>
          <div className="mt-0.5 text-xs font-mono text-gray-400 dark:text-gray-500">
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
            className="flex shrink-0 items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2.5 py-1 text-xs text-gray-500 dark:text-gray-400 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100"
          >
            <Linkedin className="h-3.5 w-3.5" />
            Open LI
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      {/* Messages */}
      <div className="space-y-4">
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
      <div className="mt-4 border-t border-gray-100 dark:border-gray-700 pt-4">
        <div className="mb-3">
          <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
            Status
          </div>
          <div className="flex flex-wrap gap-1">
            {(Object.keys(STATUS_LABELS) as LinkedInStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => handleStatusChange(s)}
                disabled={saving}
                className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                  status === s
                    ? "bg-gray-900 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {STATUS_LABELS[s]}
              </button>
            ))}
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}
          </div>
        </div>

        {/* Notes */}
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
            Notes
          </div>
          <div className="flex gap-2">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes about the conversation..."
              rows={2}
              className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 px-2 py-1.5 text-xs text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-600 bg-white dark:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
            />
            {notes.trim() && (
              <button
                onClick={handleNotesSave}
                disabled={saving}
                className="self-end rounded-md px-2 py-1 text-xs font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
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
  const [genLimit, setGenLimit] = useState(20);
  const [genMode, setGenMode] = useState<"all" | "dm_only">("all");
  const [genRegenerate, setGenRegenerate] = useState(false);

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
      await runAgent("linkedin", { limit: genLimit, regenerate: genRegenerate, mode: genMode });
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
    <div className="flex h-full flex-col bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-6 py-4">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
                LinkedIn Outreach
              </h1>
              {!loading && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {filteredItems.length} contact{filteredItems.length !== 1 ? "s" : ""}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={fetchMessages}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-2.5 py-1.5 text-xs text-gray-500 dark:text-gray-400 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50"
                title="Refresh"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              </button>
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-60"
              >
                {generating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Linkedin className="h-3.5 w-3.5" />
                )}
                {generating ? "Generating..." : "Generate Messages"}
              </button>
            </div>
          </div>

          {/* Filters */}
          <div className="mt-3 flex flex-wrap items-center gap-4">
            {/* Status filter */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-400 dark:text-gray-500">Status</span>
              <div className="flex flex-wrap gap-1">
                {["all", "not_sent", "connection_sent", "accepted", "dm_sent", "responded", "meeting_booked"].map(
                  (s) => (
                    <button
                      key={s}
                      onClick={() => setStatusFilter(s)}
                      className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                        statusFilter === s
                          ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                          : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
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
              <span className="text-xs text-gray-400 dark:text-gray-500">Vertical</span>
              <div className="flex gap-1">
                {[
                  { value: "all", label: "All" },
                  { value: "fb", label: "F&B" },
                  { value: "mfg", label: "Mfg" },
                ].map(({ value, label }) => (
                  <button
                    key={value}
                    onClick={() => setVerticalFilter(value)}
                    className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                      verticalFilter === value
                        ? "bg-gray-900 text-white"
                        : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Generation options */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-400 dark:text-gray-500">Limit</span>
              <select
                value={genLimit}
                onChange={(e) => setGenLimit(Number(e.target.value))}
                className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-600 dark:text-gray-300 focus:outline-none"
              >
                {[5, 10, 20, 50, 100].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-400 dark:text-gray-500">Mode</span>
              <div className="flex gap-1">
                {[
                  { value: "all", label: "All Messages" },
                  { value: "dm_only", label: "DM Only" },
                ].map(({ value, label }) => (
                  <button
                    key={value}
                    onClick={() => setGenMode(value as "all" | "dm_only")}
                    className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                      genMode === value
                        ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                        : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={genRegenerate}
                  onChange={(e) => setGenRegenerate(e.target.checked)}
                  className="rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500 h-3.5 w-3.5"
                />
                <span className="text-xs text-gray-500 dark:text-gray-400">Regenerate existing</span>
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="max-w-4xl mx-auto w-full px-6 mt-4">
          <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
            {error}
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="max-w-4xl mx-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Linkedin className="mb-3 h-8 w-8 text-gray-300" />
              <p className="text-sm text-gray-500">No LinkedIn messages yet.</p>
              <p className="mt-1 text-xs text-gray-400">
                Click &ldquo;Generate Messages&rdquo; to create personalized LinkedIn messages
                for your qualified contacts.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {filteredItems.map((item) => (
                <ContactCard key={item.contact.id} item={item} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
