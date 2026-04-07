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
  Search,
} from "lucide-react";
import { runAgent, getLinkedInMessages, updateLinkedInStatus, getLinkedInContacts } from "@/lib/api";
import type { LinkedInContact, LinkedInIntel, LinkedInContactRaw } from "@/lib/api";

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

function ContactCard({
  item,
  selected,
  onToggle,
}: {
  item: LinkedInContact;
  selected: boolean;
  onToggle: (id: string) => void;
}) {
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
    <div className={`bg-white dark:bg-gray-900 border rounded-lg p-5 transition-colors ${selected ? "border-blue-400 dark:border-blue-500 ring-1 ring-blue-200 dark:ring-blue-800" : "border-gray-200 dark:border-gray-700"}`}>
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        {/* Checkbox */}
        <div className="flex items-start gap-3 flex-1 min-w-0">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggle(contact.id)}
          className="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500 shrink-0 cursor-pointer"
          title="Select contact"
        />
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
        </div>{/* end flex-1 + checkbox wrapper */}

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

        {/* Event Timeline */}
        {(() => {
          const events = [
            { label: "Connection Sent", ts: contact.linkedin_connection_sent_at },
            { label: "Accepted", ts: contact.linkedin_accepted_at },
            { label: "DM Sent", ts: contact.linkedin_dm_sent_at },
            { label: "Responded", ts: contact.linkedin_responded_at },
            { label: "Meeting Booked", ts: contact.linkedin_meeting_booked_at },
          ].filter((e) => e.ts);
          if (events.length === 0) return null;
          return (
            <div className="mb-3">
              <div className="mb-1.5 text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
                Timeline
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {events.map((e) => (
                  <div key={e.label} className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-gray-400 dark:bg-gray-500 shrink-0" />
                    <span className="font-medium text-gray-600 dark:text-gray-300">{e.label}</span>
                    <span className="tabular-nums">{new Date(e.ts!).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
                    <span className="text-gray-400 dark:text-gray-600 tabular-nums">{new Date(e.ts!).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}

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
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const [bulkSuccess, setBulkSuccess] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [showLinksPanel, setShowLinksPanel] = useState(false);
  const [viewMode, setViewMode] = useState<"messages" | "contacts">("contacts");
  const [rawContacts, setRawContacts] = useState<LinkedInContactRaw[]>([]);
  const [rawTotal, setRawTotal] = useState(0);
  const [rawOffset, setRawOffset] = useState(0);
  const RAW_PAGE_SIZE = 100;

  const fetchMessages = useCallback(async () => {
    if (viewMode !== "messages") return;
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (statusFilter && statusFilter !== "all") params.status = statusFilter;
      if (verticalFilter && verticalFilter !== "all") {
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
  }, [statusFilter, verticalFilter, viewMode]);

  const fetchContacts = useCallback(async (offset = 0) => {
    if (viewMode !== "contacts") return;
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {
        limit: String(RAW_PAGE_SIZE),
        offset: String(offset),
      };
      if (statusFilter && statusFilter !== "all") params.status = statusFilter;
      const res = await getLinkedInContacts(params);
      setRawContacts(res.data);
      setRawTotal(res.total);
      setRawOffset(offset);
    } catch (err) {
      console.error(err);
      setError("Failed to load contacts.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, viewMode]);

  useEffect(() => {
    if (viewMode === "messages") fetchMessages();
    else fetchContacts(0);
  }, [viewMode, fetchMessages, fetchContacts]);

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

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === allSelectableContacts.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(allSelectableContacts.map((c) => c.id)));
    }
  };

  // Only open URLs that look like valid LinkedIn profile pages (contain /in/)
  const isValidLinkedInUrl = (url: string) =>
    /linkedin\.com\/in\//i.test(url);

  const openSelectedTabs = () => {
    const urls = selectedContacts
      .map((c) => c.linkedin_url!)
      .filter(isValidLinkedInUrl);
    if (urls.length === 0) return;
    // Stagger opens by 150ms — Chrome allows multiple window.open if spaced out
    urls.forEach((url, i) => {
      setTimeout(() => window.open(url, "_blank", "noopener,noreferrer"), i * 150);
    });
    setShowLinksPanel(true);
  };

  const markSelectedConnectionSent = async () => {
    const targets = allSelectableContacts.filter((c) => selectedIds.has(c.id));
    if (targets.length === 0) return;
    setBulkUpdating(true);
    setBulkError(null);
    setBulkSuccess(false);
    try {
      await Promise.all(
        targets.map((c) =>
          updateLinkedInStatus(c.id, "connection_sent", c.linkedin_notes || "")
        )
      );
      setBulkSuccess(true);
      setTimeout(() => setBulkSuccess(false), 3000);
      setSelectedIds(new Set());
      setShowLinksPanel(false);
      if (viewMode === "messages") await fetchMessages();
      else await fetchContacts(rawOffset);
    } catch (err) {
      console.error("Bulk update failed:", err);
      setBulkError("Update failed — check console");
    } finally {
      setBulkUpdating(false);
    }
  };

  // Apply search filter to raw contacts
  const filteredRawContacts = rawContacts.filter((item) => {
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const name = (item.contact.full_name || `${item.contact.first_name ?? ""} ${item.contact.last_name ?? ""}`).toLowerCase();
      const company = (item.company.name || "").toLowerCase();
      const title = (item.contact.title || "").toLowerCase();
      if (!name.includes(q) && !company.includes(q) && !title.includes(q)) return false;
    }
    return true;
  });

  // Apply search + vertical filter on client side
  const filteredItems = items.filter((item) => {
    // Vertical filter
    if (verticalFilter !== "all") {
      const tier = item.company.tier ?? "";
      if (verticalFilter === "fb" && !tier.startsWith("fb")) return false;
      if (verticalFilter === "mfg" && tier.startsWith("fb")) return false;
    }
    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const name = (item.contact.full_name || `${item.contact.first_name ?? ""} ${item.contact.last_name ?? ""}`).toLowerCase();
      const company = (item.company.name || "").toLowerCase();
      const title = (item.contact.title || "").toLowerCase();
      if (!name.includes(q) && !company.includes(q) && !title.includes(q)) return false;
    }
    return true;
  });

  // All selectable contacts (works for both view modes) — must be after both filtered lists
  const allSelectableContacts = viewMode === "messages"
    ? filteredItems.map((i) => ({ id: i.contact.id, linkedin_url: i.contact.linkedin_url, linkedin_notes: i.contact.linkedin_notes }))
    : filteredRawContacts.map((i) => ({ id: i.contact.id, linkedin_url: i.contact.linkedin_url, linkedin_notes: i.contact.linkedin_notes }));

  const selectedContacts = allSelectableContacts.filter((c) => selectedIds.has(c.id) && c.linkedin_url);

  return (
    <div className="flex h-full flex-col bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-6 py-4">
        <div className="max-w-4xl mx-auto space-y-3">
          {/* Row 1: Title + View Toggle + Search */}
          <div className="flex items-center gap-3">
            <div className="shrink-0">
              <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
                LinkedIn Outreach
              </h1>
              {!loading && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {viewMode === "contacts"
                    ? `${filteredRawContacts.length} of ${rawTotal} contacts`
                    : `${filteredItems.length} contact${filteredItems.length !== 1 ? "s" : ""}`}
                </p>
              )}
            </div>
            {/* View mode toggle */}
            <div className="flex rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden shrink-0">
              <button
                onClick={() => { setViewMode("contacts"); setSelectedIds(new Set()); }}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${viewMode === "contacts" ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900" : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"}`}
              >
                All Contacts
              </button>
              <button
                onClick={() => { setViewMode("messages"); setSelectedIds(new Set()); }}
                className={`px-3 py-1.5 text-xs font-medium transition-colors border-l border-gray-200 dark:border-gray-700 ${viewMode === "messages" ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900" : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"}`}
              >
                With Messages
              </button>
            </div>
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name, company, or title..."
                className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 pl-8 pr-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
              />
            </div>
            <button
              onClick={() => viewMode === "messages" ? fetchMessages() : fetchContacts(rawOffset)}
              disabled={loading}
              className="flex shrink-0 items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-2.5 py-1.5 text-xs text-gray-500 dark:text-gray-400 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50"
              title="Refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {/* Row 1b: Selection controls */}
          {!loading && allSelectableContacts.length > 0 && (
            <div className="flex items-center gap-3 flex-wrap">
              {/* Select all checkbox */}
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={selectedIds.size === allSelectableContacts.length && allSelectableContacts.length > 0}
                  ref={(el) => {
                    if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < allSelectableContacts.length;
                  }}
                  onChange={toggleSelectAll}
                  className="h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {selectedIds.size > 0 ? `${selectedIds.size} selected` : "Select all"}
                </span>
              </label>

              {/* Select top N dropdown */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-gray-400 dark:text-gray-500">Select top</span>
                {[10, 20, 30, 50].map((n) => (
                  <button
                    key={n}
                    onClick={() => {
                      const ids = allSelectableContacts.slice(0, n).map((c) => c.id);
                      setSelectedIds(new Set(ids));
                    }}
                    className="rounded px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-blue-100 dark:hover:bg-blue-900 hover:text-blue-700 dark:hover:text-blue-300 transition-colors"
                  >
                    {n}
                  </button>
                ))}
              </div>

              {/* Quick action: open selected tabs inline (visible even before batch bar) */}
              {selectedIds.size > 0 && (
                <button
                  onClick={openSelectedTabs}
                  className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 transition-colors"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Open {selectedIds.size} profile{selectedIds.size !== 1 ? "s" : ""}
                </button>
              )}
            </div>
          )}

          {/* Row 2: Status filters */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">Status</span>
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

          {/* Row 3: Generation controls — only in Messages mode */}
          {viewMode === "messages" && <div className="flex flex-wrap items-center gap-3">
            {/* Vertical */}
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
                        ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                        : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Limit */}
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

            {/* Mode */}
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

            {/* Regenerate checkbox */}
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={genRegenerate}
                onChange={(e) => setGenRegenerate(e.target.checked)}
                className="rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500 h-3.5 w-3.5"
              />
              <span className="text-xs text-gray-500 dark:text-gray-400">Regenerate existing</span>
            </label>

            {/* Generate button */}
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-60 ml-auto"
            >
              {generating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Linkedin className="h-3.5 w-3.5" />
              )}
              {generating ? "Generating..." : "Generate Messages"}
            </button>
          </div>}
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

      {/* Batch action bar */}
      {selectedIds.size > 0 && (
        <div className="sticky top-0 z-10 border-b border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950 px-6 py-2.5">
          <div className="max-w-4xl mx-auto flex items-center gap-3 flex-wrap">
            <span className="text-xs font-medium text-blue-700 dark:text-blue-300">
              {selectedIds.size} contact{selectedIds.size !== 1 ? "s" : ""} selected
            </span>
            <button
              onClick={openSelectedTabs}
              className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition-colors"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open {selectedIds.size} profile{selectedIds.size !== 1 ? "s" : ""}
            </button>
            <button
              onClick={markSelectedConnectionSent}
              disabled={bulkUpdating}
              className="flex items-center gap-1.5 rounded-md bg-white dark:bg-gray-900 border border-blue-200 dark:border-blue-700 px-3 py-1.5 text-xs font-medium text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900 transition-colors disabled:opacity-50"
            >
              {bulkUpdating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              {bulkSuccess ? "Marked!" : "Mark Connection Sent"}
            </button>
            {bulkError && <span className="text-xs text-red-500">{bulkError}</span>}
            <button
              onClick={() => { setSelectedIds(new Set()); setShowLinksPanel(false); }}
              className="text-xs text-blue-500 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-200 ml-auto"
            >
              Clear selection
            </button>
          </div>
        </div>
      )}

      {/* Links panel — opens when "Open profiles" clicked */}
      {showLinksPanel && selectedContacts.length > 0 && (
        <div className="sticky top-0 z-20 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-6 py-3 shadow-md">
          <div className="max-w-4xl mx-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                Click each profile to open — use ⌘+click to open in background tab
              </span>
              <button onClick={() => setShowLinksPanel(false)} className="text-xs text-gray-400 hover:text-gray-700">Close</button>
            </div>
            <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
              {selectedContacts.filter((c) => isValidLinkedInUrl(c.linkedin_url!)).map((c) => {
                const contact = viewMode === "contacts"
                  ? filteredRawContacts.find((r) => r.contact.id === c.id)?.contact
                  : filteredItems.find((r) => r.contact.id === c.id)?.contact;
                const company = viewMode === "contacts"
                  ? filteredRawContacts.find((r) => r.contact.id === c.id)?.company
                  : filteredItems.find((r) => r.contact.id === c.id)?.company;
                const name = contact?.full_name || `${contact?.first_name ?? ""} ${contact?.last_name ?? ""}`.trim() || "Unknown";
                return (
                  <a
                    key={c.id}
                    href={c.linkedin_url!}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 rounded-md px-3 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-gray-800 group"
                  >
                    <Linkedin className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                    <span className="font-medium text-gray-900 dark:text-gray-100 w-36 truncate">{name}</span>
                    <span className="text-gray-400 truncate flex-1">{contact?.title}</span>
                    <span className="text-gray-500 truncate w-36">{company?.name}</span>
                    <ExternalLink className="h-3 w-3 text-gray-300 group-hover:text-blue-500 shrink-0" />
                  </a>
                );
              })}
            </div>
            <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
              <span className="text-[10px] text-gray-400">After sending connection requests, click below to update status</span>
              <button
                onClick={markSelectedConnectionSent}
                disabled={bulkUpdating}
                className="flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-gray-100 px-3 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-700 dark:hover:bg-gray-200 transition-colors disabled:opacity-50"
              >
                {bulkUpdating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                {bulkSuccess ? "Marked!" : `Mark ${selectedIds.size} as Connection Sent`}
              </button>
            </div>
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
          ) : viewMode === "contacts" ? (
            /* ── All Contacts table view ── */
            filteredRawContacts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <Linkedin className="mb-3 h-8 w-8 text-gray-300" />
                <p className="text-sm text-gray-500">No contacts with LinkedIn URLs found.</p>
                <p className="mt-1 text-xs text-gray-400">Run the Apollo discovery script to populate contacts.</p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                      <th className="w-8 px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selectedIds.size === filteredRawContacts.length && filteredRawContacts.length > 0}
                          onChange={toggleSelectAll}
                          className="h-3.5 w-3.5 rounded border-gray-300 dark:border-gray-600 text-blue-600"
                        />
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Name</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Title</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Company</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">PQS</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">LI</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {filteredRawContacts.map((item) => {
                      const c = item.contact;
                      const co = item.company;
                      const name = c.full_name || `${c.first_name ?? ""} ${c.last_name ?? ""}`.trim() || "—";
                      const liStatus = (c.linkedin_status || "not_sent") as LinkedInStatus;
                      return (
                        <tr
                          key={c.id}
                          className={`transition-colors ${selectedIds.has(c.id) ? "bg-blue-50 dark:bg-blue-950" : "hover:bg-gray-50 dark:hover:bg-gray-800"}`}
                        >
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              checked={selectedIds.has(c.id)}
                              onChange={() => toggleSelect(c.id)}
                              className="h-3.5 w-3.5 rounded border-gray-300 dark:border-gray-600 text-blue-600"
                            />
                          </td>
                          <td className="px-3 py-2 font-medium text-gray-900 dark:text-gray-100 whitespace-nowrap">{name}</td>
                          <td className="px-3 py-2 text-gray-500 dark:text-gray-400 max-w-[160px] truncate">{c.title || "—"}</td>
                          <td className="px-3 py-2 text-gray-700 dark:text-gray-300 whitespace-nowrap">{co.name || "—"}</td>
                          <td className="px-3 py-2 text-gray-500 dark:text-gray-400 tabular-nums">{co.pqs_total ?? "—"}</td>
                          <td className="px-3 py-2">
                            <select
                              value={liStatus}
                              onChange={async (e) => {
                                const newStatus = e.target.value as LinkedInStatus;
                                try {
                                  await updateLinkedInStatus(c.id, newStatus, c.linkedin_notes || "");
                                  setRawContacts((prev) =>
                                    prev.map((r) =>
                                      r.contact.id === c.id
                                        ? { ...r, contact: { ...r.contact, linkedin_status: newStatus } }
                                        : r
                                    )
                                  );
                                } catch (err) {
                                  console.error(err);
                                }
                              }}
                              className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-1.5 py-0.5 text-[11px] text-gray-600 dark:text-gray-300 focus:outline-none"
                            >
                              {(Object.keys(STATUS_LABELS) as LinkedInStatus[]).map((s) => (
                                <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            {c.linkedin_url ? (
                              <a
                                href={c.linkedin_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1 text-blue-500 hover:text-blue-700"
                              >
                                <Linkedin className="h-3.5 w-3.5" />
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            ) : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {/* Pagination */}
                {rawTotal > RAW_PAGE_SIZE && (
                  <div className="flex items-center justify-between border-t border-gray-100 dark:border-gray-800 px-4 py-2">
                    <span className="text-xs text-gray-400">
                      Showing {rawOffset + 1}–{Math.min(rawOffset + RAW_PAGE_SIZE, rawTotal)} of {rawTotal}
                    </span>
                    <div className="flex gap-2">
                      <button
                        disabled={rawOffset === 0}
                        onClick={() => fetchContacts(Math.max(0, rawOffset - RAW_PAGE_SIZE))}
                        className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 disabled:opacity-40"
                      >
                        Prev
                      </button>
                      <button
                        disabled={rawOffset + RAW_PAGE_SIZE >= rawTotal}
                        onClick={() => fetchContacts(rawOffset + RAW_PAGE_SIZE)}
                        className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 disabled:opacity-40"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          ) : (
            /* ── Messages card view ── */
            filteredItems.length === 0 ? (
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
                  <ContactCard
                    key={item.contact.id}
                    item={item}
                    selected={selectedIds.has(item.contact.id)}
                    onToggle={toggleSelect}
                  />
                ))}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}
