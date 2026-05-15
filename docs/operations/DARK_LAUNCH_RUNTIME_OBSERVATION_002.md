# Dark-Launch Runtime Observation — 002
## ProspectIQ — Stage B Controlled Queue Population and Observability Validation

**Document date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Observation window:** Begins at backfill execution; minimum 48 hours (covers 3 send-window cycles Mon-Fri 8-11 AM CT)  
**Status:** PLANNING — no writes have occurred; execution requires Section 16 sign-off  
**Prerequisite documents:** `BACKFILL_REVIEW_REPORT.md`, `OPERATIONAL_READINESS_ASSESSMENT_001.md`, `BACKFILL_EXECUTION_PRECHECK_001.md`

---

## 1. Operational Decisions — Recorded

The following REVIEW decisions from `BACKFILL_EXECUTION_PRECHECK_001.md` are accepted and recorded:

| Draft ID | Contact | Decision | Rationale |
|----------|---------|----------|-----------|
| `870b2cfd` | jmondello@vicorpower.com | EXCLUDE | Unverified email + 43 days stale + non-buyer title |
| `73a58bef` | jgondkoff@upmet.com | INCLUDE | catch_all, bounded risk, GM title, 12 days |
| `34b43c7d` | kathyw@gwfg.com | INCLUDE | Step-1 confirmed delivery validates address; COO title |
| `8a1d3964` | tzwiebel@rudolphfoods.com | INCLUDE | Step-1 confirmed delivery validates address; Director QA |
| `f24e49a0` | ronny.hoff@alterainfra.com | DEFER | ZeroBounce verification required before decision |
| `33c5604a` | yina.hernandez@richlinegroup.com | EXCLUDE | HR role, jewelry vertical, null email status |

Post-decisions eligible pool: **39 drafts** (36 SAFE + 3 INCLUDE-REVIEW), plus 1 deferred.  
Initial cohort: **8 drafts** (defined in Section 2).  
Remaining eligible (not yet enqueued): **31 drafts** — held for Stage B graduation.

---

## 2. Operational Cohort Composition

### 2.1 Selection Criteria Applied

1. Maximum 1 contact per company in the initial cohort
2. Prefer fresh drafts (under 14 days)
3. Step diversity (mix of step-1 and step-2)
4. All email addresses either verified, or catch_all/unverified with confirmed step-1 delivery
5. Varied industries — no two contacts from the same sector cluster
6. No contacts from companies with multiple eligible drafts where selecting both would create concentration

### 2.2 Cohort — Exact Draft IDs

| # | Draft ID | Contact | Company | Industry | Step | Age (days) | Email Status | Selection Basis |
|---|----------|---------|---------|----------|------|------------|-------------|-----------------|
| 1 | `8a1d3964-bf5e-42fd-a392-b2f28456cbde` | tzwiebel@rudolphfoods.com | Rudolph Foods | Food Manufacturing | 2 | 6 | unverified | INCLUDE-REVIEW; step-1 confirmed delivery validates address; Director QA — relevant buyer |
| 2 | `34b43c7d-f781-4f14-9275-a26e2f6351f9` | kathyw@gwfg.com | Golden West Food Group | Food Manufacturing | 2 | 9 | catch_all | INCLUDE-REVIEW; step-1 confirmed delivery; COO title |
| 3 | `73a58bef-6af3-41c1-89fe-6165cc646a46` | jgondkoff@upmet.com | United Performance Metals | Metals Distribution | 1 | 12 | catch_all | INCLUDE-REVIEW; GM title; bounded catch_all risk |
| 4 | `b6532bf5-946f-47ae-9d49-1f577bf8118d` | jmastrangelo@eosenergystorage.com | Eos Energy Enterprises | Energy Storage | 2 | 5 | verified | SAFE; freshest verified step-2; represents Eos Energy with 1 of 3 possible contacts |
| 5 | `b953d9bd-8dd1-4fa5-a4f2-f300ce771524` | tony.wade@pottersindustries.com | Potters Industries | Industrial Materials | 1 | 12 | verified | SAFE; clean verified step-1; single representative from 2-contact company |
| 6 | `aeebc0c9-c0f0-4c21-ac53-7a98878f497c` | ablount@globaladvancedmetals.com | Global Advanced Metals | Metals Processing | 1 | 12 | verified | SAFE; clean verified step-1; single representative from 2-contact company |
| 7 | `62396944-0a75-4ee3-9af1-557c4b8071a9` | nariens@ariensco.com | AriensCo | Outdoor Power Equipment | 1 | 12 | verified | SAFE; clean verified step-1; different step from AriensCo's step-2 draft |
| 8 | `4c7dbe6c-7c00-4370-8952-5e07fb2a6c05` | larryw@oildri.com | Oil-Dri Corporation of America | Specialty Minerals | 1 | 11 | verified | SAFE; clean verified step-1; sole contact from company |

**Workspace:** `00000000-0000-0000-0000-000000000001`  
**Priority:** all at default value `5`

---

## 3. Concentration Risk Analysis

### 3.1 Company Representation in Cohort

| Company | Cohort Contacts | Remaining Eligible (held) | Risk Level |
|---------|-----------------|--------------------------|------------|
| Rudolph Foods | 1 (tzwiebel, step-2) | 0 | NONE |
| Golden West Food Group | 1 (kathyw, step-2) | 0 | NONE |
| United Performance Metals | 1 (jgondkoff, step-1) | 1 (jlucas, step-2) held | LOW — different steps; jlucas held |
| Eos Energy Enterprises | 1 (jmastrangelo, step-2) | 2 (jgreggs, jmahaz) held | MANAGED — 2 of 3 contacts held back |
| Potters Industries | 1 (tony.wade, step-1) | 1 (joseph.mooney, step-1) held | MANAGED — companion held |
| Global Advanced Metals | 1 (ablount, step-1) | 1 (zijaz, step-1) held | MANAGED — companion held |
| AriensCo | 1 (nariens, step-1) | 1 (mscruggs, step-2) held | LOW — different steps |
| Oil-Dri Corporation | 1 (larryw, step-1) | 0 | NONE |

**No company has more than 1 contact in the initial cohort.** The Eos Energy, Potters, and Global Advanced Metals companies each have a second (or third) contact in the remaining eligible pool — all held for Stage B graduation.

### 3.2 Industry Concentration

| Industry Cluster | Contacts in Cohort |
|-----------------|--------------------|
| Food Manufacturing | 2 (Rudolph Foods, Golden West) |
| Metals | 2 (United Performance Metals, Global Advanced Metals) |
| Energy/Industrial | 2 (Eos Energy, Potters Industries) |
| Single-company (no cluster) | 2 (AriensCo, Oil-Dri) |

**Two-contact per sector maximum.** Not ideal, but the food cluster is explained by both being step-2 follow-ups (different companies, both included on REVIEW-INCLUDE basis). Domain reputation risk across two different companies in the same sector is negligible.

