# Operational Maturity Roadmap — 001
## ProspectIQ — Lane 1: Runtime Confidence and Observability

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Date:** 2026-05-15  
**Status:** ACTIVE — governs all Lane 1 work  
**Scope:** Runtime confidence, observability, rollback safety, operational tooling

---

## Context

The dispatch runtime is implemented and deployed. The current observability posture requires an operator to:
- open Railway logs to detect dispatch events,
- run raw SQL to check queue state,
- manually poll for anomalies.

This is acceptable for controlled activation (Stages 1–2) but insufficient for operational continuity beyond Stage 3. This roadmap defines what observability must exist at each activation stage.

**Constraint:** No redesign of the queue, scheduler, or orchestration patterns. All items below add observation and tooling on top of the existing runtime — they do not change its behavior.

---

## P0 — CRITICAL (Required before or during Stage 1)

These gaps represent active operational risk during the first live send. They require resolution before Stage 1 is complete, not before Stage 1 is started.

---

### P0-1 — Railway Log Alert: PERMANENTLY_FAILED and Lost Send

**Gap:** When `dispatch_scheduler.py` writes an ERROR log for `lost_send_pre_claim_crash` or `PERMANENTLY_FAILED`, the operator has no automated notification. Failures accumulate silently between check-ins.

**Implementation:** Railway log alert (no code change).
```
Railway → ProspectIQ production → Observability → Log Alerts
Alert 1: contains "lost_send_pre_claim_crash"
Alert 2: contains "PERMANENTLY_FAILED"
Alert 3: contains "sent_at_rollback_failed"
Destination: email (avanish.mehrotra@gmail.com)
```

**Effort:** 15 minutes (console action).  
**Risk if deferred:** A failed send at Stage 1 may go undetected if logs are not actively watched.

---

### P0-2 — Railway Log Alert: Unexpected Dispatch During Dark Launch

**Gap:** If SEND_ENABLED flips true unexpectedly (environment variable drift, Railway issue, or configuration error), the first sign would be `dispatch.claim_batch` in the logs. No automated alert exists.

**Implementation:** Railway log alert.
```
Alert: contains "dispatch.claim_batch workspace_id="
Destination: email
Trigger: any time (24/7, not just observation window)
```

**Effort:** 10 minutes (console action).  
**Risk if deferred:** An unintended activation during the dark-launch window goes undetected until the next manual SQL check.

---

### P0-3 — Pre-Send Verification Checklist (Operator Protocol)

**Gap:** No single-execution verification script exists. The operator runs 6 separate SQL queries manually from the observation guide.

**Implementation:** A single SQL block operator can paste as one query:
```sql
-- ProspectIQ Pre-Send Verification — run before any activation action
SELECT
  'queue_rows'        AS check_name,
  COUNT(*)::text      AS value,
  '8'                 AS expected,
  (COUNT(*) = 8)      AS pass
FROM outbound_queue

UNION ALL

SELECT
  'locked_rows', COUNT(*)::text, '0', (COUNT(*) = 0)
FROM outbound_queue WHERE locked_by IS NOT NULL

UNION ALL

SELECT
  'send_attempts', COUNT(*)::text, '0', (COUNT(*) = 0)
FROM send_attempts

UNION ALL

SELECT
  'send_enabled', send_enabled::text, 'false', (NOT send_enabled)
FROM outreach_send_config WHERE workspace_id = '<ws_id>'

UNION ALL

SELECT
  'batch_size', batch_size::text, '1', (batch_size = 1)
FROM outreach_send_config WHERE workspace_id = '<ws_id>'

UNION ALL

SELECT
  'drafts_unsent',
  COUNT(*)::text,
  '8',
  (COUNT(*) = 8)
FROM outreach_drafts
WHERE id IN (SELECT draft_id FROM outbound_queue)
  AND sent_at IS NULL;
```

All 6 `pass` values must be `true` before any activation action.

**Effort:** 30 minutes (SQL authoring + documentation update).  
**Deliverable:** Add to `MONDAY_OBSERVATION_EXECUTION_GUIDE_001.md` Part 1.

---

### P0-4 — Webhook Endpoint Reachability Verification

**Gap:** The Resend webhook URL registered in the Resend dashboard has not been independently verified as reachable from Resend's infrastructure. A misconfigured URL or Railway routing issue would cause silent reconciliation failure.

**Implementation:** Manual test before Stage 1.
```
1. Resend dashboard → Webhooks → "Send test event"
2. Monitor Railway logs for: "resend_webhook: event_type=email.delivered"
3. Confirm send_attempts is not mutated (no live rows during test)
4. Confirm RESEND_WEBHOOK_SECRET validation passes (no 401 in logs)
```

