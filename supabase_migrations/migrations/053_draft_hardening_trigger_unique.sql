-- Migration 053: Draft Hardening — Immutability Trigger + Active Draft Unique Index
--
-- Two enforcement mechanisms that together prevent the multi-writer state-machine
-- anti-pattern: sent drafts whose content is silently overwritten, and multiple
-- active drafts racing for the same contact/sequence slot.
--
--   enforce_draft_immutability() / trg_draft_immutability
--     BEFORE UPDATE trigger that blocks changes to 'body' and 'subject' once
--     a draft has been sent (sent_at IS NOT NULL). All other columns — including
--     resend_message_id, resend_status, sent_at itself, opened_at, clicked_at,
--     bounced_at, complained_at, and approval_status — are freely updatable.
--     The trigger raises SQLSTATE P0001 with a message prefix of
--     'draft_immutability:' so Python exception handlers can convert it to
--     HTTP 409 without surfacing a 500.
--
--   idx_outreach_drafts_active_unique
--     Partial UNIQUE index on (workspace_id, contact_id, sequence_name,
--     sequence_step) WHERE approval_status::text != 'rejected'.
--     Prevents two non-rejected drafts from existing for the same slot.
--     Rejected drafts are excluded so a contact can be re-drafted after
--     rejection without violating the constraint.
--     NULLs in sequence_name or sequence_step are naturally distinct in
--     PostgreSQL UNIQUE indexes, so non-sequence one-off drafts are exempt.
--
-- IMPORTANT: Run docs/preflight_053.sql BEFORE applying this migration to
-- staging or production. The preflight detects pre-existing duplicate active
-- drafts that would cause the UNIQUE index creation to fail with:
--     ERROR: could not create unique index "idx_outreach_drafts_active_unique"
-- The dedupe block in the preflight resolves duplicates by rejecting all but
-- the newest draft in each group. Re-run the verification query after deduping
-- to confirm zero rows before proceeding.
--
-- No production backfill is included in this migration.
-- No changes to the send path.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

-- ============================================================
-- 1. IMMUTABILITY TRIGGER FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION enforce_draft_immutability()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Content fields that were transmitted are permanent once sent.
    -- resend_message_id, resend_status, sent_at, opened_at, clicked_at,
    -- bounced_at, complained_at, approval_status, etc. remain writable.
    IF OLD.sent_at IS NOT NULL THEN
        IF NEW.body IS DISTINCT FROM OLD.body THEN
            RAISE EXCEPTION 'draft_immutability: cannot modify body of sent draft (id=%)', OLD.id
                USING ERRCODE = 'P0001';
        END IF;
        IF NEW.subject IS DISTINCT FROM OLD.subject THEN
            RAISE EXCEPTION 'draft_immutability: cannot modify subject of sent draft (id=%)', OLD.id
                USING ERRCODE = 'P0001';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- ============================================================
-- 2. ATTACH TRIGGER TO outreach_drafts
-- ============================================================

DROP TRIGGER IF EXISTS trg_draft_immutability ON outreach_drafts;

CREATE TRIGGER trg_draft_immutability
    BEFORE UPDATE ON outreach_drafts
    FOR EACH ROW
    EXECUTE FUNCTION enforce_draft_immutability();

-- ============================================================
-- 3. UNIQUE INDEX — ONE ACTIVE DRAFT PER SLOT
--
-- Run docs/preflight_053.sql first. Creating this index fails
-- if duplicate active drafts exist in the table.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_drafts_active_unique
    ON outreach_drafts (workspace_id, contact_id, sequence_name, sequence_step)
    WHERE approval_status::text != 'rejected';
