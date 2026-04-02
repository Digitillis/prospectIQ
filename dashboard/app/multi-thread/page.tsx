"use client";

// Copyright © 2026 ProspectIQ. All rights reserved.
// Authors: Avanish Mehrotra & ProspectIQ Technical Team
/**
 * Multi-Thread Orchestration — coordinate simultaneous outreach to multiple
 * contacts at the same target account with role-aware, complementary messaging.
 */

import { useEffect, useState, useCallback } from "react";
import {
  GitBranch,
  Plus,
  X,
  Loader2,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Building2,
  Users,
  CheckCircle2,
  PauseCircle,
  Zap,
  ArrowRight,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

const STRATEGY_OPTIONS = [
  {
    value: "parallel",
    label: "Parallel",
    description:
      "All contacts receive outreach simultaneously. Best for large buying committees.",
  },
  {
    value: "sequential",
    label: "Sequential",
    description:
      "Contacts are approached one by one in order. Best for sequential deal progression.",
  },
  {
    value: "waterfall",
    label: "Waterfall",
    description:
      "Start with champion, escalate to economic buyer after engagement. Best for enterprise deals.",
  },
];

const ROLE_COLORS: Record<string, string> = {
  economic_buyer:
    "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300 border border-purple-200 dark:border-purple-800",
  champion:
    "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-200 dark:border-blue-800",
  technical_evaluator:
    "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 border border-green-200 dark:border-green-800",
  influencer:
    "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 border border-gray-200 dark:border-gray-600",
};

const ROLE_LABELS: Record<string, string> = {
  economic_buyer: "Economic Buyer",
  champion: "Champion",
  technical_evaluator: "Technical Evaluator",
  influencer: "Influencer",
};

const STATUS_COLORS: Record<string, string> = {
  active:
    "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
  paused:
    "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  completed:
    "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Contact {
  id: string;
  full_name: string;
  title?: string;
  email?: string;
}

interface Company {
  id: string;
  name: string;
  domain?: string;
}

interface Thread {
  id: string;
  contact_id: string;
  role_label?: string;
  messaging_angle?: string;
  sequence_step: number;
  status: string;
  last_touch_at?: string;
  suppressed?: boolean;
  contacts?: Contact;
}

interface Campaign {
  id: string;
  campaign_name: string;
  strategy: string;
  status: string;
  created_at: string;
  updated_at: string;
  company_id: string;
  companies?: Company;
  account_campaign_threads?: Thread[];
  thread_count?: number;
  last_activity_at?: string;
}

interface CampaignDetail {
  campaign: Campaign;
  threads: Thread[];
  drafts_generated: number;
  suppressed_count: number;
  next_available_at?: string;
}

interface CoordinatedDraft {
  thread_id: string;
  contact_id: string;
  contact_name: string;
  contact_title: string;
  role_label: string;
  messaging_angle: string;
  subject: string;
  body: string;
  awareness_note?: string;
  suppressed: boolean;
  suppress_reason?: string;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function getAuthHeader(): Promise<string | null> {
  try {
    const { supabase } = await import("@/lib/supabase");
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ? `Bearer ${session.access_token}` : null;
  } catch {
    return null;
  }
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const auth = await getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (auth) headers["Authorization"] = auth;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function formatDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded bg-gray-100 dark:bg-gray-800",
        className
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function RoleBadge({ role }: { role?: string }) {
  const r = role || "influencer";
  return (
    <span
      className={cn(
        "inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        ROLE_COLORS[r] || ROLE_COLORS["influencer"]
      )}
    >
      {ROLE_LABELS[r] || r}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        STATUS_COLORS[status] || "bg-gray-100 text-gray-600"
      )}
    >
      {status}
    </span>
  );
}

function StrategyBadge({ strategy }: { strategy: string }) {
  const colors: Record<string, string> = {
    parallel:
      "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300",
    sequential:
      "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300",
    waterfall:
      "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300",
  };
  return (
    <span
      className={cn(
        "inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        colors[strategy] || "bg-gray-100 text-gray-600"
      )}
    >
      {strategy}
    </span>
  );
}

// ---------------------------------------------------------------------------
// DraftCard
// ---------------------------------------------------------------------------

function DraftCard({ draft }: { draft: CoordinatedDraft }) {
  const [expanded, setExpanded] = useState(false);
  const [approved, setApproved] = useState(false);
  const [rejected, setRejected] = useState(false);

  if (draft.suppressed) {
    return (
      <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/10 p-4">
        <div className="flex items-center gap-2 mb-1">
          <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
          <span className="text-sm font-medium text-amber-700 dark:text-amber-300">
            {draft.contact_name}
          </span>
          <RoleBadge role={draft.role_label} />
        </div>
        <p className="text-xs text-amber-600 dark:text-amber-400">
          {draft.suppress_reason || "Suppressed — too recent to send."}
        </p>
      </div>
    );
  }

  if (rejected) {
    return (
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 opacity-50">
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Draft rejected for {draft.contact_name}.
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        approved
          ? "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/10"
          : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
            {draft.contact_name}
          </span>
          {draft.contact_title && (
            <span className="text-xs text-gray-400 dark:text-gray-500 truncate hidden sm:inline">
              · {draft.contact_title}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <RoleBadge role={draft.role_label} />
          {approved && (
            <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
          )}
        </div>
      </div>

      {/* Messaging angle tag */}
      <p className="text-xs text-gray-500 dark:text-gray-400 italic mb-3">
        Angle: {draft.messaging_angle}
      </p>

      {/* Subject */}
      <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
        Subject: {draft.subject}
      </p>

      {/* Body (expandable) */}
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-400 mb-2"
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          {expanded ? "Collapse" : "View draft"}
        </button>
        {expanded && (
          <pre className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-sans bg-gray-50 dark:bg-gray-800 rounded-md p-3 mb-3 leading-relaxed">
            {draft.body}
          </pre>
        )}
      </div>

      {/* Awareness note */}
      {draft.awareness_note && (
        <div className="rounded-md bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 px-3 py-2 mb-3">
          <p className="text-xs text-blue-700 dark:text-blue-300">
            <span className="font-medium">Coordination note: </span>
            {draft.awareness_note}
          </p>
        </div>
      )}

      {/* Actions */}
      {!approved && (
        <div className="flex gap-2">
          <button
            onClick={() => setApproved(true)}
            className="flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white transition-colors"
          >
            <CheckCircle2 className="h-3 w-3" />
            Approve
          </button>
          <button
            onClick={() => setRejected(true)}
            className="flex items-center gap-1.5 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 transition-colors"
          >
            <X className="h-3 w-3" />
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ThreadCard (in campaign detail)
// ---------------------------------------------------------------------------

function ThreadCard({ thread }: { thread: Thread }) {
  const contact = thread.contacts;
  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        thread.suppressed
          ? "border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10"
          : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
            {contact?.full_name || "Unknown"}
          </p>
          {contact?.title && (
            <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
              {contact.title}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <RoleBadge role={thread.role_label} />
          <StatusBadge status={thread.status} />
        </div>
      </div>

      {thread.messaging_angle && (
        <p className="text-xs text-gray-500 dark:text-gray-400 italic mb-2">
          {thread.messaging_angle}
        </p>
      )}

      <div className="flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
        <span>Step {thread.sequence_step}</span>
        {thread.last_touch_at && (
          <span>Last touch {formatDate(thread.last_touch_at)}</span>
        )}
        {thread.suppressed && (
          <span className="flex items-center gap-1 text-amber-500">
            <AlertTriangle className="h-3 w-3" />
            Suppressed
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CampaignListItem
// ---------------------------------------------------------------------------

function CampaignListItem({
  campaign,
  selected,
  onClick,
}: {
  campaign: Campaign;
  selected: boolean;
  onClick: () => void;
}) {
  const company = campaign.companies;
  const threadCount = campaign.thread_count ?? (campaign.account_campaign_threads?.length ?? 0);

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-lg border px-4 py-3 transition-colors",
        selected
          ? "border-blue-500 bg-blue-50 dark:bg-blue-950/30"
          : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800"
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate leading-tight">
          {company?.name || campaign.campaign_name}
        </p>
        <StatusBadge status={campaign.status} />
      </div>
      <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
        <span className="flex items-center gap-1">
          <Users className="h-3 w-3" />
          {threadCount} thread{threadCount !== 1 ? "s" : ""}
        </span>
        <StrategyBadge strategy={campaign.strategy} />
        <span>{formatDate(campaign.last_activity_at || campaign.updated_at)}</span>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// CreateCampaignForm (inline form)
// ---------------------------------------------------------------------------

function CreateCampaignForm({
  onCreated,
  onCancel,
}: {
  onCreated: (c: Campaign) => void;
  onCancel: () => void;
}) {
  const [companySearch, setCompanySearch] = useState("");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedContacts, setSelectedContacts] = useState<Set<string>>(new Set());
  const [strategy, setStrategy] = useState("parallel");
  const [campaignName, setCampaignName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingContacts, setLoadingContacts] = useState(false);

  // Company typeahead
  useEffect(() => {
    if (companySearch.length < 2) {
      setCompanies([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await apiFetch<{ data: Company[] }>(
          `/api/companies?search=${encodeURIComponent(companySearch)}&limit=10`
        );
        setCompanies(res.data || []);
      } catch {
        setCompanies([]);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [companySearch]);

  // Load contacts when company selected
  const selectCompany = async (c: Company) => {
    setSelectedCompany(c);
    setCompanySearch(c.name);
    setCompanies([]);
    setSelectedContacts(new Set());
    setLoadingContacts(true);
    try {
      const res = await apiFetch<{ data: Contact[] }>(
        `/api/contacts?company_id=${c.id}&limit=50`
      );
      setContacts(res.data || []);
    } catch {
      setContacts([]);
    } finally {
      setLoadingContacts(false);
    }
  };

  const toggleContact = (id: string) => {
    setSelectedContacts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCompany) return setError("Select a company first.");
    if (selectedContacts.size === 0) return setError("Select at least one contact.");
    setError(null);
    setLoading(true);
    try {
      const res = await apiFetch<{ data: Campaign }>("/api/multi-thread/campaigns", {
        method: "POST",
        body: JSON.stringify({
          company_id: selectedCompany.id,
          contact_ids: Array.from(selectedContacts),
          strategy,
          campaign_name: campaignName || undefined,
        }),
      });
      onCreated(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create campaign.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20 p-4 space-y-4"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          New Account Campaign
        </h3>
        <button type="button" onClick={onCancel} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Campaign name */}
      <div>
        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
          Campaign Name (optional)
        </label>
        <input
          type="text"
          placeholder="e.g. Acme Corp — Enterprise Q2"
          value={campaignName}
          onChange={(e) => setCampaignName(e.target.value)}
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      {/* Company search */}
      <div className="relative">
        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
          Target Company <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          placeholder="Search companies…"
          value={companySearch}
          onChange={(e) => {
            setCompanySearch(e.target.value);
            if (e.target.value !== selectedCompany?.name) setSelectedCompany(null);
          }}
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {companies.length > 0 && (
          <ul className="absolute z-20 mt-1 w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg overflow-hidden">
            {companies.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => selectCompany(c)}
                  className="w-full text-left px-3 py-2 text-sm text-gray-900 dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  {c.name}
                  {c.domain && (
                    <span className="ml-2 text-xs text-gray-400">{c.domain}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Contact multi-select */}
      {selectedCompany && (
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Contacts at {selectedCompany.name} <span className="text-red-500">*</span>
          </label>
          {loadingContacts ? (
            <div className="flex items-center gap-2 text-xs text-gray-400 py-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading contacts…
            </div>
          ) : contacts.length === 0 ? (
            <p className="text-xs text-gray-400 dark:text-gray-500 py-1">
              No contacts found for this company.
            </p>
          ) : (
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {contacts.map((c) => (
                <label
                  key={c.id}
                  className={cn(
                    "flex items-center gap-3 rounded-md border px-3 py-2 cursor-pointer transition-colors",
                    selectedContacts.has(c.id)
                      ? "border-blue-400 dark:border-blue-600 bg-blue-50 dark:bg-blue-950/30"
                      : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700"
                  )}
                >
                  <input
                    type="checkbox"
                    checked={selectedContacts.has(c.id)}
                    onChange={() => toggleContact(c.id)}
                    className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-900 dark:text-gray-100 truncate">
                      {c.full_name}
                    </p>
                    {c.title && (
                      <p className="text-[10px] text-gray-400 dark:text-gray-500 truncate">
                        {c.title}
                      </p>
                    )}
                  </div>
                </label>
              ))}
            </div>
          )}
          {selectedContacts.size > 0 && (
            <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
              {selectedContacts.size} contact{selectedContacts.size !== 1 ? "s" : ""} selected
            </p>
          )}
        </div>
      )}

      {/* Strategy radio */}
      <div>
        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
          Strategy <span className="text-red-500">*</span>
        </label>
        <div className="space-y-2">
          {STRATEGY_OPTIONS.map((s) => (
            <label
              key={s.value}
              className={cn(
                "flex items-start gap-3 rounded-md border px-3 py-2.5 cursor-pointer transition-colors",
                strategy === s.value
                  ? "border-blue-400 dark:border-blue-600 bg-blue-50 dark:bg-blue-950/30"
                  : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700"
              )}
            >
              <input
                type="radio"
                name="strategy"
                value={s.value}
                checked={strategy === s.value}
                onChange={() => setStrategy(s.value)}
                className="mt-0.5 h-3.5 w-3.5 text-blue-600 focus:ring-blue-500"
              />
              <div>
                <p className="text-xs font-semibold text-gray-900 dark:text-gray-100">
                  {s.label}
                </p>
                <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-tight mt-0.5">
                  {s.description}
                </p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {error && (
        <p className="rounded-md bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={loading || !selectedCompany || selectedContacts.size === 0}
          className="flex items-center gap-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white transition-colors"
        >
          {loading && <Loader2 className="h-3 w-3 animate-spin" />}
          Create Campaign
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-gray-300 dark:border-gray-600 px-4 py-2 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// CampaignDetail (right panel)
// ---------------------------------------------------------------------------

function CampaignDetail({ campaignId }: { campaignId: string }) {
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<CoordinatedDraft[]>([]);
  const [generatingDrafts, setGeneratingDrafts] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [pausing, setPausing] = useState(false);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<{ data: CampaignDetail }>(
        `/api/multi-thread/campaigns/${campaignId}`
      );
      setDetail(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load campaign.");
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  const generateDrafts = async () => {
    setGeneratingDrafts(true);
    setDraftError(null);
    setDrafts([]);
    try {
      const res = await apiFetch<{ data: CoordinatedDraft[] }>(
        `/api/multi-thread/campaigns/${campaignId}/drafts`,
        { method: "POST" }
      );
      setDrafts(res.data || []);
    } catch (err: unknown) {
      setDraftError(err instanceof Error ? err.message : "Draft generation failed.");
    } finally {
      setGeneratingDrafts(false);
    }
  };

  const pauseCampaign = async () => {
    setPausing(true);
    try {
      await apiFetch(`/api/multi-thread/campaigns/${campaignId}/pause`, {
        method: "PUT",
      });
      await fetchDetail();
    } catch {
      // silent
    } finally {
      setPausing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-40" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-6">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <AlertTriangle className="h-8 w-8 text-amber-400 mx-auto mb-2" />
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {error || "Campaign not found."}
          </p>
          <button
            onClick={fetchDetail}
            className="mt-3 flex items-center gap-1 text-xs text-blue-500 hover:text-blue-400 mx-auto"
          >
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  const { campaign, threads, suppressed_count, next_available_at } = detail;
  const company = campaign.companies;

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Campaign header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
              {company?.name || campaign.campaign_name}
            </h2>
            <StrategyBadge strategy={campaign.strategy} />
            <StatusBadge status={campaign.status} />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Created {formatDate(campaign.created_at)} · {threads.length} thread
            {threads.length !== 1 ? "s" : ""}
          </p>
        </div>
        {campaign.status === "active" && (
          <button
            onClick={pauseCampaign}
            disabled={pausing}
            className="flex items-center gap-1.5 rounded-md border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100 dark:hover:bg-amber-900/40 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-300 transition-colors disabled:opacity-50"
          >
            {pausing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <PauseCircle className="h-3.5 w-3.5" />
            )}
            Pause All
          </button>
        )}
      </div>

      {/* Suppression warning */}
      {suppressed_count > 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/10 px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
              {suppressed_count} thread{suppressed_count !== 1 ? "s" : ""} suppressed —
              too recent to send.
            </p>
            {next_available_at && (
              <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                Next available:{" "}
                {new Date(next_available_at).toLocaleString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Thread grid */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 mb-3">
          Contact Threads
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {threads.map((t) => (
            <ThreadCard key={t.id} thread={t} />
          ))}
        </div>
      </div>

      {/* Generate drafts section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
            Coordinated Drafts
          </h3>
          <button
            onClick={generateDrafts}
            disabled={generatingDrafts || campaign.status === "paused"}
            className="flex items-center gap-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white transition-colors"
          >
            {generatingDrafts ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <Zap className="h-3 w-3" />
                Generate Coordinated Drafts
              </>
            )}
          </button>
        </div>

        {draftError && (
          <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/10 px-4 py-3 mb-3">
            <p className="text-xs text-red-600 dark:text-red-400">{draftError}</p>
          </div>
        )}

        {drafts.length > 0 ? (
          <div className="space-y-3">
            {drafts.map((d) => (
              <DraftCard key={d.thread_id} draft={d} />
            ))}
          </div>
        ) : (
          !generatingDrafts && (
            <div className="rounded-lg border border-dashed border-gray-200 dark:border-gray-700 px-6 py-8 text-center">
              <GitBranch className="h-8 w-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
              <p className="text-sm text-gray-400 dark:text-gray-500">
                Click "Generate Coordinated Drafts" to create role-aware outreach
                for all threads.
              </p>
            </div>
          )
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MultiThreadPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const fetchCampaigns = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch<{ data: Campaign[] }>(
        "/api/multi-thread/campaigns?limit=100"
      );
      setCampaigns(res.data || []);
    } catch {
      setCampaigns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCampaigns();
  }, [fetchCampaigns]);

  const handleCreated = (c: Campaign) => {
    setShowForm(false);
    setCampaigns((prev) => [c, ...prev]);
    setSelectedId(c.id);
  };

  return (
    <div className="flex h-full bg-gray-50 dark:bg-gray-950">
      {/* ------------------------------------------------------------------ */}
      {/* Left Panel — Campaign Builder (360px) */}
      {/* ------------------------------------------------------------------ */}
      <div className="w-[360px] shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-4 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-blue-500" />
            <h1 className="text-sm font-bold text-gray-900 dark:text-gray-100">
              Multi-Thread
            </h1>
          </div>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            New Campaign
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
          {/* Inline create form */}
          {showForm && (
            <CreateCampaignForm
              onCreated={handleCreated}
              onCancel={() => setShowForm(false)}
            />
          )}

          {/* Campaign list */}
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : campaigns.length === 0 ? (
            <div className="py-12 text-center">
              <Building2 className="h-8 w-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
              <p className="text-xs text-gray-400 dark:text-gray-500">
                No campaigns yet. Create one above to get started.
              </p>
            </div>
          ) : (
            campaigns.map((c) => (
              <CampaignListItem
                key={c.id}
                campaign={c}
                selected={selectedId === c.id}
                onClick={() => setSelectedId(c.id)}
              />
            ))
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Right Panel — Campaign Detail */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {selectedId ? (
          <CampaignDetail key={selectedId} campaignId={selectedId} />
        ) : (
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="text-center max-w-xs">
              <div className="flex items-center justify-center gap-2 mb-4">
                <GitBranch className="h-10 w-10 text-gray-300 dark:text-gray-700" />
              </div>
              <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-2">
                Multi-Thread Orchestration
              </h2>
              <p className="text-sm text-gray-400 dark:text-gray-500 leading-relaxed mb-6">
                Reach multiple contacts at the same account simultaneously with
                coordinated, role-aware messaging. No more conflicting outreach.
              </p>
              <div className="flex items-center justify-center gap-3 text-xs text-gray-400 dark:text-gray-500">
                <div className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-purple-400 inline-block" />
                  Economic Buyer
                </div>
                <ArrowRight className="h-3 w-3" />
                <div className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-blue-400 inline-block" />
                  Champion
                </div>
                <ArrowRight className="h-3 w-3" />
                <div className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-green-400 inline-block" />
                  Tech Eval
                </div>
              </div>
              <button
                onClick={() => setShowForm(true)}
                className="mt-6 flex items-center gap-2 rounded-md bg-blue-600 hover:bg-blue-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors mx-auto"
              >
                <Plus className="h-4 w-4" />
                Create first campaign
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
