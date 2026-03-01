const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";

async function fetchAPI<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.text();
    throw new Error(`API error ${res.status}: ${error}`);
  }
  return res.json();
}

// Companies
export const getCompanies = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return fetchAPI<{ data: Company[]; count: number }>(`/api/companies${qs}`);
};

export const getCompany = (id: string) =>
  fetchAPI<{ data: CompanyDetail }>(`/api/companies/${id}`);

export const updateCompany = (id: string, data: Record<string, unknown>) =>
  fetchAPI(`/api/companies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const createCompany = (data: {
  name: string;
  domain?: string;
  website?: string;
  industry?: string;
  sub_sector?: string;
  tier?: string;
  state?: string;
  employee_count?: number;
  revenue_range?: string;
  contact?: {
    full_name?: string;
    email?: string;
    title?: string;
    is_decision_maker?: boolean;
  };
}) =>
  fetchAPI<{ data: Company & { contact: Contact | null } }>("/api/companies", {
    method: "POST",
    body: JSON.stringify(data),
  });

// Contacts
export const createContact = (
  companyId: string,
  data: {
    full_name?: string;
    first_name?: string;
    last_name?: string;
    email?: string;
    title?: string;
    phone?: string;
    linkedin_url?: string;
    seniority?: string;
    department?: string;
    persona_type?: string;
    is_decision_maker?: boolean;
  }
) =>
  fetchAPI<{ data: Contact }>(`/api/companies/${companyId}/contacts`, {
    method: "POST",
    body: JSON.stringify(data),
  });

// Interactions
export const addNote = (companyId: string, body: string, subject?: string) =>
  fetchAPI(`/api/companies/${companyId}/interactions`, {
    method: "POST",
    body: JSON.stringify({ type: "note", body, subject }),
  });

// Approvals
export const getPendingDrafts = () =>
  fetchAPI<{ data: OutreachDraft[]; count: number }>("/api/approvals");

export const approveDraft = (id: string, editedBody?: string) =>
  fetchAPI(`/api/approvals/${id}/approve`, {
    method: "POST",
    body: JSON.stringify(editedBody ? { edited_body: editedBody } : {}),
  });

export const rejectDraft = (id: string, reason: string) =>
  fetchAPI(`/api/approvals/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ rejection_reason: reason }),
  });

