-- Migration 041: Company deduplication + unique name constraint
--
-- Removes duplicate company records that share the same (workspace_id, lower(name)).
-- Keeps the highest-priority record per group (contacted > outreach_pending >
-- researched > qualified > discovered; tiebreak: highest pqs_total, then oldest).
-- Reassigns all child FK references to the winner before deleting losers.
-- Finally adds a unique index to prevent future duplicates from discovery runs.

SET statement_timeout = 0;

BEGIN;

-- ── Step 1: Identify the winner for each (workspace_id, lower(name)) group ──

CREATE TEMP TABLE _dedup_winners AS
SELECT DISTINCT ON (workspace_id, lower(name))
    id            AS winner_id,
    workspace_id,
    lower(name)   AS name_lower
FROM companies
WHERE name IS NOT NULL
ORDER BY
    workspace_id,
    lower(name),
    CASE status
        WHEN 'contacted'        THEN 1
        WHEN 'outreach_pending' THEN 2
        WHEN 'researched'       THEN 3
        WHEN 'qualified'        THEN 4
        WHEN 'discovered'       THEN 5
        ELSE 6
    END ASC,
    COALESCE(pqs_total, 0) DESC,
    created_at    ASC;

-- ── Step 2: Build loser → winner mapping ──

CREATE TEMP TABLE _dedup_map AS
SELECT c.id AS loser_id, w.winner_id
FROM companies c
JOIN _dedup_winners w
    ON  c.workspace_id = w.workspace_id
    AND lower(c.name)  = w.name_lower
    AND c.id          != w.winner_id;

DO $$
DECLARE cnt INT;
BEGIN
    SELECT COUNT(*) INTO cnt FROM _dedup_map;
    RAISE NOTICE 'company_dedup: % duplicate records identified for removal', cnt;
END $$;

-- ── Step 3: Reassign child records ──

-- contacts (CASCADE — must reassign before delete)
UPDATE contacts
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  contacts.company_id = m.loser_id;

-- outreach_drafts
UPDATE outreach_drafts
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  outreach_drafts.company_id = m.loser_id;

-- interactions
UPDATE interactions
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  interactions.company_id = m.loser_id;

-- engagement_sequences
UPDATE engagement_sequences
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  engagement_sequences.company_id = m.loser_id;

-- company_outreach_state has UNIQUE(workspace_id, company_id).
-- Delete ALL loser rows — the winner's row (if any) already has the active
-- threading state. Losers are duplicates and their state is stale.
DELETE FROM company_outreach_state
WHERE company_id IN (SELECT loser_id FROM _dedup_map);

-- company_intent_signals
UPDATE company_intent_signals
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  company_intent_signals.company_id = m.loser_id;

-- company_signals
UPDATE company_signals
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  company_signals.company_id = m.loser_id;

-- icp_exclusions
UPDATE icp_exclusions
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  icp_exclusions.company_id = m.loser_id;

-- outreach_pace_log
UPDATE outreach_pace_log
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  outreach_pace_log.company_id = m.loser_id;

-- api_costs (SET NULL on delete — reassign anyway to keep analytics accurate)
UPDATE api_costs
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  api_costs.company_id = m.loser_id;

-- learning_outcomes
UPDATE learning_outcomes
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  learning_outcomes.company_id = m.loser_id;

-- contact_events
UPDATE contact_events
SET    company_id = m.winner_id
FROM   _dedup_map m
WHERE  contact_events.company_id = m.loser_id;

-- research_intelligence has UNIQUE(company_id).
-- Delete ALL loser rows — multiple losers can map to the same winner, and a
-- second UPDATE would trip the unique constraint. The winner keeps its own
-- research row; any winner without one will be re-researched on next cycle.
DELETE FROM research_intelligence
WHERE company_id IN (SELECT loser_id FROM _dedup_map);

-- ── Step 4: Delete loser companies in batches ──
-- Batch deletes avoid statement_timeout on large sets. Any remaining CASCADE
-- children not explicitly reassigned above are removed automatically.

DO $$
DECLARE
    batch_ids UUID[];
    deleted   INT := 1;
    total     INT := 0;
BEGIN
    WHILE deleted > 0 LOOP
        SELECT ARRAY(SELECT loser_id FROM _dedup_map
                     WHERE loser_id IN (SELECT id FROM companies)
                     LIMIT 500)
        INTO batch_ids;

        DELETE FROM companies WHERE id = ANY(batch_ids);
        GET DIAGNOSTICS deleted = ROW_COUNT;
        total := total + deleted;
        IF deleted > 0 THEN
            RAISE NOTICE 'company_dedup: deleted % (total so far: %)', deleted, total;
        END IF;
    END LOOP;
    RAISE NOTICE 'company_dedup: done — % loser records removed', total;
END $$;

-- ── Step 5: Add unique index to prevent future duplicates ──
-- Partial index (WHERE name IS NOT NULL) avoids issues with placeholder rows.

CREATE UNIQUE INDEX IF NOT EXISTS companies_workspace_name_uq
    ON companies (workspace_id, lower(name))
    WHERE name IS NOT NULL;

-- ── Step 6: Fix unscoped apollo_id / domain lookups ──
-- Add indexes to support workspace-scoped lookups efficiently.
CREATE INDEX IF NOT EXISTS companies_workspace_apollo_id
    ON companies (workspace_id, apollo_id)
    WHERE apollo_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS companies_workspace_domain
    ON companies (workspace_id, domain)
    WHERE domain IS NOT NULL;

COMMIT;
