# Atomic Dispatch Correctness Validation — 001
## ProspectIQ — D5: Pre-Send Claim Semantics for dispatch_queued_draft

**Document date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** IMPLEMENTATION COMPLETE — staging soak required before production activation  
**PR:** D5 — `bugfix/dispatch-atomic-sent-at-claim`

---

## 1. Problem Statement

`dispatch_queued_draft` (engagement.py) originally set `sent_at` **after** the Resend API call succeeded (line 1244, labeled "non-fatal"). This created a crash window where the system could double-send to a contact.

### Failure Window: Scenario B (Critical)

```
Timeline:
  T0  dispatch_workspace: claim_outbound_queue_batch → row locked
  T1  dispatch_workspace: _insert_send_attempt (status=DISPATCHED)
  T2  dispatch_queued_draft: assertions pass
  T3  dispatch_queued_draft: resend.Emails.send() called → Resend ACCEPTS (202)
  T4  *** PROCESS CRASH *** (OOM, Railway restart, uncaught exception)
      sent_at = NULL in outreach_drafts (never set)
      queue row = locked (locked_by=instance_id)
      send_attempts = DISPATCHED (never updated to DELIVERED)
      Resend = email queued for delivery ← UNRECOVERABLE from code perspective
  T5  (5 minutes later) reclaim_stale_locks clears the lock
  T6  dispatch_workspace: claims the same row again (new instance_id, retry_count=1)
  T7  _insert_send_attempt: attempt_number=2, idempotency_key="draft_id:2"
  T8  dispatch_queued_draft: assertions pass (sent_at still NULL → proceeds)
  T9  resend.Emails.send(idempotency_key="draft_id:2")
      → NEW idempotency key → Resend's 24h dedup does NOT apply
      → EMAIL DELIVERED TWICE TO CONTACT
```

**Root cause:** The only duplicate-send barrier was Resend's idempotency key. Because each retry increments `attempt_number`, each crash produces a different idempotency key. Resend dedup only covers identical keys.

---

## 2. Failure Window Analysis (All Five Scenarios)

| Scenario | Crash point | Before fix | After fix (D5) |
|----------|-------------|-----------|---------------|
| A | After claim, before assertions | Safe: no Resend call yet. Stale reclaim → reassert → normal retry. | Same (no change to this path). |
| B | After `resend.Emails.send()`, before `sent_at` set | **CRITICAL: duplicate send on retry** — new idempotency key bypasses Resend dedup. | Fixed: `sent_at` set pre-call; retry finds `sent_at` set → ALREADY_DELIVERED → queue row drained. No retry to Resend. |
| C | After `sent_at` set, before `_delete_queue_row()` | **STUCK LOOP: ASSERTION_FAILED loop forever** — lock reclaimed, re-claimed, assertion guard detects `sent_at`, returns ASSERTION_FAILED, lock released, repeat until max_retries exhausted → `dispatch_failed`. | Fixed: `sent_at` detected at fetch → ALREADY_DELIVERED → queue row drained. |
| D | After `resend.Emails.send()` raises exception | Safe: send rejected by Resend, no delivery. Retry via TRANSIENT/PERMANENTLY_FAILED. | Enhanced: `sent_at` is now rolled back on exception, ensuring retry sees `sent_at=NULL` and correctly re-dispatches. Without rollback, `sent_at` would remain set after TRANSIENT_FAILED, causing ALREADY_DELIVERED on retry. |
| E | After pre-send claim, before `resend.Emails.send()` | N/A (claim did not exist). | New rare case: `sent_at` set, Resend never called. On retry: ALREADY_DELIVERED. Email not delivered but draft shows `sent_at`. Acceptable trade-off vs. duplicate-send; same risk exists in legacy path's atomic claim. |

**Scenario E (new) trade-off:** A crash between the pre-send claim and the Resend call leaves `sent_at` set with no email delivered. The draft is not re-sent. This is intentional — an undelivered draft is less harmful than a duplicate send. The window for this scenario is the latency of a single Python statement (nanoseconds to microseconds) before the `try` block around `resend.Emails.send()`.

---

## 3. Implementation

### 3.1 Changes in `engagement.py`

**Change 1: `QueueDispatchOutcome` Literal extended**

```python
# Before
status: Literal["DELIVERED", "TRANSIENT_FAILED", "PERMANENTLY_FAILED", "ASSERTION_FAILED"]

# After
status: Literal["DELIVERED", "TRANSIENT_FAILED", "PERMANENTLY_FAILED", "ASSERTION_FAILED", "ALREADY_DELIVERED"]
```

**Change 2: Early-exit guard updated**

