-- ProspectIQ Migration 011: Company-Level Intent Signals Table
-- Stores structured buying intent signals per company (job postings, FDA letters,
-- OSHA citations, funding events, LinkedIn activity).
--
-- Distinct from the contacts.intent_signals JSONB column added in 010
-- (which stores per-contact signals). This table stores company-wide signals
-- with full lifecycle management (active/expired, deduplication, source tracking).
--
-- All statements are idempotent (IF NOT EXISTS guards throughout).

-- ============================================================
-- 1. company_intent_signals — structured per-company signals
-- ============================================================

CREATE TABLE IF NOT EXISTS company_intent_signals (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id     UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    signal_type    TEXT NOT NULL,    -- job_posting | fda_warning_letter | osha_citation | funding_event | linkedin_activity
    signal_detail  TEXT,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source         TEXT,            -- apollo | fda_api | osha_api | manual
    raw_data       JSONB NOT NULL DEFAULT '{}',
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at     TIMESTAMPTZ,     -- NULL = never expires
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_company_intent_signals_company
    ON company_intent_signals (company_id, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_company_intent_signals_type
    ON company_intent_signals (signal_type, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_company_intent_signals_active
    ON company_intent_signals (is_active, detected_at DESC)
    WHERE is_active = TRUE;

-- ============================================================
-- 2. companies — intent score cache columns
-- ============================================================

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS intent_score INTEGER NOT NULL DEFAULT 0;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS intent_score_updated_at TIMESTAMPTZ;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS last_intent_signal_at TIMESTAMPTZ;

-- Index for hot-company queries (intent_score >= 20)
CREATE INDEX IF NOT EXISTS idx_companies_intent_score
    ON companies (intent_score DESC)
    WHERE intent_score > 0;
