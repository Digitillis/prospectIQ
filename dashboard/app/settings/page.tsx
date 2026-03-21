"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Target,
  MapPin,
  DollarSign,
  Users,
  Building2,
  BarChart3,
  Sliders,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Info,
  Mail,
  Linkedin,
  Phone,
  MessageSquare,
  Pencil,
  X,
  Plus,
  Save,
  RotateCcw,
} from "lucide-react";
import { getAppSettings, saveSettings, AppSettings, Sequence } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tab = "icp" | "scoring" | "sequences";

// Deep clone helper
function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("icp");
  const [editMode, setEditMode] = useState(false);
  const successTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchSettings = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getAppSettings();
      setSettings(res.data);
      setDraft(deepClone(res.data));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleEdit = () => {
    if (settings) setDraft(deepClone(settings));
    setEditMode(true);
    setSaveError(null);
    setSaveSuccess(false);
  };

  const handleCancel = () => {
    if (settings) setDraft(deepClone(settings));
    setEditMode(false);
    setSaveError(null);
  };

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      // Build the PATCH payload from draft
      const payload: Record<string, unknown> = {
        icp: {
          revenue: draft.icp.revenue,
          employee_count: draft.icp.employee_count,
          geography: draft.icp.geography,
          industries: draft.icp.industries,
          contact_titles_include: draft.icp.contact_titles_include,
          discovery: draft.icp.discovery,
        },
        scoring: {
          min_firmographic_for_research: draft.scoring.min_firmographic_for_research,
          dimensions: Object.fromEntries(
            Object.entries(draft.scoring.dimensions).map(([dimName, dim]) => [
              dimName,
              {
                signals: Object.fromEntries(
                  Object.entries(dim.signals).map(([sigName, sig]) => [
                    sigName,
                    { points: sig.points },
                  ])
                ),
              },
            ])
          ),
          thresholds: Object.fromEntries(
            Object.entries(draft.scoring.thresholds).map(([name, thr]) => [
              name,
              { max_score: thr.max_score },
            ])
          ),
        },
      };
      const res = await saveSettings(payload);
      setSettings(res.data);
      setDraft(deepClone(res.data));
      setEditMode(false);
      setSaveSuccess(true);
      if (successTimer.current) clearTimeout(successTimer.current);
      successTimer.current = setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const tabs: { id: Tab; label: string; icon: typeof Target }[] = [
    { id: "icp", label: "Ideal Customer Profile", icon: Target },
    { id: "scoring", label: "PQS Scoring", icon: BarChart3 },
    { id: "sequences", label: "Sequences", icon: Mail },
  ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Settings</h2>
          <p className="mt-1 text-sm text-gray-500">
            {editMode
              ? "Edit mode — changes will be written to the YAML config files on save."
              : "Current pipeline configuration. Click Edit to modify ICP criteria, scoring, and discovery settings."}
          </p>
        </div>
        {!loading && !error && settings && activeTab !== "sequences" && (
          <div className="flex items-center gap-2 shrink-0">
            {editMode ? (
              <>
                <button
                  onClick={handleCancel}
                  disabled={saving}
                  className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 shadow-sm hover:bg-gray-50 disabled:opacity-50"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-1.5 rounded-lg bg-digitillis-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 disabled:opacity-60"
                >
                  {saving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  {saving ? "Saving…" : "Save Changes"}
                </button>
              </>
            ) : (
              <button
                onClick={handleEdit}
                className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
              >
                <Pencil className="h-3.5 w-3.5" />
                Edit
              </button>
            )}
          </div>
        )}
      </div>

      {/* Save success */}
      {saveSuccess && (
        <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-digitillis-success">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Settings saved successfully. Changes will take effect on the next agent run.
        </div>
      )}

      {/* Save error */}
      {saveError && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-digitillis-danger">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{saveError}</span>
        </div>
      )}

      {/* Edit mode banner */}
      {editMode && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          <Pencil className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            You are in <strong>edit mode</strong>. Modify values below and click{" "}
            <strong>Save Changes</strong> to persist. Changes are written directly to{" "}
            <code className="font-mono text-xs">config/icp.yaml</code> and{" "}
            <code className="font-mono text-xs">config/scoring.yaml</code>.
          </span>
        </div>
      )}

      {/* Info banner (read-only) */}
      {!editMode && (
        <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-digitillis-accent">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Settings are read from YAML files in the{" "}
            <code className="font-mono text-xs">config/</code> directory. Changes
            take effect on the next agent run without redeploying.
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-100 p-1">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              activeTab === id
                ? "bg-white text-digitillis-accent shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex h-64 items-center justify-center rounded-xl border border-gray-200 bg-white">
          <Loader2 className="h-6 w-6 animate-spin text-digitillis-accent" />
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-digitillis-danger">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      ) : draft ? (
        <>
          {activeTab === "icp" && (
            <ICPTab
              icp={draft.icp}
              editMode={editMode}
              onChange={(updated) =>
                setDraft((prev) => prev ? { ...prev, icp: updated } : prev)
              }
            />
          )}
          {activeTab === "scoring" && (
            <ScoringTab
              scoring={draft.scoring}
              editMode={editMode}
              onChange={(updated) =>
                setDraft((prev) => prev ? { ...prev, scoring: updated } : prev)
              }
            />
          )}
          {activeTab === "sequences" && (
            <SequencesTab sequences={draft.sequences ?? {}} />
          )}
        </>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ICP Tab
// ---------------------------------------------------------------------------

function ICPTab({
  icp,
  editMode,
  onChange,
}: {
  icp: AppSettings["icp"];
  editMode: boolean;
  onChange: (updated: AppSettings["icp"]) => void;
}) {
  // Chips helpers
  const removeState = (s: string) =>
    onChange({
      ...icp,
      geography: {
        ...icp.geography,
        primary_states: icp.geography.primary_states.filter((x) => x !== s),
      },
    });

  const addState = (s: string) => {
    const trimmed = s.trim();
    if (!trimmed || icp.geography.primary_states.includes(trimmed)) return;
    onChange({
      ...icp,
      geography: {
        ...icp.geography,
        primary_states: [...icp.geography.primary_states, trimmed],
      },
    });
  };

  const removeTitle = (t: string) =>
    onChange({
      ...icp,
      contact_titles_include: icp.contact_titles_include.filter((x) => x !== t),
    });

  const addTitle = (t: string) => {
    const trimmed = t.trim();
    if (!trimmed || icp.contact_titles_include.includes(trimmed)) return;
    onChange({
      ...icp,
      contact_titles_include: [...icp.contact_titles_include, trimmed],
    });
  };

  const updateIndustry = (
    idx: number,
    field: "label" | "apollo_industry",
    value: string
  ) => {
    const updated = icp.industries.map((ind, i) =>
      i === idx ? { ...ind, [field]: value } : ind
    );
    onChange({ ...icp, industries: updated });
  };

  const removeIndustry = (idx: number) =>
    onChange({ ...icp, industries: icp.industries.filter((_, i) => i !== idx) });

  const addIndustry = () =>
    onChange({
      ...icp,
      industries: [
        ...icp.industries,
        { tier: `custom_${Date.now()}`, label: "New Industry", apollo_industry: "" },
      ],
    });

  return (
    <div className="space-y-6">
      {/* Target Market */}
      <Section icon={Target} title="Target Market">
        <KV label="Name" value={icp.target_market.name} />
        <KV label="Description" value={icp.target_market.description} />
      </Section>

      {/* Geography */}
      <Section icon={MapPin} title="Geography">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
            Primary States
          </p>
          <ChipList
            items={icp.geography.primary_states}
            editMode={editMode}
            onRemove={removeState}
            onAdd={addState}
            addPlaceholder="Add state…"
            chipClass="bg-blue-50 text-digitillis-accent"
          />
        </div>
        <KV label="Countries" value={icp.geography.countries.join(", ")} />
      </Section>

      {/* Financials */}
      <div className="grid gap-6 sm:grid-cols-2">
        <Section icon={DollarSign} title="Revenue Range">
          {editMode ? (
            <div className="space-y-3">
              <NumberField
                label="Minimum ($)"
                value={icp.revenue.min}
                onChange={(v) => onChange({ ...icp, revenue: { ...icp.revenue, min: v } })}
              />
              <NumberField
                label="Maximum ($)"
                value={icp.revenue.max}
                onChange={(v) => onChange({ ...icp, revenue: { ...icp.revenue, max: v } })}
              />
            </div>
          ) : (
            <>
              <KV
                label="Minimum"
                value={`$${(icp.revenue.min / 1_000_000).toFixed(0)}M`}
              />
              <KV
                label="Maximum"
                value={`$${(icp.revenue.max / 1_000_000).toFixed(0)}M`}
              />
            </>
          )}
        </Section>
        <Section icon={Users} title="Employee Count">
          {editMode ? (
            <div className="space-y-3">
              <NumberField
                label="Minimum"
                value={icp.employee_count.min}
                onChange={(v) =>
                  onChange({ ...icp, employee_count: { ...icp.employee_count, min: v } })
                }
              />
              <NumberField
                label="Maximum"
                value={icp.employee_count.max}
                onChange={(v) =>
                  onChange({ ...icp, employee_count: { ...icp.employee_count, max: v } })
                }
              />
            </div>
          ) : (
            <>
              <KV label="Minimum" value={icp.employee_count.min.toLocaleString()} />
              <KV label="Maximum" value={icp.employee_count.max.toLocaleString()} />
            </>
          )}
        </Section>
      </div>

      {/* Industries */}
      <Section icon={Building2} title="Target Industries">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs font-medium uppercase tracking-wider text-gray-400">
                <th className="pb-2 pr-4 text-left">Tier</th>
                <th className="pb-2 pr-4 text-left">Label</th>
                <th className="pb-2 text-left">Apollo Industry</th>
                {editMode && <th className="pb-2 pl-2 w-8" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {icp.industries.map((ind, idx) => (
                <tr key={ind.tier}>
                  <td className="py-2 pr-4">
                    <span className="rounded bg-digitillis-accent/10 px-2 py-0.5 text-xs font-semibold text-digitillis-accent">
                      {ind.tier}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    {editMode ? (
                      <input
                        type="text"
                        value={ind.label}
                        onChange={(e) => updateIndustry(idx, "label", e.target.value)}
                        className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-sm text-gray-800 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent/30"
                      />
                    ) : (
                      <span className="font-medium text-gray-800">{ind.label}</span>
                    )}
                  </td>
                  <td className="py-2">
                    {editMode ? (
                      <input
                        type="text"
                        value={ind.apollo_industry}
                        onChange={(e) => updateIndustry(idx, "apollo_industry", e.target.value)}
                        className="w-full rounded border border-gray-200 bg-white px-2 py-1 text-sm text-gray-500 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent/30"
                      />
                    ) : (
                      <span className="text-gray-500">{ind.apollo_industry}</span>
                    )}
                  </td>
                  {editMode && (
                    <td className="py-2 pl-2">
                      <button
                        onClick={() => removeIndustry(idx)}
                        className="rounded p-1 text-gray-300 hover:bg-red-50 hover:text-digitillis-danger"
                        title="Remove industry"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {editMode && (
            <button
              onClick={addIndustry}
              className="mt-2 flex items-center gap-1 text-xs text-digitillis-accent hover:underline"
            >
              <Plus className="h-3.5 w-3.5" />
              Add industry
            </button>
          )}
        </div>
      </Section>

      {/* Contact Titles */}
      <Section icon={Users} title="Target Contact Titles">
        <ChipList
          items={icp.contact_titles_include}
          editMode={editMode}
          onRemove={removeTitle}
          onAdd={addTitle}
          addPlaceholder="Add title…"
          chipClass="bg-gray-100 text-gray-600"
        />
        <div className="mt-3 flex items-center gap-2">
          <p className="text-xs font-medium text-gray-500">Seniority filters:</p>
          {icp.seniority.map((s) => (
            <span
              key={s}
              className="rounded bg-green-50 px-2 py-0.5 text-xs font-medium text-digitillis-success"
            >
              {s}
            </span>
          ))}
        </div>
      </Section>

      {/* Discovery Settings */}
      <Section icon={Sliders} title="Discovery Settings">
        {editMode ? (
          <div className="space-y-3">
            <NumberField
              label="Max results per run"
              value={icp.discovery.max_results_per_run}
              onChange={(v) =>
                onChange({ ...icp, discovery: { ...icp.discovery, max_results_per_run: v } })
              }
              min={1}
              max={10000}
            />
            <NumberField
              label="Pages per tier"
              value={icp.discovery.pages_per_tier}
              onChange={(v) =>
                onChange({ ...icp, discovery: { ...icp.discovery, pages_per_tier: v } })
              }
              min={1}
              max={100}
            />
            <KV
              label="Effective max per tier"
              value={`${icp.discovery.pages_per_tier * 100} companies`}
            />
          </div>
        ) : (
          <>
            <KV label="Max results per run" value={String(icp.discovery.max_results_per_run)} />
            <KV label="Pages per tier" value={String(icp.discovery.pages_per_tier)} />
            <KV
              label="Effective max per tier"
              value={`${icp.discovery.pages_per_tier * 100} companies`}
            />
          </>
        )}
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scoring Tab
// ---------------------------------------------------------------------------

function ScoringTab({
  scoring,
  editMode,
  onChange,
}: {
  scoring: AppSettings["scoring"];
  editMode: boolean;
  onChange: (updated: AppSettings["scoring"]) => void;
}) {
  const DIMENSION_COLORS: Record<string, string> = {
    firmographic: "bg-digitillis-accent",
    technographic: "bg-purple-500",
    timing: "bg-digitillis-warning",
    engagement: "bg-digitillis-success",
  };

  const updateSignalPoints = (dimName: string, sigName: string, points: number) => {
    onChange({
      ...scoring,
      dimensions: {
        ...scoring.dimensions,
        [dimName]: {
          ...scoring.dimensions[dimName],
          signals: {
            ...scoring.dimensions[dimName].signals,
            [sigName]: {
              ...scoring.dimensions[dimName].signals[sigName],
              points,
            },
          },
        },
      },
    });
  };

  const updateThresholdMax = (name: string, max_score: number) => {
    onChange({
      ...scoring,
      thresholds: {
        ...scoring.thresholds,
        [name]: { ...scoring.thresholds[name], max_score },
      },
    });
  };

  return (
    <div className="space-y-6">
      {/* Min firmographic */}
      {editMode && (
        <Section icon={Sliders} title="Pre-filter Threshold">
          <NumberField
            label="Min firmographic score to proceed to research"
            value={scoring.min_firmographic_for_research}
            onChange={(v) => onChange({ ...scoring, min_firmographic_for_research: v })}
            min={0}
            max={25}
          />
        </Section>
      )}

      {/* PQS Dimensions */}
      {Object.entries(scoring.dimensions).map(([dimName, dim]) => (
        <Section
          key={dimName}
          icon={BarChart3}
          title={`${dimName.charAt(0).toUpperCase() + dimName.slice(1)} (max ${dim.max_points} pts)`}
          accent={DIMENSION_COLORS[dimName]}
        >
          <div className="space-y-2">
            {Object.entries(dim.signals).map(([sigName, sig]) => (
              <div
                key={sigName}
                className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-800">
                    {sig.description || sigName.replace(/_/g, " ")}
                  </p>
                  <p className="mt-0.5 text-xs text-gray-400 capitalize">
                    {sig.evaluation.replace(/_/g, " ")}
                  </p>
                </div>
                <div className="ml-4 shrink-0">
                  {editMode ? (
                    <input
                      type="number"
                      min={0}
                      max={25}
                      value={sig.points}
                      onChange={(e) =>
                        updateSignalPoints(dimName, sigName, parseInt(e.target.value, 10) || 0)
                      }
                      className={cn(
                        "w-16 rounded-full px-2 py-1 text-center text-xs font-bold text-white focus:outline-none focus:ring-2 focus:ring-white/50",
                        DIMENSION_COLORS[dimName] ?? "bg-gray-400"
                      )}
                    />
                  ) : (
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-1 text-xs font-bold text-white",
                        DIMENSION_COLORS[dimName] ?? "bg-gray-400"
                      )}
                    >
                      +{sig.points}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ))}

      {/* Thresholds */}
      <Section icon={Sliders} title="Qualification Thresholds">
        {!editMode && (
          <p className="mb-3 text-xs text-gray-500">
            Min firmographic score to proceed to research:{" "}
            <strong>{scoring.min_firmographic_for_research}</strong>
          </p>
        )}
        <div className="space-y-2">
          {Object.entries(scoring.thresholds).map(([name, threshold]) => {
            const COLOR_MAP: Record<string, string> = {
              unqualified: "bg-digitillis-danger",
              research_needed: "bg-digitillis-warning",
              qualified: "bg-digitillis-accent",
              high_priority: "bg-digitillis-success",
              hot_prospect: "bg-purple-500",
            };
            return (
              <div
                key={name}
                className="flex items-center gap-4 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3"
              >
                <span
                  className={cn(
                    "w-3 h-3 shrink-0 rounded-full",
                    COLOR_MAP[name] ?? "bg-gray-400"
                  )}
                />
                <p className="flex-1 text-sm font-medium capitalize text-gray-800">
                  {name.replace(/_/g, " ")}
                </p>
                {editMode && threshold.max_score !== undefined ? (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-400">≤</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={threshold.max_score}
                      onChange={(e) =>
                        updateThresholdMax(name, parseInt(e.target.value, 10) || 0)
                      }
                      className="w-16 rounded border border-gray-200 bg-white px-2 py-1 text-center text-xs font-medium text-gray-700 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent/30"
                    />
                    <span className="text-xs text-gray-400">pts</span>
                  </div>
                ) : (
                  <span className="text-xs text-gray-500">
                    {threshold.max_score !== undefined
                      ? `≤ ${threshold.max_score} pts`
                      : "no cap"}
                  </span>
                )}
                {threshold.new_status && (
                  <span className="rounded bg-gray-200 px-2 py-0.5 text-xs text-gray-600">
                    → {threshold.new_status}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sequences Tab (read-only)
// ---------------------------------------------------------------------------

const CHANNEL_ICON: Record<string, typeof Mail> = {
  email: Mail,
  linkedin: Linkedin,
  phone: Phone,
};

const CHANNEL_COLOR: Record<string, string> = {
  email: "bg-blue-100 text-digitillis-accent",
  linkedin: "bg-sky-100 text-sky-700",
  phone: "bg-green-100 text-digitillis-success",
};

function SequencesTab({ sequences }: { sequences: Record<string, Sequence> }) {
  const entries = Object.entries(sequences);

  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        No sequences configured. Add sequences to{" "}
        <code className="font-mono text-xs">config/sequences.yaml</code>.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
        <span>
          Sequences are read-only in the UI. Edit{" "}
          <code className="font-mono text-xs">config/sequences.yaml</code> directly to
          modify steps, delays, and templates.
        </span>
      </div>
      {entries.map(([key, seq]) => (
        <div key={key} className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="mb-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-base font-semibold text-gray-900">{seq.name}</h3>
                <p className="mt-0.5 text-sm text-gray-500">{seq.description}</p>
              </div>
              <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                {seq.total_steps} step{seq.total_steps !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
          <div className="relative space-y-0">
            {(seq.steps ?? []).map((step, idx) => {
              const Icon = CHANNEL_ICON[step.channel] ?? MessageSquare;
              const isLast = idx === (seq.steps ?? []).length - 1;
              return (
                <div key={step.step} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <div
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                        CHANNEL_COLOR[step.channel] ?? "bg-gray-100 text-gray-600"
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    {!isLast && (
                      <div className="mt-1 w-px flex-1 bg-gray-200" style={{ minHeight: "1.5rem" }} />
                    )}
                  </div>
                  <div className={cn("pb-5 min-w-0 flex-1", isLast && "pb-0")}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-gray-900 capitalize">
                        Step {step.step} — {step.channel}
                      </span>
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                        Day {step.delay_days}
                      </span>
                      <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-gray-500">
                        {step.template}
                      </code>
                    </div>
                    {step.instructions && (
                      <div className="mt-2 space-y-1">
                        {(step.instructions.body_approach as string | undefined) && (
                          <p className="text-xs text-gray-500 leading-relaxed">
                            {step.instructions.body_approach as string}
                          </p>
                        )}
                        {(step.instructions.approach as string | undefined) && (
                          <p className="text-xs text-gray-500 leading-relaxed">
                            {step.instructions.approach as string}
                          </p>
                        )}
                        {(step.instructions.tone as string | undefined) && (
                          <p className="mt-1 text-xs font-medium text-gray-400">
                            Tone: {step.instructions.tone as string}
                          </p>
                        )}
                        {(step.instructions.max_words as number | undefined) && (
                          <p className="text-xs text-gray-400">
                            Max {step.instructions.max_words as number} words
                          </p>
                        )}
                        {(step.instructions.note as string | undefined) && (
                          <p className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
                            {step.instructions.note as string}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function Section({
  icon: Icon,
  title,
  children,
  accent,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <Icon
          className={cn(
            "h-5 w-5",
            accent ? "text-white" : "text-digitillis-accent"
          )}
        />
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        {accent && (
          <span className={cn("ml-auto h-2 w-2 rounded-full", accent)} />
        )}
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">{value}</span>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-gray-500">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-32 rounded border border-gray-200 bg-white px-2 py-1 text-right text-sm font-medium text-gray-900 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent/30"
      />
    </div>
  );
}

function ChipList({
  items,
  editMode,
  onRemove,
  onAdd,
  addPlaceholder,
  chipClass,
}: {
  items: string[];
  editMode: boolean;
  onRemove: (item: string) => void;
  onAdd: (item: string) => void;
  addPlaceholder: string;
  chipClass: string;
}) {
  const [inputVal, setInputVal] = useState("");

  const commit = () => {
    if (inputVal.trim()) {
      onAdd(inputVal.trim());
      setInputVal("");
    }
  };

  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className={cn(
              "flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
              chipClass
            )}
          >
            {item}
            {editMode && (
              <button
                onClick={() => onRemove(item)}
                className="ml-0.5 rounded-full p-0.5 hover:bg-black/10"
                title={`Remove ${item}`}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            )}
          </span>
        ))}
      </div>
      {editMode && (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="text"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); commit(); }
            }}
            placeholder={addPlaceholder}
            className="flex-1 rounded border border-dashed border-gray-300 bg-white px-2.5 py-1 text-xs text-gray-600 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none"
          />
          <button
            onClick={commit}
            className="flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
          >
            <Plus className="h-3 w-3" />
            Add
          </button>
        </div>
      )}
    </div>
  );
}
