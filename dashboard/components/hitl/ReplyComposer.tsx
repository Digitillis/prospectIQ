"use client";

/**
 * ReplyComposer — AI-assisted reply drafting modal for HITL queue items.
 *
 * Fetches a Claude-drafted suggestion, allows editing, and provides a
 * "Copy to Clipboard" action (or "Send via Instantly" when SEND_ENABLED).
 */

import { useState, useEffect } from "react";
import {
  X, Loader2, Copy, Check, RefreshCw, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { suggestHitlResponse } from "@/lib/api";

interface ReplyComposerProps {
  hitlId: string;
  contactName?: string;
  companyName?: string;
  inboundSubject?: string;
  onClose: () => void;
  onSend?: (subject: string, body: string) => void;
}

type Tone = "professional" | "warm" | "direct";

const TONE_LABELS: Record<Tone, string> = {
  professional: "Professional",
  warm: "Warm",
  direct: "Direct",
};

export function ReplyComposer({
  hitlId,
  contactName,
  companyName,
  inboundSubject,
  onClose,
  onSend,
}: ReplyComposerProps) {
  const [subject, setSubject] = useState(
    inboundSubject ? `Re: ${inboundSubject.replace(/^Re:\s*/i, "")}` : ""
  );
  const [body, setBody] = useState("");
  const [toneNotes, setToneNotes] = useState("");
  const [tone, setTone] = useState<Tone>("professional");
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSuggestion = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await suggestHitlResponse(hitlId);
      setSubject(res.subject || subject);
      setBody(res.body || "");
      setToneNotes(res.tone_notes || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate suggestion");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSuggestion();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hitlId]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* fallback */
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-5 py-4 shrink-0">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-500" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Draft Reply
            </h2>
            {(companyName || contactName) && (
              <span className="text-xs text-gray-400">
                — {contactName ?? ""}{companyName ? ` at ${companyName}` : ""}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

          {/* Tone toggle */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 shrink-0">Tone:</span>
            {(Object.keys(TONE_LABELS) as Tone[]).map((t) => (
              <button
                key={t}
                onClick={() => setTone(t)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium border transition-colors",
                  tone === t
                    ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900 border-gray-900 dark:border-white"
                    : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-gray-400"
                )}
              >
                {TONE_LABELS[t]}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
              <Loader2 className="h-6 w-6 animate-spin" />
              <p className="text-sm">Drafting reply with Claude...</p>
            </div>
          ) : error ? (
            <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20 px-4 py-3 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          ) : (
            <>
              {/* Subject */}
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Subject</label>
                <input
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 dark:focus:ring-gray-600"
                />
              </div>

              {/* Body */}
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Body</label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={12}
                  className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 dark:focus:ring-gray-600 resize-y font-mono leading-relaxed"
                />
              </div>

              {/* Tone notes */}
              {toneNotes && (
                <div className="rounded-lg border border-violet-100 dark:border-violet-900/30 bg-violet-50 dark:bg-violet-950/20 px-4 py-2.5">
                  <p className="text-xs text-violet-700 dark:text-violet-300">
                    <span className="font-medium">Strategy: </span>{toneNotes}
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 border-t border-gray-100 dark:border-gray-800 px-5 py-4 shrink-0">
          <button
            onClick={fetchSuggestion}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            Regenerate
          </button>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="rounded-md border border-gray-200 dark:border-gray-700 px-4 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Cancel
            </button>

            {onSend ? (
              <button
                onClick={() => onSend(subject, body)}
                disabled={!body || loading}
                className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-4 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-40"
              >
                Send via Instantly
              </button>
            ) : (
              <button
                onClick={handleCopy}
                disabled={!body || loading}
                className="inline-flex items-center gap-1.5 rounded-md bg-gray-900 dark:bg-white px-4 py-1.5 text-xs font-medium text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 disabled:opacity-40"
              >
                {copied ? (
                  <><Check className="h-3 w-3" /> Copied!</>
                ) : (
                  <><Copy className="h-3 w-3" /> Copy to Clipboard</>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