**Effort:** 20 minutes (manual test).  
**Risk if deferred:** Stage 1 email.delivered webhook fires but reconciliation silently fails; operator discovers `reconciled_at` is NULL hours later.

---

## P1 — IMPORTANT (Required before Stage 3 — live cohort sends)

These items are not required for the first internal sink test but must exist before multiple real sends are in flight.

---

### P1-1 — Queue Health SQL Dashboard (Documented Query Set)

**Gap:** Operator must construct queue health queries on-demand. No canonical query set exists for monitoring queue state during active sends.

**Implementation:** A documented reference query set (no new API, no new tables):

```sql
-- Queue Health Dashboard — ProspectIQ
-- Run during any active send window

-- 1. Overall queue state
SELECT
  COUNT(*)                                          AS total_rows,
  COUNT(*) FILTER (WHERE locked_by IS NOT NULL)    AS locked,
  COUNT(*) FILTER (WHERE locked_by IS NULL)        AS available,
  COUNT(*) FILTER (WHERE retry_count > 0)          AS retrying,
  MAX(retry_count)                                  AS max_retry_count,
  MIN(enqueued_at)                                  AS oldest_row
FROM outbound_queue
WHERE workspace_id = '<ws_id>';

-- 2. Send attempt status distribution
SELECT status, COUNT(*) AS count
FROM send_attempts
WHERE workspace_id = '<ws_id>'
GROUP BY status;

-- 3. Today's send count
SELECT COUNT(*) AS sent_today
FROM send_attempts
WHERE workspace_id = '<ws_id>'
  AND created_at >= CURRENT_DATE;

-- 4. Unreconciled delivered sends (webhook not yet received)
SELECT sa.id, sa.draft_id, sa.provider_message_id, sa.created_at,
       NOW() - sa.created_at AS time_since_send
FROM send_attempts sa
WHERE sa.workspace_id = '<ws_id>'
  AND sa.status = 'DELIVERED'
  AND sa.reconciled_at IS NULL
ORDER BY sa.created_at;
-- Flag if any row > 2 hours old (webhook delay anomaly)

-- 5. Retry queue detail
SELECT oq.draft_id, oq.retry_count, oq.next_retry_at,
       sa.failure_code, sa.failure_reason
FROM outbound_queue oq
LEFT JOIN send_attempts sa ON sa.draft_id = oq.draft_id
WHERE oq.workspace_id = '<ws_id>'
  AND oq.retry_count > 0
ORDER BY oq.retry_count DESC;

-- 6. PERMANENTLY_FAILED inventory
SELECT sa.draft_id, sa.failure_code, sa.failure_reason, sa.created_at
FROM send_attempts sa
WHERE sa.workspace_id = '<ws_id>'
  AND sa.status = 'PERMANENTLY_FAILED'
ORDER BY sa.created_at DESC;
```

**Effort:** 2 hours (SQL authoring + documentation).  
**Deliverable:** `docs/operations/QUEUE_HEALTH_REFERENCE_001.md`

---

### P1-2 — Webhook Latency Tracking

**Gap:** No measurement exists for the time between a send completing (`send_attempts.created_at` where status=DELIVERED) and the webhook reconciling it (`send_attempts.reconciled_at`). If Resend webhook delivery is degrading, the operator has no signal.

**Implementation:** SQL query (no schema change — `reconciled_at` already exists):

```sql
-- Webhook latency: time from send to reconciliation
SELECT
  sa.draft_id,
  sa.provider_message_id,
  sa.created_at                              AS sent_at,
  sa.reconciled_at,
  sa.reconciled_at - sa.created_at          AS reconciliation_latency,
  CASE
    WHEN sa.reconciled_at IS NULL
     AND NOW() - sa.created_at > INTERVAL '2 hours'
    THEN 'ALERT: webhook delayed > 2h'
    WHEN sa.reconciled_at IS NULL
    THEN 'pending'
    ELSE 'reconciled'
  END                                        AS status
FROM send_attempts sa
WHERE sa.workspace_id = '<ws_id>'
  AND sa.status = 'DELIVERED'
ORDER BY sa.created_at DESC;
```

**Escalation threshold:** Any `DELIVERED` row with `reconciled_at IS NULL` and `sent_at > 2 hours ago` requires investigation of Resend webhook delivery.

**Effort:** 1 hour (documentation).

---

### P1-3 — Failure Classification Reference

**Gap:** When a send fails, the operator sees `failure_code` and `failure_reason` in `send_attempts` but has no reference for what each code means, whether it is recoverable, and what the correct response is.

**Implementation:** A failure code reference table (documentation only):

