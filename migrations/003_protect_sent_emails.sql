-- Migration 003: Protect sent outreach emails from deletion
-- Sent emails are the permanent interaction record. Once sent_at is set,
-- the row is immutable (no DELETE allowed). Apply via Supabase SQL editor.

-- Trigger function: raise an error if anyone tries to delete a sent draft
CREATE OR REPLACE FUNCTION prevent_sent_draft_deletion()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.sent_at IS NOT NULL THEN
        RAISE EXCEPTION
            'Cannot delete sent outreach draft (id: %). Sent emails are the permanent interaction record.',
            OLD.id;
    END IF;
    RETURN OLD;  -- allow deletion of unsent drafts
END;
$$ LANGUAGE plpgsql;

-- Attach trigger to outreach_drafts
DROP TRIGGER IF EXISTS protect_sent_drafts_from_deletion ON outreach_drafts;
CREATE TRIGGER protect_sent_drafts_from_deletion
    BEFORE DELETE ON outreach_drafts
    FOR EACH ROW EXECUTE FUNCTION prevent_sent_draft_deletion();

-- Index to make sent email queries fast
CREATE INDEX IF NOT EXISTS idx_outreach_drafts_sent_at
    ON outreach_drafts(sent_at DESC)
    WHERE sent_at IS NOT NULL;