### 3.3 Batch-Window Dispatch Risk (for future reference)

When SEND_ENABLED is eventually set to true, `dispatch_loop` runs at :00 and :30 past each hour from 8-11 AM CT. `claim_outbound_queue_batch()` with default `batch_size=50` would claim all 8 rows in a single tick. This is acceptable for 8 drafts. No per-company guard exists in the RPC — all 8 could theoretically dispatch in the same 30-minute window.

**Recommendation before activation:** Set `outreach_send_config.batch_size = 1` for the first live dispatch event to enforce temporal separation. Increase batch_size gradually after the first successful send cycle.

---

## 4. Pre-Execution State Requirements

Before any write operation, confirm all invariants:

```sql
-- Run this block. All values must match exactly.
SELECT
  (SELECT COUNT(*) FROM outbound_queue)                             AS queue_rows,           -- must be 0
  (SELECT COUNT(*) FROM send_attempts)                              AS attempt_rows,         -- must be 0
  (SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL) AS locked_rows,          -- must be 0
  (SELECT send_enabled FROM outreach_send_config LIMIT 1)           AS db_send_enabled,      -- must be false
  (SELECT COUNT(*) FROM outreach_drafts
   WHERE approval_status IN ('approved','edited')
   AND sent_at IS NULL
   AND id NOT IN (SELECT draft_id FROM outbound_queue))             AS backfill_candidates,  -- must be 51
  (SELECT COUNT(*) FROM outreach_drafts
   WHERE approval_status = 'rejected'
   AND rejection_category IN ('hard_bounce','email_ineligible'))    AS pre_rejected_count;   -- must be 0 (rejections not yet run)
```

Expected result: `0 | 0 | 0 | false | 51 | 0`

---

## 5. Execution Sequence (Planning Only — No Writes Yet)

This section documents the exact sequence that will be executed when Avanish authorizes. No writes occur until Section 16 is signed.

### Step 1 — Execute 9 Pre-Rejections

Run the exact SQL from `BACKFILL_EXECUTION_PRECHECK_001.md` Section 2 verbatim. Do not modify.

**Expected result after Step 1:**
```sql
SELECT approval_status, COUNT(*)
FROM outreach_drafts
WHERE id IN (
  'd776e831-bc13-4651-ab74-b13dd214dfc7',
  '12be759c-9f1b-4dc7-9b18-adc10b846fa5',
  'b76e0d26-88d9-4db9-81bf-c24f51092043',
  '9292af08-25bc-4c40-814b-6ed40ab84b67',
  '5f0f6510-e480-4eed-abf0-ed8ca75482e5',
  '8f342cc1-a6aa-4926-9fb7-fcce2d5ea823',
  '82774bf8-167c-4041-9f59-5d49d7c39240',
  '79153776-e66e-470f-a287-a1a74733f998',
  '447c9f6f-fe76-47bc-809e-b89d8f52b304'
)
GROUP BY approval_status;
-- Must return: rejected | 9
```

### Step 2 — State Checkpoint After Pre-Rejections

```sql
SELECT
  (SELECT COUNT(*) FROM outreach_drafts
   WHERE approval_status IN ('approved','edited')
   AND sent_at IS NULL
   AND id NOT IN (SELECT draft_id FROM outbound_queue)) AS remaining_eligible,
  (SELECT COUNT(*) FROM outbound_queue)                 AS queue_rows,
  (SELECT COUNT(*) FROM send_attempts)                  AS attempt_rows;
-- Must return: 42 | 0 | 0
```

Confirm before proceeding to Step 3.

### Step 3 — 8-Draft Cohort Enqueue SQL

