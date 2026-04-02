"""Pydantic models for ProspectIQ.

These models define the data contracts between agents and integrations.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# Enums (matching database enums)
# ============================================================

class EnrichmentStatus(str, Enum):
    NEEDS_ENRICHMENT = "needs_enrichment"
    PENDING = "pending"
    ENRICHED = "enriched"
    FAILED = "failed"
    STALE = "stale"


class CompanyStatus(str, Enum):
    DISCOVERED = "discovered"
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    OUTREACH_PENDING = "outreach_pending"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    MEETING_SCHEDULED = "meeting_scheduled"
    PILOT_DISCUSSION = "pilot_discussion"
    PILOT_SIGNED = "pilot_signed"
    ACTIVE_PILOT = "active_pilot"
    CONVERTED = "converted"
    NOT_INTERESTED = "not_interested"
    PAUSED = "paused"
    BOUNCED = "bounced"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class ChannelType(str, Enum):
    EMAIL = "email"
    LINKEDIN = "linkedin"
    PHONE = "phone"
    OTHER = "other"


class InteractionType(str, Enum):
    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    EMAIL_REPLIED = "email_replied"
    EMAIL_BOUNCED = "email_bounced"
    LINKEDIN_CONNECTION = "linkedin_connection"
    LINKEDIN_MESSAGE = "linkedin_message"
    PHONE_CALL = "phone_call"
    MEETING = "meeting"
    NOTE = "note"
    STATUS_CHANGE = "status_change"


# ============================================================
# Company Models
# ============================================================

class CompanyCreate(BaseModel):
    """Data required to create a new company from Apollo discovery."""
    apollo_id: Optional[str] = None
    name: str
    domain: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    naics_code: Optional[str] = None
    sub_sector: Optional[str] = None
    tier: Optional[str] = None
    employee_count: Optional[int] = None
    revenue_range: Optional[str] = None
    estimated_revenue: Optional[int] = None
    founded_year: Optional[int] = None
    is_private: Optional[bool] = None
    street_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "US"
    territory: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    phone: Optional[str] = None
    status: CompanyStatus = CompanyStatus.DISCOVERED
    campaign_name: Optional[str] = None
    batch_id: Optional[str] = None


class CompanyUpdate(BaseModel):
    """Fields that can be updated on a company."""
    research_summary: Optional[str] = None
    technology_stack: Optional[list] = None
    pain_signals: Optional[list] = None
    manufacturing_profile: Optional[dict] = None
    personalization_hooks: Optional[list] = None
    pqs_total: Optional[int] = None
    pqs_firmographic: Optional[int] = None
    pqs_technographic: Optional[int] = None
    pqs_timing: Optional[int] = None
    pqs_engagement: Optional[int] = None
    qualification_notes: Optional[str] = None
    status: Optional[CompanyStatus] = None
    priority_flag: Optional[bool] = None


# ============================================================
# Contact Models
# ============================================================

class ContactCreate(BaseModel):
    """Data required to create a new contact."""
    company_id: str
    apollo_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    seniority: Optional[str] = None
    department: Optional[str] = None
    headline: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    photo_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    is_decision_maker: bool = False
    persona_type: Optional[str] = None
    role: Optional[str] = None
    enrichment_status: EnrichmentStatus = EnrichmentStatus.NEEDS_ENRICHMENT
    enrichment_source: Optional[str] = None

    @field_validator("apollo_id")
    @classmethod
    def apollo_id_must_be_full(cls, v: Optional[str]) -> Optional[str]:
        """Reject truncated Apollo IDs — must be at least 24 chars."""
        if v is not None and len(v) < 24:
            raise ValueError(
                f"apollo_id '{v}' is only {len(v)} chars — must be the full 24-char Apollo person ID. "
                "Truncated IDs cause enrichment failures."
            )
        return v


# ============================================================
# Enrichment & Credit Models
# ============================================================

class ApolloEnrichmentJob(BaseModel):
    """Batch of contacts queued for Apollo bulk match enrichment."""
    contact_ids: list[str]
    campaign_name: Optional[str] = None
    batch_id: Optional[str] = None
    dry_run: bool = False


class ApolloCreditEvent(BaseModel):
    """One Apollo API credit spend event."""
    operation: str          # people_match | people_bulk_match | org_enrich | people_search
    credits_used: int = 1
    contact_id: Optional[str] = None
    company_id: Optional[str] = None
    batch_id: Optional[str] = None
    campaign_name: Optional[str] = None
    response_status: str = "success"   # success | failed | no_match
    notes: Optional[str] = None


class SeedAuditEvent(BaseModel):
    """One record from an idempotent seed / import script."""
    script_name: str
    entity_type: str        # company | contact
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    action: str             # created | skipped | updated | deleted | failed
    source: Optional[str] = None  # apollo_mcp | csv | manual | api
    details: Optional[str] = None


class ReadinessCheck(BaseModel):
    """Result of a campaign readiness gate evaluation for one company."""
    company_id: str
    company_name: str
    campaign_name: str
    is_ready: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    enriched_contacts: int = 0
    total_contacts: int = 0
    has_domain: bool = False


# ============================================================
# Research Intelligence Models
# ============================================================

class TriggerEvent(BaseModel):
    """A buying trigger event detected during company research."""
    type: str = ""  # leadership_change, ma_pe, esg_commitment, operational_incident, capex_investment, growth_signal, competitor_displacement
    description: str = ""
    date_approx: str = ""  # YYYY-QQ or YYYY-MM or 'Unknown'
    outreach_relevance: str = ""


class ResearchResult(BaseModel):
    """Structured output from the Research Agent's Claude analysis."""
    company_description: str = ""
    manufacturing_type: str = "unknown"  # discrete, process, hybrid
    equipment_types: list[str] = Field(default_factory=list)
    known_systems: list[str] = Field(default_factory=list)
    iot_maturity: str = "unknown"  # none, basic, intermediate, advanced
    maintenance_approach: str = "unknown"  # reactive, time_based, condition_based, predictive
    digital_transformation_status: str = ""
    pain_points: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    existing_solutions: list[str] = Field(default_factory=list)
    funding_status: str = ""
    funding_details: str = ""
    trigger_events: list[TriggerEvent] = Field(default_factory=list)
    trigger_score: int = 0  # 0-10; higher = more compelling buying triggers detected
    personalization_hooks: list[str] = Field(default_factory=list)
    confidence_level: str = "low"  # high, medium, low
    # Awareness level: how aware the prospect is of AI manufacturing intelligence solutions.
    # unaware         — no evidence they know solutions like Digitillis exist
    # problem_aware   — they know the problem (downtime, quality, etc.) but not specific AI solutions
    # solution_aware  — they know AI manufacturing platforms exist; may be evaluating options
    awareness_level: str = "unaware"  # unaware, problem_aware, solution_aware


