# Stage C Activation Runbook — 001
## ProspectIQ — First Governed Live Send

**Document date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** READY FOR OPERATOR USE — activation pending Avanish authorization  
**Activation window:** Monday 2026-05-18 8:00 AM CT (earliest)

---

## PART 1 — GO/NO-GO CHECKLIST

This checklist must be completed in full immediately before activation. Every item must be checked. A single unchecked item blocks activation.

### Section 1A: Code Prerequisites (verify against PR list)

```
[ ] D7 merged — send_approved scheduler registration retired (PR #122)
[ ] D5 merged — atomic pre-send sent_at claim (PR #123)
[ ] D6 merged — ALREADY_DELIVERED provider reconciliation (PR #124)
[ ] D1 merged — Resend webhook send_attempts reconciliation (PR #125)
```

All four PRs are on `main`. Confirm via `git log --oneline -10` showing these commits.

### Section 1B: Production State Invariants (run SQL immediately before activation)

```sql
-- Run all queries. Expected values listed. Stop if any mismatch.

-- B1: Queue cohort present and unlocked
SELECT COUNT(*) AS total_rows FROM outbound_queue;
-- Expected: 8

SELECT COUNT(*) AS locked_rows FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0

-- B2: No prior sends
SELECT COUNT(*) AS send_attempts FROM send_attempts;
-- Expected: 0

-- B3: Send config correct
SELECT send_enabled, batch_size, daily_limit, max_retries
  FROM outreach_send_config
  WHERE workspace_id = (SELECT id FROM workspaces LIMIT 1);
-- Expected: send_enabled=false, batch_size=1, daily_limit=125, max_retries=4

-- B4: No dispatch-failed drafts in cohort
SELECT COUNT(*) AS dispatch_failed
  FROM outreach_drafts
  WHERE approval_status = 'dispatch_failed';
-- Expected: 0

-- B5: All 8 cohort drafts have sent_at=NULL (none pre-claimed)
SELECT COUNT(*) AS pre_sent
  FROM outreach_drafts d
  JOIN outbound_queue q ON q.draft_id = d.id
  WHERE d.sent_at IS NOT NULL;
-- Expected: 0
```

```
[ ] B1 — queue rows = 8
[ ] B1 — locked rows = 0
[ ] B2 — send_attempts = 0
[ ] B3 — send_enabled=false, batch_size=1
[ ] B4 — dispatch_failed count = 0
[ ] B5 — pre-sent drafts in cohort = 0
```

### Section 1C: Environment Gates (check Railway dashboard)

```
[ ] SEND_ENABLED = false in Railway production env (confirm before changing)
[ ] RESEND_WEBHOOK_SECRET = <value> set in Railway production env (non-empty)
[ ] DB send_enabled = false (confirmed by B3 SQL above)
```

**How to verify RESEND_WEBHOOK_SECRET:**
```
GET /api/admin/send-config
Look for: "resend_webhook_secret_configured": true (or check Railway env vars directly)
```

Alternatively: `GET /api/admin/send-trace` — if it returns `{"abort_at":"send_enabled=false"}` the env gate is working.

### Section 1D: Scheduler State (verify in Railway startup logs)

Look for the startup log line after last deploy:
```
Expected: "dispatch_loop cron Mon-Fri 8:00-11:00 Chicago (sole scheduler send path; send_approved RETIRED 2026-05-15)"
Not expected: "send_approved" anywhere in the registered jobs list
```

```
[ ] dispatch_loop registered in scheduler (present in startup log)
[ ] send_approved NOT registered (absent from startup log)
[ ] reclaim_stale_locks registered (present in startup log)
```

### Section 1E: Staged Activation Gate

Per `STAGED_ACTIVATION_PROGRESSION_001.md`, activation begins at Stage 1 (internal sink):

```
[ ] First activation target is a sink address (Avanish-controlled inbox)
[ ] batch_size=1 confirmed (B3 above)
[ ] Avanish present and monitoring during first dispatch window
[ ] Railway logs accessible
[ ] Rollback procedure reviewed (Part 4 of this document)
```

### Section 1F: Authorization

```
[ ] Avanish has issued explicit verbal or written authorization:
    "I authorize Stage C activation for the [date] send window"
```

**If every box above is checked:** proceed to Part 2.  
**If any box is unchecked:** do not proceed. Identify and resolve the gap.

---

## PART 2 — ACTIVATION SEQUENCE

Execute steps in exact order. Do not batch steps. Read the expected outcome before executing each step.

