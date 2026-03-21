"use client";

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
  ChevronDown,
  ChevronUp,
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

type AgentName = "discovery" | "research" | "qualification" | "outreach" | "full";

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
}

interface AgentFilters {
  discovery: { tiers: string[]; limit: number; max_pages: number; campaign: string };
  research: { tiers: string[]; limit: number; min_score: number; status: string };
  qualification: { tiers: string[]; limit: number };
  outreach: { tiers: string[]; limit: number; sequence_name: string; step: number };
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
    name: "outreach",
    label: "Run Outreach",
    description: "Generate personalized outreach drafts",
    icon: Mail,
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
              ? "border-digitillis-accent bg-blue-50 text-digitillis-accent"
              : "border-gray-200 bg-white text-gray-500 hover:border-gray-300"
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
    <div className="mt-2 space-y-2.5 rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs">
      {/* Tiers */}
      <div>
        <label className="mb-1 block font-medium text-gray-600">
          Tiers{" "}
          <span className="font-normal text-gray-400">
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
        <label className="w-16 shrink-0 font-medium text-gray-600">Limit</label>
        <input
          type="number"
          min={1}
          max={500}
          value={f.limit as number}
          onChange={(e) => onChange("limit", parseInt(e.target.value) || 1)}
          className="w-20 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-digitillis-accent focus:outline-none"
        />
      </div>

      {/* Discovery-specific */}
      {agentName === "discovery" && (
        <>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600">Max Pages</label>
            <input
              type="number"
              min={1}
              max={10}
              value={f.max_pages as number}
              onChange={(e) => onChange("max_pages", parseInt(e.target.value) || 1)}
              className="w-20 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-digitillis-accent focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600">Campaign</label>
            <input
              type="text"
              value={f.campaign as string}
              onChange={(e) => onChange("campaign", e.target.value)}
              placeholder="e.g. q1_foodbev"
              className="flex-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 placeholder-gray-400 focus:border-digitillis-accent focus:outline-none"
            />
          </div>
        </>
      )}

      {/* Research-specific */}
      {agentName === "research" && (
        <>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600">Min Score</label>
            <input
              type="number"
              min={0}
              max={100}
              value={f.min_score as number}
              onChange={(e) => onChange("min_score", parseInt(e.target.value) || 0)}
              className="w-20 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-digitillis-accent focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600">Status</label>
            <select
              value={f.status as string}
              onChange={(e) => onChange("status", e.target.value)}
              className="flex-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-digitillis-accent focus:outline-none"
            >
              <option value="">Any</option>
              <option value="discovered">discovered</option>
              <option value="researched">researched</option>
            </select>
          </div>
        </>
      )}

      {/* Outreach-specific */}
      {agentName === "outreach" && (
        <>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600">Sequence</label>
            <input
              type="text"
              value={f.sequence_name as string}
              onChange={(e) => onChange("sequence_name", e.target.value)}
              placeholder="e.g. initial_outreach"
              className="flex-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 placeholder-gray-400 focus:border-digitillis-accent focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="w-16 shrink-0 font-medium text-gray-600">Step</label>
            <input
              type="number"
              min={1}
              value={f.step as number}
              onChange={(e) => onChange("step", parseInt(e.target.value) || 1)}
              className="w-20 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-digitillis-accent focus:outline-none"
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
    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 rounded-md bg-green-50 p-2.5 text-[10px] text-gray-600">
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
        <p className="col-span-2 mt-0.5 leading-relaxed text-gray-500">{details.summary}</p>
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
    outreach: { loading: false, result: null, message: null, details: null },
  });

  const [agentFilters, setAgentFilters] = useState<AgentFilters>({
    discovery: { tiers: [], limit: 50, max_pages: 3, campaign: "" },
    research: { tiers: [], limit: 50, min_score: 0, status: "" },
    qualification: { tiers: [], limit: 100 },
    outreach: { tiers: [], limit: 20, sequence_name: "initial_outreach", step: 1 },
    full: {},
  });

  const [filtersOpen, setFiltersOpen] = useState<Record<AgentName, boolean>>({
    discovery: false,
    research: false,
    qualification: false,
    outreach: false,
    full: false,
  });

  // Feature 3: real-time progress messages while an agent runs
  const [agentProgress, setAgentProgress] = useState<Record<AgentName, string>>({
    discovery: "",
    research: "",
    qualification: "",
    outreach: "",
    full: "",
  });

  // Feature 7: estimated company counts per agent
  const [estimatedCounts, setEstimatedCounts] = useState<
    Record<AgentName, number | null>
  >({
    discovery: null,
    research: null,
    qualification: null,
    outreach: null,
    full: null,
  });

