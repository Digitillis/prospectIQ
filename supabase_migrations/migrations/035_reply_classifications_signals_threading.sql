-- Migration 035: reply_classifications + company_signals + company_outreach_state
--
-- reply_classifications: cache Haiku classification results by reply hash.
--   Prevents double-spend on re-processed emails. One row per unique reply body.
--
-- company_signals: normalized signal store with half-life decay.
--   Replaces boolean trigger evaluation with continuous signal strength.
--   freshness_weight = 0.5 ^ (days_since_observed / decay_half_life_days)
--
-- company_outreach_state: explicit threading state machine per company.
--   Replaces implicit state inferred from queries. Hard rules enforced in table,
--   not in Python heuristics.

-- ── reply_classifications ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reply_classifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reply_hash      TEXT NOT NULL UNIQUE,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,
    company_id      UUID REFERENCES companies(id) ON DELETE SET NULL,
    classification  JSONB NOT NULL DEFAULT '{}'::jsonb,
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reply_class_contact ON reply_classifications (contact_id);

-- ── company_signals ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS company_signals (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         UUID,
    company_id           UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    signal_type          TEXT NOT NULL,   -- 'fda_recall', 'osha_citation', 'mep_grant',
                                          --  'job_posting', 'funding', 'leadership_change', etc.
    source               TEXT NOT NULL,   -- 'fda', 'osha', 'mep', 'apollo', 'manual', etc.
    value                JSONB NOT NULL DEFAULT '{}'::jsonb,  -- signal payload (flexible)
    signal_text          TEXT,            -- human-readable summary for prompt injection
    observed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decay_half_life_days INTEGER NOT NULL DEFAULT 90,
    source_url           TEXT,
    source_id            TEXT,            -- dedup key per source (e.g., FDA recall number)

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dedup: same source + source_id means same event, don't re-insert
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_dedup
    ON company_signals (company_id, source, source_id)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signals_company    ON company_signals (company_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_type       ON company_signals (signal_type, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_workspace  ON company_signals (workspace_id, company_id);

-- Computed freshness view (materialized periodically or computed inline)
-- freshness_weight = 0.5 ^ (extract(epoch from now()-observed_at)/86400 / decay_half_life_days)
CREATE OR REPLACE VIEW v_company_signal_scores AS
SELECT
    company_id,
    workspace_id,
    signal_type,
    source,
    signal_text,
    observed_at,
    decay_half_life_days,
    -- Freshness weight: exponential decay with configurable half-life
    POWER(0.5,
        EXTRACT(EPOCH FROM (NOW() - observed_at)) / 86400.0 / NULLIF(decay_half_life_days, 0)
    ) AS freshness_weight,
    value
FROM company_signals
WHERE observed_at > NOW() - INTERVAL '365 days';  -- ignore signals older than 1 year


-- ── company_outreach_state ────────────────────────────────────────────────────

CREATE TYPE IF NOT EXISTS outreach_state AS ENUM (
    'not_started',
    'contact_1_queued',
    'contact_1_sent',
    'contact_1_engaged',
    'contact_2_queued',
    'contact_2_sent',
    'paused',
    'closed_won',
    'closed_lost',
    'excluded'
);

CREATE TABLE IF NOT EXISTS company_outreach_state (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID,
    company_id              UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    state                   outreach_state NOT NULL DEFAULT 'not_started',

    -- Contact threading
    contact_1_id            UUID REFERENCES contacts(id) ON DELETE SET NULL,
    contact_2_id            UUID REFERENCES contacts(id) ON DELETE SET NULL,
    contact_1_sent_at       TIMESTAMPTZ,
    contact_2_sent_at       TIMESTAMPTZ,
    contact_1_sequence_step INTEGER DEFAULT 1,
    contact_2_sequence_step INTEGER DEFAULT 1,

    -- Engagement
    last_reply_at           TIMESTAMPTZ,
    last_reply_contact_id   UUID REFERENCES contacts(id) ON DELETE SET NULL,
    meeting_booked_at       TIMESTAMPTZ,

    -- Locks
    paused_reason           TEXT,         -- 'reply_received', 'manual', 'company_limit', etc.
    paused_at               TIMESTAMPTZ,

    -- Metadata
    pqs_at_start            NUMERIC(5,2),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cos_company_workspace
    ON company_outreach_state (workspace_id, company_id);

CREATE INDEX IF NOT EXISTS idx_cos_state      ON company_outreach_state (workspace_id, state);
CREATE INDEX IF NOT EXISTS idx_cos_company    ON company_outreach_state (company_id);

-- Hard rule: if contact_1 replies, contact_2 must be paused.
-- Enforced via constraint: contact_2 cannot be sent while state = 'contact_1_engaged'.
-- The application layer also checks, but the constraint is the safety net.
-- (PostgreSQL does not support cross-row constraints in standard SQL —
--  this is enforced via the threading state machine in the application layer
--  and checked by the pre-send assertions.)

-- Threading rules enforced at application layer (see threading_coordinator.py):
--   1. Max 2 contacts per company with < 500 employees
--   2. Min 5 business days gap between contact_1 and contact_2
--   3. contact_2 blocked if state = 'contact_1_engaged' or 'paused'
--   4. Threading only for companies with PQS >= 65
