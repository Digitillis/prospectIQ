"use client";

/**
 * Revenue Intelligence Dashboard — Coming Soon
 *
 * Full-funnel analytics dashboard for revenue tracking.
 * This feature is under development.
 */

import Link from "next/link";
import { TrendingUp } from "lucide-react";

export default function RevenueAnalyticsPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 p-8 bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800">
      <div className="text-center space-y-4 max-w-md">
        <TrendingUp className="w-16 h-16 mx-auto text-green-500" />
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
          Revenue Intelligence
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          Advanced revenue analytics, funnel performance, and attribution tracking is coming soon.
        </p>
        <p className="text-sm text-gray-500 dark:text-gray-500">
          For now, check the main dashboard for campaign and sequence performance metrics.
        </p>
      </div>

      <Link
        href="/intelligence"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
      >
        View Analytics
      </Link>
    </div>
  );
}