  const [countLoading, setCountLoading] = useState<Record<AgentName, boolean>>({
    discovery: false,
    research: false,
    qualification: false,
    outreach: false,
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
    outreach: 0.02,
    full: 0,
  };

  // Feature 7: fetch estimated count for the given agent based on current filters
  const estimateBatchSize = async (agent: AgentName) => {
    if (agent === "full") return;
    setCountLoading((prev) => ({ ...prev, [agent]: true }));
    try {
      const filters = agentFilters[agent] as Record<string, unknown>;
      const params: Record<string, string> = { limit: "1", offset: "0" };

      if ((filters.tiers as string[]).length > 0)
        params.tier = (filters.tiers as string[])[0];

      const statusMap: Record<Exclude<AgentName, "full">, string> = {
        discovery: "",
        research: "discovered",
        qualification: "researched",
        outreach: "qualified",
      };
      const requiredStatus = statusMap[agent as Exclude<AgentName, "full">];
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
        <h2 className="text-2xl font-bold text-gray-900">Daily Actions</h2>
        <p className="mt-1 text-sm text-gray-500">
          Today&apos;s tasks and pipeline operations
        </p>
      </div>

      {/* Section 1: Follow-ups Due */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <Send className="h-5 w-5 text-digitillis-accent" />
          <h3 className="text-lg font-semibold text-gray-900">
            Follow-ups Due
          </h3>
          <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-digitillis-accent">
            {loading ? "..." : followUps.length}
          </span>
        </div>

        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-xl border border-gray-200 bg-white">
            <Loader2 className="h-6 w-6 animate-spin text-digitillis-accent" />
          </div>
        ) : followUps.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
            No follow-ups due today. Approved drafts will appear here.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {followUps.map((draft) => (
              <div
                key={draft.id}
                className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-gray-900">
                      {draft.companies?.name ?? "Unknown"}
                    </p>
                    <p className="mt-0.5 truncate text-sm text-gray-500">
                      {draft.contacts?.full_name ?? "Unknown Contact"}
                    </p>
                  </div>
                  {draft.companies?.tier && (
                    <span className="ml-2 shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {TIER_LABELS[draft.companies.tier] ?? draft.companies.tier}
                    </span>
                  )}
                </div>
                <p className="mt-2 truncate text-sm font-medium text-gray-700">
                  {draft.subject}
                </p>
                <div className="mt-3 flex items-center gap-2 text-xs text-gray-400">
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
          <Linkedin className="h-5 w-5 text-digitillis-accent" />
          <h3 className="text-lg font-semibold text-gray-900">
            LinkedIn Touches
          </h3>
          <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-digitillis-accent">
            {loading ? "..." : linkedInTasks.length}
          </span>
        </div>

        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-xl border border-gray-200 bg-white">
            <Loader2 className="h-6 w-6 animate-spin text-digitillis-accent" />
          </div>
        ) : linkedInTasks.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
            No LinkedIn actions due. They appear here when a sequence step requires a LinkedIn touch.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {linkedInTasks.map((task) => (
              <div
                key={task.id}
                className="rounded-xl border border-blue-100 bg-white p-4 shadow-sm"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-gray-900">
                      {task.companies?.name ?? "Unknown"}
                    </p>
                    <p className="truncate text-xs text-gray-500">
                      {task.contacts?.full_name ?? "Unknown"} &mdash;{" "}
                      {task.contacts?.title ?? ""}
                    </p>
                  </div>
                  {task.companies?.tier && (
                    <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {TIER_LABELS[task.companies.tier] ?? task.companies.tier}
                    </span>
                  )}
                </div>

                <p className="mb-3 text-xs text-gray-500">
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
                      className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-2.5 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50"
                    >
                      <ExternalLink className="h-3 w-3" />
                      Open LinkedIn
                    </a>
                  )}
                  <button
                    onClick={() => handleCompleteLinkedIn(task.id)}
                    disabled={completingId === task.id}
                    className="inline-flex items-center gap-1 rounded-md bg-digitillis-accent px-2.5 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
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
          <MessageSquare className="h-5 w-5 text-digitillis-warning" />
          <h3 className="text-lg font-semibold text-gray-900">Hot Replies</h3>
          <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-digitillis-warning">
            {loading ? "..." : hotReplies.length}
          </span>
        </div>

        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-xl border border-gray-200 bg-white">
            <Loader2 className="h-6 w-6 animate-spin text-digitillis-warning" />
          </div>
        ) : hotReplies.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
            No hot replies pending. Positive and question replies will surface here for your response.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hotReplies.map((draft) => (
              <a
                key={draft.id}
                href="/approvals"
                className="block rounded-xl border border-amber-100 bg-white p-4 shadow-sm transition-shadow hover:shadow-md"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-gray-900">
                      {draft.companies?.name ?? "Unknown"}
                    </p>
                    <p className="truncate text-xs text-gray-500">
                      {draft.contacts?.full_name ?? "Unknown"}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-digitillis-warning">
                    Reply
                  </span>
                </div>
                <p className="mb-2 truncate text-xs font-medium text-gray-700">
                  {draft.subject}
                </p>
                <div className="flex items-center gap-1 text-xs text-amber-600">
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
          <Zap className="h-5 w-5 text-digitillis-accent" />
          <h3 className="text-lg font-semibold text-gray-900">
            Pipeline Actions
          </h3>
        </div>

        {/* Run Full Pipeline */}
        <div className="rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 to-slate-50 p-5 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Zap className="h-5 w-5 text-digitillis-accent" />
                <h4 className="font-semibold text-gray-900">Run Full Pipeline</h4>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Discovery → Research → Qualification → Outreach drafts. Outreach still requires your approval before sending.
              </p>
              {agentStatus.full.result && (
                <div
                  className={cn(
                    "mt-3 flex items-center gap-1.5 rounded-md px-3 py-2 text-xs",
                    agentStatus.full.result === "success"
                      ? "bg-green-50 text-digitillis-success"
                      : "bg-red-50 text-digitillis-danger"
                  )}
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
                "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg px-6 py-3 text-sm font-semibold transition-colors",
                agentStatus.full.loading
                  ? "cursor-not-allowed bg-gray-100 text-gray-400"
                  : "bg-digitillis-accent text-white hover:opacity-90"
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

        <p className="text-xs text-gray-400">Or run individual stages:</p>

        {/* Individual agent cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {AGENTS.map((agent) => {
            const status = agentStatus[agent.name];
            const Icon = agent.icon;
            const isOpen = filtersOpen[agent.name];
            const filters = agentFilters[agent.name] as Record<string, unknown>;
            const count = estimatedCounts[agent.name];
            const costPerCompany = AGENT_COST_PER_COMPANY[agent.name];
            const progressMsg = agentProgress[agent.name];
            const isCountLoading = countLoading[agent.name];

            return (
              <div
                key={agent.name}
                className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
              >
                {/* Header */}
                <div className="flex items-center gap-2">
                  <Icon className="h-5 w-5 text-digitillis-accent" />
                  <h4 className="font-medium text-gray-900">{agent.label}</h4>
                </div>
                <p className="mt-1 text-xs text-gray-500">{agent.description}</p>

                {/* Filters toggle */}
                <button
                  type="button"
                  onClick={() => {
                    const willOpen = !filtersOpen[agent.name];
                    setFiltersOpen((prev) => ({
                      ...prev,
                      [agent.name]: willOpen,
                    }));
                    // Auto-fetch estimate when panel opens
                    if (willOpen && count === null) {
                      estimateBatchSize(agent.name);
                    }
                  }}
                  className="mt-2 flex items-center gap-0.5 text-[11px] font-medium text-digitillis-accent hover:opacity-75"
                >
                  {isOpen ? (
                    <>
                      Filters <ChevronUp className="h-3 w-3" />
                    </>
                  ) : (
                    <>
                      Filters <ChevronDown className="h-3 w-3" />
                    </>
                  )}
                </button>

                {/* Collapsible filter panel */}
                {isOpen && (
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
                )}

                {/* Feature 7: cost estimator */}
                <div className="mt-3 rounded-md border border-gray-100 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-500">
                  {isCountLoading ? (
                    <span className="flex items-center gap-1">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Estimating...
                    </span>
                  ) : count !== null ? (
                    <span>
                      ~{count} companies will be processed
                      {costPerCompany > 0 && count > 0 && (
                        <span className="ml-1 font-medium text-gray-700">
                          · Est. cost: ${(count * costPerCompany).toFixed(2)}
                        </span>
                      )}
                      {costPerCompany === 0 && (
                        <span className="ml-1 text-green-600">· Free</span>
                      )}
                      <button
                        type="button"
                        onClick={() => estimateBatchSize(agent.name)}
                        className="ml-2 underline hover:text-digitillis-accent"
                      >
                        Refresh
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => estimateBatchSize(agent.name)}
                      className="underline hover:text-digitillis-accent"
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
                    "mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
                    status.loading
                      ? "cursor-not-allowed bg-gray-100 text-gray-400"
                      : "bg-digitillis-accent text-white hover:opacity-90"
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

                {/* Feature 3: progress message while loading */}
                {status.loading && progressMsg && (
                  <p className="mt-2 text-xs text-gray-500 animate-pulse">
                    {progressMsg}
                  </p>
                )}

                {/* Result feedback */}
                {status.result && (
                  <div
                    className={cn(
                      "mt-3 flex items-center gap-1.5 rounded-md px-3 py-2 text-xs",
                      status.result === "success"
                        ? "bg-green-50 text-digitillis-success"
                        : "bg-red-50 text-digitillis-danger"
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
            );
          })}
        </div>
      </section>
    </div>
  );
}