### Step 1 — Final pre-activation state snapshot (T-10 minutes)

Run the Part 1 Section 1B SQL queries. Record all values. They become the baseline for post-activation comparison.

**Abort condition:** Any value differs from expected → stop, investigate.

### Step 2 — Set batch_size=1 in production DB (if not already set)

```sql
UPDATE outreach_send_config
SET batch_size = 1
WHERE workspace_id = (SELECT id FROM workspaces LIMIT 1);

-- Verify
SELECT batch_size FROM outreach_send_config WHERE workspace_id = (SELECT id FROM workspaces LIMIT 1);
-- Expected: 1
```

**Timing:** Execute at T-5 minutes. Takes effect immediately without deploy.  
**Abort condition:** UPDATE fails or returns 0 rows → stop, investigate.

### Step 3 — Set DB send_enabled = true (T-2 minutes)

```sql
UPDATE outreach_send_config
SET send_enabled = true
WHERE workspace_id = (SELECT id FROM workspaces LIMIT 1);

-- Verify
SELECT send_enabled FROM outreach_send_config WHERE workspace_id = (SELECT id FROM workspaces LIMIT 1);
-- Expected: true
```

**Effect:** Arms the DB gate. The env gate (SEND_ENABLED) still blocks actual sends.  
**Timing:** T-2 minutes before target cron tick.  
**Rollback at this step:** `UPDATE outreach_send_config SET send_enabled = false WHERE workspace_id = ...`

### Step 4 — Set SEND_ENABLED=true in Railway env (T-1 minute)

In Railway dashboard: production environment → `SEND_ENABLED` → change to `true`.

Railway triggers an automatic redeploy. Typical redeploy time: 60–90 seconds.

**This is the activation event.** After this step, the next cron tick (Mon–Fri 8–11 AM CT :00 or :30) will execute `dispatch_loop` without the env gate abort.

**Abort condition BEFORE this step:**
- Any unexpected queue mutation in Step 1 snapshot
- send_enabled was somehow already true (investigate before proceeding)
- Avanish changes mind → do not proceed

**Rollback at this step (before deploy completes):**
- In Railway: immediately change SEND_ENABLED back to false
- Railway will redeploy again to the correct state

### Step 5 — Confirm redeploy completion

Watch Railway dashboard for deploy completion indicator. Then verify:

```
GET /api/admin/send-trace
Expected response: {"abort_at": null, "trace": [...]}
```

If `abort_at` is null, sends are live. If `abort_at` is still `"send_enabled=false"`, the new deploy has not taken effect yet — wait 30 more seconds and retry.

**Do not proceed to Step 6 until send-trace confirms sends are live.**

### Step 6 — Monitor first dispatch_loop tick

The next cron tick fires at the next :00 or :30 mark within 8–11 AM CT.

**Expected log sequence in Railway:**

```
[~:00 or :30] _run_dispatch_loop fired
[~:00 or :30] dispatch_workspace called: workspace_id=<id>, batch_size=1, max_retries=4
[~:00 or :30] dispatch.claim_batch workspace=<id> instance=<uuid> claimed=1
[~:00 or :30] send_attempt inserted: draft_id=<id> attempt=1 idempotency_key=<id>:1
[~:00 or :30] dispatch_queued_draft: pre_send_claim OK draft_id=<id>
[~:00 or :30] resend.Emails.send called idempotency_key=<id>:1
[~:00 or :30] dispatch_queued_draft DELIVERED draft_id=<id> contact=<email> resend_id=<re_xxx>
[~:00 or :30] dispatch.workspace_complete dispatched=1 delivered=1 transient=0 permanent=0 assertion_skipped=0 already_delivered_drained=0 errors=0
```

**Timing:** If activation happens at 8:00 AM tick, wait for the 8:30 tick as first live dispatch. If activation happens between ticks, first live dispatch is at the next tick.

### Step 7 — First-send verification SQL (run within 5 minutes of expected tick)

