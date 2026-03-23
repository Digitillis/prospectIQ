"use client";

import { useState } from "react";
import { X, Plus, Loader2, ChevronDown } from "lucide-react";
import { requestActions } from "@/lib/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

const ACTION_TYPES = [
  { value: "connection", label: "LinkedIn Connections", icon: "🔗" },
  { value: "dm", label: "LinkedIn DMs", icon: "💬" },
  { value: "email", label: "Email Outreach", icon: "📧" },
  { value: "follow_up", label: "Follow-ups", icon: "🔄" },
  { value: "research", label: "Research Prospects", icon: "🔍" },
] as const;

const PRESETS = [10, 20, 50, 100];

export default function AddActionsModal({ isOpen, onClose, onSuccess }: Props) {
  const [actionType, setActionType] = useState("connection");
  const [count, setCount] = useState(20);
  const [minPqs, setMinPqs] = useState(0);
  const [maxPqs, setMaxPqs] = useState(100);
  const [industries, setIndustries] = useState("");
  const [titleKeywords, setTitleKeywords] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{
    fulfilled: number;
    requested: number;
    preview: { company: string; contact: string; pqs: number }[];
  } | null>(null);
  const [error, setError] = useState("");

  if (!isOpen) return null;

  const handleSubmit = async () => {
    setSaving(true);
    setError("");
    setResult(null);
    try {
      const filters: Record<string, unknown> = {};
      if (minPqs > 0) filters.min_pqs = minPqs;
      if (maxPqs < 100) filters.max_pqs = maxPqs;
      if (industries.trim()) filters.industries = industries.split(",").map((s) => s.trim());
      if (titleKeywords.trim()) filters.title_keywords = titleKeywords.split(",").map((s) => s.trim());

      const res = await requestActions({
        action_type: actionType,
        count,
        filters,
        source_preference: "existing_first",
      });
      setResult({
        fulfilled: res.data.fulfilled,
        requested: res.data.requested,
        preview: res.data.queue_preview || [],
      });
      onSuccess?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to queue actions");
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    setResult(null);
    setError("");
    onClose();
  };

  const selectedType = ACTION_TYPES.find((t) => t.value === actionType);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={handleClose}>
      <div
        className="w-full max-w-md rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Add Actions to Today
          </h2>
          <button
            onClick={handleClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {result ? (
          /* Success state */
          <div className="space-y-4">
            <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-4">
              <p className="text-sm font-medium text-green-800 dark:text-green-200">
                Queued {result.fulfilled} of {result.requested} {selectedType?.label || actionType}
              </p>
              {result.fulfilled < result.requested && (
                <p className="text-xs text-green-600 dark:text-green-400 mt-1">
                  Not enough matching prospects in the database for the full request.
                </p>
              )}
            </div>
            {result.preview.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wider">
                  Top prospects added
                </p>
                <div className="space-y-1.5">
                  {result.preview.map((p, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between rounded-lg bg-gray-50 dark:bg-gray-800 px-3 py-2"
                    >
                      <div>
                        <span className="text-xs font-medium text-gray-900 dark:text-gray-100">
                          {p.contact}
                        </span>
                        <span className="text-xs text-gray-500 dark:text-gray-400 ml-2">
                          {p.company}
                        </span>
                      </div>
                      <span className="text-xs font-mono text-gray-500">PQS {p.pqs}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <button
              onClick={handleClose}
              className="w-full rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 py-2 text-xs font-medium hover:bg-gray-700 dark:hover:bg-gray-300 transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          /* Form state */
          <div className="space-y-4">
            {/* Action type selector */}
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                Action type
              </label>
              <div className="grid grid-cols-2 gap-1.5">
                {ACTION_TYPES.map((t) => (
                  <button
                    key={t.value}
                    onClick={() => setActionType(t.value)}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                      actionType === t.value
                        ? "border-gray-900 dark:border-gray-100 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                        : "border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                    }`}
                  >
                    <span>{t.icon}</span>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Count selector */}
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                How many?
              </label>
              <div className="flex items-center gap-2">
                {PRESETS.map((n) => (
                  <button
                    key={n}
                    onClick={() => setCount(n)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      count === n
                        ? "border-gray-900 dark:border-gray-100 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                        : "border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                    }`}
                  >
                    {n}
                  </button>
                ))}
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={count}
                  onChange={(e) => setCount(Math.max(1, Math.min(500, parseInt(e.target.value) || 1)))}
                  className="w-16 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-2 py-1.5 text-center text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-400"
                />
              </div>
            </div>

            {/* Filters toggle */}
            <button
              onClick={() => setShowFilters(!showFilters)}
              className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
            >
              <ChevronDown
                className={`h-3 w-3 transition-transform ${showFilters ? "rotate-180" : ""}`}
              />
              {showFilters ? "Hide" : "Show"} filters
            </button>

            {showFilters && (
              <div className="space-y-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 p-3">
                <div className="flex gap-3">
                  <div className="flex-1">
                    <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                      Min PQS
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={minPqs}
                      onChange={(e) => setMinPqs(parseInt(e.target.value) || 0)}
                      className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-900"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                      Max PQS
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={maxPqs}
                      onChange={(e) => setMaxPqs(parseInt(e.target.value) || 100)}
                      className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-900"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                    Industries (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={industries}
                    onChange={(e) => setIndustries(e.target.value)}
                    placeholder="Food Manufacturing, Chemicals..."
                    className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-900"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                    Title keywords (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={titleKeywords}
                    onChange={(e) => setTitleKeywords(e.target.value)}
                    placeholder="VP, Director, Head of..."
                    className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-xs text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-gray-900"
                  />
                </div>
              </div>
            )}

            {error && (
              <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2">
                <p className="text-xs text-red-700 dark:text-red-300">{error}</p>
              </div>
            )}

            {/* Submit */}
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={handleClose}
                className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 px-4 py-1.5 text-xs font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50 transition-colors"
              >
                {saving ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Plus className="h-3 w-3" />
                )}
                {saving ? "Queuing..." : `Add ${count} ${selectedType?.label || "actions"}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
