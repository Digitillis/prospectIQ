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
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { label: "Pipeline", href: "/", icon: LayoutDashboard },
  { label: "Activity", href: "/activity", icon: Activity },
  { label: "Tasks", href: "/tasks", icon: ListChecks },
  { label: "Prospects", href: "/prospects", icon: Building2 },
  { label: "Contacts", href: "/contacts", icon: Users },
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

      {/* Navigation links */}
      <ul className="mt-2 flex flex-1 flex-col gap-1 px-2">
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
