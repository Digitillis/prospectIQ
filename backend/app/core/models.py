"""Pydantic models for ProspectIQ.

These models define the data contracts between agents and integrations.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# Enums (matching database enums)
# ============================================================

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


# ============================================================
# Research Intelligence Models
# ============================================================

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
    personalization_hooks: list[str] = Field(default_factory=list)
    confidence_level: str = "low"  # high, medium, low


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
