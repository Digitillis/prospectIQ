-- Migration 052: Policy Snapshots + Context Packets
--
-- Two tables that underpin the context intelligence layer:
--
--   policy_snapshots — immutable, append-only record of what the send-limit
--     policy looked like at any given moment. Every decision that consults
--     limits.yaml or outreach_send_config references a snapshot_id so the
--     exact rules that governed it can be reconstructed later.
--
--   context_packets — point-in-time snapshot of everything the system knew
--     about a contact, company, and their outreach history at decision time.
--     Assembled by ContextPacketBuilder before draft generation, approval,
--     or send (shadow mode until PR F wires the send path).
--
-- Notable differences from the PR #99 draft:
--
--   context_packets.workspace_id is NULLABLE (not UUID NOT NULL).
--   Provider webhooks and early-lifecycle calls may not yet have a reliable
--   workspace_id. A NULL workspace_id is visible in logs (WARNING) and safe
--   to query against — the RLS policy allows service-role access to NULL rows.
--
--   No context_packet_id FK column on workflow_events in this migration.
--   That column will be added via ALTER TABLE in a later migration once
--   the two tables are confirmed stable, avoiding the dual-column confusion
--   in the PR #99 draft (which had both a non-FK context_packet_id UUID and
--   a FK context_packet_id_fk UUID on workflow_events).
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

-- ============================================================
-- 1. POLICY SNAPSHOTS
-- ============================================================

CREATE TABLE IF NOT EXISTS policy_snapshots (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL,

    -- Monotonically increasing within a workspace — used for "latest policy" queries
    version         INTEGER     NOT NULL DEFAULT 1,

    -- Which sources contributed to this snapshot
    -- values: limits_yaml | db_config | env
    sources         TEXT[]      NOT NULL DEFAULT '{}',

    -- Full policy payload at capture time (limits, caps, cooldowns, flags)
    payload         JSONB       NOT NULL DEFAULT '{}',

    -- Optional note when policy was deliberately changed
    change_reason   TEXT,
    changed_by      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Immutable — policy captures are permanent records
CREATE OR REPLACE RULE policy_snapshots_no_update AS
    ON UPDATE TO policy_snapshots DO INSTEAD NOTHING;

CREATE OR REPLACE RULE policy_snapshots_no_delete AS
    ON DELETE TO policy_snapshots DO INSTEAD NOTHING;

-- "What is the current policy version?" — used by PR F to find the latest snapshot
CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_snapshots_version
    ON policy_snapshots (workspace_id, version);

CREATE INDEX IF NOT EXISTS idx_policy_snapshots_latest
    ON policy_snapshots (workspace_id, created_at DESC);

ALTER TABLE policy_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON policy_snapshots
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 2. CONTEXT PACKETS
-- ============================================================

CREATE TABLE IF NOT EXISTS context_packets (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- NULLABLE: see design note above. A NULL workspace_id means the packet
    -- was assembled before workspace context was resolved. ContextPacketBuilder
    -- logs a WARNING when this happens.
    workspace_id            UUID,

    -- What this packet was assembled for
    purpose                 TEXT        NOT NULL,  -- draft_generation | approval | send | risk_score
    draft_id                UUID        REFERENCES outreach_drafts(id) ON DELETE SET NULL,
    contact_id              UUID,
    company_id              UUID,

    -- Schema version — increment when ContextPacketBuilder adds/removes fields
    schema_version          INTEGER     NOT NULL DEFAULT 1,

    -- Content hash — SHA-256 of the decision-relevant fields, for staleness detection
    content_hash            TEXT        NOT NULL,

    -- ---- Contact snapshot ----
    contact_snapshot        JSONB       NOT NULL DEFAULT '{}',
    -- keys: full_name, email, linkedin_url, seniority, title, department,
    --       reply_sentiment, linkedin_status, has_email, has_linkedin

    -- ---- Company snapshot ----
    company_snapshot        JSONB       NOT NULL DEFAULT '{}',
    -- keys: name, domain, employee_count, headcount_growth_6m, industry,
    --       tier, status, intent_score, assigned_persona

    -- ---- Outreach history ----
    prior_messages          JSONB       NOT NULL DEFAULT '[]',
    -- [{step, channel, subject, sent_at, primary_angle}]

    sibling_contact_history JSONB       NOT NULL DEFAULT '[]',
    -- other contacts at this company who received outreach (prevents duplicate angles)

    reply_history           JSONB       NOT NULL DEFAULT '[]',
    -- [{contact_id, sentiment, replied_at, body_excerpt}]

    active_conversation     BOOLEAN     NOT NULL DEFAULT false,

    -- ---- Governance context ----
    channel_assignment      TEXT,       -- email | linkedin | both | none
    channel_reason          TEXT,
    company_locked          BOOLEAN     NOT NULL DEFAULT false,
    company_lock_reason     TEXT,
    suppression_status      TEXT,       -- none | contact | company | domain | global
    suppression_reason      TEXT,

    -- ---- Content guardrails ----
    prohibited_claims       TEXT[]      NOT NULL DEFAULT '{}',
    registered_claims       JSONB       NOT NULL DEFAULT '[]',
    -- [{claim_id, claim_text, source, verified_at}]

    -- ---- Sequence context ----
    sequence_name           TEXT,
    sequence_step           INTEGER,
    prior_step_angle        TEXT,

    -- ---- Risk indicators (pre-score) ----
    traction_signal         TEXT,       -- none | warm | active_reply | meeting_booked
    is_first_touch          BOOLEAN     NOT NULL DEFAULT true,
    days_since_last_touch   INTEGER,

    -- ---- Meta ----
    assembled_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_seconds             INTEGER     NOT NULL DEFAULT 300,
    expired_at              TIMESTAMPTZ,  -- assembled_at + ttl_seconds; set by application on insert

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- Indexes ----

CREATE INDEX IF NOT EXISTS idx_context_packets_draft
    ON context_packets (draft_id)
    WHERE draft_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_context_packets_contact_recent
    ON context_packets (contact_id, assembled_at DESC)
    WHERE contact_id IS NOT NULL;

-- Partial index — skip unresolved-workspace rows for workspace-scoped queries
CREATE INDEX IF NOT EXISTS idx_context_packets_workspace
    ON context_packets (workspace_id, assembled_at DESC)
    WHERE workspace_id IS NOT NULL;

-- ---- RLS ----

ALTER TABLE context_packets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON context_packets
    FOR ALL
    USING (
        workspace_id IS NULL
        OR workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );
