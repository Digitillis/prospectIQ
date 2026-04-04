"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Mail, Lock, Building2, User } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

export default function SignupPage() {
  const router = useRouter();

  const [workspaceName, setWorkspaceName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          password,
          workspace_name: workspaceName.trim(),
          full_name: fullName.trim(),
        }),
      });

      if (res.status === 409) {
        setError("An account with this email already exists. Sign in instead.");
        setLoading(false);
        return;
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.detail ?? "Something went wrong. Please try again.");
        setLoading(false);
        return;
      }

      // Success — redirect to login with a confirmation banner
      router.push("/login?signup=success");
    } catch {
      setError("Could not reach the server. Check your connection.");
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-digitillis-dark px-4 py-12">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="text-center">
          <h1 className="text-3xl font-bold text-white">ProspectIQ</h1>
          <p className="mt-2 text-sm text-slate-400">
            AI-powered Sales Intelligence
          </p>
        </div>

        {/* Card */}
        <div className="rounded-xl bg-white p-8 shadow-xl dark:bg-gray-900">
          <h2 className="mb-1 text-lg font-semibold text-gray-900 dark:text-gray-100">
            Create your workspace
          </h2>
          <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
            Free to start — no credit card required
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Workspace name */}
            <div>
              <label htmlFor="workspace_name" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Company / workspace name
              </label>
              <div className="relative">
                <Building2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="workspace_name"
                  type="text"
                  autoFocus
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  placeholder="Acme Industrial"
                  required
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                />
              </div>
            </div>

            {/* Full name */}
            <div>
              <label htmlFor="full_name" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Your name <span className="font-normal text-gray-400">(optional)</span>
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="full_name"
                  type="text"
                  autoComplete="name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Jane Smith"
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                />
              </div>
            </div>

            {/* Email */}
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Work email
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="email"
                  type="email"
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
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 8 characters"
                  required
                  minLength={8}
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                />
              </div>
            </div>

            {/* Confirm password */}
            <div>
              <label htmlFor="confirm_password" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Confirm password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  id="confirm_password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter password"
                  required
                  className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-digitillis-accent focus:outline-none focus:ring-1 focus:ring-digitillis-accent dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
                />
              </div>
            </div>

            {error && (
              <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
                {error}
                {error.includes("already exists") && (
                  <>
                    {" "}
                    <a href="/login" className="underline font-medium">
                      Sign in
                    </a>
                  </>
                )}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !email || !password || !workspaceName}
              className="w-full rounded-lg bg-digitillis-accent py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating workspace…
                </span>
              ) : (
                "Create workspace"
              )}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-gray-500 dark:text-gray-400">
            Already have an account?{" "}
            <a href="/login" className="font-medium text-digitillis-accent hover:underline">
              Sign in
            </a>
          </p>
        </div>

        <p className="text-center text-xs text-slate-500">
          By signing up you agree to our{" "}
          <a href="https://prospectiq.ai/terms" className="underline hover:text-slate-300">
            Terms of Service
          </a>{" "}
          and{" "}
          <a href="https://prospectiq.ai/privacy" className="underline hover:text-slate-300">
            Privacy Policy
          </a>
          .
        </p>
      </div>
    </div>
  );
}
