"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Building2,
  Users,
  Key,
  Copy,
  Trash2,
  Plus,
  Check,
  Loader2,
  AlertCircle,
  BarChart2,
  ClipboardList,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { supabase } from "@/lib/supabase";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

async function authFetch(path: string, options?: RequestInit) {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers as Record<string, string>),
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tier = "starter" | "growth" | "scale";

interface Workspace {
  id: string;
  name: string;
  owner_email: string;
  tier: Tier;
  subscription_status: string;
}

interface Member {
  user_id: string;
  email: string;
  role: string;
  joined_at: string;
}

interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  status: "active" | "revoked";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TIER_COLORS: Record<Tier, string> = {
  starter: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  growth: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  scale: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
};

function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${TIER_COLORS[tier] ?? TIER_COLORS.starter}`}
    >
      {tier}
    </span>
  );
}

function SectionCard({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 mb-6">
      <div className="flex items-center gap-2 mb-5">
        <span className="text-gray-500 dark:text-gray-400">{icon}</span>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-400 mb-4">
      <AlertCircle className="h-4 w-4 flex-shrink-0" />
      {message}
    </div>
  );
}

function formatDate(iso: string | null) {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Section 1: Workspace Info
// ---------------------------------------------------------------------------

function WorkspaceInfoSection() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authFetch("/api/workspaces/me")
      .then((data: { data?: Workspace } | Workspace) => {
        const ws = (data as { data: Workspace }).data ?? (data as Workspace);
        setWorkspace(ws);
        setName(ws.name);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    if (!workspace) return;
    setSaving(true);
    setError(null);
    try {
      await authFetch("/api/workspaces/me", {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      setWorkspace((prev) => (prev ? { ...prev, name } : prev));
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SectionCard icon={<Building2 className="h-5 w-5" />} title="Workspace Info">
      {error && <ErrorBanner message={error} />}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : workspace ? (
        <div className="space-y-5">
          {/* Workspace name */}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
              Workspace name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full max-w-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
            />
          </div>

          {/* Owner email */}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
              Owner email
            </label>
            <p className="text-sm text-gray-700 dark:text-gray-300">
              {workspace.owner_email}
            </p>
          </div>

          {/* Tier + status */}
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                Plan
              </label>
              <TierBadge tier={workspace.tier} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                Subscription status
              </label>
              <span className="text-sm text-gray-700 dark:text-gray-300 capitalize">
                {workspace.subscription_status}
              </span>
            </div>
          </div>

          {/* Save */}
          <div>
            <button
              onClick={handleSave}
              disabled={saving || name === workspace.name}
              className="flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white transition-colors"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : saved ? (
                <Check className="h-4 w-4" />
              ) : null}
              {saved ? "Saved" : "Save changes"}
            </button>
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 2: Members
// ---------------------------------------------------------------------------

function MembersSection() {
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteSent, setInviteSent] = useState(false);

  const fetchMembers = useCallback(() => {
    setLoading(true);
    authFetch("/api/workspaces/me/members")
      .then((data: { data?: Member[] } | Member[]) => {
        const list =
          (data as { data: Member[] }).data ?? (data as Member[]);
        setMembers(list);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchMembers();
  }, [fetchMembers]);

  const handleRemove = async (userId: string) => {
    setRemoving(userId);
    try {
      await authFetch(`/api/workspaces/me/members/${userId}`, {
        method: "DELETE",
      });
      setMembers((prev) => prev.filter((m) => m.user_id !== userId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRemoving(null);
    }
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setInviteError(null);
    try {
      await authFetch("/api/workspaces/me/members/invite", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      setInviteEmail("");
      setInviteRole("member");
      setInviteSent(true);
      setTimeout(() => setInviteSent(false), 3000);
      fetchMembers();
    } catch (e) {
      setInviteError((e as Error).message);
    } finally {
      setInviting(false);
    }
  };

  return (
    <SectionCard icon={<Users className="h-5 w-5" />} title="Members">
      {error && <ErrorBanner message={error} />}

      {/* Members table */}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400 mb-5">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading members…
        </div>
      ) : members.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
          No members yet.
        </p>
      ) : (
        <div className="mb-6 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Email
                </th>
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Role
                </th>
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Joined
                </th>
                <th className="pb-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {members.map((m) => (
                <tr key={m.user_id}>
                  <td className="py-3 text-gray-900 dark:text-gray-100">
                    {m.email}
                  </td>
                  <td className="py-3 capitalize text-gray-600 dark:text-gray-400">
                    {m.role}
                  </td>
                  <td className="py-3 text-gray-600 dark:text-gray-400">
                    {formatDate(m.joined_at)}
                  </td>
                  <td className="py-3 text-right">
                    <button
                      onClick={() => handleRemove(m.user_id)}
                      disabled={removing === m.user_id}
                      className="flex items-center gap-1 ml-auto rounded-md px-2.5 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 transition-colors"
                    >
                      {removing === m.user_id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Invite form */}
      <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
          Invite a member
        </h3>
        {inviteError && <ErrorBanner message={inviteError} />}
        <form onSubmit={handleInvite} className="flex flex-wrap gap-2">
          <input
            type="email"
            placeholder="colleague@company.com"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            required
            className="flex-1 min-w-48 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
          />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value)}
            className="rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="viewer">Viewer</option>
          </select>
          <button
            type="submit"
            disabled={inviting}
            className="flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 text-sm font-medium text-white transition-colors"
          >
            {inviting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : inviteSent ? (
              <Check className="h-4 w-4" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            {inviteSent ? "Invite sent!" : "Invite"}
          </button>
        </form>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 3: API Keys
// ---------------------------------------------------------------------------

function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchKeys = useCallback(() => {
    setLoading(true);
    authFetch("/api/workspaces/api-keys")
      .then((data: { data?: ApiKey[] } | ApiKey[]) => {
        const list =
          (data as { data: ApiKey[] }).data ?? (data as ApiKey[]);
        setKeys(list);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await authFetch("/api/workspaces/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: newKeyName.trim() }),
      });
      const rawKey: string =
        res.key ?? res.data?.key ?? res.data ?? null;
      setRevealedKey(rawKey);
      setNewKeyName("");
      setShowCreateForm(false);
      fetchKeys();
    } catch (e) {
      setCreateError((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setRevoking(keyId);
    try {
      await authFetch(`/api/workspaces/api-keys/${keyId}`, {
        method: "DELETE",
      });
      setKeys((prev) =>
        prev.map((k) =>
          k.id === keyId ? { ...k, status: "revoked" } : k
        )
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRevoking(null);
    }
  };

  const handleCopy = async () => {
    if (!revealedKey) return;
    await navigator.clipboard.writeText(revealedKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <SectionCard icon={<Key className="h-5 w-5" />} title="API Keys">
      {error && <ErrorBanner message={error} />}

      {/* Revealed key banner */}
      {revealedKey && (
        <div className="mb-5 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4">
          <p className="text-xs font-medium text-amber-800 dark:text-amber-300 mb-2">
            Store this key now — it will not be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-white dark:bg-gray-800 border border-amber-200 dark:border-amber-700 px-3 py-2 text-xs font-mono text-gray-900 dark:text-gray-100">
              {revealedKey}
            </code>
            <button
              onClick={handleCopy}
              className="flex-shrink-0 flex items-center gap-1.5 rounded-md border border-amber-300 dark:border-amber-600 bg-white dark:bg-gray-800 px-3 py-2 text-xs font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/30 transition-colors"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={() => setRevealedKey(null)}
              className="flex-shrink-0 rounded-md border border-amber-300 dark:border-amber-600 bg-white dark:bg-gray-800 px-3 py-2 text-xs font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/30 transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Keys table */}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400 mb-5">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading keys…
        </div>
      ) : keys.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
          No API keys yet.
        </p>
      ) : (
        <div className="mb-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Name
                </th>
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Prefix
                </th>
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Created
                </th>
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Last used
                </th>
                <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">
                  Status
                </th>
                <th className="pb-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {keys.map((k) => (
                <tr key={k.id} className={k.status === "revoked" ? "opacity-50" : ""}>
                  <td className="py-3 text-gray-900 dark:text-gray-100">
                    {k.name}
                  </td>
                  <td className="py-3 font-mono text-xs text-gray-600 dark:text-gray-400">
                    {k.prefix}…
                  </td>
                  <td className="py-3 text-gray-600 dark:text-gray-400">
                    {formatDate(k.created_at)}
                  </td>
                  <td className="py-3 text-gray-600 dark:text-gray-400">
                    {formatDate(k.last_used_at)}
                  </td>
                  <td className="py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        k.status === "active"
                          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                          : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500"
                      }`}
                    >
                      {k.status}
                    </span>
                  </td>
                  <td className="py-3 text-right">
                    {k.status === "active" && (
                      <button
                        onClick={() => handleRevoke(k.id)}
                        disabled={revoking === k.id}
                        className="flex items-center gap-1 ml-auto rounded-md px-2.5 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 transition-colors"
                      >
                        {revoking === k.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create key */}
      {!showCreateForm ? (
        <button
          onClick={() => setShowCreateForm(true)}
          className="flex items-center gap-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Create API key
        </button>
      ) : (
        <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
            New API key
          </h3>
          {createError && <ErrorBanner message={createError} />}
          <form onSubmit={handleCreate} className="flex gap-2">
            <input
              type="text"
              placeholder="Key name (e.g. production)"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              required
              autoFocus
              className="flex-1 min-w-48 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
            />
            <button
              type="submit"
              disabled={creating}
              className="flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 text-sm font-medium text-white transition-colors"
            >
              {creating && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </button>
            <button
              type="button"
              onClick={() => {
                setShowCreateForm(false);
                setNewKeyName("");
                setCreateError(null);
              }}
              className="rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
          </form>
        </div>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function SettingsNav({ active }: { active: "workspace" | "billing" }) {
  const tabs = [
    { label: "Workspace", href: "/settings/workspace", key: "workspace" },
    { label: "Billing", href: "/settings/billing", key: "billing" },
  ];
  return (
    <div className="mb-6 border-b border-gray-200 dark:border-gray-800">
      <div className="flex gap-0">
        {tabs.map((t) => (
          <a
            key={t.key}
            href={t.href}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              active === t.key
                ? "border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {t.label}
          </a>
        ))}
      </div>
    </div>
  );
}

export default function WorkspaceSettingsPage() {
  return (
    <div>
      <SettingsNav active="workspace" />
      <WorkspaceInfoSection />
      <MembersSection />
      <ApiKeysSection />
      <UsageSection />
      <AuditLogSection />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 4: Usage & Limits
// ---------------------------------------------------------------------------

interface UsageData {
  period_start: string;
  companies: { total: number; qualified: number };
  contacts: { total: number };
  outreach: { sent_this_month: number; drafts_pending_approval: number };
  api_cost_usd_this_month: number;
  members: { active: number; pending_invite: number };
}

function UsageSection() {
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    authFetch("/api/workspaces/me/usage")
      .then((data: UsageData) => setUsage(data))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <SectionCard icon={<BarChart2 className="h-5 w-5" />} title="Usage this month">
      {error && <ErrorBanner message={error} />}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading usage…
        </div>
      ) : usage ? (
        <>
          <p className="mb-4 text-xs text-gray-400 dark:text-gray-500">
            Period starting {new Date(usage.period_start).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
          </p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatTile label="Total companies" value={usage.companies.total} />
            <StatTile label="Qualified" value={usage.companies.qualified} />
            <StatTile label="Contacts" value={usage.contacts.total} />
            <StatTile label="Emails sent" value={usage.outreach.sent_this_month} />
            <StatTile label="Drafts pending" value={usage.outreach.drafts_pending_approval} />
            <StatTile
              label="AI cost this month"
              value={`$${usage.api_cost_usd_this_month.toFixed(2)}`}
            />
            <StatTile label="Active members" value={usage.members.active} />
            <StatTile label="Pending invites" value={usage.members.pending_invite} />
          </div>
        </>
      ) : null}
    </SectionCard>
  );
}

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 p-4">
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 5: Audit Log
// ---------------------------------------------------------------------------

interface AuditEntry {
  id: string;
  action: string;
  user_email: string | null;
  resource_type: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

const ACTION_LABELS: Record<string, string> = {
  "member.invited": "Invited member",
  "member.removed": "Removed member",
  "api_key.created": "Created API key",
  "api_key.revoked": "Revoked API key",
};

function AuditLogSection() {
  const PAGE_SIZE = 20;
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(
    async (off: number) => {
      setLoading(true);
      setError(null);
      try {
        const data: { total: number; items: AuditEntry[] } = await authFetch(
          `/api/workspaces/me/audit-log?limit=${PAGE_SIZE}&offset=${off}`
        );
        setEntries(data.items);
        setTotal(data.total);
        setOffset(off);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    fetchPage(0);
  }, [fetchPage]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <SectionCard icon={<ClipboardList className="h-5 w-5" />} title="Audit log">
      {error && <ErrorBanner message={error} />}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : entries.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500">No audit events yet.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-800">
                  <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">Action</th>
                  <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">By</th>
                  <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">Detail</th>
                  <th className="pb-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {entries.map((e) => (
                  <tr key={e.id}>
                    <td className="py-2.5 pr-4 text-gray-900 dark:text-gray-100 whitespace-nowrap">
                      {ACTION_LABELS[e.action] ?? e.action}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                      {e.user_email ?? "system"}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-500 dark:text-gray-400 text-xs">
                      {e.metadata && Object.keys(e.metadata).length > 0
                        ? Object.entries(e.metadata)
                            .filter(([, v]) => v !== null && v !== undefined)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(" · ")
                        : e.resource_type ?? "—"}
                    </td>
                    <td className="py-2.5 text-gray-400 dark:text-gray-500 text-xs whitespace-nowrap">
                      {new Date(e.created_at).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
              <span>
                Page {currentPage} of {totalPages} ({total} events)
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => fetchPage(offset - PAGE_SIZE)}
                  disabled={offset === 0 || loading}
                  className="rounded p-1 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  onClick={() => fetchPage(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total || loading}
                  className="rounded p-1 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}
