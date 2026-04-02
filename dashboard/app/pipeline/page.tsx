"use client";

/**
 * Pipeline Overview — Bird's-eye view of the entire prospecting pipeline
 *
 * Expected actions:
 * Monitor pipeline health, click into any stage to drill down, trigger discovery/research/qualification runs
 */


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
  ArrowRight,
  Ban,
  Search,
  Filter,
  Mail,
  AlertTriangle,
  Zap,
  Bell,
  LayoutGrid,
  List,
} from "lucide-react";
import { getCompanies, getPendingDrafts, getPipelineVelocity, PipelineVelocityStage } from "@/lib/api";
import { useReminders } from "@/lib/use-reminders";
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

// ---------------------------------------------------------------------------
// How It Works — collapsible visual guide
// ---------------------------------------------------------------------------

const FLOW_STEPS = [
  {
    step: 1,
    title: "Discovery",
    description: "Search Apollo for decision-makers matching your ICP",
    details: "Finds VP/Directors at F&B and manufacturing companies by title, revenue, and industry. Free, no credits.",
    action: "Actions → Run Discovery",
    color: "bg-gray-500",
    status: "discovered",
  },
  {
    step: 2,
    title: "Research",
    description: "Deep-dive each company with Perplexity + Claude",
    details: "Web research extracts tech stack, pain signals, IoT maturity, personalization hooks. ~$0.05/company.",
    action: "Actions → Run Research",
    color: "bg-gray-500",
    status: "researched",
  },
  {
    step: 3,
    title: "Qualification",
    description: "Score prospects 0-100 across 4 dimensions (PQS)",
    details: "Firmographic fit + technographic readiness + timing signals + engagement. Companies scoring 15+ qualify.",
    action: "Actions → Run Qualification",
    color: "bg-gray-600",
    status: "qualified",
  },
  {
    step: 4,
    title: "Enrichment",
    description: "Get verified emails and phone numbers",
    details: "Apollo People Match reveals contact details. Domain MX verification prevents bounces. Uses Apollo credits.",
    action: "Actions → Run Enrichment",
    color: "bg-gray-700",
    status: "enriched",
  },
  {
    step: 5,
    title: "Outreach",
    description: "Claude generates personalized email drafts",
    details: "Uses your Outreach Guidelines (Settings tab) for tone, structure, and signature. ~$0.02/draft.",
    action: "Actions → Run Outreach",
    color: "bg-gray-700",
    status: "outreach_pending",
  },
  {
    step: 6,
    title: "Review & Approve",
    description: "Read each draft, edit if needed, send test to yourself",
    details: "Quality score shown per draft. 'Send Test to Me' delivers to your inbox. Nothing sends without your approval.",
    action: "Approvals page",
    color: "bg-gray-800",
    status: "approved",
  },
  {
    step: 7,
    title: "Send & Engage",
    description: "Approved drafts sent via Instantly.ai, track opens/replies",
    details: "Multi-step sequences with follow-ups. Buying signals auto-detected. Hot replies trigger Slack alerts.",
    action: "Actions → Run Engagement",
    color: "bg-gray-900",
    status: "contacted",
  },
];