```sql
BEGIN;

-- ============================================================
-- PRE-ASSERTION: all 8 cohort drafts must be eligible
-- ============================================================
DO $$
DECLARE
  v_eligible INT;
  v_already_queued INT;
BEGIN
  SELECT COUNT(*) INTO v_eligible
  FROM outreach_drafts
  WHERE id IN (
    '8a1d3964-bf5e-42fd-a392-b2f28456cbde',
    '34b43c7d-f781-4f14-9275-a26e2f6351f9',
    '73a58bef-6af3-41c1-89fe-6165cc646a46',
    'b6532bf5-946f-47ae-9d49-1f577bf8118d',
    'b953d9bd-8dd1-4fa5-a4f2-f300ce771524',
    'aeebc0c9-c0f0-4c21-ac53-7a98878f497c',
    '62396944-0a75-4ee3-9af1-557c4b8071a9',
    '4c7dbe6c-7c00-4370-8952-5e07fb2a6c05'
  )
  AND approval_status IN ('approved', 'edited')
  AND sent_at IS NULL;

  SELECT COUNT(*) INTO v_already_queued
  FROM outbound_queue
  WHERE draft_id IN (
    '8a1d3964-bf5e-42fd-a392-b2f28456cbde',
    '34b43c7d-f781-4f14-9275-a26e2f6351f9',
    '73a58bef-6af3-41c1-89fe-6165cc646a46',
    'b6532bf5-946f-47ae-9d49-1f577bf8118d',
    'b953d9bd-8dd1-4fa5-a4f2-f300ce771524',
    'aeebc0c9-c0f0-4c21-ac53-7a98878f497c',
    '62396944-0a75-4ee3-9af1-557c4b8071a9',
    '4c7dbe6c-7c00-4370-8952-5e07fb2a6c05'
  );

  IF v_eligible <> 8 THEN
    RAISE EXCEPTION 'Pre-assertion failed: expected 8 eligible drafts, found %. '
      'Some may have been rejected or already sent.', v_eligible;
  END IF;

  IF v_already_queued > 0 THEN
    RAISE EXCEPTION 'Pre-assertion failed: % cohort draft(s) are already in outbound_queue. '
      'This enqueue has already run or a duplicate was inserted.', v_already_queued;
  END IF;
END $$;

-- ============================================================
-- COHORT ENQUEUE — 8 drafts, workspace 00000000-...-000001
-- Direct INSERT (drafts already approved; does not touch outreach_drafts)
-- ON CONFLICT (draft_id) DO NOTHING ensures idempotency
-- ============================================================
INSERT INTO outbound_queue (draft_id, workspace_id, priority)
VALUES
  -- 1. Rudolph Foods — step-2, 6d, unverified/step-1-confirmed
  ('8a1d3964-bf5e-42fd-a392-b2f28456cbde', '00000000-0000-0000-0000-000000000001', 5),
  -- 2. Golden West Food Group — step-2, 9d, catch_all/step-1-confirmed
  ('34b43c7d-f781-4f14-9275-a26e2f6351f9', '00000000-0000-0000-0000-000000000001', 5),
  -- 3. United Performance Metals — step-1, 12d, catch_all
  ('73a58bef-6af3-41c1-89fe-6165cc646a46', '00000000-0000-0000-0000-000000000001', 5),
  -- 4. Eos Energy Enterprises — step-2, 5d, verified (1 of 3 Eos contacts)
  ('b6532bf5-946f-47ae-9d49-1f577bf8118d', '00000000-0000-0000-0000-000000000001', 5),
  -- 5. Potters Industries — step-1, 12d, verified (1 of 2 Potters contacts)
  ('b953d9bd-8dd1-4fa5-a4f2-f300ce771524', '00000000-0000-0000-0000-000000000001', 5),
  -- 6. Global Advanced Metals — step-1, 12d, verified (1 of 2 GAM contacts)
  ('aeebc0c9-c0f0-4c21-ac53-7a98878f497c', '00000000-0000-0000-0000-000000000001', 5),
  -- 7. AriensCo — step-1, 12d, verified (different step from AriensCo's step-2)
  ('62396944-0a75-4ee3-9af1-557c4b8071a9', '00000000-0000-0000-0000-000000000001', 5),
  -- 8. Oil-Dri Corporation — step-1, 11d, verified (sole Oil-Dri contact)
  ('4c7dbe6c-7c00-4370-8952-5e07fb2a6c05', '00000000-0000-0000-0000-000000000001', 5)
ON CONFLICT (draft_id) DO NOTHING;

-- ============================================================
-- POST-ASSERTION: confirm exactly 8 rows inserted, all unlocked
-- ============================================================
DO $$
DECLARE
  v_count INT;
  v_locked INT;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM outbound_queue
  WHERE draft_id IN (
    '8a1d3964-bf5e-42fd-a392-b2f28456cbde',
    '34b43c7d-f781-4f14-9275-a26e2f6351f9',
    '73a58bef-6af3-41c1-89fe-6165cc646a46',
    'b6532bf5-946f-47ae-9d49-1f577bf8118d',
    'b953d9bd-8dd1-4fa5-a4f2-f300ce771524',
    'aeebc0c9-c0f0-4c21-ac53-7a98878f497c',
    '62396944-0a75-4ee3-9af1-557c4b8071a9',
    '4c7dbe6c-7c00-4370-8952-5e07fb2a6c05'
  );

  SELECT COUNT(*) INTO v_locked
  FROM outbound_queue
  WHERE draft_id IN (
    '8a1d3964-bf5e-42fd-a392-b2f28456cbde',
    '34b43c7d-f781-4f14-9275-a26e2f6351f9',
    '73a58bef-6af3-41c1-89fe-6165cc646a46',
    'b6532bf5-946f-47ae-9d49-1f577bf8118d',
    'b953d9bd-8dd1-4fa5-a4f2-f300ce771524',
    'aeebc0c9-c0f0-4c21-ac53-7a98878f497c',
    '62396944-0a75-4ee3-9af1-557c4b8071a9',
    '4c7dbe6c-7c00-4370-8952-5e07fb2a6c05'
  )
  AND locked_by IS NOT NULL;

  IF v_count <> 8 THEN
    RAISE EXCEPTION
      'Post-assertion failed: expected 8 queue rows, found %. Rolling back.', v_count;
  END IF;

  IF v_locked > 0 THEN
    RAISE EXCEPTION
      'Post-assertion failed: % row(s) are locked immediately after insert. '
      'This should not be possible without a concurrent dispatcher. Investigate.', v_locked;
  END IF;
END $$;

COMMIT;
```

### Step 4 — Post-Enqueue Verification

Run immediately after COMMIT:

```sql
-- Core counts
SELECT
  (SELECT COUNT(*) FROM outbound_queue)                             AS queue_total,      -- must be 8
  (SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL) AS locked_count,     -- must be 0
  (SELECT COUNT(*) FROM outbound_queue WHERE retry_count > 0)       AS retried_count,    -- must be 0
  (SELECT COUNT(*) FROM send_attempts)                              AS send_attempts,    -- must be 0
  (SELECT COUNT(*) FROM outreach_drafts
   WHERE id IN (SELECT draft_id FROM outbound_queue)
   AND sent_at IS NOT NULL)                                         AS already_sent;     -- must be 0

-- Priority ordering (must match: all priority=5, ordered by enqueued_at)
SELECT oq.id, od.contact_id, oq.priority, oq.enqueued_at, oq.locked_by, oq.retry_count
FROM outbound_queue oq
JOIN outreach_drafts od ON od.id = oq.draft_id
ORDER BY oq.priority ASC, oq.enqueued_at ASC;
-- Expected: 8 rows, all priority=5, locked_by=NULL, retry_count=0

-- Draft status unchanged (enqueue must not have modified approval_status)
SELECT od.id, od.approval_status, od.sent_at
FROM outreach_drafts od
WHERE od.id IN (SELECT draft_id FROM outbound_queue);
-- Expected: all approval_status = 'approved', all sent_at = NULL
```

---

## 6. Expected Queue State

### Before Enqueue
```
outbound_queue: 0 rows
send_attempts:  0 rows
outreach_drafts approval_status: 51 'approved', 0 'rejected' (pre-rejections not yet run)
```

### After Pre-Rejections (Step 1) — Drafts Only, Queue Unchanged
```
outbound_queue: 0 rows
send_attempts:  0 rows
outreach_drafts approval_status: 42 'approved', 9 'rejected'
```

### After 8-Draft Cohort Enqueue (Step 3)
```
outbound_queue: 8 rows
  - all locked_by = NULL
  - all locked_at = NULL
  - all retry_count = 0
  - all next_retry_at = NULL
  - all priority = 5
  - enqueued_at = now() for each row
send_attempts:  0 rows
outreach_drafts: approval_status unchanged (enqueue is INSERT-only, no UPDATE to drafts)
```

### Expected State After N Scheduler Ticks (SEND_ENABLED=false)
```
outbound_queue: 8 rows — UNCHANGED across all ticks
  - locked_by: NULL for all (dispatch_loop returns before calling claim_outbound_queue_batch)
  - retry_count: 0 for all
  - next_retry_at: NULL for all
send_attempts:  0 rows — UNCHANGED
outreach_drafts sent_at: NULL for all cohort drafts — UNCHANGED
```

The population of the queue must have zero effect on the inert state of dispatch and send behavior as long as SEND_ENABLED=false.

---

## 7. Expected Scheduler Behavior (SEND_ENABLED=false, Non-Empty Queue)

### 7.1 dispatch_loop (cron: Mon-Fri 8-11 AM CT, :00 and :30)

The `_dispatch_workspace()` function contains:
```python
if not get_settings().send_enabled:
    return
```

This check fires BEFORE any call to `claim_outbound_queue_batch()`. With SEND_ENABLED=false:

