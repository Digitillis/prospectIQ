# ProspectIQ — Dark-Launch Stabilization Plan

**Document type**: Production operator runbook  
**Status**: ACTIVE — dark-launch phase in effect as of 2026-05-15  
**Author**: Avanish Mehrotra & Digitillis Architecture Team  
**Last updated**: 2026-05-15  
**Applies to**: Production environment (`wlyhbdmjhgvovigogdco`)

---

## Table of Contents

1. [Purpose of the Dark-Launch Phase](#1-purpose-of-the-dark-launch-phase)
2. [Current Production State Inventory](#2-current-production-state-inventory)
3. [Exact Production Rollout Sequencing](#3-exact-production-rollout-sequencing)
4. [Production Migration 055 Readiness Checklist](#4-production-migration-055-readiness-checklist)
5. [Production Backfill Dry-Run Plan](#5-production-backfill-dry-run-plan)
6. [Queue Dark-Launch Observation Plan](#6-queue-dark-launch-observation-plan)
7. [Runtime Observability Plan](#7-runtime-observability-plan)
8. [Failure Mode Catalog](#8-failure-mode-catalog)
9. [Operational No-Go Conditions](#9-operational-no-go-conditions)
10. [Controlled Send Activation Strategy](#10-controlled-send-activation-strategy)
11. [Legacy Send-Path Retirement Strategy](#11-legacy-send-path-retirement-strategy)
12. [Required Future Workstreams Before Autonomous Execution](#12-required-future-workstreams-before-autonomous-execution)
13. [Final Recommendation](#13-final-recommendation)

---

## 1. Purpose of the Dark-Launch Phase

### 1.1 Why queue infrastructure is deployed but inactive

PR F and PR G merged the full outbound queue infrastructure — `outbound_queue`, `send_attempts`, `dispatch_scheduler.py`, and the APScheduler dispatch loop — but `SEND_ENABLED` remains `false` everywhere. The dispatch loop will start on the next Railway production deploy but will short-circuit at the `get_settings().send_enabled` guard and process zero messages.

This is deliberate. The queue schema and dispatch code are in place so that the production system can demonstrate queue stability, lock correctness, stale-lock reclaim behavior, and scheduler lifecycle under real production load before any message is sent.

**Merged** means the code is in the repository and will be deployed at the next production deploy trigger.  
**Activated** means `SEND_ENABLED=true` has been set in the production Railway environment, which unblocks Resend API calls. These are separate events separated by an observation window of at minimum one week, more likely two.

### 1.2 Risks being mitigated

| Risk | Mitigation |
|------|-----------|
| Scheduler overlap exhausting PostgREST connection pool | APScheduler job start_date offsets (+0s/+30s/+45s/+90s) reduce simultaneous job firings; observe under production load before activating sends |
| Stale lock accumulation preventing queue progress | Stale lock reclaim runs every 2 minutes; validate reclaim count over ≥7 days in production dark-launch before activation |
| Duplicate queue claims across concurrent dispatch instances | `FOR UPDATE SKIP LOCKED` in `claim_outbound_queue_batch()` prevents races; validate by confirming no duplicate `send_attempts` rows during observation period |
| Pre-PR F drafts missing from queue | Backfill script provides one-time insertion with dry-run verification; must not run until migration 054 is on production |
| Backfill inserting drafts that were already sent | `sent_at IS NULL` guard in backfill query; validate with dry-run output before `--execute` |
| `send_attempts` missing before Resend call | Invariant enforced in `dispatch_workspace()`: insert attempt before API call; any Resend call without a prior send_attempt is a code defect |
| Production/staging DB contamination | Staging uses a separate Supabase project; production URL contains `wlyhbdmjhgvovigogdco`, staging does not; CI workflow refuses to run if URLs match |
| Accidental send activation via env var change | `SEND_ENABLED` is read from Railway environment at request time via `get_settings()`; no code path enables it; documented as requiring explicit Avanish approval |

### 1.3 Operational assumptions being validated during dark-launch

- APScheduler starts cleanly and registers all jobs without error at production boot
- `dispatch_loop` job fires at correct schedule (Mon-Fri 08:00–11:00 Chicago, every 30 minutes) but processes zero rows (queue is empty or `SEND_ENABLED=false`)
- `reclaim_stale_locks` job fires every 2 minutes without errors; no stale locks accumulate in idle state
- PostgREST connection pool is not exhausted by staggered scheduler jobs
- `claim_outbound_queue_batch()` RPC executes without error on an empty queue
- No orphaned `locked_by` rows accumulate over time

### 1.4 Difference between "merged" and "activated"

| State | Code in repo | DB migrations applied | Scheduler running | Dispatch loop running | Sends happening |
|-------|--------------|-----------------------|-------------------|-----------------------|-----------------|
| **Pre-PR F** | No queue code | No 054/055 | Legacy only | No | Legacy path only |
| **Post-PR G merge (current)** | Yes | Staging only | Staging only | Staging only (SEND_ENABLED=false) | No |
| **Production deployed** | Yes | No | No | No | No |
| **Migrations applied** | Yes | Yes | No | No | No |
| **Dark-launch active** | Yes | Yes | Yes | Yes (SEND_ENABLED=false) | No |
| **Activated** | Yes | Yes | Yes | Yes | Yes |

The system is currently between "Post-PR G merge" and "Production deployed" — migrations have not been applied to production, production has not been redeployed with PR G code.

---

## 2. Current Production State Inventory

### 2.1 Merged PRs (as of 2026-05-15)

| PR | Description | Merged | Code on prod Railway | DB migrations on prod |
|----|-------------|--------|---------------------|----------------------|
| PR F (#108) | `outbound_queue` + `send_attempts` schema (migration 054) | Yes | Unknown — no deploy-production.yml run on record | No (outbound_queue absent) |
| PR G (#109) | Dispatch scheduler, EngagementAgent dispatch, migration 055 | Yes (2026-05-15 15:08Z) | No | No |
| #110 | `gmail_api_client.py` committed to git | Yes | Unknown | N/A |
| #111 | Staging validation workflow | Yes | N/A | N/A |
| #112 | Post-merge validation workflow (Section 11) | Yes | N/A | N/A |
| #113 | Validation workflow stdout output | Yes | N/A | N/A |

**Production Railway deploy status**: `deploy-production.yml` has zero recorded runs. The last production deploy was executed via a mechanism not reflected in GitHub Actions history. The exact commit running on production Railway is unknown and must be verified before proceeding.

### 2.2 Database migration state — production (`wlyhbdmjhgvovigogdco`)

Verified via read-only psql queries on 2026-05-15:

| Migration | Description | Applied to prod | Applied to staging |
|-----------|-------------|-----------------|-------------------|
| 001–049 | All migrations through review_manifests | **Yes** | Yes |
| 050 | `workflow_events` | **No** | Yes |
| 051 | `provider_events` | **No** | Yes |
| 052 | `policy_snapshots` | **No** | Yes |
| 053 | `unique_send_key` column + trigger on outreach_drafts | **No** | Yes |
| 054 | `outbound_queue` + `send_attempts` tables | **No** | Yes |
| 055 | `dispatch_failed` enum, `max_retries` column, `claim_outbound_queue_batch()` | **No** | Yes |

**Production waterline: migration 049.** Six migrations (050–055) are unapplied.

Verification queries (run against production before any migration work):

```sql
-- Verify 049 applied
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name = 'review_manifests';
-- Expected: 1

-- Verify 050 NOT applied
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name = 'workflow_events';
-- Expected: 0

-- Verify 054 NOT applied
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name = 'outbound_queue';
-- Expected: 0

-- Verify 055 NOT applied
SELECT COUNT(*) FROM pg_enum e
JOIN pg_type t ON e.enumtypid = t.oid
WHERE t.typname = 'approval_status' AND e.enumlabel = 'dispatch_failed';
-- Expected: 0
```

### 2.3 SEND_ENABLED status

| Environment | Value | Verified |
|-------------|-------|---------|
| Production DB (`outreach_send_config.send_enabled`) | `false` | 2026-05-15 via psql |
| Staging DB (`outreach_send_config.send_enabled`) | `false` | 2026-05-15 via CI run 25929774843 |
| Production Railway env var `SEND_ENABLED` | Not set / unknown | Requires Railway dashboard verification |
| Staging Railway env var `SEND_ENABLED` | Not set (defaults to false in code) | Inferred from CI validation |

The application code reads `SEND_ENABLED` via `get_settings()` from the Railway environment variable. If unset, it defaults to `false`. The DB value is an independent guard used by the existing legacy send path. Both must be `false` for zero sends.

### 2.4 Scheduler state

| Environment | APScheduler jobs registered | dispatch_loop active | reclaim_stale_locks active |
|-------------|-----------------------------|--------------------|--------------------------|
| Production Railway | Unknown (last deploy predates PR G) | No | No |
| Staging Railway | Yes (PR G deployed 2026-05-15) | Yes (SEND_ENABLED=false) | Yes |

### 2.5 Dispatch loop state

Not running on production. Will start after production is redeployed with PR G code and migrations 050–055 are applied. With `SEND_ENABLED=false`, it will execute `claim_outbound_queue_batch()` but no drafts will be dispatched.

### 2.6 Backfill state

| Environment | Backfill run | Candidates | Status |
|-------------|-------------|-----------|--------|
| Staging | Dry-run executed 2026-05-15 | 0 | No action needed (clean staging DB) |
| Production | Not run | **51 drafts** (approved/edited, sent_at IS NULL) | Awaiting migration 054 + explicit authorization |

### 2.7 Production `outreach_send_config` state

```
send_enabled = false
batch_size   = 50
stagger_seconds = (unknown — column not yet present, added by migration 029 or later)
```

`outreach_send_config` is present. `send_enabled=false` and `batch_size=50` confirmed via direct query.

---

## 3. Exact Production Rollout Sequencing

Each step requires explicit operator authorization before execution. No step may proceed without Avanish sign-off unless stated otherwise.

### Step 0: Production Railway deploy of PR G code (prerequisite)

**Trigger**: `workflow_dispatch` on `deploy-production.yml`, targeting commit `c9608cb` (PR G merge) or later.  
**Prerequisite**: Verify Railway production shows the correct commit in the dashboard.  
**Verification**:
```bash
curl -s https://prospectiq-production.up.railway.app/health
# Expected: {"status":"ok","service":"prospectiq-api",...}
```
**Note**: Production deploy must occur before any migration work, because the application code must be compatible with the new schema before the schema is applied.

### Step 1: Production migrations 050–053

**Why before 054**: Migrations are numbered sequentially and must be applied in order. 050–053 contain logic that 054 may depend on (e.g., unique_send_key guard in 053 prevents duplicate sends). Apply each in order:

```
050_workflow_events.sql
051_provider_events.sql
052_policy_snapshots_and_context_packets.sql
053_draft_hardening_trigger_unique.sql
```

Apply via Supabase SQL editor or psql, one file at a time, verifying each before the next. Abort on any error.

**Abort condition**: Any error on any file. Do not continue.

### Step 2: Production migration 054 (`outbound_queue` + `send_attempts`)

See Section 4 for the full readiness checklist. This creates the queue infrastructure on production.

### Step 3: Production migration 055 (`dispatch_failed`, `max_retries`, `claim_outbound_queue_batch`)

Apply after 054 is confirmed. This is additive and idempotent. See Section 4 for the full readiness checklist.

### Step 4: Production backfill dry-run

See Section 5 for the full plan. Execute `scripts/backfill_outbound_queue.py` in dry-run mode against production. **Do not proceed to Step 5 without reviewing the dry-run output with Avanish.**

Expected: ~51 backfill candidates (approved/edited, sent_at IS NULL, not yet in queue). Actual count may differ depending on draft state at execution time.

### Step 5: Dark-launch observation period (≥7 days)

- Production is deployed with PR G code
- Migrations 050–055 are applied
- Queue is empty (no backfill yet)
- `SEND_ENABLED=false`
- Dispatch loop runs on schedule but claims zero rows
- Validate: scheduler starts, jobs fire, no errors, connection pool not exhausted

Minimum observation window: **7 days**. Extend to 14 days if any anomaly is detected.

### Step 6: Controlled production backfill execute

Only after Step 5 observation is clean. Execute `scripts/backfill_outbound_queue.py --execute` with operator present. Insert the ~51 pre-PR F drafts into `outbound_queue`. Verify row count immediately after.

**Authorization required**: Explicit Avanish sign-off on the dry-run output from Step 4.

### Step 7: Queue stabilization observation (≥48 hours)

With ~51 rows in `outbound_queue` and `SEND_ENABLED=false`:
- Dispatch loop claims zero rows (SEND_ENABLED guard)
- Queue rows remain `locked_by IS NULL` (never claimed)
- `send_attempts` table stays empty
- No stale locks accumulate
- Scheduler fires without error

Minimum: 48 hours. Purpose: confirm queue rows are stable and do not corrupt or disappear in idle state.

### Step 8: Controlled limited dispatch (internal sink recipients only)

See Section 10 for full strategy. This is the first live send event. One workspace, sink email addresses only, batch_size=1, `SEND_ENABLED=true` for exactly one dispatch cycle, then back to false.

### Step 9: Gradual send activation

Increase scope incrementally: sink recipients → one real workspace → full workspace set. Each increment requires an observation window and explicit authorization. See Section 10.

### Step 10: Legacy send-path retirement

After dispatch path proves reliable over ≥2 weeks of production sends. See Section 11.

---

## 4. Production Migration 055 Readiness Checklist

This checklist applies to both migration 054 and migration 055. Run it in order. Do not skip steps.

> Migration 054 must be applied and verified before migration 055. Run this checklist twice — once for 054, once for 055.

### 4.1 Preflight queries (run before applying migration)

```sql
-- For migration 054 preflight:
-- Confirm 049 applied (waterline), 054 not yet applied
SELECT
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'review_manifests') AS has_049,
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'outbound_queue') AS has_054;
-- Expected: has_049=1, has_054=0

-- For migration 055 preflight:
-- Confirm 054 applied, 055 not yet applied
SELECT
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'outbound_queue') AS has_054,
  (SELECT COUNT(*) FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid
   WHERE t.typname = 'approval_status' AND e.enumlabel = 'dispatch_failed') AS has_055;
-- Expected: has_054=1, has_055=0

-- Confirm send_enabled is false before touching schema
SELECT send_enabled FROM outreach_send_config LIMIT 1;
-- Expected: f

-- Capture pre-migration baseline counts
SELECT COUNT(*) FROM outreach_drafts WHERE approval_status IN ('approved','edited') AND sent_at IS NULL;
-- Record this number. It must not decrease after migration.

-- For 054 specifically: check approval_status enum values (055 adds dispatch_failed)
SELECT enumlabel FROM pg_enum e
JOIN pg_type t ON e.enumtypid = t.oid
WHERE t.typname = 'approval_status'
ORDER BY enumsortorder;
-- Record output. dispatch_failed must NOT appear here before 055.
```

### 4.2 Migration execution

Apply the migration file via psql with `ON_ERROR_STOP=1`:

```bash
psql "$PRODUCTION_DATABASE_URL" \
  -f supabase_migrations/migrations/054_outbound_queue_send_attempts.sql \
  -v ON_ERROR_STOP=1

psql "$PRODUCTION_DATABASE_URL" \
  -f supabase_migrations/migrations/055_dispatch_schema.sql \
  -v ON_ERROR_STOP=1
```

**Do not proceed to the next command if exit code is non-zero.**

### 4.3 Post-migration verification queries

```sql
-- After 054:
SELECT
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'outbound_queue') AS has_outbound_queue,
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'send_attempts') AS has_send_attempts,
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'outbound_queue' AND column_name = 'locked_by') AS has_locked_by,
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'outbound_queue' AND column_name = 'next_retry_at') AS has_next_retry_at,
  (SELECT COUNT(*) FROM outbound_queue) AS queue_rows_initial,
  (SELECT COUNT(*) FROM send_attempts) AS attempt_rows_initial;
-- Expected: all counts = 1 except queue_rows_initial=0, attempt_rows_initial=0

-- After 055:
SELECT
  (SELECT COUNT(*) FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid
   WHERE t.typname = 'approval_status' AND e.enumlabel = 'dispatch_failed') AS has_dispatch_failed,
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_name = 'outreach_send_config' AND column_name = 'max_retries') AS has_max_retries,
  (SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
   WHERE n.nspname = 'public' AND p.proname = 'claim_outbound_queue_batch') AS has_claim_fn,
  (SELECT column_default FROM information_schema.columns
   WHERE table_name = 'outreach_send_config' AND column_name = 'max_retries') AS max_retries_default;
-- Expected: all = 1, max_retries_default = '4'

-- Confirm send_enabled unchanged after migration
SELECT send_enabled FROM outreach_send_config LIMIT 1;
-- Expected: f (must not have changed)

-- Smoke test claim_outbound_queue_batch() with null workspace
SELECT COUNT(*) FROM claim_outbound_queue_batch(
  '00000000-0000-0000-0000-000000000000'::uuid,
  'migration-smoke-test',
  10
);
-- Expected: 0 (no rows, no error)
```

### 4.4 Rollback criteria

A migration must be rolled back if:

- `ON_ERROR_STOP=1` triggers (psql exits non-zero)
- Post-migration verification query shows unexpected count (any expected=1 returns 0, or vice versa)
- `send_enabled` is `true` after migration (must investigate immediately)
- `claim_outbound_queue_batch()` smoke test returns an error
- Draft count for `approval_status IN ('approved','edited') AND sent_at IS NULL` decreased (data loss)

### 4.5 Rollback actions

Migration 054 and 055 are both additive (no DROP, no destructive ALTER). The direct rollback is:

```sql
-- Rollback 055 (remove objects 055 added):
-- Note: removing an enum value is not supported in PostgreSQL without full enum rebuild.
-- dispatch_failed value cannot be removed once added. However, it has no effect unless
-- a row explicitly sets approval_status = 'dispatch_failed'. With send_enabled=false,
-- no row will ever be set to this value. This is an acceptable non-rollback.
ALTER TABLE outreach_send_config DROP COLUMN IF EXISTS max_retries;
DROP FUNCTION IF EXISTS claim_outbound_queue_batch(UUID, TEXT, INTEGER);

-- Rollback 054:
DROP TABLE IF EXISTS send_attempts;
DROP TABLE IF EXISTS outbound_queue;
```

Rollback of 054 must only be performed if zero rows have been inserted into `outbound_queue` and `send_attempts`. Verify before executing:

```sql
SELECT COUNT(*) FROM outbound_queue; -- Must be 0
SELECT COUNT(*) FROM send_attempts;  -- Must be 0
```

### 4.6 Abort conditions

Stop immediately and do NOT proceed if:

- Production database URL contains `wlyhbdmjhgvovigogdco` but connection is refused (wrong credentials)
- Any migration file produces an ERROR line before `ON_ERROR_STOP=1` exits (output may contain warnings; errors are distinct)
- `send_enabled = true` at any point in this checklist — investigate before proceeding
- Operator cannot connect to Railway staging health endpoint after migration (may indicate broad DB issue)

### 4.7 Operator verification and evidence capture

Before marking the migration complete, capture and record the following:

```
Migration applied:       [054 / 055]
Applied at:              [ISO timestamp CDT]
Applied by:              Avanish Mehrotra
psql exit code:          [0]
Post-verify query output: [paste result of post-migration verification query above]
smoke test result:       [0 rows, no error]
send_enabled post:       [f]
Draft baseline count:    [N] (must match pre-migration count)
```

Store this in `docs/operations/migration-evidence/YYYY-MM-DD-migration-0NN-production.txt`.

---

## 5. Production Backfill Dry-Run Plan

### 5.1 Prerequisites

- Migration 054 applied and verified on production
- Migration 055 applied and verified on production
- `SEND_ENABLED=false` confirmed on production
- `STAGING_SERVICE_KEY` added to GitHub secrets (or operator running the script locally with production credentials)

### 5.2 Execution

```bash
# Dry-run only — no --execute flag
SUPABASE_URL=https://wlyhbdmjhgvovigogdco.supabase.co \
SUPABASE_SERVICE_KEY=<production service key> \
python scripts/backfill_outbound_queue.py
```

The script will print counts and draft IDs without writing. Do not add `--execute` in this step.

### 5.3 Expected output format

```
Scanning outreach_drafts for pre-PR F approved drafts with sent_at IS NULL...

Eligible drafts:     [N]
Already in queue:    0
To insert:           [N]

Draft IDs to backfill:
  <uuid>  workspace=<uuid>  status=approved  created=<timestamp>
  ...

DRY-RUN MODE: No rows written. Pass --execute to insert these rows after reviewing the list above.
```

### 5.4 Acceptable ranges

| Metric | Expected | If outside range |
|--------|----------|-----------------|
| Eligible drafts | 45–60 (based on 51 observed 2026-05-15) | If > 100: investigate — possible data integrity issue. If 0: verify query is correct. |
| Already in queue | 0 (no backfill has run yet) | If > 0: prior partial backfill ran; investigate before proceeding |
| To insert | = Eligible (since already-in-queue = 0) | Mismatch indicates race condition or prior partial run |

### 5.5 Anomaly detection

Before running `--execute`, inspect each row in the dry-run output:

1. **Duplicate draft IDs**: Each ID must appear exactly once. If a draft appears twice, there is a data integrity problem in `outreach_drafts`. Do not proceed.

2. **sent_at invariant**: All listed drafts must have `sent_at IS NULL`. The query enforces this, but spot-check two or three IDs directly:

```sql
SELECT id, sent_at, approval_status, created_at
FROM outreach_drafts
WHERE id = '<draft_id_from_output>';
-- sent_at must be NULL
-- approval_status must be 'approved' or 'edited'
```

3. **Workspace consistency**: All draft IDs should belong to known, active workspaces. Check any unfamiliar workspace UUIDs.

4. **Age of drafts**: Check the `created_at` range. Drafts older than 90 days may represent stale pipeline artifacts that should not be dispatched. Flag any draft with `created_at < NOW() - INTERVAL '90 days'` for manual review before including in backfill.

### 5.6 Duplicate detection

The backfill script checks `outbound_queue` for existing rows matching each `draft_id`. If any draft already has a queue row (because `approve_draft_and_enqueue()` was called after PR F deployed), it is excluded from the to-insert list. This is the `ON CONFLICT DO NOTHING` path.

Verify before `--execute`:

```sql
SELECT COUNT(*) FROM outbound_queue
WHERE draft_id IN (
  SELECT id FROM outreach_drafts
  WHERE approval_status IN ('approved', 'edited') AND sent_at IS NULL
);
-- Must be 0 before first backfill run. If > 0, reconcile before proceeding.
```

### 5.7 Rollback strategy

The backfill inserts rows into `outbound_queue`. If an incorrect batch was inserted, remove with:

```sql
-- Delete backfill rows that have never been claimed (safe to remove)
DELETE FROM outbound_queue
WHERE locked_by IS NULL
  AND draft_id IN (
    SELECT id FROM outreach_drafts
    WHERE approval_status IN ('approved', 'edited') AND sent_at IS NULL
  );
-- Verify: this should only remove rows inserted by the backfill
```

Do not delete rows where `locked_by IS NOT NULL` — those may be in active dispatch.

### 5.8 Operator sign-off requirements

Before running `--execute`, Avanish must review and explicitly approve:

- Dry-run output (all draft IDs, counts)
- Spot-checks on at least 3 draft rows (sent_at IS NULL confirmed)
- Age range of drafts (no drafts older than 90 days in backfill set without explicit inclusion decision)
- Workspace list (all workspaces recognized)

Record approval as: "Backfill approved by Avanish Mehrotra on [date] after reviewing dry-run output."

---

## 6. Queue Dark-Launch Observation Plan

### 6.1 What should exist in `outbound_queue` during dark-launch

**Before backfill**: Zero rows. Any rows present without backfill indicate the `approve_draft_and_enqueue()` path in PR F is inserting rows for newly-approved drafts (which is correct behavior).

**After backfill**: Rows equal to the `--execute` insertion count (approximately 51). Each row should have:
- `locked_by IS NULL`
- `locked_at IS NULL`
- `next_retry_at IS NULL`
- `retry_count = 0`
- `priority = 5` (backfill default)
- `enqueued_at` set to backfill execution time

### 6.2 What should NOT happen

- `send_attempts` rows should NOT be created while `SEND_ENABLED=false`
- `locked_by` should NOT be set while `SEND_ENABLED=false` (dispatch loop guard prevents it)
- `approval_status = 'dispatch_failed'` on any draft (requires dispatch path execution, which is blocked)
- Queue row count should NOT decrease unless rows are explicitly deleted
- `retry_count` should NOT increment (no dispatch attempts occur)

Verify with a daily check:

```sql
SELECT
  COUNT(*) FILTER (WHERE locked_by IS NOT NULL) AS locked_rows,
  COUNT(*) FILTER (WHERE retry_count > 0) AS retried_rows,
  COUNT(*) FROM send_attempts AS attempt_rows
FROM outbound_queue;
-- All values must be 0 during dark-launch
```

### 6.3 Expected queue growth patterns

| Trigger | Expected behavior |
|---------|-----------------|
| Draft approved via UI (`approve_draft_and_enqueue()`) | One new row inserted into `outbound_queue` with `retry_count=0`, `locked_by=NULL` |
| Backfill `--execute` | Bulk insert, all rows with `priority=5`, `retry_count=0`, `locked_by=NULL` |
| `SEND_ENABLED=false` dispatch loop tick | Zero rows claimed, zero `send_attempts` created, no queue mutations |
| Scheduler restart (Railway redeploy) | Job re-registration; no queue mutations |

### 6.4 Lock behavior expectations

With `SEND_ENABLED=false`, `dispatch_workspace()` returns immediately at the guard without calling `claim_outbound_queue_batch()`. Therefore:

- `locked_by` column must remain `NULL` on all rows
- `locked_at` column must remain `NULL` on all rows
- `reclaim_stale_locks` fires every 2 minutes and should report zero reclaims (nothing to reclaim)

Railway log signature for a clean idle tick:
```
dispatch.send_disabled workspace_id=<uuid> — returning early
```

There must be NO log lines containing:
```
dispatch.stale_lock_reclaim reclaimed=N  (where N > 0, in dark-launch idle state)
```
Stale reclaim log entries during dark-launch with empty queue indicate a bug.

### 6.5 Retry expectations

Zero. No draft should have `retry_count > 0` or `next_retry_at IS NOT NULL` during dark-launch. If either appears, the dispatch loop executed despite `SEND_ENABLED=false`, which is a defect requiring immediate investigation.

### 6.6 `send_attempts` expectations

Zero rows. The `send_attempts` invariant states that rows are inserted immediately before each Resend API call. With `SEND_ENABLED=false`, no Resend calls are made and therefore no `send_attempts` rows are created.

```sql
SELECT COUNT(*) FROM send_attempts;
-- Must be 0 during entire dark-launch phase
```

### 6.7 Scheduler expectations

Check Railway logs at each scheduler tick (every 30 minutes for dispatch_loop, every 2 minutes for reclaim_stale_locks). Acceptable log signatures:

```
# dispatch_loop tick, SEND_ENABLED=false
INFO dispatch_loop.start workspaces=N
INFO dispatch.send_disabled workspace_id=<uuid>
INFO dispatch_loop.complete dispatched=0 delivered=0

# reclaim_stale_locks tick (clean, nothing to reclaim)
INFO reclaim_stale_locks.start workspaces=N
INFO reclaim_stale_locks.complete reclaimed=0
```

Unacceptable during dark-launch:
```
WARNING dispatch.stale_lock_reclaim reclaimed=N  (N > 0)
ERROR dispatch.claim_failed
ERROR claim_outbound_queue_batch
```

### 6.8 Acceptable idle-state behavior

The dispatch loop running against a queue with rows (after backfill) and `SEND_ENABLED=false` is expected to:
1. Call `get_settings().send_enabled` → returns `False`
2. Log `dispatch.send_disabled` and return
3. NOT call `claim_outbound_queue_batch()`
4. NOT modify any queue row

This is the intended behavior. The dispatcher is idle, not broken.

---

## 7. Runtime Observability Plan

### 7.1 Required Railway log signals

Check Railway production logs after each production deploy and at regular intervals (at minimum, once per day during dark-launch).

**Startup signals (after deploy):**

```
# Scheduler registered all expected jobs
APScheduler started
Job 'dispatch_loop' registered: cron mon-fri 8-11 minute=0,30 America/Chicago
Job 'reclaim_stale_locks' registered: interval minutes=2
Job 'health_snapshot' registered: interval minutes=15
Job 'pipeline_qc' registered: interval minutes=15
Job 'qualification' registered: interval minutes=15
Job 'gmail_intake' registered: interval minutes=15
```

Absence of any registered job at startup is a defect.

**Scheduler tick signals (every 30 min for dispatch):**

```
INFO  [dispatch_loop] Starting for N workspaces
INFO  [dispatch] workspace_id=<uuid> send_enabled=False — skip
INFO  [dispatch_loop] Complete: 0 dispatched, 0 errors
```

**Stale lock reclaim signal (every 2 min, should be silent):**

```
INFO  [reclaim_stale_locks] Checked N workspaces, reclaimed 0 locks
```

**Error signals that require immediate operator action:**

```
ERROR [scheduler] Job execution failed: <job_id>
ERROR [dispatch] claim_outbound_queue_batch failed
ERROR [dispatch] send_attempts insert returned None
CRITICAL [dispatch] Resend call made without send_attempts record
```

### 7.2 Required Supabase query checks

Run against production on a regular basis during dark-launch. Suggested frequency: daily for first 7 days, then weekly.

```sql
-- Daily dark-launch health check
SELECT
  (SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL) AS stuck_locks,
  (SELECT COUNT(*) FROM outbound_queue WHERE retry_count > 0) AS unexpected_retries,
  (SELECT COUNT(*) FROM send_attempts) AS unexpected_send_attempts,
  (SELECT COUNT(*) FROM outbound_queue) AS queue_depth,
  (SELECT send_enabled FROM outreach_send_config LIMIT 1) AS send_enabled,
  NOW() AS checked_at;
-- All anomaly columns must be 0. send_enabled must be f.

-- Lock age check (must be empty)
SELECT id, locked_by, locked_at, NOW() - locked_at AS lock_age
FROM outbound_queue
WHERE locked_by IS NOT NULL
ORDER BY locked_at;
-- No rows expected during dark-launch.

-- Queue growth check (new rows since last check)
SELECT COUNT(*), MIN(enqueued_at), MAX(enqueued_at)
FROM outbound_queue
WHERE enqueued_at > NOW() - INTERVAL '24 hours';
-- Shows drafts approved in last 24h. Natural growth is expected from review approvals.
```

### 7.3 Operational dashboards to build (future work)

These are not prerequisites for dark-launch but should be built before send activation:

- **Queue depth over time**: `COUNT(*) FROM outbound_queue` sampled every 15 minutes, graphed
- **Queue lag**: `NOW() - MIN(enqueued_at)` for unlocked rows — oldest waiting draft
- **Lock utilization**: `COUNT(*) WHERE locked_by IS NOT NULL` over time
- **Retry histogram**: Distribution of `retry_count` values in queue
- **Send attempt status distribution**: `COUNT(*) GROUP BY status FROM send_attempts`
- **Dispatch throughput**: `delivered` count per scheduler tick over time

### 7.4 Queue health indicators

| Indicator | Healthy | Warning | Critical |
|-----------|---------|---------|---------|
| Queue depth (post-backfill, pre-activation) | Stable or growing slowly from new approvals | Rapid unexpected growth | Rapid unexpected decrease |
| Locked rows during dark-launch | 0 | > 0 for > 5 minutes | > 0 for > 10 minutes |
| `send_attempts` rows during dark-launch | 0 | Any value > 0 | Any value > 0 |
| Stale lock reclaim count per tick | 0 | > 0 (investigate) | > 5 (immediate action) |
| Draft count with `approval_status='dispatch_failed'` | 0 | > 0 (investigate) | N/A |

### 7.5 Stale lock indicators

A stale lock is a `locked_at` timestamp older than 5 minutes on a row where `locked_by IS NOT NULL`. Stale locks accumulate if a dispatch worker crashes mid-batch without completing the update cycle.

Detection query:

```sql
SELECT id, draft_id, workspace_id, locked_by, locked_at,
       NOW() - locked_at AS lock_age
FROM outbound_queue
WHERE locked_by IS NOT NULL
  AND locked_at < NOW() - INTERVAL '5 minutes';
```

Expected during dark-launch: zero rows. Any result requires investigation before send activation.

### 7.6 Retry storm indicators

A retry storm occurs when a large number of queue rows enter exponential backoff simultaneously. Indicators:

```sql
-- Check for high retry counts
SELECT retry_count, COUNT(*) FROM outbound_queue
GROUP BY retry_count ORDER BY retry_count;
-- Expected during dark-launch: all retry_count = 0

-- Check for concentrated next_retry_at values (retry storm signature)
SELECT DATE_TRUNC('minute', next_retry_at) AS retry_window, COUNT(*)
FROM outbound_queue
WHERE next_retry_at IS NOT NULL
GROUP BY 1 ORDER BY 1;
-- Expected during dark-launch: no rows
```

### 7.7 Pool saturation indicators

PostgREST connection pool exhaustion appears in Railway logs as:

```
ERROR could not obtain connection from pool
ERROR connection pool timeout
```

The scheduler job staggering (+0s/+30s/+45s/+90s offsets) is designed to prevent all 5 jobs from hitting PostgREST simultaneously. If pool exhaustion appears in logs, reduce batch_size in `outreach_send_config` first before investigating further.

### 7.8 Duplicate-send indicators

A duplicate send is a Resend API call for a draft that has already been sent. Detection requires send activation (dark-launch will not produce duplicates). Pre-activation verification:

```sql
-- Ensure no draft has sent_at IS NOT NULL AND also has a queue row
SELECT oq.draft_id, od.sent_at
FROM outbound_queue oq
JOIN outreach_drafts od ON oq.draft_id = od.id
WHERE od.sent_at IS NOT NULL;
-- Must be empty. If not, a sent draft is still queued — investigate before activation.
```

### 7.9 Queue lag indicators

Queue lag is the age of the oldest unlocked, eligible queue row:

```sql
SELECT NOW() - MIN(enqueued_at) AS oldest_waiting,
       COUNT(*) AS eligible_count
FROM outbound_queue
WHERE locked_by IS NULL
  AND (next_retry_at IS NULL OR next_retry_at <= NOW());
```

During dark-launch with `SEND_ENABLED=false`, lag will grow indefinitely as no rows are consumed. This is expected. This indicator becomes meaningful only after send activation.

---

## 8. Failure Mode Catalog

| Failure mode | Detection method | Severity | Immediate operator action | Rollback action | SEND_ENABLED must stay false? |
|---|---|---|---|---|---|
| **Duplicate queue claims** | Two `send_attempts` rows with same `draft_id` and overlapping `created_at`; or `locked_by` same row by two instance IDs | High | Stop dispatch loop; investigate `claim_outbound_queue_batch()` execution log | Set `batch_size=0` in send config; disable dispatch cron | Yes — until root cause confirmed |
| **Pool exhaustion** | Railway log: `could not obtain connection from pool`; health endpoint timeouts | High | Reduce `batch_size` to 1 in `outreach_send_config`; verify scheduler job offsets are in place | Restart Railway staging service; reduce job concurrency | Yes — until pool stability confirmed |
| **Stale locks** | `locked_at < NOW() - INTERVAL '5 minutes'` with `locked_by IS NOT NULL`; `reclaim_stale_locks` log shows `reclaimed=N > 0` repeatedly | Medium | Verify reclaim job is running; check Railway logs for worker crash during batch | `reclaim_stale_locks` will auto-clear; if not, run manually: `UPDATE outbound_queue SET locked_by=NULL, locked_at=NULL WHERE locked_at < NOW() - '5 minutes'::interval` | No — reclaim is self-healing; monitor |
| **Retry storm** | High `retry_count` values on many rows; concentrated `next_retry_at` window; Railway log flood of transient error classifications | High | Set `batch_size=0`; investigate Resend API availability; check for misconfigured sender | `UPDATE outbound_queue SET retry_count=0, next_retry_at=NULL WHERE retry_count > 0` (only if confident in root cause) | Yes — until Resend errors resolved |
| **Queue growth runaway** | `COUNT(*) FROM outbound_queue` growing faster than approval rate; rows with `priority=5` accumulating without dispatch | Medium | Verify `SEND_ENABLED=false` is enforced; investigate whether any code path is inserting duplicates | Audit and deduplicate: `DELETE FROM outbound_queue WHERE id NOT IN (SELECT MIN(id) FROM outbound_queue GROUP BY draft_id)` | No — but investigate |
| **Missing send_attempts** | Resend API call logged without prior `send_attempts` row; or `sent_at` set without `send_attempts` record | Critical | Immediately set `SEND_ENABLED=false`; quarantine affected drafts | Reconstruct missing rows from interaction logs if possible; file as P0 defect | **Yes — do not re-enable until fixed** |
| **Orphaned queue rows** | `outbound_queue` rows whose `draft_id` does not exist in `outreach_drafts`; or whose workspace is deleted | Low | Remove orphans: `DELETE FROM outbound_queue WHERE draft_id NOT IN (SELECT id FROM outreach_drafts)` | None required beyond the delete | No |
| **Dispatch without send_attempt row** | Resend API logged (via webhook or provider event) with no matching `send_attempts` record | Critical | Set `SEND_ENABLED=false`; audit all recent Resend events against `send_attempts` | Root cause must be identified before any re-activation | **Yes** |
| **Scheduler overlap** | Two concurrent jobs of the same ID executing simultaneously; duplicate log entries with identical `job_id` within 1 minute | Medium | Check APScheduler `misfire_grace_time` configuration; check Railway deployment for duplicate running instances | Redeploy production Railway (kills all instances); verify single-instance deployment | No — but resolve before activation |
| **Production/staging contamination** | Production contact data in staging DB; staging Supabase URL (`wlyhbdmjhgvovigogdco`) in any non-production log | Critical | Immediately stop all DB operations; audit access logs | Restore staging DB from known-clean snapshot | **Yes on all environments** |
| **Accidental send activation** | `send_enabled=true` in `outreach_send_config` without operator authorization; `SEND_ENABLED=true` in Railway production env | Critical | Set `SEND_ENABLED=false` in Railway env immediately; set `UPDATE outreach_send_config SET send_enabled=false` | Identify how activation occurred; audit Railway env change history; check for unauthorized `UPDATE` statements in audit log | **Yes — remains false until re-authorized** |

---

## 9. Operational No-Go Conditions

### 9.1 Production migration 055 must NOT proceed if:

- Migration 054 has not been applied and verified (outbound_queue table must exist)
- `send_enabled = true` on production at time of migration
- Railway production is not running PR G code (deploy step 0 must be complete)
- Post-migration verification for 054 produced any unexpected result
- Operator cannot connect to production Railway health endpoint
- Any active stale locks exist on staging or production
- Avanish has not given explicit authorization for this migration in the current session

### 9.2 Backfill `--execute` must NOT proceed if:

- Migration 054 has not been applied to production
- Migration 055 has not been applied to production
- Dry-run output has not been reviewed and approved by Avanish
- Dry-run shows `to_insert > 100` (unexpected volume — investigate before inserting)
- Any draft in the dry-run output has `sent_at IS NOT NULL` (invariant violation — the query filters these, but if somehow present, stop)
- Any draft in the dry-run output is older than 90 days and has not been explicitly reviewed
- `send_enabled = true` (would allow dispatch immediately after backfill, before observation window)
- The dry-run `already_queued` count is > 0 unexpectedly (investigate prior partial run)

### 9.3 Send activation (`SEND_ENABLED=true`) must NOT proceed if:

- Dark-launch observation window has not completed (minimum 7 days post-migration)
- Any entry in the failure mode catalog has been triggered and not resolved
- `send_attempts` table is not empty before activation attempt (unexpected pre-activation records)
- Any queue row has `retry_count > 0` before activation
- Any queue row has `locked_by IS NOT NULL` before activation
- Production Railway logs show any scheduler errors in the prior 7 days
- Deliverability infrastructure is not verified (SPF/DKIM/DMARC on sending domains, bounce handling, unsubscribe compliance — Workstream 3)
- Production observability dashboards are not in place (Workstream 2)
- Sender pool and per-domain rate limits are not confirmed (Workstream 3)
- Avanish has not given explicit authorization with the words "enable sends" or equivalent in the current session

---

## 10. Controlled Send Activation Strategy

This section describes the intended future activation sequence. **None of these steps are authorized at the time of this document. Each requires a separate explicit instruction from Avanish.**

### 10.1 Phase 1: Internal sink recipients only

Before any real contact receives an email:

1. Set `batch_size = 1` in `outreach_send_config`
2. Insert a single test draft into `outbound_queue` whose recipient email is a verified internal sink address (e.g., `avanish.mehrotra+sink@gmail.com` or equivalent)
3. Set `SEND_ENABLED=true` in Railway production for one scheduler window (one 30-minute dispatch tick)
4. Verify: exactly one `send_attempts` row created, status transitions to `DELIVERED`, no duplicate rows
5. Set `SEND_ENABLED=false` immediately after the tick completes
6. Verify: no further `send_attempts` rows created after `SEND_ENABLED=false`
7. Observe for 24 hours: no additional Resend events, no stale locks, no retry activity

Pass criteria: One email delivered to sink address. Resend dashboard shows exactly one event. `send_attempts` table shows exactly one row with `status='DELIVERED'`. No errors.

### 10.2 Phase 2: One workspace, limited batch

After Phase 1 passes:

1. Select one low-risk workspace (fewest active contacts, known contact data)
2. Set `batch_size = 3` in `outreach_send_config`
3. Enable `SEND_ENABLED=true` for one scheduler window
4. Observe: exactly 3 queue rows claimed, 3 `send_attempts` rows created, status progression correct
5. Disable `SEND_ENABLED=false` after one tick

Pass criteria: exactly 3 sends, 0 bounce spikes, 0 duplicate `send_attempts` rows, Resend dashboard matches `send_attempts` count.

### 10.3 Phase 3: Full workspace set, limited batch

After Phase 2 passes with 72-hour observation:

1. Set `batch_size = 5`
2. Enable dispatch for one full day (Mon-Fri window)
3. Monitor continuously for first 2 hours, then hourly for remainder of day
4. Disable at end of business day; observe overnight

### 10.4 Phase 4: Normal operation

After Phase 3 passes with 7-day observation:

1. Restore `batch_size` to production value (currently 50)
2. Enable permanent `SEND_ENABLED=true`
3. Begin Workstream 3 monitoring (deliverability, bounce rates, complaint rates)

### 10.5 Rollback checkpoints

At each phase, the rollback procedure is identical:

```bash
# Railway: set SEND_ENABLED=false in environment
# DB:
UPDATE outreach_send_config SET send_enabled = false;
```

This stops all new dispatch within one scheduler tick (≤30 minutes). In-flight sends may complete; there is no mechanism to recall a Resend API call once made.

### 10.6 Legacy-path coexistence during activation

During Phases 1–3, the legacy `_run_send_approved` scheduler job remains active alongside the new dispatch loop. Both are gated by `SEND_ENABLED`. When `SEND_ENABLED=true`, both paths are active. To prevent double-sending:

- The legacy path selects drafts by `approval_status = 'approved'` and `sent_at IS NULL`
- The dispatch path processes only rows in `outbound_queue`
- A draft can only be in `outbound_queue` if it was explicitly enqueued (via `approve_draft_and_enqueue()` or the backfill script)

These are separate eligibility sets and should not overlap unless a draft exists in both `outbound_queue` and is simultaneously eligible for the legacy path. Verify before activation:

```sql
-- Identify any draft that would be claimed by BOTH paths simultaneously
SELECT od.id, od.approval_status, od.sent_at, oq.id AS queue_id
FROM outreach_drafts od
JOIN outbound_queue oq ON oq.draft_id = od.id
WHERE od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND oq.locked_by IS NULL;
-- These drafts are at risk of double-send. Resolve before activation.
```

---

## 11. Legacy Send-Path Retirement Strategy

The legacy send path is `_run_send_approved()` in `backend/app/api/main.py`, which calls `EngagementAgent._send_approved_drafts()` on a 15-minute scheduler job.

### 11.1 Preconditions before removal

All of the following must be true:

1. Dispatch path has been running in production for ≥14 days with `SEND_ENABLED=true`
2. No send has been attributed to the legacy path for ≥7 days (verify via `interactions` table — check `source` or `method` field)
3. All approved drafts flow through `outbound_queue` (i.e., all new approvals call `approve_draft_and_enqueue()`)
4. `send_attempts` coverage is 100% — every sent draft has a `send_attempts` row
5. `backfill_outbound_queue.py` has been run and confirmed zero remaining pre-PR F drafts outside the queue
6. Explicit authorization from Avanish to remove the legacy path

### 11.2 Retirement procedure

1. Set `_run_send_approved` scheduler job `max_instances=0` or comment out `scheduler.add_job` call in `main.py`
2. Deploy to staging; observe for 24 hours
3. Confirm no legacy-path sends occur (no `_send_approved_drafts` log entries)
4. Deploy to production; observe for 48 hours
5. After 48 hours clean observation, remove the dead code paths from `engagement.py` and `main.py`

### 11.3 Rollback if dispatch path misbehaves post-retirement

If the dispatch path exhibits errors after legacy path retirement:

1. Re-add the `scheduler.add_job` call for `_run_send_approved` immediately
2. Deploy the restored code to production
3. `SEND_ENABLED` behavior is unchanged — the legacy path is also gated by `send_enabled`

The legacy path code must not be deleted from the repository until at least 14 days of production dispatch operation have been observed. Keep the code in place even after the scheduler job is disabled; remove only when thoroughly validated.

### 11.4 Coexistence duration guidance

| Duration | State |
|----------|-------|
| Dark-launch phase | Both paths present; neither sending |
| Phases 1–3 of send activation | Both paths present; dispatch path active; legacy path active but should produce zero additional sends (queue is authoritative) |
| 14 days post full activation | Legacy scheduler job disabled; code retained |
| 30 days post full activation with zero legacy-path activity | Legacy code removed |

---

## 12. Required Future Workstreams Before Autonomous Execution

**Autonomous send behavior — where the dispatch loop runs without per-send manual oversight — is explicitly deferred.** The dispatch loop as built requires `SEND_ENABLED=true` to operate, and that flag requires manual authorization. No workstream currently under development changes this requirement without a separate explicit decision.

The following workstreams must reach a defined maturity level before any autonomous execution is considered:

### 12.1 Workstream 1 — Functional and governance testing

**Required before activation**: Integration test suite covering the full send path end-to-end: queue claim, assertion check, Resend call, `send_attempts` lifecycle, retry path, stale lock reclaim, and duplicate-send prevention. Mocked Resend acceptable for unit tests; requires a staging send to a sink address for integration confidence.

**Current state**: Unit tests (23 in `test_pr_g_dispatch.py`) cover dispatch logic. No integration test of the full path from approval to Resend API exists.

### 12.2 Workstream 2 — Observability and telemetry

**Required before activation**: At minimum, the following must be answerable from production data without running ad-hoc queries:

- What is the current queue depth?
- How many drafts were delivered in the last 24 hours?
- Are there any stale locks?
- What is the retry distribution?
- Why is this specific draft not sending? (deterministic answer)

**Current state**: No dashboard exists. Manual Supabase queries only.

### 12.3 Workstream 3 — Deliverability and reputation infrastructure

**Required before activation**: SPF, DKIM, DMARC configured and verified on all sending domains. Resend bounce webhook configured and handled. Per-domain daily send cap enforced. Unsubscribe link present in all drafts. Complaint handling procedure documented.

**Current state**: Not assessed. This is a hard blocker for real contact sends.

### 12.4 Workstream 4 — Draft quality

**Required before activation**: Manual review of at least 20 production-eligible drafts. Any draft with a subject line that is generic, misleading, or in violation of CAN-SPAM must be excluded from the first backfill batch.

**Current state**: Not assessed.

### 12.5 Workstream 5 — Queue and lifecycle architecture

**Required before activation**: Review of queue ordering logic, priority scoring, and stale draft expiration. Drafts older than 90 days should not be dispatched without explicit review. Per-sender daily cap must be enforced at the queue level before activation.

**Current state**: Queue uses simple FIFO with priority=5 for all backfill rows. No staleness check. No per-sender cap.

### 12.6 Workstream 6 — Operational runbooks

**Required before activation**: Complete send activation checklist, rollback procedure, emergency shutdown procedure, bounce-spike response, and webhook outage procedure. This document covers the dark-launch phase; a separate activation runbook is needed for the go-live event.

**Current state**: Dark-launch runbook (this document) is complete. Activation runbook does not exist.

---

## 13. Final Recommendation

### 13.1 Recommended next operational action

**Apply production migrations 050–055 in sequence, then redeploy production Railway with PR G code.** This is the minimum step required to enter true dark-launch state (scheduler running, dispatch loop active but idle).

Before executing: verify the exact commit running on production Railway, confirm Railway production health endpoint, and confirm `send_enabled=false` in both Railway env and DB. Apply migrations one at a time with the readiness checklist in Section 4.

Do not run the backfill. Do not enable sends. These are separate, subsequent decisions.

### 13.2 Recommended observation window duration

**Minimum 7 days** after production deploy with migrations applied, before any backfill execution. **Minimum 14 days** after backfill execute, before any send activation. These windows are non-negotiable unless a critical operational reason for acceleration exists and is explicitly documented.

### 13.3 What must be learned before enabling sends

1. Scheduler starts cleanly on production with all 7 jobs registered
2. `dispatch_loop` and `reclaim_stale_locks` fire on schedule without error for ≥7 consecutive days
3. Zero stale locks accumulate in idle state
4. PostgREST connection pool shows no exhaustion events
5. `send_attempts` table remains empty throughout dark-launch (no phantom sends)
6. Queue rows inserted by backfill remain intact and uncorrupted after 7+ days
7. Workstream 3 (deliverability) has been assessed and no blocking issues identified
8. At least one successful sink-address send validated in staging

### 13.4 Current system state declaration

**As of 2026-05-15, the system is in dark-launch state on staging and in pre-dark-launch state on production.**

- Production database: migrations through 049 applied; 050–055 not applied
- Production Railway: PR G code not deployed
- Staging database: migrations through 055 applied
- Staging Railway: PR G code deployed; health endpoint 200
- `send_enabled`: `false` on both staging and production
- `send_attempts` rows: 0
- Dispatch loop: not running on production; running but idle on staging
- Backfill: not executed on production; not needed on staging (0 candidates)
- Production backfill candidates: 51 drafts (approved/edited, sent_at IS NULL)

No sends have occurred via the dispatch path on any environment. The system remains in zero-send state pending completion of the steps in Section 3.

---

*Author: Avanish Mehrotra & Digitillis Architecture Team*  
*This document must be updated whenever production state changes. Do not rely on stale state descriptions for operational decisions — run the verification queries in Section 2 before each migration step.*
