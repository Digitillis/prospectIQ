-- Copyright © 2026 ProspectIQ. All rights reserved.
-- Authors: Avanish Mehrotra & ProspectIQ Technical Team
--
-- Migration 026: Voice of Prospect
-- Stores cached analysis snapshots of reply corpus intelligence

CREATE TABLE voice_of_prospect_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  total_replies_analysed INT DEFAULT 0,
  data_quality VARCHAR(20) DEFAULT 'demo',  -- rich | moderate | limited | demo
  resonance_themes JSONB DEFAULT '[]',      -- list[MessagingTheme]
  objection_themes JSONB DEFAULT '[]',      -- list[MessagingTheme]
  persona_engagement JSONB DEFAULT '[]',    -- list[PersonaEngagement]
  sequence_dropoff JSONB DEFAULT '[]',      -- list[SequenceStepMetrics]
  top_performing_angle TEXT,
  top_objection TEXT,
  recommended_adjustment TEXT,
  analysed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_vop_snapshots_workspace
  ON voice_of_prospect_snapshots(workspace_id, analysed_at DESC);
