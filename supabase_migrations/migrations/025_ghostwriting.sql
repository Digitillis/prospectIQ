-- Copyright © 2026 ProspectIQ. All rights reserved.
-- Authors: Avanish Mehrotra & ProspectIQ Technical Team
--
-- Migration 025: Ghostwriting Engine
-- Creates voice_profiles and ghostwritten_posts tables

CREATE TABLE voice_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  profile_name TEXT NOT NULL DEFAULT 'My Voice',
  writing_samples TEXT[] NOT NULL DEFAULT '{}',  -- up to 5 past posts
  extracted_style JSONB DEFAULT '{}',  -- tone, vocabulary, sentence_length, structure
  calibrated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ghostwritten_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  voice_profile_id UUID REFERENCES voice_profiles(id) ON DELETE SET NULL,
  topic TEXT NOT NULL,
  content_type VARCHAR(30) NOT NULL DEFAULT 'linkedin_post',  -- linkedin_post | short_article | thread
  generated_content TEXT NOT NULL,
  hook_line TEXT,       -- first line extracted for preview
  word_count INT,
  status VARCHAR(20) DEFAULT 'draft',  -- draft | published | archived
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_voice_profiles_workspace ON voice_profiles(workspace_id);
CREATE INDEX idx_ghostwritten_posts_workspace ON ghostwritten_posts(workspace_id, created_at DESC);
