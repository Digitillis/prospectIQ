-- Migration 047: add assertion_context to send_assertions
--
-- Adds a column that distinguishes draft-generation assertions (advisory,
-- run in outreach.py before draft creation) from send-path assertions
-- (authoritative runtime governance, run in engagement.py before delivery).
--
-- Without this column the two contexts write identical rows and are
-- indistinguishable in post-incident queries. Draft-gen assertions tell us
-- what the contact state was at generation time. Send-path assertions tell
-- us what was verified at the moment of delivery. These are different facts.
--
-- DEFAULT 'draft_gen' preserves full backward compatibility with all
-- existing rows — no backfill required.
--
-- Reversible: DROP COLUMN assertion_context;

ALTER TABLE send_assertions
    ADD COLUMN IF NOT EXISTS assertion_context TEXT NOT NULL DEFAULT 'draft_gen';

CREATE INDEX IF NOT EXISTS idx_assertions_context
    ON send_assertions (assertion_context, evaluated_at DESC);