- The scheduler fires the job at each cron tick
- `for_each_workspace()` iterates and calls `_dispatch_workspace()`
- `_dispatch_workspace()` reads `get_settings().send_enabled` → false → returns immediately
- `claim_outbound_queue_batch()` is NEVER called
- No rows in `outbound_queue` are touched
- No `send_attempts` rows are created
- No Resend API calls occur
- The job completes in microseconds

**Key validation:** This behavior must be identical whether `outbound_queue` has 0 rows or 8 rows. The early return occurs before any database interaction. The populated queue is completely invisible to the dispatch path.

### 7.2 reclaim_stale_locks (interval: every 2 minutes)

`reclaim_stale_locks()` runs the UPDATE:
```sql
UPDATE outbound_queue SET locked_by = NULL, locked_at = NULL
WHERE locked_at < NOW() - INTERVAL '5 minutes'
```

With freshly inserted rows where `locked_by IS NULL` and `locked_at IS NULL`:
- The WHERE clause requires `locked_at < ...` — NULL does not satisfy this predicate
- Returns 0 rows affected
- No logging (log only emits when count > 0)
- Clean, silent, zero-side-effect

**Important distinction:** `reclaim_stale_locks` will remain silent until a row has a non-NULL `locked_at` that ages past 5 minutes. In dark-launch mode with SEND_ENABLED=false, `locked_at` is never set, so this job remains permanently silent with the current cohort.

### 7.3 send_approved (cron: Mon-Fri 8-11 AM CT, :00 and :30 — legacy path)

The `_send_approved_workspace()` function calls `EngagementAgent.run()`, which calls `_load_send_config()` which reads `outreach_send_config.send_enabled` from the DB. DB `send_enabled = false` → EngagementAgent returns without sending.

**This is independent of SEND_ENABLED env var.** The legacy path is blocked by the DB flag, not the env flag.

Both paths will remain inert as long as:
- `SEND_ENABLED` (env) = false → blocks dispatch_loop
- `outreach_send_config.send_enabled` (DB) = false → blocks send_approved

---

## 8. Observation Protocol

### 8.1 Minimum Observation Window

**Minimum:** 48 hours from enqueue execution.  
**Rationale:** This covers at least 2 full Mon-Fri send-window cycles (7 cron ticks per day × 2 days = 14 dispatch_loop invocations) and 1,440 reclaim_stale_locks ticks.

**Preferred:** 72 hours (Friday through Monday) to include a weekend-idle validation and confirm no scheduler drift across a long non-window period.

**Observation checkpoints:**
- T+2 min: first reclaim_stale_locks tick with non-empty queue
- T+next send window tick: first dispatch_loop invocation with non-empty queue
- T+24 hours: full send-window cycle check
- T+48 hours: minimum evidence threshold

### 8.2 Primary Invariant Queries

Run at each checkpoint:

```sql
-- Invariant 1: Queue rows unchanged — no claims, no locks
SELECT
  COUNT(*)                             AS total_rows,        -- must stay at 8
  COUNT(*) FILTER (WHERE locked_by IS NOT NULL) AS locked,   -- must stay at 0
  COUNT(*) FILTER (WHERE retry_count > 0)       AS retried,  -- must stay at 0
  COUNT(*) FILTER (WHERE next_retry_at IS NOT NULL) AS has_retry  -- must stay at 0
FROM outbound_queue;

-- Invariant 2: No send attempts
SELECT COUNT(*) FROM send_attempts;  -- must stay at 0

-- Invariant 3: No drafts sent
SELECT COUNT(*) FROM outreach_drafts
WHERE id IN (SELECT draft_id FROM outbound_queue)
AND sent_at IS NOT NULL;  -- must stay at 0

-- Invariant 4: DB send gate still closed
SELECT send_enabled, batch_size, max_retries FROM outreach_send_config;
-- send_enabled must be false
```

### 8.3 Railway Log Signatures

With SEND_ENABLED=false and a populated queue, the following Railway log pattern is expected (and its absence is also significant):

**Expected to appear (normal):**
```
[scheduler] dispatch_loop fired
[scheduler] reclaim_stale_locks fired
[health] GET /health 200
```

**Expected to NOT appear (absence confirms inert state):**
```
claim_outbound_queue_batch          -- must NEVER appear in logs while SEND_ENABLED=false
dispatch: claiming batch            -- must NEVER appear
Sending email to                    -- must NEVER appear
resend:                             -- must NEVER appear
send_attempt created                -- must NEVER appear
locked_by=                          -- must NEVER appear in queue-related context
```

**If any of the "must NEVER appear" strings appear in Railway logs before SEND_ENABLED has been deliberately set to true: this is an ABORT condition. Stop all execution and investigate immediately.**

To inspect logs: Railway dashboard → ProspectIQ → production service → Logs tab. Filter by time window around each cron tick (Mon-Fri 8-11 AM CT).

### 8.4 Stale Lock Observation Queries

Run after each reclaim_stale_locks tick (every 2 minutes):

```sql
-- Should return 0 rows in dark-launch (nothing is ever locked)
SELECT id, draft_id, locked_by, locked_at,
       NOW() - locked_at AS lock_age
FROM outbound_queue
WHERE locked_by IS NOT NULL;

-- Historical check: have any rows ever been locked?
-- (All locked_at must be NULL in dark-launch)
SELECT COUNT(*) FROM outbound_queue WHERE locked_at IS NOT NULL;
-- Must be 0 throughout the observation window

-- Stale lock threshold check (for when dispatch is eventually active)
SELECT COUNT(*) FROM outbound_queue
WHERE locked_at < NOW() - INTERVAL '5 minutes';
-- Must be 0 throughout dark-launch
```

### 8.5 Duplicate-Claim Detection Queries

In dark-launch (SEND_ENABLED=false), no claims occur. These queries validate that no claim has leaked through:

```sql
-- No row should ever have a non-null locked_by in dark-launch
SELECT draft_id, locked_by, locked_at
FROM outbound_queue
WHERE locked_by IS NOT NULL;
-- Expected: 0 rows

-- No send_attempt should exist for any cohort draft
SELECT sa.*
FROM send_attempts sa
JOIN outbound_queue oq ON oq.draft_id = sa.draft_id
LIMIT 10;
-- Expected: 0 rows

-- No duplicate queue rows (ON CONFLICT guard ensures uniqueness by draft_id)
SELECT draft_id, COUNT(*) AS count
FROM outbound_queue
GROUP BY draft_id
HAVING COUNT(*) > 1;
-- Expected: 0 rows
```

### 8.6 Send Attempt Invariant Checks

