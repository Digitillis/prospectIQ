-- Migration 028: Meetings and Deals Infrastructure
-- Adds tables for meeting scheduling and deal pipeline management

BEGIN;

-- Meetings table
CREATE TABLE IF NOT EXISTS meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  scheduled_at TIMESTAMPTZ NOT NULL,
  duration_minutes INTEGER DEFAULT 30,
  status TEXT NOT NULL DEFAULT 'scheduled', -- scheduled, confirmed, completed, cancelled, no_show
  meeting_type TEXT NOT NULL DEFAULT 'discovery', -- discovery, demo, close, check-in
  title TEXT,
  description TEXT,
  location TEXT, -- Physical location or Zoom URL
  organizer_email TEXT,
  created_by UUID NOT NULL REFERENCES auth.users(id),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT valid_status CHECK (status IN ('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show')),
  CONSTRAINT valid_type CHECK (meeting_type IN ('discovery', 'demo', 'close', 'check-in', 'follow-up'))
);

CREATE INDEX idx_meetings_workspace ON meetings(workspace_id);
CREATE INDEX idx_meetings_company ON meetings(company_id);
CREATE INDEX idx_meetings_contact ON meetings(contact_id);
CREATE INDEX idx_meetings_scheduled_at ON meetings(scheduled_at);
CREATE INDEX idx_meetings_status ON meetings(status);

-- Deals table
CREATE TABLE IF NOT EXISTS deals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  contact_id BIGINT REFERENCES contacts(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  amount DECIMAL(12, 2),
  currency TEXT DEFAULT 'USD',
  stage TEXT NOT NULL DEFAULT 'prospect', -- prospect, qualified, proposal, negotiation, won, lost
  probability SMALLINT DEFAULT 25, -- 0-100 percentage
  expected_close_date DATE,
  close_date DATE,
  source TEXT, -- outreach, inbound, partnership, etc.
  reason_lost TEXT, -- Only if stage = lost
  notes TEXT,
  created_by UUID NOT NULL REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT valid_stage CHECK (stage IN ('prospect', 'qualified', 'proposal', 'negotiation', 'won', 'lost')),
  CONSTRAINT valid_probability CHECK (probability >= 0 AND probability <= 100)
);

CREATE INDEX idx_deals_workspace ON deals(workspace_id);
CREATE INDEX idx_deals_company ON deals(company_id);
CREATE INDEX idx_deals_stage ON deals(stage);
CREATE INDEX idx_deals_probability ON deals(probability);
CREATE INDEX idx_deals_expected_close ON deals(expected_close_date);

-- Meeting Attendees junction table
CREATE TABLE IF NOT EXISTS meeting_attendees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  contact_email TEXT NOT NULL,
  contact_name TEXT,
  response_status TEXT DEFAULT 'pending', -- pending, accepted, declined, tentative
  attended BOOLEAN,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT valid_response CHECK (response_status IN ('pending', 'accepted', 'declined', 'tentative'))
);

CREATE INDEX idx_meeting_attendees_meeting ON meeting_attendees(meeting_id);
CREATE INDEX idx_meeting_attendees_status ON meeting_attendees(response_status);

-- Deal Activities (for tracking interactions tied to deals)
CREATE TABLE IF NOT EXISTS deal_activities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
  activity_type TEXT NOT NULL, -- email, call, meeting, proposal_sent, proposal_received, note
  description TEXT,
  activity_date TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID NOT NULL REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_deal_activities_deal ON deal_activities(deal_id);
CREATE INDEX idx_deal_activities_type ON deal_activities(activity_type);
CREATE INDEX idx_deal_activities_date ON deal_activities(activity_date);

-- Backfill workspace_id for meetings and deals (default workspace for now)
-- These will be populated by application when records are created

-- Enable RLS on new tables
ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_attendees ENABLE ROW LEVEL SECURITY;
ALTER TABLE deal_activities ENABLE ROW LEVEL SECURITY;

-- RLS Policies for meetings
CREATE POLICY "Users can view meetings in their workspace" ON meetings
  FOR SELECT USING (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

CREATE POLICY "Users can insert meetings in their workspace" ON meetings
  FOR INSERT WITH CHECK (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

CREATE POLICY "Users can update meetings in their workspace" ON meetings
  FOR UPDATE USING (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

CREATE POLICY "Users can delete meetings in their workspace" ON meetings
  FOR DELETE USING (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

-- RLS Policies for deals
CREATE POLICY "Users can view deals in their workspace" ON deals
  FOR SELECT USING (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

CREATE POLICY "Users can insert deals in their workspace" ON deals
  FOR INSERT WITH CHECK (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

CREATE POLICY "Users can update deals in their workspace" ON deals
  FOR UPDATE USING (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

CREATE POLICY "Users can delete deals in their workspace" ON deals
  FOR DELETE USING (workspace_id IN (
    SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
  ));

-- RLS Policies for meeting_attendees (inherits from meeting)
CREATE POLICY "Users can view meeting attendees in their workspace meetings" ON meeting_attendees
  FOR SELECT USING (meeting_id IN (
    SELECT id FROM meetings WHERE workspace_id IN (
      SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
    )
  ));

-- RLS Policies for deal_activities (inherits from deal)
CREATE POLICY "Users can view deal activities in their workspace deals" ON deal_activities
  FOR SELECT USING (deal_id IN (
    SELECT id FROM deals WHERE workspace_id IN (
      SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()
    )
  ));

COMMIT;
