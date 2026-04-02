/**
 * TypeScript types for the Visual Sequence Builder.
 */

// Step type discriminator
export type StepType = "email" | "wait" | "condition" | "linkedin" | "task";

// Wait condition options
export type WaitCondition = "no_reply" | "no_open" | "any";

// Condition branch trigger options
export type ConditionType = "if_opened" | "if_replied" | "if_clicked" | "if_pqs_above";

export interface SequenceStepV2 {
  step_id: string;           // uuid, client-generated
  step_type: StepType;
  step_order: number;        // 1-based position

  // Email step fields
  subject_template?: string;
  body_template?: string;
  persona_variants?: Record<string, string>; // { persona_key: body_template }

  // Wait step fields
  wait_days?: number;
  wait_condition?: WaitCondition;

  // Condition branch fields
  condition_type?: ConditionType;
  condition_value?: number | string;
  branch_yes?: string;  // step_id
  branch_no?: string;   // step_id

  // Task step fields
  task_description?: string;
  task_due_offset_days?: number;

  metadata: Record<string, unknown>;
}

export interface SequenceDefinitionV2 {
  id?: string;
  name: string;
  description?: string;
  cluster?: string;
  persona?: string;
  steps: SequenceStepV2[];
  is_template: boolean;
  tags: string[];
  source?: "yaml" | "custom" | "builder";
  is_active?: boolean;
  created_at?: string;
  updated_at?: string;
  // Legacy fields present when fetched from merged list
  display_name?: string;
  channel?: string;
  total_steps?: number;
}

export interface SequenceTemplate {
  name: string;
  display_name: string;
  description?: string;
  channel: string;
  total_steps: number;
  steps: SequenceStepV2[];
  source: "yaml" | "custom";
  is_active: boolean;
  id?: string;
  created_at?: string;
  is_template?: boolean;
  tags?: string[];
}

export interface SequenceStats {
  sequence_id: string;
  enrolled_count: number;
  active_count: number;
  open_rate: number;       // 0-1
  reply_rate: number;      // 0-1
  click_rate: number;      // 0-1
  conversion_rate: number; // 0-1
  completed_count: number;
  bounced_count: number;
}

export interface RenderedStep {
  step_id: string;
  step_type: StepType;
  step_order: number;
  subject?: string;
  body?: string;
  wait_days?: number;
  wait_condition?: WaitCondition;
  condition_type?: ConditionType;
  task_description?: string;
}

export interface RenderedSequence {
  sequence_id: string;
  contact_id: string;
  company_id: string;
  contact_name?: string;
  company_name?: string;
  steps: RenderedStep[];
}

// UI-only helpers

export interface StepPaletteItem {
  type: StepType;
  label: string;
  icon: string;
  colorClass: string;
}

export const STEP_PALETTE: StepPaletteItem[] = [
  { type: "email",     label: "Email Step",        icon: "Mail",       colorClass: "text-blue-600 bg-blue-50 dark:bg-blue-900/20 dark:text-blue-400" },
  { type: "wait",      label: "Wait",               icon: "Clock",      colorClass: "text-gray-600 bg-gray-100 dark:bg-gray-700 dark:text-gray-300" },
  { type: "condition", label: "Condition Branch",   icon: "GitBranch",  colorClass: "text-purple-600 bg-purple-50 dark:bg-purple-900/20 dark:text-purple-400" },
  { type: "task",      label: "Task Reminder",      icon: "ClipboardList", colorClass: "text-orange-600 bg-orange-50 dark:bg-orange-900/20 dark:text-orange-400" },
  { type: "linkedin",  label: "LinkedIn Message",   icon: "Linkedin",   colorClass: "text-sky-600 bg-sky-50 dark:bg-sky-900/20 dark:text-sky-400" },
];

export const STEP_TYPE_LABELS: Record<StepType, string> = {
  email: "Email Step",
  wait: "Wait",
  condition: "Condition Branch",
  task: "Task Reminder",
  linkedin: "LinkedIn Message",
};

export const TEMPLATE_VARIABLES = [
  { name: "{first_name}",            desc: "Contact first name" },
  { name: "{last_name}",             desc: "Contact last name" },
  { name: "{company_name}",          desc: "Company name" },
  { name: "{industry}",              desc: "Industry / vertical" },
  { name: "{pain_signal_1}",         desc: "Top pain signal" },
  { name: "{personalization_hook_1}", desc: "AI personalization hook" },
  { name: "{trigger_event_1}",       desc: "Recent trigger event" },
  { name: "{title}",                 desc: "Contact job title" },
  { name: "{value_prop}",            desc: "Core value proposition" },
];
