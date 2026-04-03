-- Copyright © 2026 ProspectIQ. All rights reserved.
-- Authors: Avanish Mehrotra & ProspectIQ Technical Team
--
-- Migration 024: Multi-Thread Account Campaign Orchestration
-- Adds account-level campaign coordination, contact thread tracking,
-- and suppression logic for coordinated multi-contact outreach.

-- ---------------------------------------------------------------------------
-- Account-level campaign thread coordinator
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  campaign_name TEXT NOT NULL,
  strategy TEXT NOT NULL DEFAULT 'parallel',  -- parallel | sequential | waterfall
  status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active | paused | completed
  coordinator_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Individual contact threads within an account campaign
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_campaign_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_campaign_id UUID NOT NULL REFERENCES account_campaigns(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  role_label TEXT,  -- 'economic_buyer' | 'champion' | 'technical_evaluator' | 'influencer' | 'other'
  messaging_angle TEXT,  -- brief description of this thread's angle
  sequence_step INT NOT NULL DEFAULT 1,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  last_touch_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Suppression: prevent same message going to same company within N days
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_suppression_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  company_id UUID NOT NULL,
  contact_id UUID NOT NULL,
  message_type TEXT NOT NULL,  -- 'email' | 'linkedin'
  sent_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_account_campaigns_workspace
  ON account_campaigns(workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_account_threads_campaign
  ON account_campaign_threads(account_campaign_id);

CREATE INDEX IF NOT EXISTS idx_suppression_company
  ON account_suppression_log(workspace_id, company_id, sent_at DESC);

-- ---------------------------------------------------------------------------
-- Auto-update updated_at on account_campaigns
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_account_campaigns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_account_campaigns_updated_at ON account_campaigns;
CREATE TRIGGER trg_account_campaigns_updated_at
  BEFORE UPDATE ON account_campaigns
  FOR EACH ROW
  EXECUTE FUNCTION update_account_campaigns_updated_at();
