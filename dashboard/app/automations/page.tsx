"use client";

/**
 * Automation Rules — Configure triggers that run pipeline steps automatically
 *
 * Expected actions:
 * Create rules (e.g., auto-research when PQS > 10), enable/disable automations, set schedules
 */


import { useState } from "react";
import { Zap, Trash2, Plus, X, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAutomations, AutomationRule } from "@/lib/use-automations";

// ── Helpers ────────────────────────────────────────────────────────────────

const EVENT_LABELS: Record<string, string> = {
  status_change: "Status Change",
  pqs_update: "PQS Updated",
  research_complete: "Research Complete",
  qualification_complete: "Qualification Complete",
};

const FIELD_LABELS: Record<string, string> = {
  status: "Status",
  pqs_total: "PQS Total",
  tier: "Tier",
  pqs_firmographic: "PQS Firmographic",
};

const OPERATOR_LABELS: Record<string, string> = {
  equals: "equals",
  greater_than: "is greater than",
  less_than: "is less than",
  contains: "contains",
};

const ACTION_LABELS: Record<string, string> = {
  flag_priority: "Flag as Priority",
  change_status: "Change Status",
  run_agent: "Run Agent",
  notify_slack: "Notify Slack",
  add_tag: "Add Tag",
};

function describeCondition(trigger: AutomationRule["trigger"]): string {
  const event = EVENT_LABELS[trigger.event] ?? trigger.event;
  const field = FIELD_LABELS[trigger.condition.field] ?? trigger.condition.field;
  const op = OPERATOR_LABELS[trigger.condition.operator] ?? trigger.condition.operator;
  return `${event} · ${field} ${op} "${trigger.condition.value}"`;
}

function describeAction(action: AutomationRule["action"]): string {
  const type = ACTION_LABELS[action.type] ?? action.type;
  switch (action.type) {
    case "run_agent":
      return `${type} → ${action.params.agent ?? ""}`;
    case "change_status":
      return `${type} → ${action.params.status ?? ""}`;
    case "notify_slack":
      return `${type} · "${action.params.message ?? ""}"`;
    case "add_tag":
      return `${type} · #${action.params.tag ?? ""}`;
    default:
      return type;
  }
}

function formatTimeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Add Rule Form ──────────────────────────────────────────────────────────

const TRIGGER_EVENTS = [
  { value: "status_change", label: "Status Change" },
  { value: "pqs_update", label: "PQS Updated" },
  { value: "research_complete", label: "Research Complete" },
  { value: "qualification_complete", label: "Qualification Complete" },
];

const CONDITION_FIELDS = [
  { value: "status", label: "Status" },
  { value: "pqs_total", label: "PQS Total" },
  { value: "tier", label: "Tier" },
  { value: "pqs_firmographic", label: "PQS Firmographic" },
];

const CONDITION_OPERATORS = [
  { value: "equals", label: "equals" },
  { value: "greater_than", label: "greater than" },
  { value: "less_than", label: "less than" },
  { value: "contains", label: "contains" },
];

const ACTION_TYPES = [
  { value: "flag_priority", label: "Flag Priority" },
  { value: "change_status", label: "Change Status" },
  { value: "run_agent", label: "Run Agent" },
  { value: "notify_slack", label: "Notify Slack" },
  { value: "add_tag", label: "Add Tag" },
];

const STATUS_OPTIONS = [
  "new", "researching", "researched", "qualifying", "qualified",
  "engaged", "meeting_set", "closed_won", "closed_lost", "nurture",
];

const AGENT_OPTIONS = [
  { value: "research", label: "Research Agent" },
  { value: "qualification", label: "Qualification Agent" },
  { value: "outreach", label: "Outreach Agent" },
];

interface FormState {
  name: string;
  event: string;
  conditionField: string;
  conditionOperator: string;
  conditionValue: string;
  actionType: string;
  actionStatus: string;
  actionAgent: string;
  actionSlackMessage: string;
  actionTag: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  event: "status_change",
  conditionField: "status",
  conditionOperator: "equals",
  conditionValue: "",
  actionType: "flag_priority",
  actionStatus: "researched",
  actionAgent: "research",
  actionSlackMessage: "",
  actionTag: "",
};

