"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  BarChart3,
  Loader2,
  RefreshCw,
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Clock,
  Mail,
  Linkedin,
  MessageSquare,
} from "lucide-react";
import { getSequencePerformance, SequencePerformance } from "@/lib/api";
import { cn } from "@/lib/utils";

// Group sequence steps under their parent sequence name
interface SequenceGroup {
  name: string;
  steps: SequencePerformance[];
  totalDrafts: number;
  totalApproved: number;
  totalRejected: number;
  totalPending: number;
}

const CHANNEL_ICONS: Record<string, React.ElementType> = {
  email: Mail,
  linkedin: Linkedin,
  sms: MessageSquare,
};

const CHANNEL_LABELS: Record<string, string> = {
  email: "Email",
  linkedin: "LinkedIn",
  sms: "SMS",
};

function approvalRate(approved: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((approved / total) * 100);
}

function rejectionRate(rejected: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((rejected / total) * 100);
}

function pendingRate(pending: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((pending / total) * 100);
}

export default function SequencePerformancePage() {
  const [data, setData] = useState<SequencePerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSequencePerformance();
      setData(res.data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sequence performance");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Group by sequence name
  const groups: SequenceGroup[] = [];
  const seen = new Map<string, SequenceGroup>();
  for (const row of data) {
    const name = row.sequence_name;
    if (!seen.has(name)) {
      const g: SequenceGroup = {
        name,
        steps: [],
        totalDrafts: 0,
        totalApproved: 0,
        totalRejected: 0,
        totalPending: 0,
      };
      seen.set(name, g);
      groups.push(g);
    }
    const g = seen.get(name)!;
    g.steps.push(row);
    g.totalDrafts += row.total_drafts;
    g.totalApproved += row.approved;
    g.totalRejected += row.rejected;
    g.totalPending += row.pending;
  }

  // Summary across all sequences
  const totalDrafts = data.reduce((s, r) => s + r.total_drafts, 0);
  const totalApproved = data.reduce((s, r) => s + r.approved, 0);
  const overallApprovalRate = approvalRate(totalApproved, totalDrafts);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/analytics"
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Analytics
            </Link>
          </div>
          <h2 className="text-2xl font-bold text-gray-900">Sequence Performance</h2>
          <p className="mt-1 text-sm text-gray-500">
            Approval, rejection, and pending rates per sequence and step.
          </p>
        </div>

        <button
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 shadow-sm hover:bg-gray-50 disabled:opacity-50 transition-colors shrink-0"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* Summary cards */}
      {!loading && !error && totalDrafts > 0 && (
        <div className="grid grid-cols-4 gap-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <BarChart3 className="h-4 w-4 text-digitillis-accent" />
              Total Drafts
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">{totalDrafts.toLocaleString()}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <CheckCircle2 className="h-4 w-4 text-digitillis-success" />
              Approved
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">{totalApproved.toLocaleString()}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <XCircle className="h-4 w-4 text-red-500" />
              Rejected
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">
              {data.reduce((s, r) => s + r.rejected, 0).toLocaleString()}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <CheckCircle2 className="h-4 w-4 text-indigo-500" />
              Overall Approval Rate
            </div>
            <p className="mt-2 text-2xl font-bold text-gray-900">{overallApprovalRate}%</p>
          </div>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex h-48 items-center justify-center gap-3 text-gray-400">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading sequence data...</span>
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-medium text-red-600">{error}</p>
          <button
            onClick={fetchData}
            className="mt-3 text-xs text-red-500 underline hover:text-red-700 transition-colors"
          >
            Try again
          </button>
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col h-48 items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white text-gray-400">
          <BarChart3 className="h-8 w-8" />
          <p className="text-sm font-medium">No outreach drafts recorded yet.</p>
          <p className="text-xs text-gray-300">
            Drafts appear here once sequences start generating outreach.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => {
            const seqApprovalRate = approvalRate(group.totalApproved, group.totalDrafts);

            return (
              <section
                key={group.name}
                className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden"
              >
                {/* Sequence header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50">
                  <div>
                    <h3 className="text-base font-semibold text-gray-900 capitalize">
                      {group.name.replace(/_/g, " ")}
                    </h3>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {group.steps.length} step{group.steps.length !== 1 ? "s" : ""} &middot;{" "}
                      {group.totalDrafts} drafts total
                    </p>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <div className="flex items-center gap-1.5 text-digitillis-success">
                      <CheckCircle2 className="h-4 w-4" />
                      <span className="font-semibold">{seqApprovalRate}%</span>
                      <span className="text-gray-400 text-xs">approval</span>
                    </div>
                    <div className="text-xs text-gray-400">
                      {group.totalApproved} approved &middot; {group.totalRejected} rejected &middot;{" "}
                      {group.totalPending} pending
                    </div>
                  </div>
                </div>

                {/* Step rows */}
                <div className="divide-y divide-gray-50">
                  {group.steps.map((step) => {
                    const ChannelIcon =
                      CHANNEL_ICONS[step.channel?.toLowerCase()] ?? Mail;
                    const approved = step.approved;
                    const rejected = step.rejected;
                    const pending = step.pending;
                    const total = step.total_drafts;

                    const approvedPct = approvalRate(approved, total);
                    const rejectedPct = rejectionRate(rejected, total);
                    const pendingPct = pendingRate(pending, total);

                    return (
                      <div key={`${step.sequence_name}-${step.step}`} className="px-6 py-4">
                        {/* Step label row */}
                        <div className="flex items-center gap-3 mb-3">
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-digitillis-accent/10 text-xs font-bold text-digitillis-accent">
                            {step.step}
                          </div>
                          <div className="flex items-center gap-2">
                            <ChannelIcon className="h-3.5 w-3.5 text-gray-400" />
                            <span className="text-sm font-medium text-gray-700">
                              Step {step.step} &mdash;{" "}
                              {CHANNEL_LABELS[step.channel?.toLowerCase()] ?? step.channel}
                            </span>
                          </div>
                          <span className="ml-auto text-xs text-gray-400">
                            {total} draft{total !== 1 ? "s" : ""}
                          </span>
                        </div>

                        {/* Horizontal stacked bar */}
                        <div className="flex h-6 w-full overflow-hidden rounded-full bg-gray-100">
                          {approvedPct > 0 && (
                            <div
                              className="flex h-full items-center justify-center bg-digitillis-success text-xs font-semibold text-white transition-all duration-500"
                              style={{ width: `${approvedPct}%` }}
                              title={`Approved: ${approved} (${approvedPct}%)`}
                            >
                              {approvedPct >= 8 ? `${approvedPct}%` : ""}
                            </div>
                          )}
                          {rejectedPct > 0 && (
                            <div
                              className="flex h-full items-center justify-center bg-red-400 text-xs font-semibold text-white transition-all duration-500"
                              style={{ width: `${rejectedPct}%` }}
                              title={`Rejected: ${rejected} (${rejectedPct}%)`}
                            >
                              {rejectedPct >= 8 ? `${rejectedPct}%` : ""}
                            </div>
                          )}
                          {pendingPct > 0 && (
                            <div
                              className="flex h-full items-center justify-center bg-gray-300 text-xs font-semibold text-gray-600 transition-all duration-500"
                              style={{ width: `${pendingPct}%` }}
                              title={`Pending: ${pending} (${pendingPct}%)`}
                            >
                              {pendingPct >= 8 ? `${pendingPct}%` : ""}
                            </div>
                          )}
                        </div>

                        {/* Legend */}
                        <div className="mt-2 flex items-center gap-5 text-xs text-gray-500">
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block h-2.5 w-2.5 rounded-full bg-digitillis-success" />
                            Approved {approved}
                          </span>
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-400" />
                            Rejected {rejected}
                          </span>
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-300" />
                            <Clock className="h-3 w-3 text-gray-400" />
                            Pending {pending}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Back link */}
      {!loading && (
        <div className="pt-2">
          <Link
            href="/analytics"
            className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Analytics
          </Link>
        </div>
      )}
    </div>
  );
}
