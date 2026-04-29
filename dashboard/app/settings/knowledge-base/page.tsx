"use client";

import { useEffect, useState, useRef } from "react";
import {
  BookOpen, Upload, Trash2, Loader2, AlertCircle,
  CheckCircle2, Database, Search, FileText, Cpu,
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ITEM_TYPES = ["icp", "template", "competitor", "case_study", "offer", "general"] as const;
type ItemType = typeof ITEM_TYPES[number];

const TYPE_LABELS: Record<ItemType, string> = {
  icp: "ICP Definition",
  template: "Email Template",
  competitor: "Competitor Intel",
  case_study: "Case Study",
  offer: "Offer Context",
  general: "General",
};

const TYPE_COLORS: Record<ItemType, string> = {
  icp: "bg-blue-100 text-blue-800",
  template: "bg-purple-100 text-purple-800",
  competitor: "bg-red-100 text-red-800",
  case_study: "bg-green-100 text-green-800",
  offer: "bg-amber-100 text-amber-800",
  general: "bg-gray-100 text-gray-700",
};

interface KnowledgeItem {
  id: string;
  title: string;
  type: ItemType;
  char_count: number;
  chunk_count: number;
  created_at: string;
}

interface MemoryStatus {
  mode: "vector" | "text_search";
  mode_description: string;
  knowledge_items: number;
  memory_nodes: number;
  top_accessed: Array<{ content: string; source_ref: string; access_count: number }>;
}

export default function KnowledgeBasePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  // Upload form state
  const [form, setForm] = useState({ title: "", type: "general" as ItemType, content: "" });
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const headers = { "Content-Type": "application/json" };

  async function loadAll() {
    setLoading(true);
    try {
      const [itemsRes, statusRes] = await Promise.all([
        fetch(`${API}/api/memory/items`, { credentials: "include" }),
        fetch(`${API}/api/memory/status`, { credentials: "include" }),
      ]);
      if (itemsRes.ok) {
        const d = await itemsRes.json();
        setItems(d.items || []);
      }
      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
    } catch (e) {
      setError("Failed to load knowledge base.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadAll(); }, []);

  async function upload() {
    if (!form.title.trim() || !form.content.trim()) {
      setError("Title and content are required.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/memory/items`, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || "Upload failed.");
      }
      const d = await res.json();
      setSuccess(`Uploaded "${form.title}" — ${d.chunks_inserted} chunks indexed.`);
      setForm({ title: "", type: "general", content: "" });
      await loadAll();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }

  async function deleteItem(id: string, title: string) {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      const res = await fetch(`${API}/api/memory/items/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Delete failed.");
      setSuccess(`Deleted "${title}".`);
      await loadAll();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setDeleting(null);
    }
  }

  async function search() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const res = await fetch(`${API}/api/memory/retrieve`, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({ query: searchQuery, k: 5 }),
      });
      if (res.ok) {
        const d = await res.json();
        setSearchResults(d.results || []);
      }
    } catch (e) {
      setError("Search failed.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BookOpen className="w-6 h-6 text-blue-600" />
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Knowledge Base</h1>
          <p className="text-sm text-gray-500">
            Documents Claude reads when generating outreach, qualifying prospects, and planning campaigns.
          </p>
        </div>
      </div>

      {/* Status banner */}
      {status && (
        <div className={`rounded-lg border p-4 flex items-start gap-3 ${
          status.mode === "vector"
            ? "bg-green-50 border-green-200"
            : "bg-amber-50 border-amber-200"
        }`}>
          <Cpu className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
            status.mode === "vector" ? "text-green-600" : "text-amber-600"
          }`} />
          <div className="text-sm">
            <p className={`font-medium ${status.mode === "vector" ? "text-green-800" : "text-amber-800"}`}>
              {status.mode_description}
            </p>
            <p className="text-gray-600 mt-1">
              {status.knowledge_items} documents · {status.memory_nodes} indexed chunks
              {status.mode === "text_search" && (
                <span className="ml-2">· Set <code className="bg-gray-100 px-1 rounded text-xs">VOYAGE_API_KEY</code> to enable semantic search</span>
              )}
            </p>
          </div>
        </div>
      )}

      {/* Alerts */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-center gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">×</button>
        </div>
      )}
      {success && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-3 flex items-center gap-2 text-sm text-green-700">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          {success}
          <button onClick={() => setSuccess(null)} className="ml-auto text-green-400 hover:text-green-600">×</button>
        </div>
      )}

      {/* Upload form */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
        <h2 className="font-medium text-gray-900 flex items-center gap-2">
          <Upload className="w-4 h-4" /> Add Knowledge Item
        </h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Title</label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. FSMA Compliance Guide"
              value={form.title}
              onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.type}
              onChange={e => setForm(f => ({ ...f, type: e.target.value as ItemType }))}
            >
              {ITEM_TYPES.map(t => (
                <option key={t} value={t}>{TYPE_LABELS[t]}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Content</label>
          <textarea
            ref={textareaRef}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
            rows={8}
            placeholder="Paste document text, email templates, competitor notes, or ICP descriptions..."
            value={form.content}
            onChange={e => setForm(f => ({ ...f, content: e.target.value }))}
          />
          <p className="text-xs text-gray-400 mt-1">{form.content.length.toLocaleString()} characters</p>
        </div>
        <button
          onClick={upload}
          disabled={uploading || !form.title.trim() || !form.content.trim()}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          {uploading ? "Uploading..." : "Upload & Index"}
        </button>
      </div>

      {/* Semantic search */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
        <h2 className="font-medium text-gray-900 flex items-center gap-2">
          <Search className="w-4 h-4" /> Test Knowledge Retrieval
        </h2>
        <div className="flex gap-2">
          <input
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. What messaging works for food safety directors?"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && search()}
          />
          <button
            onClick={search}
            disabled={searching || !searchQuery.trim()}
            className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : "Search"}
          </button>
        </div>
        {searchResults.length > 0 && (
          <div className="space-y-2">
            {searchResults.map((r, i) => (
              <div key={i} className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-mono text-gray-400">{r.source_ref}</span>
                  <span className="text-xs text-gray-500 ml-auto">relevance: {r.relevance}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    r.mode === "vector" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
                  }`}>{r.mode}</span>
                </div>
                <p className="text-sm text-gray-700 line-clamp-3">{r.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Item list */}
      <div className="bg-white border border-gray-200 rounded-xl">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="font-medium text-gray-900 flex items-center gap-2">
            <Database className="w-4 h-4" /> Indexed Documents ({items.length})
          </h2>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center text-gray-400 text-sm">
            <FileText className="w-8 h-8 mx-auto mb-2 opacity-40" />
            No documents yet. Upload your ICP definition, email templates, or competitor notes.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {items.map(item => (
              <div key={item.id} className="flex items-center gap-4 px-6 py-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="font-medium text-sm text-gray-900 truncate">{item.title}</p>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[item.type]}`}>
                      {TYPE_LABELS[item.type]}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {item.char_count?.toLocaleString()} chars · {item.chunk_count} chunks ·{" "}
                    {new Date(item.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={() => deleteItem(item.id, item.title)}
                  disabled={deleting === item.id}
                  className="text-gray-400 hover:text-red-500 p-1.5 rounded-lg hover:bg-red-50 disabled:opacity-50"
                >
                  {deleting === item.id
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <Trash2 className="w-4 h-4" />
                  }
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
