"use client";

/**
 * SequencePreview — modal that renders sequence steps with contact/company variables filled in.
 */

import { useState, useEffect, useCallback } from "react";
import { Loader2, Mail, Clock, GitBranch, ClipboardList, Linkedin, X, Search } from "lucide-react";
import {
  getAllContacts, getCompanies,
} from "@/lib/api";
import type { StepType } from "@/types/sequence";
import { cn } from "@/lib/utils";

interface Contact {
  id: string;
  full_name?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  title?: string;
  company_id?: string;
}

interface Company {
  id: string;
  name: string;
  industry?: string;
}

interface RenderedStep {
  step_id: string;
  step_type: StepType;
  subject_template?: string;
  body_template?: string;
  rendered_subject?: string;
  rendered_body?: string;
  wait_days?: number;
}

interface RenderedSequence {
  sequence_id: string;
  name: string;
  steps: RenderedStep[];
}

const STEP_ICONS: Record<StepType, React.ElementType> = {
  email:     Mail,
  wait:      Clock,
  condition: GitBranch,
  task:      ClipboardList,
  linkedin:  Linkedin,
};

const STEP_COLORS: Record<StepType, string> = {
  email:     "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20",
  wait:      "text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-700",
  condition: "text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20",
  task:      "text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20",
  linkedin:  "text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-900/20",
};

const STEP_LABELS: Record<StepType, string> = {
  email:     "Email",
  wait:      "Wait",
  condition: "Condition",
  task:      "Task",
  linkedin:  "LinkedIn",
};

