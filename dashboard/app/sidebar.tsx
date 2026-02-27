"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Building2,
  CheckCircle2,
  ListTodo,
  BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { label: "Pipeline", href: "/", icon: LayoutDashboard },
  { label: "Prospects", href: "/prospects", icon: Building2 },
  { label: "Approvals", href: "/approvals", icon: CheckCircle2 },
  { label: "Actions", href: "/actions", icon: ListTodo },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="group flex h-full w-16 flex-col bg-[#1a1a2e] transition-all duration-200 hover:w-60">
      {/* Logo area */}
      <div className="flex h-14 items-center justify-center border-b border-white/10 px-4">
        <span className="text-xl font-bold text-white">P</span>
        <span className="ml-1 hidden truncate text-lg font-semibold text-white group-hover:inline">
          rospectIQ
        </span>
      </div>

      {/* Navigation links */}
      <ul className="mt-4 flex flex-1 flex-col gap-1 px-2">
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
                    ? "bg-white/15 text-white"
                    : "text-gray-400 hover:bg-white/10 hover:text-white"
                )}
              >
                <Icon className="h-5 w-5 shrink-0" />
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
