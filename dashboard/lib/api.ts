const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://prospectiq-production-4848.up.railway.app";

async function getAuthHeader(): Promise<string | null> {
  try {
    // Dynamic import to avoid SSR issues — supabase client is browser-only
    const { supabase } = await import("@/lib/supabase");
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token ? `Bearer ${session.access_token}` : null;
  } catch {
    return null;
  }
}

async function fetchAPI<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const authHeader = await getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
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
  fetchAPI<{ data: OutreachDraft[]; count: number; total_pending: number }>("/api/approvals");

export interface AlertItem {
  id: string;
  assertion: string;
  detail: string;
  contact_name: string;
  evaluated_at: string;
}
export const getAlerts = (hours = 24) =>
  fetchAPI<{ count: number; items: AlertItem[] }>(`/api/approvals/alerts?hours=${hours}`);

export const approveDraft = (id: string, editedBody?: string) =>
  fetchAPI(`/api/approvals/${id}/approve`, {
    method: "POST",
    body: JSON.stringify(editedBody ? { edited_body: editedBody } : {}),
  });

export const saveDraftEdit = (id: string, editedBody: string) =>
  fetchAPI(`/api/approvals/${id}/edit`, {
    method: "PATCH",
    body: JSON.stringify({ edited_body: editedBody }),
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

export interface SentEmail {
  id: string;
  subject: string;
  body: string;
  edited_body?: string;
  sent_at: string;
  sequence_name?: string;
  sequence_step?: number;
  channel?: string;
}

export interface ResearchIntelligence {
  company_id: string;
  company_description?: string;
  manufacturing_type?: string;
  equipment_types?: string;
  known_systems?: string;
  iot_maturity?: string;
  maintenance_approach?: string;
  pain_points?: string;
  opportunities?: string;
  existing_solutions?: string;
  digital_transformation_status?: string;
  confidence_level?: string;
  researched_at?: string;
}

export const getDraftThread = (draftId: string) =>
  fetchAPI<{ data: SentEmail[]; count: number }>(`/api/approvals/${draftId}/thread`);

export const getDraftResearch = (draftId: string) =>
  fetchAPI<{ data: ResearchIntelligence | null }>(`/api/approvals/${draftId}/research`);

// ---------------------------------------------------------------------------
// Outreach Agent — personalized draft generation and intelligence
// ---------------------------------------------------------------------------

export interface IntelligenceData {
  contact: Record<string, unknown>;
  company: {
    id: string;
    name: string;
    domain?: string;
    tier?: string;
    pqs_total?: number;
    status?: string;
    campaign_cluster?: string;
    tranche?: string;
    research_updated_at?: string;
  };
  research_summary: Record<string, unknown>;
  personalization_hooks: string[];
  pain_signals: string[];
  trigger_events: Array<{
    type?: string;
    description?: string;
    date_approx?: string;
    outreach_relevance?: string;
  }>;
  persona_type: string;
  recommended_hooks: string[];
}

export interface DraftQualityScore {
  draft_id: string;
  scores: {
    specificity: number;
    relevance: number;
    tone_match: number;
    cta_clarity: number;
  };
  overall: number;
  suggestions: string[];
}

/** Generate a personalized outreach draft for a company-contact pair. */
export const generateOutreachDraft = (
  companyId: string,
  contactId: string,
  sequenceStep: string = "touch_1",
  forceRegenerate: boolean = false,
) =>
  fetchAPI<{ data: OutreachDraft & Record<string, unknown>; message: string }>(
    "/api/outreach/generate",
    {
      method: "POST",
      body: JSON.stringify({
        company_id: companyId,
        contact_id: contactId,
        sequence_step: sequenceStep,
        force_regenerate: forceRegenerate,
      }),
    }
  );

/** Generate drafts for multiple companies in one batch request. */
export const generateOutreachBatch = (
  companyIds: string[],
  sequenceStep: string = "touch_1",
) =>
  fetchAPI<{ created: number; drafts: OutreachDraft[]; message: string }>(
    "/api/outreach/generate-batch",
    {
      method: "POST",
      body: JSON.stringify({ company_ids: companyIds, sequence_step: sequenceStep }),
    }
  );

/** Fetch the full personalization intelligence payload for a contact. */
export const getOutreachIntelligence = (contactId: string) =>
  fetchAPI<IntelligenceData>(`/api/outreach/intelligence/${contactId}`);

/** Score a draft across four quality dimensions (specificity, relevance, tone, CTA). */
export const scoreDraft = (draftId: string) =>
  fetchAPI<DraftQualityScore>(`/api/outreach/score-draft/${draftId}`, {
    method: "POST",
  });

// Pipeline
export const runAgent = async (agent: string, body: Record<string, unknown> = {}): Promise<unknown> => {
  const res = await fetchAPI<{ data: Record<string, unknown> }>(`/api/pipeline/run/${agent}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

  // Long-running agents (e.g. research) return {status: "running", batch_id: "..."}
  // and run in the background to avoid Railway's request timeout. Poll until done.
  const d = (res as { data?: Record<string, unknown> })?.data;
  if (d?.status === "running" && d?.batch_id) {
    const batchId = d.batch_id as string;
    for (let i = 0; i < 240; i++) {  // max 12 min (240 × 3s)
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const poll = await fetchAPI<{ data: Record<string, unknown> }>(`/api/pipeline/job/${batchId}`);
        const s = (poll as { data?: Record<string, unknown> })?.data;
        if (s?.status !== "running") {
          return { data: s };
        }
      } catch {
        // transient network error — keep polling
      }
    }
    throw new Error("Research job timed out after 12 minutes");
  }

  return res;
};

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

// Content Guidelines
export interface ContentGuidelinesAuthor {
  name: string;
  short_name: string;
  title: string;
  company: string;
  linkedin_url: string;
}

export interface ContentGuidelinesFormatTemplate {
  display_name: string;
  frequency: string;
  structure: string;
  char_limit: number;
  rules: string[];
}

export interface ContentGuidelinesTopic {
  id: string;
  title: string;
  key_data: string;
  format_hint: string;
}

export interface ContentGuidelinesPillar {
  name: string;
  display_name: string;
  target_reader: string;
  data_sources: string[];
  topic_examples: string[];
}

export interface ContentGuidelinesCalendarEntry {
  day: string;
  format: string;
  pillar: string;
  topic: string;
}

export interface ContentGuidelines {
  version: string;
  author: ContentGuidelinesAuthor;
  voice_and_tone: string;
  content_pillars: ContentGuidelinesPillar[];
  format_templates: Record<string, ContentGuidelinesFormatTemplate>;
  quality_standards: string[];
  banned_phrases: string[];
  never_include: string[];
  must_include: string[];
  visual_style: Record<string, unknown>;
  content_calendar: Record<string, ContentGuidelinesCalendarEntry[]>;
  topics_library: Record<string, ContentGuidelinesTopic[]>;
}

export const getContentGuidelines = () =>
  fetchAPI<{ data: ContentGuidelines }>("/api/settings/content-guidelines");

export const saveContentGuidelines = (data: Record<string, unknown>) =>
  fetchAPI<{ data: ContentGuidelines; message: string }>("/api/settings/content-guidelines", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

// LinkedIn Messages Guidelines
export interface LinkedInGuidelinesSender {
  name: string;
  short_name: string;
  title: string;
  company: string;
  linkedin_url: string;
}

export interface LinkedInGuidelines {
  version: string;
  sender: LinkedInGuidelinesSender;
  connection_note_rules: string;
  opening_dm_rules: string;
  followup_dm_rules: string;
  tone: string;
  fb_question_templates: string[];
  mfg_question_templates: string[];
  banned_phrases: string[];
  never_include: string[];
}

export const getLinkedinGuidelines = () =>
  fetchAPI<{ data: LinkedInGuidelines }>("/api/settings/linkedin-guidelines");

export const saveLinkedinGuidelines = (data: Record<string, unknown>) =>
  fetchAPI<{ data: LinkedInGuidelines; message: string }>("/api/settings/linkedin-guidelines", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

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
    data: {
      contacts_enriched: number;
      contacts_skipped: number;
      errors: number;
      error_message?: string;
      details?: Array<{ company: string; status: string; message: string }>;
    };
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

// ---------------------------------------------------------------------------
// Daily Cockpit — /api/today
// ---------------------------------------------------------------------------

export interface TodayHotSignal {
  id: string;
  name: string;
  domain?: string;
  tier?: string;
  pqs_total: number;
  status: string;
  contacts?: Contact[];
  last_interaction?: {
    type: string;
    body?: string;
    created_at: string;
    metadata?: Record<string, unknown>;
  } | null;
}

export interface TodayInteraction {
  id: string;
  type: string;
  channel?: string;
  subject?: string;
  body?: string;
  created_at: string;
  metadata?: Record<string, unknown>;
  company_id: string;
  contact_id?: string;
  companies?: { id: string; name: string; tier?: string; pqs_total: number } | null;
  contacts?: { id: string; full_name?: string; title?: string } | null;
}

export interface LinkedInIntel {
  personalization_notes?: string;
  company?: {
    industry?: string;
    employee_count?: number;
    revenue_printed?: string;
    headcount_growth_6m?: number;
    is_public?: boolean;
    parent_company_name?: string;
    pain_signals?: string[];
    personalization_hooks?: string[];
    research_summary?: string;
  };
  research?: {
    products_services?: string[];
    recent_news?: string[];
    pain_points?: string[];
    known_systems?: string[];
    confidence?: string;
    company_description?: string;
    manufacturing_type?: string;
    equipment_types?: string[];
    maintenance_approach?: string;
    iot_maturity?: string;
    opportunities?: string[];
    existing_solutions?: string[];
    funding_status?: string;
  } | null;
  contact?: {
    title?: string;
    seniority?: string;
    city?: string;
    state?: string;
  };
}

export interface LinkedInActionItem {
  contact_id: string;
  company_id: string;
  full_name?: string;
  title?: string;
  linkedin_url?: string;
  linkedin_status?: string;
  company_name?: string;
  company_tier?: string;
  company_domain?: string;
  pqs_total: number;
  draft_id?: string;
  message_text?: string;
  intel?: LinkedInIntel;
}

export interface ContentItem {
  draft_id?: string;
  topic: string;
  post_text: string;
  approval_status?: string;
  created_at?: string;
}

export interface DailyPlanSection {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  priority: number;
  target?: number;
  completed?: number;
  // items is typed loosely here since each section has different item shapes
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  items: any[];
}

export interface DailyPlan {
  date: string;
  greeting: string;
  sections: DailyPlanSection[];
}

export interface ProgressBreakdown {
  linkedin_connections: { done: number; target: number };
  linkedin_dms: { done: number; target: number };
  emails_approved: { done: number; target: number };
  outcomes_logged: { done: number; target: number };
  content_posted: { done: number; target: number };
}

export interface ProgressDetail {
  target: number;
  completed: number;
  breakdown: ProgressBreakdown;
}

export interface TodayData {
  // Legacy fields
  hot_signals: TodayHotSignal[];
  pending_approvals: OutreachDraft[];
  linkedin_queue: LinkedInTask[];
  pipeline_summary: Record<string, number>;
  recent_interactions: TodayInteraction[];
  progress: { completed: number; target: number };
  // New structured fields
  daily_plan?: DailyPlan;
  progress_detail?: ProgressDetail;
  // AI-recommended next actions
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pending_next_actions?: any[];
  // Connections sent but not yet accepted/ignored
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pending_acceptances?: any[];
}

export const getTodayData = () =>
  fetchAPI<{ data: TodayData }>("/api/today");

export const logOutcome = (data: {
  company_id: string;
  contact_id?: string;
  channel: string;
  outcome: string;
  notes?: string;
}) =>
  fetchAPI<{ data: { company_id: string; outcome: string; new_status: string | null; pqs_delta: number }; message: string }>(
    "/api/today/log-outcome",
    { method: "POST", body: JSON.stringify(data) }
  );

export const markDone = (data: {
  action_type: string;
  contact_id?: string;
  company_id?: string;
}) =>
  fetchAPI<{ data: { action_type: string; marked_done_at: string }; message: string }>(
    "/api/today/mark-done",
    { method: "POST", body: JSON.stringify(data) }
  );

// LinkedIn messages (generated by LinkedInAgent)
export const getLinkedInMessages = (params?: Record<string, string>) => {
  const qs =
    params && Object.keys(params).length > 0
      ? "?" + new URLSearchParams(params).toString()
      : "";
  return fetchAPI<{ data: LinkedInContact[]; count: number }>(
    `/api/companies/linkedin-messages${qs}`
  );
};

// All contacts with LinkedIn URL — no draft generation required
export interface LinkedInContactRaw {
  contact: {
    id: string;
    company_id: string;
    full_name?: string;
    first_name?: string;
    last_name?: string;
    title?: string;
    persona_type?: string;
    is_decision_maker?: boolean;
    linkedin_url?: string;
    linkedin_status?: string;
    linkedin_notes?: string;
    status?: string;
    linkedin_connection_sent_at?: string;
    linkedin_accepted_at?: string;
    linkedin_dm_sent_at?: string;
    linkedin_responded_at?: string;
    linkedin_meeting_booked_at?: string;
  };
  company: {
    id: string;
    name?: string;
    tier?: string;
    sub_sector?: string;
    pqs_total?: number;
    domain?: string;
  };
}

export const getLinkedInContacts = (params?: Record<string, string>) => {
  const qs =
    params && Object.keys(params).length > 0
      ? "?" + new URLSearchParams(params).toString()
      : "";
  return fetchAPI<{ data: LinkedInContactRaw[]; count: number; total: number }>(
    `/api/companies/linkedin-contacts${qs}`
  );
};

export const updateLinkedInStatus = (
  contactId: string,
  status: string,
  notes?: string
) =>
  fetchAPI<{ data: { contact_id: string; linkedin_status: string } }>(
    `/api/companies/${contactId}/linkedin-status`,
    {
      method: "POST",
      body: JSON.stringify({ status, notes: notes ?? "" }),
    }
  );

// ---------------------------------------------------------------------------
// Content — LinkedIn thought leadership post generation
// ---------------------------------------------------------------------------

export interface ContentCalendarEntry {
  week: number;
  day: string;
  format: string;
  pillar: string;
  topic: string;
}

export interface ContentIntel {
  report: string | null;
  credibility_score: number | null;
  publish_ready: boolean | null;
  verification_rounds: number | null;
  error: string | null;
}

export interface ContentQualityReport {
  score: number;
  verdict: string;
  fact_check: { result: string; sources: string[]; note: string };
  publication_standard: { mckinsey_share: boolean; fluff_free: boolean; claims_supported: boolean; worth_sharing: boolean };
  content_objective: string[];
  positioning: { systems_thinker: boolean; pattern_recognizer: boolean; builder: boolean };
  differentiation: { could_100_write: boolean; original_insight: boolean; note: string };
  craft: { banned_phrases: string[]; em_dashes: boolean; char_count_ok: boolean; mobile_format: boolean };
  reader_value: { actionable: boolean; explains_why: boolean };
  flags: string[];
}

export interface ContentDraft {
  id: string;
  topic: string;
  pillar: string;
  format: string;
  post_text: string;
  char_count: number;
  generated_at: string;
  approval_status: string;
  credibility_score?: number | null;
  publish_ready?: boolean | null;
  intel?: ContentIntel | null;
  quality_report?: ContentQualityReport | null;
}

export const getContentCalendar = () =>
  fetchAPI<{ data: ContentCalendarEntry[] }>("/api/content/calendar");

export const generateContent = (data: {
  topic?: string;
  pillar?: string;
  format_type?: string;
  commentary?: string;
}) =>
  fetchAPI<{ data: ContentDraft }>("/api/content/generate", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const generateContentBatch = (data: {
  pillar?: string;
  format_type?: string;
  time_horizon?: string;
  commentary?: string;
}) =>
  fetchAPI<{ data: ContentDraft[]; count: number; requested: number; errors: string[] }>(
    "/api/content/generate-batch",
    {
      method: "POST",
      body: JSON.stringify({ ...data, batch: true }),
    }
  );

export const getContentDrafts = () =>
  fetchAPI<{ data: ContentDraft[]; count: number }>("/api/content/drafts");

export const markContentPosted = (id: string) =>
  fetchAPI(`/api/content/${id}/mark-posted`, { method: "POST" });

export interface AutoCalendarPost {
  id: string;
  scheduled_date: string;
  day_of_week: string;
  week_number: number;
  pillar: string;
  pillar_display: string;
  format: string;
  format_display: string;
  topic: string;
  body: string;
  char_count: number;
  status: string;
}

export interface AutoCalendarResponse {
  calendar_id: string;
  start_date: string;
  end_date: string;
  weeks: number;
  posts: AutoCalendarPost[];
  coverage: Record<string, number>;
  estimated_cost: number;
  generation_time_seconds: number;
}

export const autoGenerateCalendar = (data: {
  start_date?: string;
  commentary?: string;
  weeks?: number;
}) =>
  fetchAPI<{ data: AutoCalendarResponse }>("/api/content/auto-calendar", {
    method: "POST",
    body: JSON.stringify(data),
  });

// Content Archive
export interface ContentArchiveEntry {
  id: string;
  topic: string;
  pillar?: string | null;
  format?: string | null;
  post_text: string;
  char_count?: number | null;
  credibility_score?: number | null;
  publish_ready?: boolean | null;
  intel_report?: string | null;
  posted_at?: string | null;
  linkedin_post_url?: string | null;
  impressions?: number | null;
  likes?: number | null;
  comments?: number | null;
  shares?: number | null;
  engagement_rate?: number | null;
  engagement_updated_at?: string | null;
  draft_id?: string | null;
  calendar_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContentAnalytics {
  total_posts: number;
  avg_credibility: number;
  total_impressions: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  avg_engagement_rate: number;
  by_pillar: Record<string, { count: number; avg_rate: number }>;
  by_format: Record<string, { count: number; avg_rate: number }>;
}

export const getContentArchive = (params?: { limit?: number; offset?: number; pillar?: string }) => {
  const qs = params
    ? "?" + new URLSearchParams(
        Object.fromEntries(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        )
      ).toString()
    : "";
  return fetchAPI<{ data: ContentArchiveEntry[]; count: number }>(`/api/content/archive${qs}`);
};

export const archiveContent = (
  draftId: string,
  data: { linkedin_post_url?: string; posted_at?: string }
) =>
  fetchAPI<{ data: ContentArchiveEntry }>(`/api/content/${draftId}/archive`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateEngagement = (
  archiveId: string,
  data: {
    impressions?: number;
    likes?: number;
    comments?: number;
    shares?: number;
    linkedin_post_url?: string;
  }
) =>
  fetchAPI<{ data: ContentArchiveEntry }>(`/api/content/archive/${archiveId}/engagement`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const getContentAnalytics = () =>
  fetchAPI<{ data: ContentAnalytics }>("/api/content/archive/analytics");

export const checkContentDedup = (topic: string) =>
  fetchAPI<{ duplicate: boolean; days_since?: number; last_posted?: string }>(
    `/api/content/archive/dedup-check?topic=${encodeURIComponent(topic)}`
  );

// Content draft management
export const deleteContentDraft = (draftId: string) =>
  fetchAPI<{ data: { deleted: string } }>(`/api/content/${draftId}`, {
    method: "DELETE",
  });

export const deleteAllContentDrafts = () =>
  fetchAPI<{ data: { deleted_count: number } }>("/api/content/drafts/all", {
    method: "DELETE",
  });

export const runIntelOnDraft = (draftId: string) =>
  fetchAPI<{ data: { draft_id: string; credibility_score: number; publish_ready: boolean; intel: ContentIntel } }>(
    `/api/content/${draftId}/run-intel`,
    { method: "POST" }
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
  campaign_cluster?: string;
  tranche?: string;
  pqs_total: number;
  pqs_firmographic: number;
  pqs_technographic: number;
  pqs_timing: number;
  pqs_engagement: number;
  status: string;
  priority_flag?: boolean;
  custom_tags?: string[];
  estimated_deal_value?: number;
  contacts?: Contact[];
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
  linkedin_status?: string; // not_sent | connection_sent | accepted | dm_sent | responded | meeting_booked
  linkedin_notes?: string;
  linkedin_connection_sent_at?: string;
  linkedin_accepted_at?: string;
  linkedin_dm_sent_at?: string;
  linkedin_responded_at?: string;
  linkedin_meeting_booked_at?: string;
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
  edited_body?: string;
  personalization_notes?: string;
  approval_status: string;
  quality_score?: number;
  sent_at?: string;
  companies?: { name: string; tier?: string; pqs_total: number };
  contacts?: { full_name?: string; title?: string; email?: string; open_count?: number; click_count?: number };
  step_engagement?: Record<string, "clicked" | "opened" | "replied" | "none">;
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

export interface LinkedInDraft {
  id: string;
  body: string;
  personalization_notes?: string;
  created_at: string;
}

export interface LinkedInContactCompany {
  id: string;
  name: string;
  tier?: string;
  sub_sector?: string;
  industry?: string;
  pqs_total: number;
  city?: string;
  state?: string;
  domain?: string;
}

export interface LinkedInContact {
  contact: Contact;
  company: LinkedInContactCompany;
  drafts: {
    linkedin_connection?: LinkedInDraft;
    linkedin_dm_opening?: LinkedInDraft;
    linkedin_dm_followup?: LinkedInDraft;
  };
  intel?: LinkedInIntel;
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

// ---------------------------------------------------------------------------
// Contact Event Thread — /api/events
// ---------------------------------------------------------------------------

export interface ContactEvent {
  id: string;
  contact_id: string;
  company_id: string;
  event_type: string;
  channel: string | null;
  direction: string | null;
  subject: string | null;
  body: string | null;
  sentiment: string | null;
  sentiment_reason: string | null;
  signals: string[];
  tags: string[];
  next_action: string | null;
  next_action_date: string | null;
  next_action_status: string | null;
  suggested_message: string | null;
  action_reasoning: string | null;
  action_type?: string | null;
  ai_analyzed?: boolean;
  pqs_delta: number;
  created_by: string;
  created_at: string;
  updated_at?: string;
}

export const getContactEvents = (contactId: string, limit?: number) =>
  fetchAPI<{ data: ContactEvent[] }>(`/api/contacts/${contactId}/events?limit=${limit || 50}`);

export const createContactEvent = (
  contactId: string,
  data: {
    event_type: string;
    channel?: string;
    direction?: string;
    subject?: string;
    body?: string;
    tags?: string[];
    analyze?: boolean;
  }
) =>
  fetchAPI<{ data: ContactEvent }>(`/api/contacts/${contactId}/events`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateNextAction = (eventId: string, status: string) =>
  fetchAPI<{ data: ContactEvent }>(`/api/contacts/events/${eventId}/next-action`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const getPendingActions = (contactId?: string) =>
  fetchAPI<{ data: ContactEvent[]; count: number }>(
    `/api/contacts/events/pending-actions${contactId ? `?contact_id=${contactId}` : ""}`
  );

// Action Queue types
export interface ActionQueueItem { id:string; action_type:string; company_id?:string; contact_id?:string; source:string; priority:number; pqs_at_queue_time?:number; status:string; scheduled_date:string; context:Record<string,unknown>; companies?:{id:string;name:string;tier?:string;pqs_total:number;industry?:string}; contacts?:{id:string;full_name?:string;title?:string;linkedin_url?:string;email?:string}; }
export interface ActionRequestResult { request_id:string; action_type:string; requested:number; fulfilled:number; from_existing:number; from_apollo:number; queue_preview:{company:string;contact:string;pqs:number}[]; }
export interface DailyTarget { id:string; action_type:string; target_count:number; effective_date?:string; is_active:boolean; }
export interface QueueSummary { date:string; total_done:number; total_target:number; breakdown:Record<string,{done:number;pending:number;target:number}>; }

// Action Queue API
export const requestActions = (d: {
  action_type: string;
  count: number;
  filters?: Record<string, unknown>;
  source_preference?: string;
}) =>
  fetchAPI<{ data: ActionRequestResult; message: string }>(
    "/api/action-queue/request",
    { method: "POST", body: JSON.stringify(d) }
  );

export const getActionQueue = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return fetchAPI<{ data: ActionQueueItem[]; count: number }>(
    "/api/action-queue" + qs
  );
};

export const completeQueueAction = (
  id: string,
  d: { action_type: string; contact_id?: string; company_id?: string }
) =>
  fetchAPI<{ data: { item_id: string; status: string }; message: string }>(
    `/api/action-queue/${id}/complete`,
    { method: "POST", body: JSON.stringify(d) }
  );

export const skipQueueAction = (id: string, reason?: string) =>
  fetchAPI<{ data: { item_id: string; status: string }; message: string }>(
    `/api/action-queue/${id}/skip`,
    { method: "POST", body: JSON.stringify({ reason }) }
  );

export const getDailyTargets = (date?: string) =>
  fetchAPI<{ data: DailyTarget[]; summary: Record<string, number> }>(
    "/api/action-queue/targets" + (date ? "?date=" + date : "")
  );

export const updateDailyTargetsBatch = (d: {
  targets: { action_type: string; target_count: number }[];
  effective_date?: string;
}) =>
  fetchAPI<{ data: DailyTarget[]; message: string }>(
    "/api/action-queue/targets/batch",
    { method: "PUT", body: JSON.stringify(d) }
  );

export const autoFillQueue = (scheduledDate?: string) =>
  fetchAPI<{
    data: { scheduled_date: string; total_added: number; by_type: Record<string, number> };
    message: string;
  }>("/api/action-queue/auto-fill", {
    method: "POST",
    body: JSON.stringify({ scheduled_date: scheduledDate }),
  });

export const getQueueSummary = (date?: string) =>
  fetchAPI<{ data: QueueSummary }>(
    "/api/action-queue/summary" + (date ? "?date=" + date : "")
  );

// ---------------------------------------------------------------------------
// Threads — campaign reply thread management
// ---------------------------------------------------------------------------

export interface ThreadMessage {
  id: string;
  thread_id: string;
  direction: "inbound" | "outbound";
  subject?: string;
  body?: string;
  sent_at: string;
  classification?: string;
  classification_confidence?: number;
  classification_reasoning?: string;
  classification_confirmed_by?: string;
  outreach_draft_id?: string;
  source?: string;
}

export interface CampaignThread {
  id: string;
  company_id: string;
  contact_id: string;
  sequence_name?: string;
  status: string; // active | paused | closed | unsubscribed | bounced | converted
  current_step?: number;
  next_step?: number;
  paused_reason?: string;
  last_sent_at?: string;
  last_replied_at?: string;
  updated_at: string;
  created_at: string;
  // Joined
  companies?: {
    id: string;
    name: string;
    tier?: string;
    pqs_total: number;
    campaign_cluster?: string;
    status: string;
    research_summary?: string;
    pain_signals?: string[];
    intent_score?: number;
    personalization_hooks?: string[];
  };
  contacts?: {
    id: string;
    full_name?: string;
    title?: string;
    email?: string;
    persona_type?: string;
  };
  // Enriched by API
  last_message?: ThreadMessage | null;
  messages?: ThreadMessage[];
  pending_draft?: OutreachDraft | null;
  needs_action?: boolean;
  step_display?: string;
}

export const listThreads = (params?: {
  status?: string;
  needs_action?: boolean;
  limit?: number;
}) => {
  const qs = params ? "?" + new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => [k, String(v)])
  ).toString() : "";
  return fetchAPI<{ data: CampaignThread[]; count: number; needs_action_count: number }>(`/api/threads${qs}`);
};

export const getThread = (id: string) =>
  fetchAPI<{ data: CampaignThread & { messages: ThreadMessage[]; pending_draft: OutreachDraft | null; research: Record<string, unknown> | null } }>(`/api/threads/${id}`);

export const confirmThreadClassification = (
  threadId: string,
  data: { message_id: string; classification: string; override?: boolean }
) =>
  fetchAPI<{ message: string; draft_id?: string; draft_queued: boolean }>(
    `/api/threads/${threadId}/confirm`,
    { method: "POST", body: JSON.stringify(data) }
  );

export const sendThreadDraft = (
  threadId: string,
  data: { draft_id: string; edited_body?: string }
) =>
  fetchAPI<{ message: string; sent_immediately: boolean; draft_id: string }>(
    `/api/threads/${threadId}/send`,
    { method: "POST", body: JSON.stringify(data) }
  );

export const regenerateThreadDraft = (
  threadId: string,
  data?: { instruction?: string }
) =>
  fetchAPI<{ message: string; draft_id: string; subject: string; body: string; strategy_used: string }>(
    `/api/threads/${threadId}/regenerate`,
    { method: "POST", body: JSON.stringify(data || {}) }
  );

// ---------------------------------------------------------------------------
// Sequences — templates and routing
// ---------------------------------------------------------------------------

export interface SequenceTemplate {
  name: string;
  display_name: string;
  description?: string;
  channel: string;
  total_steps: number;
  steps: SequenceStep[];
  source: "yaml" | "custom";
  is_active: boolean;
  is_template?: boolean;
  id?: string;
  created_at?: string;
}

export interface SequenceStep {
  step: number;
  name: string;
  channel: string;
  delay_days: number;
  subject_template?: string;
  template?: string;
  instructions: Record<string, unknown>;
}

export interface RoutingEntry {
  cluster: string;
  persona: string;
  env_var: string;
  campaign_id?: string;
  linked: boolean;
}

export const getSequenceTemplates = () =>
  fetchAPI<{ built_in: SequenceTemplate[]; custom: SequenceTemplate[]; total: number }>(
    "/api/sequences/templates"
  );

export const saveSequenceTemplate = (data: {
  name: string;
  display_name: string;
  description?: string;
  channel: string;
  steps: SequenceStep[];
  cluster?: string;
  personas?: string[];
  value_prop_angle?: string;
}) =>
  fetchAPI<{ data: SequenceTemplate; message: string }>("/api/sequences/templates", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const getSequenceRouting = () =>
  fetchAPI<{ data: RoutingEntry[]; total: number; linked_count: number; unlinked_count: number }>(
    "/api/sequences/routing"
  );

export const updateRoutingEntry = (data: {
  cluster: string;
  persona?: string;
  campaign_id: string;
}) =>
  fetchAPI<{ message: string; env_var: string; campaign_id: string }>(
    "/api/sequences/routing",
    { method: "PUT", body: JSON.stringify(data) }
  );

export const provisionInstantlyCampaigns = (data?: { cluster?: string; dry_run?: boolean }) =>
  fetchAPI<{ results: unknown[]; provisioned: number; pending: number }>(
    "/api/sequences/routing/provision",
    { method: "POST", body: JSON.stringify(data || {}) }
  );

export const listActiveEnrollments = (limit = 100) =>
  fetchAPI<{ data: unknown[]; count: number }>(
    `/api/sequences/active-enrollments?limit=${limit}`
  );

// Sequence V2 API
export interface SequenceStepV2 {
  step_id: string;
  step_type: "email" | "wait" | "condition" | "linkedin" | "task";
  step_order: number;
  subject_template?: string;
  body_template?: string;
  wait_days?: number;
  wait_condition?: string;
  condition_type?: string;
  condition_value?: unknown;
  branch_yes?: string;
  branch_no?: string;
  task_description?: string;
  task_due_offset_days?: number;
  metadata?: Record<string, unknown>;
}

export interface SequenceV2 {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  cluster?: string;
  persona?: string;
  steps: SequenceStepV2[];
  is_template: boolean;
  tags: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SequenceStats {
  sequence_id: string;
  enrolled_count: number;
  active_count: number;
  completed_count: number;
  open_rate: number;
  reply_rate: number;
  click_rate: number;
}

export const createSequenceV2 = (data: Omit<SequenceV2, "id" | "created_at" | "updated_at">) =>
  fetchAPI<{ data: SequenceV2; message: string }>("/api/sequences/v2", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const getSequenceV2 = (id: string) =>
  fetchAPI<{ data: SequenceV2 }>(`/api/sequences/v2/${id}`);

export const updateSequenceV2 = (id: string, data: Omit<SequenceV2, "id" | "created_at" | "updated_at">) =>
  fetchAPI<{ data: SequenceV2; message: string }>(`/api/sequences/v2/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const duplicateSequenceV2 = (id: string) =>
  fetchAPI<{ data: SequenceV2; message: string }>(`/api/sequences/v2/${id}/duplicate`, {
    method: "POST",
  });

export const getSequenceStatsV2 = (id: string) =>
  fetchAPI<SequenceStats>(`/api/sequences/v2/${id}/stats`);

export const patchEnrollment = (enrollmentId: string, status: "paused" | "active" | "stopped") =>
  fetchAPI<{ message: string; status: string }>(`/api/sequences/v2/enrollments/${enrollmentId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

// ---------------------------------------------------------------------------
// Sequence Timeline + Reply Intake
// ---------------------------------------------------------------------------

export interface TimelineRow {
  enrollment_id: string;
  company_id: string;
  company_name: string | null;
  contact_id: string;
  contact_name: string | null;
  contact_email: string | null;
  persona_type: string | null;
  sequence_name: string;
  current_step: number;
  total_steps: number;
  status: string;
  next_action_at: string | null;
  next_action_type: string | null;
  step1_sent_at: string | null;
  step1_due_at?: string;
  step2_due_at?: string;
  step3_due_at?: string;
  step4_due_at?: string;
  reply_received: boolean;
  reply_intent: string | null;
  reply_body_preview: string | null;
}

export const getSequenceTimeline = () =>
  fetchAPI<{ data: TimelineRow[]; total: number }>("/api/sequences/v2/timeline");

export interface LogReplyPayload {
  body: string;
  intent: "interested" | "not_interested" | "question" | "referral" | "objection";
  notes?: string;
  sequence_enrollment_id?: string;
}

export const logReply = (contactId: string, payload: LogReplyPayload) =>
  fetchAPI<{ message: string; contact_id: string; intent: string; enrollment_status: string }>(
    `/api/sequences/v2/contacts/${contactId}/reply`,
    { method: "POST", body: JSON.stringify(payload) }
  );

export const rescheduleStep = (enrollmentId: string, step: number, newDate: string) =>
  fetchAPI<{ message: string; enrollment_id: string; step: number; new_next_action_at: string }>(
    `/api/sequences/v2/enrollments/${enrollmentId}/schedule`,
    { method: "PATCH", body: JSON.stringify({ step, new_date: newDate }) }
  );

// ---------------------------------------------------------------------------
// Intelligence — signals, funnel, velocity, costs, goals, command center
// ---------------------------------------------------------------------------

export interface IntentSignal {
  company_id: string;
  company_name: string;
  tier?: string;
  pqs_total: number;
  cluster?: string;
  status?: string;
  intent_score: number;
  intent_level: "hot" | "warm" | "warming" | "cold";
  pain_signals: string[];
  research_summary: string;
}

export interface BuyingSignal {
  contact_id: string;
  contact_name?: string;
  title?: string;
  persona_type?: string;
  company_id?: string;
  company_name?: string;
  tier?: string;
  pqs_total: number;
  cluster?: string;
  open_count: number;
  click_count: number;
  signal_description: string;
  intent_level: "hot" | "warm" | "warming";
  outreach_state?: string;
}

export interface CommandCenterData {
  attention_items: Array<{ type: string; count: number; label: string; href: string }>;
  kpis: {
    pipeline_total: number;
    researched: number;
    researched_pct: number;
    active_outreach: number;
    replies_this_week: number;
    meetings_booked: number;
    ai_cost_month: number;
    ai_cost_cap: number;
    ai_cost_pct: number;
  };
  reply_queue: CampaignThread[];
  draft_queue: OutreachDraft[];
  hot_signals: IntentSignal[];
  funnel_summary: Record<string, unknown>;
  weekly_goals: {
    targets: { researched_target: number; emails_sent_target: number; replies_target: number; meetings_target: number };
    actuals: { researched: number; emails_sent: number; replies: number; meetings: number };
  };
  billing_status: {
    tier: string;
    companies_this_month: number;
    companies_limit: number;
    usage_pct: number;
    over_limit: boolean;
    approaching_limit: boolean;
  };
}

export const getCommandCenter = () =>
  fetchAPI<CommandCenterData>("/api/command-center");

export const getIntelligenceSignals = () =>
  fetchAPI<{ intent_signals: IntentSignal[]; buying_signals: BuyingSignal[]; total_hot: number; total_warm: number }>(
    "/api/intelligence/signals"
  );

export const getIntelligenceFunnel = (days = 30) =>
  fetchAPI<{ funnel: Record<string, unknown>; by_vertical: unknown[]; by_persona: unknown[] }>(
    `/api/intelligence/funnel?days=${days}`
  );

export const getIntelligenceVelocity = () =>
  fetchAPI<{ data: { enriched_to_sequenced_days: number; sequenced_to_replied_days: number; overall_discovery_to_reply_days: number; contacts_with_reply: number } }>(
    "/api/intelligence/velocity"
  );

export const getIntelligenceCosts = () =>
  fetchAPI<{ data: { total_usd: number; research_usd: number; drafts_usd: number; by_agent: Record<string, number>; monthly_cap_usd: number; pct_of_cap: number }; anthropic_balance_usd: number | null; weekly_trend: unknown[] }>(
    "/api/intelligence/costs"
  );

export const getIntelligenceWeekly = (weeks = 8) =>
  fetchAPI<{ data: Array<{ week_start: string; contacts_added: number; sequenced: number; replied: number }> }>(
    `/api/intelligence/weekly?weeks=${weeks}`
  );

export const getIntelligenceGoals = () =>
  fetchAPI<{ targets: Record<string, number>; actuals: Record<string, number>; week_start: string }>(
    "/api/intelligence/goals"
  );

export const updateIntelligenceGoals = (data: {
  researched_target?: number;
  emails_sent_target?: number;
  replies_target?: number;
  meetings_target?: number;
}) =>
  fetchAPI<{ data: Record<string, number>; message: string }>("/api/intelligence/goals", {
    method: "PUT",
    body: JSON.stringify(data),
  });

// ---------------------------------------------------------------------------
// Personalization Engine — /api/personalization
// ---------------------------------------------------------------------------

export interface TriggerEvent {
  trigger_type: string;    // growth | pain | tech | timing
  description: string;
  urgency: string;         // immediate | near_term | background
  confidence: number;
  source_text: string;
  priority_rank: number;
}

export interface PersonalizationHook {
  hook_text: string;
  persona_target: string;
  trigger_reference: string;
  tone: string;            // specific | empathetic | provocative
  confidence: number;
}

export interface PersonalizationResult {
  company_id: string;
  readiness_score: number;
  readiness_breakdown: Record<string, number>;
  triggers: TriggerEvent[];
  hooks: PersonalizationHook[];
  personas_found: string[];
  contacts_updated: number;
  generated_at: string;
  cost_usd: number;
}

export interface BatchResult {
  processed: number;
  updated: number;
  errors: number;
  total_cost_usd: number;
  avg_readiness_score: number;
  error_details: Array<{ company_id: string; error: string }>;
}

export interface PersonalizationStatus {
  company_id: string;
  readiness_score: number;
  triggers: TriggerEvent[];
  hooks: PersonalizationHook[];
  personas_found: string[];
  last_run_at: string | null;
  contacts_count: number;
}

export interface PersonalizationFilters {
  cluster?: string;
  tranche?: string;
  min_pqs?: number;
}

export interface PersonalizationLeaderboardItem {
  company_id: string;
  company_name: string;
  cluster?: string;
  tranche?: string;
  readiness_score: number;
  trigger_count: number;
  hook_count: number;
  contact_count: number;
  personas_found: string[];
  last_run_at?: string;
  pqs_total: number;
}

export interface ManualTriggerInput {
  trigger_type: string;
  description: string;
  urgency: string;
  source?: string;
}

export const runPersonalization = (companyId: string): Promise<PersonalizationResult> =>
  fetchAPI<PersonalizationResult>(`/api/personalization/run/${companyId}`, {
    method: "POST",
  });

export const runPersonalizationBatch = (
  filters: PersonalizationFilters = {},
  maxCompanies = 50
): Promise<BatchResult> =>
  fetchAPI<BatchResult>("/api/personalization/run-batch", {
    method: "POST",
    body: JSON.stringify({ filters, max_companies: maxCompanies }),
  });

export const getPersonalizationStatus = (companyId: string): Promise<PersonalizationStatus> =>
  fetchAPI<PersonalizationStatus>(`/api/personalization/status/${companyId}`);

export const getPersonalizationLeaderboard = (params?: {
  limit?: number;
  cluster?: string;
  tranche?: string;
}): Promise<PersonalizationLeaderboardItem[]> => {
  const qs = params ? "?" + new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))
  ).toString() : "";
  return fetchAPI<PersonalizationLeaderboardItem[]>(`/api/personalization/leaderboard${qs}`);
};

export const addManualTrigger = (
  companyId: string,
  trigger: ManualTriggerInput
): Promise<TriggerEvent> =>
  fetchAPI<TriggerEvent>(`/api/personalization/add-trigger/${companyId}`, {
    method: "POST",
    body: JSON.stringify(trigger),
  });

// ---------------------------------------------------------------------------
// HITL — Human-in-the-Loop reply review queue
// ---------------------------------------------------------------------------

export interface HitlMessage {
  id: string;
  thread_id: string;
  direction: "inbound" | "outbound";
  subject?: string | null;
  body?: string;
  sent_at?: string;
  classification?: string | null;
  classification_confidence?: number | null;
  classification_reasoning?: string | null;
  extracted_entities?: Record<string, unknown> | null;
  summary?: string | null;
  next_action_suggestion?: string | null;
  hitl_action?: string | null;
  hitl_notes?: string | null;
  hitl_actioned_at?: string | null;
}

export interface HitlQueueItem {
  id: string;
  thread_id: string;
  message_id?: string | null;
  workspace_id: string;
  classification?: string | null;
  classification_confidence?: number | null;
  priority: number;
  status: string; // pending | reviewing | actioned | snoozed
  assigned_to?: string | null;
  snoozed_until?: string | null;
  created_at: string;
  actioned_at?: string | null;
  // Enriched
  message?: HitlMessage | null;
  company?: {
    id: string;
    name: string;
    tier?: string;
    pqs_total: number;
    status?: string;
    research_summary?: string;
    personalization_hooks?: string[];
  } | null;
  contact?: {
    id: string;
    full_name?: string;
    title?: string;
    email?: string;
    persona_type?: string;
  } | null;
}

export interface HitlDetailResponse {
  id: string;
  thread_id: string;
  message_id?: string | null;
  workspace_id: string;
  classification?: string | null;
  classification_confidence?: number | null;
  priority: number;
  status: string;
  created_at: string;
  actioned_at?: string | null;
  thread?: {
    id: string;
    status: string;
    current_step?: number;
    company_id: string;
    contact_id: string;
    last_replied_at?: string | null;
  } | null;
  messages?: HitlMessage[];
  company?: {
    id: string;
    name: string;
    tier?: string;
    pqs_total: number;
    status?: string;
    research_summary?: string;
    personalization_hooks?: string[];
  } | null;
  contact?: {
    id: string;
    full_name?: string;
    title?: string;
    email?: string;
    persona_type?: string;
  } | null;
  research?: {
    company_description?: string;
    manufacturing_type?: string;
    maintenance_approach?: string;
    iot_maturity?: string;
    personalization_hooks?: string[];
    pain_points?: string[];
  } | null;
}

export interface HitlStats {
  pending: number;
  reviewing: number;
  by_classification: Record<string, number>;
  avg_response_time_hours: number;
}

export const getHitlQueue = (params?: {
  status?: string;
  priority_max?: number;
  classification?: string;
  limit?: number;
}) => {
  const qs = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== null)
          .map(([k, v]) => [k, String(v)])
      ).toString()
    : "";
  return fetchAPI<{ data: HitlQueueItem[]; count: number; status_filter: string }>(
    `/api/hitl/queue${qs}`
  );
};

export const getHitlDetail = (hitlId: string) =>
  fetchAPI<{ data: HitlDetailResponse }>(`/api/hitl/queue/${hitlId}`);

export const actionHitlItem = (
  hitlId: string,
  action: string,
  notes?: string,
  snoozeUntil?: string
) =>
  fetchAPI<{ message: string; hitl_id: string; action: string; thread_id?: string }>(
    `/api/hitl/queue/${hitlId}/action`,
    {
      method: "PATCH",
      body: JSON.stringify({
        action,
        notes: notes ?? null,
        snooze_until: snoozeUntil ?? null,
      }),
    }
  );

export const getHitlStats = () =>
  fetchAPI<HitlStats>("/api/hitl/stats");

export interface AnalyticsSummary {
  pipeline_health: string;
  projected_arr_90d: number;
  total_replied: number;
  overall_conversion_rate: number;
  best_cluster: string;
  stuck_in_research_14d: number;
}

export const getAnalyticsSummary = () =>
  fetchAPI<AnalyticsSummary>("/api/analytics/summary");

export const suggestHitlResponse = (hitlId: string) =>
  fetchAPI<{ subject: string; body: string; tone_notes: string }>(
    `/api/hitl/queue/${hitlId}/suggest-response`,
    { method: "POST", body: JSON.stringify({}) }
  );

// ---------------------------------------------------------------------------
// Lookalike Discovery
// ---------------------------------------------------------------------------

export interface SeedProfile {
  seed_company_ids: string[];
  seed_company_count: number;
  dominant_cluster: string;
  dominant_tranche: string;
  employee_count_range: [number, number];
  revenue_ranges: string[];
  top_technologies: string[];
  top_pain_themes: string[];
  avg_pqs: number;
}

export interface LookalikeMatch {
  company_id: string;
  company_name: string;
  domain: string | null;
  cluster: string | null;
  tranche: string | null;
  employee_count: number | null;
  revenue_range: string | null;
  similarity_score: number;
  matching_factors: string[];
  pqs_total: number;
  status: string;
  has_contact: boolean;
}

export interface LookalikeResult {
  run_id: string | null;
  seed_profile: SeedProfile;
  matches: LookalikeMatch[];
  total_scored: number;
  generated_at: string;
}

export interface LookalikeRunSummary {
  id: string;
  created_at: string;
  match_count: number;
  seed_count: number;
  dominant_cluster: string;
  dominant_tranche: string;
}

export const runLookalike = (
  seedIds: string[],
  limit?: number,
  excludeContacted?: boolean
) =>
  fetchAPI<LookalikeResult>("/api/lookalike/run", {
    method: "POST",
    body: JSON.stringify({
      seed_company_ids: seedIds,
      limit: limit ?? 50,
      exclude_contacted: excludeContacted ?? true,
    }),
  });

export const runAutoLookalike = () =>
  fetchAPI<LookalikeResult>("/api/lookalike/auto-run", {
    method: "POST",
    body: JSON.stringify({}),
  });

export const getLookalikeRuns = () =>
  fetchAPI<{ data: LookalikeRunSummary[]; count: number }>("/api/lookalike/runs");

export const getLookalikeRun = (runId: string) =>
  fetchAPI<{
    id: string;
    created_at: string;
    seed_profile: SeedProfile;
    matches: LookalikeMatch[];
    total_scored: number;
  }>(`/api/lookalike/runs/${runId}`);

export const addLookalikesToPipeline = (
  runId: string,
  companyIds: string[],
  sequenceName?: string
) =>
  fetchAPI<{ added: number; already_in_pipeline: number }>(
    `/api/lookalike/runs/${runId}/add-to-pipeline`,
    {
      method: "POST",
      body: JSON.stringify({
        company_ids: companyIds,
        sequence_name: sequenceName ?? null,
      }),
    }
  );

export const getSeedProfile = () =>
  fetchAPI<SeedProfile>("/api/lookalike/seed-profile");

// ---------------------------------------------------------------------------
// Email Engagement
// ---------------------------------------------------------------------------

export interface EmailEngagementRow {
  draft_id: string;
  contact_id: string | null;
  contact_name: string;
  contact_email: string;
  persona_type: string | null;
  company_id: string | null;
  company_name: string;
  industry: string | null;
  sequence_step: number;
  subject: string | null;
  sent_at: string;
  resend_status: string | null;
  resend_message_id: string | null;
  display_status: string;
  opens: number;
  clicks: number;
  bounced: boolean;
  complained: boolean;
  last_open_at: string | null;
}

export const getEmailEngagement = (limit = 200, offset = 0) =>
  fetchAPI<{ data: EmailEngagementRow[]; total: number }>(
    `/api/sequences/v2/email-engagement?limit=${limit}&offset=${offset}`
  );
