"use client";

/**
 * Prospect List — All companies in the pipeline with filtering and sorting
 *
 * Expected actions:
 * Filter by status/tier/PQS, click a prospect to see full profile, bulk select for batch operations
 */


import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertCircle,
  Flag,
  MoreHorizontal,
  Ban,
  Download,
  Plus,
  X,
  Bookmark,
  MessageSquare,
} from "lucide-react";

import { getCompanies, updateCompany, createCompany, runAgent, addNote, type Company } from "@/lib/api";
import {
  cn,
  formatTimeAgo,
  STATUS_COLORS,
  TIER_LABELS,
  getPQSColor,
} from "@/lib/utils";

// ---------------------------------------------------------------------------
// Saved views
// ---------------------------------------------------------------------------

interface SavedView {
  id: string;
  name: string;
  filters: {
    status: string;
    tier: string;
    minPqs: string;
    search: string;
  };
}

const DEFAULT_VIEWS: SavedView[] = [
  { id: "preset-1", name: "Hot Prospects", filters: { status: "", tier: "", minPqs: "60", search: "" } },
  { id: "preset-2", name: "F&B Ready", filters: { status: "discovered", tier: "fb1", minPqs: "", search: "" } },
  { id: "preset-3", name: "Needs Research", filters: { status: "discovered", tier: "", minPqs: "", search: "" } },
];

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

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
] as const;

const TIER_OPTIONS = Object.keys(TIER_LABELS);

const US_STATES = [
  "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL",
  "GA", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA",
  "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE",
  "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI",
  "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
];

type SortKey =
  | "name"
  | "tier"
  | "pqs_total"
  | "status"
  | "sub_sector"
  | "state"
  | "updated_at";
type SortDir = "asc" | "desc";

// ---------------------------------------------------------------------------
// CSV export helper
// ---------------------------------------------------------------------------

function exportToCSV(companies: Company[], filename = "prospects.csv") {
  const headers = [
    "Name",
    "Domain",
    "Tier",
    "PQS Score",
    "Status",
    "Sub-Sector",
    "State",
    "Employee Count",
    "Industry",
    "Priority Flag",
    "Last Activity",
  ];

  const rows = companies.map((c) => [
    c.name,
    c.domain ?? "",
    c.tier ?? "",
    String(c.pqs_total),
    c.status,
    c.sub_sector ?? "",
    c.state ?? "",
    c.employee_count != null ? String(c.employee_count) : "",
    c.industry ?? "",
    c.priority_flag ? "Yes" : "No",
    c.updated_at ? new Date(c.updated_at).toLocaleDateString() : "",
  ]);

  const csvContent = [headers, ...rows]
    .map((row) =>
      row
        .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
        .join(",")
    )
    .join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Add Company Modal
// ---------------------------------------------------------------------------

interface AddCompanyForm {
  name: string;
  domain: string;
  industry: string;
  sub_sector: string;
  tier: string;
  state: string;
  employee_count: string;
  revenue_range: string;
  contact_name: string;
  contact_email: string;
  contact_title: string;
  contact_is_dm: boolean;
}

const EMPTY_FORM: AddCompanyForm = {
  name: "",
  domain: "",
  industry: "",
  sub_sector: "",
  tier: "",
  state: "",
  employee_count: "",
  revenue_range: "",
  contact_name: "",
  contact_email: "",
  contact_title: "",
  contact_is_dm: false,
};

const inputCls =
  "w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600 dark:text-gray-500">{label}</label>
      {children}
    </div>
  );
}

function AddCompanyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<AddCompanyForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (field: keyof AddCompanyForm, value: string | boolean) =>
    setForm((f) => ({ ...f, [field]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createCompany({
        name: form.name.trim(),
        domain: form.domain.trim() || undefined,
        industry: form.industry || undefined,
        sub_sector: form.sub_sector.trim() || undefined,
        tier: form.tier || undefined,
        state: form.state || undefined,
        employee_count: form.employee_count
          ? parseInt(form.employee_count, 10)
          : undefined,
        revenue_range: form.revenue_range.trim() || undefined,
        contact:
          form.contact_name.trim() || form.contact_email.trim()
            ? {
                full_name: form.contact_name.trim() || undefined,
                email: form.contact_email.trim() || undefined,
                title: form.contact_title.trim() || undefined,
                is_decision_maker: form.contact_is_dm,
              }
            : undefined,
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create company");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-black/30 sm:items-center sm:justify-center">
      <div className="w-full max-w-lg rounded-t-2xl bg-white dark:bg-gray-900 shadow-2xl sm:rounded-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-6 py-4">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Add Company Manually</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:text-gray-500"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="max-h-[80vh] overflow-y-auto">
          <div className="space-y-4 px-6 py-5">
            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 text-sm text-gray-700 dark:text-gray-300">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
              Company Details
            </p>

            <Field label="Company Name *">
              <input
                required
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="Acme Manufacturing Co."
                className={inputCls}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Domain">
                <input
                  value={form.domain}
                  onChange={(e) => set("domain", e.target.value)}
                  placeholder="acme.com"
                  className={inputCls}
                />
              </Field>
              <Field label="State">
                <select
                  value={form.state}
                  onChange={(e) => set("state", e.target.value)}
                  className={inputCls}
                >
                  <option value="">Select state…</option>
                  {US_STATES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Industry">
                <input
                  value={form.industry}
                  onChange={(e) => set("industry", e.target.value)}
                  placeholder="Industrial Machinery"
                  className={inputCls}
                />
              </Field>
              <Field label="Tier">
                <select
                  value={form.tier}
                  onChange={(e) => set("tier", e.target.value)}
                  className={inputCls}
                >
                  <option value="">Select tier…</option>
                  {TIER_OPTIONS.map((t) => (
                    <option key={t} value={t}>
                      {t} — {TIER_LABELS[t]}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Employee Count">
                <input
                  type="number"
                  min={1}
                  value={form.employee_count}
                  onChange={(e) => set("employee_count", e.target.value)}
                  placeholder="5000"
                  className={inputCls}
                />
              </Field>
              <Field label="Revenue Range">
                <input
                  value={form.revenue_range}
                  onChange={(e) => set("revenue_range", e.target.value)}
                  placeholder="$500M–$1B"
                  className={inputCls}
                />
              </Field>
            </div>

            <div className="border-t border-gray-100 dark:border-gray-800 pt-2">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                Primary Contact (optional)
              </p>
              <div className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Full Name">
                    <input
                      value={form.contact_name}
                      onChange={(e) => set("contact_name", e.target.value)}
                      placeholder="Jane Smith"
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Email">
                    <input
                      type="email"
                      value={form.contact_email}
                      onChange={(e) => set("contact_email", e.target.value)}
                      placeholder="jane@acme.com"
                      className={inputCls}
                    />
                  </Field>
                </div>
                <Field label="Title">
                  <input
                    value={form.contact_title}
                    onChange={(e) => set("contact_title", e.target.value)}
                    placeholder="VP Operations"
                    className={inputCls}
                  />
                </Field>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                  <input
                    type="checkbox"
                    checked={form.contact_is_dm}
                    onChange={(e) => set("contact_is_dm", e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-gray-900 dark:text-gray-100"
                  />
                  Mark as decision maker
                </label>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 border-t border-gray-200 dark:border-gray-700 px-6 py-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-300 bg-white dark:bg-gray-900 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !form.name.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-gray-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              Add Company
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row action menu
// ---------------------------------------------------------------------------

function RowActions({
  company,
  onFlagToggle,
  onDisqualify,
  onQuickNote,
  loading,
}: {
  company: Company;
  onFlagToggle: (c: Company) => void;
  onDisqualify: (c: Company) => void;
  onQuickNote: (c: Company) => void;
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirmDisqualify, setConfirmDisqualify] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirmDisqualify(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div
      ref={ref}
      className="relative"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        onClick={() => { setOpen((o) => !o); setConfirmDisqualify(false); }}
        disabled={loading}
        className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 dark:text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-700 dark:text-gray-300 disabled:opacity-40"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <MoreHorizontal className="h-4 w-4" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-8 z-20 w-44 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 py-1 shadow-lg">
          {/* Flag priority */}
          <button
            onClick={() => { onFlagToggle(company); setOpen(false); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <Flag
              className={cn(
                "h-4 w-4",
                company.priority_flag
                  ? "fill-gray-600 text-gray-600 dark:text-gray-500"
                  : "text-gray-400 dark:text-gray-500"
              )}
            />
            {company.priority_flag ? "Remove flag" : "Flag priority"}
          </button>

          {/* Quick Note */}
          <button
            onClick={() => { onQuickNote(company); setOpen(false); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <MessageSquare className="h-4 w-4 text-gray-400 dark:text-gray-500" />
            Quick Note
          </button>

          <div className="my-1 border-t border-gray-100 dark:border-gray-800" />

          {/* Disqualify */}
          {company.status !== "disqualified" && (
            confirmDisqualify ? (
              <div className="px-3 py-2">
                <p className="mb-2 text-xs text-gray-500 dark:text-gray-500">Disqualify this company?</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => { onDisqualify(company); setOpen(false); setConfirmDisqualify(false); }}
                    className="flex-1 rounded-md bg-gray-900 px-2 py-1 text-xs font-medium text-white hover:bg-gray-800"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => setConfirmDisqualify(false)}
                    className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDisqualify(true)}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                <Ban className="h-4 w-4" />
                Disqualify
              </button>
            )
          )}

          {/* Re-enable if already disqualified */}
          {company.status === "disqualified" && (
            <button
              onClick={() => { onFlagToggle(company); setOpen(false); }}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Restore to discovered
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ProspectsPage() {
  const router = useRouter();

  // --- Data state ---
  const [companies, setCompanies] = useState<Company[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // --- Filter state ---
  const [statusFilter, setStatusFilter] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [minPqs, setMinPqs] = useState("");
  const [search, setSearch] = useState("");

  // --- Pagination & sort ---
  const [offset, setOffset] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("pqs_total");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // --- Selection & bulk action state ---
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  // --- UI state ---
  const [showAddModal, setShowAddModal] = useState(false);
  const [exporting, setExporting] = useState(false);

  // --- Quick note state ---
  const [quickNoteCompany, setQuickNoteCompany] = useState<Company | null>(null);
  const [quickNoteText, setQuickNoteText] = useState("");
  const [quickNoteSaving, setQuickNoteSaving] = useState(false);

  // --- Saved views ---
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => {
    if (typeof window === "undefined") return DEFAULT_VIEWS;
    const stored = localStorage.getItem("prospectiq-saved-views");
    return stored ? JSON.parse(stored) : DEFAULT_VIEWS;
  });
  const [showSaveView, setShowSaveView] = useState(false);
  const [viewName, setViewName] = useState("");

  useEffect(() => {
    localStorage.setItem("prospectiq-saved-views", JSON.stringify(savedViews));
  }, [savedViews]);

  const saveCurrentView = () => {
    if (!viewName.trim()) return;
    const view: SavedView = {
      id: Date.now().toString(),
      name: viewName.trim(),
      filters: { status: statusFilter, tier: tierFilter, minPqs, search },
    };
    setSavedViews((prev) => [...prev, view]);
    setViewName("");
    setShowSaveView(false);
  };

  const applyView = (view: SavedView) => {
    setStatusFilter(view.filters.status);
    setTierFilter(view.filters.tier);
    setMinPqs(view.filters.minPqs);
    setSearch(view.filters.search);
  };

  const deleteView = (id: string) => {
    setSavedViews((prev) => prev.filter((v) => v.id !== id));
  };

  const isViewActive = (view: SavedView) =>
    view.filters.status === statusFilter &&
    view.filters.tier === tierFilter &&
    view.filters.minPqs === minPqs &&
    view.filters.search === search;

  // --- Fetch ---
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params: Record<string, string> = {
        limit: String(PAGE_SIZE),
        offset: String(offset),
      };
      if (statusFilter) params.status = statusFilter;
      if (tierFilter) params.tier = tierFilter;
      if (minPqs) params.min_pqs = minPqs;
      if (search.trim()) params.search = search.trim();

      const res = await getCompanies(params);
      let data = res.data ?? [];

      // Client-side sort
      data.sort((a, b) => {
        let aVal: string | number = "";
        let bVal: string | number = "";

        switch (sortKey) {
          case "name":
            aVal = (a.name ?? "").toLowerCase();
            bVal = (b.name ?? "").toLowerCase();
            break;
          case "tier":
            aVal = a.tier ?? "";
            bVal = b.tier ?? "";
            break;
          case "pqs_total":
            aVal = a.pqs_total ?? 0;
            bVal = b.pqs_total ?? 0;
            break;
          case "status":
            aVal = a.status ?? "";
            bVal = b.status ?? "";
            break;
          case "sub_sector":
            aVal = (a.sub_sector ?? "").toLowerCase();
            bVal = (b.sub_sector ?? "").toLowerCase();
            break;
          case "state":
            aVal = (a.state ?? "").toLowerCase();
            bVal = (b.state ?? "").toLowerCase();
            break;
          case "updated_at":
            aVal = a.updated_at ?? "";
            bVal = b.updated_at ?? "";
            break;
        }

        if (aVal < bVal) return sortDir === "asc" ? -1 : 1;
        if (aVal > bVal) return sortDir === "asc" ? 1 : -1;
        return 0;
      });

      setCompanies(data);
      setTotalCount(res.count ?? data.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load companies");
    } finally {
      setLoading(false);
    }
  }, [offset, statusFilter, tierFilter, minPqs, search, sortKey, sortDir]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Reset offset when filters change
  useEffect(() => {
    setOffset(0);
  }, [statusFilter, tierFilter, minPqs, search]);

  // --- Sort handler ---
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) {
      return <ChevronsUpDown className="ml-1 inline h-3.5 w-3.5 text-gray-400 dark:text-gray-500" />;
    }
    return sortDir === "asc" ? (
      <ChevronUp className="ml-1 inline h-3.5 w-3.5 text-gray-700 dark:text-gray-300" />
    ) : (
      <ChevronDown className="ml-1 inline h-3.5 w-3.5 text-gray-700 dark:text-gray-300" />
    );
  };

  // --- Export ---
  const handleExport = async () => {
    setExporting(true);
    try {
      const params: Record<string, string> = { limit: "500", offset: "0" };
      if (statusFilter) params.status = statusFilter;
      if (tierFilter) params.tier = tierFilter;
      if (minPqs) params.min_pqs = minPqs;
      if (search.trim()) params.search = search.trim();
      const res = await getCompanies(params);
      const data = res.data ?? [];
      const date = new Date().toISOString().slice(0, 10);
      exportToCSV(data, `prospects-${date}.csv`);
    } finally {
      setExporting(false);
    }
  };

  // --- Row actions ---
  const handleFlagToggle = async (company: Company) => {
    setActionLoading(company.id);
    const newFlag = !company.priority_flag;
    setCompanies((prev) =>
      prev.map((c) => (c.id === company.id ? { ...c, priority_flag: newFlag } : c))
    );
    try {
      await updateCompany(company.id, { priority_flag: newFlag });
    } catch {
      setCompanies((prev) =>
        prev.map((c) => (c.id === company.id ? { ...c, priority_flag: !newFlag } : c))
      );
    } finally {
      setActionLoading(null);
    }
  };

  const handleDisqualify = async (company: Company) => {
    setActionLoading(company.id);
    setCompanies((prev) =>
      prev.map((c) => (c.id === company.id ? { ...c, status: "disqualified" } : c))
    );
    try {
      await updateCompany(company.id, { status: "disqualified" });
    } catch {
      setCompanies((prev) =>
        prev.map((c) => (c.id === company.id ? { ...c, status: company.status } : c))
      );
    } finally {
      setActionLoading(null);
    }
  };

  // --- Quick note handlers ---
  const handleQuickNote = (company: Company) => {
    setQuickNoteCompany(company);
    setQuickNoteText("");
  };

  const handleSaveNote = async () => {
    if (!quickNoteCompany || !quickNoteText.trim()) return;
    setQuickNoteSaving(true);
    try {
      await addNote(quickNoteCompany.id, quickNoteText.trim());
      setQuickNoteCompany(null);
      setQuickNoteText("");
    } catch {
      // silent
    } finally {
      setQuickNoteSaving(false);
    }
  };

  // --- Selection helpers ---
  const allVisibleSelected =
    companies.length > 0 && companies.every((c) => selectedIds.has(c.id));

  const toggleSelectAll = () => {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(companies.map((c) => c.id)));
    }
  };

  const toggleSelectOne = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  // --- Bulk action handlers ---
  const handleBulkResearch = async () => {
    setBulkLoading(true);
    try {
      await runAgent("research", { company_ids: Array.from(selectedIds) });
      clearSelection();
      await fetchData();
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkQualify = async () => {
    setBulkLoading(true);
    try {
      await runAgent("qualification", { company_ids: Array.from(selectedIds) });
      clearSelection();
      await fetchData();
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkDisqualify = async () => {
    setBulkLoading(true);
    try {
      await Promise.all(
        Array.from(selectedIds).map((id) =>
          updateCompany(id, { status: "disqualified" })
        )
      );
      clearSelection();
      await fetchData();
    } finally {
      setBulkLoading(false);
    }
  };

  // --- Pagination ---
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < totalCount;

  // --- Render ---
  return (
    <div className="space-y-4">
      {/* Page heading */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Prospects</h2>
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-sm text-gray-500 dark:text-gray-500">
            {totalCount} {totalCount === 1 ? "company" : "companies"}
          </span>
          <button
            onClick={handleExport}
            disabled={exporting || loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Export CSV
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
          >
            <Plus className="h-4 w-4" />
            Add Company
          </button>
        </div>
      </div>

      {/* ---- Saved Views ---- */}
      <div className="flex items-center gap-2 flex-wrap">
        {savedViews.map((view) => (
          <button
            key={view.id}
            onClick={() => applyView(view)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              isViewActive(view)
                ? "border-gray-900 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
            )}
          >
            <Bookmark className="h-3 w-3" />
            {view.name}
            <span
              role="button"
              onClick={(e) => { e.stopPropagation(); deleteView(view.id); }}
              className="ml-1 hover:text-gray-900 dark:text-gray-100 cursor-pointer"
            >
              <X className="h-3 w-3" />
            </span>
          </button>
        ))}

        {showSaveView ? (
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="View name..."
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") saveCurrentView();
                if (e.key === "Escape") setShowSaveView(false);
              }}
            />
            <button
              onClick={saveCurrentView}
              className="rounded-md bg-gray-900 px-2 py-1 text-xs text-white hover:bg-gray-800"
            >
              Save
            </button>
            <button
              onClick={() => { setShowSaveView(false); setViewName(""); }}
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:text-gray-500"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowSaveView(true)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-gray-300 px-3 py-1 text-xs text-gray-500 dark:text-gray-500 hover:border-gray-400 hover:text-gray-700 dark:text-gray-300"
          >
            <Plus className="h-3 w-3" />
            Save view
          </button>
        )}
      </div>

      {/* ---- Bulk action bar ---- */}
      {selectedIds.size > 0 && (
        <div className="sticky top-0 z-10 flex items-center gap-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkResearch}
            disabled={bulkLoading}
            className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {bulkLoading && <Loader2 className="h-3 w-3 animate-spin" />}
            Research Selected
          </button>
          <button
            onClick={handleBulkQualify}
            disabled={bulkLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {bulkLoading && <Loader2 className="h-3 w-3 animate-spin" />}
            Qualify Selected
          </button>
          <button
            onClick={handleBulkDisqualify}
            disabled={bulkLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {bulkLoading && <Loader2 className="h-3 w-3 animate-spin" />}
            Disqualify Selected
          </button>
          <button
            onClick={clearSelection}
            disabled={bulkLoading}
            className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:text-gray-300 disabled:opacity-50"
          >
            <X className="h-3.5 w-3.5" />
            Clear
          </button>
        </div>
      )}

      {/* ---- Filter bar ---- */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3">
        {/* Search */}
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 dark:text-gray-500" />
          <input
            type="text"
            placeholder="Search by company name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-md border border-gray-300 py-1.5 pl-8 pr-3 text-sm focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
          />
        </div>

        {/* Status */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
        >
          <option value="">All Statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
            </option>
          ))}
        </select>

        {/* Tier */}
        <select
          value={tierFilter}
          onChange={(e) => setTierFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
        >
          <option value="">All Tiers</option>
          {TIER_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {t} &mdash; {TIER_LABELS[t]}
            </option>
          ))}
        </select>

        {/* PQS min */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="pqs-min" className="text-xs font-medium text-gray-600 dark:text-gray-500">
            Min PQS
          </label>
          <input
            id="pqs-min"
            type="number"
            min={0}
            max={100}
            value={minPqs}
            onChange={(e) => setMinPqs(e.target.value)}
            placeholder="0"
            className="w-16 rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
          />
        </div>
      </div>

      {/* ---- Table ---- */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
            <span className="ml-2 text-sm text-gray-500 dark:text-gray-500">Loading prospects...</span>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center gap-2 py-20 text-gray-700 dark:text-gray-300">
            <AlertCircle className="h-5 w-5" />
            <span className="text-sm">{error}</span>
          </div>
        ) : companies.length === 0 ? (
          <div className="py-20 text-center text-sm text-gray-500 dark:text-gray-500">
            No prospects found matching your filters.
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-500">
                {/* Select-all checkbox */}
                <th className="w-10 px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleSelectAll}
                    className="h-4 w-4 rounded border-gray-300 text-gray-900 dark:text-gray-100"
                  />
                </th>
                {(
                  [
                    ["name", "Name"],
                    ["tier", "Tier"],
                    ["pqs_total", "PQS Score"],
                    ["status", "Status"],
                    ["sub_sector", "Sub-Sector"],
                    ["state", "State"],
                    ["updated_at", "Last Activity"],
                  ] as [SortKey, string][]
                ).map(([key, label]) => (
                  <th
                    key={key}
                    className="cursor-pointer select-none whitespace-nowrap px-4 py-3 hover:text-gray-700 dark:text-gray-300"
                    onClick={() => handleSort(key)}
                  >
                    {label}
                    <SortIcon column={key} />
                  </th>
                ))}
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {companies.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => router.push(`/prospects/${c.id}`)}
                  className={cn(
                    "cursor-pointer transition-colors hover:bg-gray-50 dark:hover:bg-gray-800",
                    c.status === "disqualified" && "opacity-50",
                    selectedIds.has(c.id) && "bg-gray-50 dark:bg-gray-800"
                  )}
                >
                  {/* Row checkbox */}
                  <td
                    className="w-10 px-4 py-3"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelectOne(c.id);
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(c.id)}
                      onChange={() => toggleSelectOne(c.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="h-4 w-4 rounded border-gray-300 text-gray-900 dark:text-gray-100"
                    />
                  </td>

                  {/* Name */}
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                    <div className="flex items-center gap-1.5">
                      {c.priority_flag && (
                        <Flag className="h-3.5 w-3.5 fill-gray-600 text-gray-600 dark:text-gray-500" />
                      )}
                      {c.domain && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={`https://logo.clearbit.com/${c.domain}`}
                          alt=""
                          className="h-5 w-5 shrink-0 rounded"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                        />
                      )}
                      <div>
                        <div className="whitespace-nowrap">{c.name}</div>
                        {(c.employee_count != null || c.revenue_range) && (
                          <div className="mt-0.5 flex items-center gap-2 text-xs font-normal text-gray-400 dark:text-gray-500">
                            {c.employee_count != null && (
                              <span>{c.employee_count.toLocaleString()} emp</span>
                            )}
                            {c.employee_count != null && c.revenue_range && (
                              <span>&middot;</span>
                            )}
                            {c.revenue_range && <span>{c.revenue_range}</span>}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* Tier */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600 dark:text-gray-500">
                    {c.tier ? (
                      <span className="rounded bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs font-medium">
                        {c.tier}
                      </span>
                    ) : (
                      <span className="text-gray-400 dark:text-gray-500">&mdash;</span>
                    )}
                  </td>

                  {/* PQS Score */}
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="group relative inline-block">
                      <span className="cursor-help font-semibold text-gray-900 dark:text-gray-100">
                        {c.pqs_total}
                      </span>
                      <span className="text-gray-400 dark:text-gray-500">/100</span>
                      {/* Breakdown tooltip */}
                      <div className="invisible absolute bottom-full left-1/2 z-30 mb-2 -translate-x-1/2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 shadow-lg group-hover:visible">
                        <div className="space-y-1.5 text-xs whitespace-nowrap">
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-gray-500 dark:text-gray-500">Firmographic</span>
                            <span className="font-semibold text-gray-900 dark:text-gray-100">{c.pqs_firmographic}</span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-gray-500 dark:text-gray-500">Technographic</span>
                            <span className="font-semibold text-gray-900 dark:text-gray-100">{c.pqs_technographic}</span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-gray-500 dark:text-gray-500">Timing</span>
                            <span className="font-semibold text-gray-900 dark:text-gray-100">{c.pqs_timing}</span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-gray-500 dark:text-gray-500">Engagement</span>
                            <span className="font-semibold text-gray-900 dark:text-gray-100">{c.pqs_engagement}</span>
                          </div>
                        </div>
                        {/* Arrow */}
                        <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-white" />
                      </div>
                    </div>
                  </td>

                  {/* Status */}
                  <td className="whitespace-nowrap px-4 py-3">
                    <span
                      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-medium capitalize bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-500"
                    >
                      {c.status.replace(/_/g, " ")}
                    </span>
                  </td>

                  {/* Sub-Sector */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600 dark:text-gray-500">
                    {c.sub_sector || <span className="text-gray-400 dark:text-gray-500">&mdash;</span>}
                  </td>

                  {/* State */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600 dark:text-gray-500">
                    {c.state || <span className="text-gray-400 dark:text-gray-500">&mdash;</span>}
                  </td>

                  {/* Last Activity */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-500 dark:text-gray-500">
                    {c.updated_at ? formatTimeAgo(c.updated_at) : "\u2014"}
                  </td>

                  {/* Actions */}
                  <td className="whitespace-nowrap px-2 py-3">
                    <RowActions
                      company={c}
                      onFlagToggle={handleFlagToggle}
                      onDisqualify={handleDisqualify}
                      onQuickNote={handleQuickNote}
                      loading={actionLoading === c.id}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ---- Pagination ---- */}
      {!loading && companies.length > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3">
          <span className="text-sm text-gray-600 dark:text-gray-500">
            Showing {offset + 1}&ndash;{Math.min(offset + PAGE_SIZE, totalCount)} of{" "}
            {totalCount}
          </span>
          <div className="flex items-center gap-2">
            <button
              disabled={!hasPrev}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </button>
            <button
              disabled={!hasNext}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* ---- Add Company Modal ---- */}
      {showAddModal && (
        <AddCompanyModal
          onClose={() => setShowAddModal(false)}
          onCreated={fetchData}
        />
      )}

      {/* ---- Quick Note Modal ---- */}
      {quickNoteCompany && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div className="w-full max-w-md rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-6 shadow-lg">
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{quickNoteCompany.name}</h3>
            <textarea
              value={quickNoteText}
              onChange={(e) => setQuickNoteText(e.target.value)}
              placeholder="Add a note..."
              rows={3}
              className="mt-3 w-full rounded-md border border-gray-300 p-3 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:text-gray-500 focus:border-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
              autoFocus
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                onClick={() => { setQuickNoteCompany(null); setQuickNoteText(""); }}
                className="rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveNote}
                disabled={quickNoteSaving || !quickNoteText.trim()}
                className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              >
                {quickNoteSaving ? "Saving..." : "Save Note"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
