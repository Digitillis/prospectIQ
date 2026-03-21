"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Bell,
  BellOff,
  CheckCircle2,
  ExternalLink,
  Loader2,
  AlertCircle,
  ArrowLeft,
  Send,
  Slack,
  XCircle,
} from "lucide-react";
import { testSlack } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NotificationToggle {
  key: string;
  label: string;
  description: string;
  defaultEnabled: boolean;
}

const NOTIFICATION_TOGGLES: NotificationToggle[] = [
  {
    key: "notify_research_complete",
    label: "Research agent completions",
    description: "Sends a summary when the research agent finishes a batch (companies researched, skipped, errors, cost).",
    defaultEnabled: true,
  },
  {
    key: "notify_qualification_complete",
    label: "Qualification agent completions",
    description: "Sends a summary when the qualification agent finishes scoring a batch (qualified vs disqualified counts).",
    defaultEnabled: true,
  },
  {
    key: "notify_hot_replies",
    label: "Hot replies",
    description: "Instant alert when a prospect replies to your outreach email — name, email address, and a link to their dashboard profile.",
    defaultEnabled: true,
  },
  {
    key: "notify_outreach_sent",
    label: "Outreach batch sent",
    description: "Notification when approved drafts are dispatched via Instantly.ai.",
    defaultEnabled: false,
  },
  {
    key: "notify_draft_approvals",
    label: "Draft approvals pending",
    description: "Reminder when there are outreach drafts waiting for your approval.",
    defaultEnabled: false,
  },
];

const STORAGE_KEY = "prospectiq_notification_prefs";

function loadPrefs(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function savePrefs(prefs: Record<string, boolean>) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ToggleRow({
  toggle,
  enabled,
  onChange,
}: {
  toggle: NotificationToggle;
  enabled: boolean;
  onChange: (key: string, value: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-4">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-900">{toggle.label}</p>
        <p className="mt-0.5 text-sm text-gray-500">{toggle.description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        onClick={() => onChange(toggle.key, !enabled)}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2",
          enabled ? "bg-indigo-600" : "bg-gray-200"
        )}
      >
        <span
          className={cn(
            "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
            enabled ? "translate-x-5" : "translate-x-0"
          )}
        />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function NotificationsSettingsPage() {
  const [prefs, setPrefs] = useState<Record<string, boolean>>({});
  const [testStatus, setTestStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [testError, setTestError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  // Load prefs from localStorage on mount
  useEffect(() => {
    const stored = loadPrefs();
    const initial: Record<string, boolean> = {};
    for (const t of NOTIFICATION_TOGGLES) {
      initial[t.key] = stored[t.key] !== undefined ? stored[t.key] : t.defaultEnabled;
    }
    setPrefs(initial);
    setMounted(true);
  }, []);

  function handleToggle(key: string, value: boolean) {
    const updated = { ...prefs, [key]: value };
    setPrefs(updated);
    savePrefs(updated);
  }

  async function handleTestSlack() {
    setTestStatus("loading");
    setTestError(null);
    try {
      await testSlack();
      setTestStatus("success");
    } catch (err) {
      setTestStatus("error");
      setTestError(
        err instanceof Error
          ? err.message
          : "Test failed. Ensure SLACK_WEBHOOK_URL is set on the server."
      );
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Notification Settings</h2>
        <p className="mt-1 text-sm text-gray-500">
          Configure Slack alerts for agent completions, hot replies, and pipeline events.
        </p>
      </div>

      {/* Slack webhook status card */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#4A154B]/10">
            {/* Slack brand colour */}
            <Slack className="h-5 w-5 text-[#4A154B]" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-gray-900">Slack Webhook</h3>
            <p className="mt-1 text-sm text-gray-600">
              ProspectIQ uses an incoming Slack webhook URL to post notifications.
              The URL is configured via the{" "}
              <code className="rounded bg-gray-100 px-1 py-0.5 text-xs font-mono text-gray-700">
                SLACK_WEBHOOK_URL
              </code>{" "}
              environment variable on the server.
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              {/* Test button */}
              <button
                onClick={handleTestSlack}
                disabled={testStatus === "loading"}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {testStatus === "loading" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                {testStatus === "loading" ? "Sending…" : "Send Test Notification"}
              </button>

              {/* Setup docs link */}
              <a
                href="https://api.slack.com/messaging/webhooks"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
              >
                Webhook setup guide
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </div>

            {/* Test result banners */}
            {testStatus === "success" && (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-2.5 text-sm text-green-700">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                Test message sent successfully. Check your Slack channel.
              </div>
            )}
            {testStatus === "error" && (
              <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{testError}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Notification type toggles */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-6 py-4">
          <h3 className="text-base font-semibold text-gray-900">Notification Types</h3>
          <p className="mt-0.5 text-sm text-gray-500">
            Toggle which events trigger a Slack message. Preferences are saved in your browser.
          </p>
        </div>

        <div className="divide-y divide-gray-100 px-6">
          {mounted ? (
            NOTIFICATION_TOGGLES.map((toggle) => (
              <ToggleRow
                key={toggle.key}
                toggle={toggle}
                enabled={prefs[toggle.key] ?? toggle.defaultEnabled}
                onChange={handleToggle}
              />
            ))
          ) : (
            // SSR skeleton
            <div className="space-y-4 py-4">
              {NOTIFICATION_TOGGLES.map((t) => (
                <div key={t.key} className="h-10 animate-pulse rounded-lg bg-gray-100" />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Events reference card */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <h3 className="mb-4 flex items-center gap-2 text-base font-semibold text-gray-900">
          <Bell className="h-5 w-5 text-indigo-500" />
          What triggers a notification?
        </h3>
        <ul className="space-y-3 text-sm text-gray-600">
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
            <span>
              <strong className="font-medium text-gray-900">Research complete</strong> — posted at
              the end of each research agent run with a count of companies researched, skipped,
              errors, and total API cost.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
            <span>
              <strong className="font-medium text-gray-900">Qualification complete</strong> — posted
              at the end of each qualification run with qualified vs disqualified counts.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-orange-500" />
            <span>
              <strong className="font-medium text-gray-900">Hot reply</strong> — instant alert when
              Instantly.ai reports a{" "}
              <code className="rounded bg-gray-100 px-1 py-0.5 text-xs font-mono">reply_received</code>{" "}
              event. Includes the company name and prospect email address.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <BellOff className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
            <span>
              <strong className="font-medium text-gray-900">Outreach sent / Draft approvals</strong>{" "}
              — disabled by default. Enable above if you want per-batch send confirmations or
              approval reminders.
            </span>
          </li>
        </ul>

        <div className="mt-4 rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <strong>Note:</strong> Toggle preferences are stored locally in your browser. The actual
          Slack webhook URL must be set as{" "}
          <code className="rounded bg-amber-100 px-1 py-0.5 text-xs font-mono">
            SLACK_WEBHOOK_URL
          </code>{" "}
          in the server environment. If the variable is not set, all notifications are silently
          skipped regardless of toggle state.
        </div>
      </div>

      {/* Back to settings */}
      <div className="rounded-xl border border-gray-200 bg-gray-50 p-5">
        <div className="flex items-start gap-3">
          <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-gray-400" />
          <div>
            <p className="text-sm font-semibold text-gray-700">Back to Settings</p>
            <p className="mt-1 text-sm text-gray-500">
              Manage your ICP, scoring weights, and outreach sequences from the main settings page.
            </p>
            <Link
              href="/settings"
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-white transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Settings
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