```python
# Before (line 1084 original)
if draft.get("sent_at"):
    return QueueDispatchOutcome(status="ASSERTION_FAILED", failure_reason="draft_already_sent")

# After
if draft.get("sent_at"):
    logger.warning("dispatch_queued_draft already_delivered_at_fetch ...")
    return QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="draft_sent_at_set_at_fetch")
```

Rationale: ASSERTION_FAILED released the lock but left the queue row alive, causing an infinite reclaim→re-dispatch loop. ALREADY_DELIVERED signals dispatch_workspace to drain the queue row.

**Change 3: Pre-send atomic claim inserted before `resend.Emails.send()`**

```python
_pre_send_now = datetime.now(timezone.utc).isoformat()
_claim_result = (
    self.db.client.table("outreach_drafts")
    .update({"sent_at": _pre_send_now})
    .eq("id", draft_id)
    .is_("sent_at", "null")
    .execute()
)
# if not _claim_result.data: return ALREADY_DELIVERED
```

**Change 4: Rollback on Resend exception**

```python
except Exception as send_exc:
    # Roll back sent_at so retry path sees NULL and can re-dispatch safely
    self.db.client.table("outreach_drafts").update({"sent_at": None}).eq("id", draft_id).execute()
    ...return TRANSIENT_FAILED / PERMANENTLY_FAILED
```

**Change 5: Post-send update only writes `resend_message_id`**

```python
# Before: updated both sent_at and resend_message_id
# After: updates only resend_message_id (sent_at already set by pre-send claim)
self.db.update_outreach_draft(draft_id, {"resend_message_id": resend_id})
```

The `now` variable used in subsequent post-send operations (interactions, campaign_threads, etc.) is set to `_pre_send_now` — consistent timestamps throughout.

### 3.2 Changes in `dispatch_scheduler.py`

**Change 6: `BatchResult.already_delivered_drained` counter added**

```python
@dataclass
class BatchResult:
    ...
    already_delivered_drained: int = 0
```

**Change 7: ALREADY_DELIVERED handler in `dispatch_workspace()`**

```python
elif outcome.status == "ALREADY_DELIVERED":
    _update_send_attempt(db_client, attempt_id, status="DELIVERED",
                         failure_reason=f"already_delivered_drain: {outcome.failure_reason}",
                         resolved_at=_now_iso())
    _delete_queue_row(db_client, queue_row_id)
    result.already_delivered_drained += 1
    logger.warning("dispatch.already_delivered_drain draft_id=%s ...", draft_id, ...)
```

The send_attempt row is marked `DELIVERED` (consistent with the CHECK constraint: `'DISPATCHED', 'DELIVERED', 'FAILED', 'PERMANENTLY_FAILED'`). The `failure_reason` field records the drain context. No schema migration required.

D6 will enhance this handler with webhook reconciliation to verify the actual provider delivery status before committing to `DELIVERED`.

### 3.3 Changes in `main.py`

**Change 8:** Dispatch log message updated to include `already_delivered_drained=%d`.

---

## 4. Invariant Analysis Post-Fix

| Invariant | Before D5 | After D5 |
|-----------|----------|---------|
| No Resend call without `send_attempts` DISPATCHED row | HELD | HELD |
| `sent_at` is set before the Resend call | VIOLATED | HELD |
| No duplicate send on crash-and-retry | VIOLATED (Scenario B) | HELD |
| Stuck queue row clears within one retry cycle | VIOLATED (Scenario C: infinite loop) | HELD |
| Retries see correct `sent_at=NULL` state after Resend failure | NOT APPLICABLE | HELD (rollback) |
| `dispatch_failed` only set on permanent failures, not on already-sent drafts | VIOLATED (Scenario C eventual) | HELD |

---

## 5. Test Coverage

9 tests added in `backend/tests/test_d5_atomic_dispatch_claim.py`:

| Test class | Tests | What is verified |
|-----------|-------|-----------------|
| `TestAlreadyDeliveredAtFetch` | 2 | `sent_at` set at draft fetch → ALREADY_DELIVERED; Resend never called |
| `TestPreSendClaimReturnsZeroRows` | 1 | Pre-send claim returns 0 rows → ALREADY_DELIVERED; Resend never called |
| `TestRollbackOnResendFailure` | 2 | Transient failure rolls back `sent_at`; permanent failure rolls back `sent_at` |
| `TestAlreadyDeliveredDrainInDispatchWorkspace` | 2 | ALREADY_DELIVERED → queue row deleted; `dispatch_failed` NOT set |
| `TestBatchResultCounters` | 2 | `already_delivered_drained` field exists; ALREADY_DELIVERED status accepted |

All 9 tests pass. Full suite: 202 tests passed (9 new + 193 pre-existing), 0 failures.

---

## 6. Staging Soak Protocol

Before this PR is deployed to production:

