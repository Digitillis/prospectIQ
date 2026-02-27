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
} from "lucide-react";

import { getCompanies, updateCompany, type Company } from "@/lib/api";
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
                    className="flex-1 rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700"
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
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
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

  // --- Row actions ---
  const handleFlagToggle = async (company: Company) => {
    setActionLoading(company.id);
    const newFlag = !company.priority_flag;
    // Optimistic update
    setCompanies((prev) =>
      prev.map((c) => (c.id === company.id ? { ...c, priority_flag: newFlag } : c))
    );
    try {
      await updateCompany(company.id, { priority_flag: newFlag });
    } catch {
      // Revert on failure
      setCompanies((prev) =>
        prev.map((c) => (c.id === company.id ? { ...c, priority_flag: !newFlag } : c))
      );
    } finally {
      setActionLoading(null);
    }
  };

  const handleDisqualify = async (company: Company) => {
    setActionLoading(company.id);
    // Optimistic update
    setCompanies((prev) =>
      prev.map((c) => (c.id === company.id ? { ...c, status: "disqualified" } : c))
    );
    try {
      await updateCompany(company.id, { status: "disqualified" });
    } catch {
      // Revert on failure
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
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900">Prospects</h2>
        <span className="text-sm text-gray-500">
          {totalCount} {totalCount === 1 ? "company" : "companies"}
        </span>
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
            className="w-full rounded-md border border-gray-300 py-1.5 pl-8 pr-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        {/* Status */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
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
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
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
            className="w-16 rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      </div>

      {/* ---- Table ---- */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
            <span className="ml-2 text-sm text-gray-500">Loading prospects...</span>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center gap-2 py-20 text-red-600">
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
    </div>
  );
}