| `failure_code` | Source | Recoverable? | Operator action |
|----------------|--------|-------------|-----------------|
| `assertion_failed` | Pre-send assertion blocked | Usually yes | Review draft state; re-enqueue if resolved |
| `resend_rate_limit` | Resend 429 response | Yes | Will retry via backoff |
| `resend_invalid_to` | Resend 422 invalid recipient | No | Mark draft invalid; do not re-enqueue |
| `resend_error` | Other Resend API error | Maybe | Check Resend status page; retry if transient |
| `exception` | Unhandled exception in dispatch | Maybe | Check full log trace; investigate root cause |
| `lost_send_pre_claim_crash` | Crash between pre-send claim and Resend call | Yes | Email was NOT sent; safe to re-enqueue |
| `bounce` | email.bounced webhook | No | Recipient address invalid or rejected |
| `max_retries_exceeded` | retry_count >= max_retries | No | Draft permanently failed; do not re-enqueue |

**Effort:** 2 hours (documentation).  
**Deliverable:** Section in `QUEUE_HEALTH_REFERENCE_001.md`.

---

### P1-4 — Replay Tooling (Safe Re-Enqueue Procedure)

**Gap:** When a draft fails with `lost_send_pre_claim_crash` (email not sent, safe to retry), there is no documented safe re-enqueue procedure. An operator who manually inserts into `outbound_queue` without resetting `outreach_drafts.sent_at` will hit an ALREADY_DELIVERED outcome on the next dispatch.

**Implementation:** Documented re-enqueue SQL procedure:

```sql
-- Safe re-enqueue for a lost_send_pre_claim_crash draft
-- Step 1: Confirm the draft was NOT sent (resend_message_id should be NULL)
SELECT id, sent_at, resend_message_id FROM outreach_drafts WHERE id = '<draft_id>';
-- If resend_message_id IS NOT NULL, the email WAS sent — do NOT re-enqueue.

-- Step 2: Reset sent_at (only if resend_message_id IS NULL)
UPDATE outreach_drafts
SET sent_at = NULL
WHERE id = '<draft_id>'
  AND resend_message_id IS NULL;
-- Confirm: 1 row updated

-- Step 3: Reset send_attempt status to allow re-dispatch
-- (or leave FAILED row and let a new DISPATCHED row be created on next dispatch)

-- Step 4: Re-enqueue
INSERT INTO outbound_queue (draft_id, workspace_id, priority)
VALUES ('<draft_id>', '<ws_id>', 5)
ON CONFLICT DO NOTHING;

-- Step 5: Confirm queue contains the re-enqueued row
SELECT * FROM outbound_queue WHERE draft_id = '<draft_id>';
```

**Authorization gate:** Re-enqueue requires explicit Avanish authorization. This SQL must not be executed autonomously.

**Effort:** 2 hours (documentation + safety validation).

---

### P1-5 — Scheduler Heartbeat External Check

**Gap:** APScheduler runs inside the Railway process. If the process restarts mid-window, the scheduler re-registers but may miss a tick. Currently the only evidence is the absence of log lines — which requires the operator to actively watch logs.

**Implementation:** Add a heartbeat endpoint (read-only, no behavioral change):

```python
@router.get("/api/admin/scheduler-health")
def scheduler_health():
    """Returns APScheduler job list and next fire times."""
    from backend.app.api.main import _scheduler
    if _scheduler is None:
        return {"status": "not_initialized", "jobs": []}
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return {"status": "running", "jobs": jobs}
```

**Effort:** 2 hours (implementation + test).  
**Risk if deferred:** Scheduler silently stops running. Only discovered when Monday has no log entries.

---

### P1-6 — Forensic Reconstruction Query

**Gap:** After a send completes (or fails), there is no single query that reconstructs the full lifecycle of a draft through the dispatch system. An operator investigating an anomaly must join 3+ tables manually.

**Implementation:** A canonical forensic query:

```sql
-- Full dispatch lifecycle for a single draft
SELECT
  d.id                          AS draft_id,
  d.approval_status,
  d.sent_at,
  d.resend_message_id,
  oq.id                         AS queue_row_id,
  oq.enqueued_at,
  oq.retry_count,
  oq.locked_by,
  oq.locked_at,
  oq.next_retry_at,
  sa.id                         AS attempt_id,
  sa.attempt_number,
  sa.idempotency_key,
  sa.status                     AS attempt_status,
  sa.provider_message_id,
  sa.failure_code,
  sa.failure_reason,
  sa.reconciled_at,
  sa.created_at                 AS attempt_created_at,
  sa.resolved_at                AS attempt_resolved_at
FROM outreach_drafts d
LEFT JOIN outbound_queue oq ON oq.draft_id = d.id
LEFT JOIN send_attempts sa ON sa.draft_id = d.id
WHERE d.id = '<draft_id>'
ORDER BY sa.attempt_number NULLS LAST;
```

**Effort:** 1 hour (documentation).

---

## P2 — LATER HARDENING (Stage 4+ / operational scale)

These items are not urgent but should exist before daily_limit exceeds 25.

---

### P2-1 — Provider Degradation Alert (Resend API)

**Trigger condition:** If 3 or more `TRANSIENT_FAILED` outcomes occur within a single send window, it likely indicates Resend API degradation rather than individual draft failures.

**Implementation:** Post-window SQL check (no new infrastructure):
```sql
SELECT COUNT(*) AS transient_failures_today
FROM send_attempts
WHERE workspace_id = '<ws_id>'
  AND status = 'FAILED'
  AND failure_code IN ('resend_rate_limit', 'resend_error', 'exception')
  AND created_at >= CURRENT_DATE;
-- If > 3: check status.resend.com before next dispatch window
```

---

### P2-2 — Duplicate Send Detection Query

**Gap:** With idempotency keys, Resend should prevent duplicate sends at the provider level. But if the idempotency key format changes or a bug allows two DISPATCHED rows for the same draft_id, the operator needs to detect it.

```sql
-- Duplicate send detection
SELECT draft_id, COUNT(*) AS attempt_count
FROM send_attempts
WHERE status IN ('DELIVERED', 'DISPATCHED')
GROUP BY draft_id
HAVING COUNT(*) > 1;
-- Expected: 0 rows always
-- Run after every Stage 3+ window
```

---

### P2-3 — Operational Audit Export

**Requirement:** For each send cohort, produce a structured export showing: draft_id, recipient, sent_at, provider_message_id, reconciled_at, outcome, failure_code. This becomes the send-cohort evidence artifact.

```sql
-- Cohort send audit export
SELECT
  sa.draft_id,
  sa.idempotency_key,
  sa.attempt_number,
  sa.status,
  sa.provider_message_id,
  sa.failure_code,
  sa.reconciled_at,
  sa.created_at     AS dispatched_at,
  sa.resolved_at
FROM send_attempts sa
WHERE sa.workspace_id = '<ws_id>'
ORDER BY sa.created_at;
```

---

### P2-4 — Admin API: Queue State Endpoint

**Gap:** All queue health monitoring requires direct DB access (Supabase SQL editor). An authenticated admin endpoint would allow verification without DB credentials.

**Scope:** Read-only endpoint returning queue row count, locked count, send_attempts count, and send_config state.

**Defer until:** daily_limit > 25 or Stage 4 begins.

---

### P2-5 — Stale Lock Age Alert

**Gap:** `reclaim_stale_locks` reclaims rows silently (debug log). If a row has been locked for > 10 minutes without being reclaimed (e.g., reclaim loop stopped), no alert fires.

**Implementation:** Add to post-window verification SQL:
```sql
SELECT id, draft_id, locked_at, NOW() - locked_at AS lock_age
FROM outbound_queue
WHERE locked_by IS NOT NULL
  AND locked_at < NOW() - INTERVAL '10 minutes';
-- If any rows: reclaim loop may have stopped — investigate
```

---

## Implementation Sequence

| Priority | Item | Effort | Gate |
|----------|------|--------|------|
| P0-1 | Railway log alert: PERMANENTLY_FAILED | 15 min | Before Stage 1 |
| P0-2 | Railway log alert: unexpected dispatch | 10 min | Before Stage 1 |
| P0-3 | Single-block verification SQL | 30 min | Before Stage 1 |
| P0-4 | Webhook endpoint reachability test | 20 min | Before Stage 1 |
| P1-1 | Queue health SQL dashboard | 2 hrs | Before Stage 3 |
| P1-2 | Webhook latency tracking | 1 hr | Before Stage 3 |
| P1-3 | Failure classification reference | 2 hrs | Before Stage 3 |
| P1-4 | Replay tooling (safe re-enqueue) | 2 hrs | Before Stage 3 |
| P1-5 | Scheduler heartbeat endpoint | 2 hrs | Before Stage 3 |
| P1-6 | Forensic reconstruction query | 1 hr | Before Stage 3 |
| P2-1 | Provider degradation alert SQL | 1 hr | Before Stage 4 |
| P2-2 | Duplicate send detection | 1 hr | Before Stage 4 |
| P2-3 | Operational audit export | 1 hr | Before Stage 4 |
| P2-4 | Admin API queue state endpoint | 4 hrs | Stage 4+ |
| P2-5 | Stale lock age alert | 1 hr | Stage 4+ |

**Total P0:** ~75 minutes (mostly console actions)  
**Total P1:** ~10 hours (SQL + one code endpoint)  
**Total P2:** ~8 hours (SQL + one API endpoint)

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/OPERATIONAL_MATURITY_ROADMAP_001.md`
