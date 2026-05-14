-- Migration 051: Provider Events (idempotent webhook intake)
--
-- Stores one row per unique inbound webhook event from a delivery provider.
-- The UNIQUE index on (provider, provider_event_id) is the deduplication
-- fence: a duplicate event from Resend, Instantly, or any future provider
-- raises a unique-constraint violation before any business logic runs.
--
-- Design choices:
--
--   workspace_id is NULLABLE.
--   Provider webhooks may arrive before the workspace context can be reliably
--   resolved (e.g. if the resend_message_id lookup fails or the contact has
--   not yet been matched). Requiring a workspace_id here would force the
--   dedup layer to skip unresolvable events instead of recording them.
--
--   provider_event_id is a constructed key, not a raw provider field.
--   Resend does not mint a globally unique ID per event delivery; it reuses
--   email_id across all events for the same message. The caller must construct
--   a key that is unique per (message × event_type), e.g.:
--     "resend:{email_id}:{event_type}"
--
--   No UPDATE or DELETE on this table — rows are written once on intake.
--   Unlike workflow_events, this is NOT enforced via a PostgreSQL RULE
--   because idempotent re-intake (upsert) may be used in recovery scenarios.
--   The append-only property is a convention, not a DB rule.
--
-- Scope: this migration adds provider_events only.
--   context_packets, outbound_queue, send_attempts → later migrations.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

CREATE TABLE IF NOT EXISTS provider_events (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Nullable: webhook may arrive before workspace is resolved
    workspace_id        UUID,

    -- ---- Deduplication key ----
    -- provider:           'resend' | 'instantly' | 'unipile' (reserved for future)
    -- provider_event_id:  Caller-constructed unique key per event delivery.
    --                     For Resend one-shot events: "resend:{email_id}:{event_type}"
    provider            TEXT        NOT NULL,
    provider_event_id   TEXT        NOT NULL,

    -- ---- What happened ----
    event_type          TEXT        NOT NULL,  -- email_delivered | email_bounced | email_complained
    recipient_email     TEXT,

    -- Denormalized for fast joins — populated during intake
    contact_id          UUID,
    company_id          UUID,

    -- Full raw payload — never truncated
    raw_payload         JSONB       NOT NULL DEFAULT '{}',

    -- Processing lifecycle
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at        TIMESTAMPTZ,           -- set when processing completes
    processing_error    TEXT,                  -- non-null if processing failed

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- DEDUPLICATION CONSTRAINT
-- Any second INSERT with the same (provider, provider_event_id)
-- raises a unique-constraint violation (PostgreSQL error 23505).
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_events_dedup
    ON provider_events (provider, provider_event_id);

-- ============================================================
-- INDEXES
-- ============================================================

-- Contact-level timeline: "show me all delivery events for contact X"
CREATE INDEX IF NOT EXISTS idx_provider_events_contact
    ON provider_events (contact_id, received_at DESC)
    WHERE contact_id IS NOT NULL;

-- Workspace-level timeline (partial — skips unresolved events)
CREATE INDEX IF NOT EXISTS idx_provider_events_workspace
    ON provider_events (workspace_id, received_at DESC)
    WHERE workspace_id IS NOT NULL;

-- Ops: find unprocessed events
CREATE INDEX IF NOT EXISTS idx_provider_events_unprocessed
    ON provider_events (received_at ASC)
    WHERE processed_at IS NULL;

-- ============================================================
-- ROW LEVEL SECURITY
-- Applied only where workspace_id is resolved; unresolved rows
-- are visible to service-role queries only.
-- ============================================================

ALTER TABLE provider_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON provider_events
    FOR ALL
    USING (
        workspace_id IS NULL
        OR workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );
