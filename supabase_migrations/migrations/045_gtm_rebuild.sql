-- GTM rebuild: approval gate + engagement tiers
-- Phase 1-4 support columns

-- outreach_drafts: reviewer tracking
ALTER TABLE outreach_drafts
  ADD COLUMN IF NOT EXISTS approved_by    TEXT,
  ADD COLUMN IF NOT EXISTS reviewed_at    TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS attestation    JSONB;

-- approval_status enum: tier-1 two-reviewer flow
ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'pending_second_review';

-- companies: engagement tier classification
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS engagement_tier TEXT;

CREATE INDEX IF NOT EXISTS idx_companies_engagement_tier
  ON companies (engagement_tier)
  WHERE engagement_tier IS NOT NULL;

-- company_outreach_state: hot-tier timestamps for velocity SLO
ALTER TABLE company_outreach_state
  ADD COLUMN IF NOT EXISTS hot_at                 TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS last_founder_action_at TIMESTAMP WITH TIME ZONE;