```sql
-- Full send_attempts scan — must remain empty throughout observation window
SELECT status, COUNT(*)
FROM send_attempts
GROUP BY status;
-- Expected: 0 rows total

-- Resend message ID leakage check
SELECT COUNT(*) FROM outreach_drafts
WHERE resend_message_id IS NOT NULL
AND id IN (SELECT draft_id FROM outbound_queue);
-- Expected: 0 (no Resend API calls have been made for cohort drafts)

-- sent_at leakage check
SELECT COUNT(*) FROM outreach_drafts
WHERE sent_at IS NOT NULL
AND id IN (SELECT draft_id FROM outbound_queue);
-- Expected: 0
```

---

## 9. Risk Analysis

### 9.1 Dual Send Path Risk

**Description:** Two scheduler jobs fire on the same cron window (Mon-Fri 8-11 AM CT):
- `send_approved` (legacy): checks DB `send_enabled` → calls `EngagementAgent.run()`
- `dispatch_loop` (queue): checks env `SEND_ENABLED` → calls `claim_outbound_queue_batch()`

**Current state (SEND_ENABLED=false, DB send_enabled=false):**
Both paths are independently blocked. No race condition is possible.

**Risk at activation:** If both paths are active simultaneously when SEND_ENABLED is flipped:
- `dispatch_loop` claims a queue row and dispatches via Resend
- `send_approved` may simultaneously select the same draft via `EngagementAgent._dispatch_draft()`
- `send_approved` does not check `outbound_queue` — it queries `outreach_drafts` directly
- Result: the same email could be sent twice from two different dispatcher instances

**Severity:** HIGH — duplicate send to a real prospect.

**Mitigation (required before any activation):** `send_approved` must be disabled (commented out in main.py scheduler registration) BEFORE `SEND_ENABLED` is set to true. The two paths must never be simultaneously active. This is the core condition in Section 14 (Legacy Send Path Retirement).

**Detection query:**
```sql
-- If this ever returns > 0 rows with 2 distinct resend_message_ids for the same draft: duplicate send occurred
SELECT draft_id, COUNT(DISTINCT resend_message_id) AS message_count
FROM send_attempts
WHERE resend_message_id IS NOT NULL
GROUP BY draft_id
HAVING COUNT(DISTINCT resend_message_id) > 1;
```

### 9.2 Stale Lock Reclaim Edge Cases

**Case A: reclaim fires while dispatch is mid-batch claim**

`claim_outbound_queue_batch()` uses `FOR UPDATE SKIP LOCKED`. If reclaim runs concurrently with a dispatch batch claim:
- Dispatch holds a row-level lock during the UPDATE
- reclaim's UPDATE WHERE locked_at < NOW() - 5 minutes evaluates the locked_at after the lock is acquired
- A freshly-locked row has locked_at = NOW() — the WHERE predicate returns false for fresh locks
- No reclaim interference with a running dispatch

**Risk:** NONE in current design. The 5-minute threshold means reclaim only targets rows that have been locked for over 5 minutes — not freshly claimed rows.

**Case B: dispatcher crashes after claiming but before completing send**

If the dispatcher crashes after `claim_outbound_queue_batch()` but before updating `send_attempts`:
- The row remains locked with a non-null `locked_at`
- After 5 minutes, `reclaim_stale_locks` sets `locked_by = NULL`, `locked_at = NULL`
- The row becomes eligible for claim again
- Next dispatch tick claims it and retries

**Risk:** ACCEPTABLE — this is exactly the design intent. No send occurred before the crash, so re-dispatch is safe.

**Case C: dispatcher sends but crashes before writing send_attempt**

If the Resend API call succeeds but the process crashes before the `INSERT INTO send_attempts` completes:
- The row remains locked
- After 5 minutes, reclaim releases it
- The row is claimed again and a second Resend API call is made
- Result: duplicate send

**Risk:** REAL but LOW probability in single-instance Railway deployment. This is a gap in the current design. Mitigations: use Resend idempotency keys in the dispatch call (not currently implemented); add resend_message_id check before dispatch; detect via Resend API list call.

**Detection:** This scenario would manifest as two `send_attempts` rows for the same `draft_id` and two Resend events for the same contact in the same window.

### 9.3 Queue Starvation Scenarios

**Scenario A: all rows locked and locks expire simultaneously**

With 8 rows all claimed in the same batch (same `locked_by`, same `locked_at`), and the dispatcher process crashes: all 8 locks expire at the same time. Next reclaim releases all 8. Next dispatch tick claims all 8 again. No starvation.

**Scenario B: rows with future `next_retry_at`**

`claim_outbound_queue_batch()` filters: `next_retry_at IS NULL OR next_retry_at <= NOW()`. If a row has a future `next_retry_at` (set after a failed send attempt), it is invisible to the claim query until that time arrives.

In dark-launch, no rows have `next_retry_at` set (retry count = 0, never failed). No starvation risk.

**Scenario C: single-instance dispatcher with large queue**

With one Railway instance and the default `batch_size=50`, the dispatcher processes at most 50 rows per tick. With 39 total eligible drafts, all can be claimed in a single tick when enabled. No starvation with current queue depth.

**Scenario D: clock drift between Railway and Supabase**

`claim_outbound_queue_batch()` uses `NOW()` (PostgreSQL server time) for both `locked_at` and the `next_retry_at` comparison. `reclaim_stale_locks` also uses `NOW()`. Both are evaluated on the Supabase server. No Railway clock drift affects the lock lifecycle.

### 9.4 Scheduler Restart Behavior

APScheduler `BackgroundScheduler` runs in a daemon thread. If the Railway service restarts:
- The scheduler is fully re-initialized in the lifespan startup
- All jobs are re-registered with the same schedules
- Any in-flight job is abandoned (no state persisted by APScheduler)
- Queue rows that were locked at restart time may have orphaned locks

**Lock orphan scenario at restart:**
1. Dispatch claims batch (rows locked, locked_at = T)
2. Railway service restarts before send completes
3. Rows remain locked, locked_at = T
4. reclaim_stale_locks re-initializes after restart and runs every 2 minutes
5. After `T + 5 minutes`, reclaim releases the orphaned locks
6. Next dispatch tick reclaims

**Risk:** LOW. The 5-minute lock timeout handles restart-induced orphans. No sends are lost; they are retried after lock expiry.

**Observation during dark-launch:** Confirm that any service restart event (visible in Railway dashboard) does not result in locked rows in the queue. With SEND_ENABLED=false, no rows are ever locked, so any restart is invisible to the queue.

### 9.5 APScheduler Drift

APScheduler `BackgroundScheduler` uses Python's threading timer for interval jobs. Under sustained high CPU load, interval jobs can fire late (positive drift). Under Railway's single-process deployment:

- `reclaim_stale_locks` (every 2 minutes): drift of ±10 seconds is expected and acceptable. A 2-minute job drifting 10 seconds does not affect correctness — only timing.
- `dispatch_loop` (cron): APScheduler uses the cron trigger against wall-clock time with the configured timezone. Cron triggers are not subject to accumulated drift because they target absolute times, not relative offsets.

