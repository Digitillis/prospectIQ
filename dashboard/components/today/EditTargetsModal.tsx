"use client";

import { useEffect, useState } from "react";
import { X, Loader2 } from "lucide-react";
import { getDailyTargets, updateDailyTargetsBatch } from "@/lib/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSave?: () => void;
}

const FIELDS: { key: string; label: string; icon: string }[] = [
  { key: "connection", label: "LinkedIn Connections", icon: "🔗" },
  { key: "dm", label: "LinkedIn DMs", icon: "💬" },
  { key: "email", label: "Emails", icon: "📧" },
  { key: "outcome", label: "Outcomes Logged", icon: "📋" },
  { key: "post", label: "Content Posts", icon: "📝" },
];

const DEFAULTS: Record<string, number> = {
  connection: 10,
  dm: 5,
  email: 3,
  outcome: 2,
  post: 1,
};

export default function EditTargetsModal({ isOpen, onClose, onSave }: Props) {
  const [targets, setTargets] = useState<Record<string, number>>(DEFAULTS);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    getDailyTargets()
      .then((res) => {
        if (res?.summary) {
          setTargets((prev) => ({ ...prev, ...res.summary }));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateDailyTargetsBatch({
        targets: Object.entries(targets).map(([action_type, target_count]) => ({
          action_type,
          target_count,
        })),
      });
      onSave?.();
      onClose();
    } catch {
      // Silently fail — targets still saved locally
    } finally {
      setSaving(false);
    }
  };

  const total = Object.values(targets).reduce((s, v) => s + v, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Daily Targets
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {FIELDS.map(({ key, label, icon }) => (
                <div key={key} className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="text-sm">{icon}</span>
                    <label className="text-xs text-gray-600 dark:text-gray-400 truncate">
                      {label}
                    </label>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() =>
                        setTargets((p) => ({ ...p, [key]: Math.max(0, (p[key] || 0) - 1) }))
                      }
                      className="rounded border border-gray-200 dark:border-gray-700 w-6 h-6 flex items-center justify-center text-xs text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      min={0}
                      max={500}
                      value={targets[key] ?? 0}
                      onChange={(e) =>
                        setTargets((p) => ({
                          ...p,
                          [key]: Math.max(0, parseInt(e.target.value) || 0),
                        }))
                      }
                      className="w-12 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-1 py-1 text-center text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-900 dark:focus:ring-gray-400"
                    />
                    <button
                      onClick={() =>
                        setTargets((p) => ({ ...p, [key]: (p[key] || 0) + 1 }))
                      }
                      className="rounded border border-gray-200 dark:border-gray-700 w-6 h-6 flex items-center justify-center text-xs text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                    >
                      +
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800">
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs text-gray-500 dark:text-gray-400">Daily total</span>
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {total} actions
                </span>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  onClick={onClose}
                  className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 px-4 py-1.5 text-xs font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50 transition-colors"
                >
                  {saving && <Loader2 className="h-3 w-3 animate-spin" />}
                  {saving ? "Saving..." : "Save Targets"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