```sql
-- V1: Queue drain
SELECT COUNT(*) AS queue_remaining FROM outbound_queue;
-- Expected: 7 (one row consumed)

-- V2: send_attempts lifecycle
SELECT status, draft_id, attempt_number, idempotency_key,
       provider_message_id, dispatched_at, resolved_at
  FROM send_attempts
  ORDER BY created_at DESC LIMIT 3;
-- Expected: 1 row, status=DELIVERED, provider_message_id=re_<xxx> (non-null)

-- V3: Draft sent_at set
SELECT d.id, d.sent_at, d.resend_message_id
  FROM outreach_drafts d
  JOIN send_attempts sa ON sa.draft_id = d.id
  WHERE sa.status = 'DELIVERED'
  ORDER BY sa.created_at DESC LIMIT 1;
-- Expected: sent_at is non-null, resend_message_id is non-null

-- V4: Remaining queue rows still unlocked
SELECT COUNT(*) AS still_locked FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0 (dispatch_loop released all locks after batch)
```

**Abort condition:** Any V1-V4 result differs from expected → execute Emergency Freeze (Part 4).

### Step 8 — Webhook reconciliation verification (run 5–15 minutes after send)

Resend typically delivers and fires `email.delivered` within 1–5 minutes of accepting the call.

```sql
-- V5: send_attempt reconciled_at set by webhook
SELECT status, provider_message_id, reconciled_at, resolved_at
  FROM send_attempts
  WHERE draft_id = (
    SELECT draft_id FROM send_attempts ORDER BY created_at DESC LIMIT 1
  );
-- Expected: reconciled_at is non-null (set by email.delivered webhook)
```

Also verify in Railway logs:
```
Expected: "webhook.send_attempt_reconciled draft_id=<id> status=DELIVERED attempt_id=<id>"
```

**If reconciled_at is null after 15 minutes:** The webhook did not fire. Possible causes:
- RESEND_WEBHOOK_SECRET mismatch (check Railway logs for 401)
- Resend webhook endpoint not configured in Resend dashboard
- Delivery delay (wait up to 30 minutes before escalating)

This does not block continuing the send window — webhook reconciliation is a tracking concern, not a delivery safety concern.

### Step 9 — Continue observation through send window

During the 8–11 AM CT window, `dispatch_loop` fires every 30 minutes. With `batch_size=1`, each tick dispatches one email. Observe each tick for:

- `dispatched=1, delivered=1` in log
- `queue_remaining` decrements by 1
- No error log lines

At 11:00 AM CT, the send window closes and `dispatch_loop` stops firing.

---

## PART 3 — MONDAY OBSERVATION PROCEDURES (Phase B)

This section covers the 2026-05-18 observation window specifically.

### Pre-Window Checklist (7:50 AM CT)

```
[ ] Railway logs tab open
[ ] psql or Supabase table editor ready
[ ] This runbook open
[ ] Emergency Freeze procedure visible (Part 4)
[ ] Phone or Slack monitoring available
```

### At 8:00 AM CT — First Cron Tick

**If SEND_ENABLED=false (dark-launch continuation, no activation yet):**

Expected log:
```
_run_dispatch_loop fired
dispatch_workspace: batch claimed=0 (SEND_ENABLED=false abort)
```

Check `outbound_queue` row count — must still be 8. Check `send_attempts` — must be 0.

**If SEND_ENABLED=true (activation day):**

Expected log: full sequence from Part 2 Step 6.

### Queue Claim Monitoring (per tick)

After each tick:
```sql
SELECT COUNT(*) FROM outbound_queue;           -- Decrements by 1 per successful send
SELECT COUNT(*) FROM send_attempts;             -- Increments by 1 per successful send
SELECT MAX(created_at) FROM send_attempts;     -- Timestamp of most recent dispatch
```

### Send Attempt Verification (after each delivered send)

```sql
SELECT sa.status, sa.attempt_number, sa.idempotency_key,
       sa.provider_message_id, sa.dispatched_at, sa.resolved_at, sa.reconciled_at,
       d.sent_at, d.resend_message_id
  FROM send_attempts sa
  JOIN outreach_drafts d ON d.id = sa.draft_id
  ORDER BY sa.dispatched_at DESC LIMIT 3;
```

All columns must be non-null for a complete send lifecycle.

### sent_at Verification

For each dispatched draft:
```sql
SELECT id, sent_at, resend_message_id, approval_status
  FROM outreach_drafts
  WHERE sent_at IS NOT NULL
  ORDER BY sent_at DESC LIMIT 5;
-- sent_at should match dispatch time (set pre-send by D5 claim)
-- resend_message_id should be non-null
-- approval_status should be 'approved' (unchanged)
```

### Lock Reclaim Monitoring

`reclaim_stale_locks` runs every 2 minutes. Watch for:
```
reclaim_stale_locks workspace=<id>: reclaimed=0
```