**Drift impact on lock lifecycle:** If reclaim_stale_locks drifts and runs at T+2m10s instead of T+2m, a lock aged at exactly 5 minutes could be missed by one tick (cleared at next tick, T+4m20s). Maximum orphan lock duration: `5 min + max_interval_drift`. At typical Railway CPU load, drift is under 30 seconds.

**No action required during dark-launch.** If drift becomes significant (reclaim ticks visible in logs more than 60 seconds apart), investigate Railway CPU allocation.

### 9.6 Supabase Connection Saturation Under Populated Queue

**Current pool behavior:**
- Supabase uses PgBouncer in transaction mode
- PostgREST opens one connection per request, returned after response
- With SEND_ENABLED=false: dispatch_loop makes 0 PostgREST calls per tick
- reclaim_stale_locks makes 1 PostgREST call per 2-minute tick (UPDATE returning 0 rows)

**Effect of populating queue:**
- Queue population (8-draft INSERT): 1 PostgREST call per transaction
- Subsequent reclaim_stale_locks: still 1 call per 2 minutes (finds 0 rows to release)
- No change in connection pool pressure from population alone

**When dispatch is eventually enabled:**
- Each dispatch tick: 1 call to `claim_outbound_queue_batch()` + N calls to Resend + N calls to insert `send_attempts`
- With batch_size=1 (recommended for first activation), that is 3 PostgREST calls per tick
- With batch_size=8 (full cohort), that is approximately 1 + 8 + 8 = 17 PostgREST calls per tick
- Supabase PgBouncer default pool has 80 connections available; dispatch pressure is negligible

**Connection saturation risk:** LOW at current queue depth and send volume. Would only become a concern above ~500 concurrent send attempts.

**Monitoring:** Supabase dashboard → Database → Reports → Connections to observe pool utilization.

---

## 10. Abort Criteria

Stop all work and do not proceed with any further enqueue or activation if any of the following conditions are observed at any time during the observation window:

| # | Condition | Action |
|---|-----------|--------|
| A1 | `send_attempts` row count > 0 | IMMEDIATE STOP — a send was triggered unexpectedly. Execute Section 12 Emergency Freeze. |
| A2 | Any outreach_drafts row in cohort has `sent_at IS NOT NULL` | IMMEDIATE STOP — a send was dispatched. Execute Section 12 Emergency Freeze. |
| A3 | Any `outbound_queue` row has `locked_by IS NOT NULL` while SEND_ENABLED=false | IMMEDIATE STOP — claim_outbound_queue_batch ran unexpectedly. Investigate SEND_ENABLED state. |
| A4 | `outbound_queue` row count changes without an authorized operation | IMMEDIATE STOP — unexpected write to queue. Audit workflow_events and application logs. |
| A5 | Railway logs contain `claim_outbound_queue_batch` or `Sending email to` | IMMEDIATE STOP — dispatch path activated unexpectedly. |
| A6 | `env_send_enabled: true` returned from `/api/admin/send-config` | IMMEDIATE STOP — SEND_ENABLED was changed. Revert Railway env immediately. |
| A7 | Service crash + restart loop (health endpoint non-responsive or Railway shows restart) | STOP enqueue. Investigate root cause before proceeding. |
| A8 | Supabase connection errors appearing in Railway logs at high frequency | STOP. Investigate connection pool pressure before proceeding. |

---

## 11. Rollback Procedure

If any abort condition triggers, or if a post-enqueue verification step fails:

```sql
-- Emergency queue purge — removes all rows from outbound_queue and send_attempts
-- Does NOT modify outreach_drafts (pre-rejections remain rejected; queue rows are removed)
-- Re-running the Step 3 enqueue SQL after rollback is safe (ON CONFLICT DO NOTHING)

BEGIN;

DELETE FROM send_attempts;   -- clear all attempt records (should be 0 in dark-launch)
DELETE FROM outbound_queue;  -- clear all queue rows

-- Verify rollback
DO $$
DECLARE
  v_q INT;
  v_s INT;
BEGIN
  SELECT COUNT(*) INTO v_q FROM outbound_queue;
  SELECT COUNT(*) INTO v_s FROM send_attempts;
  IF v_q <> 0 OR v_s <> 0 THEN
    RAISE EXCEPTION 'Rollback verification failed: outbound_queue=%, send_attempts=%', v_q, v_s;
  END IF;
END $$;

COMMIT;
```

Post-rollback state:
```sql
SELECT COUNT(*) FROM outbound_queue;   -- must be 0
SELECT COUNT(*) FROM send_attempts;    -- must be 0
-- outreach_drafts are NOT affected by this rollback
-- The 9 pre-rejections (approval_status='rejected') persist — this is correct
```

---

## 12. Global Emergency Freeze Procedure

Execute this procedure if sends must be stopped immediately for any reason — unexpected dispatch, wrong recipient, webhook failure, bounce spike, or any unintended outbound activity.

**Estimated time to full freeze: under 3 minutes.**

### Step 1 — Environment-Level Kill (Railway dashboard)

1. Open Railway dashboard → ProspectIQ project → production environment → Variables tab
2. Set `SEND_ENABLED` = `false` (if it was set to true during activation)
3. Railway propagates the env var change without requiring a redeploy (Railway injected env vars are read at runtime via `get_settings()`)
4. Verify: `curl https://prospectiq-production-4848.up.railway.app/api/admin/send-config`
   → `env_send_enabled` must be `false`

**Effect:** On the next dispatch_loop tick, `_dispatch_workspace()` returns immediately. No new claims are made. In-flight dispatches that have already called `claim_outbound_queue_batch()` will continue to completion (cannot be interrupted mid-Resend call), but no new batches start.

### Step 2 — DB-Level Freeze

```sql
BEGIN;

UPDATE outreach_send_config
SET send_enabled = false, updated_at = NOW()
WHERE send_enabled = true;

-- Verify
SELECT send_enabled FROM outreach_send_config;
-- Must be false

COMMIT;
```

**Effect:** Blocks the legacy `send_approved` path at the EngagementAgent DB check level. Defense-in-depth regardless of env var state.

### Step 3 — Queue Purge (if sending must stop permanently for these cohort drafts)

Only run this step if the decision is to discard the queue contents, not just pause dispatch:

```sql
BEGIN;
DELETE FROM outbound_queue WHERE locked_by IS NULL;
-- Leaves locked rows (currently in-flight dispatches) in place
-- to avoid orphaning send_attempts records

-- If a full nuclear purge is needed (accepts potential orphan):
-- DELETE FROM outbound_queue;
-- DELETE FROM send_attempts WHERE status NOT IN ('DELIVERED');

COMMIT;
```

### Step 4 — Retry Suppression

If sends have begun and failed dispatches are retrying:

