"use client";

// Copyright © 2026 ProspectIQ. All rights reserved.
// Authors: Avanish Mehrotra & ProspectIQ Technical Team

import { useState, useEffect, useCallback } from "react";
import {
  Shield,
  ShieldCheck,
  ShieldX,
  LogOut,
  Key,
  Monitor,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Trash2,
  Clock,
  XCircle,
} from "lucide-react";
import { supabase } from "@/lib/supabase";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AuditEvent {
  id: string;
  event_type: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

interface Session {
  id: string;
  event_type: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function getAuthHeader(): Promise<string | null> {
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ? `Bearer ${session.access_token}` : null;
  } catch {
    return null;
  }
}

async function apiCall<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const auth = await getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (auth) headers["Authorization"] = auth;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function formatEventType(type: string): string {
  const labels: Record<string, string> = {
    login_success: "Signed in",
    login_failure: "Failed sign-in attempt",
    logout: "Signed out",
    password_reset_requested: "Password reset requested",
    password_reset_completed: "Password changed",
    session_revoked: "Session revoked",
  };
  return labels[type] || type.replace(/_/g, " ");
}

function eventIcon(type: string) {
  switch (type) {
    case "login_success":
      return <ShieldCheck className="h-4 w-4 text-green-500" />;
    case "login_failure":
      return <ShieldX className="h-4 w-4 text-red-500" />;
    case "logout":
      return <LogOut className="h-4 w-4 text-slate-400" />;
    case "password_reset_requested":
    case "password_reset_completed":
      return <Key className="h-4 w-4 text-blue-500" />;
    case "session_revoked":
      return <XCircle className="h-4 w-4 text-amber-500" />;
    default:
      return <Shield className="h-4 w-4 text-slate-400" />;
  }
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function parseUserAgent(ua: string | null): string {
  if (!ua) return "Unknown device";
  if (/iPhone|iPad/.test(ua)) return "iOS Device";
  if (/Android/.test(ua)) return "Android Device";
  if (/Mac/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  if (/Linux/.test(ua)) return "Linux";
  return "Unknown device";
}

// ---------------------------------------------------------------------------
// Password strength evaluator (mirrors reset-password page logic)
// ---------------------------------------------------------------------------

interface PasswordChecks {
  length: boolean;
  uppercase: boolean;
  lowercase: boolean;
  digit: boolean;
  special: boolean;
}

function evaluatePassword(pw: string): PasswordChecks {
  return {
    length: pw.length >= 10,
    uppercase: /[A-Z]/.test(pw),
    lowercase: /[a-z]/.test(pw),
    digit: /\d/.test(pw),
    special: /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/.test(pw),
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
      <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">{description}</p>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active Sessions section
// ---------------------------------------------------------------------------

function SessionsSection() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeAllLoading, setRevokeAllLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiCall<{ sessions: Session[] }>("/api/auth/sessions");
      setSessions(data.sessions);
    } catch (err) {
      setError((err as Error).message || "Failed to load sessions.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const handleRevoke = async (id: string) => {
    setRevoking(id);
    try {
      await apiCall(`/api/auth/sessions/${id}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError((err as Error).message || "Failed to revoke session.");
    } finally {
      setRevoking(null);
    }
  };

  const handleRevokeAll = async () => {
    const others = sessions.filter((s) => s.event_type === "login_success");
    if (!others.length) return;
    setRevokeAllLoading(true);
    try {
      await Promise.allSettled(
        others.map((s) => apiCall(`/api/auth/sessions/${s.id}`, { method: "DELETE" }))
      );
      await loadSessions();
    } finally {
      setRevokeAllLoading(false);
    }
  };

  const loginSessions = sessions.filter((s) => s.event_type === "login_success");

  return (
    <Card>
      <SectionHeader
        title="Active Sessions"
        description="Devices and locations where you are currently signed in."
      />

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading sessions…
        </div>
      )}

      {!loading && error && (
        <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {!loading && !error && loginSessions.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No active session records found.
        </p>
      )}

      {!loading && loginSessions.length > 0 && (
        <div className="space-y-3">
          {loginSessions.map((session, idx) => (
            <div
              key={session.id}
              className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-800 dark:bg-gray-800/50"
            >
              <div className="flex items-center gap-3">
                <Monitor className="h-5 w-5 text-gray-400" />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {parseUserAgent(session.user_agent)}
                    </span>
                    {idx === 0 && (
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                        Current
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                    {session.ip_address && <span>{session.ip_address}</span>}
                    {session.ip_address && <span>·</span>}
                    <span>{formatDate(session.created_at)}</span>
                  </div>
                </div>
              </div>

              {idx !== 0 && (
                <button
                  onClick={() => handleRevoke(session.id)}
                  disabled={revoking === session.id}
                  className="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-900/20"
                >
                  {revoking === session.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                  Revoke
                </button>
              )}
            </div>
          ))}

          {loginSessions.length > 1 && (
            <button
              onClick={handleRevokeAll}
              disabled={revokeAllLoading}
              className="mt-2 flex items-center gap-1.5 text-sm font-medium text-red-600 hover:text-red-500 disabled:opacity-50 dark:text-red-400"
            >
              {revokeAllLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              Revoke all other sessions
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Recent Activity section
// ---------------------------------------------------------------------------

function ActivitySection() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await apiCall<{ events: AuditEvent[] }>("/api/auth/audit-log");
        setEvents(data.events);
      } catch (err) {
        setError((err as Error).message || "Failed to load activity.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <Card>
      <SectionHeader
        title="Recent Activity"
        description="The last 20 security events on your account."
      />

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading activity…
        </div>
      )}

      {!loading && error && (
        <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {!loading && !error && events.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">No activity recorded yet.</p>
      )}

      {!loading && events.length > 0 && (
        <ol className="relative ml-1 space-y-0 border-l border-gray-200 dark:border-gray-700">
          {events.map((ev) => (
            <li key={ev.id} className="ml-4 pb-5 last:pb-0">
              {/* Timeline dot */}
              <span className="absolute -left-[9px] flex h-4 w-4 items-center justify-center rounded-full bg-white dark:bg-gray-900">
                {eventIcon(ev.event_type)}
              </span>

              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatEventType(ev.event_type)}
                  </p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-500 dark:text-gray-400">
                    {ev.ip_address && <span>{ev.ip_address}</span>}
                    {ev.user_agent && (
                      <span>{parseUserAgent(ev.user_agent)}</span>
                    )}
                  </div>
                </div>

                <div className="flex flex-shrink-0 items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
                  <Clock className="h-3 w-3" />
                  {formatDate(ev.created_at)}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Change Password section
// ---------------------------------------------------------------------------

function ChangePasswordSection() {
  const [open, setOpen] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const checks = evaluatePassword(newPassword);
  const allMet = Object.values(checks).every(Boolean);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!allMet || newPassword !== confirmPassword) return;
    setError("");
    setLoading(true);

    try {
      const { error: supaError } = await supabase.auth.updateUser({
        password: newPassword,
      });
      if (supaError) {
        setError(supaError.message || "Password update failed.");
        return;
      }

      // Also call our backend to log the audit event
      try {
        await apiCall("/api/auth/reset-password", {
          method: "POST",
          body: JSON.stringify({ token: "__supabase_direct__", new_password: newPassword }),
        });
      } catch {
        // Non-fatal — audit log failure should not block the UI success
      }

      setSuccess(true);
      setNewPassword("");
      setConfirmPassword("");
      setTimeout(() => {
        setOpen(false);
        setSuccess(false);
      }, 3000);
    } catch (err) {
      setError((err as Error).message || "Password update failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <SectionHeader
        title="Password"
        description="Update your account password."
      />

      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <Key className="h-4 w-4" />
          Change Password
        </button>
      ) : (
        <form onSubmit={handleSubmit} className="max-w-sm space-y-4">
          {success && (
            <div className="flex items-center gap-2 rounded-md bg-green-50 px-3 py-2 text-sm text-green-600 dark:bg-green-900/20 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4" />
              Password updated successfully.
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
              New password
            </label>
            <input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="••••••••••"
              required
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
            />
            {newPassword.length > 0 && (
              <ul className="mt-2 space-y-1">
                {[
                  [checks.length, "At least 10 characters"],
                  [checks.uppercase, "Uppercase letter"],
                  [checks.lowercase, "Lowercase letter"],
                  [checks.digit, "Number"],
                  [checks.special, "Special character"],
                ].map(([met, label]) => (
                  <li
                    key={label as string}
                    className={`flex items-center gap-1.5 text-xs ${
                      met ? "text-green-600 dark:text-green-400" : "text-gray-400"
                    }`}
                  >
                    {met ? (
                      <CheckCircle2 className="h-3.5 w-3.5" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5" />
                    )}
                    {label as string}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
              Confirm password
            </label>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••••"
              required
              className={`w-full rounded-lg border px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-1 dark:bg-gray-800 dark:text-gray-100 ${
                confirmPassword.length > 0 && confirmPassword !== newPassword
                  ? "border-red-400 focus:border-red-500 focus:ring-red-500"
                  : "border-gray-300 focus:border-blue-500 focus:ring-blue-500 dark:border-gray-700"
              }`}
            />
          </div>

          {error && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </p>
          )}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={loading || !allMet || newPassword !== confirmPassword || !confirmPassword}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Updating…
                </span>
              ) : (
                "Update password"
              )}
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setNewPassword("");
                setConfirmPassword("");
                setError("");
              }}
              className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SecuritySettingsPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Security
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Manage your active sessions, review account activity, and update your
          password.
        </p>
      </div>

      <SessionsSection />
      <ActivitySection />
      <ChangePasswordSection />
    </div>
  );
}
