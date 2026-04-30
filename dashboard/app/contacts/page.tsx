"use client";

/**
 * Contact Directory — All decision-maker contacts across companies
 *
 * Expected actions:
 * Search contacts, filter by persona/seniority, click to view contact detail and interaction history
 */


import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Search,
  Users,
  Loader2,
  ExternalLink,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  X,
} from "lucide-react";
import { getAllContacts, type Contact } from "@/lib/api";
import { cn } from "@/lib/utils";

type ContactWithCompany = Contact & {
  companies?: { id: string; name: string; tier?: string; status: string; pqs_total: number };
};

const PAGE_SIZE = 50;

const PERSONA_OPTIONS = [
  "operations_vp",
  "maintenance_director",
  "plant_manager",
  "coo",
  "cto",
  "it_director",
  "procurement",
  "engineer",
];

const SENIORITY_OPTIONS = [
  "c_suite",
  "vp",
  "director",
  "manager",
  "senior",
  "mid",
  "entry",
];

const DEPARTMENT_OPTIONS = [
  "operations",
  "engineering",
  "maintenance",
  "it",
  "procurement",
  "finance",
  "executive",
  "hr",
  "sales",
];

function formatLabel(s: string) {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function displayName(c: ContactWithCompany): string {
  return c.full_name || [c.first_name, c.last_name].filter(Boolean).join(" ") || "";
}

function exportCSV(contacts: ContactWithCompany[]) {
  const headers = [
    "Name",
    "Title",
    "Email",
    "Company",
    "Seniority",
    "Department",
    "Persona",
    "Decision Maker",
    "LinkedIn",
  ];
  const rows = contacts.map((c) => [
    displayName(c),
    c.title ?? "",
    c.email ?? "",
    c.companies?.name ?? "",
    c.seniority ?? "",
    c.department ?? "",
    c.persona_type ?? "",
    c.is_decision_maker ? "Yes" : "No",
    c.linkedin_url ?? "",
  ]);
  const csv = [headers, ...rows]
    .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "contacts.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState<ContactWithCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState("");
  const [personaFilter, setPersonaFilter] = useState("");
  const [seniorityFilter, setSeniorityFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [dmOnly, setDmOnly] = useState(false);

  // Pagination
  const [page, setPage] = useState(0);

  const fetchContacts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (search) params.search = search;
      if (personaFilter) params.persona_type = personaFilter;
      if (seniorityFilter) params.seniority = seniorityFilter;
      if (departmentFilter) params.department = departmentFilter;
      if (dmOnly) params.is_decision_maker = "true";
      params.limit = "500";
      params.offset = "0";
      const res = await getAllContacts(params);
      setContacts(res.data);
      setPage(0);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load contacts");
    } finally {
      setLoading(false);
    }
  }, [search, personaFilter, seniorityFilter, departmentFilter, dmOnly]);

  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  const totalPages = Math.ceil(contacts.length / PAGE_SIZE);
  const paginated = contacts.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  const hasFilters = search || personaFilter || seniorityFilter || departmentFilter || dmOnly;

  function clearFilters() {
    setSearch("");
    setPersonaFilter("");
    setSeniorityFilter("");
    setDepartmentFilter("");
    setDmOnly(false);
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">Contacts</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">
            All contacts across companies — {loading ? "…" : contacts.length} total
          </p>
        </div>
        <button
          onClick={() => exportCSV(contacts)}
          disabled={contacts.length === 0}
          className="flex items-center gap-2 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-500 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40"
        >
          <Download className="h-4 w-4" />
          Export CSV
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 dark:text-gray-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name…"
            className="h-9 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 pl-9 pr-3 text-sm focus:outline-none focus:ring-1 focus:ring-gray-200 w-52"
          />
        </div>

        {/* Persona */}
        <select
          value={personaFilter}
          onChange={(e) => setPersonaFilter(e.target.value)}
          className="h-9 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 text-sm text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
        >
          <option value="">All Personas</option>
          {PERSONA_OPTIONS.map((p) => (
            <option key={p} value={p}>{formatLabel(p)}</option>
          ))}
        </select>

        {/* Seniority */}
        <select
          value={seniorityFilter}
          onChange={(e) => setSeniorityFilter(e.target.value)}
          className="h-9 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 text-sm text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
        >
          <option value="">All Seniority</option>
          {SENIORITY_OPTIONS.map((s) => (
            <option key={s} value={s}>{formatLabel(s)}</option>
          ))}
        </select>

        {/* Department */}
        <select
          value={departmentFilter}
          onChange={(e) => setDepartmentFilter(e.target.value)}
          className="h-9 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 text-sm text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-gray-200"
        >
          <option value="">All Departments</option>
          {DEPARTMENT_OPTIONS.map((d) => (
            <option key={d} value={d}>{formatLabel(d)}</option>
          ))}
        </select>

        {/* Decision-maker toggle */}
        <button
          onClick={() => setDmOnly((v) => !v)}
          className={cn(
            "flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors",
            dmOnly
              ? "border-gray-900 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
          )}
        >
          <CheckCircle2 className="h-4 w-4" />
          Decision Makers
        </button>

        {/* Clear */}
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="flex h-9 items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 text-xs text-gray-500 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <X className="h-3.5 w-3.5" />
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
        {loading ? (
          <div className="flex h-48 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : error ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-gray-500 dark:text-gray-500">
            <p className="text-sm">{error}</p>
          </div>
        ) : contacts.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-gray-400 dark:text-gray-500">
            <Users className="h-8 w-8" />
            <p className="text-sm">No contacts found</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
                    <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Name</th>
                    <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Title</th>
                    <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Email</th>
                    <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Company</th>
                    <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Seniority</th>
                    <th className="px-4 py-3 text-left text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Department</th>
                    <th className="px-4 py-3 text-center text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">DM</th>
                    <th className="px-4 py-3 text-center text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">LinkedIn</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {paginated.map((contact) => (
                    <tr key={contact.id} className="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                        {contact.companies?.id ? (
                          <Link
                            href={`/prospects/${contact.companies.id}`}
                            className="hover:text-gray-900 dark:text-gray-100 hover:underline"
                          >
                            {displayName(contact) || "—"}
                          </Link>
                        ) : (
                          displayName(contact) || "—"
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-500 max-w-[180px] truncate" title={contact.title}>
                        {contact.title || "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-500">
                        {contact.email ? (
                          <a href={`mailto:${contact.email}`} className="hover:text-gray-900 dark:text-gray-100 hover:underline">
                            {contact.email}
                          </a>
                        ) : (
                          <span className="text-gray-400 dark:text-gray-500">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {contact.companies ? (
                          <Link
                            href={`/prospects/${contact.companies.id}`}
                            className="font-medium text-gray-800 hover:text-gray-900 dark:text-gray-100 hover:underline"
                          >
                            {contact.companies.name}
                          </Link>
                        ) : (
                          <span className="text-gray-400 dark:text-gray-500">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-500">
                        {contact.seniority ? (
                          <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs">
                            {formatLabel(contact.seniority)}
                          </span>
                        ) : (
                          <span className="text-gray-400 dark:text-gray-500">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-500">
                        {contact.department ? formatLabel(contact.department) : <span className="text-gray-400 dark:text-gray-500">—</span>}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {contact.is_decision_maker ? (
                          <CheckCircle2 className="mx-auto h-4 w-4 text-gray-500 dark:text-gray-500" />
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {contact.linkedin_url ? (
                          <a
                            href={contact.linkedin_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center justify-center text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:text-gray-300"
                          >
                            <ExternalLink className="h-4 w-4" />
                          </a>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-gray-100 dark:border-gray-800 px-4 py-3">
                <p className="text-sm text-gray-500 dark:text-gray-500">
                  Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, contacts.length)} of {contacts.length}
                </p>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage((p) => p - 1)}
                    disabled={page === 0}
                    className="flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="px-3 text-sm text-gray-700 dark:text-gray-300">
                    {page + 1} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => p + 1)}
                    disabled={page >= totalPages - 1}
                    className="flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