```sql
-- Set next_retry_at far in the future for all eligible rows
-- (prevents automatic retry without manual operator release)
BEGIN;

UPDATE outbound_queue
SET next_retry_at = NOW() + INTERVAL '30 days'
WHERE locked_by IS NULL
  AND (next_retry_at IS NULL OR next_retry_at <= NOW());

COMMIT;
```

To release the suppression when ready to resume:

```sql
UPDATE outbound_queue
SET next_retry_at = NULL
WHERE next_retry_at > NOW();
```

### Step 5 — reclaim_stale_locks Containment

`reclaim_stale_locks` runs every 2 minutes and cannot be stopped without a deployment. Its only action is releasing orphaned locks. During a freeze, this behavior is benign — releasing an orphaned lock does not cause a send; it only re-enables re-claim on the next dispatch tick. As long as Step 1 (SEND_ENABLED=false) and Step 3 (queue purge) are complete, reclaim has no effect.

If you need to prevent ANY queue interaction (e.g., for a forensic investigation), the only option is to stop the Railway service entirely via the dashboard.

### Step 6 — Scheduler Disable

To disable the scheduler completely without a code deployment:

Stop the Railway service from the dashboard → service settings → Stop service.

**Warning:** This also stops all other scheduler jobs (health_snapshot, pipeline_qc, gmail_intake, etc.). Use only if the situation requires complete process termination.

**Alternative (preferred):** Leave the service running with SEND_ENABLED=false (Step 1). The scheduler continues running non-send jobs; only dispatch is blocked.

### Step 7 — Recovery and Restart Procedure

After the emergency is resolved and the root cause is confirmed:

1. Confirm SEND_ENABLED=false in Railway env (Step 1)
2. Confirm DB send_enabled=false (Step 2)
3. Run queue state audit:

```sql
SELECT locked_by, locked_at, retry_count, next_retry_at, COUNT(*)
FROM outbound_queue
GROUP BY locked_by, locked_at, retry_count, next_retry_at;
```

4. Release any orphaned locks if present:

```sql
UPDATE outbound_queue
SET locked_by = NULL, locked_at = NULL
WHERE locked_at < NOW() - INTERVAL '1 minute';
```

5. Clear retry suppression if Step 4 was applied:

```sql
UPDATE outbound_queue SET next_retry_at = NULL WHERE next_retry_at > NOW();
```

6. Run the full invariant check from Section 8.2 before resuming.

7. Document the incident in a new operational observation document before re-enabling sends.

### Step 8 — Freeze State Verification Queries

```sql
-- Complete freeze confirmation — all must pass
SELECT
  (SELECT send_enabled FROM outreach_send_config LIMIT 1) AS db_send_enabled,           -- must be false
  (SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL) AS locked_rows,     -- must be 0 (after release)
  (SELECT COUNT(*) FROM send_attempts WHERE status = 'DISPATCHED') AS in_flight,        -- should be 0 after freeze
  (SELECT COUNT(*) FROM outreach_drafts
   WHERE sent_at > NOW() - INTERVAL '1 hour') AS sent_last_hour;                        -- 0 if freeze before sends
```

Confirm `/api/admin/send-config` returns `env_send_enabled: false` before declaring freeze complete.

---

## 13. Legacy Send Path Retirement Readiness

### 13.1 What Must Be True Before Disabling send_approved

The `send_approved` scheduler job (`_run_send_approved()` → `EngagementAgent.run()`) is the legacy send path that predates the queue architecture. It must be disabled before `dispatch_loop` is activated. These are the required proof conditions:

| Condition | How to Verify | Not Yet Met |
|-----------|---------------|-------------|
| 1. dispatch_loop has run cleanly through at least 3 consecutive send-window days | Observation 002 evidence capture | Yes — pending this observation |
| 2. Queue population event has completed with correct rows and no data anomalies | Step 4 verification passed | Yes — pending enqueue |
| 3. reclaim_stale_locks has never triggered unexpectedly | Observation 002 lock audit | Yes — pending observation |
| 4. No duplicate-claim events in any prior window | Duplicate-claim detection queries: 0 rows | Yes — pending observation |
| 5. send_approved has not produced any sends during the observation window (DB gated) | sent_at unchanged for all drafts | Yes — ongoing |
| 6. dispatch_loop abort behavior under SEND_ENABLED=false is confirmed over multiple ticks | Observation 002 log evidence | Yes — pending observation |
| 7. Emergency Freeze procedure has been dry-run reviewed by Avanish | This section reviewed | Not yet confirmed |

### 13.2 Proof Required — dispatch_loop Stability

Before retiring send_approved, the following evidence must exist in writing (Observation 003 or later):

1. At least 1 full live dispatch event: batch claimed → Resend API call → send_attempt DISPATCHED → webhook received → send_attempt updated to DELIVERED
2. At least 1 retry cycle: send_attempt FAILED → next_retry_at set → retry claimed → delivery attempt
3. At least 1 stale lock release: row locked → scheduler restart or timeout → reclaim fires → lock released → re-claim succeeds
4. Resend delivery webhook correctly updates send_attempt status (requires webhook handler — not yet implemented)

None of these proofs can be established in dark-launch mode. They require at least one live dispatch cycle.

### 13.3 Proof Required — No Duplicate-Send Race

Before retiring send_approved, confirm:

```sql
-- Must return 0 rows after any dispatch window
SELECT od.id, od.sent_at, sa.resend_message_id, COUNT(*) AS count
FROM outreach_drafts od
JOIN send_attempts sa ON sa.draft_id = od.id
GROUP BY od.id, od.sent_at, sa.resend_message_id
HAVING COUNT(*) > 1;
-- 0 rows = no duplicates

-- Must return no drafts that were sent by BOTH paths
-- (send_approved sets sent_at directly; dispatch path sets via send_attempts + webhook)
SELECT od.id
FROM outreach_drafts od
JOIN send_attempts sa ON sa.draft_id = od.id
WHERE od.sent_at IS NOT NULL
AND sa.status = 'DELIVERED';
-- These should be the same events, not duplicates
```

### 13.4 Migration Path to Queue-Only Execution

**Sequence (to be executed at activation time, not now):**

1. Confirm all retirement conditions in Section 13.1 are met
2. Set `SEND_ENABLED=false` in Railway env (freeze state)
3. Deploy code change: comment out `send_approved` scheduler registration in `main.py`
4. Verify deployment SHA in Railway dashboard
5. Confirm service restart completed: health endpoint responds
6. Confirm `send_approved` no longer appears in scheduler job list (via logs or APScheduler debug endpoint if available)
7. Verify DB `send_enabled=false` is still in place
8. Verify `SEND_ENABLED=false` in Railway env
9. Authorize send activation: set DB `send_enabled=true`, then set `SEND_ENABLED=true` in Railway env
10. Monitor first dispatch window (30 minutes minimum)

**Code change (step 3):**

