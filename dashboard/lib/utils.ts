import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatTimeAgo(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return formatDate(dateString);
}

export const STATUS_COLORS: Record<string, string> = {
  discovered:         "bg-slate-100 text-slate-700",
  researched:         "bg-blue-100 text-digitillis-accent",
  qualified:          "bg-green-100 text-digitillis-success",
  disqualified:       "bg-red-100 text-digitillis-danger",
  outreach_pending:   "bg-amber-100 text-digitillis-warning",
  contacted:          "bg-indigo-100 text-indigo-700",
  engaged:            "bg-purple-100 text-purple-700",
  meeting_scheduled:  "bg-pink-100 text-pink-700",
  pilot_discussion:   "bg-orange-100 text-orange-700",
  pilot_signed:       "bg-emerald-100 text-emerald-700",
  active_pilot:       "bg-teal-100 text-teal-700",
  converted:          "bg-green-200 text-green-800",
  not_interested:     "bg-gray-200 text-gray-600",
  paused:             "bg-amber-100 text-digitillis-warning",
  bounced:            "bg-red-200 text-digitillis-danger",
};

export const TIER_LABELS: Record<string, string> = {
  "1a": "Industrial Machinery",
  "1b": "Automotive Parts",
  "2": "Metal Fabrication",
  "3": "Plastics & Molding",
  "4": "Electronics",
  "5": "Aerospace",
};

export function getPQSColor(score: number): string {
  if (score >= 76) return "text-purple-600";
  if (score >= 61) return "text-digitillis-success";
  if (score >= 46) return "text-digitillis-accent";
  if (score >= 26) return "text-digitillis-warning";
  return "text-gray-400";
}
