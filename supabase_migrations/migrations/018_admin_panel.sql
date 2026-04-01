-- Migration 018: Admin panel additions
-- 1. workspace_audit_log — record every significant action for the workspace owner
-- 2. workspace_members.status + invite_token — support the invite flow

-- ============================================================
-- 1. WORKSPACE AUDIT LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS workspace_audit_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID,                       -- NULL for system/pipeline actions
    user_email   TEXT,
    action       TEXT NOT NULL,              -- e.g. "member.invited", "api_key.created"
    resource_type TEXT,                      -- e.g. "company", "contact", "api_key"
    resource_id  TEXT,                       -- FK to the affected row (as text)
    metadata     JSONB DEFAULT '{}'::jsonb,  -- extra context
    ip_address   TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_workspace
    ON workspace_audit_log (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_user
    ON workspace_audit_log (user_id, created_at DESC);

-- ============================================================
-- 2. WORKSPACE MEMBERS — invitation support
-- ============================================================

-- status: 'active' (joined) | 'pending' (invite sent, not yet accepted)
ALTER TABLE workspace_members
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';

-- One-time token used in the invite link; NULLed out after acceptance
ALTER TABLE workspace_members
    ADD COLUMN IF NOT EXISTS invite_token TEXT UNIQUE;

-- When the invite email was sent (NULL for directly-added members)
ALTER TABLE workspace_members
    ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_workspace_members_invite_token
    ON workspace_members (invite_token)
    WHERE invite_token IS NOT NULL;
