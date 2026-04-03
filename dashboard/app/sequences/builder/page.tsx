"use client";

/**
 * Visual Sequence Builder — Coming Soon
 *
 * This feature is under development. The backend API for V2 sequences
 * is not yet complete. Use the template library for now.
 */

import Link from "next/link";
import { ArrowLeft, Zap } from "lucide-react";

export default function SequenceBuilderPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 p-8 bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800">
      <div className="text-center space-y-4 max-w-md">
        <Zap className="w-16 h-16 mx-auto text-amber-500" />
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
          Sequence Builder
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          The visual sequence builder is coming soon. This feature will let you design custom engagement sequences with a drag-and-drop interface.
        </p>
        <p className="text-sm text-gray-500 dark:text-gray-500">
          For now, use the template library or contact support for custom sequence setup.
        </p>
      </div>

      <Link
        href="/sequences"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Sequences
      </Link>
    </div>
  );
}
