"use client";

/**
 * Data Quality Monitor — Identify missing fields, stale records, and data gaps
 *
 * Expected actions:
 * Review companies with missing research, contacts without emails, stale records needing refresh
 */


import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Loader2, ShieldCheck, UserPlus, AlertTriangle } from "lucide-react";
import { getDataQuality, DataQuality } from "@/lib/api";
import { cn } from "@/lib/utils";

const FIELD_LABELS: Record<string, string> = {
  domain: "Domain",
  tier: "Tier",
  state: "State",
  industry: "Industry",
  employee_count: "Employee Count",
  revenue_range: "Revenue Range",
  contacts: "Has Contacts",
  contact_email: "Contact Email",
};

function ScoreColor(score: number): string {
  if (score >= 80) return "text-green-600";
  if (score >= 60) return "text-amber-500";
  return "text-red-500";
}

function BarColor(coverage: number): string {
  if (coverage >= 80) return "bg-green-500";
  if (coverage >= 60) return "bg-amber-400";
  return "bg-red-400";
}

export default function DataQualityPage() {
  const [data, setData] = useState<DataQuality | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getDataQuality();
      setData(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data quality");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Data Quality</h2>
          <p className="mt-1 text-sm text-gray-500">
            Completeness analysis across all prospect companies
          </p>
        </div>
        <Link
          href="/analytics"
          className="text-sm text-digitillis-accent hover:underline"
        >
          ← Back to Analytics
        </Link>
      </div>

      {loading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
          {error}
        </div>
      ) : data ? (
        <>
          {/* Overall Score */}
          <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-4">
              <ShieldCheck className="h-6 w-6 text-digitillis-accent" />
              <h3 className="text-lg font-semibold text-gray-900">Overall Completeness</h3>
            </div>
            <div className="flex items-end gap-6">
              <div>
                <span
                  className={cn(
                    "text-7xl font-extrabold leading-none",
                    ScoreColor(data.overall_completeness)
                  )}
                >
                  {data.overall_completeness}%
                </span>
                <p className="mt-2 text-sm text-gray-500">
                  across {data.total_companies.toLocaleString()} companies · 8 tracked fields
                </p>
              </div>
              <div className="mb-1 flex gap-4 text-xs text-gray-400">
                <span className="flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-full bg-green-500" />
                  ≥80% Good
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                  60–79% Fair
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  &lt;60% Poor
                </span>
              </div>
            </div>
          </section>

          {/* Field Coverage Bars */}
          <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-5">Field Coverage</h3>
            <div className="space-y-3">
              {Object.entries(data.field_coverage).map(([field, stats]) => (
                <div key={field} className="flex items-center gap-4">
                  <div className="w-36 shrink-0 text-sm font-medium text-gray-700">
                    {FIELD_LABELS[field] ?? field}
                  </div>
                  <div className="relative flex-1 h-6 rounded-full bg-gray-100 overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        BarColor(stats.coverage)
                      )}
                      style={{ width: `${stats.coverage}%` }}
                    />
                  </div>
                  <div className="w-20 shrink-0 text-right">
                    <span
                      className={cn(
                        "text-sm font-semibold",
                        ScoreColor(stats.coverage)
                      )}
                    >
                      {stats.coverage}%
                    </span>
                    <span className="ml-1 text-xs text-gray-400">
                      ({stats.missing} missing)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Incomplete Companies Table */}
          <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-5">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              <h3 className="text-lg font-semibold text-gray-900">
                Most Incomplete Companies
              </h3>
              <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
                {data.incomplete_companies.length} shown
              </span>
            </div>

            {data.incomplete_companies.length === 0 ? (
              <p className="text-center text-sm text-gray-400 py-6">
                All companies have complete data.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-gray-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="px-4 py-3 text-left font-medium text-gray-600">
                        Company
                      </th>
                      <th className="px-4 py-3 text-left font-medium text-gray-600">
                        Status
                      </th>
                      <th className="px-4 py-3 text-left font-medium text-gray-600">
                        Tier
                      </th>
                      <th className="px-4 py-3 text-left font-medium text-gray-600">
                        Missing Fields
                      </th>
                      <th className="px-4 py-3 text-right font-medium text-gray-600">
                        Completeness
                      </th>
                      <th className="px-4 py-3 text-right font-medium text-gray-600">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.incomplete_companies.map((company) => (
                      <tr
                        key={company.id}
                        className="hover:bg-gray-50 transition-colors"
                      >
                        <td className="px-4 py-3">
                          <Link
                            href={`/prospects/${company.id}`}
                            className="font-medium text-digitillis-accent hover:underline"
                          >
                            {company.name}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-gray-600 capitalize">
                          {company.status ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {company.tier ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {company.missing_fields.map((f) => (
                              <span
                                key={f}
                                className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"
                              >
                                {FIELD_LABELS[f] ?? f}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <span
                            className={cn(
                              "font-semibold",
                              ScoreColor(company.completeness)
                            )}
                          >
                            {company.completeness}%
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {company.missing_fields.includes("contacts") ||
                          company.missing_fields.includes("contact_email") ? (
                            <Link
                              href="/enrichment"
                              className="inline-flex items-center gap-1 rounded-md bg-digitillis-accent/10 px-2.5 py-1 text-xs font-medium text-digitillis-accent hover:bg-digitillis-accent/20 transition-colors"
                            >
                              <UserPlus className="h-3 w-3" />
                              Enrich
                            </Link>
                          ) : (
                            <Link
                              href={`/prospects/${company.id}`}
                              className="text-xs text-gray-400 hover:text-digitillis-accent transition-colors"
                            >
                              Edit
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
