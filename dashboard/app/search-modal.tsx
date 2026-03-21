"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Search, Loader2, Building2 } from "lucide-react";
import { getCompanies, type Company } from "@/lib/api";
import { cn, TIER_LABELS, getPQSColor } from "@/lib/utils";

export function SearchModal() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Company[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  // Cmd+K / Ctrl+K listener
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Focus input when opening
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
    }
  }, [open]);

  // Debounced search
  useEffect(() => {
    if (!query.trim() || query.length < 2) {
      setResults([]);
      return;
    }
    const timeout = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await getCompanies({ search: query.trim(), limit: "10" });
        setResults(res.data ?? []);
        setSelectedIndex(0);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(timeout);
  }, [query]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[selectedIndex]) {
      router.push(`/prospects/${results[selectedIndex].id}`);
      setOpen(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
      onClick={() => setOpen(false)}
    >
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40" />

      {/* Modal */}
      <div
        className="relative w-full max-w-lg rounded-xl border border-gray-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-gray-200 px-4 py-3">
          <Search className="h-5 w-5 shrink-0 text-gray-400" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search companies..."
            className="flex-1 text-sm outline-none placeholder:text-gray-400"
          />
          {loading && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />}
          <kbd className="hidden rounded border border-gray-200 px-1.5 py-0.5 text-xs text-gray-400 sm:inline">
            ESC
          </kbd>
        </div>

        {/* Results */}
        {results.length > 0 && (
          <ul className="max-h-80 overflow-y-auto py-2">
            {results.map((company, idx) => (
              <li key={company.id}>
                <button
                  onClick={() => {
                    router.push(`/prospects/${company.id}`);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors",
                    idx === selectedIndex
                      ? "bg-blue-50 text-gray-900"
                      : "text-gray-700 hover:bg-gray-50"
                  )}
                >
                  <Building2 className="h-4 w-4 shrink-0 text-gray-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{company.name}</p>
                    <p className="truncate text-xs text-gray-400">
                      {company.status} · {company.state || "—"} · {company.industry || "—"}
                    </p>
                  </div>
                  {company.tier && (
                    <span className="shrink-0 rounded bg-gray-100 px-2 py-0.5 text-xs">
                      {TIER_LABELS[company.tier] ?? company.tier}
                    </span>
                  )}
                  <span
                    className={cn(
                      "shrink-0 text-sm font-semibold",
                      getPQSColor(company.pqs_total)
                    )}
                  >
                    {company.pqs_total}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* Empty state */}
        {query.length >= 2 && !loading && results.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-gray-400">
            No companies found for &ldquo;{query}&rdquo;
          </div>
        )}

        {/* Footer hint */}
        <div className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">
          <span className="mr-3">↑↓ Navigate</span>
          <span className="mr-3">↵ Open</span>
          <span>ESC Close</span>
        </div>
      </div>
    </div>
  );
}