// Pipeline
export const runAgent = (agent: string, body: Record<string, unknown> = {}) =>
  fetchAPI(`/api/pipeline/run/${agent}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// Settings
export const getAppSettings = () =>
  fetchAPI<{ data: AppSettings }>("/api/settings");

// Analytics
export const getPipelineOverview = () =>
  fetchAPI<{ data: StatusCount[] }>("/api/analytics/pipeline");

export const getCosts = (batchId?: string) => {
  const qs = batchId ? `?batch_id=${batchId}` : "";
  return fetchAPI(`/api/analytics/costs${qs}`);
};

// Enrichment (Apollo — consumes credits)
export const enrichCompany = (companyId: string) =>
  fetchAPI<{
    data: { contacts_enriched: number; contacts_skipped: number; errors: number };
  }>(`/api/companies/${companyId}/enrich`, { method: "POST" });

// Outcome tagging
export const recordOutcome = (
  companyId: string,
  outcome: "won" | "lost" | "no_response",
  notes?: string
) =>
  fetchAPI<{ data: { company_id: string; outcome: string; new_status: string } }>(
    `/api/companies/${companyId}/outcome`,
    {
      method: "POST",
      body: JSON.stringify({ outcome, notes }),
    }
  );

// LinkedIn task queue
export const getLinkedInTasks = () =>
  fetchAPI<{ data: LinkedInTask[]; count: number }>("/api/actions/linkedin-tasks");

export const completeLinkedInTask = (sequenceId: string) =>
  fetchAPI(`/api/actions/linkedin-tasks/${sequenceId}/complete`, {
    method: "POST",
  });

// Hot replies (positive/question reply responses needing approval)
export const getHotReplies = () =>
  fetchAPI<{ data: OutreachDraft[]; count: number }>("/api/actions/hot-replies");

// Types
export interface Company {
  id: string;
  name: string;
  domain?: string;
  website?: string;
  industry?: string;
  naics_code?: string;
  tier?: string;
  sub_sector?: string;
  city?: string;
  state?: string;
  territory?: string;
  employee_count?: number;
  revenue_range?: string;
  estimated_revenue?: number;
  founded_year?: number;
  is_private?: boolean;
  linkedin_url?: string;
  twitter_url?: string;
  phone?: string;
  campaign_name?: string;
  pqs_total: number;
  pqs_firmographic: number;
  pqs_technographic: number;
  pqs_timing: number;
  pqs_engagement: number;
  status: string;
  priority_flag?: boolean;
  updated_at: string;
  created_at?: string;
}

export interface CompanyDetail extends Company {
  contacts: Contact[];
  research: Research | null;
  interactions: Interaction[];
  research_summary?: string;
  technology_stack?: string[];
  pain_signals?: string[];
  manufacturing_profile?: Record<string, unknown>;
  personalization_hooks?: string[];
  qualification_notes?: string;
}

export interface Contact {
  id: string;
  company_id: string;
  full_name?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  phone?: string;
  title?: string;
  seniority?: string;
  department?: string;
  headline?: string;
  persona_type?: string;
  is_decision_maker: boolean;
  linkedin_url?: string;
  status?: string;
}

export interface Research {
  company_description?: string;
  manufacturing_type?: string;
  equipment_types?: string[];
  known_systems?: string[];
  iot_maturity?: string;
  maintenance_approach?: string;
  digital_transformation_status?: string;
  pain_points?: string[];
  opportunities?: string[];
  existing_solutions?: string[];
  confidence_level?: string;
}

export interface OutreachDraft {
  id: string;
  company_id: string;
  contact_id: string;
  channel: string;
  sequence_name: string;
  sequence_step: number;
  subject: string;
  body: string;
  personalization_notes?: string;
  approval_status: string;
  companies?: { name: string; tier?: string; pqs_total: number };
  contacts?: { full_name?: string; title?: string; email?: string };
}

export interface Interaction {
  id: string;
  type: string;
  channel?: string;
  subject?: string;
  body?: string;
  source?: string;
  created_at: string;
}

export interface StatusCount {
  status: string;
  count: number;
}

export interface LinkedInTask {
  id: string;
  company_id: string;
  contact_id: string;
  sequence_name: string;
  current_step: number;
  total_steps: number;
  next_action_at: string;
  next_action_type: string;
  companies?: { name: string; domain?: string; tier?: string; pqs_total: number; linkedin_url?: string };
  contacts?: { full_name?: string; title?: string; linkedin_url?: string };
}

export interface SequenceStep {
  step: number;
  channel: string;
  delay_days: number;
  template: string;
  instructions?: Record<string, unknown>;
}

export interface Sequence {
  name: string;
  description: string;
  total_steps: number;
  steps: SequenceStep[];
}

export interface AppSettings {
  icp: {
    target_market: { name: string; description: string };
    revenue: { min: number; max: number };
    employee_count: { min: number; max: number };
    geography: { primary_states: string[]; countries: string[] };
    industries: { tier: string; label: string; apollo_industry: string }[];
    contact_titles_include: string[];
    seniority: string[];
    discovery: { max_results_per_run: number; pages_per_tier: number };
  };
  scoring: {
    dimensions: Record<string, {
      max_points: number;
      signals: Record<string, { points: number; description: string; evaluation: string }>;
    }>;
    thresholds: Record<string, { max_score?: number; action: string; new_status: string | null }>;
    min_firmographic_for_research: number;
  };
  sequences: Record<string, Sequence>;
}
