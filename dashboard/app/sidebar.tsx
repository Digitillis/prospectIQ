"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Building2,
  MessageSquare,
  Zap,
  Users,
  Filter,
  GitBranch,
  Send,
  PenTool,
  BarChart3,
  History,
  Settings,
  Search,
  Activity,
  UserPlus,
  Ban,
  CheckCircle2,
  Moon,
  Sun,
  Inbox,
} from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { listThreads, getHitlStats } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

/** Fetch threads needing action for the badge count. */
function useThreadsBadge(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    listThreads({ needs_action: true, limit: 200 })
      .then((res) => setCount(res.needs_action_count ?? 0))
      .catch(() => {});
  }, []);

  return count;
}

/** HITL queue pending badge count. */
function useHitlBadge(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    getHitlStats()
      .then((res) => setCount(res.pending ?? 0))
      .catch(() => {});
  }, []);

  return count;
}

/** Hot signals badge — companies with intent_score > 15. */
function useSignalsBadge(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    fetch(`${API_BASE}/api/intelligence/signals`)
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (json) setCount(json.total_hot ?? 0);
      })
      .catch(() => {});
  }, []);

  return count;
}

// ---------------------------------------------------------------------------
// Section type
// ---------------------------------------------------------------------------
interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  exactMatch?: boolean;
  badge?: number;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

// ---------------------------------------------------------------------------
// Sidebar component
// ---------------------------------------------------------------------------

export function Sidebar() {
  const pathname = usePathname();
  const threadsBadge = useThreadsBadge();
  const hitlBadge = useHitlBadge();
  const signalsBadge = useSignalsBadge();

  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "dark") {
      document.documentElement.classList.add("dark");
      setDark(true);
    }
  }, []);

  const toggleDark = () => {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  };

  const sections: NavSection[] = [
    {
      title: "OPERATE",
      items: [
        { label: "Command Center", href: "/", icon: LayoutDashboard, exactMatch: true },
        { label: "Pipeline", href: "/pipeline", icon: Activity },
        { label: "Reply Queue", href: "/hitl", icon: Inbox, badge: hitlBadge > 0 ? hitlBadge : undefined },
        { label: "Threads", href: "/threads", icon: MessageSquare, badge: threadsBadge > 0 ? threadsBadge : undefined },
        { label: "Signals", href: "/signals", icon: Zap, badge: signalsBadge > 0 ? signalsBadge : undefined },
      ],
    },
    {
      title: "BUILD",
      items: [
        { label: "Prospects", href: "/prospects", icon: Building2 },
        { label: "Contacts", href: "/contacts", icon: Users },
        { label: "Segments", href: "/segments", icon: Filter },
      ],
    },
    {
      title: "ENGAGE",
      items: [
        { label: "Sequences", href: "/sequences", icon: GitBranch },
        { label: "Outreach Hub", href: "/outreach", icon: Send },
        { label: "Content", href: "/content", icon: PenTool },
      ],
    },
    {
      title: "MEASURE",
      items: [
        { label: "Intelligence", href: "/intelligence", icon: BarChart3 },
        { label: "Analytics", href: "/analytics", icon: BarChart3 },
        { label: "History", href: "/history", icon: History },
      ],
    },
    {
      title: "SYSTEM",
      items: [
        { label: "Enrichment", href: "/enrichment", icon: UserPlus },
        { label: "Automations", href: "/automations", icon: Zap },
        { label: "Approvals", href: "/approvals", icon: CheckCircle2 },
        { label: "DNC List", href: "/dnc", icon: Ban },
        { label: "Settings", href: "/settings/workspace", icon: Settings },
      ],
    },
  ];

  const isActive = (item: NavItem) => {
    if (item.exactMatch) return pathname === item.href;
    return item.href !== "/" && pathname.startsWith(item.href);
  };

  return (
    <nav className="group flex h-full w-14 flex-col bg-white dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800 transition-all duration-200 hover:w-52">
      {/* Logo */}
      <div className="flex h-14 items-center justify-center border-b border-gray-200 dark:border-gray-800 px-4 shrink-0">
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">P</span>
        <span className="ml-1 hidden truncate text-sm font-semibold text-gray-900 dark:text-gray-100 group-hover:inline">
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
        className="mx-2 mt-3 flex items-center gap-3 rounded-md px-3 py-2 text-xs text-gray-500 dark:text-gray-400 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100 shrink-0"
        title="Search (⌘K)"
      >
        <Search className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500" />
        <span className="hidden min-w-0 flex-1 truncate text-left group-hover:inline">
          Search
        </span>
        <kbd className="hidden shrink-0 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] group-hover:inline">
          ⌘K
        </kbd>
      </button>

      {/* Scrollable nav */}
      <div className="flex flex-1 flex-col gap-0 overflow-y-auto px-2 py-2 scrollbar-thin scrollbar-thumb-gray-200 dark:scrollbar-thumb-gray-700 scrollbar-track-transparent">
        {sections.map((section) => (
          <div key={section.title}>
            {/* Section label — only visible when expanded */}
            <div className="mb-0.5 mt-3 hidden px-3 group-hover:block">
              <span className="text-[9px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-600">
                {section.title}
              </span>
            </div>
            {/* Divider when collapsed */}
            <div className="mb-1 mt-2 border-t border-gray-100 dark:border-gray-800 group-hover:hidden" />

            <ul className="flex flex-col gap-0.5">
              {section.items.map((item) => {
                const active = isActive(item);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={cn(
                        "relative flex items-center gap-3 rounded-md px-3 py-2 text-xs transition-colors",
                        active
                          ? "bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium"
                          : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100"
                      )}
                    >
                      {/* Icon with optional badge dot (collapsed state) */}
                      <div className="relative shrink-0">
                        <Icon
                          className={cn(
                            "h-4 w-4",
                            active
                              ? "text-gray-900 dark:text-gray-100"
                              : "text-gray-400 dark:text-gray-500"
                          )}
                        />
                        {item.badge !== undefined && item.badge > 0 && (
                          <span className="absolute -right-1.5 -top-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-red-500 px-0.5 text-[8px] font-bold text-white leading-none group-hover:hidden">
                            {item.badge > 99 ? "99+" : item.badge}
                          </span>
                        )}
                      </div>

                      {/* Label (expanded state) */}
                      <span className="hidden truncate flex-1 group-hover:inline">
                        {item.label}
                      </span>

                      {/* Badge pill (expanded state) */}
                      {item.badge !== undefined && item.badge > 0 && (
                        <span className="ml-auto hidden shrink-0 rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white group-hover:inline">
                          {item.badge > 99 ? "99+" : item.badge}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      {/* Dark mode toggle */}
      <div className="flex shrink-0 items-center justify-center border-t border-gray-200 dark:border-gray-800 p-2">
        <button
          onClick={toggleDark}
          className="flex items-center gap-3 rounded-md px-3 py-2 text-xs text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100 w-full transition-colors"
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {dark ? (
            <Sun className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500" />
          ) : (
            <Moon className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500" />
          )}
          <span className="hidden group-hover:inline truncate">
            {dark ? "Light mode" : "Dark mode"}
          </span>
        </button>
      </div>
    </nav>
  );
}
