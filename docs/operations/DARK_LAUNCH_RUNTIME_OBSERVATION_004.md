# Dark-Launch Runtime Observation — 004
## ProspectIQ — Re-baselined Observation Checkpoint

**Observation window:** NOT YET SCHEDULED — to be filled in when Avanish authorizes a real observation window. Must be a live Mon–Fri 8:00–11:00 AM CT window with the scheduler actually running.
**Author:** Avanish Mehrotra & Digitillis Architecture Team
**Status:** RE-BASELINED, NOT YET RUN — see "Re-baseline note" below. Do not treat this as PASSED or as authorization to proceed; it is the observation *plan*, not its result.
**Governing protocol:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` Section 12 (Emergency Freeze)

---

## Re-baseline note (added 2026-08-14, session reconciliation)

This document originally targeted a single date, Monday 2026-05-18, with a baseline of 8 queue rows and 0 send_attempts. That date passed with the document still showing `Status: PENDING OBSERVATION` and an unfilled verdict — it was never actually run. Real production sending then happened anyway, entirely outside this or any other stage of the doctrine (see `docs/operations/STAGED_ACTIVATION_PROGRESSION_001.md`'s Reconciliation Notice for the full account: real sending ran 2026-05-19 through 2026-06-26, then stopped).

This document is re-baselined against the system's actual current state so that whenever a real Stage 0 observation is run, it is checked against what is really live, not a 3-month-stale snapshot. The date-specific tick log below is a **template to copy for the actual window**, not a record of one that already happened.

**Two preconditions this document cannot satisfy on its own, both requiring Avanish's explicit action before any observation window can start:**

1. **The Railway scheduler is currently halted** (start-command override: `sh -c 'echo "HALTED 2026-08-14 by operator..."; sleep infinity'`, set earlier this session after the scheduler was found running unattended). Un-halting it (restoring the normal start command in Railway service settings) is required before any tick can fire — and is a real production action, done deliberately by the operator, that should not be reversed without an explicit decision to do so.
2. **A real observation window is multiple hours of live wall-clock monitoring** (checking Railway logs and running the SQL below at each 30-minute tick), not something completable in a single sitting. It needs to be scheduled for an actual Mon–Fri morning.

Given both of these, this document stops at "prepared and ready" — the scheduler has not been un-halted and no observation window has been run.

---

## 1. Pre-Observation State Baseline

Execute before the 8 AM CT window opens. All values must match expected before observation begins.

### 1.1 Pre-Observation SQL Verification

```sql
-- Run immediately before 8:00 AM CT

-- Queue state
SELECT COUNT(*) AS queue_rows FROM outbound_queue;
-- Expected: verify against current count at observation time — was 579 as of
-- 2026-08-14 reconciliation, tapering but non-zero; there is no longer a
-- clean single-cohort baseline to check against. Record whatever the real
-- count is immediately before the window and treat THAT as this window's
-- baseline for the post-window delta in Section 3, not a fixed number.

SELECT COUNT(*) AS locked_rows FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0

SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: NOT 0 -- this table has 15,676+ historical rows from the 2026-05-19
-- to 2026-06-26 sending run. Unlike the original version of this document,
-- "send_attempts count" is not a useful pre/post inertness check on its own;
-- check instead that NO NEW rows appear during the window (Section 3), by
-- comparing the pre-window count captured here against the post-window count.

-- Send config
SELECT workspace_id, send_enabled, batch_size, daily_limit, max_retries, sender_physical_address
  FROM outreach_send_config;
-- Expected (verified live 2026-08-14): main workspace (...0001) send_enabled=false,
-- batch_size=1, daily_limit=1 (reset down from an unauthorized 270/45 found
-- live in this same reconciliation), sender_physical_address is NULL (not yet
-- set -- must be set before any real send stage, but is irrelevant to Stage 0
-- since Stage 0 never sends). Second workspace (...0002, "WARM/PERSONAL") is
-- permanently disabled, daily_limit=0/batch_size=0 -- not in scope for
-- activation at all.

