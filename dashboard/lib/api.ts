const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

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

// Analytics
export const getPipelineOverview = () =>
  fetchAPI<{ data: StatusCount[] }>("/api/analytics/pipeline");

export const getCosts = (batchId?: string) => {
  const qs = batchId ? `?batch_id=${batchId}` : "";
  return fetchAPI(`/api/analytics/costs${qs}`);
};

// Types
export interface Company {
  id: string;
  name: string;
  domain?: string;
  industry?: string;
  tier?: string;
  sub_sector?: string;
  state?: string;
  territory?: string;
  employee_count?: number;
  pqs_total: number;
  pqs_firmographic: number;
  pqs_technographic: number;
  pqs_timing: number;
  pqs_engagement: number;
  status: string;
  priority_flag?: boolean;
  updated_at: string;
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
  email?: string;
  title?: string;
  persona_type?: string;
  is_decision_maker: boolean;
  linkedin_url?: string;
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
