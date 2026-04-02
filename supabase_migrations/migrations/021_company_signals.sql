-- Migration 021: Company Signals (Signal Monitor / Trigger Engine)
-- Creates the company_signals table and supporting indexes.
-- Signals represent detected buying events: job postings, funding, tech changes,
-- news mentions, leadership changes, expansions, pain signals, regulatory events,
-- and partnerships.

CREATE TABLE IF NOT EXISTS company_signals (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id    UUID        REFERENCES companies(id) ON DELETE CASCADE,
    workspace_id  UUID        NOT NULL,
    signal_type   TEXT        NOT NULL,
    urgency       TEXT        NOT NULL DEFAULT 'background',
    title         TEXT        NOT NULL,
    description   TEXT,
    source_url    TEXT,
    source_name   TEXT        DEFAULT 'system',
    signal_score  FLOAT       DEFAULT 0.5,
    is_read       BOOLEAN     DEFAULT FALSE,
    is_actioned   BOOLEAN     DEFAULT FALSE,
    actioned_at   TIMESTAMPTZ,
    detected_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Primary query: list unactioned signals for a workspace, newest first
CREATE INDEX IF NOT EXISTS idx_signals_workspace
    ON company_signals(workspace_id, detected_at DESC);

-- Per-company signal lookup
CREATE INDEX IF NOT EXISTS idx_signals_company
    ON company_signals(company_id);

-- Urgency-filtered queries for immediate/near_term prioritization
CREATE INDEX IF NOT EXISTS idx_signals_urgency
    ON company_signals(workspace_id, urgency)
    WHERE is_actioned = FALSE;

-- Unread signal badge counts
CREATE INDEX IF NOT EXISTS idx_signals_unread
    ON company_signals(workspace_id, is_read)
    WHERE is_read = FALSE;

-- Track when each company was last signal-scanned so batch scan can
-- skip recently-scanned companies (add column to companies table)
ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS last_signal_scan_at TIMESTAMPTZ;
