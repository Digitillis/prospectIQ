"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Loader2,
  Mail,
  MousePointerClick,
  Eye,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { getEmailEngagement, type EmailEngagementRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function fmtShort(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

type StatusConfig = { label: string; cls: string; dot: string };

const STATUS_CONFIG: Record<string, StatusConfig> = {
  clicked:   { label: "Clicked",   cls: "bg-violet-500/15 text-violet-300 border-violet-500/30",  dot: "bg-violet-400" },
  opened:    { label: "Opened",    cls: "bg-blue-500/15 text-blue-300 border-blue-500/30",        dot: "bg-blue-400" },
  delivered: { label: "Delivered", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30", dot: "bg-emerald-400" },
  sent:      { label: "Sent",      cls: "bg-zinc-700/40 text-zinc-400 border-zinc-600/40",        dot: "bg-zinc-500" },
  bounced:   { label: "Bounced",   cls: "bg-rose-500/15 text-rose-300 border-rose-500/30",        dot: "bg-rose-400" },
  complained:{ label: "Spam",      cls: "bg-orange-500/15 text-orange-300 border-orange-500/30",  dot: "bg-orange-400" },
  failed:    { label: "Failed",    cls: "bg-rose-500/15 text-rose-300 border-rose-500/30",        dot: "bg-rose-400" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG["sent"];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full border font-medium", cfg.cls)}>
      <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", cfg.dot)} />
      {cfg.label}
    </span>
  );
}

type FilterTab = "all" | "opened" | "clicked" | "delivered" | "bounced";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EmailEngagementPage() {
  const [rows, setRows] = useState<EmailEngagementRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getEmailEngagement(200, 0);
      setRows(res.data ?? []);
      setTotal(res.total ?? 0);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Stats
  const stats = {
    sent: rows.length,
    delivered: rows.filter(r => ["delivered","opened","clicked"].includes(r.display_status)).length,
    opened: rows.filter(r => r.opens > 0).length,
    clicked: rows.filter(r => r.clicks > 0).length,
    bounced: rows.filter(r => r.bounced).length,
  };

  const openRate = stats.sent > 0 ? ((stats.opened / stats.sent) * 100).toFixed(1) : "0.0";
  const clickRate = stats.sent > 0 ? ((stats.clicked / stats.sent) * 100).toFixed(1) : "0.0";

  // Filter
  const filtered = rows.filter(r => {
    if (tab === "opened"    && r.opens === 0) return false;
    if (tab === "clicked"   && r.clicks === 0) return false;
    if (tab === "delivered" && !["delivered","opened","clicked"].includes(r.display_status)) return false;
    if (tab === "bounced"   && !r.bounced) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        r.contact_name.toLowerCase().includes(q) ||
        r.contact_email.toLowerCase().includes(q) ||
        r.company_name.toLowerCase().includes(q) ||
        (r.subject ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const TABS: { key: FilterTab; label: string; count: number }[] = [
    { key: "all",       label: "All Sent",  count: stats.sent },
    { key: "opened",    label: "Opened",    count: stats.opened },
    { key: "clicked",   label: "Clicked",   count: stats.clicked },
    { key: "delivered", label: "Delivered", count: stats.delivered },
    { key: "bounced",   label: "Bounced",   count: stats.bounced },
  ];

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Email Engagement</h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            Delivery and engagement tracking for all sent outreach emails
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 border border-zinc-700 rounded-lg px-3 py-1.5 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: "Emails Sent",   value: stats.sent,      icon: Mail,              iconCls: "text-zinc-400",   bg: "bg-zinc-500/10" },
          { label: "Delivered",     value: stats.delivered, icon: CheckCircle2,      iconCls: "text-emerald-400", bg: "bg-emerald-500/10" },
          { label: `Opened ${openRate}%`,  value: stats.opened,    icon: Eye,               iconCls: "text-blue-400",   bg: "bg-blue-500/10" },
          { label: `Clicked ${clickRate}%`, value: stats.clicked,   icon: MousePointerClick, iconCls: "text-violet-400", bg: "bg-violet-500/10" },
          { label: "Bounced",       value: stats.bounced,   icon: XCircle,           iconCls: "text-rose-400",   bg: "bg-rose-500/10" },
        ].map(({ label, value, icon: Icon, iconCls, bg }) => (
          <div key={label} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex items-center gap-3">
            <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center shrink-0", bg)}>
              <Icon className={cn("w-4 h-4", iconCls)} />
            </div>
            <div>
              <p className="text-xl font-semibold text-zinc-100 leading-none">{value}</p>
              <p className="text-[10px] text-zinc-500 mt-0.5 uppercase tracking-wider">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        {/* Tabs */}
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-medium transition-colors",
                tab === t.key
                  ? "bg-zinc-700 text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-300"
              )}
            >
              {t.label}
              <span className={cn(
                "ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full",
                tab === t.key ? "bg-zinc-600 text-zinc-300" : "bg-zinc-800 text-zinc-500"
              )}>
                {t.count}
              </span>
            </button>
          ))}
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Search contact, company, subject…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="text-xs bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 w-64"
        />
      </div>

      {/* Table */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-[1fr_1fr_1fr_80px_60px_60px_100px_90px] gap-3 px-4 py-2.5 border-b border-zinc-800 text-[10px] text-zinc-500 uppercase tracking-wider">
          <span>Contact</span>
          <span>Company</span>
          <span>Subject</span>
          <span className="text-center">Step</span>
          <span className="text-center">Opens</span>
          <span className="text-center">Clicks</span>
          <span>Status</span>
          <span>Sent</span>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-16 gap-2 text-zinc-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">Loading…</span>
          </div>
        )}

        {!loading && error && (
          <div className="flex items-center justify-center py-16 gap-2 text-rose-400">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-2 text-zinc-600">
            <TrendingUp className="w-6 h-6" />
            <span className="text-sm">No emails match this filter</span>
          </div>
        )}

        {!loading && !error && filtered.map((row, idx) => (
          <div
            key={row.draft_id}
            className={cn(
              "grid grid-cols-[1fr_1fr_1fr_80px_60px_60px_100px_90px] gap-3 px-4 py-3 border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/40 transition-colors",
              idx % 2 === 0 ? "bg-zinc-900" : "bg-zinc-900/60"
            )}
          >
            {/* Contact */}
            <div className="min-w-0">
              <p className="text-xs font-medium text-zinc-200 truncate">{row.contact_name}</p>
              <p className="text-[11px] text-zinc-500 truncate">{row.contact_email}</p>
            </div>

            {/* Company */}
            <div className="min-w-0">
              <p className="text-xs text-zinc-300 truncate">{row.company_name}</p>
              {row.industry && (
                <p className="text-[11px] text-zinc-600 truncate">{row.industry}</p>
              )}
            </div>

            {/* Subject */}
            <div className="min-w-0">
              <p className="text-[11px] text-zinc-400 truncate">{row.subject ?? "—"}</p>
            </div>

            {/* Step */}
            <div className="flex items-center justify-center">
              <span className="text-[11px] text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded">
                Step {row.sequence_step}
              </span>
            </div>

            {/* Opens */}
            <div className="flex items-center justify-center gap-1">
              {row.opens > 0 ? (
                <span className="flex items-center gap-1 text-xs text-blue-400 font-medium">
                  <Eye className="w-3 h-3" />
                  {row.opens}
                </span>
              ) : (
                <span className="text-xs text-zinc-600">—</span>
              )}
            </div>

            {/* Clicks */}
            <div className="flex items-center justify-center">
              {row.clicks > 0 ? (
                <span className="flex items-center gap-1 text-xs text-violet-400 font-medium">
                  <MousePointerClick className="w-3 h-3" />
                  {row.clicks}
                </span>
              ) : (
                <span className="text-xs text-zinc-600">—</span>
              )}
            </div>

            {/* Status */}
            <div className="flex items-center">
              <StatusBadge status={row.display_status} />
            </div>

            {/* Sent */}
            <div className="flex items-center">
              <span className="text-[11px] text-zinc-500">{fmtShort(row.sent_at)}</span>
            </div>
          </div>
        ))}
      </div>

      {!loading && filtered.length > 0 && (
        <p className="text-[11px] text-zinc-600 text-right">
          Showing {filtered.length} of {total} sent emails
        </p>
      )}

      {/* Webhook notice if no delivery data */}
      {!loading && rows.length > 0 && rows.every(r => r.display_status === "sent") && (
        <div className="flex items-start gap-3 bg-amber-500/10 border border-amber-500/20 rounded-xl p-4">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-medium text-amber-300">Webhook not yet delivering events</p>
            <p className="text-[11px] text-amber-500/80 mt-0.5">
              All emails show &quot;Sent&quot; because the Resend webhook is still being configured.
              Once the webhook secret is fixed in Resend + Railway, delivery/open/click events will populate here automatically.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
