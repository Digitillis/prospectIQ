"use client";

// Copyright © 2026 ProspectIQ. All rights reserved.
// Authors: Avanish Mehrotra & ProspectIQ Technical Team

import { useState } from "react";
import { Loader2, Mail, ArrowLeft, MailCheck } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;

    setError("");
    setRetryAfter(null);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });

      if (res.status === 429) {
        const retryHeader = res.headers.get("Retry-After");
        const seconds = retryHeader ? parseInt(retryHeader, 10) : 300;
        const minutes = Math.ceil(seconds / 60);
        setError(
          `Too many requests. Please wait ${minutes} minute${minutes !== 1 ? "s" : ""} before trying again.`
        );
        setRetryAfter(seconds);
        return;
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(
          (body as { detail?: string }).detail ||
            "Something went wrong. Please try again."
        );
        return;
      }

      setSuccess(true);
    } catch {
      setError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-digitillis-dark px-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="text-center">
          <h1 className="text-3xl font-bold text-white">ProspectIQ</h1>
          <p className="mt-2 text-sm text-slate-400">
            AI-powered manufacturing intelligence
          </p>
        </div>

        {success ? (
          /* ---- Success state ---- */
          <div className="rounded-xl bg-white p-8 shadow-xl dark:bg-gray-900 text-center space-y-4">
            <div className="flex justify-center">
              <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
                <MailCheck className="h-7 w-7 text-green-600 dark:text-green-400" />
              </span>
            </div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              Check your email
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              If an account with{" "}
              <span className="font-medium text-gray-700 dark:text-gray-300">
                {email}
              </span>{" "}
              exists, we&apos;ve sent a password reset link. Check your inbox
              (and spam folder) — it should arrive within a minute.
            </p>
            <a
              href="/login"
              className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-blue-500 hover:text-blue-400"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to sign in
            </a>
          </div>
        ) : (
          /* ---- Request state ---- */
          <div className="rounded-xl bg-white p-8 shadow-xl dark:bg-gray-900">
            <h2 className="mb-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
              Reset your password
            </h2>
            <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
              Enter the email address for your account and we&apos;ll send you a
              reset link.
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label
                  htmlFor="email"
                  className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
                >
                  Email address
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    id="email"
                    type="email"
                    autoFocus
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    required
                    className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                  />
                </div>
              </div>

              {error && (
                <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading || !email.trim() || retryAfter !== null}
                className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white transition-opacity hover:bg-blue-500 disabled:opacity-50"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Sending reset link...
                  </span>
                ) : (
                  "Send reset link"
                )}
              </button>
            </form>
          </div>
        )}

        <p className="text-center text-sm text-slate-400">
          <a
            href="/login"
            className="inline-flex items-center gap-1 font-medium text-blue-400 hover:text-blue-300"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to sign in
          </a>
        </p>
      </div>
    </div>
  );
}
