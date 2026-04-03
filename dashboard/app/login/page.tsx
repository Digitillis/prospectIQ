"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Mail, Lock } from "lucide-react";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [signupSuccess, setSignupSuccess] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (searchParams.get("signup") === "success") {
      setSignupSuccess(true);
      window.history.replaceState({}, "", "/login");
    }
    if (searchParams.get("reset") === "success") {
      setResetSuccess(true);
      window.history.replaceState({}, "", "/login");
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const { error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password,
      });

      if (authError) {
        setError(authError.message || "Invalid email or password.");
        setPassword("");
      } else {
        router.push("/");
        router.refresh();
      }
    } catch {
      setError("Something went wrong. Try again.");
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

        {/* Signup success banner */}
        {signupSuccess && (
          <div className="rounded-lg bg-green-900/30 border border-green-700 px-4 py-3 text-sm text-green-300">
            Workspace created! Sign in below to get started.
          </div>
        )}

        {/* Password reset success banner */}
        {resetSuccess && (
          <div className="rounded-lg bg-green-900/30 border border-green-700 px-4 py-3 text-sm text-green-300">
            Password updated! Sign in with your new password below.
          </div>
        )}

        {/* Card */}
        <div className="rounded-xl bg-white p-8 shadow-xl dark:bg-gray-900">
          <h2 className="mb-6 text-lg font-semibold text-gray-900 dark:text-gray-100">
            Sign in to your workspace
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Email
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
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Password
                </label>
                <a
                  href="/forgot-password"
                  className="text-xs font-medium text-blue-500 hover:text-blue-400"
                >
                  Forgot password?
                </a>
              </div>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
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
              disabled={loading || !email || !password}
              className="w-full rounded-lg bg-digitillis-accent py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in...
                </span>
              ) : (
                "Sign in"
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-sm text-slate-400">
          Don&apos;t have a workspace?{" "}
          <a href="/signup" className="font-medium text-blue-400 underline hover:text-blue-300">
            Create one free
          </a>
        </p>

        <p className="text-center text-xs text-slate-500">
          ProspectIQ by Digitillis &mdash; questions?{" "}
          <a href="mailto:avi@digitillis.com" className="underline hover:text-slate-300">
            avi@digitillis.com
          </a>
        </p>
      </div>
    </div>
  );
}
