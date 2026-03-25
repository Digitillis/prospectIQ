"use client";

/**
 * Daily Actions — Today's follow-ups, pending approvals, and hot prospects requiring attention
 *
 * Expected actions:
 * Process due follow-ups, review LinkedIn manual touches, prioritize hot signals, send approved drafts
 */


import { useEffect, useState, useCallback } from "react";
import {
  Send,
  Linkedin,
  MessageSquare,
  Play,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Clock,
  Zap,
  Search,
  FileSearch,
  Filter,
  Mail,
  ExternalLink,
  Reply,
} from "lucide-react";
import {
  getPendingDrafts,
  runAgent,
  getLinkedInTasks,
  completeLinkedInTask,
  getHotReplies,
  getCompanies,
  type OutreachDraft,
  type LinkedInTask,
} from "@/lib/api";
import { cn, TIER_LABELS } from "@/lib/utils";

type AgentName = "discovery" | "research" | "qualification" | "enrichment" | "outreach" | "reengagement" | "full";

interface AgentStatus {
  loading: boolean;
  result: "success" | "error" | null;
  message: string | null;
  details: AgentRunDetails | null;
}

interface AgentRunDetails {
  processed: number;
  skipped: number;
  errors: number;
  duration_seconds: number;
  total_cost_usd: number;
  summary?: string;
  batch_id?: string;
  error_details?: Array<{ company: string; status: string; message: string }>;
}

interface AgentFilters {
  discovery: { tiers: string[]; limit: number; max_pages: number; campaign: string };
  research: { tiers: string[]; limit: number; min_score: number; status: string };
  qualification: { tiers: string[]; limit: number };
  enrichment: { tiers: string[]; limit: number; include_phone: boolean };
  outreach: { tiers: string[]; limit: number; sequence_name: string; step: number };
  reengagement: { tiers: string[]; limit: number; cooldown_days: number };
  full: Record<string, unknown>;
}

const ALL_TIERS = Object.keys(TIER_LABELS);

const AGENTS: {
  name: AgentName;
  label: string;
  description: string;
  icon: typeof Search;
}[] = [
  {
    name: "discovery",
    label: "Run Discovery",
    description: "Find new manufacturing prospects",
    icon: Search,
  },
  {
    name: "research",
    label: "Run Research",
    description: "Deep-dive into discovered companies",
    icon: FileSearch,
  },
  {
    name: "qualification",
    label: "Run Qualification",
    description: "Score and qualify researched prospects",
    icon: Filter,
  },
  {
    name: "enrichment",
    label: "Run Enrichment",
    description: "Get emails & phones for qualified contacts (uses Apollo credits)",
    icon: Zap,
  },
  {
    name: "outreach",
    label: "Run Outreach",
    description: "Generate personalized outreach drafts",
    icon: Mail,
  },
  {
    name: "reengagement",
    label: "Run Re-engagement",
    description: "Re-queue stale prospects after cooldown period",
    icon: Reply,
  },
];

// ── Tier Pills ────────────────────────────────────────────────────────────────

function TierPills({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (tiers: string[]) => void;
}) {
  const toggle = (tier: string) => {
    onChange(
      selected.includes(tier)
        ? selected.filter((t) => t !== tier)
        : [...selected, tier]
    );
  };
  return (
    <div className="flex flex-wrap gap-1">
      {ALL_TIERS.map((tier) => (
        <button
          key={tier}
          type="button"
          onClick={() => toggle(tier)}
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
            selected.includes(tier)
              ? "border-gray-900 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-500 dark:text-gray-500 hover:border-gray-300"
          )}
        >
          {tier}
        </button>
      ))}
    </div>
  );
}

// ── Filter Panel ──────────────────────────────────────────────────────────────

interface FilterPanelProps {
  agentName: AgentName;
  filters: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}