If `reclaimed > 0`, a lock was held longer than 5 minutes. This indicates a crash or slow operation. Investigate before the next send tick.

### Failure Escalation Conditions

Execute Emergency Freeze (Part 4) immediately if ANY of the following appear:

```
ABORT CONDITIONS:
[ ] queue_rows decreased by more than 1 per tick (more than batch_size sent)
[ ] send_attempts.status = 'DISPATCHED' not transitioning to DELIVERED within 5 min
[ ] duplicate email received at sink (check inbox immediately)
[ ] dispatch_loop log shows "errors=1" or higher
[ ] TRANSIENT_FAILED or PERMANENTLY_FAILED on first attempt
[ ] reclaim_stale_locks shows reclaimed > 0 on a row that then re-fails
[ ] already_delivered_drained > 0 (unexpected crash-recovery path fired)
[ ] Queue row count goes negative (impossible, indicates assertion failure)
[ ] Any Railway log: "lost_send_pre_claim_crash"
```

### Rollback Trigger Conditions

```
ROLLBACK TRIGGERS (set SEND_ENABLED=false immediately):
[ ] Two emails received at sink for the same draft (duplicate send confirmed)
[ ] Any Resend API error on the first attempt that is classified PERMANENTLY_FAILED
[ ] send_attempts count exceeds outbound_queue dequeued count (orphan records)
[ ] outreach_drafts.sent_at set without corresponding send_attempts DELIVERED row
[ ] Scheduler thread crash or restart loop in Railway logs
```

---

## PART 4 — EMERGENCY FREEZE PROCEDURE

Execute immediately if any abort or rollback trigger fires. Estimated time to halt: 60–90 seconds.

### Step F1 — Set SEND_ENABLED=false in Railway

Railway dashboard → production environment → `SEND_ENABLED` → change to `false`.

Railway triggers automatic redeploy. Do not wait for confirmation before F2.

### Step F2 — Set DB send_enabled=false

```sql
UPDATE outreach_send_config
SET send_enabled = false
WHERE workspace_id = (SELECT id FROM workspaces LIMIT 1);
```

This takes effect immediately without a deploy.

### Step F3 — Verify freeze via send-trace

```
GET /api/admin/send-trace
Expected: {"abort_at": "send_enabled=false", "trace": []}
```

Retry every 30 seconds until confirmed. If redeploy takes > 120 seconds, verify Railway build progress in dashboard.

### Step F4 — Capture state

```sql
-- Capture everything relevant for post-mortem
SELECT id, draft_id, locked_by, locked_at, retry_count, next_retry_at
  FROM outbound_queue ORDER BY enqueued_at;

SELECT id, draft_id, status, attempt_number, idempotency_key,
       provider_message_id, dispatched_at, resolved_at, reconciled_at,
       failure_code, failure_reason
  FROM send_attempts ORDER BY created_at DESC;

SELECT id, sent_at, resend_message_id, approval_status
  FROM outreach_drafts
  WHERE sent_at IS NOT NULL
  ORDER BY sent_at DESC LIMIT 10;
```

Save all output. Timestamp the capture.

### Step F5 — Assess and decide

| State | Assessment |
|-------|-----------|
| `outbound_queue` rows = 8 (no change) | No sends occurred. Safe to resume after investigation. |
| `outbound_queue` rows = 7, `send_attempts` has 1 DELIVERED | First send completed successfully before freeze. Resume at next window after investigation. |
| `outbound_queue` rows = 7, `send_attempts` has 1 DISPATCHED | Send in-flight during freeze. Check Resend dashboard for delivery status. |
| `outbound_queue` rows = 7, `send_attempts` has 2+ rows | Retry path may have fired. Check idempotency_keys. |
| Duplicate email confirmed | Escalate immediately. Check idempotency_key match in Resend dashboard. |

### Post-Freeze: Do Not Re-Enable Without Investigation

Document the anomaly before clearing the freeze. Re-activation requires a new session with updated go/no-go checklist.

---

## PART 5 — EXPECTED STATE TRANSITIONS

### Complete single-send lifecycle (normal path)

```
T+0    outbound_queue: row locked (locked_by=instance_id, locked_at=now)
T+0    send_attempts: DISPATCHED row inserted (attempt_number=1, idempotency_key="<id>:1")
T+0    outreach_drafts: sent_at=<now> (pre-send claim, D5)
T+0    resend.Emails.send() called
T+0    send_attempts: status=DELIVERED, provider_message_id=re_<xxx>, resolved_at=now
T+0    outbound_queue: row deleted (queue drained)
T+1-5m Resend fires email.delivered webhook
T+1-5m send_attempts: reconciled_at=now (D1 webhook reconciliation)
```

