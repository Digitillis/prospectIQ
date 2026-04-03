"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  Users,
  Zap,
  ChevronDown,
  X,
  Search,
  Plus,
  Clock,
  CheckSquare,
  Square,
  Info,
  ArrowRight,
  Building2,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  runLookalike,
  runAutoLookalike,
  getLookalikeRuns,
  getLookalikeRun,
  addLookalikesToPipeline,
  getSeedProfile,
  getCompanies,
  type LookalikeResult,
  type LookalikeMatch,
  type LookalikeRunSummary,
  type SeedProfile,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number): string {
  if (score >= 80) return "text-green-500";
  if (score >= 60) return "text-amber-500";
  return "text-red-400";
}

function scoreBg(score: number): string {
  if (score >= 80) return "bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800";
  if (score >= 60) return "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800";
  return "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// SeedProfileCard
// ---------------------------------------------------------------------------

function SeedProfileCard({ profile }: { profile: SeedProfile }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4 mt-4">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
        Seed Profile
      </p>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="text-gray-500 dark:text-gray-400">Cluster: </span>
          <span className="font-medium text-gray-900 dark:text-gray-100 capitalize">
            {profile.dominant_cluster}
          </span>
        </div>
        <div>
          <span className="text-gray-500 dark:text-gray-400">Tranche: </span>
          <span className="font-medium text-gray-900 dark:text-gray-100">
            {profile.dominant_tranche}
          </span>
        </div>
        <div>
          <span className="text-gray-500 dark:text-gray-400">Avg PQS: </span>
          <span className="font-bold text-green-600 dark:text-green-400">
            {profile.avg_pqs}
          </span>
        </div>
        <div>
          <span className="text-gray-500 dark:text-gray-400">Seed size: </span>
          <span className="font-medium text-gray-900 dark:text-gray-100">
            {profile.seed_company_count} companies
          </span>
        </div>
      </div>
      {profile.top_technologies.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1.5">Top technologies:</p>
          <div className="flex flex-wrap gap-1">
            {profile.top_technologies.slice(0, 6).map((t) => (
              <span
                key={t}
                className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded text-xs"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
      {profile.top_pain_themes.length > 0 && (
        <div className="mt-2">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1.5">Pain themes:</p>
          <div className="flex flex-wrap gap-1">
            {profile.top_pain_themes.slice(0, 4).map((p) => (
              <span
                key={p}
                className="px-2 py-0.5 bg-orange-50 dark:bg-orange-950 text-orange-700 dark:text-orange-300 rounded text-xs"
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LookalikeMatchCard
// ---------------------------------------------------------------------------

function LookalikeMatchCard({
  match,
  selected,
  onSelect,
  onAddToPipeline,
  onViewCompany,
}: {
  match: LookalikeMatch;
  selected: boolean;
  onSelect: () => void;
  onAddToPipeline: () => void;
  onViewCompany: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-white dark:bg-gray-900 p-4 hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-200 relative",
        selected
          ? "border-blue-400 dark:border-blue-500 ring-1 ring-blue-400 dark:ring-blue-500"
          : "border-gray-200 dark:border-gray-700"
      )}
    >
      {/* Select checkbox */}
      <button
        onClick={onSelect}
        className="absolute top-3 right-3 text-gray-400 hover:text-blue-500 transition-colors"
        aria-label={selected ? "Deselect company" : "Select company"}
      >
        {selected ? (
          <CheckSquare className="h-4 w-4 text-blue-500" />
        ) : (
          <Square className="h-4 w-4" />
        )}
      </button>

      {/* Header row */}
      <div className="flex items-start justify-between mb-2 pr-6">
        <div className="min-w-0">
          <p className="font-semibold text-gray-900 dark:text-white text-sm truncate">
            {match.company_name}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
            {match.domain || "—"}
          </p>
        </div>
        <div className="flex items-baseline gap-1 ml-2 shrink-0">
          <span className={cn("text-xl font-bold", scoreColor(match.similarity_score))}>
            {match.similarity_score}
          </span>
          <span className="text-xs text-gray-400 dark:text-gray-500">/ 100</span>
        </div>
      </div>

      {/* Score bar */}
      <div className="mb-3 h-1 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            match.similarity_score >= 80
              ? "bg-green-500"
              : match.similarity_score >= 60
              ? "bg-amber-500"
              : "bg-red-400"
          )}
          style={{ width: `${match.similarity_score}%` }}
        />
      </div>

      {/* Badges row */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {match.cluster && (
          <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded text-xs font-medium capitalize">
            {match.cluster}
          </span>
        )}
        {match.tranche && (
          <span className="px-2 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded text-xs">
            {match.tranche}
          </span>
        )}
        <span className="px-2 py-0.5 bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 rounded text-xs">
          PQS {Math.round(match.pqs_total)}
        </span>
        {match.has_contact && (
          <span className="px-2 py-0.5 bg-green-50 dark:bg-green-950 text-green-600 dark:text-green-400 rounded text-xs">
            Has contact
          </span>
        )}
      </div>

      {/* Why it matched */}
      {match.matching_factors.length > 0 && (
        <div className="mb-3">
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-1">Why it matched:</p>
          <div className="flex flex-col gap-0.5">
            {match.matching_factors.map((f, i) => (
              <span key={i} className="text-xs text-gray-600 dark:text-gray-400 flex items-center gap-1">
                <span className="text-green-500">✓</span> {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2 border-t border-gray-100 dark:border-gray-800">
        <button
          onClick={onAddToPipeline}
          className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium flex items-center gap-1 transition-colors"
          aria-label={`Add ${match.company_name} to pipeline`}
        >
          <Plus className="h-3 w-3" />
          Add to Pipeline
        </button>
        <button
          onClick={onViewCompany}
          className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-1 transition-colors"
          aria-label={`View ${match.company_name}`}
        >
          <ArrowRight className="h-3 w-3" />
          View Company
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type SeedMode = "auto" | "manual";
type SortKey = "score" | "pqs" | "cluster";

export default function LookalikeDiscoveryPage() {
  const [seedMode, setSeedMode] = useState<SeedMode>("auto");
  const [result, setResult] = useState<LookalikeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Past runs
  const [pastRuns, setPastRuns] = useState<LookalikeRunSummary[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);

  // Seed profile preview (auto mode)
  const [seedProfile, setSeedProfile] = useState<SeedProfile | null>(null);
  const [seedProfileLoading, setSeedProfileLoading] = useState(false);

  // Manual seed selection
  const [manualSearch, setManualSearch] = useState("");
  const [searchResults, setSearchResults] = useState<{ id: string; name: string; domain?: string; status: string }[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedSeedIds, setSelectedSeedIds] = useState<string[]>([]);
  const [selectedSeedNames, setSelectedSeedNames] = useState<Record<string, string>>({});

  // Match selection + filters
  const [selectedMatchIds, setSelectedMatchIds] = useState<Set<string>>(new Set());
  const [minScore, setMinScore] = useState(60);
  const [sortKey, setSortKey] = useState<SortKey>("score");

  // Add to pipeline state
  const [addingToPipeline, setAddingToPipeline] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<{ added: number; already_in_pipeline: number } | null>(null);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);

  // Load past runs + seed profile on mount
  useEffect(() => {
    getLookalikeRuns()
      .then((res) => setPastRuns(res.data || []))
      .catch(() => {})
      .finally(() => setRunsLoading(false));

    if (seedMode === "auto") {
      setSeedProfileLoading(true);
      getSeedProfile()
        .then((p) => setSeedProfile(p))
        .catch(() => {})
        .finally(() => setSeedProfileLoading(false));
    }
  }, []);

  // Live company search for manual mode
  useEffect(() => {
    if (!manualSearch.trim() || seedMode !== "manual") {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(() => {
      setSearchLoading(true);
      getCompanies({ search: manualSearch, limit: "10" })
        .then((res) => {
          const rows = (res.data || []).filter((c: { id: string }) => !selectedSeedIds.includes(c.id));
          setSearchResults(rows.map((c: { id: string; name: string; domain?: string; status: string }) => ({
            id: c.id,
            name: c.name,
            domain: c.domain,
            status: c.status,
          })));
        })
        .catch(() => setSearchResults([]))
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [manualSearch, seedMode, selectedSeedIds]);

  const handleAutoRun = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setPipelineResult(null);
    setSelectedMatchIds(new Set());
    try {
      const res = await runAutoLookalike();
      setResult(res);
      setCurrentRunId(res.run_id);
      setSeedProfile(res.seed_profile);
      // Refresh past runs
      getLookalikeRuns().then((r) => setPastRuns(r.data || [])).catch(() => {});
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Discovery failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleManualRun = async () => {
    if (selectedSeedIds.length === 0) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setPipelineResult(null);
    setSelectedMatchIds(new Set());
    try {
      const res = await runLookalike(selectedSeedIds, 50, true);
      setResult(res);
      setCurrentRunId(res.run_id);
      getLookalikeRuns().then((r) => setPastRuns(r.data || [])).catch(() => {});
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Discovery failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const loadPastRun = async (runId: string) => {
    setLoading(true);
    setError(null);
    setPipelineResult(null);
    setSelectedMatchIds(new Set());
    try {
      const run = await getLookalikeRun(runId);
      setResult({
        run_id: run.id,
        seed_profile: run.seed_profile,
        matches: run.matches,
        total_scored: run.total_scored,
        generated_at: run.created_at,
      });
      setCurrentRunId(run.id);
      setSeedProfile(run.seed_profile);
    } catch {
      setError("Failed to load run");
    } finally {
      setLoading(false);
    }
  };

  const handleAddSelected = async () => {
    if (!currentRunId || selectedMatchIds.size === 0) return;
    setAddingToPipeline(true);
    try {
      const res = await addLookalikesToPipeline(currentRunId, Array.from(selectedMatchIds));
      setPipelineResult(res);
      setSelectedMatchIds(new Set());
    } catch {
      setError("Failed to add companies to pipeline");
    } finally {
      setAddingToPipeline(false);
    }
  };

  const handleAddSingle = async (match: LookalikeMatch) => {
    if (!currentRunId) return;
    try {
      const res = await addLookalikesToPipeline(currentRunId, [match.company_id]);
      setPipelineResult(res);
    } catch {
      setError("Failed to add company to pipeline");
    }
  };

  const handleAddAll = async () => {
    if (!currentRunId || !result) return;
    const filtered = filteredMatches;
    setAddingToPipeline(true);
    try {
      const res = await addLookalikesToPipeline(currentRunId, filtered.map((m) => m.company_id));
      setPipelineResult(res);
      setSelectedMatchIds(new Set());
    } catch {
      setError("Failed to add companies to pipeline");
    } finally {
      setAddingToPipeline(false);
    }
  };

  const toggleMatchSelection = (id: string) => {
    setSelectedMatchIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const addSeedCompany = (id: string, name: string) => {
    if (!selectedSeedIds.includes(id)) {
      setSelectedSeedIds((p) => [...p, id]);
      setSelectedSeedNames((p) => ({ ...p, [id]: name }));
    }
    setManualSearch("");
    setSearchResults([]);
  };

  const removeSeedCompany = (id: string) => {
    setSelectedSeedIds((p) => p.filter((s) => s !== id));
    setSelectedSeedNames((p) => {
      const next = { ...p };
      delete next[id];
      return next;
    });
  };

  // Filtered + sorted matches
  const filteredMatches: LookalikeMatch[] = result
    ? [...result.matches]
        .filter((m) => m.similarity_score >= minScore)
        .sort((a, b) => {
          if (sortKey === "pqs") return b.pqs_total - a.pqs_total;
          if (sortKey === "cluster") return (a.cluster || "").localeCompare(b.cluster || "");
          return b.similarity_score - a.similarity_score;
        })
    : [];

  return (
    <div className="flex h-full min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* ------------------------------------------------------------------ */}
      {/* LEFT PANEL — Seed & Controls                                        */}
      {/* ------------------------------------------------------------------ */}
      <aside className="w-[400px] shrink-0 border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex flex-col overflow-y-auto">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-blue-500" />
            <h1 className="text-base font-semibold text-gray-900 dark:text-white">
              Lookalike Discovery
            </h1>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Surface companies that look like your best-performing prospects.
          </p>
        </div>

        <div className="flex-1 px-5 py-4 space-y-5">
          {/* Mode toggle */}
          <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-xs font-medium">
            <button
              onClick={() => setSeedMode("auto")}
              className={cn(
                "flex-1 py-2 px-3 flex items-center justify-center gap-1.5 transition-colors",
                seedMode === "auto"
                  ? "bg-blue-600 text-white"
                  : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
              )}
            >
              <Zap className="h-3.5 w-3.5" />
              Auto-seed
            </button>
            <button
              onClick={() => setSeedMode("manual")}
              className={cn(
                "flex-1 py-2 px-3 flex items-center justify-center gap-1.5 transition-colors",
                seedMode === "manual"
                  ? "bg-blue-600 text-white"
                  : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
              )}
            >
              <Users className="h-3.5 w-3.5" />
              Manual seed
            </button>
          </div>

          {/* Auto mode */}
          {seedMode === "auto" && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-100 dark:border-blue-900 p-3">
                <Info className="h-3.5 w-3.5 text-blue-500 mt-0.5 shrink-0" />
                <p className="text-xs text-blue-700 dark:text-blue-300">
                  Uses your best-performing companies (replied, interested, demo booked, customer)
                  as the seed cohort.
                </p>
              </div>
              <button
                onClick={handleAutoRun}
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md px-4 py-2.5 text-sm font-medium flex items-center justify-center gap-2 transition-colors"
              >
                {loading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {loading ? "Running discovery..." : "Find Lookalikes"}
              </button>
              {seedProfileLoading && (
                <p className="text-xs text-gray-400 text-center">Loading seed profile...</p>
              )}
              {seedProfile && seedProfile.seed_company_count > 0 && (
                <SeedProfileCard profile={seedProfile} />
              )}
            </div>
          )}

          {/* Manual mode */}
          {seedMode === "manual" && (
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 block">
                  Search companies to use as seed
                </label>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
                  <input
                    type="text"
                    value={manualSearch}
                    onChange={(e) => setManualSearch(e.target.value)}
                    placeholder="Search by company name..."
                    className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-md bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                {/* Search results dropdown */}
                {searchResults.length > 0 && (
                  <div className="mt-1 border border-gray-200 dark:border-gray-700 rounded-md bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
                    {searchResults.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => addSeedCompany(c.id, c.name)}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-800 last:border-0"
                      >
                        <span className="text-gray-900 dark:text-gray-100 font-medium truncate">
                          {c.name}
                        </span>
                        <span className="text-xs text-gray-400 shrink-0">{c.status}</span>
                      </button>
                    ))}
                  </div>
                )}

                {searchLoading && (
                  <p className="text-xs text-gray-400 mt-1">Searching...</p>
                )}
              </div>

              {/* Selected chips */}
              {selectedSeedIds.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                    Seed companies ({selectedSeedIds.length})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedSeedIds.map((id) => (
                      <span
                        key={id}
                        className="flex items-center gap-1 px-2 py-0.5 bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded-full text-xs"
                      >
                        {selectedSeedNames[id] || id.slice(0, 8)}
                        <button
                          onClick={() => removeSeedCompany(id)}
                          className="hover:text-blue-900 dark:hover:text-blue-100 transition-colors"
                          aria-label={`Remove ${selectedSeedNames[id]}`}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <button
                onClick={handleManualRun}
                disabled={loading || selectedSeedIds.length === 0}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md px-4 py-2.5 text-sm font-medium flex items-center justify-center gap-2 transition-colors"
              >
                {loading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {loading ? "Running discovery..." : `Run Discovery (${selectedSeedIds.length} seed)`}
              </button>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-md bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 p-3 text-xs text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          {/* Pipeline result notification */}
          {pipelineResult && (
            <div className="rounded-md bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 p-3 text-xs text-green-700 dark:text-green-300">
              Added {pipelineResult.added} companies to pipeline
              {pipelineResult.already_in_pipeline > 0 &&
                ` (${pipelineResult.already_in_pipeline} already in pipeline)`}
            </div>
          )}

          {/* Past runs */}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
              Recent Runs
            </p>
            {runsLoading && (
              <p className="text-xs text-gray-400">Loading...</p>
            )}
            {!runsLoading && pastRuns.length === 0 && (
              <p className="text-xs text-gray-400">No runs yet.</p>
            )}
            <div className="space-y-1">
              {pastRuns.slice(0, 8).map((run) => (
                <button
                  key={run.id}
                  onClick={() => loadPastRun(run.id)}
                  className={cn(
                    "w-full text-left rounded-md px-3 py-2 text-xs transition-colors border",
                    currentRunId === run.id
                      ? "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300"
                      : "bg-gray-50 dark:bg-gray-800 border-gray-100 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {run.match_count} matches
                    </span>
                    <span className="text-gray-400 dark:text-gray-500">
                      {run.dominant_cluster} · {run.dominant_tranche}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 mt-0.5 text-gray-400">
                    <Clock className="h-3 w-3" />
                    <span>{formatDate(run.created_at)}</span>
                    <span className="mx-1">·</span>
                    <span>{run.seed_count} seed</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* RIGHT PANEL — Match Results                                         */}
      {/* ------------------------------------------------------------------ */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Results header */}
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-gray-400" />
            <span className="text-sm font-medium text-gray-900 dark:text-white">
              {result
                ? `${filteredMatches.length} matches found`
                : "Run discovery to find lookalikes"}
            </span>
            {result && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                · {result.total_scored} companies scored
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 ml-auto flex-wrap">
            {/* Min score filter */}
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
                Min score:
              </label>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="w-24 accent-blue-600"
                aria-label="Minimum similarity score"
              />
              <span className={cn("text-sm font-bold w-8 text-right", scoreColor(minScore))}>
                {minScore}
              </span>
            </div>

            {/* Sort */}
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-gray-500 dark:text-gray-400">Sort:</label>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className="text-xs border border-gray-200 dark:border-gray-700 rounded-md bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="score">By score</option>
                <option value="pqs">By PQS</option>
                <option value="cluster">By cluster</option>
              </select>
            </div>

            {/* Add all */}
            {result && filteredMatches.length > 0 && (
              <button
                onClick={handleAddAll}
                disabled={addingToPipeline}
                className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-md px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                Add All to Pipeline
              </button>
            )}
          </div>
        </div>

        {/* Bulk action bar */}
        {selectedMatchIds.size > 0 && (
          <div className="px-6 py-2.5 bg-blue-50 dark:bg-blue-950 border-b border-blue-200 dark:border-blue-800 flex items-center gap-3">
            <span className="text-xs font-medium text-blue-700 dark:text-blue-300">
              {selectedMatchIds.size} selected
            </span>
            <button
              onClick={handleAddSelected}
              disabled={addingToPipeline}
              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-md px-3 py-1 text-xs font-medium flex items-center gap-1.5 transition-colors"
            >
              {addingToPipeline ? (
                <RefreshCw className="h-3 w-3 animate-spin" />
              ) : (
                <Plus className="h-3 w-3" />
              )}
              Add to Pipeline
            </button>
            <button
              onClick={() => setSelectedMatchIds(new Set())}
              className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-200 transition-colors"
            >
              Clear selection
            </button>
          </div>
        )}

        {/* Content area */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Empty state */}
          {!result && !loading && (
            <div className="flex flex-col items-center justify-center h-full text-center py-20">
              <div className="rounded-full bg-blue-50 dark:bg-blue-950 p-5 mb-4">
                <Sparkles className="h-10 w-10 text-blue-400" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Find Your Next Best Prospects
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mb-6">
                The Lookalike Discovery Engine scores your entire company database against
                your best-performing prospects and surfaces the most similar targets.
              </p>
              <div className="grid grid-cols-3 gap-4 text-left max-w-lg">
                {[
                  { label: "Cluster match", desc: "Same or adjacent industry cluster" },
                  { label: "Tranche fit", desc: "Matching T1/T2/T3 segmentation" },
                  { label: "Tech overlap", desc: "Shared technology signals" },
                ].map((f) => (
                  <div
                    key={f.label}
                    className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3"
                  >
                    <p className="text-xs font-semibold text-gray-900 dark:text-white mb-0.5">
                      {f.label}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{f.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Loading spinner */}
          {loading && (
            <div className="flex flex-col items-center justify-center h-full py-20">
              <RefreshCw className="h-8 w-8 text-blue-500 animate-spin mb-3" />
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Scoring companies against seed profile...
              </p>
            </div>
          )}

          {/* No matches after filter */}
          {result && !loading && filteredMatches.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                No matches above score {minScore}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Lower the minimum score filter to see more results.
              </p>
            </div>
          )}

          {/* Match grid */}
          {result && !loading && filteredMatches.length > 0 && (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {filteredMatches.map((match) => (
                <LookalikeMatchCard
                  key={match.company_id}
                  match={match}
                  selected={selectedMatchIds.has(match.company_id)}
                  onSelect={() => toggleMatchSelection(match.company_id)}
                  onAddToPipeline={() => handleAddSingle(match)}
                  onViewCompany={() =>
                    window.open(`/prospects?company=${match.company_id}`, "_blank")
                  }
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
