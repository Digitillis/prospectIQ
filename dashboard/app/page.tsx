"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Users,
  Target,
  Send,
  TrendingUp,
  Clock,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import type { Company } from "@/lib/api";
import {
  cn,
  formatTimeAgo,
  getPQSColor,
  TIER_LABELS,
  STATUS_COLORS,
} from "@/lib/utils";

const PIPELINE_COLUMNS = [
  "discovered",
  "researched",
  "qualified",
  "outreach_pending",
  "contacted",
  "engaged",
  "meeting_scheduled",
] as const;

const COLUMN_LABELS: Record<string, string> = {
  discovered: "Discovered",
  researched: "Researched",
  qualified: "Qualified",
  outreach_pending: "Outreach Pending",
  contacted: "Contacted",
  engaged: "Engaged",
  meeting_scheduled: "Meeting",
};

interface PipelineData {
  [status: string]: { companies: Company[]; count: number };
}

export default function PipelinePage() {
  const [pipeline, setPipeline] = useState<PipelineData>({});
  const [approvalCount, setApprovalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch companies for each pipeline stage in parallel
      const [results, approvalsRes] = await Promise.all([
        Promise.all(
          PIPELINE_COLUMNS.map(async (status) => {
            const res = await fetch(
              `/api/companies?status=${status}&limit=5`
            );
            if (!res.ok) throw new Error(`Failed to fetch ${status}`);
            const json = await res.json();
            return {
              status,
              companies: json.data as Company[],
              count: json.count as number,
            };
          })
        ),
        fetch("/api/approvals").then((r) =>
          r.ok ? r.json() : { count: 0 }
        ),
      ]);

      const data: PipelineData = {};
      for (const r of results) {
        data[r.status] = { companies: r.companies, count: r.count };
      }
      setPipeline(data);
      setApprovalCount(approvalsRes.count ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Compute summary metrics
  const totalProspects = Object.values(pipeline).reduce(
    (sum, col) => sum + col.count,
    0
  );
  const qualifiedCount = pipeline["qualified"]?.count ?? 0;
  const contactedCount = pipeline["contacted"]?.count ?? 0;
  const engagedCount = pipeline["engaged"]?.count ?? 0;
  const responseRate =
    contactedCount > 0
      ? Math.round((engagedCount / contactedCount) * 100)
      : 0;

  return (
    <div className="space-y-6">
      {/* Page header with approval badge */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Pipeline</h2>
          <p className="mt-1 text-sm text-gray-500">
            Overview of your prospect pipeline
          </p>
        </div>
        <div className="flex items-center gap-3">
          {approvalCount > 0 && (
            <Link
              href="/approvals"
              className="flex items-center gap-2 rounded-lg bg-yellow-50 px-3 py-2 text-sm font-medium text-yellow-700 transition-colors hover:bg-yellow-100"
            >
              <AlertCircle className="h-4 w-4" />
              {approvalCount} Pending Approval{approvalCount !== 1 ? "s" : ""}
            </Link>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw
              className={cn("h-4 w-4", loading && "animate-spin")}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary metric cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Total Prospects"
          value={totalProspects}
          icon={Users}
          color="bg-blue-50 text-blue-600"
        />
        <MetricCard
          label="Qualified"
          value={qualifiedCount}
          icon={Target}
          color="bg-green-50 text-green-600"
        />
        <MetricCard
          label="Contacted"
          value={contactedCount}
          icon={Send}
          color="bg-indigo-50 text-indigo-600"
        />
        <MetricCard
          label="Response Rate"
          value={`${responseRate}%`}
          icon={TrendingUp}
          color="bg-purple-50 text-purple-600"
        />
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Pipeline columns */}
      {loading && Object.keys(pipeline).length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
          <span className="ml-2 text-gray-500">Loading pipeline...</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          {PIPELINE_COLUMNS.map((status) => {
            const col = pipeline[status];
            return (
              <PipelineColumn
                key={status}
                status={status}
                label={COLUMN_LABELS[status]}
                companies={col?.companies ?? []}
                count={col?.count ?? 0}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- Sub-components ---

function MetricCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500">{label}</p>
        <div className={cn("rounded-lg p-2", color)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
    </div>
  );
}

function PipelineColumn({
  status,
  label,
  companies,
  count,
}: {
  status: string;
  label: string;
  companies: Company[];
  count: number;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-gray-200 bg-white">
      {/* Column header */}
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-700">{label}</h3>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-xs font-medium",
            STATUS_COLORS[status] ?? "bg-gray-100 text-gray-700"
          )}
        >
          {count}
        </span>
      </div>

      {/* Company cards */}
      <div className="flex flex-col gap-2 p-3">
        {companies.length === 0 ? (
          <p className="py-4 text-center text-xs text-gray-400">
            No prospects
          </p>
        ) : (
          companies.map((company) => (
            <CompanyCard key={company.id} company={company} />
          ))
        )}
        {count > 5 && (
          <Link
            href={`/prospects?status=${status}`}
            className="mt-1 text-center text-xs font-medium text-blue-600 hover:text-blue-800"
          >
            View all {count} &rarr;
          </Link>
        )}
      </div>
    </div>
  );
}

function CompanyCard({ company }: { company: Company }) {
  return (
    <Link
      href={`/prospects/${company.id}`}
      className="block rounded-lg border border-gray-100 bg-gray-50 p-3 transition-colors hover:border-gray-200 hover:bg-white"
    >
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-gray-900 leading-tight">
          {company.name}
        </p>
        {company.tier && (
          <span className="ml-1 shrink-0 rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
            {TIER_LABELS[company.tier] ?? company.tier}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span
          className={cn(
            "text-sm font-semibold",
            getPQSColor(company.pqs_total)
          )}
        >
          PQS {company.pqs_total}
        </span>
        <span className="flex items-center gap-1 text-[11px] text-gray-400">
          <Clock className="h-3 w-3" />
          {formatTimeAgo(company.updated_at)}
        </span>
      </div>
    </Link>
  );
}
