"use client";

export const dynamic = "force-dynamic";

// Copyright © 2026 ProspectIQ. All rights reserved.
// Authors: Avanish Mehrotra & ProspectIQ Technical Team

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Lock, CheckCircle2, XCircle } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

// ---------------------------------------------------------------------------
// Password-strength helpers
// ---------------------------------------------------------------------------

interface PasswordChecks {
  length: boolean;
  uppercase: boolean;
  lowercase: boolean;
  digit: boolean;
  special: boolean;
}

function evaluatePassword(password: string): PasswordChecks {
  return {
    length: password.length >= 10,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    digit: /\d/.test(password),
    special: /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/.test(password),
  };
}

function strengthScore(checks: PasswordChecks): number {
  return Object.values(checks).filter(Boolean).length; // 0–5
}

function strengthLabel(score: number): string {
  if (score <= 1) return "Weak";
  if (score <= 2) return "Fair";
  if (score <= 3) return "Good";
  return "Strong";
}

function strengthColor(score: number): string {
  if (score <= 1) return "bg-red-500";
  if (score <= 2) return "bg-amber-500";
  if (score <= 3) return "bg-amber-400";
  return "bg-green-500";
}

function strengthTextColor(score: number): string {
  if (score <= 1) return "text-red-500";
  if (score <= 2) return "text-amber-500";
  if (score <= 3) return "text-amber-400";
  return "text-green-500";
}

// ---------------------------------------------------------------------------
// Requirement row
// ---------------------------------------------------------------------------

function Requirement({
  met,
  label,
}: {
  met: boolean;
  label: string;
}) {
  return (
    <li className="flex items-center gap-2 text-xs">
      {met ? (
        <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 text-green-500" />
      ) : (
        <XCircle className="h-3.5 w-3.5 flex-shrink-0 text-gray-400 dark:text-gray-600" />
      )}
      <span
        className={
          met
            ? "text-green-600 dark:text-green-400"
            : "text-gray-500 dark:text-gray-400"
        }
      >
        {label}
      </span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ResetPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tokenMissing, setTokenMissing] = useState(false);

  const checks = evaluatePassword(newPassword);
  const score = strengthScore(checks);
  const allChecksMet = Object.values(checks).every(Boolean);

  useEffect(() => {
    // Supabase appends the token as `?token=…` or via hash fragment
    const t =
      searchParams.get("token") ||
      searchParams.get("access_token") ||
      new URLSearchParams(window.location.hash.slice(1)).get("access_token") ||
      "";
    if (t) {
      setToken(t);
    } else {
      setTokenMissing(true);
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!allChecksMet) {
      setError("Please satisfy all password requirements before submitting.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (!token) {
      setError("Reset token is missing. Please use the link from your email.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: newPassword }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(
          (body as { detail?: string }).detail ||
            "Reset failed. Please request a new reset link."
        );
        return;
      }

      router.push("/login?reset=success");
    } catch {
      setError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render — missing token state
  // ---------------------------------------------------------------------------

  if (tokenMissing) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-digitillis-dark px-4">
        <div className="w-full max-w-sm space-y-6">
          <div className="text-center">
            <h1 className="text-3xl font-bold text-white">ProspectIQ</h1>
          </div>
          <div className="rounded-xl bg-white p-8 shadow-xl dark:bg-gray-900 text-center space-y-4">
            <XCircle className="mx-auto h-12 w-12 text-red-500" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              Reset link expired or invalid
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              This password reset link is missing its token. Reset links expire
              after a short period for security.
            </p>
            <a
              href="/forgot-password"
              className="inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
            >
              Request a new reset link
            </a>
          </div>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render — main form
  // ---------------------------------------------------------------------------

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

        <div className="rounded-xl bg-white p-8 shadow-xl dark:bg-gray-900">
          <h2 className="mb-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
            Set a new password
          </h2>
          <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
            Choose a strong password to secure your account.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* New password */}
            <div>
              <label
                htmlFor="new-password"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                New password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="new-password"
                  type="password"
                  autoFocus
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="••••••••••"
                  required
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                />
              </div>
            </div>

            {/* Strength meter — shown once user starts typing */}
            {newPassword.length > 0 && (
              <div className="space-y-2">
                {/* 4-segment bar */}
                <div className="flex gap-1">
                  {[1, 2, 3, 4].map((segment) => (
                    <div
                      key={segment}
                      className={`h-1.5 flex-1 rounded-full transition-colors ${
                        score >= segment + 1
                          ? strengthColor(score)
                          : score === segment
                          ? strengthColor(score)
                          : "bg-gray-200 dark:bg-gray-700"
                      }`}
                    />
                  ))}
                </div>
                <p
                  className={`text-xs font-medium ${strengthTextColor(score)}`}
                >
                  {strengthLabel(score)}
                </p>

                {/* Requirements checklist */}
                <ul className="space-y-1 pt-1">
                  <Requirement met={checks.length} label="At least 10 characters" />
                  <Requirement met={checks.uppercase} label="Uppercase letter (A–Z)" />
                  <Requirement met={checks.lowercase} label="Lowercase letter (a–z)" />
                  <Requirement met={checks.digit} label="Number (0–9)" />
                  <Requirement
                    met={checks.special}
                    label="Special character (!@#$%…)"
                  />
                </ul>
              </div>
            )}

            {/* Confirm password */}
            <div>
              <label
                htmlFor="confirm-password"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Confirm password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••••"
                  required
                  className={`w-full rounded-lg border py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-1 dark:bg-gray-800 dark:text-gray-100 ${
                    confirmPassword.length > 0 && confirmPassword !== newPassword
                      ? "border-red-400 focus:border-red-500 focus:ring-red-500"
                      : "border-gray-300 focus:border-blue-500 focus:ring-blue-500 dark:border-gray-700"
                  }`}
                />
              </div>
              {confirmPassword.length > 0 && confirmPassword !== newPassword && (
                <p className="mt-1 text-xs text-red-500">
                  Passwords do not match.
                </p>
              )}
            </div>

            {error && (
              <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
                {error.includes("expired") || error.includes("invalid") ? (
                  <>
                    {error}{" "}
                    <a
                      href="/forgot-password"
                      className="underline hover:no-underline"
                    >
                      Request a new link.
                    </a>
                  </>
                ) : (
                  error
                )}
              </div>
            )}

            <button
              type="submit"
              disabled={
                loading ||
                !allChecksMet ||
                newPassword !== confirmPassword ||
                !confirmPassword
              }
              className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white transition-opacity hover:bg-blue-500 disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Updating password...
                </span>
              ) : (
                "Set new password"
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-sm text-slate-400">
          <a
            href="/login"
            className="font-medium text-blue-400 hover:text-blue-300"
          >
            Back to sign in
          </a>
        </p>
      </div>
    </div>
  );
}
