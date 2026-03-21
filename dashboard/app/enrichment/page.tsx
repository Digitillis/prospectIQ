"use client";

/**
 * Enrichment Manager — Track Apollo credit usage and contact enrichment status
 *
 * Expected actions:
 * Trigger enrichment for qualified companies, monitor credit consumption, review enrichment results
 */


import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  UserPlus,
  Loader2,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Building2,
  Users,
} from "lucide-react";
import { getCompanies, enrichCompany, Company } from "@/lib/api";
import { cn } from "@/lib/utils";

const TIER_COLORS: Record<string, string> = {
  tier1: "bg-digitillis-accent/10 text-digitillis-accent border-digitillis-accent/20",
  tier2: "bg-digitillis-success/10 text-digitillis-success border-digitillis-success/20",
  tier3: "bg-amber-50 text-amber-700 border-amber-200",
};

const TIER_LABELS: Record<string, string> = {
  tier1: "Tier 1",
  tier2: "Tier 2",
  tier3: "Tier 3",
};

type EnrichStatus =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; contacts_enriched: number; contacts_skipped: number; errors: number }
  | { kind: "error"; message: string };

interface EnrichableCompany extends Company {
  contact_count?: number;
}

export default function EnrichmentQueuePage() {
  const [companies, setCompanies] = useState<EnrichableCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrichStatuses, setEnrichStatuses] = useState<Record<string, EnrichStatus>>({});
  const [enrichAllProgress, setEnrichAllProgress] = useState<{
    active: boolean;
    current: number;
    total: number;
  }>({ active: false, current: 0, total: 0 });
  const abortRef = useRef(false);

  const fetchCompanies = useCallback(async () => {
    setLoading(true);
    try {
      const [researchedRes, qualifiedRes] = await Promise.all([
        getCompanies({ status: "researched", limit: "100" }),
        getCompanies({ status: "qualified", limit: "100" }),
      ]);

      // Merge and deduplicate by id
      const merged = new Map<string, EnrichableCompany>();
      for (const c of [...(researchedRes.data ?? []), ...(qualifiedRes.data ?? [])]) {
        if (!merged.has(c.id)) {
          merged.set(c.id, c);
        }
      }

      // Sort: prioritise tier1 > tier2 > tier3, then by PQS desc
      const sorted = [...merged.values()].sort((a, b) => {
        const tierOrder: Record<string, number> = { tier1: 0, tier2: 1, tier3: 2 };
        const ta = tierOrder[a.tier ?? "tier3"] ?? 2;
        const tb = tierOrder[b.tier ?? "tier3"] ?? 2;
        if (ta !== tb) return ta - tb;
        return (b.pqs_total ?? 0) - (a.pqs_total ?? 0);
      });

      setCompanies(sorted);
    } catch {
      // Leave empty on error
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCompanies();
  }, [fetchCompanies]);

  const handleEnrich = useCallback(async (companyId: string) => {
    setEnrichStatuses((prev) => ({ ...prev, [companyId]: { kind: "loading" } }));
    try {
      const res = await enrichCompany(companyId);
      setEnrichStatuses((prev) => ({
        ...prev,
        [companyId]: { kind: "done", ...res.data },
      }));
    } catch (err) {
      setEnrichStatuses((prev) => ({
        ...prev,
        [companyId]: {
          kind: "error",
          message: err instanceof Error ? err.message : "Enrichment failed",
        },
      }));
    }
  }, []);

  const handleEnrichAll = useCallback(async () => {
    const pending = companies.filter((c) => {
      const s = enrichStatuses[c.id];
      return !s || s.kind === "idle" || s.kind === "error";
    });
    if (pending.length === 0) return;

    abortRef.current = false;
    setEnrichAllProgress({ active: true, current: 0, total: pending.length });

    for (let i = 0; i < pending.length; i++) {
      if (abortRef.current) break;
      const company = pending[i];
      setEnrichAllProgress({ active: true, current: i + 1, total: pending.length });
      await handleEnrich(company.id);
      // Small delay to avoid hammering the API
      await new Promise((r) => setTimeout(r, 300));
    }

    setEnrichAllProgress((prev) => ({ ...prev, active: false }));
  }, [companies, enrichStatuses, handleEnrich]);

  const handleStop = () => {
    abortRef.current = true;
    setEnrichAllProgress((prev) => ({ ...prev, active: false }));
  };

  const pendingCount = companies.filter((c) => {
    const s = enrichStatuses[c.id];
    return !s || s.kind === "idle" || s.kind === "error";
  }).length;

  const doneCount = companies.filter((c) => enrichStatuses[c.id]?.kind === "done").length;

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Contact Enrichment Queue</h2>
          <p className="mt-1 text-sm text-gray-500">
            Researched and qualified companies ready for Apollo contact enrichment.
          </p>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={fetchCompanies}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 shadow-sm hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </button>

          {enrichAllProgress.active ? (
            <button
              onClick={handleStop}
              className="flex items-center gap-1.5 rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-600 transition-colors"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              Stop ({enrichAllProgress.current}/{enrichAllProgress.total})
            </button>
          ) : (
            <button
              onClick={handleEnrichAll}
              disabled={loading || pendingCount === 0}
              className="flex items-center gap-1.5 rounded-lg bg-digitillis-accent px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-digitillis-accent/90 disabled:opacity-50 transition-colors"
            >
              <UserPlus className="h-4 w-4" />
              Enrich All ({pendingCount})
            </button>
          )}
        </div>
      </div>

      {/* Summary bar */}
      {!loading && companies.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Building2 className="h-4 w-4 text-digitillis-accent" />
              Total in Queue
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">{companies.length}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <CheckCircle2 className="h-4 w-4 text-digitillis-success" />
              Enriched This Session
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">{doneCount}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Users className="h-4 w-4 text-amber-500" />
              Pending Enrichment
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">{pendingCount}</p>
          </div>
        </div>
      )}

      {/* Company list */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex h-48 items-center justify-center gap-3 text-gray-400">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading companies...</span>
          </div>
        ) : companies.length === 0 ? (
          <div className="flex flex-col h-48 items-center justify-center gap-2 text-gray-400">
            <UserPlus className="h-8 w-8" />
            <p className="text-sm font-medium">No companies need enrichment right now.</p>
            <p className="text-xs text-gray-300">
              Companies appear here once they reach Researched or Qualified status.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {companies.map((company) => {
              const status = enrichStatuses[company.id] ?? { kind: "idle" };

              return (
                <div
                  key={company.id}
                  className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors"
                >
                  {/* Company info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link
                        href={`/prospects/${company.id}`}
                        className="text-sm font-semibold text-gray-900 hover:text-digitillis-accent truncate transition-colors"
                      >
                        {company.name}
                      </Link>
                      {company.tier && (
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                            TIER_COLORS[company.tier] ?? "bg-gray-100 text-gray-600 border-gray-200"
                          )}
                        >
                          {TIER_LABELS[company.tier] ?? company.tier}
                        </span>
                      )}
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                          company.status === "qualified"
                            ? "bg-digitillis-success/10 text-digitillis-success border-digitillis-success/20"
                            : "bg-blue-50 text-blue-700 border-blue-200"
                        )}
                      >
                        {company.status}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-3 text-xs text-gray-400">
                      {company.domain && <span>{company.domain}</span>}
                      <span>PQS {company.pqs_total ?? 0}</span>
                      {company.industry && <span>{company.industry}</span>}
                    </div>
                  </div>

                  {/* Enrichment status / button */}
                  <div className="shrink-0 flex items-center gap-3">
                    {status.kind === "idle" && (
                      <button
                        onClick={() => handleEnrich(company.id)}
                        className="flex items-center gap-1.5 rounded-lg bg-digitillis-accent/10 px-3 py-1.5 text-xs font-semibold text-digitillis-accent hover:bg-digitillis-accent/20 transition-colors"
                      >
                        <UserPlus className="h-3.5 w-3.5" />
                        Enrich Contacts
                      </button>
                    )}

                    {status.kind === "loading" && (
                      <div className="flex items-center gap-1.5 text-xs text-gray-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Enriching...
                      </div>
                    )}

                    {status.kind === "done" && (
                      <div className="flex items-center gap-1.5 text-xs text-digitillis-success">
                        <CheckCircle2 className="h-4 w-4" />
                        <span>
                          {status.contacts_enriched} found
                          {status.contacts_skipped > 0 && `, ${status.contacts_skipped} skipped`}
                        </span>
                      </div>
                    )}

                    {status.kind === "error" && (
                      <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1.5 text-xs text-red-500" title={status.message}>
                          <AlertCircle className="h-4 w-4" />
                          Failed
                        </div>
                        <button
                          onClick={() => handleEnrich(company.id)}
                          className="text-xs text-gray-400 underline hover:text-gray-600 transition-colors"
                        >
                          Retry
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Batch progress overlay */}
      {enrichAllProgress.active && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl border border-gray-200 bg-white p-4 shadow-xl">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-digitillis-accent shrink-0" />
            <div>
              <p className="text-sm font-semibold text-gray-900">
                Enriching companies...
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {enrichAllProgress.current} of {enrichAllProgress.total} processed
              </p>
            </div>
          </div>
          <div className="mt-3 h-1.5 w-56 overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-full rounded-full bg-digitillis-accent transition-all duration-300"
              style={{
                width: `${Math.round((enrichAllProgress.current / enrichAllProgress.total) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
