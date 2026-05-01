-- Migration 036: title_classifications + title_review_queue + raw_contacts + CCS

-- ── title_classifications (Haiku result cache + human overrides) ──────────────

CREATE TABLE IF NOT EXISTS title_classifications (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key    TEXT NOT NULL UNIQUE,  -- SHA256(normalized_title|industry)[:32]
    title        TEXT NOT NULL,
    industry     TEXT NOT NULL DEFAULT '',
    tier         TEXT NOT NULL CHECK (tier IN ('target', 'borderline', 'excluded')),
    confidence   NUMERIC(4,3) NOT NULL DEFAULT 0.5,
    reasoning    TEXT,
    source       TEXT NOT NULL DEFAULT 'haiku' CHECK (source IN ('haiku', 'human', 'deterministic')),
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_title_class_key ON title_classifications (cache_key);

-- ── title_review_queue (Pass 3 — low-confidence outputs pending human review) ─

CREATE TABLE IF NOT EXISTS title_review_queue (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title            TEXT NOT NULL,
    industry         TEXT NOT NULL DEFAULT '',
    haiku_tier       TEXT,
    haiku_confidence NUMERIC(4,3),
    haiku_reasoning  TEXT,
    status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'reviewed', 'skipped')),
    human_tier       TEXT CHECK (human_tier IN ('target', 'borderline', 'excluded')),
    reviewed_by      TEXT,
    reviewed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON title_review_queue (status, created_at DESC);

-- ── raw_contacts (append-only, source-tagged system of record) ────────────────

CREATE TABLE IF NOT EXISTS raw_contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID,
    source          TEXT NOT NULL CHECK (source IN ('apollo', 'linkedin', 'zoominfo', 'manual', 'clearbit', 'import')),
    source_record_id TEXT,              -- Apollo person_id, LinkedIn URL, etc.
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- raw data from source, immutable
    resolved_contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,  -- links to contacts table after resolution
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_contacts_dedup
    ON raw_contacts (workspace_id, source, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_contacts_resolved ON raw_contacts (resolved_contact_id);
CREATE INDEX IF NOT EXISTS idx_raw_contacts_workspace ON raw_contacts (workspace_id, fetched_at DESC);

-- ── Contact Confidence Score (CCS) column on contacts ────────────────────────
-- Numeric 0-100 score replacing binary is_outreach_eligible as the ranking signal.
-- Gates still use is_outreach_eligible (threshold = CCS >= 70).
-- CCS is recomputed whenever gate-relevant fields change.

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ccs_score NUMERIC(5,2) DEFAULT NULL;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ccs_computed_at TIMESTAMPTZ DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_ccs ON contacts (workspace_id, ccs_score DESC NULLS LAST)
    WHERE is_outreach_eligible = TRUE;
