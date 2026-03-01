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
} from "lucide-react";
import {
  getPendingDrafts,
  runAgent,
  getLinkedInTasks,
  completeLinkedInTask,
  getHotReplies,
  type OutreachDraft,
  type LinkedInTask,
} from "@/lib/api";
import { cn, TIER_LABELS } from "@/lib/utils";

type AgentName = "discovery" | "research" | "qualification" | "outreach" | "full";

interface AgentStatus {
  loading: boolean;
  result: "success" | "error" | null;
  message: string | null;
}

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

export default function ActionsPage() {
  const [followUps, setFollowUps] = useState<OutreachDraft[]>([]);
  const [linkedInTasks, setLinkedInTasks] = useState<LinkedInTask[]>([]);
  const [hotReplies, setHotReplies] = useState<OutreachDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [completingId, setCompletingId] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<Record<AgentName, AgentStatus>>(
    {
      full: { loading: false, result: null, message: null },
      discovery: { loading: false, result: null, message: null },
      research: { loading: false, result: null, message: null },
      qualification: { loading: false, result: null, message: null },
      outreach: { loading: false, result: null, message: null },
    }
  );

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

  const handleRunAgent = async (agent: AgentName) => {
    setAgentStatus((prev) => ({
      ...prev,
      [agent]: { loading: true, result: null, message: null },
    }));
    try {
      await runAgent(agent);
      setAgentStatus((prev) => ({
        ...prev,
        [agent]: {
          loading: false,
          result: "success",
          message: `${agent} agent completed successfully`,
        },
      }));
    } catch (err) {
      setAgentStatus((prev) => ({
        ...prev,
        [agent]: {
          loading: false,
          result: "error",
          message:
            err instanceof Error ? err.message : `${agent} agent failed`,
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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {AGENTS.map((agent) => {
            const status = agentStatus[agent.name];
            const Icon = agent.icon;
            return (
              <div
                key={agent.name}
                className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
              >
                <div className="flex items-center gap-2">
                  <Icon className="h-5 w-5 text-digitillis-accent" />
                  <h4 className="font-medium text-gray-900">{agent.label}</h4>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {agent.description}
                </p>
                <button
                  onClick={() => handleRunAgent(agent.name)}
                  disabled={status.loading}
                  className={cn(
                    "mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
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

                {/* Result Feedback */}
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
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
