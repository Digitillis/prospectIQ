-- 060_send_schedule.sql
-- Forward send schedule: every pending outreach draft is pre-slotted with a
-- scheduled_date, sender mailbox, and intra-day slot order. Dispatch becomes
-- "enqueue today's slice" instead of just-in-time selection. Rebuildable and
-- idempotent: recompute wipes only future/unsent rows and rebuilds from live state.

CREATE TABLE IF NOT EXISTS send_schedule (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id        UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE CASCADE,
    contact_id      UUID NOT NULL,
    company_id      UUID NOT NULL,
    workspace_id    UUID NOT NULL,
    sequence_step   INT  NOT NULL,
    scheduled_date  DATE NOT NULL,
    sender_email    TEXT NOT NULL,
    slot_order      INT  NOT NULL,
    -- scheduled | enqueued | sent | cancelled | paused
    status          TEXT NOT NULL DEFAULT 'scheduled',
    schedule_run_id UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- one live schedule row per draft
    UNIQUE (draft_id)
);

CREATE INDEX IF NOT EXISTS idx_send_schedule_date_status
    ON send_schedule (scheduled_date, status);
CREATE INDEX IF NOT EXISTS idx_send_schedule_contact
    ON send_schedule (contact_id);
CREATE INDEX IF NOT EXISTS idx_send_schedule_run
    ON send_schedule (schedule_run_id);

-- RLS: service role only (same pattern as scheduler_state / other internal tables)
ALTER TABLE send_schedule ENABLE ROW LEVEL SECURITY;
CREATE POLICY send_schedule_service_only ON send_schedule
    USING (auth.role() = 'service_role');
