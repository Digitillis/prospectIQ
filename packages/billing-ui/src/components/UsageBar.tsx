/**
 * UsageBar — reusable usage progress bar.
 * Zero external dependencies beyond Tailwind CSS.
 */

import { usagePct, usageLevel, fmtNumber } from "../utils";

interface UsageBarProps {
  label: string;
  used: number;
  limit: number;
  icon?: React.ReactNode;
  suffix?: string;        // e.g. "this month", "total"
  unlimited?: boolean;    // skip bar and show "Unlimited"
  accentClass?: string;   // Tailwind color for the "ok" state bar. Default: "bg-blue-500"
}

export function UsageBar({
  label,
  used,
  limit,
  icon,
  suffix,
  unlimited = false,
  accentClass = "bg-blue-500",
}: UsageBarProps) {
  const pct = usagePct(used, limit);
  const level = usageLevel(used, limit);

  const barColor =
    level === "danger"  ? "bg-red-500" :
    level === "warning" ? "bg-amber-500" :
    accentClass;

  const textColor =
    level === "danger"  ? "text-red-600 dark:text-red-400" :
    level === "warning" ? "text-amber-600 dark:text-amber-400" :
    "text-gray-900 dark:text-gray-100";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
          {icon}
          <span>{label}</span>
        </div>
        {unlimited ? (
          <span className="text-gray-500 dark:text-gray-400 text-xs">Unlimited</span>
        ) : (
          <span className={`font-medium tabular-nums ${textColor}`}>
            {fmtNumber(used)}{" "}
            <span className="font-normal text-gray-400 dark:text-gray-500">
              / {fmtNumber(limit)}{suffix ? ` ${suffix}` : ""}
            </span>
          </span>
        )}
      </div>
      {!unlimited && (
        <div className="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800">
          <div
            className={`h-1.5 rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}
