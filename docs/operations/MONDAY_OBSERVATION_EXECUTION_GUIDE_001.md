# Monday Observation Execution Guide — 001
## ProspectIQ — 2026-05-18 Dark-Launch Window Operator Reference

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Observation window:** Monday 2026-05-18, 8:00 AM – 11:30 AM CT  
**Observation log target:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`  
**Emergency freeze:** `STAGE_C_ACTIVATION_RUNBOOK_001.md` Part 4 (Steps F1–F5)

---

## PRE-MONDAY: D8 AND D9 VERIFICATION

Complete both before Monday. These are Avanish console and SQL actions.

---

### D8 — RESEND_WEBHOOK_SECRET (Railway Console)

**Required before:** Any live send. Does not block Monday observation (SEND_ENABLED stays false during observation).

**Action:**
```
1. Resend dashboard → Webhooks → copy the signing secret for the production endpoint
2. Railway dashboard → ProspectIQ production service → Variables
3. Add variable: RESEND_WEBHOOK_SECRET = <value>
4. Railway will redeploy automatically
5. After redeploy, check Railway logs:
   - Should NOT see: "resend_webhook: RESEND_WEBHOOK_SECRET not configured"
   - Silence on this line = correctly configured
```

**Verification SQL:** None — this is a Railway env var. No DB state involved.

**Verification endpoint (optional):**
```
GET /api/admin/send-config
```
If the endpoint exposes `resend_webhook_secret_configured`, it should return `true`.

**D8 status record (fill in):**
```
Secret retrieved from Resend dashboard: [ ] YES
Railway variable set: [ ] YES
Railway redeployed: [ ] YES
Warning log absent: [ ] CONFIRMED
D8 complete: [ ] YES
Timestamp: _______________
```

---

### D9 — batch_size=1 Verification (SQL)

**Required before:** Stage 1 activation. Does not block Monday observation.

**Verification SQL:**
```sql
SELECT workspace_id, batch_size, daily_limit, max_retries, send_enabled
FROM outreach_send_config
WHERE workspace_id = '<ws_id>';
```

Expected:
```
batch_size  = 1
daily_limit = 125
max_retries = 4
send_enabled = false
```

**If batch_size is not 1:**
```sql
UPDATE outreach_send_config
SET batch_size = 1
WHERE workspace_id = '<ws_id>';

-- Confirm:
SELECT batch_size FROM outreach_send_config WHERE workspace_id = '<ws_id>';
-- Expected: 1
```

**D9 status record (fill in):**
```
batch_size before: ___
batch_size after (if changed): ___
D9 complete: [ ] YES
Timestamp: _______________
```

---

## MONDAY 2026-05-18 OBSERVATION PROTOCOL

---

## PART 1 — PRE-OBSERVATION BASELINE (Run before 7:55 AM CT)

Run all six queries. All values must match expected before the window opens.

### SQL 1 — Queue State
```sql
SELECT COUNT(*) AS queue_rows FROM outbound_queue;
-- Expected: 8
```

### SQL 2 — Locked Row Count
```sql
SELECT COUNT(*) AS locked_rows
FROM outbound_queue
WHERE locked_by IS NOT NULL;
-- Expected: 0
```

### SQL 3 — Send Attempts Count
```sql
SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: 0
```

### SQL 4 — Send Config Gate State
```sql
SELECT send_enabled, batch_size, daily_limit, max_retries
FROM outreach_send_config
WHERE workspace_id = '<ws_id>';
-- Expected: send_enabled=false, batch_size=1, daily_limit=125, max_retries=4
```

### SQL 5 — Queue Cohort Full Detail
```sql
SELECT id, draft_id, locked_by, locked_at, retry_count, next_retry_at, enqueued_at
FROM outbound_queue
ORDER BY enqueued_at;
-- Expected: 8 rows, all NULL locked_by, all retry_count=0
--           All enqueued_at = 2026-05-15 21:24:xx UTC
```

### SQL 6 — Draft State Cross-Check
```sql
SELECT d.id, d.sent_at, d.resend_message_id, d.approval_status
FROM outbound_queue oq
JOIN outreach_drafts d ON oq.draft_id = d.id
ORDER BY oq.enqueued_at;
-- Expected: all sent_at = NULL, all resend_message_id = NULL, all approval_status = 'approved'
```

**STOP IF ANY VALUE IS UNEXPECTED. Do not proceed with observation — investigate first.**

**Baseline record (fill in):**
```
Baseline SQL run at (CT): _______________
queue_rows: ___  (expected 8)
locked_rows: ___  (expected 0)
send_attempts: ___  (expected 0)
send_enabled: ___  (expected false)
batch_size: ___  (expected 1)
All drafts: sent_at=NULL [ ] YES  approval_status=approved [ ] YES
Baseline: [ ] CLEAN / [ ] UNEXPECTED — investigate
```

---

## PART 2 — SCHEDULER REGISTRATION VERIFICATION (Run before 7:58 AM CT)

Verify dispatch_loop and reclaim_stale_locks are registered before the first tick fires.

```
Railway dashboard → ProspectIQ production → Logs
```

Search for startup log lines (appear at process startup, not at tick time):

**Expected startup log sequence (appears at last deploy/restart):**
```
dispatch_loop: registered (scheduler)
reclaim_stale_locks: registered (scheduler)
```
or similar registration confirmation log. Exact text depends on the startup sequence.

**Alternative verification:** Check Railway logs for the last `reclaim_stale_locks: running for 1 workspace(s)` log line. If it appeared within the last 2 minutes before your check, the scheduler is running.

**Scheduler verification record:**
```
reclaim_stale_locks last log visible: [ ] YES  at (CT): _______________
dispatch_loop last log visible: [ ] YES  at (CT): _______________
APScheduler thread: [ ] CONFIRMED RUNNING
```

---

## PART 3 — PER-TICK OBSERVATION (8:00 AM – 11:30 AM CT)

### Tick Schedule

| Tick | CT Time | Source |
|------|---------|--------|
| 1 | 8:00 AM | APScheduler cron: hour=8, minute=0 |
| 2 | 8:30 AM | APScheduler cron: hour=8, minute=30 |
| 3 | 9:00 AM | APScheduler cron: hour=9, minute=0 |
| 4 | 9:30 AM | APScheduler cron: hour=9, minute=30 |
| 5 | 10:00 AM | APScheduler cron: hour=10, minute=0 |
| 6 | 10:30 AM | APScheduler cron: hour=10, minute=30 |
| 7 | 11:00 AM | APScheduler cron: hour=11, minute=0 |
| 8 | 11:30 AM | APScheduler cron: hour=11, minute=30 |

**Total ticks: 8**

### Exact Expected Log Signatures

#### dispatch_loop tick (SEND_ENABLED=false) — Expected at each tick

**ONLY line expected:**
```
INFO dispatch_loop: running for 1 workspace(s)
```

**Critical: NO second line.** When `SEND_ENABLED=false`, `_dispatch_workspace()` returns at line 217–218 of `main.py` before calling `dispatch_workspace()`. The `Dispatch [<workspace>]:...` outcome log is never written.

**Full expected tick sequence in Railway logs:**
```
[8:00:00 CT] INFO  dispatch_loop: running for 1 workspace(s)
[8:00:00 CT] (silence — no dispatch outcome line)
```

**If SEND_ENABLED were true, you would instead see (do NOT expect this during observation):**
```
INFO  dispatch_loop: running for 1 workspace(s)
INFO  dispatch.claim_batch workspace_id=<ws_id> instance=<uuid> claimed=1
INFO  dispatch.workspace_complete workspace_id=<ws_id> dispatched=1 delivered=1 ...
INFO  Dispatch [<name>]: dispatched=1 delivered=1 transient=0 permanent=0 assertion_skipped=0 already_delivered_drained=0 errors=0
```
Seeing ANY of these lines during the dark-launch window is an ANOMALY — investigate immediately.

#### reclaim_stale_locks (every 2 minutes, all day) — Expected

**Expected (no stale locks, normal state):**
```
INFO  reclaim_stale_locks: running for 1 workspace(s)
```
*(No warning line — `dispatch.stale_lock_reclaim ... no stale locks` is DEBUG level, suppressed in production)*

**If stale locks are found (anomaly — queue rows should have no locks):**
```
WARNING  dispatch.stale_lock_reclaim workspace_id=<ws_id> reclaimed=<N> (locked_at < <ts>)
WARNING  Stale lock reclaim [<ws_name>]: <N> rows released
```
Seeing these warning lines = stale locks present. Run SQL immediately (see PART 4 anomaly SQL).

### Per-Tick Capture Template

Copy and fill in for each tick during the window:

```
TICK [ 1 / 2 / 3 / 4 / 5 / 6 / 7 / 8 ]
CT timestamp of tick: _______________
Tick number expected at: _______________ (see schedule above)

