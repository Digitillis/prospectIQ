"use client";

import { useEffect, useState, useCallback } from "react";
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
} from "lucide-react";
import { getAppSettings, AppSettings } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tab = "icp" | "scoring";

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("icp");

  const fetchSettings = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getAppSettings();
      setSettings(res.data);
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

  const tabs: { id: Tab; label: string; icon: typeof Target }[] = [
    { id: "icp", label: "Ideal Customer Profile", icon: Target },
    { id: "scoring", label: "PQS Scoring", icon: BarChart3 },
  ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Settings</h2>
        <p className="mt-1 text-sm text-gray-500">
          Current pipeline configuration — edit{" "}
          <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-gray-700">
            config/icp.yaml
          </code>{" "}
          and{" "}
          <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-gray-700">
            config/scoring.yaml
          </code>{" "}
          to change these values.
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-digitillis-accent">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Settings are read from YAML files in the{" "}
          <code className="font-mono text-xs">config/</code> directory. Changes
          take effect on the next agent run without redeploying.
        </span>
      </div>

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
      ) : settings ? (
        <>
          {activeTab === "icp" && <ICPTab icp={settings.icp} />}
          {activeTab === "scoring" && <ScoringTab scoring={settings.scoring} />}
        </>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ICP Tab
// ---------------------------------------------------------------------------

function ICPTab({ icp }: { icp: AppSettings["icp"] }) {
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
          <div className="flex flex-wrap gap-1.5">
            {icp.geography.primary_states.map((s) => (
              <span
                key={s}
                className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-digitillis-accent"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
        <KV
          label="Countries"
          value={icp.geography.countries.join(", ")}
        />
      </Section>

      {/* Financials */}
      <div className="grid gap-6 sm:grid-cols-2">
        <Section icon={DollarSign} title="Revenue Range">
          <KV
            label="Minimum"
            value={`$${(icp.revenue.min / 1_000_000).toFixed(0)}M`}
          />
          <KV
            label="Maximum"
            value={`$${(icp.revenue.max / 1_000_000_000).toFixed(0)}B`}
          />
        </Section>
        <Section icon={Users} title="Employee Count">
          <KV label="Minimum" value={icp.employee_count.min.toLocaleString()} />
          <KV label="Maximum" value={icp.employee_count.max.toLocaleString()} />
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
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {icp.industries.map((ind) => (
                <tr key={ind.tier}>
                  <td className="py-2 pr-4">
                    <span className="rounded bg-digitillis-accent/10 px-2 py-0.5 text-xs font-semibold text-digitillis-accent">
                      Tier {ind.tier}
                    </span>
                  </td>
                  <td className="py-2 pr-4 font-medium text-gray-800">
                    {ind.label}
                  </td>
                  <td className="py-2 text-gray-500">{ind.apollo_industry}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* Contact Titles */}
      <Section icon={Users} title="Target Contact Titles">
        <div className="flex flex-wrap gap-1.5">
          {icp.contact_titles_include.map((t) => (
            <span
              key={t}
              className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600"
            >
              {t}
            </span>
          ))}
        </div>
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
        <KV label="Max results per run" value={String(icp.discovery.max_results_per_run)} />
        <KV label="Pages per tier" value={String(icp.discovery.pages_per_tier)} />
        <KV
          label="Effective max per tier"
          value={`${icp.discovery.pages_per_tier * 100} companies`}
        />
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scoring Tab
// ---------------------------------------------------------------------------

function ScoringTab({ scoring }: { scoring: AppSettings["scoring"] }) {
  const DIMENSION_COLORS: Record<string, string> = {
    firmographic: "bg-digitillis-accent",
    technographic: "bg-purple-500",
    timing: "bg-digitillis-warning",
    engagement: "bg-digitillis-success",
  };

  return (
    <div className="space-y-6">
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
                <span
                  className={cn(
                    "ml-4 shrink-0 rounded-full px-2.5 py-1 text-xs font-bold text-white",
                    DIMENSION_COLORS[dimName] ?? "bg-gray-400"
                  )}
                >
                  +{sig.points}
                </span>
              </div>
            ))}
          </div>
        </Section>
      ))}

      {/* Thresholds */}
      <Section icon={Sliders} title="Qualification Thresholds">
        <p className="mb-3 text-xs text-gray-500">
          Min firmographic score to proceed to research:{" "}
          <strong>{scoring.min_firmographic_for_research}</strong>
        </p>
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
                <span className="text-xs text-gray-500">
                  {threshold.max_score !== undefined
                    ? `≤ ${threshold.max_score} pts`
                    : "no cap"}
                </span>
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
          style={
            accent
              ? { background: "none" }
              : undefined
          }
        />
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        {accent && (
          <span
            className={cn("ml-auto h-2 w-2 rounded-full", accent)}
          />
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

function CheckItem({ label, checked = true }: { label: string; checked?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <CheckCircle2
        className={cn(
          "h-4 w-4 shrink-0",
          checked ? "text-digitillis-success" : "text-gray-300"
        )}
      />
      <span className="text-gray-700">{label}</span>
    </div>
  );
}
