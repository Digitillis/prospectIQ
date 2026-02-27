-- ProspectIQ Database Schema
-- Supabase (PostgreSQL) migration

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- ENUMS
-- ============================================================

CREATE TYPE company_status AS ENUM (
    'discovered',
    'researched',
    'qualified',
    'disqualified',
    'outreach_pending',
    'contacted',
    'engaged',
    'meeting_scheduled',
    'pilot_discussion',
    'pilot_signed',
    'active_pilot',
    'converted',
    'not_interested',
    'paused',
    'bounced'
);

CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'edited');

CREATE TYPE channel_type AS ENUM ('email', 'linkedin', 'phone', 'other');

CREATE TYPE interaction_type AS ENUM (
    'email_sent',
    'email_opened',
    'email_clicked',
    'email_replied',
    'email_bounced',
    'linkedin_connection',
    'linkedin_message',
    'phone_call',
    'meeting',
    'note',
    'status_change'
);

-- ============================================================
-- COMPANIES
-- ============================================================

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    apollo_id TEXT UNIQUE,
    name TEXT NOT NULL,
    domain TEXT,
    website TEXT,

    -- Industry classification
    industry TEXT,
    naics_code TEXT,
    sub_sector TEXT,
    tier TEXT,  -- '1a', '1b', '2', '3', '4', '5'

    -- Firmographic
    employee_count INTEGER,
    revenue_range TEXT,
    estimated_revenue BIGINT,
    founded_year INTEGER,
    is_private BOOLEAN,

    -- Location
    street_address TEXT,
    city TEXT,
    state TEXT,
    country TEXT DEFAULT 'US',
    territory TEXT,  -- Deterministic from state

    -- Social / contact
    linkedin_url TEXT,
    twitter_url TEXT,
    phone TEXT,

    -- AI-derived intelligence (populated by Research Agent)
    research_summary TEXT,
    technology_stack JSONB DEFAULT '[]'::jsonb,
    pain_signals JSONB DEFAULT '[]'::jsonb,
    manufacturing_profile JSONB DEFAULT '{}'::jsonb,
    personalization_hooks JSONB DEFAULT '[]'::jsonb,

    -- Qualification scores (PQS: 0-25 each dimension)
    pqs_total INTEGER DEFAULT 0,
    pqs_firmographic INTEGER DEFAULT 0,
    pqs_technographic INTEGER DEFAULT 0,
    pqs_timing INTEGER DEFAULT 0,
    pqs_engagement INTEGER DEFAULT 0,
    qualification_notes TEXT,

    -- Lifecycle
    status company_status DEFAULT 'discovered',
    status_changed_at TIMESTAMPTZ DEFAULT NOW(),
    priority_flag BOOLEAN DEFAULT FALSE,

    -- Tracking
    campaign_name TEXT,
    batch_id TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- CONTACTS
-- ============================================================

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    apollo_id TEXT UNIQUE,

    -- Personal
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    email TEXT,
    phone TEXT,

    -- Professional
    title TEXT,
    seniority TEXT,
    department TEXT,
    headline TEXT,

    -- Social
    linkedin_url TEXT,
    twitter_url TEXT,
    photo_url TEXT,

    -- Location
    city TEXT,
    state TEXT,
    country TEXT,

    -- Classification
    is_decision_maker BOOLEAN DEFAULT FALSE,
    persona_type TEXT,  -- 'vp_ops', 'plant_manager', 'cio', 'coo', 'digital_transformation', 'director_ops', 'vp_manufacturing'

    -- Lifecycle
    status TEXT DEFAULT 'identified',  -- identified, enriched, contacted, engaged, not_interested, bounced

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RESEARCH INTELLIGENCE
-- ============================================================

CREATE TABLE research_intelligence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE UNIQUE,

    -- Raw responses
    perplexity_response TEXT,
    claude_analysis TEXT,

    -- Structured intelligence
    company_description TEXT,
    manufacturing_type TEXT,  -- 'discrete', 'process', 'hybrid'
    equipment_types JSONB DEFAULT '[]'::jsonb,
    known_systems JSONB DEFAULT '[]'::jsonb,
    iot_maturity TEXT,  -- 'none', 'basic', 'intermediate', 'advanced'
    maintenance_approach TEXT,  -- 'reactive', 'time_based', 'condition_based', 'predictive'
    digital_transformation_status TEXT,

    -- Pain points & opportunities
    pain_points JSONB DEFAULT '[]'::jsonb,
    opportunities JSONB DEFAULT '[]'::jsonb,

    -- Competitive landscape
    existing_solutions JSONB DEFAULT '[]'::jsonb,

    -- Financial intelligence
    funding_status TEXT,
    funding_details TEXT,
    recent_investments TEXT,

    -- Quality
    confidence_level TEXT DEFAULT 'low',  -- 'high', 'medium', 'low'
    researched_at TIMESTAMPTZ DEFAULT NOW(),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- OUTREACH DRAFTS
