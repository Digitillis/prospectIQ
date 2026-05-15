# Dark-Launch Runtime Observation — 004
## ProspectIQ — Monday 2026-05-18 Observation Checkpoint

**Observation window:** Monday 2026-05-18, 8:00 AM – 11:30 AM CT  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** PENDING OBSERVATION — document to be completed during/after observation window  
**Governing protocol:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` Section 12 (Emergency Freeze)

---

## 1. Pre-Observation State Baseline

Execute before the 8 AM CT window opens. All values must match expected before observation begins.

### 1.1 Pre-Observation SQL Verification

```sql
-- Run immediately before 8:00 AM CT

-- Queue state
SELECT COUNT(*) AS queue_rows FROM outbound_queue;
-- Expected: 8

SELECT COUNT(*) AS locked_rows FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0

SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: 0

-- Send config
SELECT send_enabled, batch_size, daily_limit, max_retries
  FROM outreach_send_config WHERE workspace_id = :ws_id;
-- Expected: send_enabled=false, batch_size=1, daily_limit=125, max_retries=4

-- SEND_ENABLED env gate
-- Check via Railway dashboard or API:
-- GET /api/admin/send-config → env_send_enabled should be false
```

**If ANY value is unexpected, STOP. Do not observe — investigate first.**

### 1.2 Pre-Observation Expected Values

| Metric | Expected value |
|--------|---------------|
| `outbound_queue` row count | 8 |
| Locked rows | 0 |
| `send_attempts` row count | 0 |
| `SEND_ENABLED` Railway env | false |
| DB `send_enabled` | false |
| Queue cohort enqueued | 2026-05-15 21:24:00 UTC |

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
-- Expected: 8 (unchanged)

SELECT COUNT(*) AS locked_rows FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0

SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: 0

-- Verify no unauthorized queue mutations
SELECT id, draft_id, locked_by, locked_at, retry_count, next_retry_at
  FROM outbound_queue
  ORDER BY enqueued_at;
-- Expected: same 8 rows as enqueued 2026-05-15, all unlocked, retry_count=0

-- Send-trace confirms inert dispatch path
-- GET /api/admin/send-trace → abort_at=send_enabled=false
```

### Post-Window Values (to be filled in)

| Metric | Pre-window | Post-window | Delta |
|--------|-----------|-------------|-------|
| `outbound_queue` rows | 8 | | |
| Locked rows | 0 | | |
| `send_attempts` rows | 0 | | |
| Queue mutations | N/A | | |
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
| D12 — 72h dark-launch window complete | PENDING | |
| D13 — Queue state verified | | |

### Remaining open items before Stage C authorization

```
[ ] D8 — RESEND_WEBHOOK_SECRET set in Railway production env (Avanish console action)
[ ] D9 — batch_size=1 confirmed in production outreach_send_config (Avanish SQL)
[ ] D12 — This observation documented and CLEAN verdict issued
[ ] D13 — outbound_queue: 8 rows present, all unlocked (verified above)
[ ] Avanish explicit authorization: "authorize Stage C activation"
```

If D12 returns CLEAN and all other items are confirmed, Stage C may proceed at Avanish's direction in the next session.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`  
**Observation window:** Monday 2026-05-18 8:00–11:30 AM CT  
**Emergency procedure:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` Section 12
