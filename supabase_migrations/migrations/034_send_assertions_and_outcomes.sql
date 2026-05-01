-- Migration 034: send_assertions + outreach_outcomes
--
-- send_assertions: audit log of every pre-send invariant evaluation.
--   Every assertion that runs (pass or fail) writes a row here. This is the
--   test-in-production safety net — when something goes wrong, we can answer
--   "which gate failed and when?"
--
-- outreach_outcomes: single source of truth for all send results.
--   Populated at send time with static context (PQS, ICP version, signals).
--   Reply classification, meeting, and deal data fill in as events arrive.
--   Nothing adaptive can be built without this table.

-- ── send_assertions ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS send_assertions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id   UUID REFERENCES contacts(id) ON DELETE SET NULL,
    company_id   UUID REFERENCES companies(id) ON DELETE SET NULL,
    assertion    TEXT NOT NULL,
    passed       BOOLEAN NOT NULL,
    detail       TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assertions_contact  ON send_assertions (contact_id, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_assertions_failed   ON send_assertions (passed, evaluated_at DESC) WHERE passed = FALSE;

-- ── outreach_outcomes ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS outreach_outcomes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    send_id             UUID REFERENCES outreach_drafts(id) ON DELETE SET NULL,
    contact_id          UUID REFERENCES contacts(id) ON DELETE SET NULL,
    company_id          UUID REFERENCES companies(id) ON DELETE SET NULL,
    workspace_id        UUID,

    -- Context at send time (immutable after creation)
    icp_version_id      UUID,               -- which ICP definition was active
    persona             TEXT,               -- contact_tier at send time
    sequence_step       INTEGER,
    pqs_at_send         NUMERIC(5,2),       -- prospect quality score
    ccs_at_send         NUMERIC(5,2),       -- contact confidence score
    signals_at_send     JSONB DEFAULT '{}'::jsonb,  -- company signals active at send
    sender_email        TEXT,

    -- Engagement events (fill in from webhooks)
    sent_at             TIMESTAMPTZ,
    opened_at           TIMESTAMPTZ,
    clicked_at          TIMESTAMPTZ,
    replied_at          TIMESTAMPTZ,

    -- Reply classification (filled by reply_classifier agent)
    reply_sentiment     TEXT CHECK (reply_sentiment IN ('positive', 'neutral', 'negative')),
    reply_classification TEXT CHECK (reply_classification IN (
                            'interested', 'not_interested', 'wrong_person',
                            'unsubscribe', 'meeting_request', 'auto_reply', 'other')),
    reply_key_objection TEXT,
    wrong_person_flag   BOOLEAN DEFAULT FALSE,
    raw_reply_snippet   TEXT,

    -- Downstream conversion
    meeting_booked_at   TIMESTAMPTZ,
    deal_stage          TEXT,
    deal_value          NUMERIC(12,2),
    closed_at           TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outcomes_workspace  ON outreach_outcomes (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_contact    ON outreach_outcomes (contact_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_company    ON outreach_outcomes (company_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_send       ON outreach_outcomes (send_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_replied    ON outreach_outcomes (replied_at) WHERE replied_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_outcomes_wrong_person ON outreach_outcomes (wrong_person_flag) WHERE wrong_person_flag = TRUE;

-- icp_definitions table (for P2.1 ICP versioning — used by outreach_outcomes FK)
CREATE TABLE IF NOT EXISTS icp_definitions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID,
    version      INTEGER NOT NULL DEFAULT 1,
    label        TEXT,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    activated_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_icp_active_workspace
    ON icp_definitions (workspace_id) WHERE is_active = TRUE;

-- Now add FK constraint on outreach_outcomes.icp_version_id
ALTER TABLE outreach_outcomes
    ADD CONSTRAINT fk_outcomes_icp
    FOREIGN KEY (icp_version_id) REFERENCES icp_definitions(id) ON DELETE SET NULL
    NOT VALID;

-- icp_exclusions table (P2.3 — companies that should never re-enter the pipeline)
CREATE TABLE IF NOT EXISTS icp_exclusions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID,
    company_id   UUID REFERENCES companies(id) ON DELETE CASCADE,
    domain       TEXT,
    reason       TEXT CHECK (reason IN (
                    'hard_bounce', 'wrong_person_reply', 'not_a_fit',
                    'competitor', 'existing_customer', 'manual')),
    detail       TEXT,
    excluded_by  TEXT,     -- 'system' or user email
    excluded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_icp_exclusions_company
    ON icp_exclusions (workspace_id, company_id);
CREATE INDEX IF NOT EXISTS idx_icp_exclusions_domain
    ON icp_exclusions (workspace_id, domain);