function FilterPanel({ agentName, filters: f, onChange }: FilterPanelProps) {
  return (
    <div className="mt-2 space-y-2.5 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 p-3 text-xs">
      {/* Tiers */}
      <div>
        <label className="mb-1 block font-medium text-gray-600 dark:text-gray-500">
          Tiers{" "}
          <span className="font-normal text-gray-400 dark:text-gray-500">
            {(f.tiers as string[]).length === 0
              ? "(all)"
              : `(${(f.tiers as string[]).join(", ")})`}
          </span>
        </label>
        <TierPills
          selected={f.tiers as string[]}
          onChange={(tiers) => onChange("tiers", tiers)}
        />
      </div>

      {/* Limit */}
      <div className="flex items-center gap-2">
        <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Limit</label>
        <input
          type="number"
          min={1}
          max={500}
          value={f.limit as number}
          onChange={(e) => onChange("limit", parseInt(e.target.value) || 1)}
          className="w-20 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:border-gray-300 focus:outline-none"
        />
      </div>

      {/* Discovery-specific */}
      {agentName === "discovery" && (
        <>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Max Pages</label>
            <input
              type="number"
              min={1}
              max={10}
              value={f.max_pages as number}
              onChange={(e) => onChange("max_pages", parseInt(e.target.value) || 1)}
              className="w-20 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:border-gray-300 focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Campaign</label>
            <input
              type="text"
              value={f.campaign as string}
              onChange={(e) => onChange("campaign", e.target.value)}
              placeholder="e.g. q1_foodbev"
              className="flex-1 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:border-gray-300 focus:outline-none"
            />
          </div>
        </>
      )}

      {/* Research-specific */}
      {agentName === "research" && (
        <>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Min Score</label>
            <input
              type="number"
              min={0}
              max={100}
              value={f.min_score as number}
              onChange={(e) => onChange("min_score", parseInt(e.target.value) || 0)}
              className="w-20 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:border-gray-300 focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Status</label>
            <select
              value={f.status as string}
              onChange={(e) => onChange("status", e.target.value)}
              className="flex-1 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:border-gray-300 focus:outline-none"
            >
              <option value="">Any</option>
              <option value="discovered">discovered</option>
              <option value="researched">researched</option>
            </select>
          </div>
        </>
      )}

      {/* Enrichment-specific */}
      {agentName === "enrichment" && (
        <div className="flex items-center gap-2">
          <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Phone</label>
          <label className="flex items-center gap-1.5 text-gray-600 dark:text-gray-500 cursor-pointer">
            <input
              type="checkbox"
              checked={f.include_phone as boolean}
              onChange={(e) => onChange("include_phone", e.target.checked)}
              className="rounded border-gray-300 text-gray-900 dark:text-gray-100 focus:ring-gray-300 dark:focus:ring-gray-600"
            />
            <span>Include phone numbers (async via webhook)</span>
          </label>
        </div>
      )}

      {/* Re-engagement-specific */}
      {agentName === "reengagement" && (
        <div className="flex items-center gap-2">
          <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Cooldown</label>
          <input
            type="number"
            min={30}
            max={365}
            value={f.cooldown_days as number}
            onChange={(e) => onChange("cooldown_days", parseInt(e.target.value) || 90)}
            className="w-20 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:border-gray-300 focus:outline-none"
          />
          <span className="text-gray-400 dark:text-gray-500">days</span>
        </div>
      )}

      {/* Outreach-specific */}
      {agentName === "outreach" && (
        <>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Sequence</label>
            <input
              type="text"
              value={f.sequence_name as string}
              onChange={(e) => onChange("sequence_name", e.target.value)}
              placeholder="e.g. initial_outreach"
              className="flex-1 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 focus:border-gray-300 focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600 dark:text-gray-500">Step</label>
            <input
              type="number"
              min={1}
              value={f.step as number}
              onChange={(e) => onChange("step", parseInt(e.target.value) || 1)}
              className="w-20 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:border-gray-300 focus:outline-none"
            />
          </div>
        </>
      )}
    </div>
  );
}

// ── Run Details ───────────────────────────────────────────────────────────────