function AddRuleForm({
  onSave,
  onCancel,
}: {
  onSave: (rule: Omit<AutomationRule, "id" | "createdAt" | "triggerCount">) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});

  const set = (key: keyof FormState) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function buildActionParams(): Record<string, string> {
    switch (form.actionType) {
      case "change_status": return { status: form.actionStatus };
      case "run_agent":     return { agent: form.actionAgent };
      case "notify_slack":  return { message: form.actionSlackMessage };
      case "add_tag":       return { tag: form.actionTag };
      default:              return {};
    }
  }

  function validate(): boolean {
    const errs: typeof errors = {};
    if (!form.name.trim()) errs.name = "Name is required";
    if (!form.conditionValue.trim()) errs.conditionValue = "Value is required";
    if (form.actionType === "notify_slack" && !form.actionSlackMessage.trim())
      errs.actionSlackMessage = "Message is required";
    if (form.actionType === "add_tag" && !form.actionTag.trim())
      errs.actionTag = "Tag name is required";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function handleSave() {
    if (!validate()) return;
    onSave({
      name: form.name.trim(),
      enabled: true,
      trigger: {
        event: form.event as AutomationRule["trigger"]["event"],
        condition: {
          field: form.conditionField,
          operator: form.conditionOperator,
          value: form.conditionValue.trim(),
        },
      },
      action: {
        type: form.actionType,
        params: buildActionParams(),
      },
    });
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="mb-5 flex items-center justify-between">
        <h3 className="font-semibold text-gray-900">New Automation Rule</h3>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-4">
        {/* Rule name */}
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-700">Rule Name</label>
          <input
            value={form.name}
            onChange={set("name")}
            placeholder="e.g. Auto-flag hot prospects"
            className={cn(
              "w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500",
              errors.name ? "border-red-400" : "border-gray-300"
            )}
          />
          {errors.name && <p className="mt-1 text-xs text-red-500">{errors.name}</p>}
        </div>

        {/* Trigger section */}
        <div className="rounded-lg bg-blue-50 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-blue-700">
            Trigger — When…
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs text-gray-600">Event</label>
              <div className="relative">
                <select
                  value={form.event}
                  onChange={set("event")}
                  className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {TRIGGER_EVENTS.map((e) => (
                    <option key={e.value} value={e.value}>{e.label}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-600">Field</label>
              <div className="relative">
                <select
                  value={form.conditionField}
                  onChange={set("conditionField")}
                  className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {CONDITION_FIELDS.map((f) => (
                    <option key={f.value} value={f.value}>{f.label}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-600">Operator</label>
              <div className="relative">
                <select
                  value={form.conditionOperator}
                  onChange={set("conditionOperator")}
                  className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {CONDITION_OPERATORS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
              </div>
            </div>
          </div>
          <div className="mt-3">
            <label className="mb-1 block text-xs text-gray-600">Value</label>
            <input
              value={form.conditionValue}
              onChange={set("conditionValue")}
              placeholder={
                form.conditionField === "pqs_total" ? "e.g. 70" :
                form.conditionField === "status" ? "e.g. engaged" :
                form.conditionField === "tier" ? "e.g. enterprise" :
                "Enter value…"
              }
              className={cn(
                "w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500",
                errors.conditionValue ? "border-red-400" : "border-gray-300"
              )}
            />
            {errors.conditionValue && (
              <p className="mt-1 text-xs text-red-500">{errors.conditionValue}</p>
            )}
          </div>
        </div>

        {/* Action section */}
        <div className="rounded-lg bg-green-50 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-green-700">
            Action — Then…
          </p>
          <div>
            <label className="mb-1 block text-xs text-gray-600">Action Type</label>
            <div className="relative">
              <select
                value={form.actionType}
                onChange={set("actionType")}
                className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm outline-none focus:ring-2 focus:ring-green-500"
              >
                {ACTION_TYPES.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
            </div>
          </div>

          {/* Dynamic params */}
          {form.actionType === "change_status" && (
            <div className="mt-3">
              <label className="mb-1 block text-xs text-gray-600">Target Status</label>
              <div className="relative">
                <select
                  value={form.actionStatus}
                  onChange={set("actionStatus")}
                  className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm outline-none focus:ring-2 focus:ring-green-500"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
              </div>
            </div>
          )}

          {form.actionType === "run_agent" && (
            <div className="mt-3">
              <label className="mb-1 block text-xs text-gray-600">Agent</label>
              <div className="relative">
                <select
                  value={form.actionAgent}
                  onChange={set("actionAgent")}
                  className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm outline-none focus:ring-2 focus:ring-green-500"
                >
                  {AGENT_OPTIONS.map((a) => (
                    <option key={a.value} value={a.value}>{a.label}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-400" />
              </div>
            </div>
          )}

          {form.actionType === "notify_slack" && (
            <div className="mt-3">
              <label className="mb-1 block text-xs text-gray-600">Slack Message</label>
              <input
                value={form.actionSlackMessage}
                onChange={set("actionSlackMessage")}
                placeholder="e.g. New hot prospect detected!"
                className={cn(
                  "w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-green-500",
                  errors.actionSlackMessage ? "border-red-400" : "border-gray-300"
                )}
              />
              {errors.actionSlackMessage && (
                <p className="mt-1 text-xs text-red-500">{errors.actionSlackMessage}</p>
              )}
            </div>
          )}

          {form.actionType === "add_tag" && (
            <div className="mt-3">
              <label className="mb-1 block text-xs text-gray-600">Tag Name</label>
              <input
                value={form.actionTag}
                onChange={set("actionTag")}
                placeholder="e.g. hot-lead"
                className={cn(
                  "w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-green-500",
                  errors.actionTag ? "border-red-400" : "border-gray-300"
                )}
              />
              {errors.actionTag && (
                <p className="mt-1 text-xs text-red-500">{errors.actionTag}</p>
              )}
            </div>
          )}
        </div>

        {/* Buttons */}
        <div className="flex items-center justify-end gap-3 pt-1">
          <button
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Save Rule
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Rule Card ──────────────────────────────────────────────────────────────

function RuleCard({
  rule,
  onToggle,
  onDelete,
}: {
  rule: AutomationRule;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-5 shadow-sm transition-all",
        rule.enabled
          ? "border-l-4 border-l-green-500"
          : "border-gray-200 opacity-60"
      )}
    >
      <div className="flex items-start gap-4">
        {/* Toggle */}
        <button
          onClick={onToggle}
          title={rule.enabled ? "Disable rule" : "Enable rule"}
          className={cn(
            "relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1",
            rule.enabled
              ? "bg-green-500 focus:ring-green-500"
              : "bg-gray-300 focus:ring-gray-400"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
              rule.enabled ? "translate-x-4" : "translate-x-0.5"
            )}
          />
        </button>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <h4 className="truncate font-medium text-gray-900">{rule.name}</h4>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-gray-600">
            <span className="shrink-0 rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
              When
            </span>
            <span className="truncate">{describeCondition(rule.trigger)}</span>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-gray-600">
            <span className="shrink-0 rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
              Then
            </span>
            <span className="truncate">{describeAction(rule.action)}</span>
          </div>

          {rule.triggerCount > 0 && (
            <p className="mt-2 text-xs text-gray-400">
              Triggered {rule.triggerCount} time{rule.triggerCount !== 1 ? "s" : ""}
              {rule.lastTriggered && ` · Last: ${formatTimeAgo(rule.lastTriggered)}`}
            </p>
          )}
          {rule.triggerCount === 0 && (
            <p className="mt-2 text-xs text-gray-400">Never triggered</p>
          )}
        </div>

        {/* Delete */}
        <div className="shrink-0">
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Delete?</span>
              <button
                onClick={onDelete}
                className="rounded bg-red-500 px-2 py-1 text-xs font-medium text-white hover:bg-red-600"
              >
                Yes
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="rounded bg-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-300"
              >
                No
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              title="Delete rule"
              className="text-gray-400 hover:text-red-500"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function AutomationsPage() {
  const { rules, addRule, toggleRule, deleteRule } = useAutomations();
  const [showForm, setShowForm] = useState(false);

  const enabledCount = rules.filter((r) => r.enabled).length;

  function handleSave(
    rule: Omit<AutomationRule, "id" | "createdAt" | "triggerCount">
  ) {
    addRule(rule);
    setShowForm(false);
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-yellow-100">
            <Zap className="h-5 w-5 text-yellow-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Automations</h1>
            <p className="text-sm text-gray-500">
              Set up rules to automate repetitive tasks
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowForm(true)}
          disabled={showForm}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Add Rule
        </button>
      </div>

      {/* Stats bar */}
      <div className="mb-6 flex gap-4">
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm shadow-sm">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          <span className="font-medium text-gray-700">{enabledCount}</span>
          <span className="text-gray-500">active</span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm shadow-sm">
          <span className="h-2 w-2 rounded-full bg-gray-300" />
          <span className="font-medium text-gray-700">{rules.length - enabledCount}</span>
          <span className="text-gray-500">disabled</span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm shadow-sm">
          <Zap className="h-3.5 w-3.5 text-yellow-500" />
          <span className="font-medium text-gray-700">
            {rules.reduce((sum, r) => sum + r.triggerCount, 0)}
          </span>
          <span className="text-gray-500">total triggers</span>
        </div>
      </div>

      {/* Add rule form (inline) */}
      {showForm && (
        <div className="mb-6">
          <AddRuleForm
            onSave={handleSave}
            onCancel={() => setShowForm(false)}
          />
        </div>
      )}

      {/* Rules list */}
      {rules.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 py-16 text-center">
          <Zap className="mb-3 h-8 w-8 text-gray-300" />
          <p className="font-medium text-gray-500">No automation rules yet</p>
          <p className="mt-1 text-sm text-gray-400">
            Click &ldquo;Add Rule&rdquo; to create your first automation.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Enabled rules first */}
          {rules
            .slice()
            .sort((a, b) => Number(b.enabled) - Number(a.enabled))
            .map((rule) => (
              <RuleCard
                key={rule.id}
                rule={rule}
                onToggle={() => toggleRule(rule.id)}
                onDelete={() => deleteRule(rule.id)}
              />
            ))}
        </div>
      )}

      {/* Footer note */}
      <p className="mt-8 text-center text-xs text-gray-400">
        Rules are stored locally and define automation intent. Backend evaluation
        will be applied to each pipeline event in a future release.
      </p>
    </div>
  );
}
