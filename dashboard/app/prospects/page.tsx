"use client";

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
} from "lucide-react";

import { getCompanies, updateCompany, createCompany, type Company } from "@/lib/api";
import {
  cn,
  formatTimeAgo,
  STATUS_COLORS,
  TIER_LABELS,
  getPQSColor,
} from "@/lib/utils";

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

const MIDWEST_STATES = ["IL", "IN", "MI", "OH", "WI", "MN", "IA", "MO"];

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
  "w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600">{label}</label>
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
      <div className="w-full max-w-lg rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-base font-semibold text-gray-900">Add Company Manually</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="max-h-[80vh] overflow-y-auto">
          <div className="space-y-4 px-6 py-5">
            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
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
                  {MIDWEST_STATES.map((s) => (
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

            <div className="border-t border-gray-100 pt-2">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">
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
                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={form.contact_is_dm}
                    onChange={(e) => set("contact_is_dm", e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-digitillis-accent"
                  />
                  Mark as decision maker
                </label>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !form.name.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-digitillis-accent px-5 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
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
  loading,
}: {
  company: Company;
  onFlagToggle: (c: Company) => void;
  onDisqualify: (c: Company) => void;
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
        className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 disabled:opacity-40"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <MoreHorizontal className="h-4 w-4" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-8 z-20 w-44 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          {/* Flag priority */}
          <button
            onClick={() => { onFlagToggle(company); setOpen(false); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            <Flag
              className={cn(
                "h-4 w-4",
                company.priority_flag
                  ? "fill-orange-400 text-orange-400"
                  : "text-gray-400"
              )}
            />
            {company.priority_flag ? "Remove flag" : "Flag priority"}
          </button>

          <div className="my-1 border-t border-gray-100" />

          {/* Disqualify */}
          {company.status !== "disqualified" && (
            confirmDisqualify ? (
              <div className="px-3 py-2">
                <p className="mb-2 text-xs text-gray-500">Disqualify this company?</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => { onDisqualify(company); setOpen(false); setConfirmDisqualify(false); }}
                    className="flex-1 rounded-md bg-digitillis-danger px-2 py-1 text-xs font-medium text-white hover:opacity-90"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => setConfirmDisqualify(false)}
                    className="flex-1 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDisqualify(true)}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-digitillis-danger hover:bg-red-50"
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
              className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
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

  // --- UI state ---
  const [showAddModal, setShowAddModal] = useState(false);
  const [exporting, setExporting] = useState(false);

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

      const res = await getCompanies(params);
      let data = res.data ?? [];

      // Client-side search filter
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        data = data.filter((c) => c.name.toLowerCase().includes(q));
      }

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
      return <ChevronsUpDown className="ml-1 inline h-3.5 w-3.5 text-gray-400" />;
    }
    return sortDir === "asc" ? (
      <ChevronUp className="ml-1 inline h-3.5 w-3.5 text-gray-700" />
    ) : (
      <ChevronDown className="ml-1 inline h-3.5 w-3.5 text-gray-700" />
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
      const res = await getCompanies(params);
      let data = res.data ?? [];
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        data = data.filter((c) => c.name.toLowerCase().includes(q));
      }
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

  // --- Pagination ---
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < totalCount;

  // --- Render ---
  return (
    <div className="space-y-4">
      {/* Page heading */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-bold text-gray-900">Prospects</h2>
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-sm text-gray-500">
            {totalCount} {totalCount === 1 ? "company" : "companies"}
          </span>
          <button
            onClick={handleExport}
            disabled={exporting || loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
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
            className="inline-flex items-center gap-1.5 rounded-lg bg-digitillis-accent px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            Add Company
          </button>
        </div>
      </div>

      {/* ---- Filter bar ---- */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 bg-white p-3">
        {/* Search */}
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by company name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-md border border-gray-300 py-1.5 pl-8 pr-3 text-sm focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent"
          />
        </div>

        {/* Status */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent"
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
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent"
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
          <label htmlFor="pqs-min" className="text-xs font-medium text-gray-600">
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
            className="w-16 rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent"
          />
        </div>
      </div>

      {/* ---- Table ---- */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-digitillis-accent" />
            <span className="ml-2 text-sm text-gray-500">Loading prospects...</span>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center gap-2 py-20 text-digitillis-danger">
            <AlertCircle className="h-5 w-5" />
            <span className="text-sm">{error}</span>
          </div>
        ) : companies.length === 0 ? (
          <div className="py-20 text-center text-sm text-gray-500">
            No prospects found matching your filters.
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50 text-xs font-medium uppercase tracking-wider text-gray-500">
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
                    className="cursor-pointer select-none whitespace-nowrap px-4 py-3 hover:text-gray-700"
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
                    "cursor-pointer transition-colors hover:bg-gray-50",
                    c.status === "disqualified" && "opacity-50"
                  )}
                >
                  {/* Name */}
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-gray-900">
                    <div className="flex items-center gap-1.5">
                      {c.priority_flag && (
                        <Flag className="h-3.5 w-3.5 fill-orange-400 text-orange-400" />
                      )}
                      {c.name}
                    </div>
                  </td>

                  {/* Tier */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600">
                    {c.tier ? (
                      <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium">
                        {c.tier}
                      </span>
                    ) : (
                      <span className="text-gray-400">&mdash;</span>
                    )}
                  </td>

                  {/* PQS Score */}
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className={cn("font-semibold", getPQSColor(c.pqs_total))}>
                      {c.pqs_total}
                    </span>
                    <span className="text-gray-400">/100</span>
                  </td>

                  {/* Status */}
                  <td className="whitespace-nowrap px-4 py-3">
                    <span
                      className={cn(
                        "inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
                        STATUS_COLORS[c.status] ?? "bg-gray-100 text-gray-600"
                      )}
                    >
                      {c.status.replace(/_/g, " ")}
                    </span>
                  </td>

                  {/* Sub-Sector */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600">
                    {c.sub_sector || <span className="text-gray-400">&mdash;</span>}
                  </td>

                  {/* State */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600">
                    {c.state || <span className="text-gray-400">&mdash;</span>}
                  </td>

                  {/* Last Activity */}
                  <td className="whitespace-nowrap px-4 py-3 text-gray-500">
                    {c.updated_at ? formatTimeAgo(c.updated_at) : "\u2014"}
                  </td>

                  {/* Actions */}
                  <td className="whitespace-nowrap px-2 py-3">
                    <RowActions
                      company={c}
                      onFlagToggle={handleFlagToggle}
                      onDisqualify={handleDisqualify}
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
        <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3">
          <span className="text-sm text-gray-600">
            Showing {offset + 1}&ndash;{Math.min(offset + PAGE_SIZE, totalCount)} of{" "}
            {totalCount}
          </span>
          <div className="flex items-center gap-2">
            <button
              disabled={!hasPrev}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </button>
            <button
              disabled={!hasNext}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
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
    </div>
  );
}