### 6.1 Staging Environment Setup

```
SEND_ENABLED=true  (staging only)
batch_size=1
max_retries=4
Queue: populated with 1-2 sink-recipient drafts (email addresses you control)
```

**Do NOT enable SEND_ENABLED in production. This soak is staging-only.**

### 6.2 Happy Path Validation

Execute one complete dispatch cycle in staging:

```
Pre-condition:
  outbound_queue: 1 row, unlocked, sent_at=NULL in outreach_drafts

Trigger: POST /api/admin/trigger-dispatch (or wait for cron tick)

Expected log sequence:
  1. dispatch_workspace called
  2. _insert_send_attempt: attempt 1, status=DISPATCHED
  3. dispatch_queued_draft: pre-send claim UPDATE returned 1 row
  4. resend.Emails.send(idempotency_key="draft_id:1") → 202 accepted
  5. sent_at already set (pre-claim) — no second update
  6. resend_message_id updated
  7. dispatch_workspace: DELIVERED, send_attempt → DELIVERED, queue row deleted

Post-condition:
  outbound_queue: 0 rows
  send_attempts: 1 row, status=DELIVERED, provider_message_id set
  outreach_drafts: sent_at set, resend_message_id set
  Email: received at sink address
```

### 6.3 Crash Simulation: Scenario B (Verify duplicate-send prevention)

```
1. Pause the process immediately after resend.Emails.send() by inserting a test hook
   (or simulate by manually setting sent_at on a queue row and re-triggering dispatch)
2. Confirm: second dispatch attempt returns ALREADY_DELIVERED
3. Confirm: send_attempt updated to DELIVERED, queue row deleted
4. Confirm: no second Resend call in logs
5. Confirm: only one email received at sink address
```

### 6.4 Rollback Simulation: Verify sent_at reset on failure

```
1. Inject a Resend exception (mock or staging API key error)
2. Confirm: sent_at is NULL in outreach_drafts after the exception
3. Confirm: TRANSIENT_FAILED or PERMANENTLY_FAILED returned
4. Confirm: retry succeeds on next attempt (sent_at=NULL allows re-dispatch)
```

### 6.5 ALREADY_DELIVERED Drain Simulation

```
1. Manually set sent_at on an outreach_drafts row that has a queue row
   (simulates Scenario C: crash after pre-send claim, before queue deletion)
2. Trigger dispatch_loop
3. Confirm: ALREADY_DELIVERED returned at fetch-time check
4. Confirm: queue row deleted
5. Confirm: already_delivered_drained=1 in dispatch log
6. Confirm: draft NOT marked dispatch_failed
```

### 6.6 Timestamp Capture Requirements

For each validation step, capture:

```sql
-- Before dispatch
SELECT id, sent_at, resend_message_id, approval_status FROM outreach_drafts WHERE id = :draft_id;
SELECT id, status, attempt_number, idempotency_key, provider_message_id, dispatched_at, resolved_at
  FROM send_attempts WHERE draft_id = :draft_id ORDER BY attempt_number;
SELECT id, locked_by, locked_at, retry_count FROM outbound_queue WHERE draft_id = :draft_id;

-- After dispatch
-- Same queries — capture timestamps for diff
```

---

## 7. Production Deployment Authorization

This PR may be deployed to production after:

```
[ ] Staging happy-path validation complete (Section 6.2)
[ ] Scenario B duplicate-prevention confirmed (Section 6.3)
[ ] Rollback behavior confirmed (Section 6.4)
[ ] ALREADY_DELIVERED drain confirmed (Section 6.5)
[ ] Avanish authorization: "authorize D5 production deployment"
[ ] SEND_ENABLED remains false in production at time of deployment
```

Note: Deploying with `SEND_ENABLED=false` is safe. No behavioral change until SEND_ENABLED is activated. The pre-send claim logic is only reached after the `SEND_ENABLED` env gate.

---

## 8. Rollback Procedure

If D5 causes unexpected behavior after deployment:

1. Revert the PR (uncomment the old `sent_at` post-send block, remove pre-send claim)
2. Deploy the revert
3. Confirm scheduler behavior returns to pre-D5 state via `/api/admin/send-trace`
4. Document the observed anomaly before re-attempting

**Risk assessment:** Low. The change is additive — new code paths are only reached when the queue path is active. The pre-send claim is a standard Supabase `.update().is_("sent_at", "null")` pattern identical to the legacy path. The rollback restores the original non-fatal post-send update.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/ATOMIC_DISPATCH_CORRECTNESS_VALIDATION_001.md`  
**Prerequisite documents:** `DELIVERY_CORRECTNESS_ANALYSIS_001.md`, `DARK_LAUNCH_RUNTIME_OBSERVATION_003.md`
