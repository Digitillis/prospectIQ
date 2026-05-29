-- 057_scheduler_state.sql
-- Persistent last-run cursor for cron jobs so IMAP intake can use SINCE
-- instead of UNSEEN, capturing replies that a human read before the cron fired.
-- Each (job_id, workspace_id, account_email) triple gets one row.

CREATE TABLE IF NOT EXISTS scheduler_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          TEXT NOT NULL,
    workspace_id    UUID NOT NULL,
    account_email   TEXT NOT NULL DEFAULT '',
    last_run_at     TIMESTAMPTZ NOT NULL DEFAULT (now() - INTERVAL '48 hours'),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, workspace_id, account_email)
);

CREATE INDEX IF NOT EXISTS idx_scheduler_state_lookup
    ON scheduler_state (job_id, workspace_id, account_email);

-- RLS: service role only (same pattern as other internal tables)
ALTER TABLE scheduler_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY scheduler_state_service_only ON scheduler_state
    USING (auth.role() = 'service_role');