-- ============================================================

CREATE TABLE outreach_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,

    -- Message
    channel channel_type NOT NULL DEFAULT 'email',
    sequence_name TEXT,
    sequence_step INTEGER DEFAULT 1,
    subject TEXT,
    body TEXT,
    personalization_notes TEXT,

    -- Approval workflow
    approval_status approval_status DEFAULT 'pending',
    edited_body TEXT,
    rejection_reason TEXT,
    approved_at TIMESTAMPTZ,

    -- Sending
    sent_at TIMESTAMPTZ,
    instantly_lead_id TEXT,
    instantly_campaign_id TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INTERACTIONS (immutable event log)
-- ============================================================

CREATE TABLE interactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,

    type interaction_type NOT NULL,
    channel channel_type,

    subject TEXT,
    body TEXT,

    -- Event metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Source tracking
    source TEXT,  -- 'instantly_webhook', 'manual', 'apollo', 'system'
    external_id TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ENGAGEMENT SEQUENCES
-- ============================================================

CREATE TABLE engagement_sequences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,

    sequence_name TEXT NOT NULL,
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER,

    status TEXT DEFAULT 'active',  -- 'active', 'paused', 'completed', 'cancelled'

    next_action_at TIMESTAMPTZ,
    next_action_type TEXT,  -- 'send_email', 'linkedin_touch', 'phone_call', 'wait'

    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- API COSTS
-- ============================================================

CREATE TABLE api_costs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    provider TEXT NOT NULL,  -- 'anthropic', 'perplexity', 'apollo', 'instantly'
    model TEXT,
    endpoint TEXT,

    company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    batch_id TEXT,

    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_usd DECIMAL(10, 6),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- LEARNING OUTCOMES
-- ============================================================

CREATE TABLE learning_outcomes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,

    -- What was tried
    outreach_approach TEXT,
    channel channel_type,
    message_theme TEXT,  -- 'roi_focused', 'pain_point', 'industry_trend', 'peer_reference'
    personalization_level TEXT,  -- 'high', 'medium', 'low'

    -- What happened
    outcome TEXT,  -- 'opened', 'replied_positive', 'replied_negative', 'no_response', 'meeting_booked'

    -- Context at time of outreach
    company_tier TEXT,
    sub_sector TEXT,
    persona_type TEXT,
    pqs_at_time INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Companies
CREATE INDEX idx_companies_status ON companies(status);
CREATE INDEX idx_companies_pqs ON companies(pqs_total DESC);
CREATE INDEX idx_companies_tier_state ON companies(tier, state);
CREATE INDEX idx_companies_batch ON companies(batch_id);
CREATE INDEX idx_companies_domain ON companies(domain);

-- Contacts
CREATE INDEX idx_contacts_company ON contacts(company_id);
CREATE INDEX idx_contacts_persona ON contacts(persona_type);
CREATE INDEX idx_contacts_email ON contacts(email);

-- Outreach Drafts
CREATE INDEX idx_drafts_approval ON outreach_drafts(approval_status, created_at);
CREATE INDEX idx_drafts_company ON outreach_drafts(company_id);

-- Interactions
CREATE INDEX idx_interactions_company ON interactions(company_id, created_at DESC);
CREATE INDEX idx_interactions_contact ON interactions(contact_id, created_at DESC);
CREATE INDEX idx_interactions_type ON interactions(type);

-- Engagement Sequences
CREATE INDEX idx_sequences_status_next ON engagement_sequences(status, next_action_at);
CREATE INDEX idx_sequences_company ON engagement_sequences(company_id);

-- API Costs
CREATE INDEX idx_costs_provider ON api_costs(provider, created_at);
CREATE INDEX idx_costs_batch ON api_costs(batch_id);

-- ============================================================
-- TRIGGERS: auto-update updated_at
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER contacts_updated_at
    BEFORE UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER research_intelligence_updated_at
    BEFORE UPDATE ON research_intelligence
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER outreach_drafts_updated_at
    BEFORE UPDATE ON outreach_drafts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER engagement_sequences_updated_at
    BEFORE UPDATE ON engagement_sequences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- TRIGGER: auto-update status_changed_at on companies
-- ============================================================

CREATE OR REPLACE FUNCTION update_status_changed_at()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        NEW.status_changed_at = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER companies_status_changed
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_status_changed_at();