dispatch_loop log line visible: [ ] YES / [ ] NO
  Exact log line: _______________________________________________
  Only one log line for this tick: [ ] YES / [ ] NO
  No "dispatch.claim_batch" line: [ ] CONFIRMED
  No "Dispatch [<name>]:" outcome line: [ ] CONFIRMED

Unexpected lines (any line not matching expected signatures):
  [ ] NONE
  If any: _______________________________________________

SQL spot-check (run at 3+ ticks, always at 8:00 and 11:00 AM):
  queue_rows: ___  (expected 8, unchanged)
  locked_rows: ___  (expected 0)
  send_attempts rows: ___  (expected 0)
```

### Mandatory SQL Spot-Checks

Run SQL at these specific ticks (minimum). Run at all ticks if capacity permits.

| Tick | CT | SQL Required |
|------|----|-------------|
| 1 | 8:00 AM | Yes — first tick, establish window baseline |
| 4 | 9:30 AM | Yes — midpoint check |
| 7 | 11:00 AM | Yes — end of window |
| 8 | 11:30 AM | Yes — final tick |

**Spot-check SQL (abbreviated — run at each mandatory tick):**
```sql
SELECT
  (SELECT COUNT(*) FROM outbound_queue) AS queue_rows,
  (SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL) AS locked_rows,
  (SELECT COUNT(*) FROM send_attempts) AS send_attempts;
-- Expected every time: queue_rows=8, locked_rows=0, send_attempts=0
```

---

## PART 4 — ANOMALY RESPONSE SQL

Run these immediately if any anomaly is detected during the observation window.

### A1 — If locked_rows > 0
```sql
-- Who holds the lock and since when?
SELECT id, draft_id, locked_by, locked_at, retry_count
FROM outbound_queue
WHERE locked_by IS NOT NULL;

-- How long has the lock been held?
SELECT id, draft_id, locked_by,
       NOW() - locked_at AS lock_duration,
       locked_at
FROM outbound_queue
WHERE locked_by IS NOT NULL;
```
**Expected during dark-launch:** 0 locked rows. Any locked row with SEND_ENABLED=false is anomalous — the dispatch_loop aborts before claiming. This indicates either: (a) a pre-existing lock from a prior session, or (b) something claimed a row outside the scheduler.

### A2 — If send_attempts row appears
```sql
-- What is in send_attempts?
SELECT id, draft_id, workspace_id, status, failure_code, failure_reason,
       provider_message_id, created_at
FROM send_attempts
ORDER BY created_at DESC;

-- Which queue row does it correspond to?
SELECT oq.id AS queue_id, oq.draft_id, oq.locked_by, oq.locked_at
FROM outbound_queue oq
WHERE oq.draft_id = '<draft_id_from_send_attempts>';
```
**Expected during dark-launch:** 0 rows in send_attempts. Any row here means a send was attempted — escalate immediately (see PART 6).

### A3 — If queue_rows != 8
```sql
-- What is in the queue?
SELECT id, draft_id, locked_by, locked_at, retry_count, enqueued_at
FROM outbound_queue
ORDER BY enqueued_at;

-- Was a row deleted?
-- (No audit table — check outreach_drafts to see if any draft shows sent_at set)
SELECT id, sent_at, resend_message_id, approval_status
FROM outreach_drafts
WHERE id IN (
  SELECT draft_id FROM outbound_queue
) OR sent_at IS NOT NULL;
```

### A4 — If draft sent_at or resend_message_id changes
```sql
-- Verify draft state for all queued drafts
SELECT d.id, d.sent_at, d.resend_message_id, d.approval_status,
       oq.locked_by, oq.retry_count