-- SEND_ENABLED env gate
-- Check via Railway dashboard or API:
-- GET /api/admin/send-config → env_send_enabled should be false
```

**If ANY value is unexpected, STOP. Do not observe — investigate first.**

### 1.2 Pre-Observation Expected Values

Fill in the left column with the real count immediately before the window opens — do not reuse a number from a prior run of this document.

| Metric | Expected value |
|--------|---------------|
| `outbound_queue` row count | (record live count at window start) |
| Locked rows | 0 |
| `send_attempts` row count | (record live count at window start — will be nonzero, that's expected; watch for the DELTA during the window, not the absolute number) |
| `SEND_ENABLED` Railway env | false |
| DB `send_enabled` (both workspaces) | false |
| Scheduler process | running (un-halted) — confirm via Railway deployment status before the window, not assumed |

---

## 2. Observation Log

Capture the following at each tick during the 8:00–11:00 AM CT window.

### Tick Template (complete for each observed cron fire)

```
Tick timestamp (CT): 
Railway log available (Y/N): 
Scheduler fired: 

dispatch_loop execution:
  Log line: 
  Queue claimed (rows): 
  Queue inert (expected: yes, SEND_ENABLED=false): 

reclaim_stale_locks execution:
  Log line (every 2 minutes): 
  Rows reclaimed: 
  Queue row count after reclaim: 

Unexpected events:
  Any send_attempts inserted (expected: 0): 
  Any queue mutations (expected: none): 
  Any scheduler errors (expected: none): 
  Any provider activity in Resend dashboard (expected: none): 
```

### 8:00 AM CT Tick

```
Tick timestamp (CT): 
Railway log available: 
dispatch_loop fired: 
  Log line: 
  Queue claimed: 
  Abort confirmation (SEND_ENABLED=false): 

reclaim_stale_locks (8:00 AM interval):
  Log line: 
  Rows reclaimed: 

Unexpected events: 
```

### 8:30 AM CT Tick

```
Tick timestamp (CT): 
dispatch_loop fired: 
  Log line: 
  Queue claimed: 
  Abort confirmation: 

reclaim_stale_locks:
  Rows reclaimed: 

Unexpected events: 
```

### 9:00 AM CT Tick

```
[same template]
```

### 9:30 AM CT Tick

```
[same template]
```

### 10:00 AM CT Tick

```
[same template]
```

### 10:30 AM CT Tick

```
[same template]
```

### 11:00 AM CT Tick

```
[same template]
```

---

## 3. Post-Window SQL Verification

Execute after 11:00 AM CT send window closes.

```sql
-- Post-window state audit

SELECT COUNT(*) AS queue_rows FROM outbound_queue;
-- Expected: unchanged from the pre-window count recorded in Section 1.2
-- (queue rows may still be enqueued by an upstream draft-generation job
-- during the window -- that is a SEPARATE process from dispatch and is not
-- itself an anomaly; what matters is that no rows are CLAIMED or DELETED)

SELECT COUNT(*) AS locked_rows FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0

SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: unchanged from the pre-window count recorded in Section 1.2 --
-- i.e. delta = 0. The absolute number will be large and nonzero (historical
-- rows); a nonzero DELTA during this window is the anomaly, not the
-- absolute count.

-- Verify no unauthorized queue mutations
SELECT id, draft_id, locked_by, locked_at, retry_count, next_retry_at
  FROM outbound_queue
  ORDER BY enqueued_at DESC
  LIMIT 20;
-- Expected: no row among the ones present before the window shows a changed
-- locked_by, locked_at, retry_count, or next_retry_at

-- Send-trace confirms inert dispatch path
-- GET /api/admin/send-trace → abort_at=send_enabled=false
```

### Post-Window Values (to be filled in)

| Metric | Pre-window | Post-window | Delta |
|--------|-----------|-------------|-------|
| `outbound_queue` rows | (from 1.2) | | (expect 0, or explained by upstream enqueue) |
| Locked rows | 0 | | (expect 0) |
| `send_attempts` rows | (from 1.2) | | (expect 0 -- this is the real inertness check) |
| Queue mutations (locked_by/retry_count changes on pre-existing rows) | N/A | | (expect none) |
| Scheduler errors | 0 | | |

---

## 4. Observation Findings

### 4.1 Scheduler Stability

```
dispatch_loop: [STABLE / DEGRADED / FAILED]
  Total ticks observed: 
  Successful ticks: 
  Error ticks: 
  Notes: 

reclaim_stale_locks: [STABLE / DEGRADED / FAILED]
  Total executions: 
  Rows reclaimed: 
  Notes: 

