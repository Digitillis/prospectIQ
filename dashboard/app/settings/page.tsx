"use client";

/**
 * ICP & Scoring Settings — Configure target market filters and PQS scoring rules
 *
 * Expected actions:
 * Edit ICP criteria, adjust PQS dimension weights, change qualification thresholds
 */


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
import { getAppSettings, saveSettings, getOutreachGuidelines, saveOutreachGuidelines, AppSettings, Sequence, OutreachGuidelines } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tab = "icp" | "scoring" | "sequences" | "outreach";

// ---------------------------------------------------------------------------
// Industry catalog — all NAICS manufacturing sectors available for selection
// ---------------------------------------------------------------------------
const INDUSTRY_CATALOG = [
  // Food & Beverage
  { tier: "fb1", naics_prefix: "311", label: "Food Manufacturing (General)", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb2", naics_prefix: "3116", label: "Meat & Poultry Processing", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb3", naics_prefix: "3115", label: "Dairy Product Manufacturing", apollo_industry: "dairy", category: "Food & Beverage" },
  { tier: "fb4", naics_prefix: "3114", label: "Fruit & Vegetable Preserving", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb5", naics_prefix: "3121", label: "Beverage Manufacturing", apollo_industry: "food & beverages", category: "Food & Beverage" },
  { tier: "fb6", naics_prefix: "3118", label: "Bakeries & Tortilla Manufacturing", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb7", naics_prefix: "3119", label: "Other Food Manufacturing (Snacks, Coffee, Spices)", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb8", naics_prefix: "3113", label: "Sugar & Confectionery", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb9", naics_prefix: "3117", label: "Seafood Processing", apollo_industry: "food production", category: "Food & Beverage" },
  { tier: "fb10", naics_prefix: "3111", label: "Animal Food Manufacturing", apollo_industry: "food production", category: "Food & Beverage" },
  // Discrete Manufacturing
  { tier: "mfg1", naics_prefix: "333", label: "Industrial Machinery & Heavy Equipment", apollo_industry: "machinery", category: "Discrete Manufacturing" },
  { tier: "mfg2", naics_prefix: "332", label: "Metal Fabrication & Precision Machining", apollo_industry: "fabricated metal products", category: "Discrete Manufacturing" },
  { tier: "mfg3", naics_prefix: "336", label: "Automotive Parts & Components", apollo_industry: "automotive", category: "Discrete Manufacturing" },
  { tier: "mfg4", naics_prefix: "3364", label: "Aerospace Components & Parts", apollo_industry: "aviation & aerospace", category: "Discrete Manufacturing" },
  { tier: "mfg5", naics_prefix: "335", label: "Electrical Equipment & Components", apollo_industry: "electrical & electronic manufacturing", category: "Discrete Manufacturing" },
  { tier: "mfg6", naics_prefix: "3372", label: "Office Furniture & Fixtures Manufacturing", apollo_industry: "furniture", category: "Discrete Manufacturing" },
  { tier: "mfg7", naics_prefix: "339", label: "Medical Devices & Instruments", apollo_industry: "medical devices", category: "Discrete Manufacturing" },
  { tier: "mfg8", naics_prefix: "3365", label: "Railroad Rolling Stock", apollo_industry: "railroad manufacture", category: "Discrete Manufacturing" },
  { tier: "mfg9", naics_prefix: "3366", label: "Ship & Boat Building", apollo_industry: "shipbuilding", category: "Discrete Manufacturing" },
  // Process Manufacturing
  { tier: "proc1", naics_prefix: "325", label: "Chemical Manufacturing", apollo_industry: "chemicals", category: "Process Manufacturing" },
  { tier: "proc2", naics_prefix: "3254", label: "Pharmaceutical & Medicine Manufacturing", apollo_industry: "pharmaceuticals", category: "Process Manufacturing" },
  { tier: "proc3", naics_prefix: "326", label: "Plastics & Rubber Products", apollo_industry: "plastics", category: "Process Manufacturing" },
  { tier: "proc4", naics_prefix: "327", label: "Glass, Cement & Concrete Products", apollo_industry: "glass, ceramics & concrete", category: "Process Manufacturing" },
  { tier: "proc5", naics_prefix: "324", label: "Petroleum & Coal Products", apollo_industry: "oil & energy", category: "Process Manufacturing" },
  { tier: "proc6", naics_prefix: "322", label: "Paper & Pulp Manufacturing", apollo_industry: "paper & forest products", category: "Process Manufacturing" },
  { tier: "proc7", naics_prefix: "3251", label: "Basic Chemical Manufacturing", apollo_industry: "chemicals", category: "Process Manufacturing" },
  { tier: "proc8", naics_prefix: "3256", label: "Soap, Cleaning & Cosmetics Manufacturing", apollo_industry: "cosmetics", category: "Process Manufacturing" },
  { tier: "proc9", naics_prefix: "3255", label: "Paint, Coating & Adhesive Manufacturing", apollo_industry: "chemicals", category: "Process Manufacturing" },
  // Electronics & Semiconductor
  { tier: "elec1", naics_prefix: "334", label: "Computer & Electronic Product Manufacturing", apollo_industry: "computer hardware", category: "Electronics" },
  { tier: "elec2", naics_prefix: "3344", label: "Semiconductor & Electronic Component Manufacturing", apollo_industry: "semiconductors", category: "Electronics" },
  { tier: "elec3", naics_prefix: "3341", label: "Computer & Peripheral Equipment", apollo_industry: "computer hardware", category: "Electronics" },
  { tier: "elec4", naics_prefix: "3342", label: "Communications Equipment", apollo_industry: "telecommunications", category: "Electronics" },
  // Metals & Mining
  { tier: "metal1", naics_prefix: "331", label: "Primary Metal Manufacturing (Steel, Aluminum)", apollo_industry: "mining & metals", category: "Metals & Mining" },
  { tier: "metal2", naics_prefix: "3315", label: "Foundries (Iron, Steel, Nonferrous)", apollo_industry: "mining & metals", category: "Metals & Mining" },
  { tier: "metal3", naics_prefix: "3312", label: "Steel Product Manufacturing", apollo_industry: "mining & metals", category: "Metals & Mining" },
  // Textiles & Apparel
  { tier: "text1", naics_prefix: "313", label: "Textile Mills", apollo_industry: "textiles", category: "Textiles & Apparel" },
  { tier: "text2", naics_prefix: "314", label: "Textile Product Mills", apollo_industry: "textiles", category: "Textiles & Apparel" },
  { tier: "text3", naics_prefix: "315", label: "Apparel Manufacturing", apollo_industry: "apparel & fashion", category: "Textiles & Apparel" },
  { tier: "text4", naics_prefix: "316", label: "Leather & Allied Product Manufacturing", apollo_industry: "luxury goods & jewelry", category: "Textiles & Apparel" },
  // Wood & Building Materials
  { tier: "wood1", naics_prefix: "321", label: "Wood Product Manufacturing", apollo_industry: "building materials", category: "Building Materials" },
  { tier: "wood2", naics_prefix: "3371", label: "Household & Institutional Furniture", apollo_industry: "furniture", category: "Building Materials" },
  // Printing & Packaging
  { tier: "print1", naics_prefix: "323", label: "Printing & Related Support Activities", apollo_industry: "printing", category: "Printing & Packaging" },
  { tier: "pkg1", naics_prefix: "3222", label: "Converted Paper & Packaging Products", apollo_industry: "packaging & containers", category: "Printing & Packaging" },
  // Water & Wastewater
  { tier: "water1", naics_prefix: "2213", label: "Water & Wastewater Treatment", apollo_industry: "utilities", category: "Water & Utilities" },
  // Oil & Gas
  { tier: "og1", naics_prefix: "211", label: "Oil & Gas Extraction", apollo_industry: "oil & energy", category: "Oil & Gas" },
  { tier: "og2", naics_prefix: "213", label: "Support Activities for Mining & Oil/Gas", apollo_industry: "oil & energy", category: "Oil & Gas" },
] as const;

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
    { id: "outreach", label: "Outreach Guidelines", icon: MessageSquare },
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
          {activeTab === "outreach" && (
            <OutreachGuidelinesTab />
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

  const [showIndustryPicker, setShowIndustryPicker] = useState(false);
  const [industrySearch, setIndustrySearch] = useState("");

  const addIndustryFromCatalog = (entry: typeof INDUSTRY_CATALOG[number]) => {
    // Skip if already added
    if (icp.industries.some((i) => i.tier === entry.tier)) return;
    onChange({
      ...icp,
      industries: [
        ...icp.industries,
        { tier: entry.tier, label: entry.label, apollo_industry: entry.apollo_industry },
      ],
    });
  };

  const addCustomIndustry = () =>
    onChange({
      ...icp,
      industries: [
        ...icp.industries,
        { tier: `custom_${Date.now()}`, label: "New Industry", apollo_industry: "" },
      ],
    });

  const filteredCatalog = INDUSTRY_CATALOG.filter(
    (entry) =>
      !icp.industries.some((i) => i.tier === entry.tier) &&
      (entry.label.toLowerCase().includes(industrySearch.toLowerCase()) ||
        entry.category.toLowerCase().includes(industrySearch.toLowerCase()) ||
        entry.apollo_industry.toLowerCase().includes(industrySearch.toLowerCase()))
  );

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
            <div className="mt-4 space-y-3">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowIndustryPicker(!showIndustryPicker)}
                  className="flex items-center gap-1.5 rounded-lg border border-digitillis-accent/30 bg-digitillis-accent/5 px-3 py-2 text-xs font-medium text-digitillis-accent hover:bg-digitillis-accent/10"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add from catalog ({INDUSTRY_CATALOG.length} industries)
                </button>
                <button
                  onClick={addCustomIndustry}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 hover:underline"
                >
                  <Plus className="h-3 w-3" />
                  Custom
                </button>
              </div>
              {showIndustryPicker && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <input
                    type="text"
                    value={industrySearch}
                    onChange={(e) => setIndustrySearch(e.target.value)}
                    placeholder="Search industries… (e.g., pharma, plastics, aerospace)"
                    className="mb-3 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent/30"
                  />
                  <div className="max-h-72 overflow-y-auto space-y-1">
                    {filteredCatalog.length === 0 ? (
                      <p className="py-4 text-center text-xs text-gray-400">
                        No matching industries (or all already added)
                      </p>
                    ) : (
                      filteredCatalog.map((entry) => (
                        <button
                          key={entry.tier}
                          onClick={() => addIndustryFromCatalog(entry)}
                          className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm hover:bg-white hover:shadow-sm transition-all"
                        >
                          <div className="min-w-0 flex-1">
                            <span className="font-medium text-gray-800">{entry.label}</span>
                            <span className="ml-2 text-xs text-gray-400">{entry.category}</span>
                          </div>
                          <div className="ml-3 flex items-center gap-2 shrink-0">
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-gray-500">
                              NAICS {entry.naics_prefix}
                            </span>
                            <Plus className="h-3.5 w-3.5 text-digitillis-accent" />
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
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
// Outreach Guidelines Tab (self-contained — has its own fetch/save lifecycle)
// ---------------------------------------------------------------------------

function OutreachGuidelinesTab() {
  const [guidelines, setGuidelines] = useState<OutreachGuidelines | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState<OutreachGuidelines | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const res = await getOutreachGuidelines();
        setGuidelines(res.data);
        setDraft(JSON.parse(JSON.stringify(res.data)));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load guidelines");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const payload: Record<string, unknown> = {
        voice_and_tone: draft.voice_and_tone,
        email_structure: draft.email_structure,
        must_include: draft.must_include,
        never_include: draft.never_include,
        banned_phrases: draft.banned_phrases,
        digitillis_facts: draft.digitillis_facts,
        subject_line_rules: draft.subject_line_rules,
        sender_name: draft.sender.name,
        sender_title: draft.sender.title,
        sender_email: draft.sender.email,
        sender_phone: draft.sender.phone,
        sender_signature: draft.sender.signature,
      };
      const res = await saveOutreachGuidelines(payload);
      setGuidelines(res.data);
      setDraft(JSON.parse(JSON.stringify(res.data)));
      setEditMode(false);
      setSaveMsg("Guidelines saved. Changes apply to the next outreach run.");
      setTimeout(() => setSaveMsg(null), 5000);
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="flex h-40 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-digitillis-accent" /></div>;
  if (error) return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-600">{error}</div>;
  if (!draft) return null;

  const updateField = (field: string, value: unknown) => {
    setDraft((prev) => prev ? { ...prev, [field]: value } : prev);
  };

  const updateSender = (field: string, value: string) => {
    setDraft((prev) => prev ? { ...prev, sender: { ...prev.sender, [field]: value } } : prev);
  };

  const updateList = (field: string, idx: number, value: string) => {
    const list = [...((draft as unknown as Record<string, unknown>)[field] as string[])];
    list[idx] = value;
    updateField(field, list);
  };

  const removeFromList = (field: string, idx: number) => {
    const list = [...((draft as unknown as Record<string, unknown>)[field] as string[])];
    list.splice(idx, 1);
    updateField(field, list);
  };

  const addToList = (field: string) => {
    const list = [...((draft as unknown as Record<string, unknown>)[field] as string[]), ""];
    updateField(field, list);
  };

  return (
    <div className="space-y-6">
      {/* Header with Edit/Save */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-500">
            {editMode
              ? "Edit your outreach guidelines below. Changes apply to the next outreach run."
              : `Version ${draft.version}. Click Edit to refine your outreach voice and rules.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {editMode ? (
            <>
              <button onClick={() => { setDraft(JSON.parse(JSON.stringify(guidelines))); setEditMode(false); }} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"><RotateCcw className="mr-1 inline h-3.5 w-3.5" />Cancel</button>
              <button onClick={handleSave} disabled={saving} className="rounded-lg bg-digitillis-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">{saving ? <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1 inline h-3.5 w-3.5" />}{saving ? "Saving…" : "Save"}</button>
            </>
          ) : (
            <button onClick={() => setEditMode(true)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"><Pencil className="mr-1 inline h-3.5 w-3.5" />Edit</button>
          )}
        </div>
      </div>
      {saveMsg && <div className={cn("rounded-lg border px-4 py-3 text-sm", saveMsg.includes("saved") ? "border-green-200 bg-green-50 text-green-700" : "border-red-200 bg-red-50 text-red-600")}>{saveMsg}</div>}

      {/* Sender Info */}
      <Section icon={Users} title="Sender Identity">
        {editMode ? (
          <div className="space-y-3">
            {[["Name", "name"], ["Title", "title"], ["Email", "email"], ["Phone", "phone"]].map(([label, field]) => (
              <div key={field} className="flex items-center justify-between gap-4 text-sm">
                <span className="text-gray-500 w-20">{label}</span>
                <input type="text" value={(draft.sender as Record<string, string>)[field] || ""} onChange={(e) => updateSender(field, e.target.value)} className="flex-1 rounded border border-gray-200 bg-white px-2 py-1 text-sm text-gray-900 focus:border-digitillis-accent focus:outline-none" />
              </div>
            ))}
            <div>
              <p className="mb-1 text-xs font-medium text-gray-500">Signature Block</p>
              <textarea value={draft.sender.signature} onChange={(e) => updateSender("signature", e.target.value)} rows={6} className="w-full rounded border border-gray-200 bg-white px-3 py-2 text-sm font-mono text-gray-700 focus:border-digitillis-accent focus:outline-none" />
            </div>
          </div>
        ) : (
          <div className="space-y-1 text-sm">
            <KV label="Name" value={draft.sender.name} />
            <KV label="Title" value={draft.sender.title} />
            <KV label="Email" value={draft.sender.email} />
            <KV label="Phone" value={draft.sender.phone} />
            <div className="mt-3">
              <p className="text-xs font-medium text-gray-400 mb-1">Signature Preview</p>
              <pre className="whitespace-pre-wrap rounded bg-gray-50 border border-gray-100 p-3 text-xs text-gray-600 font-mono">{draft.sender.signature}</pre>
            </div>
          </div>
        )}
      </Section>

      {/* Voice & Tone */}
      <Section icon={Target} title="Voice & Tone">
        {editMode ? (
          <textarea value={draft.voice_and_tone} onChange={(e) => updateField("voice_and_tone", e.target.value)} rows={10} className="w-full rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 leading-relaxed focus:border-digitillis-accent focus:outline-none" placeholder="Describe how outreach emails should sound..." />
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{draft.voice_and_tone}</p>
        )}
      </Section>

      {/* Email Structure */}
      <Section icon={Sliders} title="Email Structure">
        {editMode ? (
          <textarea value={draft.email_structure} onChange={(e) => updateField("email_structure", e.target.value)} rows={7} className="w-full rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 leading-relaxed focus:border-digitillis-accent focus:outline-none" />
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{draft.email_structure}</p>
        )}
      </Section>

      {/* Subject Line Rules */}
      <Section icon={Mail} title="Subject Line Rules">
        {editMode ? (
          <textarea value={draft.subject_line_rules} onChange={(e) => updateField("subject_line_rules", e.target.value)} rows={5} className="w-full rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 leading-relaxed focus:border-digitillis-accent focus:outline-none" />
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{draft.subject_line_rules}</p>
        )}
      </Section>

      {/* Must Include / Never Include / Banned Phrases / Digitillis Facts */}
      {[
        { field: "must_include", title: "Must Include (in every email)", icon: Target },
        { field: "never_include", title: "Never Include", icon: Sliders },
        { field: "banned_phrases", title: "Banned Phrases", icon: Sliders },
        { field: "digitillis_facts", title: "Digitillis Facts (agent picks selectively)", icon: Building2 },
      ].map(({ field, title, icon }) => (
        <Section key={field} icon={icon} title={title}>
          <div className="space-y-1">
            {((draft as unknown as Record<string, unknown>)[field] as string[]).map((item, idx) => (
              <div key={idx} className="flex items-center gap-2">
                {editMode ? (
                  <>
                    <input type="text" value={item} onChange={(e) => updateList(field, idx, e.target.value)} className="flex-1 rounded border border-gray-200 bg-white px-2 py-1 text-sm text-gray-700 focus:border-digitillis-accent focus:outline-none" />
                    <button onClick={() => removeFromList(field, idx)} className="text-gray-300 hover:text-red-500"><X className="h-3.5 w-3.5" /></button>
                  </>
                ) : (
                  <span className="text-sm text-gray-700">• {item}</span>
                )}
              </div>
            ))}
            {editMode && (
              <button onClick={() => addToList(field)} className="mt-1 flex items-center gap-1 text-xs text-digitillis-accent hover:underline"><Plus className="h-3 w-3" />Add</button>
            )}
          </div>
        </Section>
      ))}
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
