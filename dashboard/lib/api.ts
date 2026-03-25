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
