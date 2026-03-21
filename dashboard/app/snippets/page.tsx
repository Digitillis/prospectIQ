"use client";

/**
 * Message Snippets — Quick-insert text blocks for common outreach patterns
 *
 * Expected actions:
 * Create snippets for value props, CTAs, sign-offs, insert into drafts during approval review
 */


import { useState, useEffect } from "react";
import {
  TextQuote,
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  Link as LinkIcon,
  Save,
  Copy,
} from "lucide-react";
import { useSnippets, useMeetingLink, type Snippet } from "@/lib/use-snippets";
import { cn } from "@/lib/utils";

function SnippetCard({
  snippet,
  onEdit,
  onDelete,
}: {
  snippet: Snippet;
  onEdit: (s: Snippet) => void;
  onDelete: (id: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(snippet.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-gray-900 text-sm">
              {snippet.name}
            </span>
            <code className="rounded bg-digitillis-accent/10 px-2 py-0.5 text-xs font-mono text-digitillis-accent">
              {snippet.shortcut}
            </code>
          </div>
          <p className="mt-2 text-sm text-gray-600 leading-relaxed line-clamp-3">
            {snippet.content}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={handleCopy}
            title="Copy content"
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-lg border transition-colors",
              copied
                ? "border-green-300 bg-green-50 text-green-600"
                : "border-gray-200 text-gray-400 hover:bg-gray-50 hover:text-gray-700"
            )}
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <button
            onClick={() => onEdit(snippet)}
            title="Edit"
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:bg-gray-50 hover:text-gray-700 transition-colors"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => onDelete(snippet.id)}
            title="Delete"
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

interface SnippetFormData {
  name: string;
  shortcut: string;
  content: string;
}

const EMPTY_FORM: SnippetFormData = { name: "", shortcut: "", content: "" };

export default function SnippetsPage() {
  const { snippets, addSnippet, updateSnippet, deleteSnippet } = useSnippets();
  const { link: meetingLink, save: saveMeetingLink } = useMeetingLink();

  const [meetingLinkDraft, setMeetingLinkDraft] = useState("");
  const [meetingLinkSaved, setMeetingLinkSaved] = useState(false);

  // Sync meeting link draft from localStorage once mounted
  useEffect(() => {
    setMeetingLinkDraft(meetingLink);
  }, [meetingLink]);

  function handleSaveMeetingLink() {
    saveMeetingLink(meetingLinkDraft.trim());
    setMeetingLinkSaved(true);
    setTimeout(() => setMeetingLinkSaved(false), 2000);
  }

  // Form state: null = closed, "new" = adding, Snippet = editing
  const [editing, setEditing] = useState<null | "new" | Snippet>(null);
  const [form, setForm] = useState<SnippetFormData>(EMPTY_FORM);
  const [formError, setFormError] = useState("");

  function openNew() {
    setForm(EMPTY_FORM);
    setFormError("");
    setEditing("new");
  }

  function openEdit(snippet: Snippet) {
    setForm({
      name: snippet.name,
      shortcut: snippet.shortcut,
      content: snippet.content,
    });
    setFormError("");
    setEditing(snippet);
  }

  function closeForm() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError("");
  }

  function validateShortcut(s: string) {
    return s.startsWith("/") && s.length > 1;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    if (!validateShortcut(form.shortcut)) {
      setFormError("Shortcut must start with / (e.g. /intro).");
      return;
    }
    if (!form.content.trim()) {
      setFormError("Content is required.");
      return;
    }

    if (editing === "new") {
      addSnippet({
        name: form.name.trim(),
        shortcut: form.shortcut.trim(),
        content: form.content.trim(),
      });
    } else if (editing && typeof editing !== "string") {
      updateSnippet(editing.id, {
        name: form.name.trim(),
        shortcut: form.shortcut.trim(),
        content: form.content.trim(),
      });
    }
    closeForm();
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Snippets</h2>
          <p className="mt-1 text-sm text-gray-500">
            Reusable canned responses for outreach drafts — {snippets.length} saved
          </p>
        </div>
        <button
          onClick={openNew}
          className="flex items-center gap-2 rounded-lg bg-digitillis-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          New Snippet
        </button>
      </div>

      {/* Meeting link */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-1">
          <LinkIcon className="h-4 w-4 text-digitillis-accent" />
          <h3 className="font-semibold text-gray-900">Meeting Link</h3>
        </div>
        <p className="text-sm text-gray-500 mb-3">
          Your Calendly / Cal.com link — automatically available as the{" "}
          <code className="rounded bg-digitillis-accent/10 px-1.5 py-0.5 text-xs font-mono text-digitillis-accent">
            /meeting
          </code>{" "}
          snippet.
        </p>
        <div className="flex gap-2">
          <input
            value={meetingLinkDraft}
            onChange={(e) => setMeetingLinkDraft(e.target.value)}
            placeholder="https://calendly.com/you/30min"
            className="flex-1 h-9 rounded-lg border border-gray-200 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
          />
          <button
            onClick={handleSaveMeetingLink}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium transition-colors",
              meetingLinkSaved
                ? "bg-green-500 text-white"
                : "bg-digitillis-accent text-white hover:opacity-90"
            )}
          >
            {meetingLinkSaved ? (
              <>
                <Check className="h-4 w-4" />
                Saved
              </>
            ) : (
              <>
                <Save className="h-4 w-4" />
                Save
              </>
            )}
          </button>
        </div>
        {meetingLink && (
          <p className="mt-2 text-xs text-gray-400 truncate">
            Current: {meetingLink}
          </p>
        )}
      </div>

      {/* Add / edit form */}
      {editing !== null && (
        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-digitillis-accent/30 bg-white p-5 shadow-sm space-y-3"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <TextQuote className="h-4 w-4 text-digitillis-accent" />
              {editing === "new" ? "New Snippet" : "Edit Snippet"}
            </h3>
            <button type="button" onClick={closeForm} className="text-gray-400 hover:text-gray-700">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Name (e.g. Soft Intro)"
              required
              className="h-9 rounded-lg border border-gray-200 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
            <input
              value={form.shortcut}
              onChange={(e) => setForm((f) => ({ ...f, shortcut: e.target.value }))}
              placeholder="Shortcut (e.g. /intro)"
              required
              className="h-9 rounded-lg border border-gray-200 px-3 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
            <textarea
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
              placeholder="Content… use {company} or {name} as placeholders"
              rows={3}
              required
              className="col-span-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
          </div>

          {formError && (
            <p className="text-xs text-red-500">{formError}</p>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={closeForm}
              className="rounded-lg border border-gray-200 px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg bg-digitillis-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              {editing === "new" ? "Add Snippet" : "Save Changes"}
            </button>
          </div>
        </form>
      )}

      {/* Snippet list */}
      {snippets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 p-12 text-center">
          <TextQuote className="mx-auto h-8 w-8 text-gray-300 mb-3" />
          <p className="text-sm text-gray-500">No snippets yet. Add one above.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {snippets.map((snippet) => (
            <SnippetCard
              key={snippet.id}
              snippet={snippet}
              onEdit={openEdit}
              onDelete={deleteSnippet}
            />
          ))}
        </div>
      )}

      {/* Usage hint */}
      <div className="rounded-lg bg-gray-50 border border-gray-200 px-4 py-3">
        <p className="text-xs text-gray-500">
          <strong className="text-gray-700">Tip:</strong> Use{" "}
          <code className="bg-gray-100 px-1 rounded text-xs">{"{company}"}</code> and{" "}
          <code className="bg-gray-100 px-1 rounded text-xs">{"{name}"}</code> as placeholders in your content —
          they will be replaced when inserting into a draft.
        </p>
      </div>
    </div>
  );
}
