-- Migration 029: outreach_send_config table
-- Stores per-workspace outreach sending limits (daily cap, batch size, etc.)
-- Values are read at send time — no hardcoding in application code.

CREATE TABLE IF NOT EXISTS outreach_send_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    daily_limit     INT  NOT NULL DEFAULT 30,   -- max emails per calendar day
    batch_size      INT  NOT NULL DEFAULT 10,   -- max emails per scheduler run
    min_gap_minutes INT  NOT NULL DEFAULT 4,    -- min minutes between emails in a batch
    send_enabled    BOOLEAN NOT NULL DEFAULT true,
    notes           TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id)
);

-- Seed default config for the default workspace
INSERT INTO outreach_send_config (workspace_id, daily_limit, batch_size, min_gap_minutes)
VALUES ('00000000-0000-0000-0000-000000000001', 30, 10, 4)
ON CONFLICT (workspace_id) DO NOTHING;

-- Also add resend_message_id column to outreach_drafts if not present
ALTER TABLE outreach_drafts
    ADD COLUMN IF NOT EXISTS resend_message_id TEXT,
    ADD COLUMN IF NOT EXISTS resend_status TEXT;  -- delivered | bounced | opened etc (from webhook)

COMMENT ON TABLE outreach_send_config IS
    'Per-workspace outreach sending limits. Edit rows here to change send behaviour — no code deploy needed.';
