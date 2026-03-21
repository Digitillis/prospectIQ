"use client";

// Do-Not-Contact list manager
// Uses localStorage to store blocked domains and emails
// The outreach agent should check this before generating drafts

import { useEffect, useState, useRef } from "react";
import { Ban, Plus, Trash2, Download, Upload, AlertTriangle } from "lucide-react";
import { cn, formatDate } from "@/lib/utils";

const DNC_STORAGE_KEY = "prospectiq-dnc-list";

interface DNCEntry {
  value: string;
  type: "domain" | "email";
  addedAt: string;
}

function loadDNC(): DNCEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(DNC_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as DNCEntry[]) : [];
  } catch {
    return [];
  }
}

function saveDNC(entries: DNCEntry[]) {
  localStorage.setItem(DNC_STORAGE_KEY, JSON.stringify(entries));
}

export default function DNCPage() {
  const [entries, setEntries] = useState<DNCEntry[]>([]);
  const [activeTab, setActiveTab] = useState<"domain" | "email">("domain");
  const [inputValue, setInputValue] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load from localStorage on mount
  useEffect(() => {
    setEntries(loadDNC());
  }, []);

  const domainEntries = entries.filter((e) => e.type === "domain");
  const emailEntries = entries.filter((e) => e.type === "email");
  const visibleEntries = activeTab === "domain" ? domainEntries : emailEntries;

  const validate = (value: string, type: "domain" | "email"): string | null => {
    const trimmed = value.trim().toLowerCase();
    if (!trimmed) return "Please enter a value.";
    if (type === "email") {
      if (!trimmed.includes("@") || !trimmed.includes("."))
        return "Enter a valid email address.";
    } else {
      if (trimmed.includes("@")) return "For email addresses, switch to the Email tab.";
      if (!/^[a-z0-9]+([\-\.][a-z0-9]+)*\.[a-z]{2,}$/.test(trimmed))
        return "Enter a valid domain (e.g. acme.com).";
    }
    if (entries.some((e) => e.type === type && e.value === trimmed))
      return "This entry already exists.";
    return null;
  };

  const handleAdd = () => {
    const trimmed = inputValue.trim().toLowerCase();
    const err = validate(trimmed, activeTab);
    if (err) {
      setInputError(err);
      return;
    }
    const newEntry: DNCEntry = { value: trimmed, type: activeTab, addedAt: new Date().toISOString() };
    const updated = [newEntry, ...entries];
    setEntries(updated);
    saveDNC(updated);
    setInputValue("");
    setInputError(null);
  };

  const handleRemove = (value: string, type: "domain" | "email") => {
    const updated = entries.filter((e) => !(e.value === value && e.type === type));
    setEntries(updated);
    saveDNC(updated);
  };

  const handleExport = () => {
    const rows = ["type,value,added_at", ...entries.map((e) => `${e.type},${e.value},${e.addedAt}`)];
    const blob = new Blob([rows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "prospectiq-dnc-list.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target?.result as string;
      const lines = text.split("\n").slice(1); // skip header
      const imported: DNCEntry[] = [];
      for (const line of lines) {
        const [type, value, addedAt] = line.trim().split(",");
        if ((type === "domain" || type === "email") && value) {
          imported.push({ type, value: value.toLowerCase(), addedAt: addedAt || new Date().toISOString() });
        }
      }
      const merged = [...entries];
      for (const entry of imported) {
        if (!merged.some((e) => e.type === entry.type && e.value === entry.value)) {
          merged.push(entry);
        }
      }
      setEntries(merged);
      saveDNC(merged);
    };
    reader.readAsText(file);
    // Reset so the same file can be re-imported
    e.target.value = "";
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Ban className="h-5 w-5 text-red-500" />
            <h2 className="text-2xl font-bold text-gray-900">Do-Not-Contact List</h2>
            <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
              {entries.length} {entries.length === 1 ? "entry" : "entries"}
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Manage suppressed domains and email addresses. The outreach agent will skip these when generating drafts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <Download className="h-4 w-4" />
            Export CSV
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <Upload className="h-4 w-4" />
            Import CSV
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleImport}
          />
        </div>
      </div>

      {/* Notice */}
      <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <p className="text-sm text-amber-800">
          Entries are stored locally in your browser. They are not synced to the server or shared with other users.
          Use Export/Import to back up or transfer your list.
        </p>
      </div>

      {/* Tab bar */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 px-6">
          <nav className="-mb-px flex gap-6">
            {(["domain", "email"] as const).map((tab) => {
              const count = tab === "domain" ? domainEntries.length : emailEntries.length;
              return (
                <button
                  key={tab}
                  onClick={() => { setActiveTab(tab); setInputValue(""); setInputError(null); }}
                  className={cn(
                    "whitespace-nowrap border-b-2 px-1 py-4 text-sm font-medium capitalize transition-colors",
                    activeTab === tab
                      ? "border-red-500 text-red-600"
                      : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                  )}
                >
                  {tab === "domain" ? "Domains" : "Email Addresses"}
                  <span className={cn(
                    "ml-2 rounded-full px-2 py-0.5 text-xs font-medium",
                    activeTab === tab ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-600"
                  )}>
                    {count}
                  </span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="p-6">
          {/* Add form */}
          <div className="flex items-start gap-3 mb-6">
            <div className="flex-1">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => { setInputValue(e.target.value); setInputError(null); }}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                placeholder={activeTab === "domain" ? "acme.com" : "john@acme.com"}
                className={cn(
                  "w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-1",
                  inputError
                    ? "border-red-300 focus:border-red-500 focus:ring-red-500"
                    : "border-gray-300 focus:border-red-500 focus:ring-red-500"
                )}
              />
              {inputError && (
                <p className="mt-1 text-xs text-red-600">{inputError}</p>
              )}
            </div>
            <button
              onClick={handleAdd}
              className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors"
            >
              <Plus className="h-4 w-4" />
              Add {activeTab === "domain" ? "Domain" : "Email"}
            </button>
          </div>

          {/* Entries table */}
          {visibleEntries.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
              <Ban className="h-8 w-8 text-gray-300" />
              <p className="text-sm text-gray-400">
                No {activeTab === "domain" ? "domains" : "email addresses"} suppressed yet.
              </p>
              <p className="text-xs text-gray-400">
                Add {activeTab === "domain" ? "a domain" : "an email"} above to prevent outreach to it.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      {activeTab === "domain" ? "Domain" : "Email Address"}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">Date Added</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visibleEntries.map((entry) => (
                    <tr key={`${entry.type}-${entry.value}`} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <span className="font-medium text-gray-900">{entry.value}</span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">
                        {formatDate(entry.addedAt)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleRemove(entry.value, entry.type)}
                          className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