In `backend/app/api/main.py`, locate the `send_approved` scheduler registration line and comment it out:

```python
# RETIRED: legacy send path replaced by dispatch_loop (queue architecture)
# Disabled after Observation 002 conditions confirmed — see DARK_LAUNCH_RUNTIME_OBSERVATION_002.md
# scheduler.add_job(_run_send_approved, ...)
```

This requires a PR, review, and production deployment. It is not a hotfix.

### 13.5 Rollback Plan if Queue-Only Execution Fails

If `dispatch_loop` fails after `send_approved` is retired (e.g., claim RPC errors, Resend failures, webhook handler not working):

**Immediate mitigation (no deployment needed):**
- Set `SEND_ENABLED=false` — stops dispatch_loop claims
- No sends in flight, no data loss

**Full rollback (requires deployment):**
- Revert the code change from step 3 of Section 13.4 (un-comment `send_approved`)
- Deploy
- Verify `send_approved` is active
- Set DB `send_enabled=true` to re-enable the legacy path
- This re-enables send_approved but dispatch_loop remains active (and gated by SEND_ENABLED=false)
- Disable dispatch_loop next (requires another deployment)

**Important:** Rolling back to legacy-only sends is safe because send_approved and dispatch_loop queue different drafts — `send_approved` reads `outreach_drafts` directly, not `outbound_queue`. However, any drafts that were dispatched via the queue path and reached DELIVERED state must have their `outreach_drafts.sent_at` manually updated (or the webhook handler must be functional) to prevent re-send by the legacy path.

---

## 14. Risk Summary

| Risk | Severity | Probability (dark-launch) | Mitigation |
|------|----------|--------------------------|------------|
| Duplicate send (dual-path race) | HIGH | ZERO (both paths blocked) | Retire send_approved before activation |
| Unexpected dispatch (SEND_ENABLED flipped) | HIGH | LOW | Env var audit in Section 8.2 every checkpoint |
| Stale lock orphan (restart mid-dispatch) | LOW | N/A in dark-launch | 5-min reclaim TTL handles it |
| Queue starvation (next_retry_at future) | LOW | N/A in dark-launch | Only affects post-activation |
| APScheduler drift | LOW | LOW | Non-critical in dark-launch |
| Supabase connection saturation | LOW | NONE at current volume | Watch at 50+ concurrent sends |
| Crash-after-send before send_attempt written | MEDIUM | LOW | Resend idempotency key (not yet implemented — PR required) |

---

## 15. Recommendations

### 15.1 Minimum Dark-Launch Observation Window

**Minimum:** 48 hours covering at least 2 Mon-Fri send-window cycles.  
**Recommended:** 72 hours from enqueue execution.  
**Condition to extend:** If any anomaly is detected (Section 10 abort criteria), restart the observation clock from zero.

### 15.2 Minimum Evidence Required Before First Controlled Live Send

The following evidence artifacts must exist before any activation is authorized:

1. Section 8.2 invariant queries: zero deviations across all checkpoints
2. Railway log review: zero "must NEVER appear" strings in any log window
3. Stale lock queries: zero locked rows at every checkpoint
4. Duplicate-claim queries: zero results
5. send_attempts count: zero throughout
6. reclaim_stale_locks: confirmed running every ~2 minutes (visible in Railway logs or absence-of-error confirmation)
7. Health endpoint: continuously responding throughout observation window
8. No Railway service restarts during the observation window (check Railway deployment/restart history)
9. Operator confirmation that SEND_ENABLED=false was not accidentally set to true at any point

Additionally (before activation but not before observation):
10. Resend webhook handler implemented and tested
11. send_approved retirement confirmed (Section 13)
12. batch_size set to 1 in outreach_send_config (confirmed before activation)
13. Internal activation cohort defined (own addresses / sink addresses) for first live send validation

### 15.3 Graduation Criteria: Initial Cohort to Full SAFE Cohort

Graduation from the 8-draft initial cohort to the full 39-draft SAFE pool requires:

| Criterion | Evidence Required |
|-----------|------------------|
| G1: Initial cohort dark-launch observation passed cleanly | Observation 002 evidence checklist complete |
| G2: First live send cycle completed with initial cohort | At least 1 DELIVERED send_attempt from the 8-draft cohort |
| G3: No bounces in the initial cohort | 0 hard_bounce entries in suppression_log for cohort contacts post-send |
| G4: Webhook handler confirmed operational | At least 1 send_attempt updated from DISPATCHED to DELIVERED via webhook |
| G5: Queue drain behavior confirmed | Queue row count decreases correctly as drafts are sent and sent_at is set |
| G6: No duplicate send events | Duplicate-send detection query returns 0 rows |
| G7: Avanish explicit authorization | Written approval in the next operational observation document |

Only after all 7 criteria are confirmed should the remaining 31 drafts be enqueued.

---

## 16. Evidence Capture Checklist

Complete at each checkpoint (T+2min, T+send window, T+24h, T+48h):

```
Checkpoint: _________________ (date, time CDT)
Executed by: Avanish Mehrotra

[ ] Invariant 1: outbound_queue total = 8 (or expected count if partial rollback)
[ ] Invariant 1: locked = 0
[ ] Invariant 1: retried = 0
[ ] Invariant 1: has_retry = 0
[ ] Invariant 2: send_attempts = 0
[ ] Invariant 3: cohort drafts with sent_at = 0
[ ] Invariant 4: DB send_enabled = false
[ ] Stale lock query: 0 rows returned
[ ] Duplicate-claim query: 0 rows returned
[ ] send_attempt invariant: 0 rows
[ ] Railway logs reviewed for this window: no abort-condition strings found
[ ] /api/admin/send-config confirms env_send_enabled = false
[ ] Health endpoint: responding ("status":"ok")

Notes / anomalies: _______________________________________________
```

---

## 17. Operator Sign-Off

This document is reviewed and all execution conditions are confirmed. Execution of Steps 1–4 in Section 5 is authorized.

```
[ ] Section 1: REVIEW decisions accepted as recorded
[ ] Section 2: 8-draft cohort composition reviewed and approved
[ ] Section 3: Concentration risk analysis reviewed — acceptable
[ ] Section 4: Pre-execution invariants will be confirmed before Step 1
[ ] Section 5: Execution sequence reviewed — run in order, verify at each step
[ ] Section 10: Abort criteria acknowledged — will stop immediately if any condition triggers
[ ] Section 12: Emergency Freeze Procedure reviewed and understood
[ ] Section 13: Legacy Send Path Retirement readiness criteria acknowledged

SEND_ENABLED is confirmed false in Railway production env: [ ]
DB send_enabled is confirmed false: [ ]
No live sends are authorized by this document: [ ]

Authorized date/time (CDT): ____________________
Authorized by: Avanish Mehrotra
```

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_002.md`  
**Next document:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_003.md` (post-first-live-dispatch)
