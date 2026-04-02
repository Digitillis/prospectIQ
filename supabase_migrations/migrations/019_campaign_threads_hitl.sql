-- Campaign Thread + HITL Queue System
-- Phase 2: Reply ingestion, thread management, and human-in-the-loop review
-- Migration: 019_campaign_threads_hitl.sql

-- ============================================================
-- campaign_threads
-- ============================================================
CREATE TABLE IF NOT EXISTS campaign_threads (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID,
    company_id              UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id              UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    sequence_name           TEXT NOT NULL DEFAULT 'email_value_first',
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'paused', 'replied', 'awaiting_review',
                                              'actioned', 'closed', 'converted',
                                              'unsubscribed', 'bounced')),
    current_step            INTEGER NOT NULL DEFAULT 1,
    next_step               INTEGER,
    paused_reason           TEXT,
    last_sent_at            TIMESTAMPTZ,
    last_replied_at         TIMESTAMPTZ,
    instantly_campaign_id   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- thread_messages
-- ============================================================
CREATE TABLE IF NOT EXISTS thread_messages (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id                   UUID NOT NULL REFERENCES campaign_threads(id) ON DELETE CASCADE,
    direction                   TEXT NOT NULL CHECK (direction IN ('outbound', 'inbound')),
    subject                     TEXT,
    body                        TEXT NOT NULL,
    sent_at                     TIMESTAMPTZ NOT NULL,
    outreach_draft_id           UUID REFERENCES outreach_drafts(id),
    -- Classification fields (inbound only)
    classification              TEXT CHECK (classification IN (
                                    'interested', 'objection', 'referral',
                                    'soft_no', 'out_of_office', 'unsubscribe', 'bounce', 'other'
                                )),
    classification_confidence   FLOAT CHECK (classification_confidence BETWEEN 0 AND 1),
    classification_reasoning    TEXT,
    classification_confirmed_by TEXT,
    -- Extracted intelligence
    extracted_entities          JSONB DEFAULT '{}',
    summary                     TEXT,
    next_action_suggestion      TEXT,
    -- HITL tracking
    reviewed_by                 UUID,
    hitl_notes                  TEXT,
    hitl_actioned_at            TIMESTAMPTZ,
    hitl_action                 TEXT CHECK (hitl_action IN (
                                    'continue_sequence', 'manual_reply', 'mark_converted',
                                    'unsubscribe', 'archive', 'snooze'
                                )),
    -- Webhook / source
    source                      TEXT DEFAULT 'manual' CHECK (source IN (
                                    'manual', 'instantly_webhook', 'gmail_webhook'
                                )),
    raw_webhook_payload         JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- hitl_queue
-- ============================================================
CREATE TABLE IF NOT EXISTS hitl_queue (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id                   UUID NOT NULL REFERENCES campaign_threads(id) ON DELETE CASCADE,
    message_id                  UUID REFERENCES thread_messages(id) ON DELETE SET NULL,
    workspace_id                UUID NOT NULL,
    classification              TEXT,
    classification_confidence   FLOAT,
    priority                    INT NOT NULL DEFAULT 5,
    status                      TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'reviewing', 'actioned', 'snoozed')),
    assigned_to                 UUID,
    snoozed_until               TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned_at                 TIMESTAMPTZ
);

-- ============================================================
-- Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_campaign_threads_ws_status   ON campaign_threads(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_campaign_threads_company      ON campaign_threads(company_id);
CREATE INDEX IF NOT EXISTS idx_campaign_threads_contact      ON campaign_threads(contact_id);
CREATE INDEX IF NOT EXISTS idx_campaign_threads_status       ON campaign_threads(status);

CREATE INDEX IF NOT EXISTS idx_thread_messages_thread        ON thread_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_thread_messages_direction     ON thread_messages(thread_id, direction);
CREATE INDEX IF NOT EXISTS idx_thread_messages_classification ON thread_messages(classification)
    WHERE classification IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hitl_queue_ws_status         ON hitl_queue(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_hitl_queue_thread             ON hitl_queue(thread_id);
CREATE INDEX IF NOT EXISTS idx_hitl_queue_priority_created   ON hitl_queue(priority ASC, created_at ASC)
    WHERE status = 'pending';

-- ============================================================
-- Updated_at trigger for campaign_threads
-- ============================================================
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