FROM outbound_queue oq
JOIN outreach_drafts d ON oq.draft_id = d.id
ORDER BY oq.enqueued_at;
-- Expected: all sent_at = NULL, all resend_message_id = NULL
```

### A5 — If "dispatch.claim_batch" appears in logs
```sql
-- A claim occurred — find what was claimed
SELECT id, draft_id, locked_by, locked_at
FROM outbound_queue
WHERE locked_by IS NOT NULL;

-- Check send_attempts for corresponding row
SELECT * FROM send_attempts ORDER BY created_at DESC LIMIT 5;
```
This log line means SEND_ENABLED was true at tick time — investigate Railway env immediately.

---

## PART 5 — POST-WINDOW VERIFICATION (After 11:30 AM CT)

### Post-Window SQL Suite
```sql
-- Full post-window audit

-- 1. Queue count unchanged
SELECT COUNT(*) AS queue_rows FROM outbound_queue;
-- Expected: 8

-- 2. No locked rows
SELECT COUNT(*) AS locked_rows FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0

-- 3. No send attempts
SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: 0

-- 4. Queue rows unchanged from baseline
SELECT id, draft_id, locked_by, locked_at, retry_count, next_retry_at
FROM outbound_queue
ORDER BY enqueued_at;
-- Expected: same 8 rows as pre-window, all unlocked, retry_count=0

-- 5. Drafts unchanged
SELECT id, sent_at, resend_message_id
FROM outreach_drafts
WHERE id IN (SELECT draft_id FROM outbound_queue);
-- Expected: all sent_at = NULL, all resend_message_id = NULL

-- 6. SEND_ENABLED still false
SELECT send_enabled FROM outreach_send_config WHERE workspace_id = '<ws_id>';
-- Expected: false
```

**Post-window state record (fill in):**
```
Post-window SQL run at (CT): _______________
queue_rows: ___  (expected 8)
locked_rows: ___  (expected 0)
send_attempts: ___  (expected 0)
Queue rows: all unchanged from baseline [ ] CONFIRMED
All sent_at = NULL: [ ] CONFIRMED
All resend_message_id = NULL: [ ] CONFIRMED
send_enabled: ___  (expected false)
```

---

## PART 6 — SEND_ATTEMPT LIFECYCLE EXPECTATIONS (During Dark Launch)

**Expected:** Zero `send_attempts` rows created during the entire observation window.

The `send_attempts` table is written to only when `dispatch_workspace()` is called. With `SEND_ENABLED=false`, `_dispatch_workspace()` returns before calling `dispatch_workspace()`, so the table is never touched.

**send_attempt lifecycle reference (for Stage 1 reference only — does NOT apply during dark-launch):**

| Step | DB State |
|------|---------|
| Queue row claimed | `outbound_queue.locked_by = instance_id` |
| send_attempt inserted | `send_attempts.status = 'DISPATCHED'` |
| Atomic pre-send claim | `outreach_drafts.sent_at = NOW()` (WHERE sent_at IS NULL) |
| Resend API call → 200 | `outreach_drafts.resend_message_id = 're_xxx'` |
| send_attempt updated | `send_attempts.status = 'DELIVERED', provider_message_id = 're_xxx'` |
| Queue row deleted | `outbound_queue` row removed |
| Webhook fires | `send_attempts.reconciled_at = NOW()` |

During dark-launch: none of these transitions should occur. The table stays at 0 rows.

---

## PART 7 — WEBHOOK RECONCILIATION EXPECTATIONS (During Dark Launch)

**Expected:** Zero webhook events received from Resend.

No emails are sent with SEND_ENABLED=false. Resend fires `email.delivered` and `email.bounced` only after an email is dispatched through its API. No dispatch → no webhook.

**Webhook endpoint:** `POST /resend-webhook`

**Dark-launch expectation:** No log lines containing `resend_webhook:` should appear during the observation window (unless you manually triggered a Resend test event for D8 verification — in that case, you should see the webhook received and processed without errors).

**If an unexpected webhook fires:**
```sql
-- Check if any send_attempts reconciliation occurred
SELECT id, status, reconciled_at, provider_message_id
FROM send_attempts
ORDER BY created_at DESC LIMIT 10;
-- Expected: 0 rows
```

---

## PART 8 — ROLLBACK TRIGGERS (Absolute)

Set SEND_ENABLED=false in Railway IMMEDIATELY if ANY of the following occurs:

| # | Trigger |
|---|---------|
| R1 | `send_attempts` table has any rows |
| R2 | Any `outbound_queue` row shows `locked_by IS NOT NULL` |
| R3 | Any `outreach_drafts` row in the cohort shows `sent_at IS NOT NULL` |
| R4 | Any `outreach_drafts` row shows `resend_message_id IS NOT NULL` |
| R5 | `dispatch.claim_batch workspace_id=... claimed=N` appears in logs |
| R6 | `Dispatch [<name>]: dispatched=N ...` appears in logs |
| R7 | Resend dashboard shows any activity |
| R8 | `queue_rows` drops below 8 |
| R9 | Scheduler error: `Scheduled dispatch_loop failed:` appears |
| R10 | APScheduler restarts observed (repeated startup log sequences) |

**Emergency freeze procedure (verbatim):**
```
1. Railway dashboard → ProspectIQ production → Variables
2. Set SEND_ENABLED = false
3. Wait for deploy to complete
4. Run SQL: UPDATE outreach_send_config SET send_enabled = false WHERE workspace_id = '<ws_id>';
5. Wait 5 minutes, confirm: SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL;
   Expected: 0
