-- Migration 019: Visual Sequence Builder V2
-- Stores sequences created via the visual builder with full SequenceStepV2 schema.

CREATE TABLE IF NOT EXISTS campaign_sequence_definitions_v2 (
  id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  display_name TEXT,
  description  TEXT,
  cluster      TEXT,
  persona      TEXT,
  steps        JSONB NOT NULL DEFAULT '[]',
  is_template  BOOLEAN NOT NULL DEFAULT false,
  tags         TEXT[] NOT NULL DEFAULT '{}',
  is_active    BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seq_v2_workspace ON campaign_sequence_definitions_v2(workspace_id);
CREATE INDEX IF NOT EXISTS idx_seq_v2_active    ON campaign_sequence_definitions_v2(workspace_id, is_active);
CREATE INDEX IF NOT EXISTS idx_seq_v2_template  ON campaign_sequence_definitions_v2(workspace_id, is_template);