# ============================================================
# Qualification Models
# ============================================================

class PQSScore(BaseModel):
    """Prospect Quality Score breakdown."""
    firmographic: int = 0
    technographic: int = 0
    timing: int = 0
    engagement: int = 0
    total: int = 0
    classification: str = "unqualified"  # unqualified, research_needed, qualified, high_priority, hot_prospect
    notes: str = ""


# ============================================================
# Outreach Models
# ============================================================

class OutreachDraft(BaseModel):
    """An AI-generated outreach message pending approval."""
    company_id: str
    contact_id: str
    channel: ChannelType = ChannelType.EMAIL
    sequence_name: str = "initial_outreach"
    sequence_step: int = 1
    subject: str = ""
    body: str = ""
    personalization_notes: str = ""


class OutreachApproval(BaseModel):
    """Approval decision for an outreach draft."""
    draft_id: str
    status: ApprovalStatus
    edited_body: Optional[str] = None
    rejection_reason: Optional[str] = None


# ============================================================
# Interaction Models
# ============================================================

class InteractionCreate(BaseModel):
    """Data for logging a new interaction."""
    company_id: str
    contact_id: Optional[str] = None
    type: InteractionType
    channel: Optional[ChannelType] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    source: str = "system"
    external_id: Optional[str] = None


# ============================================================
# API Cost Models
# ============================================================

class APICost(BaseModel):
    """Track API usage costs."""
    provider: str  # anthropic, perplexity, apollo, instantly
    model: Optional[str] = None
    endpoint: Optional[str] = None
    company_id: Optional[str] = None
    batch_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    estimated_cost_usd: float = 0.0