6. Document in DARK_LAUNCH_RUNTIME_OBSERVATION_004.md Section 5 (Anomaly Log)
```

---

## PART 9 — ESCALATION PATHS

| Severity | Condition | Action |
|----------|-----------|--------|
| HALT | Any R1–R10 trigger | Emergency freeze (Part 8) immediately |
| INVESTIGATE | reclaim_stale_locks warning appears | Run A1 SQL; check if locked rows are pre-existing |
| INVESTIGATE | Only 7 of 8 ticks observed in logs | Check Railway for scheduler thread health |
| DOCUMENT | Any tick fires more than 60 seconds late | Record in anomaly log; no action required |
| DOCUMENT | `reclaim_stale_locks: running for 0 workspace(s)` | Workspace lookup failed; non-blocking but document |

---

## PART 10 — OBSERVATION VERDICT CRITERIA

**CLEAN verdict requires ALL of the following:**

```
[ ] 8 dispatch_loop ticks confirmed in Railway logs (8:00, 8:30, 9:00, 9:30, 10:00, 10:30, 11:00, 11:30 AM CT)
[ ] Each tick produced exactly: "dispatch_loop: running for 1 workspace(s)"
[ ] No "dispatch.claim_batch" log line appeared at any tick
[ ] No "Dispatch [<name>]:" outcome line appeared at any tick
[ ] reclaim_stale_locks fired every ~2 minutes (no warnings logged)
[ ] outbound_queue row count: 8 at start, 8 at end (unchanged)
[ ] outbound_queue locked_rows: 0 at all spot-checks
[ ] send_attempts rows: 0 throughout
[ ] outreach_drafts.sent_at: NULL for all 8 cohort drafts
[ ] outreach_drafts.resend_message_id: NULL for all 8 cohort drafts
[ ] No Resend provider activity
[ ] No emergency freeze executed
```

**NO-GO verdict (any single failure):**
- Any send_attempts row created
- Any queue row locked and not reclaimed within 10 minutes
- Any draft sent_at set
- Scheduler errors observed
- reclaim_stale_locks warning fired without explanation

---

## PART 11 — POST-OBSERVATION: STAGE C READINESS UPDATE

After completing the observation log in `DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`:

**If CLEAN:**
```
D12 — 72h dark-launch window: COMPLETE
D13 — Queue state verified: COMPLETE

Remaining open items before Stage C authorization:
[ ] D8 — RESEND_WEBHOOK_SECRET set (if not already done)
[ ] D9 — batch_size=1 confirmed (if not already done)
[ ] Avanish explicit authorization: "authorize Stage C activation"

If all items confirmed, Stage 1 (internal sink) may proceed at Avanish's direction.
```

**If NO-GO:**
```
Stage C authorization blocked.
Classify anomaly:
  (a) Operational workaround exists → document and schedule re-observation
  (b) Code fix required → open targeted PR, no other changes
  (c) Architecture defect → escalate for design review before any activation
```

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/MONDAY_OBSERVATION_EXECUTION_GUIDE_001.md`  
**Observation target:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`  
**Emergency procedure:** `STAGE_C_ACTIVATION_RUNBOOK_001.md` Part 4