function RunDetails({ details }: { details: AgentRunDetails }) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 rounded-md bg-gray-50 dark:bg-gray-800 p-2.5 text-[10px] text-gray-600 dark:text-gray-500">
      <span>
        <span className="font-semibold text-gray-800">{details.processed}</span> processed
      </span>
      <span>
        <span className="font-semibold text-gray-800">{details.skipped}</span> skipped
      </span>
      <span>
        <span className="font-semibold text-gray-800">{details.errors}</span> errors
      </span>
      <span>
        <span className="font-semibold text-gray-800">
          {details.duration_seconds?.toFixed(1)}s
        </span>{" "}
        duration
      </span>
      {details.total_cost_usd != null && (
        <span className="col-span-2">
          <span className="font-semibold text-gray-800">
            ${details.total_cost_usd.toFixed(4)}
          </span>{" "}
          cost
        </span>
      )}
      {details.summary && (
        <p className="col-span-2 mt-0.5 leading-relaxed text-gray-500 dark:text-gray-500">{details.summary}</p>
      )}
      {details.errors > 0 && details.error_details && details.error_details.length > 0 && (
        <div className="col-span-2 mt-1 space-y-0.5">
          {details.error_details.map((d, i) => (
            <p key={i} className="text-red-500 truncate" title={d.message}>
              {d.company}: {d.message}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ActionsPage() {
  const [followUps, setFollowUps] = useState<OutreachDraft[]>([]);
  const [linkedInTasks, setLinkedInTasks] = useState<LinkedInTask[]>([]);
  const [hotReplies, setHotReplies] = useState<OutreachDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [completingId, setCompletingId] = useState<string | null>(null);

  const [agentStatus, setAgentStatus] = useState<Record<AgentName, AgentStatus>>({
    full: { loading: false, result: null, message: null, details: null },
    discovery: { loading: false, result: null, message: null, details: null },
    research: { loading: false, result: null, message: null, details: null },
    qualification: { loading: false, result: null, message: null, details: null },
    enrichment: { loading: false, result: null, message: null, details: null },
    outreach: { loading: false, result: null, message: null, details: null },
    reengagement: { loading: false, result: null, message: null, details: null },
  });

  const [agentFilters, setAgentFilters] = useState<AgentFilters>({
    discovery: { tiers: [], limit: 50, max_pages: 3, campaign: "" },
    research: { tiers: [], limit: 10, min_score: 0, status: "" },
    qualification: { tiers: [], limit: 100 },
    enrichment: { tiers: [], limit: 25, include_phone: false },
    outreach: { tiers: [], limit: 20, sequence_name: "initial_outreach", step: 1 },
    reengagement: { tiers: [], limit: 50, cooldown_days: 90 },
    full: {},
  });

  // Feature 3: real-time progress messages while an agent runs
  const [agentProgress, setAgentProgress] = useState<Record<AgentName, string>>({
    discovery: "",
    research: "",
    qualification: "",
    enrichment: "",
    outreach: "",
    reengagement: "",
    full: "",
  });

  // Feature 7: estimated company counts per agent
  const [estimatedCounts, setEstimatedCounts] = useState<
    Record<AgentName, number | null>
  >({
    discovery: null,
    research: null,
    qualification: null,
    enrichment: null,
    outreach: null,
    reengagement: null,
    full: null,
  });

  const [countLoading, setCountLoading] = useState<Record<AgentName, boolean>>({
    discovery: false,
    research: false,
    qualification: false,
    enrichment: false,
    outreach: false,
    reengagement: false,
    full: false,
  });

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [draftsRes, linkedInRes, hotRes] = await Promise.allSettled([
        getPendingDrafts(),
        getLinkedInTasks(),
        getHotReplies(),
      ]);

      if (draftsRes.status === "fulfilled") {
        const approved = draftsRes.value.data.filter(
          (d) => d.approval_status === "approved"
        );
        setFollowUps(approved);
      }
      if (linkedInRes.status === "fulfilled") {
        setLinkedInTasks(linkedInRes.value.data);
      }
      if (hotRes.status === "fulfilled") {
        setHotReplies(hotRes.value.data);
      }
    } catch {
      // Silently handle — sections will show empty state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCompleteLinkedIn = async (sequenceId: string) => {
    setCompletingId(sequenceId);
    try {
      await completeLinkedInTask(sequenceId);
      setLinkedInTasks((prev) => prev.filter((t) => t.id !== sequenceId));
    } catch {
      // silent
    } finally {
      setCompletingId(null);
    }
  };

  const updateFilter = (
    agent: Exclude<AgentName, "full">,
    key: string,
    value: unknown
  ) => {
    setAgentFilters((prev) => ({
      ...prev,
      [agent]: { ...prev[agent], [key]: value },
    }));
  };

  // Per-agent cost estimates
  const AGENT_COST_PER_COMPANY: Record<AgentName, number> = {
    discovery: 0,
    research: 0.05,
    qualification: 0,
    enrichment: 0.01,
    outreach: 0.02,
    reengagement: 0,
    full: 0,
  };

  // Feature 7: fetch estimated count for the given agent based on current filters
  const estimateBatchSize = async (agent: AgentName) => {
    if (agent === "full") return;
    setCountLoading((prev) => ({ ...prev, [agent]: true }));
    try {
      const filters = agentFilters[agent] as Record<string, unknown>;

      // Discovery searches Apollo for NEW prospects — estimate is based on
      // filter settings, not existing DB records
      if (agent === "discovery") {
        const pages = (filters.max_pages as number) || 3;
        const tiersSelected = (filters.tiers as string[]).length || 8;
        const estimate = pages * 100 * tiersSelected; // ~100 results per page per tier
        setEstimatedCounts((prev) => ({ ...prev, discovery: estimate }));
        return;
      }

      // Re-engagement looks for completed sequences past cooldown — different query
      if (agent === "reengagement") {
        const res = await getCompanies({ status: "contacted", limit: "1", offset: "0" });
        setEstimatedCounts((prev) => ({ ...prev, reengagement: res.count ?? 0 }));
        return;
      }

      // All other agents query existing DB records by required status
      const params: Record<string, string> = { limit: "1", offset: "0" };

      if ((filters.tiers as string[]).length > 0)
        params.tier = (filters.tiers as string[])[0];

      const statusMap: Record<string, string> = {
        research: "discovered",
        qualification: "researched",
        enrichment: "qualified",
        outreach: "qualified",
      };
      const requiredStatus = statusMap[agent];
      if (requiredStatus) params.status = requiredStatus;

      const res = await getCompanies(params);
      setEstimatedCounts((prev) => ({
        ...prev,
        [agent]: res.count ?? 0,
      }));
    } catch {
      // leave count as null on failure
    } finally {
      setCountLoading((prev) => ({ ...prev, [agent]: false }));
    }
  };

  // Feature 3: progress messages timeline
  const PROGRESS_MESSAGES: { delay: number; msg: string }[] = [
    { delay: 0, msg: "Starting agent..." },
    { delay: 2000, msg: "Processing companies..." },
    { delay: 5000, msg: "Still working — large batches may take a few minutes..." },
    { delay: 15000, msg: "Almost there..." },
  ];

  const handleRunAgent = async (agent: AgentName) => {
    setAgentStatus((prev) => ({
      ...prev,
      [agent]: { loading: true, result: null, message: null, details: null },
    }));

    // Feature 3: schedule progress message updates
    const timers: ReturnType<typeof setTimeout>[] = PROGRESS_MESSAGES.map(
      ({ delay, msg }) =>
        setTimeout(() => {
          setAgentProgress((prev) => ({ ...prev, [agent]: msg }));
        }, delay)
    );

    const clearProgress = () => {
      timers.forEach(clearTimeout);
      setAgentProgress((prev) => ({ ...prev, [agent]: "" }));
    };

    try {
      const body: Record<string, unknown> = {};

      if (agent !== "full") {
        const f = agentFilters[agent] as Record<string, unknown>;

        if ((f.tiers as string[]).length > 0) body.tiers = f.tiers;
        if (f.limit) body.limit = f.limit;

        if (agent === "discovery") {
          if (f.max_pages) body.max_pages = f.max_pages;
          if (f.campaign) body.campaign = f.campaign;
        }
        if (agent === "research") {
          if (f.min_score) body.min_score = f.min_score;
          if (f.status) body.status = f.status;
        }
        if (agent === "outreach") {
          if (f.sequence_name) body.sequence_name = f.sequence_name;
          if (f.step) body.step = f.step;
        }
      }

      const res = (await runAgent(agent, body)) as {
        data?: {
          success?: boolean;
          processed?: number;
          skipped?: number;
          errors?: number;
          batch_id?: string;
          duration_seconds?: number;
          total_cost_usd?: number;
          summary?: string;
        };
      };

      const d = res?.data;
      const details: AgentRunDetails | null = d
        ? {
            processed: d.processed ?? 0,
            skipped: d.skipped ?? 0,
            errors: d.errors ?? 0,
            duration_seconds: d.duration_seconds ?? 0,
            total_cost_usd: d.total_cost_usd ?? 0,
            summary: d.summary,
            batch_id: d.batch_id,
            error_details: (d as any).details?.filter((x: any) => x.status === 'error')?.slice(0, 3),
          }
        : null;

      clearProgress();
      setAgentStatus((prev) => ({
        ...prev,
        [agent]: {
          loading: false,
          result: "success",
          message: details?.summary ?? `${agent} agent completed successfully`,
          details,
        },
      }));
    } catch (err) {
      clearProgress();
      setAgentStatus((prev) => ({
        ...prev,
        [agent]: {
          loading: false,
          result: "error",
          message:
            err instanceof Error ? err.message : `${agent} agent failed`,
          details: null,
        },
      }));
    }
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Daily Actions</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">
          Today&apos;s tasks and pipeline operations
        </p>
      </div>

      {/* Section 1: Follow-ups Due */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <Send className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
            Follow-ups Due
          </h3>
          <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
            {loading ? "..." : followUps.length}
          </span>
        </div>

        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : followUps.length === 0 ? (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center text-sm text-gray-500 dark:text-gray-500">
            No follow-ups due today. Approved drafts will appear here.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {followUps.map((draft) => (
              <div
                key={draft.id}
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-gray-900 dark:text-gray-100">
                      {draft.companies?.name ?? "Unknown"}
                    </p>
                    <p className="mt-0.5 truncate text-sm text-gray-500 dark:text-gray-500">
                      {draft.contacts?.full_name ?? "Unknown Contact"}
                    </p>
                  </div>
                  {draft.companies?.tier && (
                    <span className="ml-2 shrink-0 rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-600 dark:text-gray-500">
                      {TIER_LABELS[draft.companies.tier] ?? draft.companies.tier}
                    </span>
                  )}
                </div>
                <p className="mt-2 truncate text-sm font-medium text-gray-700 dark:text-gray-300">
                  {draft.subject}
                </p>
                <div className="mt-3 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                  <Clock className="h-3.5 w-3.5" />
                  <span>Ready to send</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Section 2: LinkedIn Touches */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <Linkedin className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
            LinkedIn Touches
          </h3>
          <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
            {loading ? "..." : linkedInTasks.length}
          </span>
        </div>

        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : linkedInTasks.length === 0 ? (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center text-sm text-gray-500 dark:text-gray-500">
            No LinkedIn actions due. They appear here when a sequence step requires a LinkedIn touch.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {linkedInTasks.map((task) => (
              <div
                key={task.id}
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-gray-900 dark:text-gray-100">
                      {task.companies?.name ?? "Unknown"}
                    </p>
                    <p className="truncate text-xs text-gray-500 dark:text-gray-500">
                      {task.contacts?.full_name ?? "Unknown"} &mdash;{" "}
                      {task.contacts?.title ?? ""}
                    </p>
                  </div>
                  {task.companies?.tier && (
                    <span className="shrink-0 rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-600 dark:text-gray-500">
                      {TIER_LABELS[task.companies.tier] ?? task.companies.tier}
                    </span>
                  )}
                </div>

                <p className="mb-3 text-xs text-gray-500 dark:text-gray-500">
                  Step {task.current_step + 1}/{task.total_steps} &mdash;{" "}
                  {task.next_action_type === "send_linkedin"
                    ? task.current_step <= 1
                      ? "Connection request"
                      : "Direct message"
                    : task.next_action_type}
                </p>

                <div className="flex items-center gap-2">
                  {task.contacts?.linkedin_url && (
                    <a
                      href={task.contacts.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-gray-700 px-2.5 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                    >
                      <ExternalLink className="h-3 w-3" />
                      Open LinkedIn
                    </a>
                  )}
                  <button
                    onClick={() => handleCompleteLinkedIn(task.id)}
                    disabled={completingId === task.id}
                    className="inline-flex items-center gap-1 rounded-md bg-gray-900 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                  >
                    {completingId === task.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-3 w-3" />
                    )}
                    Mark Done
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Section 3: Hot Replies */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <MessageSquare className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">Hot Replies</h3>
          <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
            {loading ? "..." : hotReplies.length}
          </span>
        </div>

        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : hotReplies.length === 0 ? (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center text-sm text-gray-500 dark:text-gray-500">
            No hot replies pending. Positive and question replies will surface here for your response.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hotReplies.map((draft) => (
              <a
                key={draft.id}
                href="/approvals"
                className="block rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-gray-900 dark:text-gray-100">
                      {draft.companies?.name ?? "Unknown"}
                    </p>
                    <p className="truncate text-xs text-gray-500 dark:text-gray-500">
                      {draft.contacts?.full_name ?? "Unknown"}
                    </p>
                  </div>
                  <span className="shrink-0 rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-500">
                    Reply
                  </span>
                </div>
                <p className="mb-2 truncate text-xs font-medium text-gray-700 dark:text-gray-300">
                  {draft.subject}
                </p>
                <div className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-500">
                  <Reply className="h-3.5 w-3.5" />
                  <span>Response draft ready — review in Approvals</span>
                </div>
              </a>
            ))}
          </div>
        )}
      </section>

      {/* Section 4: Pipeline Actions */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <Zap className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          <h3 className="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-500">
            Pipeline Actions
          </h3>
        </div>

        {/* Run Full Pipeline */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-gray-400 dark:text-gray-500" />
                <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Run Full Pipeline</h4>
              </div>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">
                Discovery → Research → Qualification → Outreach drafts. Outreach still requires your approval before sending.
              </p>
              {agentStatus.full.result && (
                <div
                  className="mt-3 flex items-center gap-1.5 rounded-md bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs text-gray-700 dark:text-gray-300"
                >
                  {agentStatus.full.result === "success" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  ) : (
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                  )}
                  <span>{agentStatus.full.message}</span>
                </div>
              )}
              {agentStatus.full.result === "success" && agentStatus.full.details && (
                <RunDetails details={agentStatus.full.details} />
              )}
            </div>
            <button
              onClick={() => handleRunAgent("full")}
              disabled={agentStatus.full.loading}
              className={cn(
                "inline-flex shrink-0 items-center justify-center gap-2 rounded-md px-4 py-2 text-xs font-medium transition-colors",
                agentStatus.full.loading
                  ? "cursor-not-allowed bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500"
                  : "bg-gray-900 text-white hover:bg-gray-800"
              )}
            >
              {agentStatus.full.loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Running pipeline...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Run Full Pipeline
                </>
              )}
            </button>
          </div>
        </div>

        <p className="text-xs text-gray-400 dark:text-gray-500">Or run individual stages:</p>

        {/* Individual agent cards — 3-column, 2-row grid */}
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {AGENTS.map((agent) => {
            const status = agentStatus[agent.name];
            const Icon = agent.icon;
            const filters = agentFilters[agent.name] as Record<string, unknown>;
            const count = estimatedCounts[agent.name];
            const costPerCompany = AGENT_COST_PER_COMPANY[agent.name];
            const progressMsg = agentProgress[agent.name];
            const isCountLoading = countLoading[agent.name];

            return (
              <div
                key={agent.name}
                className="flex flex-col rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden"
              >
                {/* Header — fixed height */}
                <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
                  <div className="flex items-center gap-2">
                    <Icon className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                    <h4 className="text-base font-semibold text-gray-900 dark:text-gray-100">{agent.label}</h4>
                  </div>
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-500">{agent.description}</p>
                </div>

                {/* Body — flex-col so Run button pins to bottom */}
                <div className="flex flex-1 flex-col px-5 py-4">
                  {/* Filter panel — fixed minimum height so all cards in the same row align */}
                  <div className="min-h-[220px]">
                    <FilterPanel
                      agentName={agent.name}
                      filters={filters}
                      onChange={(key, value) => {
                        updateFilter(
                          agent.name as Exclude<AgentName, "full">,
                          key,
                          value
                        );
                        // Invalidate count when filters change
                        setEstimatedCounts((prev) => ({
                          ...prev,
                          [agent.name]: null,
                        }));
                      }}
                    />
                  </div>

                  {/* Estimate + Run button — pinned to bottom via mt-auto */}
                  <div className="mt-auto pt-4 space-y-3">
                    {/* Feature 7: cost estimator */}
                    <div className="rounded-md border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800 px-2.5 py-2 text-[11px] text-gray-500 dark:text-gray-500">
                      {isCountLoading ? (
                        <span className="flex items-center gap-1">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Estimating...
                        </span>
                      ) : count !== null ? (
                        <span>
                          {agent.name === "discovery" ? (
                            <>Will search Apollo for ~{count} contacts across {(agentFilters.discovery.tiers.length || 8)} tier(s)</>
                          ) : agent.name === "reengagement" ? (
                            <>~{count} contacted companies eligible for re-engagement check</>
                          ) : (
                            <>~{count} companies ready to process</>
                          )}
                          {costPerCompany > 0 && count > 0 && (
                            <span className="ml-1 font-medium text-gray-700 dark:text-gray-300">
                              · Est. cost: ${(count * costPerCompany).toFixed(2)}
                            </span>
                          )}
                          {costPerCompany === 0 && (
                            <span className="ml-1 text-gray-500 dark:text-gray-500">· Free</span>
                          )}
                          <button
                            type="button"
                            onClick={() => estimateBatchSize(agent.name)}
                            className="ml-2 underline hover:text-gray-900 dark:text-gray-100"
                          >
                            Refresh
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => estimateBatchSize(agent.name)}
                          className="underline hover:text-gray-900 dark:text-gray-100"
                        >
                          Estimate batch size
                        </button>
                      )}
                    </div>

                    {/* Run button */}
                    <button
                      onClick={() => handleRunAgent(agent.name)}
                      disabled={status.loading}
                      className={cn(
                        "inline-flex w-full items-center justify-center gap-2 rounded-md px-4 py-2 text-xs font-medium transition-colors",
                        status.loading
                          ? "cursor-not-allowed bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500"
                          : "bg-gray-900 text-white hover:bg-gray-800"
                      )}
                    >
                      {status.loading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Running...
                        </>
                      ) : (
                        <>
                          <Play className="h-4 w-4" />
                          Run
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Results area — outside the fixed-height body, shown after run */}
                {(status.loading && progressMsg) || status.result ? (
                  <div className="px-5 py-3 border-t border-gray-100 dark:border-gray-800 space-y-2">
                    {/* Feature 3: progress message while loading */}
                    {status.loading && progressMsg && (
                      <p className="text-xs text-gray-500 dark:text-gray-500 animate-pulse">
                        {progressMsg}
                      </p>
                    )}

                    {/* Result feedback */}
                    {status.result && (
                      <div
                        className={cn(
                          "flex items-center gap-1.5 rounded-md px-3 py-2 text-xs",
                          "bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300"
                        )}
                      >
                        {status.result === "success" ? (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                        ) : (
                          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        )}
                        <span className="truncate">{status.message}</span>
                      </div>
                    )}

                    {/* Run details breakdown */}
                    {status.result === "success" && status.details && (
                      <RunDetails details={status.details} />
                    )}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
