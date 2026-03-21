"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Building2,
  CheckCircle2,
  ListTodo,
  UserPlus,
  BarChart3,
  History,
  Settings,
  Search,
  Activity,
  Upload,
  FileText,
  Ban,
  Zap,
  Users,
  ListChecks,
  TextQuote,
  MessageCircle,
  Sun,
  PenTool,
} from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Fetch today's total pending action count for the notification badge.
 * Silently returns 0 on any failure so the sidebar always renders.
 */
function useTodayBadgeCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const API_BASE =
      process.env.NEXT_PUBLIC_API_URL ||
      "https://prospectiq-production-4848.up.railway.app";

    fetch(`${API_BASE}/api/today`, {
      headers: { "Content-Type": "application/json" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (!json?.data) return;
        const d = json.data;
        const total =
          (d.hot_signals?.length ?? 0) +
          (d.pending_approvals?.length ?? 0) +
          (d.linkedin_queue?.length ?? 0);
        setCount(total);
      })
      .catch(() => {});
  }, []);

  return count;
}

const NAV_ITEMS = [
  // "Today" is intentionally NOT here — it's rendered separately with a badge
  { label: "Pipeline", href: "/", icon: LayoutDashboard },
  { label: "Activity", href: "/activity", icon: Activity },
  { label: "Tasks", href: "/tasks", icon: ListChecks },
  { label: "Prospects", href: "/prospects", icon: Building2 },
  { label: "Contacts", href: "/contacts", icon: Users },
  { label: "LinkedIn", href: "/linkedin", icon: MessageCircle },
  { label: "Content", href: "/content", icon: PenTool },
  { label: "Approvals", href: "/approvals", icon: CheckCircle2 },
  { label: "Actions", href: "/actions", icon: ListTodo },
  { label: "Automations", href: "/automations", icon: Zap },
  { label: "Enrichment", href: "/enrichment", icon: UserPlus },
  { label: "Templates", href: "/templates", icon: FileText },
  { label: "Snippets", href: "/snippets", icon: TextQuote },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "History", href: "/history", icon: History },
  { label: "Import", href: "/import", icon: Upload },
  { label: "DNC List", href: "/dnc", icon: Ban },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const todayCount = useTodayBadgeCount();
  const isTodayActive = pathname === "/today";

  return (
    <nav className="group flex h-full w-16 flex-col bg-digitillis-darker transition-all duration-200 hover:w-60">
      {/* Logo area */}
      <div className="flex h-14 items-center justify-center border-b border-white/10 px-4">
        <span className="text-xl font-bold text-white">P</span>
        <span className="ml-1 hidden truncate text-lg font-semibold text-white group-hover:inline">
          rospectIQ
        </span>
      </div>

      {/* Search trigger */}
      <button
        onClick={() =>
          document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true })
          )
        }
        className="mx-2 mt-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
        title="Search (⌘K)"
      >
        <Search className="h-5 w-5 shrink-0" />
        <span className="hidden min-w-0 flex-1 truncate text-left group-hover:inline">
          Search
        </span>
        <kbd className="hidden shrink-0 rounded border border-white/20 px-1.5 py-0.5 text-xs group-hover:inline">
          ⌘K
        </kbd>
      </button>

      {/* Navigation links — scrollable when viewport is short */}
      <ul className="mt-2 flex flex-1 flex-col gap-1 overflow-y-auto px-2 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">

        {/* TODAY — always first, with notification badge */}
        <li>
          <Link
            href="/today"
            className={cn(
              "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
              isTodayActive
                ? "bg-amber-500/20 text-white"
                : "text-slate-400 hover:bg-white/10 hover:text-white"
            )}
          >
            <div className="relative shrink-0">
              <Sun
                className={cn(
                  "h-5 w-5",
                  isTodayActive ? "text-amber-400" : ""
                )}
              />
              {/* Notification badge */}
              {todayCount > 0 && (
                <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white leading-none">
                  {todayCount > 99 ? "99+" : todayCount}
                </span>
              )}
            </div>
            <span className="hidden truncate group-hover:inline">Today</span>
            {/* Badge visible in expanded state */}
            {todayCount > 0 && (
              <span className="ml-auto hidden shrink-0 rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white group-hover:inline">
                {todayCount > 99 ? "99+" : todayCount}
              </span>
            )}
          </Link>
        </li>

        {/* Divider */}
        <li className="mx-2 my-1 border-t border-white/10" />

        {/* All other nav items */}
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-digitillis-accent/20 text-white"
                    : "text-slate-400 hover:bg-white/10 hover:text-white"
                )}
              >
                <Icon className={cn("h-5 w-5 shrink-0", isActive && "text-digitillis-accent")} />
                <span className="hidden truncate group-hover:inline">
                  {item.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
