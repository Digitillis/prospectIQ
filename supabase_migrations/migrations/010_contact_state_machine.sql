-- ProspectIQ Migration 010: Contact State Machine
-- Adds outreach state tracking, Instantly integration fields, intent signals,
-- company-level outreach flags, and the state transition audit log.
-- All statements are idempotent (IF NOT EXISTS / IF EXISTS guards throughout).

-- ============================================================
-- 1. contacts — outreach state machine columns
-- ============================================================

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS outreach_state TEXT NOT NULL DEFAULT 'enriched';

-- Allowed values (enforced at application layer, documented here):
--   discovered, enriched, sequenced,
--   touch_1_sent, touch_2_sent, touch_3_sent, touch_4_sent, touch_5_sent,
--   replied, demo_scheduled, closed_won, closed_lost,
--   nurture, not_qualified, dnc

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS outreach_state_updated_at TIMESTAMPTZ;

-- Instantly.ai integration
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS instantly_sequence_id TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS instantly_lead_id TEXT;

-- Reply sentiment (positive | neutral | negative)
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS reply_sentiment TEXT;

-- Demo booking
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS demo_scheduled_at TIMESTAMPTZ;

-- LinkedIn touch timestamps
-- Note: linkedin_connection_sent_at already exists from migration 009.
-- We add the ones that don't exist yet.
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS linkedin_connected_at TIMESTAMPTZ;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS linkedin_message_sent_at TIMESTAMPTZ;

-- Phone touch timestamp
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS phone_called_at TIMESTAMPTZ;

-- Last touch metadata
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS last_touch_channel TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS last_touch_at TIMESTAMPTZ;

-- Email engagement counters
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS open_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS click_count INTEGER NOT NULL DEFAULT 0;

-- Intent scoring
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS intent_score INTEGER NOT NULL DEFAULT 0;

-- Array of {type, detected_at, detail} intent signal objects
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS intent_signals JSONB NOT NULL DEFAULT '[]'::jsonb;

-- ============================================================
-- 2. companies — outreach activity columns
-- ============================================================

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS outreach_active BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS primary_contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS outreach_started_at TIMESTAMPTZ;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS outreach_last_touch_at TIMESTAMPTZ;

-- ============================================================
-- 3. outreach_state_log — immutable state transition audit log
-- ============================================================

CREATE TABLE IF NOT EXISTS outreach_state_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id       UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    from_state       TEXT,
    to_state         TEXT NOT NULL,
    channel          TEXT,          -- email | linkedin | phone | system
    instantly_event  TEXT,          -- raw Instantly event_type that triggered this
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_state_log_contact
    ON outreach_state_log (contact_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_outreach_state_log_to_state
    ON outreach_state_log (to_state, created_at DESC);

-- ============================================================
-- 4. Indexes on new contacts columns
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_contacts_outreach_state
    ON contacts (outreach_state);

CREATE INDEX IF NOT EXISTS idx_contacts_instantly_lead
    ON contacts (instantly_lead_id)
    WHERE instantly_lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_intent_score
    ON contacts (intent_score DESC)
    WHERE intent_score > 0;
