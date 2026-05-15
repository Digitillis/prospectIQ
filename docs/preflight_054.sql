-- Preflight verification for migration 054 (outbound_queue + send_attempts)
-- Run BEFORE applying 054 to any environment.
--
-- Expected results on a clean database (no PR F rows yet):
--   outbound_queue does not exist  → table will be created by 054
--   send_attempts does not exist   → table will be created by 054
--   approve_draft_and_enqueue does not exist → function will be created by 054
--
-- Expected results AFTER applying 054:
--   outbound_queue exists, 0 rows
--   send_attempts exists, 0 rows
--   approve_draft_and_enqueue function exists

-- 1. Confirm tables do not exist before applying (run before migration)
SELECT
    CASE WHEN EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'outbound_queue'
    ) THEN 'EXISTS (migration may already be applied)'
    ELSE 'OK: outbound_queue not yet present'
    END AS outbound_queue_check;

SELECT
    CASE WHEN EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'send_attempts'
    ) THEN 'EXISTS (migration may already be applied)'
    ELSE 'OK: send_attempts not yet present'
    END AS send_attempts_check;

-- 2. After applying 054: verify tables and function exist
SELECT COUNT(*) AS outbound_queue_rows FROM outbound_queue;
SELECT COUNT(*) AS send_attempts_rows FROM send_attempts;

SELECT proname AS function_name
FROM pg_proc
WHERE proname = 'approve_draft_and_enqueue';

-- 3. Verify indexes exist
SELECT indexname
FROM pg_indexes
WHERE tablename IN ('outbound_queue', 'send_attempts')
ORDER BY tablename, indexname;

-- 4. Baseline: count existing approved drafts without queue rows
--    These predate PR F and will need manual handling before dispatch is enabled.
SELECT COUNT(*) AS pre_prf_approved_drafts_without_queue_row
FROM outreach_drafts d
WHERE d.approval_status IN ('approved', 'edited')
  AND d.sent_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM outbound_queue q WHERE q.draft_id = d.id
  );