function HowItWorksGuide() {
  const [open, setOpen] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("prospectiq_guide_dismissed") !== "true";
    }
    return true;
  });

  const dismiss = () => {
    setOpen(false);
    localStorage.setItem("prospectiq_guide_dismissed", "true");
  };

  const show = () => {
    setOpen(true);
    localStorage.removeItem("prospectiq_guide_dismissed");
  };

  if (!open) {
    return (
      <button
        onClick={show}
        className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-digitillis-accent"
      >
        <AlertCircle className="h-3 w-3" />
        Show pipeline guide
      </button>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            How ProspectIQ Works
          </h3>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            Your AI-powered prospecting pipeline in 7 steps
          </p>
        </div>
        <button
          onClick={dismiss}
          className="rounded-md px-2 py-1 text-xs text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300"
        >
          Dismiss
        </button>
      </div>

      {/* Flowchart */}
      <div className="flex items-start gap-0 overflow-x-auto pb-2">
        {FLOW_STEPS.map((step, idx) => (
          <div key={step.step} className="flex items-start shrink-0">
            {/* Step card */}
            <div className="group relative w-36">
              {/* Step number circle */}
              <div className="flex justify-center mb-2">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold text-white shadow-sm",
                    step.color
                  )}
                >
                  {step.step}
                </div>
              </div>
              {/* Title + description */}
              <div className="text-center px-1">
                <p className="text-xs font-semibold text-gray-900">{step.title}</p>
                <p className="mt-0.5 text-[10px] leading-tight text-gray-500">
                  {step.description}
                </p>
              </div>
              {/* Hover tooltip with details */}
              <div className="pointer-events-none absolute left-1/2 top-full z-10 mt-2 w-52 -translate-x-1/2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 opacity-0 shadow-lg transition-opacity group-hover:pointer-events-auto group-hover:opacity-100">
                <p className="text-xs text-gray-700 dark:text-gray-300 leading-relaxed">{step.details}</p>
                <p className="mt-2 text-[10px] font-medium text-digitillis-accent">{step.action}</p>
              </div>
            </div>
            {/* Arrow connector */}
            {idx < FLOW_STEPS.length - 1 && (
              <div className="flex items-center pt-3 px-0.5 shrink-0">
                <ArrowRight className="h-3.5 w-3.5 text-gray-300" />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Quick links */}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gray-200 dark:border-gray-700 pt-3">
        <span className="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Quick start:</span>
        <Link href="/actions" className="rounded bg-gray-900 dark:bg-gray-100 px-2.5 py-1 text-[10px] font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-200">
          Run Pipeline →
        </Link>
        <Link href="/settings" className="rounded bg-gray-100 dark:bg-gray-800 px-2.5 py-1 text-[10px] font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
          Configure ICP
        </Link>
        <Link href="/approvals" className="rounded bg-gray-100 dark:bg-gray-800 px-2.5 py-1 text-[10px] font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700">
          Review Drafts
        </Link>
      </div>
    </div>
  );
}

export default function PipelinePage() {
  const [pipeline, setPipeline] = useState<PipelineData>({});
  const [approvalCount, setApprovalCount] = useState(0);
  const [disqualifiedCount, setDisqualifiedCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"kanban" | "list">("kanban");
  const [velocity, setVelocity] = useState<Record<string, PipelineVelocityStage> | null>(null);
  const { dueReminders } = useReminders();

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch companies for each pipeline stage in parallel
      const [results, approvalsRes, disqualifiedRes, velocityRes] = await Promise.all([
        Promise.all(
          PIPELINE_COLUMNS.map(async (status) => {
            const json = await getCompanies({ status, limit: "5" });
            return {
              status,
              companies: json.data,
              count: json.count,
            };
          })
        ),
        getPendingDrafts().catch(() => ({ data: [], count: 0 })),
        getCompanies({ status: "disqualified", limit: "1" }).catch(() => ({ data: [], count: 0 })),
        getPipelineVelocity().catch(() => ({ data: {} })),
      ]);
      setVelocity(velocityRes.data || null);

      const data: PipelineData = {};
      for (const r of results) {
        data[r.status] = { companies: r.companies, count: r.count };
      }
      setPipeline(data);
      setApprovalCount(approvalsRes.count ?? 0);
      setDisqualifiedCount(disqualifiedRes.count ?? 0);
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

  const discoveredCount = pipeline["discovered"]?.count ?? 0;
  const researchedCount = pipeline["researched"]?.count ?? 0;

  type Nudge = {
    id: string;
    label: string;
    href: string;
    color: string;
    dot: string;
    icon: React.ComponentType<{ className?: string }>;
    priority: number;
  };

  const nudges: Nudge[] = [];
  if (!loading) {
    // Priority 0: Due follow-up reminders — highest priority
    if (dueReminders.length > 0)
      nudges.push({
        id: "reminders",
        icon: Bell,
        label: `${dueReminders.length} follow-up reminder${dueReminders.length !== 1 ? "s" : ""} due`,
        href: "/prospects",
        color: "border-gray-200 bg-gray-50 text-gray-900",
        dot: "bg-gray-900",
        priority: 0,
      });

    // Priority 1: Engaged replies — urgent, follow up now
    if (engagedCount > 0)
      nudges.push({
        id: "engaged",
        label: `${engagedCount} prospect${engagedCount !== 1 ? "s" : ""} replied — follow up now!`,
        href: "/prospects?status=engaged",
        color: "border-gray-200 bg-gray-50 text-gray-900",
        dot: "bg-gray-900",
        icon: Zap,
        priority: 1,
      });

    // Priority 2: Pending approvals
    if (approvalCount > 0)
      nudges.push({
        id: "approvals",
        label: `${approvalCount} draft${approvalCount !== 1 ? "s" : ""} pending your approval`,
        href: "/approvals",
        color: "border-gray-200 bg-gray-50 text-gray-900",
        dot: "bg-gray-700",
        icon: AlertCircle,
        priority: 2,
      });

    // Priority 3: Pipeline bottleneck
    if (discoveredCount > 100 && researchedCount < 10)
      nudges.push({
        id: "bottleneck",
        label: `Pipeline bottleneck: ${discoveredCount} discovered but only ${researchedCount} researched. Run Research to move them forward.`,
        href: "/actions",
        color: "border-gray-200 bg-gray-50 text-gray-900",
        dot: "bg-gray-500",
        icon: AlertTriangle,
        priority: 3,
      });

    // Priority 4: Qualified prospects ready for outreach
    if (qualifiedCount > 5)
      nudges.push({
        id: "outreach",
        label: `${qualifiedCount} qualified prospects — generate outreach drafts?`,
        href: "/actions",
        color: "border-gray-200 bg-gray-50 text-gray-900",
        dot: "bg-gray-900",
        icon: Mail,
        priority: 4,
      });

    // Priority 5: Researched companies ready for qualification
    if (researchedCount > 10)
      nudges.push({
        id: "qualify",
        label: `${researchedCount} researched companies ready for qualification scoring.`,
        href: "/actions",
        color: "border-gray-200 bg-gray-50 text-gray-900",
        dot: "bg-gray-500",
        icon: Filter,
        priority: 5,
      });

    // Priority 6: Discovered companies waiting for research
    if (discoveredCount > 20 && !(discoveredCount > 100 && researchedCount < 10))
      nudges.push({
        id: "research",
        label: `You have ${discoveredCount} discovered companies waiting for research. Run Research →`,
        href: "/actions",
        color: "border-gray-200 bg-gray-50 text-gray-700",
        dot: "bg-gray-400",
        icon: Search,
        priority: 6,
      });
  }

  // Sort by priority and cap at 3
  const visibleNudges = nudges
    .sort((a, b) => a.priority - b.priority)
    .slice(0, 3);

  return (
    <div className="space-y-6">
      {/* Smart Suggestions Banner */}
      {visibleNudges.length > 0 && (
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {visibleNudges.map((n) => (
            <Link
              key={n.id}
              href={n.href}
              className={cn(
                "flex items-center gap-2.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-opacity hover:opacity-80",
                n.color
              )}
            >
              <n.icon className="h-4 w-4 shrink-0" />
              {n.label}
              <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0" />
            </Link>
          ))}
        </div>
      )}

      {/* How It Works — collapsible flowchart guide */}
      <HowItWorksGuide />

      {/* Page header with approval badge */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Pipeline</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Overview of your prospect pipeline
          </p>
        </div>
        <div className="flex items-center gap-3">
          {approvalCount > 0 && (
            <Link
              href="/approvals"
              className="flex items-center gap-2 rounded-md bg-gray-100 dark:bg-gray-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-300 transition-colors hover:bg-gray-200 dark:hover:bg-gray-700"
            >
              <AlertCircle className="h-4 w-4" />
              {approvalCount} Pending Approval{approvalCount !== 1 ? "s" : ""}
            </Link>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            <RefreshCw
              className={cn("h-4 w-4", loading && "animate-spin")}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary metric cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          label="Total Prospects"
          value={totalProspects}
          icon={Users}
          color="bg-gray-100 text-gray-600"
        />
        <MetricCard
          label="Qualified"
          value={qualifiedCount}
          icon={Target}
          color="bg-gray-100 text-gray-600"
        />
        <MetricCard
          label="Contacted"
          value={contactedCount}
          icon={Send}
          color="bg-gray-100 text-gray-600"
        />
        <MetricCard
          label="Response Rate"
          value={`${responseRate}%`}
          icon={TrendingUp}
          color="bg-gray-100 text-gray-600"
        />
        <MetricCard
          label="Disqualified"
          value={disqualifiedCount}
          icon={Ban}
          color="bg-gray-100 text-gray-600"
          href="/prospects?status=disqualified"
        />
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4 text-sm text-gray-700 dark:text-gray-300">
          {error}
        </div>
      )}

      {/* Velocity bar */}
      {velocity && Object.keys(velocity).length > 0 && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              Pipeline Velocity (avg days per stage)
            </h3>
          </div>
          <div className="flex items-end gap-2 overflow-x-auto pb-1">
            {Object.entries(velocity).map(([stage, data]) => {
              const maxDays = Math.max(...Object.values(velocity).map((d) => d.avg_days), 1);
              const barH = Math.max(Math.round((data.avg_days / maxDays) * 60), 4);
              return (
                <div key={stage} className="flex flex-col items-center gap-1 flex-shrink-0 group relative">
                  <div
                    className={cn(
                      "w-10 rounded-t transition-all",
                      data.avg_days > 14 ? "bg-rose-400 dark:bg-rose-600" :
                      data.avg_days > 7 ? "bg-amber-400 dark:bg-amber-600" :
                      "bg-green-400 dark:bg-green-600"
                    )}
                    style={{ height: `${barH}px` }}
                    title={`${stage}: ${data.avg_days}d avg (${data.count} companies)`}
                  />
                  <span className="text-[9px] text-gray-400 font-medium">{data.avg_days}d</span>
                  <span className="text-[8px] text-gray-300 dark:text-gray-600 truncate max-w-[40px] text-center leading-tight">
                    {(COLUMN_LABELS[stage] || stage).split(" ")[0]}
                  </span>
                  {/* Tooltip */}
                  <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 hidden group-hover:block z-10 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-[10px] rounded px-2 py-1 whitespace-nowrap shadow-lg">
                    {COLUMN_LABELS[stage] || stage}: {data.avg_days}d avg · {data.count} co.
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* View mode toggle + pipeline */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 dark:text-gray-500">
          {PIPELINE_COLUMNS.reduce((sum, s) => sum + (pipeline[s]?.count ?? 0), 0)} companies across {PIPELINE_COLUMNS.length} stages
        </span>
        <div className="flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 p-0.5">
          <button
            onClick={() => setViewMode("kanban")}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors",
              viewMode === "kanban"
                ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            )}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
            Kanban
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors",
              viewMode === "list"
                ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            )}
          >
            <List className="h-3.5 w-3.5" />
            List
          </button>
        </div>
      </div>

      {/* Pipeline columns */}
      {loading && Object.keys(pipeline).length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
          <span className="ml-2 text-gray-500">Loading pipeline...</span>
        </div>
      ) : viewMode === "kanban" ? (
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
      ) : (
        /* List view */
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Company</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Tier</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Stage</th>
                <th className="text-right px-3 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">PQS</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Updated</th>
              </tr>
            </thead>
            <tbody>
              {PIPELINE_COLUMNS.flatMap((status) =>
                (pipeline[status]?.companies ?? []).map((company) => (
                  <tr
                    key={company.id}
                    className="border-b border-gray-50 dark:border-gray-800/50 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-3">
                      <a href={`/prospects/${company.id}`} className="flex items-center gap-2 hover:text-blue-600">
                        {company.domain && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={`https://logo.clearbit.com/${company.domain}`}
                            alt=""
                            className="h-4 w-4 shrink-0 rounded"
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                          />
                        )}
                        <span className="font-medium text-gray-900 dark:text-gray-100 truncate max-w-[200px]">
                          {company.name}
                        </span>
                      </a>
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-500 dark:text-gray-400">
                      {company.tier ? (TIER_LABELS[company.tier] ?? company.tier) : "—"}
                    </td>
                    <td className="px-3 py-3">
                      <span className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium",
                        STATUS_COLORS[status] || "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                      )}>
                        {COLUMN_LABELS[status]}
                      </span>
                    </td>
                    <td className={cn("px-3 py-3 text-right text-sm font-bold", getPQSColor(company.pqs_total))}>
                      {company.pqs_total}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-gray-400">
                      {formatTimeAgo(company.updated_at)}
                    </td>
                  </tr>
                ))
              )}
              {/* Per-stage "view all" rows */}
              {PIPELINE_COLUMNS.map((status) => {
                const col = pipeline[status];
                if (!col || col.count <= 5) return null;
                return (
                  <tr key={`${status}-more`} className="bg-gray-50/50 dark:bg-gray-800/20">
                    <td colSpan={5} className="px-4 py-2 text-center text-xs text-gray-400">
                      <a href={`/prospects?status=${status}`} className="hover:text-gray-700 dark:hover:text-gray-300">
                        + {col.count - 5} more in {COLUMN_LABELS[status]} →
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
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
  href,
}: {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  href?: string;
}) {
  const inner = (
    <>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</p>
        <div className={cn("rounded-lg p-2", color)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-100">{value}</p>
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="block rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
      >
        {inner}
      </Link>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">{inner}</div>
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
    <div className="flex flex-col rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
      {/* Column header */}
      <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
        <h3 className="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">{label}</h3>
        <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
          {count}
        </span>
      </div>

      {/* Company cards */}
      <div className="flex flex-col p-2">
        {companies.length === 0 ? (
          <p className="py-4 text-center text-xs text-gray-400 dark:text-gray-500">
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
            className="mt-1 text-center text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
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
      className="block border-b border-gray-100 dark:border-gray-800 last:border-0 px-2 py-2.5 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          {company.domain && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`https://logo.clearbit.com/${company.domain}`}
              alt=""
              className="h-4 w-4 shrink-0 rounded"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-tight truncate">
            {company.name}
          </p>
        </div>
        {company.tier && (
          <span className="ml-1 shrink-0 rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
            {TIER_LABELS[company.tier] ?? company.tier}
          </span>
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between">
        <span className="text-xs font-mono text-gray-400 dark:text-gray-500">
          PQS {company.pqs_total}
        </span>
        <span className="flex items-center gap-1 text-[11px] text-gray-400 dark:text-gray-500">
          <Clock className="h-3 w-3" />
          {formatTimeAgo(company.updated_at)}
        </span>
      </div>
    </Link>
  );
}