### Expected DB state after first successful tick

```
outbound_queue:  7 rows, all unlocked
send_attempts:   1 row, status=DELIVERED, provider_message_id non-null, reconciled_at non-null
outreach_drafts: 1 row with sent_at non-null, resend_message_id non-null
```

### Webhook timing expectations

| Event | Typical latency | Maximum before concern |
|-------|----------------|----------------------|
| email.delivered | 1–3 minutes | 15 minutes |
| email.opened | 0–24 hours | N/A (contact-driven) |
| email.bounced | 0–5 minutes | 30 minutes |

If `email.delivered` does not arrive within 15 minutes, check:
1. Resend dashboard for the message status by `resend_message_id`
2. Railway logs for webhook 401 errors (RESEND_WEBHOOK_SECRET mismatch)
3. Resend dashboard webhook configuration URL

---

## PART 6 — RECOVERY PROCEDURES

### If TRANSIENT_FAILED on first attempt

Dispatch scheduler will retry with exponential backoff: 5min → 15min → 1h → 4h. After 4 retries, the draft is permanently failed. To prevent permanent failure:

1. Identify the failure code in `send_attempts.failure_code`
2. If it's a rate limit (429): do nothing, retry will succeed
3. If it's a network error: verify Resend API key is valid
4. If it's a provider 5xx: retry naturally

Do not manually re-queue. Let the scheduler handle retries.

### If PERMANENTLY_FAILED on first attempt (4xx)

```sql
-- Identify the failed draft
SELECT sa.draft_id, sa.failure_code, sa.failure_reason, d.sent_at
  FROM send_attempts sa
  JOIN outreach_drafts d ON d.id = sa.draft_id
  WHERE sa.status = 'PERMANENTLY_FAILED'
  ORDER BY sa.created_at DESC LIMIT 3;
```

Common causes:
- Invalid recipient email → contact should be in suppression_log (verify)
- Invalid from address → check sender config
- API key invalid → verify RESEND_API_KEY in Railway env

After resolving root cause, the queue row is already deleted (dispatch_scheduler drains on permanent failure). The draft is marked `dispatch_failed`. Manual re-queue requires operator action.

### If webhook does not fire

The send still completed. The only effect is `send_attempts.reconciled_at` remains null. This is an observability gap, not a safety gap. Resend will retry webhook delivery for up to 3 days.

Do not re-send to compensate for missing webhook.

### If already_delivered_drained appears in logs

This means a crash-recovery path fired (D6). It is safe:
- If `resend_message_id` was set: email was sent, queue row drained
- If not: Scenario E (lost send), review manually

Check:
```sql
SELECT sa.failure_code, sa.failure_reason, d.sent_at, d.resend_message_id
  FROM send_attempts sa JOIN outreach_drafts d ON d.id = sa.draft_id
  WHERE sa.failure_reason LIKE 'already_delivered_drain%'
  ORDER BY sa.created_at DESC LIMIT 3;
```

---

## PART 7 — OPERATOR TIMING GUIDANCE

| Time | Action |
|------|--------|
| T-10 min | Run Part 1 go/no-go SQL and checklist |
| T-5 min | Execute Step 2 (batch_size=1 SQL) |
| T-2 min | Execute Step 3 (DB send_enabled=true) |
| T-1 min | Execute Step 4 (Railway SEND_ENABLED=true) — triggers redeploy |
| T+0 min | Watch Railway redeploy progress |
| T+90s | Verify send-trace shows abort_at=null (Step 5) |
| T+next :00/:30 | Monitor first dispatch_loop tick (Step 6) |
| T+5 min | Run Step 7 verification SQL |
| T+15 min | Check reconciled_at in send_attempts (Step 8) |
| T+30 min | Next tick fires — repeat monitoring |
| 11:00 AM CT | Send window closes. Run final state snapshot. |

**Minimum two people should be available during first activation:** one monitoring Railway logs, one running verification SQL.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/STAGE_C_ACTIVATION_RUNBOOK_001.md`  
**Prerequisite documents:** `ACTIVATION_SAFETY_HARDENING_001.md`, `DELIVERY_CORRECTNESS_ANALYSIS_001.md`, `ATOMIC_DISPATCH_CORRECTNESS_VALIDATION_001.md`, `DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`
