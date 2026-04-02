"use client";

/**
 * Intelligence — Personalization Leaderboard, Trigger Feed, Hook Library,
 * Pipeline analytics, sequence performance, cost breakdown, A/B tests.
 *
 * Default tab: Leaderboard (personalization readiness ranking)
 */

import { useEffect, useState, useCallback } from "react";
import {
  BarChart3,
  DollarSign,
  FlaskConical,
  GitBranch,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Loader2,
  RefreshCw,
  ArrowRight,
  ChevronRight,
  Zap,
  Clock,
  Target,
  BookOpen,
  Play,
  PlayCircle,
  Filter,
  Copy,
  Check,
  Plus,
} from "lucide-react";
import {
  getIntelligenceFunnel,
  getIntelligenceVelocity,
  getIntelligenceCosts,
  getIntelligenceWeekly,
  getSequencePerformance,
  getPersonalizationLeaderboard,
  runPersonalization,
  runPersonalizationBatch,
  addManualTrigger,
  SequencePerformance,
  PersonalizationLeaderboardItem,
  TriggerEvent,
  PersonalizationHook,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { ReadinessScore } from "@/components/personalization/ReadinessScore";
import { TriggerCard } from "@/components/personalization/TriggerCard";
import { PersonalizationDetailPanel } from "@/components/personalization/PersonalizationDetailPanel";

// ─── Types ────────────────────────────────────────────────────────────────────

interface FunnelStage {
  status: string;
  count: number;
  label: string;
}

interface VelocityData {
  enriched_to_sequenced_days: number;
  sequenced_to_replied_days: number;
  overall_discovery_to_reply_days: number;
  contacts_with_reply: number;
}

interface CostData {
  total_usd: number;
  research_usd: number;
  drafts_usd: number;
  by_agent: Record<string, number>;
  monthly_cap_usd: number;
  pct_of_cap: number;
}

interface WeeklyDataPoint {
  week_start: string;
  contacts_added: number;
  sequenced: number;
  replied: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  researched: "Researched",
  qualified: "Qualified",
  in_sequence: "In Sequence",
  replied: "Replied",
  meeting_booked: "Meeting",
  won: "Won",
  lost: "Lost",
  no_response: "No Response",
};

// ─── Tab Bar ──────────────────────────────────────────────────────────────────

function TabBar({
  active,
  onChange,
}: {
  active: string;
  onChange: (t: string) => void;
}) {
  const tabs = [
    { id: "leaderboard", label: "Leaderboard", icon: <Target className="w-3.5 h-3.5" /> },
    { id: "triggers", label: "Trigger Feed", icon: <Zap className="w-3.5 h-3.5" /> },
    { id: "hooks", label: "Hook Library", icon: <BookOpen className="w-3.5 h-3.5" /> },
    { id: "pipeline", label: "Pipeline", icon: <BarChart3 className="w-3.5 h-3.5" /> },
    { id: "sequences", label: "Sequences", icon: <GitBranch className="w-3.5 h-3.5" /> },
    { id: "cost", label: "Cost", icon: <DollarSign className="w-3.5 h-3.5" /> },
    { id: "ab", label: "A/B Tests", icon: <FlaskConical className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="flex gap-0 px-6 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-x-auto">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap",
            active === t.id
              ? "border-zinc-900 dark:border-zinc-100 text-zinc-900 dark:text-zinc-100"
              : "border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
          )}
        >
          {t.icon}
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ─── Personalization Leaderboard Tab ─────────────────────────────────────────

function LeaderboardTab() {
  const [items, setItems] = useState<PersonalizationLeaderboardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState<PersonalizationLeaderboardItem | null>(null);
  const [filterCluster, setFilterCluster] = useState("");
  const [filterTranche, setFilterTranche] = useState("");
  const [batchResult, setBatchResult] = useState<{ processed: number; errors: number; avg_readiness_score: number } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number> = { limit: 100 };
      if (filterCluster) params.cluster = filterCluster;
      if (filterTranche) params.tranche = filterTranche;
      const data = await getPersonalizationLeaderboard(params as { limit?: number; cluster?: string; tranche?: string });
      setItems(data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load leaderboard");
    } finally {
      setLoading(false);
    }
  }, [filterCluster, filterTranche]);

  useEffect(() => {
    load();
  }, [load]);

  const runOne = async (companyId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRunningId(companyId);
    try {
      await runPersonalization(companyId);
      await load();
    } catch (err) {
      console.error("Run personalization failed:", err);
    } finally {
      setRunningId(null);
    }
  };

  const runAll = async () => {
    setBatchRunning(true);
    setBatchResult(null);
    try {
      const result = await runPersonalizationBatch(
        { cluster: filterCluster || undefined, tranche: filterTranche || undefined },
        50
      );
      setBatchResult({
        processed: result.processed,
        errors: result.errors,
        avg_readiness_score: result.avg_readiness_score,
      });
      await load();
    } catch (err) {
      console.error("Batch run failed:", err);
    } finally {
      setBatchRunning(false);
    }
  };

  const clusters = [...new Set(items.map((i) => i.cluster).filter(Boolean))];
  const tranches = [...new Set(items.map((i) => i.tranche).filter(Boolean))];

  if (loading) {
    return (
      <div className="p-6 space-y-2">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-14 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center">
        <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-amber-500" />
        <p className="text-sm text-zinc-500">{error}</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      {/* Controls row */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-1">
          <Filter className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
          <select
            value={filterCluster}
            onChange={(e) => setFilterCluster(e.target.value)}
            className="text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300"
          >
            <option value="">All Clusters</option>
            {clusters.map((c) => (
              <option key={c!} value={c!}>{c}</option>
            ))}
          </select>
          <select
            value={filterTranche}
            onChange={(e) => setFilterTranche(e.target.value)}
            className="text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300"
          >
            <option value="">All Tranches</option>
            {tranches.map((t) => (
              <option key={t!} value={t!}>{t}</option>
            ))}
          </select>
        </div>
        <button
          onClick={runAll}
          disabled={batchRunning}
          className="flex items-center gap-2 px-4 py-1.5 bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-sm font-medium rounded-lg hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50 transition-colors"
        >
          {batchRunning ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running...</>
          ) : (
            <><PlayCircle className="w-3.5 h-3.5" /> Run All</>
          )}
        </button>
      </div>

      {/* Batch result banner */}
      {batchResult && (
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg px-4 py-2.5 text-sm flex items-center gap-2">
          <Check className="w-4 h-4 text-green-600 dark:text-green-400" />
          <span className="text-green-800 dark:text-green-300">
            Batch complete: {batchResult.processed} processed, {batchResult.errors} errors,
            avg score {batchResult.avg_readiness_score.toFixed(0)}
          </span>
        </div>
      )}

      {/* Table */}
      {items.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-12 text-center">
          <Target className="w-8 h-8 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
          <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400 mb-1">
            No personalized companies yet
          </p>
          <p className="text-xs text-zinc-400">
            Click "Run All" to personalize your top qualified companies.
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-100 dark:border-zinc-800">
                <th className="text-left px-4 py-2.5 font-medium text-zinc-400">Company</th>
                <th className="text-left px-3 py-2.5 font-medium text-zinc-400 hidden md:table-cell">Cluster</th>
                <th className="text-left px-3 py-2.5 font-medium text-zinc-400 w-36">Readiness</th>
                <th className="text-right px-3 py-2.5 font-medium text-zinc-400">Triggers</th>
                <th className="text-right px-3 py-2.5 font-medium text-zinc-400">Hooks</th>
                <th className="text-right px-4 py-2.5 font-medium text-zinc-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.company_id}
                  onClick={() => setSelectedCompany(item)}
                  className="border-b border-zinc-50 dark:border-zinc-800/50 last:border-0 hover:bg-zinc-50 dark:hover:bg-zinc-800/30 cursor-pointer group"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-900 dark:text-zinc-100 group-hover:text-zinc-700 dark:group-hover:text-zinc-300">
                      {item.company_name}
                    </div>
                    {item.last_run_at && (
                      <div className="text-[10px] text-zinc-400 mt-0.5">
                        {new Date(item.last_run_at).toLocaleDateString()}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell">
                    {item.cluster && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded-full">
                        {item.cluster}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 w-36">
                    <ReadinessScore score={item.readiness_score} size="sm" showLabel={false} />
                    <span className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5 block">
                      {item.readiness_score}/100
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <span className={cn(
                      "font-medium",
                      item.trigger_count > 0 ? "text-zinc-900 dark:text-zinc-100" : "text-zinc-400"
                    )}>
                      {item.trigger_count}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <span className={cn(
                      "font-medium",
                      item.hook_count > 0 ? "text-zinc-900 dark:text-zinc-100" : "text-zinc-400"
                    )}>
                      {item.hook_count}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => runOne(item.company_id, e)}
                      disabled={runningId === item.company_id}
                      className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors disabled:opacity-40"
                      title="Run personalization"
                    >
                      {runningId === item.company_id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Play className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail panel */}
      {selectedCompany && (
        <PersonalizationDetailPanel
          company={{
            id: selectedCompany.company_id,
            name: selectedCompany.company_name,
            campaign_cluster: selectedCompany.cluster,
            tier: selectedCompany.tranche,
          }}
          onClose={() => setSelectedCompany(null)}
          onRefreshed={load}
        />
      )}
    </div>
  );
}

// ─── Trigger Feed Tab ─────────────────────────────────────────────────────────

function TriggerFeedTab() {
  const [items, setItems] = useState<PersonalizationLeaderboardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string>("");
  const [filterUrgency, setFilterUrgency] = useState<string>("");
  const [addModalOpen, setAddModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPersonalizationLeaderboard({ limit: 200 });
      setItems(data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Flatten all triggers across companies, sort by urgency
  const urgencyOrder: Record<string, number> = { immediate: 0, near_term: 1, background: 2 };

  const allTriggers: Array<{ trigger: TriggerEvent; company: PersonalizationLeaderboardItem }> =
    items
      .flatMap((item) => {
        // triggers not stored in leaderboard — we show placeholder with company context
        return []; // actual triggers come from /status/{id} — skip for feed view
      })
      .sort((a, b) =>
        (urgencyOrder[a.trigger.urgency] ?? 2) - (urgencyOrder[b.trigger.urgency] ?? 2)
      );

  if (loading) {
    return (
      <div className="p-6 space-y-3">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-20 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1">
          <Filter className="w-3.5 h-3.5 text-zinc-400" />
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300"
          >
            <option value="">All Types</option>
            <option value="growth">Growth</option>
            <option value="pain">Pain</option>
            <option value="tech">Tech</option>
            <option value="timing">Timing</option>
          </select>
          <select
            value={filterUrgency}
            onChange={(e) => setFilterUrgency(e.target.value)}
            className="text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300"
          >
            <option value="">All Urgency</option>
            <option value="immediate">Immediate</option>
            <option value="near_term">Near Term</option>
            <option value="background">Background</option>
          </select>
        </div>
        <button
          onClick={() => setAddModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-zinc-200 dark:border-zinc-700 rounded-lg text-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Trigger
        </button>
      </div>

      {/* Feed */}
      {error ? (
        <div className="text-center py-8">
          <AlertTriangle className="w-5 h-5 mx-auto mb-2 text-amber-500" />
          <p className="text-sm text-zinc-500">{error}</p>
        </div>
      ) : items.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-12 text-center">
          <Zap className="w-8 h-8 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
          <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400 mb-1">
            No triggers yet
          </p>
          <p className="text-xs text-zinc-400">
            Run personalization on companies to surface buying triggers here.
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl divide-y divide-zinc-100 dark:divide-zinc-800">
          {items.filter((item) => item.trigger_count > 0).map((item) => (
            <div key={item.company_id} className="px-4 py-3">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">
                  {item.company_name}
                </span>
                {item.cluster && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-500 rounded-full">
                    {item.cluster}
                  </span>
                )}
                <span className="text-[10px] text-zinc-400 ml-auto">
                  {item.trigger_count} trigger{item.trigger_count !== 1 ? "s" : ""}
                </span>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Run personalization on this company to view detailed triggers.
              </p>
            </div>
          ))}
          {items.filter((item) => item.trigger_count === 0).length === items.length && (
            <div className="px-4 py-8 text-center text-xs text-zinc-400">
              No companies with triggers found. Run personalization to extract buying signals.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Hook Library Tab ─────────────────────────────────────────────────────────

function HookLibraryTab() {
  const [items, setItems] = useState<PersonalizationLeaderboardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterPersona, setFilterPersona] = useState("");
  const [copiedIdx, setCopiedIdx] = useState<string | null>(null);

  useEffect(() => {
    getPersonalizationLeaderboard({ limit: 200 })
      .then((data) => setItems(data || []))
      .finally(() => setLoading(false));
  }, []);

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(key);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const personaOptions = ["vp_ops", "plant_manager", "engineer", "procurement", "executive", "operations_general"];
  const personaLabels: Record<string, string> = {
    vp_ops: "VP Ops",
    plant_manager: "Plant Mgr",
    engineer: "Engineer",
    procurement: "Procurement",
    executive: "Executive",
    operations_general: "Operations",
  };

  if (loading) {
    return (
      <div className="p-6 grid grid-cols-2 gap-3">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-32 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  const companiesWithHooks = items.filter((item) => item.hook_count > 0);

  return (
    <div className="p-6 space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-2">
        <Filter className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
        <select
          value={filterPersona}
          onChange={(e) => setFilterPersona(e.target.value)}
          className="text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300"
        >
          <option value="">All Personas</option>
          {personaOptions.map((p) => (
            <option key={p} value={p}>{personaLabels[p]}</option>
          ))}
        </select>
      </div>

      {companiesWithHooks.length === 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-12 text-center">
          <BookOpen className="w-8 h-8 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
          <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400 mb-1">
            No hooks generated yet
          </p>
          <p className="text-xs text-zinc-400">
            Run personalization on companies to generate email opening hooks.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {companiesWithHooks.map((item) => (
            <div
              key={item.company_id}
              className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4"
            >
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                  {item.company_name}
                </span>
                {item.cluster && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-500 rounded-full">
                    {item.cluster}
                  </span>
                )}
                <span className="text-xs text-zinc-400 ml-auto">
                  {item.hook_count} hook{item.hook_count !== 1 ? "s" : ""}
                </span>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Open this company to view and copy individual hooks.
              </p>
              <div className="flex flex-wrap gap-1 mt-2">
                {item.personas_found.filter((p) => !filterPersona || p === filterPersona).map((p) => (
                  <span
                    key={p}
                    className="text-[10px] font-medium px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded"
                  >
                    {personaLabels[p] || p}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Pipeline Tab ─────────────────────────────────────────────────────────────

function PipelineTab() {
  const [funnelStages, setFunnelStages] = useState<FunnelStage[]>([]);
  const [velocity, setVelocity] = useState<VelocityData | null>(null);
  const [weekly, setWeekly] = useState<WeeklyDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dayRange, setDayRange] = useState(30);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [funnelRes, velRes, weeklyRes] = await Promise.allSettled([
          getIntelligenceFunnel(dayRange),
          getIntelligenceVelocity(),
          getIntelligenceWeekly(8),
        ]);

        if (funnelRes.status === "fulfilled") {
          const funnel = funnelRes.value.funnel || {};
          setFunnelStages(
            Object.entries(funnel).map(([status, count]) => ({
              status,
              label: STATUS_LABELS[status] || status,
              count: count as number,
            }))
          );
        }

        if (velRes.status === "fulfilled") {
          setVelocity(velRes.value.data);
        }

        if (weeklyRes.status === "fulfilled") {
          setWeekly(weeklyRes.value.data || []);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [dayRange]);

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-32 bg-zinc-200 dark:bg-zinc-800 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center">
        <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-amber-500" />
        <p className="text-sm text-zinc-500">{error}</p>
      </div>
    );
  }

  const maxCount = Math.max(...funnelStages.map((s) => s.count), 1);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-500 dark:text-zinc-400">Period:</span>
        {[7, 14, 30, 90].map((d) => (
          <button
            key={d}
            onClick={() => setDayRange(d)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium transition-colors",
              dayRange === d
                ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900"
                : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
            )}
          >
            {d}d
          </button>
        ))}
      </div>

      {funnelStages.length > 0 ? (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-4">Pipeline Funnel</h2>
          <div className="space-y-3">
            {funnelStages.map((stage, i) => {
              const pct = Math.round((stage.count / maxCount) * 100);
              const convPct =
                i > 0 && funnelStages[i - 1].count > 0
                  ? Math.round((stage.count / funnelStages[i - 1].count) * 100)
                  : null;
              return (
                <div key={stage.status}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300 w-28">{stage.label}</span>
                      {convPct !== null && (
                        <span className={cn("text-[10px] flex items-center gap-0.5", convPct >= 20 ? "text-green-500" : convPct >= 10 ? "text-amber-500" : "text-rose-500")}>
                          <ArrowRight className="w-2.5 h-2.5" />{convPct}%
                        </span>
                      )}
                    </div>
                    <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{stage.count.toLocaleString()}</span>
                  </div>
                  <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-zinc-900 dark:bg-zinc-100 rounded-full transition-all" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-8 text-center">
          <BarChart3 className="w-8 h-8 mx-auto mb-2 text-zinc-300 dark:text-zinc-700" />
          <p className="text-sm text-zinc-400">No funnel data for this period</p>
        </div>
      )}

      {velocity && (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-4 flex items-center gap-2">
            <Clock className="w-4 h-4" />Pipeline Velocity
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center">
              <div className="text-3xl font-bold text-zinc-900 dark:text-zinc-100">{velocity.enriched_to_sequenced_days}</div>
              <div className="text-xs text-zinc-400 mt-1">days enriched → sequenced</div>
            </div>
            <div className="text-center border-x border-zinc-100 dark:border-zinc-800">
              <div className="text-3xl font-bold text-zinc-900 dark:text-zinc-100">{velocity.sequenced_to_replied_days}</div>
              <div className="text-xs text-zinc-400 mt-1">days sequenced → replied</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-zinc-900 dark:text-zinc-100">{velocity.overall_discovery_to_reply_days}</div>
              <div className="text-xs text-zinc-400 mt-1">days discovery → reply</div>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800 text-xs text-zinc-400 text-center">
            Based on {velocity.contacts_with_reply} contacts with at least one reply
          </div>
        </div>
      )}

      {weekly.length > 0 && (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-4 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" />Weekly Activity (last 8 weeks)
          </h2>
          <div className="space-y-4">
            {["contacts_added", "sequenced", "replied"].map((metric) => {
              const maxVal = Math.max(...weekly.map((w) => (w as unknown as Record<string, number>)[metric] || 0), 1);
              const labels: Record<string, string> = { contacts_added: "Contacts Added", sequenced: "Sequenced", replied: "Replied" };
              const colors: Record<string, string> = { contacts_added: "bg-blue-500", sequenced: "bg-amber-500", replied: "bg-green-500" };
              return (
                <div key={metric}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{labels[metric]}</span>
                    <span className="text-xs text-zinc-400">{weekly[weekly.length - 1] ? (weekly[weekly.length - 1] as unknown as Record<string, number>)[metric] : 0} this week</span>
                  </div>
                  <div className="flex items-end gap-1 h-10">
                    {weekly.map((w, i) => {
                      const val = (w as unknown as Record<string, number>)[metric] || 0;
                      const h = Math.max((val / maxVal) * 100, 2);
                      return (
                        <div key={i} className="flex-1 flex flex-col justify-end" title={`${w.week_start}: ${val}`}>
                          <div className={cn("rounded-sm", colors[metric])} style={{ height: `${h}%` }} />
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sequences Tab ────────────────────────────────────────────────────────────

function SequencesTab() {
  const [data, setData] = useState<SequencePerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSequencePerformance()
      .then((res) => setData(res.data || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-12 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center">
        <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-amber-500" />
        <p className="text-sm text-zinc-500">{error}</p>
      </div>
    );
  }

  const grouped = data.reduce<Record<string, SequencePerformance[]>>((acc, item) => {
    const key = item.sequence_name;
    if (!acc[key]) acc[key] = [];
    acc[key].push(item);
    return acc;
  }, {});

  return (
    <div className="p-6">
      {Object.keys(grouped).length === 0 ? (
        <div className="text-center py-16">
          <GitBranch className="w-8 h-8 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
          <p className="text-sm text-zinc-400">No sequence data yet. Send outreach drafts to see performance here.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([seqName, steps]) => {
            const totalDrafts = steps.reduce((s, r) => s + r.total_drafts, 0);
            const totalApproved = steps.reduce((s, r) => s + r.approved, 0);
            const totalRejected = steps.reduce((s, r) => s + r.rejected, 0);
            const approvalRate = totalDrafts > 0 ? Math.round((totalApproved / totalDrafts) * 100) : 0;

            return (
              <div key={seqName} className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                <div className="px-5 py-3 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">{seqName}</span>
                    <span className="ml-3 text-xs text-zinc-400">{steps.length} steps · {totalDrafts} total drafts</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-green-600 dark:text-green-400">{approvalRate}% approval</span>
                    <span className="text-zinc-400">{totalRejected} rejected</span>
                  </div>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-zinc-100 dark:border-zinc-800">
                      <th className="text-left px-5 py-2 font-medium text-zinc-400">Step</th>
                      <th className="text-left px-3 py-2 font-medium text-zinc-400">Channel</th>
                      <th className="text-right px-3 py-2 font-medium text-zinc-400">Drafts</th>
                      <th className="text-right px-3 py-2 font-medium text-zinc-400">Approved</th>
                      <th className="text-right px-3 py-2 font-medium text-zinc-400">Rejected</th>
                      <th className="text-right px-5 py-2 font-medium text-zinc-400">Pending</th>
                    </tr>
                  </thead>
                  <tbody>
                    {steps.sort((a, b) => a.step - b.step).map((row) => {
                      const stepApproval = row.total_drafts > 0 ? Math.round((row.approved / row.total_drafts) * 100) : 0;
                      return (
                        <tr key={row.step} className="border-b border-zinc-50 dark:border-zinc-800/50 last:border-0 hover:bg-zinc-50 dark:hover:bg-zinc-800/30">
                          <td className="px-5 py-2.5 text-zinc-700 dark:text-zinc-300">Step {row.step}</td>
                          <td className="px-3 py-2.5 text-zinc-500 capitalize">{row.channel}</td>
                          <td className="px-3 py-2.5 text-right text-zinc-700 dark:text-zinc-300">{row.total_drafts}</td>
                          <td className="px-3 py-2.5 text-right">
                            <span className="text-green-600 dark:text-green-400 font-medium">{row.approved}</span>
                            <span className="text-zinc-400 ml-1">({stepApproval}%)</span>
                          </td>
                          <td className="px-3 py-2.5 text-right text-rose-500">{row.rejected}</td>
                          <td className="px-5 py-2.5 text-right text-amber-500">{row.pending}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Cost Tab ─────────────────────────────────────────────────────────────────

function CostTab() {
  const [costData, setCostData] = useState<{
    data: CostData;
    anthropic_balance_usd: number | null;
    weekly_trend: unknown[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIntelligenceCosts()
      .then((res) => setCostData(res as unknown as { data: CostData; anthropic_balance_usd: number | null; weekly_trend: unknown[] }))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-32 bg-zinc-200 dark:bg-zinc-800 rounded-xl animate-pulse" />
        <div className="h-48 bg-zinc-200 dark:bg-zinc-800 rounded-xl animate-pulse" />
      </div>
    );
  }

  if (error || !costData) {
    return (
      <div className="p-6 text-center">
        <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-amber-500" />
        <p className="text-sm text-zinc-500">{error || "No cost data available"}</p>
      </div>
    );
  }

  const { data: costs, anthropic_balance_usd } = costData;
  const capPct = Math.min(costs.pct_of_cap || 0, 100);

  return (
    <div className="p-6 space-y-5">
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-zinc-400 mb-1">This Month</div>
          <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">${(costs.total_usd || 0).toFixed(2)}</div>
          <div className="text-xs text-zinc-400 mt-1">of ${(costs.monthly_cap_usd || 0).toFixed(0)} cap</div>
        </div>
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-zinc-400 mb-1">Research</div>
          <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">${(costs.research_usd || 0).toFixed(2)}</div>
          <div className="text-xs text-zinc-400 mt-1">{costs.total_usd > 0 ? Math.round(((costs.research_usd || 0) / costs.total_usd) * 100) : 0}% of total</div>
        </div>
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4">
          <div className="text-xs text-zinc-400 mb-1">Drafts</div>
          <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">${(costs.drafts_usd || 0).toFixed(2)}</div>
          {anthropic_balance_usd !== null && (
            <div className="text-xs text-green-500 mt-1">${anthropic_balance_usd.toFixed(2)} balance</div>
          )}
        </div>
      </div>

      <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Monthly Cap Usage</span>
          <span className={cn("text-sm font-bold", capPct >= 90 ? "text-rose-500" : capPct >= 75 ? "text-amber-500" : "text-green-500")}>
            {capPct.toFixed(1)}%
          </span>
        </div>
        <div className="h-3 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", capPct >= 90 ? "bg-rose-500" : capPct >= 75 ? "bg-amber-500" : "bg-green-500")}
            style={{ width: `${capPct}%` }}
          />
        </div>
        <div className="flex justify-between mt-1.5 text-xs text-zinc-400">
          <span>${(costs.total_usd || 0).toFixed(2)} used</span>
          <span>${(costs.monthly_cap_usd || 0).toFixed(0)} cap</span>
        </div>
      </div>

      {costs.by_agent && Object.keys(costs.by_agent).length > 0 && (
        <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-4">Cost by Agent</h2>
          <div className="space-y-3">
            {Object.entries(costs.by_agent).sort(([, a], [, b]) => (b as number) - (a as number)).map(([agent, cost]) => {
              const agentCost = cost as number;
              const pct = costs.total_usd > 0 ? (agentCost / costs.total_usd) * 100 : 0;
              return (
                <div key={agent}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-zinc-700 dark:text-zinc-300 capitalize">{agent.replace(/_/g, " ")}</span>
                    <span className="text-xs font-semibold text-zinc-900 dark:text-zinc-100">${agentCost.toFixed(3)}</span>
                  </div>
                  <div className="h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── A/B Tests Tab ─────────────────────────────────────────────────────────────

function ABTestsTab() {
  return (
    <div className="p-6">
      <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-8 text-center">
        <FlaskConical className="w-10 h-10 mx-auto mb-3 text-zinc-300 dark:text-zinc-700" />
        <h3 className="font-semibold text-zinc-700 dark:text-zinc-300 mb-2">A/B Testing — Coming Soon</h3>
        <p className="text-sm text-zinc-400 max-w-sm mx-auto">
          Split-test subject lines, opening hooks, and send times across segments.
          Configure experiments and view statistical significance.
        </p>
        <div className="mt-6 grid grid-cols-3 gap-4 max-w-md mx-auto text-left">
          {[
            { label: "Subject Line Tests", desc: "Test 2–4 variants, auto-pick winner" },
            { label: "Send Time Optimization", desc: "Learn best send time per persona" },
            { label: "Hook Angle Tests", desc: "Pain-led vs outcome-led vs curiosity" },
          ].map((item) => (
            <div key={item.label} className="border border-zinc-200 dark:border-zinc-800 rounded-lg p-3 opacity-60">
              <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">{item.label}</div>
              <div className="text-[10px] text-zinc-400">{item.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function IntelligencePage() {
  const [activeTab, setActiveTab] = useState("leaderboard");
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <div className="px-6 py-5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Intelligence</h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
              Personalization readiness, buying triggers, hook library, pipeline analytics
            </p>
          </div>
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <TabBar active={activeTab} onChange={setActiveTab} />

      {/* Tab content */}
      <div key={refreshKey}>
        {activeTab === "leaderboard" && <LeaderboardTab />}
        {activeTab === "triggers" && <TriggerFeedTab />}
        {activeTab === "hooks" && <HookLibraryTab />}
        {activeTab === "pipeline" && <PipelineTab />}
        {activeTab === "sequences" && <SequencesTab />}
        {activeTab === "cost" && <CostTab />}
        {activeTab === "ab" && <ABTestsTab />}
      </div>
    </div>
  );
}
