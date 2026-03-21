"use client";
import { useState, useEffect } from "react";

export interface AutomationRule {
  id: string;
  name: string;
  enabled: boolean;
  trigger: {
    event: "status_change" | "pqs_update" | "research_complete" | "qualification_complete";
    condition: { field: string; operator: string; value: string };
  };
  action: {
    type: string;
    params: Record<string, string>;
  };
  createdAt: string;
  lastTriggered?: string;
  triggerCount: number;
}

const DEFAULT_RULES: AutomationRule[] = [
  {
    id: "default-1",
    name: "Auto-flag hot prospects",
    enabled: true,
    trigger: {
      event: "pqs_update",
      condition: { field: "pqs_total", operator: "greater_than", value: "70" },
    },
    action: { type: "flag_priority", params: {} },
    createdAt: new Date().toISOString(),
    triggerCount: 0,
  },
  {
    id: "default-2",
    name: "Auto-qualify after research",
    enabled: false,
    trigger: {
      event: "status_change",
      condition: { field: "status", operator: "equals", value: "researched" },
    },
    action: { type: "run_agent", params: { agent: "qualification" } },
    createdAt: new Date().toISOString(),
    triggerCount: 0,
  },
  {
    id: "default-3",
    name: "Notify on engagement",
    enabled: true,
    trigger: {
      event: "status_change",
      condition: { field: "status", operator: "equals", value: "engaged" },
    },
    action: { type: "notify_slack", params: { message: "New engaged prospect!" } },
    createdAt: new Date().toISOString(),
    triggerCount: 0,
  },
];

export function useAutomations() {
  const [rules, setRules] = useState<AutomationRule[]>(() => {
    if (typeof window === "undefined") return DEFAULT_RULES;
    const stored = localStorage.getItem("prospectiq-automations");
    return stored ? JSON.parse(stored) : DEFAULT_RULES;
  });

  useEffect(() => {
    localStorage.setItem("prospectiq-automations", JSON.stringify(rules));
  }, [rules]);

  const addRule = (
    rule: Omit<AutomationRule, "id" | "createdAt" | "triggerCount">
  ) => {
    setRules((prev) => [
      ...prev,
      {
        ...rule,
        id: Date.now().toString(),
        createdAt: new Date().toISOString(),
        triggerCount: 0,
      },
    ]);
  };

  const toggleRule = (id: string) => {
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r))
    );
  };

  const deleteRule = (id: string) => {
    setRules((prev) => prev.filter((r) => r.id !== id));
  };

  const updateRule = (id: string, updates: Partial<AutomationRule>) => {
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, ...updates } : r))
    );
  };

  return { rules, addRule, toggleRule, deleteRule, updateRule };
}