APScheduler thread: [STABLE / UNSTABLE]
  Restart loops observed: 
  Thread crashes: 
  Notes: 
```

### 4.2 Queue Behavioral Analysis

```
outbound_queue inertness: [CONFIRMED / ANOMALY DETECTED]
  Unexpected row mutations: 
  Lock acquisitions: 
  Retry count changes: 

send_attempts inertness: [CONFIRMED / ANOMALY DETECTED]
  Rows inserted: 
  Unexpected updates: 
```

### 4.3 SEND_WINDOW Interaction

```
dispatch_loop fired during window (8-11 AM CT): 
dispatch_loop fired outside window: 
SEND_WINDOW env vars interacting (expected: none): 
```

### 4.4 Hidden Runtime Coupling (D5/D6/D1 code paths)

```
Pre-send claim code path triggered: [NOT TRIGGERED (expected)]
  If triggered, why: 
ALREADY_DELIVERED code path triggered: [NOT TRIGGERED (expected)]
  If triggered, why: 
Webhook reconciliation triggered: [NOT TRIGGERED (expected)]
  If triggered, why: 
```

---

## 5. Anomaly Log

If any unexpected event occurs during observation:

```
Anomaly 1:
  Timestamp (CT): 
  Event: 
  SQL query run: 
  Result: 
  Assessment: 
  Action taken: 

[Add rows as needed]
```

If Emergency Freeze was executed: see `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` Section 12 for procedure. Document the freeze execution below:

```
Emergency freeze executed: [YES / NO]
  If YES:
    Freeze timestamp: 
    Trigger event: 
    Steps executed: 
    Post-freeze state: 
```

---

## 6. Verdict

| Dimension | Status |
|-----------|--------|
| Scheduler stability | |
| Queue inertness | |
| No unexpected send_attempts | |
| No provider activity | |
| No hidden runtime coupling | |
| D5/D6/D1 code paths inert | |

**Overall observation verdict:** [CLEAN / ANOMALY DETECTED]

---

## 7. Stage C Readiness Re-Evaluation

Based on this observation window, the following items from the ACTIVATION_SAFETY_HARDENING_001.md GO/NO-GO criteria must be updated:

| Item | Status before observation | Status after observation |
|------|--------------------------|--------------------------|
| D12 — dark-launch window complete | PENDING — no window has ever actually been run; the original 2026-05-18 date passed with this document unfilled | |
| D13 — Queue state verified | PENDING | |

### Remaining open items before Stage C authorization

Re-checked live 2026-08-14. Every item below reflects a direct verification this session, not an assumption:

```
[x] D9 — batch_size=1 confirmed in production outreach_send_config
    (verified live: main workspace daily_limit=1, batch_size=1, reset from an
    unauthorized 270/45 found during this session's reconciliation)
[ ] D8 — WEBHOOK_SECRET set in Railway production env
    UNVERIFIED this session -- not re-checked against the live Railway env vars.
    Confirm via GET /api/admin/send-config or the Railway dashboard before
    relying on this; do not assume it is still set correctly from any
    earlier session's finding.
[ ] The scheduler must be un-halted before any tick can fire
    NOT DONE. Currently overridden to `sleep infinity` (2026-08-14 halt).
    Restoring the normal start command is a real production action on a
    deliberately-halted service -- requires Avanish's explicit decision to
    do so, not something to restore as a side effect of "preparing" this
    document.
[ ] sender_physical_address set in outreach_send_config
    NOT SET (confirmed live: NULL). Irrelevant to Stage 0 itself (which
    never sends), but blocks every stage after it -- worth setting before
    Stage 1 is attempted, not needed to run Stage 0.
[ ] D12 — This observation documented and CLEAN verdict issued
    NOT DONE -- no window has been run since this re-baseline.
[ ] D13 — outbound_queue state verified immediately before the window
    NOT DONE -- record the real count at window start (see Section 1.2);
    there is no fixed expected number anymore.
[ ] Avanish explicit authorization to un-halt the scheduler and begin the
    observation window
```

If D12 returns CLEAN and all other items are confirmed, Stage C may proceed at Avanish's direction in a later session. **This document, as re-baselined, is the observation plan — it does not itself authorize un-halting the scheduler or beginning the window. That is a separate decision.**

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`  
**Observation window:** NOT YET SCHEDULED — see Re-baseline note above  
**Emergency procedure:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` Section 12
