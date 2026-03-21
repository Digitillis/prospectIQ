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

// Contacts — cross-company listing and detail
export const getAllContacts = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return fetchAPI<{
    data: (Contact & {
      companies?: { id: string; name: string; tier?: string; status: string; pqs_total: number; domain?: string };
    })[];
    count: number;
  }>(`/api/contacts${qs}`);
};

export const getContact = (id: string) =>
  fetchAPI<{
    data: Contact & {
      interactions?: Interaction[];
      companies?: { id: string; name: string; tier?: string; status: string; pqs_total: number; domain?: string };
    };
  }>(`/api/contacts/${id}`);

export const updateContact = (id: string, data: Record<string, unknown>) =>
  fetchAPI<{ data: Contact }>(`/api/contacts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const getRelationshipSummary = () =>
  fetchAPI<{
    data: {
      strong: { count: number; contacts: ContactWithCompany[] };
      warm:   { count: number; contacts: ContactWithCompany[] };
      cold:   { count: number; contacts: ContactWithCompany[] };
      total_tracked: number;
    };
  }>("/api/contacts/relationship-summary");

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

export const testSendDraft = (id: string, testEmail: string) =>
  fetchAPI<{ data: { draft_id: string; sent_to: string }; message: string }>(
    `/api/approvals/${id}/test-send`,
    {
      method: "POST",
      body: JSON.stringify({ test_email: testEmail }),
    }
  );

// Pipeline
export const runAgent = (agent: string, body: Record<string, unknown> = {}) =>
  fetchAPI(`/api/pipeline/run/${agent}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// Settings
export const getAppSettings = () =>
  fetchAPI<{ data: AppSettings }>("/api/settings");

export const saveSettings = (data: Record<string, unknown>) =>
  fetchAPI<{ data: AppSettings; message: string }>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

// Outreach Guidelines
export interface OutreachGuidelines {
  version: string;
  sender: {
    name: string;
    short_name: string;
    title: string;
    company: string;
    email: string;
    phone: string;
    website: string;
    signature: string;
  };
  voice_and_tone: string;
  email_structure: string;
  must_include: string[];
  never_include: string[];
  banned_phrases: string[];
  banned_characters: string[];
  digitillis_facts: string[];
  subject_line_rules: string;
  max_words: Record<string, number>;
}

export const getOutreachGuidelines = () =>
  fetchAPI<{ data: OutreachGuidelines }>("/api/settings/outreach-guidelines");

export const saveOutreachGuidelines = (data: Record<string, unknown>) =>
  fetchAPI<{ data: OutreachGuidelines; message: string }>("/api/settings/outreach-guidelines", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const testSlack = () =>
  fetchAPI<{ data: { status: string } }>("/api/settings/test-slack", { method: "POST" });

// Templates
export interface EmailTemplate {
  id: string;
  sequence_name: string;
  sequence_display_name: string;
  sequence_description: string;
  step: number;
  channel: string;
  delay_days: number;
  template_name: string;
  instructions: Record<string, unknown>;
}

export const getTemplates = () =>
  fetchAPI<{ data: EmailTemplate[] }>("/api/settings/templates");

// Analytics
export const getPipelineOverview = () =>
  fetchAPI<{ data: StatusCount[] }>("/api/analytics/pipeline");

export const getCosts = (batchId?: string) => {
  const qs = batchId ? `?batch_id=${batchId}` : "";
  return fetchAPI(`/api/analytics/costs${qs}`);
};

export const getDuplicates = () =>
  fetchAPI<{ data: DuplicateGroup[]; total_duplicate_groups: number }>("/api/analytics/duplicates");

export const getCompetitiveRisks = () =>
  fetchAPI<{ data: CompetitiveRisk[]; total: number }>("/api/analytics/competitive-risks");

export const getSequencePerformance = () =>
  fetchAPI<{ data: SequencePerformance[] }>("/api/analytics/sequence-performance");

export const getAgentRuns = () =>
  fetchAPI<{ data: AgentRun[]; totals: { runs: number; cost_usd: number } }>(
    "/api/analytics/agent-runs"
  );

export interface Activity {
  type: string;
  entity: string;
  entity_id: string | null;
  title: string;
  description: string;
  tier: string | null;
  timestamp: string;
}

export const getActivityFeed = (limit = 50) =>
  fetchAPI<{ data: Activity[] }>(`/api/analytics/activity-feed?limit=${limit}`);

export interface DataQuality {
  total_companies: number;
  field_coverage: Record<string, { missing: number; coverage: number }>;
  incomplete_companies: {
    id: string;
    name: string;
    status: string;
    tier: string | null;
    missing_fields: string[];
    completeness: number;
  }[];
  overall_completeness: number;
}

export const getDataQuality = () =>
  fetchAPI<{ data: DataQuality }>("/api/analytics/data-quality");

export interface CampaignPerformance {
  name: string;
  total: number;
  statuses: Record<string, number>;
  avg_pqs: number;
  tiers: Record<string, number>;
  advancement_rate: number;
}

export const getCampaignPerformance = () =>
  fetchAPI<{ data: CampaignPerformance[] }>("/api/analytics/campaign-performance");

export interface PipelineVelocityStage {
  avg_days: number;
  min_days: number;
  max_days: number;
  count: number;
}

export const getPipelineVelocity = () =>
  fetchAPI<{ data: Record<string, PipelineVelocityStage> }>("/api/analytics/pipeline-velocity");

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

export const importCompaniesCSV = async (file: File): Promise<{ data: ImportResult }> => {
  const formData = new FormData();
  formData.append("file", file);
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";
  const res = await fetch(`${API_BASE}/api/companies/import`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const error = await res.text();
    throw new Error(`API error ${res.status}: ${error}`);
  }
  return res.json();
};

// Enrichment (Apollo — consumes credits)
export const enrichCompany = (companyId: string) =>
  fetchAPI<{
    data: { contacts_enriched: number; contacts_skipped: number; errors: number };
  }>(`/api/companies/${companyId}/enrich`, { method: "POST" });

// Custom tags
export const updateTags = (companyId: string, tags: string[]) =>
  fetchAPI(`/api/companies/${companyId}/tags`, {
    method: "PATCH",
    body: JSON.stringify({ tags }),
  });

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
  custom_tags?: string[];
  estimated_deal_value?: number;
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
  relationship_strength?: number; // 0-100
  last_interaction_note?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ContactWithCompany extends Contact {
  companies?: {
    id: string;
    name: string;
    tier?: string;
    status: string;
    pqs_total: number;
    domain?: string;
  };
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

export interface DuplicateGroup {
  type: string;
  key: string;
  companies: Company[];
}

export interface CompetitiveRisk {
  company_id: string;
  company: { id: string; name: string; tier?: string; status: string; pqs_total: number } | null;
  existing_solutions: string[];
}

export interface AgentRun {
  batch_id: string;
  agent: string;
  started_at: string;
  total_cost: number;
  total_calls: number;
  companies_processed: number;
  providers: string[];
}

export interface SequencePerformance {
  sequence_name: string;
  step: number;
  channel: string;
  total_drafts: number;
  approved: number;
  rejected: number;
  pending: number;
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