function RenderedStepCard({ step }: { step: RenderedStep }) {
  const [bodyExpanded, setBodyExpanded] = useState(false);
  const Icon = STEP_ICONS[step.step_type] ?? Mail;
  const colorClass = STEP_COLORS[step.step_type] ?? STEP_COLORS.email;
  const label = STEP_LABELS[step.step_type] ?? step.step_type;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", colorClass)}>
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <span className="text-xs font-semibold text-gray-900 dark:text-gray-100">{label}</span>
          <span className="ml-2 text-[10px] text-gray-400 dark:text-gray-500">Step {step.step_order}</span>
        </div>
      </div>

      <div className="px-4 py-3 text-xs space-y-2">
        {step.step_type === "email" && (
          <>
            {step.subject && (
              <div>
                <span className="font-semibold text-gray-500 dark:text-gray-400 mr-1">Subject:</span>
                <span className="text-gray-900 dark:text-gray-100">{step.subject}</span>
              </div>
            )}
            {step.body && (
              <div>
                <button
                  onClick={() => setBodyExpanded((v) => !v)}
                  className="flex items-center gap-1 font-semibold text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 mb-1"
                >
                  Body {bodyExpanded ? "▲" : "▼"}
                </button>
                {bodyExpanded && (
                  <pre className="whitespace-pre-wrap rounded bg-gray-50 dark:bg-gray-800 px-3 py-2 text-gray-800 dark:text-gray-200 font-sans leading-relaxed">
                    {step.body}
                  </pre>
                )}
                {!bodyExpanded && (
                  <p className="text-gray-600 dark:text-gray-400 line-clamp-2">
                    {step.body}
                  </p>
                )}
              </div>
            )}
          </>
        )}

        {step.step_type === "wait" && (
          <p className="text-gray-600 dark:text-gray-400">
            Wait <strong className="text-gray-900 dark:text-gray-100">{step.wait_days ?? "?"} day{(step.wait_days ?? 0) !== 1 ? "s" : ""}</strong>
            {step.wait_condition && step.wait_condition !== "any" && (
              <> if <strong className="text-gray-900 dark:text-gray-100">{step.wait_condition.replace("_", " ")}</strong></>
            )}
          </p>
        )}

        {step.step_type === "condition" && (
          <p className="text-gray-600 dark:text-gray-400">
            Condition: <strong className="text-gray-900 dark:text-gray-100">{step.condition_type?.replace(/_/g, " ") ?? "—"}</strong>
          </p>
        )}

        {step.step_type === "task" && step.task_description && (
          <p className="text-gray-600 dark:text-gray-400">{step.task_description}</p>
        )}

        {step.step_type === "linkedin" && step.body && (
          <p className="text-gray-600 dark:text-gray-400">{step.body}</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface SequencePreviewProps {
  sequenceId: string;
  onClose: () => void;
}

export function SequencePreview({ sequenceId, onClose }: SequencePreviewProps) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [contactSearch, setContactSearch] = useState("");
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [loadingContacts, setLoadingContacts] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [rendered, setRendered] = useState<RenderedSequence | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    setLoadingContacts(true);
    Promise.all([
      getAllContacts({ limit: "50" }),
      getCompanies({ limit: "50" }),
    ])
      .then(([contactsRes, companiesRes]) => {
        setContacts((contactsRes.data as Contact[]) || []);
        setCompanies((companiesRes.data as Company[]) || []);
      })
      .catch(() => {})
      .finally(() => setLoadingContacts(false));
  }, []);

  const filteredContacts = contacts.filter((c) => {
    if (!contactSearch) return true;
    const q = contactSearch.toLowerCase();
    return (
      (c.full_name ?? "").toLowerCase().includes(q) ||
      (c.email ?? "").toLowerCase().includes(q)
    );
  });

  const renderPreview = useCallback(async () => {
    if (!selectedContact || !selectedCompany) return;
    setRendering(true);
    setRenderError(null);
    setRendered(null);
    try {
      // TODO: Implement previewSequenceV2 in API
      setRenderError("Sequence preview functionality coming soon");
    } catch (e) {
      setRenderError(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setRendering(false);
    }
  }, [sequenceId, selectedContact, selectedCompany]);

  // Auto-select company when contact selected
  useEffect(() => {
    if (selectedContact?.company_id) {
      const co = companies.find((c) => c.id === selectedContact.company_id);
      if (co) setSelectedCompany(co);
    }
  }, [selectedContact, companies]);

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* Panel */}
      <div className="relative ml-auto flex h-full w-full max-w-xl flex-col bg-white dark:bg-gray-900 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200 dark:border-gray-700 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Sequence Preview</h2>
            <p className="text-xs text-gray-500 dark:text-gray-500">Select a contact to render variables</p>
          </div>
          <button
            aria-label="Close preview"
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Contact selector */}
        <div className="shrink-0 border-b border-gray-100 dark:border-gray-800 px-5 py-3 space-y-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" aria-hidden />
            <input
              type="text"
              placeholder="Search contacts..."
              value={contactSearch}
              onChange={(e) => setContactSearch(e.target.value)}
              className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 pl-9 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {loadingContacts ? (
            <div className="flex items-center gap-2 text-xs text-gray-400 py-1">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading contacts…
            </div>
          ) : (
            <div className="max-h-36 overflow-y-auto space-y-1">
              {filteredContacts.slice(0, 20).map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedContact(c)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                    selectedContact?.id === c.id
                      ? "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                      : "hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300"
                  )}
                >
                  <span className="font-medium truncate">{c.full_name || `${c.first_name ?? ""} ${c.last_name ?? ""}`.trim() || c.email || c.id.slice(0, 8)}</span>
                  {c.title && <span className="text-gray-400 dark:text-gray-500 truncate">· {c.title}</span>}
                </button>
              ))}
              {filteredContacts.length === 0 && (
                <p className="px-2 py-1 text-xs text-gray-400 dark:text-gray-500">No contacts found</p>
              )}
            </div>
          )}

          {selectedContact && (
            <div className="flex items-center gap-2">
              <div className="flex-1">
                <label className="block text-[10px] font-semibold text-gray-500 dark:text-gray-400 mb-0.5">Company</label>
                <select
                  value={selectedCompany?.id ?? ""}
                  onChange={(e) => {
                    const co = companies.find((c) => c.id === e.target.value);
                    setSelectedCompany(co ?? null);
                  }}
                  className="w-full rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="">— Select company —</option>
                  {companies.map((co) => (
                    <option key={co.id} value={co.id}>{co.name}</option>
                  ))}
                </select>
              </div>
              <button
                onClick={renderPreview}
                disabled={!selectedCompany || rendering}
                className="self-end inline-flex items-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {rendering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Render
              </button>
            </div>
          )}
        </div>

        {/* Rendered steps */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {renderError && (
            <div className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-xs text-red-700 dark:text-red-400">
              {renderError}
            </div>
          )}

          {!rendered && !renderError && !rendering && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">Select a contact and click Render</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Template variables will be filled with real data</p>
            </div>
          )}

          {rendering && (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
            </div>
          )}

          {rendered && (
            <>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  Previewing for{" "}
                  <strong className="text-gray-900 dark:text-gray-100">{rendered.contact_name || selectedContact?.full_name}</strong>
                  {rendered.company_name && (
                    <> at <strong className="text-gray-900 dark:text-gray-100">{rendered.company_name}</strong></>
                  )}
                </span>
              </div>
              {rendered.steps.map((step) => (
                <RenderedStepCard key={step.step_id} step={step} />
              ))}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-gray-200 dark:border-gray-700 px-5 py-3 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-md border border-gray-200 dark:border-gray-700 px-4 py-2 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-400"
          >
            Close Preview
          </button>
        </div>
      </div>
    </div>
  );
}
