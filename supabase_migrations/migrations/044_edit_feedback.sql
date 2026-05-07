-- Store structured edit feedback when a human edits a draft before approving.
-- The outreach agent reads this to learn what the reviewer changed and why.
CREATE TABLE IF NOT EXISTS outreach_edit_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id        UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE CASCADE,
    company_id      UUID NOT NULL,
    contact_id      UUID,
    sequence_name   TEXT,
    sequence_step   INT,
    original_body   TEXT,
    edited_body     TEXT,
    -- Computed diff metrics
    original_word_count  INT,
    edited_word_count    INT,
    opener_changed       BOOLEAN DEFAULT FALSE,
    proof_point_removed  BOOLEAN DEFAULT FALSE,
    shortened            BOOLEAN DEFAULT FALSE,
    -- Model that generated the original draft
    original_model  TEXT,
    workspace_id    UUID,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edit_feedback_contact
    ON outreach_edit_feedback (contact_id, sequence_name);

CREATE INDEX IF NOT EXISTS idx_edit_feedback_company
    ON outreach_edit_feedback (company_id, sequence_name);
