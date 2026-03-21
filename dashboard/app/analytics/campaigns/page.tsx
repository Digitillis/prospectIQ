"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Loader2, Megaphone } from "lucide-react";
import { getCampaignPerformance, CampaignPerformance } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  discovered: "bg-slate-400",
  researched: "bg-blue-500",
  qualified: "bg-green-500",
  outreach_pending: "bg-cyan-500",
  contacted: "bg-indigo-500",
  engaged: "bg-purple-500",
  meeting_scheduled: "bg-pink-500",
  pilot_discussion: "bg-amber-500",
  pilot_signed: "bg-orange-500",
  converted: "bg-emerald-600",
  not_interested: "bg-red-400",
  disqualified: "bg-red-600",
  paused: "bg-gray-400",
};

function advancementColor(rate: number): string {
  if (rate >= 30) return "text-green-600";
  if (rate >= 15) return "text-amber-500";
  return "text-red-500";
}

function advancementBg(rate: number): string {
  if (rate >= 30) return "bg-green-100 text-green-700";
  if (rate >= 15) return "bg-amber-100 text-amber-700";
  return "bg-red-100 text-red-700";
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<CampaignPerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getCampaignPerformance();
      setCampaigns(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load campaign data");
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
          <h2 className="text-2xl font-bold text-gray-900">Campaign Performance</h2>
          <p className="mt-1 text-sm text-gray-500">
            Effectiveness of each discovery campaign by advancement rate and PQS
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
      ) : campaigns.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
          <Megaphone className="mx-auto h-10 w-10 text-gray-300 mb-3" />
          <p className="text-sm text-gray-500">
            No campaign data found. Companies need a{" "}
            <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">campaign_name</code>{" "}
            to appear here.
          </p>
        </div>
      ) : (
        <section className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
            <Megaphone className="h-5 w-5 text-digitillis-accent" />
            <h3 className="text-lg font-semibold text-gray-900">
              Campaigns
            </h3>
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
              {campaigns.length} campaigns
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="px-6 py-3 text-left font-medium text-gray-600">
                    Campaign
                  </th>
                  <th className="px-6 py-3 text-right font-medium text-gray-600">
                    Companies
                  </th>
                  <th className="px-6 py-3 text-right font-medium text-gray-600">
                    Avg PQS
                  </th>
                  <th className="px-6 py-3 text-right font-medium text-gray-600">
                    Advancement Rate
                  </th>
                  <th className="px-6 py-3 text-left font-medium text-gray-600">
                    Status Breakdown
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {campaigns.map((camp) => {
                  const statusEntries = Object.entries(camp.statuses).sort(
                    (a, b) => b[1] - a[1]
                  );
                  const total = camp.total;

                  return (
                    <tr
                      key={camp.name}
                      className="hover:bg-gray-50 transition-colors"
                    >
                      {/* Campaign name */}
                      <td className="px-6 py-4">
                        <span className="font-medium text-gray-900">
                          {camp.name}
                        </span>
                      </td>

                      {/* Total */}
                      <td className="px-6 py-4 text-right font-semibold text-gray-800">
                        {camp.total.toLocaleString()}
                      </td>

                      {/* Avg PQS */}
                      <td className="px-6 py-4 text-right">
                        <span
                          className={cn(
                            "font-semibold",
                            camp.avg_pqs >= 70
                              ? "text-green-600"
                              : camp.avg_pqs >= 50
                              ? "text-amber-500"
                              : "text-gray-600"
                          )}
                        >
                          {camp.avg_pqs}
                        </span>
                      </td>

                      {/* Advancement Rate */}
                      <td className="px-6 py-4 text-right">
                        <span
                          className={cn(
                            "inline-block rounded-full px-2.5 py-1 text-xs font-semibold",
                            advancementBg(camp.advancement_rate)
                          )}
                        >
                          {camp.advancement_rate}%
                        </span>
                      </td>

                      {/* Status Breakdown — stacked mini-bar + legend */}
                      <td className="px-6 py-4">
                        <div className="space-y-2">
                          {/* Stacked bar */}
                          <div className="flex h-3 w-full overflow-hidden rounded-full bg-gray-100">
                            {statusEntries.map(([status, count]) => (
                              <div
                                key={status}
                                className={cn(
                                  "h-full",
                                  STATUS_COLORS[status] ?? "bg-gray-300"
                                )}
                                style={{
                                  width: `${(count / total) * 100}%`,
                                }}
                                title={`${status}: ${count}`}
                              />
                            ))}
                          </div>
                          {/* Legend chips */}
                          <div className="flex flex-wrap gap-1">
                            {statusEntries.slice(0, 5).map(([status, count]) => (
                              <span
                                key={status}
                                className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600"
                              >
                                {status.replace(/_/g, " ")}: {count}
                              </span>
                            ))}
                            {statusEntries.length > 5 && (
                              <span className="text-xs text-gray-400">
                                +{statusEntries.length - 5} more
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Legend footer */}
          <div className="border-t border-gray-100 px-6 py-3 bg-gray-50">
            <p className="text-xs text-gray-400">
              Advancement rate = companies that reached qualified, contacted, engaged, meeting, or pilot stages.
              Green ≥30% · Amber ≥15% · Red &lt;15%
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
