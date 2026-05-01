-- Migration 030: Per-workspace encrypted credential storage
-- Stores API keys (Apollo, Resend, Gmail, Perplexity) per workspace,
-- encrypted at rest using AES-256 (Fernet). Decryption key lives in
-- CREDENTIAL_ENCRYPTION_KEY env var — never stored in DB.

CREATE TABLE IF NOT EXISTS workspace_credentials (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID       NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider    TEXT        NOT NULL,  -- apollo | resend | gmail | perplexity | anthropic
    key_name    TEXT        NOT NULL,  -- api_key | app_password | webhook_secret etc.
    ciphertext  TEXT        NOT NULL,  -- Fernet-encrypted value (base64url)
    hint        TEXT,                  -- last 4 chars of plaintext for display only
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, provider, key_name)
);

CREATE INDEX IF NOT EXISTS idx_workspace_creds_ws
    ON workspace_credentials (workspace_id, provider);

ALTER TABLE workspace_credentials ENABLE ROW LEVEL SECURITY;

-- Authenticated users can only see their own workspace credentials
CREATE POLICY "workspace_member_creds" ON workspace_credentials
    FOR ALL USING (
        workspace_id = public.current_workspace_id()
    );

-- Service role bypass for backend agents
CREATE POLICY "service_role_creds" ON workspace_credentials
    FOR ALL TO service_role USING (true);

-- Trigger: keep updated_at current
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER workspace_credentials_updated_at
    BEFORE UPDATE ON workspace_credentials
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Workspace send config: per-workspace daily limits and sender settings
-- (previously global env vars; now stored per workspace)
ALTER TABLE outreach_send_config
    ADD COLUMN IF NOT EXISTS sender_pool   JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS reply_to      TEXT,
    ADD COLUMN IF NOT EXISTS gmail_user    TEXT;
