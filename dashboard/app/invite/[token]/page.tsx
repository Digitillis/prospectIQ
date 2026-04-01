"use client";

/**
 * Invite Acceptance Page — /invite/[token]
 *
 * Validates the invite token, shows workspace info, and lets the user
 * accept by signing in (if they have an account) or creating one.
 *
 * Flow:
 *  1. Page loads → GET /api/auth/invite/validate?token=...  (no auth required)
 *  2. If valid: show workspace name + inviter + role
 *  3. User clicks "Accept" → POST /api/auth/invite/accept with token
 *     The backend links their user_id to the pending workspace_members row
 *  4. Redirect to dashboard
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

interface InviteInfo {
  workspace_name: string;
  inviter_email: string;
  role: string;
  invitee_email: string;
}

type PageState =
  | "loading"        // validating token
  | "valid"          // token OK, not yet signed in
  | "signed_in"      // token OK, user is already signed in
  | "accepting"      // POSTing acceptance
  | "done"           // accepted successfully
  | "invalid"        // token not found or expired
  | "already_member" // already active member of this workspace
  | "error";         // unexpected server error

export default function InvitePage() {
  const params = useParams();
  const router = useRouter();
  const token = params.token as string;

  const [state, setState] = useState<PageState>("loading");
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>("");

  // Auth form state (for users who aren't logged in)
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string>("");

  // Step 1: Validate the token (public endpoint — no auth)
  useEffect(() => {
    if (!token) return;

    fetch(`${API_BASE}/api/auth/invite/validate?token=${encodeURIComponent(token)}`)
      .then(async (res) => {
        if (res.status === 404 || res.status === 410) {
          setState("invalid");
          return;
        }
        if (res.status === 409) {
          setState("already_member");
          return;
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          setErrorMsg(body.detail ?? "Unexpected error validating invite.");
          setState("error");
          return;
        }
        const data: InviteInfo = await res.json();
        setInvite(data);

        // Pre-fill email if we have it
        if (data.invitee_email) setEmail(data.invitee_email);

        // Check if user is already signed in
        const { data: { session } } = await supabase.auth.getSession();
        setState(session ? "signed_in" : "valid");
      })
      .catch(() => {
        setErrorMsg("Could not reach the server. Check your connection.");
        setState("error");
      });
  }, [token]);

  // Step 2a: Accept when already signed in
  const acceptInvite = async () => {
    setState("accepting");
    const { data: { session } } = await supabase.auth.getSession();
    const authHeader = session?.access_token
      ? `Bearer ${session.access_token}`
      : "";

    const res = await fetch(`${API_BASE}/api/auth/invite/accept`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({ token }),
    });

    if (res.ok) {
      setState("done");
      setTimeout(() => router.replace("/"), 2000);
    } else {
      const body = await res.json().catch(() => ({}));
      setErrorMsg(body.detail ?? "Failed to accept invite.");
      setState("error");
    }
  };

  // Step 2b: Sign in / sign up, then accept
  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthLoading(true);
    setAuthError("");

    try {
      if (authMode === "signup") {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) {
          setAuthError(error.message);
          setAuthLoading(false);
          return;
        }
        // Supabase requires email confirmation by default — let user know
        // In development / with email confirmation off, session is set immediately
      }

      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setAuthError(error.message);
        setAuthLoading(false);
        return;
      }

      // Signed in — now accept
      await acceptInvite();
    } catch {
      setAuthError("An unexpected error occurred.");
      setAuthLoading(false);
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  if (state === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <p className="text-sm text-gray-500">Validating invite…</p>
      </div>
    );
  }

  if (state === "done") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="w-full max-w-md rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-green-100 dark:bg-green-900">
            <svg className="h-6 w-6 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">You&apos;re in!</h2>
          <p className="mt-1 text-sm text-gray-500">
            Joined <strong>{invite?.workspace_name}</strong> successfully. Redirecting…
          </p>
        </div>
      </div>
    );
  }

  if (state === "invalid") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="w-full max-w-md rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Invite not found</h2>
          <p className="mt-2 text-sm text-gray-500">
            This invite link is invalid or has already been used. Ask your workspace admin to send a new invite.
          </p>
        </div>
      </div>
    );
  }

  if (state === "already_member") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="w-full max-w-md rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Already a member</h2>
          <p className="mt-2 text-sm text-gray-500">
            You&apos;re already an active member of this workspace.
          </p>
          <a
            href="/"
            className="mt-4 inline-block rounded-md bg-gray-900 dark:bg-gray-100 px-4 py-2 text-sm font-medium text-white dark:text-gray-900 hover:opacity-90"
          >
            Go to dashboard
          </a>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="w-full max-w-md rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Something went wrong</h2>
          <p className="mt-2 text-sm text-gray-500">{errorMsg || "An unexpected error occurred."}</p>
        </div>
      </div>
    );
  }

  // ── Valid invite card ────────────────────────────────────────────────────────

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950 px-4">
      <div className="w-full max-w-md space-y-6">

        {/* Invite card */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 shadow-sm">
          <div className="mb-6 text-center">
            <span className="text-lg font-semibold tracking-tight text-gray-900 dark:text-gray-100">
              ProspectIQ
            </span>
          </div>

          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            You&apos;ve been invited to{" "}
            <span className="text-gray-700 dark:text-gray-200">{invite?.workspace_name}</span>
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {invite?.inviter_email} invited you as a{" "}
            <span className="font-medium capitalize">{invite?.role}</span>.
          </p>

          {/* Already signed in → one-click accept */}
          {state === "signed_in" && (
            <button
              onClick={acceptInvite}
              className="mt-6 w-full rounded-md bg-gray-900 dark:bg-gray-100 px-4 py-2.5 text-sm font-medium text-white dark:text-gray-900 transition hover:opacity-90 disabled:opacity-60"
            >
              Accept invitation
            </button>
          )}

          {/* Not signed in → auth form */}
          {(state === "valid" || state === "accepting") && (
            <>
              <div className="mt-5 flex rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden text-xs font-medium">
                <button
                  onClick={() => setAuthMode("signin")}
                  className={`flex-1 py-2 transition ${
                    authMode === "signin"
                      ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                      : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                  }`}
                >
                  Sign in
                </button>
                <button
                  onClick={() => setAuthMode("signup")}
                  className={`flex-1 py-2 transition ${
                    authMode === "signup"
                      ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                      : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                  }`}
                >
                  Create account
                </button>
              </div>

              <form onSubmit={handleAuth} className="mt-4 space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Email
                  </label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-400"
                    placeholder="you@company.com"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Password
                  </label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-400"
                    placeholder={authMode === "signup" ? "Min 8 characters" : "••••••••"}
                  />
                </div>

                {authError && (
                  <p className="text-xs text-red-600 dark:text-red-400">{authError}</p>
                )}

                <button
                  type="submit"
                  disabled={authLoading || state === "accepting"}
                  className="w-full rounded-md bg-gray-900 dark:bg-gray-100 px-4 py-2.5 text-sm font-medium text-white dark:text-gray-900 transition hover:opacity-90 disabled:opacity-60"
                >
                  {authLoading || state === "accepting"
                    ? "Please wait…"
                    : authMode === "signup"
                    ? "Create account & accept"
                    : "Sign in & accept"}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-xs text-gray-400">
          This invite expires in 7 days. If you weren&apos;t expecting this, you can safely ignore it.
        </p>
      </div>
    </div>
  );
}
