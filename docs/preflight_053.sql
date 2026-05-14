-- preflight_053.sql
-- Run before applying migration 053 (draft_hardening_trigger_unique).
--
-- Migration 053 creates a UNIQUE index on
--   (workspace_id, contact_id, sequence_name, sequence_step)
--   WHERE approval_status::text != 'rejected'
--
-- If any duplicate active drafts exist for the same slot, the index creation
-- will fail with:
--   ERROR: could not create unique index "idx_outreach_drafts_active_unique"
--
-- Run Step 1 first. If it returns rows, run Step 2 (dedupe). Then re-run
-- Step 3 (verify) — it must return zero rows before applying migration 053.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

-- ============================================================
-- STEP 1: PREFLIGHT CHECK
--
-- Returns one row per duplicate group. Migration 053 requires
-- zero rows here before it can be applied safely.
-- ============================================================

SELECT
    workspace_id,
    contact_id,
    sequence_name,
    sequence_step,
    count(*)                                          AS active_count,
    array_agg(id      ORDER BY created_at DESC)       AS draft_ids,
    array_agg(approval_status::text
                      ORDER BY created_at DESC)       AS statuses,
    array_agg(created_at ORDER BY created_at DESC)    AS created_ats
FROM  outreach_drafts
WHERE approval_status::text != 'rejected'
  AND sequence_name  IS NOT NULL
  AND sequence_step  IS NOT NULL
GROUP BY workspace_id, contact_id, sequence_name, sequence_step
HAVING count(*) > 1
ORDER BY active_count DESC, workspace_id, contact_id;

-- ============================================================
-- STEP 2: DEDUPE (run only if Step 1 returns rows)
--
-- Rejects all but the newest active draft in each duplicate group.
-- "Newest" = highest created_at; ties broken by higher UUID (arbitrary
-- but stable within a run). The rejected drafts are marked with a
-- rejection_reason so they are auditable.
--
-- This is a reversible soft-reject — rows are not deleted.
-- Confirm with Avanish before running against production.
-- ============================================================

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY workspace_id, contact_id, sequence_name, sequence_step
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM  outreach_drafts
    WHERE approval_status::text != 'rejected'
      AND sequence_name  IS NOT NULL
      AND sequence_step  IS NOT NULL
),
duplicates AS (
    SELECT id FROM ranked WHERE rn > 1
)
UPDATE outreach_drafts
SET
    approval_status  = 'rejected',
    rejection_reason = 'preflight_053: superseded by newer active draft '
                       'for same (workspace, contact, sequence, step)'
WHERE id IN (SELECT id FROM duplicates)
RETURNING id, contact_id, sequence_name, sequence_step, created_at;

-- ============================================================
-- STEP 3: VERIFY
--
-- Re-run after Step 2. Must return zero rows before applying
-- migration 053. If rows are still present, investigate manually
-- before proceeding.
-- ============================================================

SELECT
    workspace_id,
    contact_id,
    sequence_name,
    sequence_step,
    count(*) AS active_count
FROM  outreach_drafts
WHERE approval_status::text != 'rejected'
  AND sequence_name  IS NOT NULL
  AND sequence_step  IS NOT NULL
GROUP BY workspace_id, contact_id, sequence_name, sequence_step
HAVING count(*) > 1;

-- Expected output: zero rows.
-- If any rows are returned, do NOT apply migration 053 until resolved.
