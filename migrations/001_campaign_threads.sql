-- Campaign Thread System
-- Phase 1: Thread model for adaptive outreach with response handling
-- Apply via Supabase SQL editor or psql

-- Thread table: one conversation per contact
CREATE TABLE IF NOT EXISTS campaign_threads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id      UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    sequence_name   TEXT NOT NULL DEFAULT 'email_value_first',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'closed', 'converted', 'unsubscribed', 'bounced')),
    current_step    INTEGER NOT NULL DEFAULT 1,
    next_step       INTEGER,                          -- NULL = sequence complete
    paused_reason   TEXT,                             -- 'reply_received', 'manual'
    last_sent_at    TIMESTAMPTZ,
    last_replied_at TIMESTAMPTZ,
    instantly_campaign_id TEXT,                       -- for Phase 3 sequencer ownership
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- All messages in a thread (both outbound and inbound)
CREATE TABLE IF NOT EXISTS thread_messages (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id                   UUID NOT NULL REFERENCES campaign_threads(id) ON DELETE CASCADE,
    direction                   TEXT NOT NULL CHECK (direction IN ('outbound', 'inbound')),
    subject                     TEXT,
    body                        TEXT NOT NULL,
    sent_at                     TIMESTAMPTZ NOT NULL,
    outreach_draft_id           UUID REFERENCES outreach_drafts(id),  -- for outbound only
    -- Classification fields (for inbound messages)
    classification              TEXT CHECK (classification IN (
                                    'interested', 'objection', 'referral',
                                    'soft_no', 'out_of_office', 'unsubscribe', 'bounce', 'other'
                                )),
    classification_confidence   FLOAT CHECK (classification_confidence BETWEEN 0 AND 1),
    classification_reasoning    TEXT,
    classification_confirmed_by TEXT,               -- 'user' or 'auto'
    -- Webhook fields (for Phase 2)
    source                      TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'instantly_webhook', 'gmail_webhook')),
    raw_webhook_payload         JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_campaign_threads_company  ON campaign_threads(company_id);
CREATE INDEX IF NOT EXISTS idx_campaign_threads_contact  ON campaign_threads(contact_id);
CREATE INDEX IF NOT EXISTS idx_campaign_threads_status   ON campaign_threads(status);
CREATE INDEX IF NOT EXISTS idx_thread_messages_thread    ON thread_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_thread_messages_direction ON thread_messages(direction);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_campaign_threads_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_campaign_threads_updated_at ON campaign_threads;
CREATE TRIGGER trg_campaign_threads_updated_at
    BEFORE UPDATE ON campaign_threads
    FOR EACH ROW EXECUTE FUNCTION update_campaign_threads_updated_at();
