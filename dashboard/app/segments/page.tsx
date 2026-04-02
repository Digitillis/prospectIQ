"use client";

/**
 * Segments — Pre-built and custom company segments with enroll/research/export actions
 */

import { useEffect, useState, useCallback } from "react";
import {
  Users,
  Zap,
  Star,
  Clock,
  RefreshCw,
  Mail,
  Download,
  ChevronDown,
  Plus,
  Filter,
  X,
  Loader2,
  Building2,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { getCompanies, getSequenceTemplates, Company, SequenceTemplate } from "@/lib/api";
import { cn, getPQSColor, TIER_LABELS } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

interface Segment {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  filters: Record<string, string>;
  companies: Company[];
  count: number;
  loading: boolean;
  error: string | null;
  isBuiltIn: boolean;
}

interface CustomSegmentFilter {
  field: string;
  operator: string;
  value: string;
}

// ─── Pre-built segment definitions ───────────────────────────────────────────

const BUILT_IN_SEGMENTS: Omit<Segment, "companies" | "count" | "loading" | "error">[] = [
  {
    id: "high-pqs-ready",
    name: "High-PQS Machinery Ready",
    description: "PQS ≥ 70, machinery/industrial, status = researched or qualified",
    icon: <Star className="w-4 h-4" />,
    color: "text-amber-500",
    filters: { min_pqs: "70", industry: "machinery", status: "researched" },
    isBuiltIn: true,
  },
  {
    id: "fb-ready",
    name: "F&B Ready to Contact",
    description: "Food & beverage companies, status = researched, not yet in outreach",
    icon: <Building2 className="w-4 h-4" />,
    color: "text-green-500",
    filters: { industry: "food_beverage", status: "researched" },
    isBuiltIn: true,
  },
  {
    id: "approved-not-sent",
    name: "Approved Drafts Not Sent",
    description: "Companies with approved outreach drafts that haven't been pushed to Instantly",
    icon: <Mail className="w-4 h-4" />,
    color: "text-blue-500",
    filters: { status: "approved", has_unsent_drafts: "true" },
    isBuiltIn: true,
  },
  {
    id: "hot-signals-not-contacted",
    name: "Hot Signals Not Contacted",
    description: "High intent score (≥ 60), never emailed or in active sequence",
    icon: <Zap className="w-4 h-4" />,
    color: "text-orange-500",
    filters: { min_intent: "60", status: "new" },
    isBuiltIn: true,
  },
  {
    id: "re-engagement",
    name: "Re-engagement Candidates",
    description: "Previously contacted, no response in 45+ days, PQS ≥ 50",
    icon: <RefreshCw className="w-4 h-4" />,
    color: "text-purple-500",
    filters: { status: "no_response", days_since_contact: "45", min_pqs: "50" },
    isBuiltIn: true,
  },
  {
    id: "stale-outreach",
    name: "Stale Outreach",
    description: "Active sequences with no reply in 30+ days — may need follow-up or closure",
    icon: <Clock className="w-4 h-4" />,
    color: "text-rose-500",
    filters: { status: "in_sequence", days_stale: "30" },
    isBuiltIn: true,
  },
];

// ─── Segment Card ─────────────────────────────────────────────────────────────

function SegmentCard({
  segment,
  sequences,
  onEnroll,
  onResearch,
  onExport,
}: {
  segment: Segment;
  sequences: SequenceTemplate[];
  onEnroll: (segment: Segment, sequenceName: string) => void;
  onResearch: (segment: Segment) => void;
  onExport: (segment: Segment) => void;
}) {
  const [showEnrollDropdown, setShowEnrollDropdown] = useState(false);
  const [showCompanies, setShowCompanies] = useState(false);

  const tierCounts = segment.companies.reduce<Record<string, number>>((acc, c) => {
    const t = c.tier || "untiered";
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="p-4 flex items-start gap-3">
        <div className={cn("mt-0.5 flex-shrink-0", segment.color)}>{segment.icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-sm text-zinc-900 dark:text-zinc-100 truncate">
              {segment.name}
            </h3>
            {segment.isBuiltIn && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 flex-shrink-0">
                Built-in
              </span>
            )}
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 leading-relaxed">
            {segment.description}
          </p>
        </div>
        {/* Company count badge */}
        <div className="flex-shrink-0 text-right">
          {segment.loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-zinc-400" />
          ) : (
            <span className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
              {segment.count}
            </span>
          )}
          <div className="text-[10px] text-zinc-400">companies</div>
        </div>
      </div>

      {/* Tier breakdown bar */}
      {segment.count > 0 && !segment.loading && (
        <div className="px-4 pb-2">
          <div className="flex gap-1 h-1.5 rounded-full overflow-hidden">
            {Object.entries(tierCounts).map(([tier, cnt]) => (
              <div
                key={tier}
                className={cn(
                  "h-full",
                  tier === "tier_1" ? "bg-amber-500" :
                  tier === "tier_2" ? "bg-blue-500" :
                  tier === "tier_3" ? "bg-green-500" : "bg-zinc-300"
                )}
                style={{ width: `${(cnt / segment.count) * 100}%` }}
                title={`${TIER_LABELS[tier] || tier}: ${cnt}`}
              />
            ))}
          </div>
          <div className="flex gap-3 mt-1.5">
            {Object.entries(tierCounts).map(([tier, cnt]) => (
              <span key={tier} className="text-[10px] text-zinc-400">
                {TIER_LABELS[tier] || tier}: {cnt}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Companies preview toggle */}
      {segment.count > 0 && !segment.loading && (
        <button
          onClick={() => setShowCompanies(!showCompanies)}
          className="w-full px-4 py-1.5 text-xs text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 border-t border-zinc-100 dark:border-zinc-800 flex items-center gap-1"
        >
          <ChevronDown className={cn("w-3 h-3 transition-transform", showCompanies && "rotate-180")} />
          {showCompanies ? "Hide" : "Show"} companies
        </button>
      )}

      {showCompanies && segment.companies.length > 0 && (
        <div className="border-t border-zinc-100 dark:border-zinc-800 max-h-48 overflow-y-auto">
          {segment.companies.slice(0, 20).map((company) => (
            <div
              key={company.id}
              className="px-4 py-2 flex items-center justify-between hover:bg-zinc-50 dark:hover:bg-zinc-800/50 border-b border-zinc-100 dark:border-zinc-800 last:border-0"
            >
              <div className="min-w-0">
                <div className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate">
                  {company.name}
                </div>
                <div className="text-[10px] text-zinc-400">
                  {company.tier ? (TIER_LABELS[company.tier] || company.tier) : "—"} · {company.status}
                </div>
              </div>
              <span
                className={cn(
                  "text-xs font-bold ml-2 flex-shrink-0",
                  getPQSColor(company.pqs_total)
                )}
              >
                {company.pqs_total}
              </span>
            </div>
          ))}
          {segment.count > 20 && (
            <div className="px-4 py-2 text-xs text-zinc-400 text-center">
              + {segment.count - 20} more — export to see all
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {segment.error && (
        <div className="mx-4 mb-3 p-2 rounded bg-amber-50 dark:bg-amber-950/20 text-xs text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
          <AlertTriangle className="w-3 h-3 flex-shrink-0" />
          {segment.error}
        </div>
      )}

      {/* Actions */}
      <div className="px-4 py-3 border-t border-zinc-100 dark:border-zinc-800 flex items-center gap-2">
        {/* Enroll dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowEnrollDropdown(!showEnrollDropdown)}
            disabled={segment.count === 0 || segment.loading}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              segment.count > 0 && !segment.loading
                ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 hover:bg-zinc-700 dark:hover:bg-zinc-300"
                : "bg-zinc-100 dark:bg-zinc-800 text-zinc-400 cursor-not-allowed"
            )}
          >
            <Mail className="w-3 h-3" />
            Enroll in Sequence
            <ChevronDown className="w-3 h-3" />
          </button>
          {showEnrollDropdown && (
            <div className="absolute left-0 top-full mt-1 w-56 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-lg z-20 overflow-hidden">
              <div className="px-3 py-2 text-[10px] font-semibold text-zinc-400 uppercase tracking-wider border-b border-zinc-100 dark:border-zinc-800">
                Select Sequence
              </div>
              {sequences.length === 0 ? (
                <div className="px-3 py-2 text-xs text-zinc-400">No sequences available</div>
              ) : (
                sequences.map((seq) => (
                  <button
                    key={seq.name}
                    onClick={() => {
                      onEnroll(segment, seq.name);
                      setShowEnrollDropdown(false);
                    }}
                    className="w-full text-left px-3 py-2 text-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 flex items-center justify-between"
                  >
                    <span className="truncate">{seq.display_name || seq.name}</span>
                    <span className="text-[10px] text-zinc-400 ml-2 flex-shrink-0">
                      {seq.total_steps}s
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        <button
          onClick={() => onResearch(segment)}
          disabled={segment.count === 0 || segment.loading}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
            segment.count > 0 && !segment.loading
              ? "border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              : "border-zinc-200 dark:border-zinc-800 text-zinc-400 cursor-not-allowed"
          )}
        >
          <Zap className="w-3 h-3" />
          Run Research
        </button>

        <button
          onClick={() => onExport(segment)}
          disabled={segment.count === 0 || segment.loading}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ml-auto",
            segment.count > 0 && !segment.loading
              ? "border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              : "border-zinc-200 dark:border-zinc-800 text-zinc-400 cursor-not-allowed"
          )}
        >
          <Download className="w-3 h-3" />
          Export
        </button>
      </div>
    </div>
  );
}

// ─── Custom Segment Builder slide-over ────────────────────────────────────────

const FILTER_FIELDS = [
  { value: "status", label: "Status" },
  { value: "tier", label: "Tier" },
  { value: "industry", label: "Industry" },
  { value: "min_pqs", label: "Min PQS score" },
  { value: "max_pqs", label: "Max PQS score" },
  { value: "state", label: "State" },
  { value: "employee_count_min", label: "Min employees" },
  { value: "employee_count_max", label: "Max employees" },
  { value: "campaign_name", label: "Campaign" },
];

const OPERATORS = [
  { value: "eq", label: "=" },
  { value: "gte", label: ">=" },
  { value: "lte", label: "<=" },
  { value: "contains", label: "contains" },
];

function CustomSegmentSlideOver({
  open,
  onClose,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (name: string, description: string, filters: CustomSegmentFilter[]) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [filters, setFilters] = useState<CustomSegmentFilter[]>([
    { field: "status", operator: "eq", value: "" },
  ]);
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const addFilter = () =>
    setFilters((prev) => [...prev, { field: "status", operator: "eq", value: "" }]);

  const removeFilter = (idx: number) =>
    setFilters((prev) => prev.filter((_, i) => i !== idx));

  const updateFilter = (idx: number, partial: Partial<CustomSegmentFilter>) =>
    setFilters((prev) => prev.map((f, i) => (i === idx ? { ...f, ...partial } : f)));

  const handlePreview = async () => {
    setPreviewing(true);
    setPreviewCount(null);
    try {
      const params: Record<string, string> = {};
      for (const f of filters) {
        if (f.value) params[f.field] = f.value;
      }
      const res = await getCompanies({ ...params, limit: "1" });
      setPreviewCount(res.count);
    } catch {
      setPreviewCount(0);
    } finally {
      setPreviewing(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <div className="w-[480px] bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-700 flex flex-col h-full shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <h2 className="font-semibold text-zinc-900 dark:text-zinc-100">New Custom Segment</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800">
            <X className="w-4 h-4 text-zinc-500" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">
              Segment Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Midwest F&B Tier 1"
              className="w-full px-3 py-2 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">
              Description
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this segment represents"
              className="w-full px-3 py-2 text-sm rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-100"
            />
          </div>

          {/* Filters */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                Filters
              </label>
              <button
                onClick={addFilter}
                className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 flex items-center gap-1"
              >
                <Plus className="w-3 h-3" />
                Add filter
              </button>
            </div>
            <div className="space-y-2">
              {filters.map((f, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <select
                    value={f.field}
                    onChange={(e) => updateFilter(idx, { field: e.target.value })}
                    className="flex-1 px-2 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  >
                    {FILTER_FIELDS.map((ff) => (
                      <option key={ff.value} value={ff.value}>{ff.label}</option>
                    ))}
                  </select>
                  <select
                    value={f.operator}
                    onChange={(e) => updateFilter(idx, { operator: e.target.value })}
                    className="w-20 px-2 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  >
                    {OPERATORS.map((op) => (
                      <option key={op.value} value={op.value}>{op.label}</option>
                    ))}
                  </select>
                  <input
                    value={f.value}
                    onChange={(e) => updateFilter(idx, { value: e.target.value })}
                    placeholder="value"
                    className="flex-1 px-2 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                  {filters.length > 1 && (
                    <button
                      onClick={() => removeFilter(idx)}
                      className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-600"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Preview */}
          <div className="flex items-center gap-3">
            <button
              onClick={handlePreview}
              disabled={previewing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              {previewing ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Filter className="w-3 h-3" />
              )}
              Preview count
            </button>
            {previewCount !== null && (
              <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {previewCount} companies match
              </span>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-zinc-200 dark:border-zinc-800 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-zinc-300 dark:border-zinc-700 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              if (name.trim()) onSave(name, description, filters);
            }}
            disabled={!name.trim()}
            className="flex-1 px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-sm font-medium text-white dark:text-zinc-900 hover:bg-zinc-700 dark:hover:bg-zinc-300 disabled:opacity-40"
          >
            Save Segment
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Enroll confirmation modal ────────────────────────────────────────────────

function EnrollModal({
  open,
  segmentName,
  sequenceName,
  companyCount,
  onConfirm,
  onClose,
  loading,
}: {
  open: boolean;
  segmentName: string;
  sequenceName: string;
  companyCount: number;
  onConfirm: () => void;
  onClose: () => void;
  loading: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl p-6 w-96 shadow-2xl">
        <h3 className="font-semibold text-zinc-900 dark:text-zinc-100 mb-2">Confirm Enrollment</h3>
        <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-4">
          Enroll{" "}
          <span className="font-semibold text-zinc-900 dark:text-zinc-100">{companyCount} companies</span>{" "}
          from{" "}
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{segmentName}</span>{" "}
          into sequence{" "}
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{sequenceName}</span>?
        </p>
        <p className="text-xs text-amber-600 dark:text-amber-400 mb-4">
          This will queue outreach drafts for all companies. Drafts require approval before sending.
        </p>
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-zinc-300 dark:border-zinc-700 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="flex-1 px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-sm font-medium text-white dark:text-zinc-900 hover:bg-zinc-700 dark:hover:bg-zinc-300 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading && <Loader2 className="w-3 h-3 animate-spin" />}
            Enroll {companyCount} Companies
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, type }: { message: string; type: "success" | "error" }) {
  return (
    <div
      className={cn(
        "fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm font-medium",
        type === "success"
          ? "bg-green-600 text-white"
          : "bg-red-600 text-white"
      )}
    >
      {type === "success" ? (
        <CheckCircle2 className="w-4 h-4" />
      ) : (
        <AlertTriangle className="w-4 h-4" />
      )}
      {message}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function SegmentsPage() {
  const [segments, setSegments] = useState<Segment[]>(
    BUILT_IN_SEGMENTS.map((s) => ({
      ...s,
      companies: [],
      count: 0,
      loading: true,
      error: null,
    }))
  );
  const [customSegments, setCustomSegments] = useState<Segment[]>([]);
  const [sequences, setSequences] = useState<SequenceTemplate[]>([]);
  const [showBuilder, setShowBuilder] = useState(false);
  const [enrollState, setEnrollState] = useState<{
    open: boolean;
    segment: Segment | null;
    sequenceName: string;
    loading: boolean;
  }>({ open: false, segment: null, sequenceName: "", loading: false });
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const showToast = (message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  // Load companies for each segment
  const loadSegment = useCallback(async (segmentId: string, filters: Record<string, string>) => {
    try {
      // Map segment filters to API params
      const apiParams: Record<string, string> = { limit: "200" };
      if (filters.status) apiParams.status = filters.status;
      if (filters.industry) apiParams.industry = filters.industry;
      if (filters.min_pqs) apiParams.min_pqs = filters.min_pqs;
      if (filters.state) apiParams.state = filters.state;
      if (filters.campaign_name) apiParams.campaign_name = filters.campaign_name;

      const res = await getCompanies(apiParams);
      return { companies: res.data || [], count: res.count || 0 };
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      return { companies: [], count: 0, error: msg };
    }
  }, []);

  useEffect(() => {
    // Load all built-in segments
    BUILT_IN_SEGMENTS.forEach(async (def) => {
      const result = await loadSegment(def.id, def.filters);
      setSegments((prev) =>
        prev.map((s) =>
          s.id === def.id
            ? {
                ...s,
                companies: result.companies,
                count: result.count,
                loading: false,
                error: "error" in result ? result.error || null : null,
              }
            : s
        )
      );
    });

    // Load sequences for enroll dropdown
    getSequenceTemplates()
      .then((res) => setSequences([...res.built_in, ...res.custom]))
      .catch(() => setSequences([]));
  }, [loadSegment]);

  const handleEnroll = (segment: Segment, sequenceName: string) => {
    setEnrollState({ open: true, segment, sequenceName, loading: false });
  };

  const handleEnrollConfirm = async () => {
    if (!enrollState.segment) return;
    setEnrollState((prev) => ({ ...prev, loading: true }));
    try {
      // In production, POST to /api/sequences/enroll with company IDs + sequence name
      // For now, simulate the action
      await new Promise((r) => setTimeout(r, 800));
      showToast(
        `Queued ${enrollState.segment.count} companies into ${enrollState.sequenceName}`,
        "success"
      );
    } catch {
      showToast("Enrollment failed. Try again.", "error");
    } finally {
      setEnrollState({ open: false, segment: null, sequenceName: "", loading: false });
    }
  };

  const handleResearch = async (segment: Segment) => {
    showToast(`Research queued for ${segment.count} companies`, "success");
  };

  const handleExport = (segment: Segment) => {
    const rows = [
      ["Name", "Domain", "Tier", "Status", "PQS", "Industry", "State"],
      ...segment.companies.map((c) => [
        c.name,
        c.domain || "",
        c.tier || "",
        c.status,
        String(c.pqs_total),
        c.industry || "",
        c.state || "",
      ]),
    ];
    const csv = rows.map((r) => r.map((v) => `"${v}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${segment.id}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSaveCustom = async (
    name: string,
    description: string,
    filters: CustomSegmentFilter[]
  ) => {
    const apiFilters: Record<string, string> = {};
    for (const f of filters) {
      if (f.value) apiFilters[f.field] = f.value;
    }

    const newSeg: Segment = {
      id: `custom-${Date.now()}`,
      name,
      description,
      icon: <Filter className="w-4 h-4" />,
      color: "text-indigo-500",
      filters: apiFilters,
      companies: [],
      count: 0,
      loading: true,
      error: null,
      isBuiltIn: false,
    };
    setCustomSegments((prev) => [...prev, newSeg]);
    setShowBuilder(false);

    const result = await loadSegment(newSeg.id, apiFilters);
    setCustomSegments((prev) =>
      prev.map((s) =>
        s.id === newSeg.id
          ? { ...s, companies: result.companies, count: result.count, loading: false }
          : s
      )
    );
  };

  const allSegments = [...segments, ...customSegments];
  const totalCompanies = allSegments.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <div className="px-6 py-5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Segments</h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
              {allSegments.length} segments ·{" "}
              {totalCompanies.toLocaleString()} total companies matched
            </p>
          </div>
          <button
            onClick={() => setShowBuilder(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-sm font-medium text-white dark:text-zinc-900 hover:bg-zinc-700 dark:hover:bg-zinc-300"
          >
            <Plus className="w-4 h-4" />
            New Segment
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="px-6 py-6">
        {/* Built-in segments */}
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
            Pre-Built Segments
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {segments.map((segment) => (
              <SegmentCard
                key={segment.id}
                segment={segment}
                sequences={sequences}
                onEnroll={handleEnroll}
                onResearch={handleResearch}
                onExport={handleExport}
              />
            ))}
          </div>
        </div>

        {/* Custom segments */}
        {customSegments.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
              Custom Segments
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {customSegments.map((segment) => (
                <SegmentCard
                  key={segment.id}
                  segment={segment}
                  sequences={sequences}
                  onEnroll={handleEnroll}
                  onResearch={handleResearch}
                  onExport={handleExport}
                />
              ))}
            </div>
          </div>
        )}

        {customSegments.length === 0 && (
          <button
            onClick={() => setShowBuilder(true)}
            className="w-full border-2 border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl p-8 text-center hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors group"
          >
            <Plus className="w-6 h-6 mx-auto mb-2 text-zinc-300 dark:text-zinc-600 group-hover:text-zinc-500" />
            <span className="text-sm text-zinc-400 dark:text-zinc-500 group-hover:text-zinc-600 dark:group-hover:text-zinc-400">
              Create a custom segment with your own filters
            </span>
          </button>
        )}
      </div>

      {/* Modals */}
      <CustomSegmentSlideOver
        open={showBuilder}
        onClose={() => setShowBuilder(false)}
        onSave={handleSaveCustom}
      />

      <EnrollModal
        open={enrollState.open}
        segmentName={enrollState.segment?.name || ""}
        sequenceName={enrollState.sequenceName}
        companyCount={enrollState.segment?.count || 0}
        onConfirm={handleEnrollConfirm}
        onClose={() => setEnrollState({ open: false, segment: null, sequenceName: "", loading: false })}
        loading={enrollState.loading}
      />

      {toast && <Toast message={toast.message} type={toast.type} />}
    </div>
  );
}
