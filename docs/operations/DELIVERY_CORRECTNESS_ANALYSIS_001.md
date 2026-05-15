# Delivery Correctness Analysis — 001
## ProspectIQ — Workstreams 1, 2, 3: Webhook Lifecycle, Exactly-Once Safety, Queue Drain

**Date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** CODE-GROUNDED ANALYSIS — all findings verified against production source  
**Source files analyzed:**
- `backend/app/core/dispatch_scheduler.py` (full)
- `backend/app/agents/engagement.py` (dispatch_queued_draft + _send_approved_drafts)
- `backend/app/api/routes/webhooks.py` (Resend webhook handler)
- `backend/app/core/config.py` (Settings)

---

## 1. Delivery Lifecycle — Complete Flow

### 1.1 New Queue Path (dispatch_loop → dispatch_scheduler.py → engagement.py)

```
dispatch_loop cron fires
  └─ _dispatch_workspace() checks get_settings().send_enabled
       └─ if false: return immediately (dark-launch gate)
       └─ if true: reads outreach_send_config (batch_size, max_retries)
            └─ dispatch_workspace() called
                 └─ claim_outbound_queue_batch() RPC (FOR UPDATE SKIP LOCKED)
                      └─ claimed rows locked in DB (locked_by=instance_id, locked_at=now)
                      └─ for each claimed row:
                           ├─ idempotency_key = f"{draft_id}:{attempt_number}"
                           ├─ _insert_send_attempt() → status=DISPATCHED (MUST succeed)
                           │    └─ if INSERT fails: _release_queue_lock(), skip row
                           └─ agent.dispatch_queued_draft(queue_row, attempt_number, idempotency_key)
                                ├─ fetch fresh draft+contact+company
                                ├─ GUARD: if draft.sent_at is not null → ASSERTION_FAILED
                                ├─ run suppression + company-lock + pre-send assertions
                                ├─ resend.Emails.send(..., idempotency_key=idempotency_key)
                                ├─ ON SUCCESS:
                                │    ├─ outreach_drafts.sent_at = now  [POST-SEND, non-fatal]
                                │    ├─ outreach_drafts.resend_message_id = resend_id
                                │    ├─ interactions INSERT
                                │    └─ return DELIVERED(provider_message_id=resend_id)
                                └─ ON FAILURE:
                                     └─ return TRANSIENT_FAILED or PERMANENTLY_FAILED

                      After dispatch_queued_draft returns:
                           DELIVERED:
                             ├─ _update_send_attempt(DELIVERED, provider_message_id, resolved_at)
                             └─ _delete_queue_row()

                           ASSERTION_FAILED:
                             ├─ _update_send_attempt(FAILED, assertion_failed, resolved_at)
                             └─ _release_queue_lock()  [row stays in queue]

                           TRANSIENT_FAILED (< max_retries):
                             ├─ _update_send_attempt(FAILED, failure_code, resolved_at)
                             └─ _schedule_retry()  [sets next_retry_at, releases lock]

                           TRANSIENT_FAILED (>= max_retries):
                             ├─ _update_send_attempt(PERMANENTLY_FAILED, ...)
                             ├─ _mark_draft_dispatch_failed()  [approval_status=dispatch_failed]
                             └─ _delete_queue_row()

                           PERMANENTLY_FAILED:
                             ├─ _update_send_attempt(PERMANENTLY_FAILED, ...)
                             ├─ _mark_draft_dispatch_failed()
                             └─ _delete_queue_row()
```

### 1.2 Legacy Path (send_approved → EngagementAgent → engagement.py)

```
send_approved cron fires
  └─ _send_approved_workspace() checks get_settings().send_enabled
       └─ if false: return immediately
       └─ agent.run("send_approved") → _send_approved_drafts()
            ├─ reads DB send_config (send_enabled, daily_limit, batch_size)
            ├─ checks send_window_start/send_window_end (UTC hours)
            ├─ for each eligible draft:
            │    ├─ ATOMIC CLAIM: UPDATE outreach_drafts SET sent_at=now
            │    │    WHERE id=draft_id AND sent_at IS NULL
            │    │    (conditional update — only one process can claim)
            │    ├─ resend.Emails.send(idempotency_key=draft["id"])
            │    ├─ ON SUCCESS: record interactions, update company/contact state
            │    └─ ON FAILURE: _rollback_sent_at() — sets sent_at=NULL
            │         (if rollback also fails: ORPHANED DRAFT logged as critical)
            └─ (no send_attempts table involvement)
```

**Critical difference between paths:**
- Legacy path: `sent_at` claimed ATOMICALLY BEFORE Resend call → crash-safe for deduplication
- Queue path: `sent_at` set POST-SEND (non-fatal, line 1244) → crash window exists between Resend call and `sent_at` update

---

## 2. Crash Analysis — Every Failure Point

The following analysis covers every point at which a process crash could affect correctness.

### 2.1 Crash Before `_insert_send_attempt()`

**State at crash:**
- Queue row: locked (`locked_by=instance_id`, `locked_at=T`)
- `send_attempts`: no row created
- `outreach_drafts`: unchanged (sent_at=NULL)
- Email: not sent

**Recovery:**
1. After `STALE_LOCK_MINUTES=5`: `reclaim_stale_locks` releases the lock
2. Next cron tick: `claim_outbound_queue_batch` claims the row again
3. `attempt_number = retry_count + 1 = 1` (retry_count not incremented for this case)
4. New `_insert_send_attempt()` with key `{draft_id}:1`
5. Resend call with `{draft_id}:1` → email sent

**Outcome: SAFE — no duplicate send, no data loss.**

### 2.2 Crash After `_insert_send_attempt()`, Before Resend Call

**State at crash:**
- Queue row: locked
- `send_attempts`: 1 row with `status=DISPATCHED`, `attempt_number=1`, `idempotency_key={draft_id}:1`
- `outreach_drafts`: unchanged (sent_at=NULL)
- Email: not sent

**Recovery:**
1. After 5 minutes: lock released by reclaim
2. Next cron tick: `attempt_number = retry_count + 1 = 1` (retry_count unchanged)
3. New `_insert_send_attempt()` with key `{draft_id}:1`
4. This INSERT MAY fail if `send_attempts` has a unique constraint on (draft_id, attempt_number) — or may succeed creating a second attempt_number=1 row if no such constraint exists

**Finding: `send_attempts` has no confirmed UNIQUE constraint on (draft_id, attempt_number).** If two DISPATCHED rows for attempt_number=1 can exist, the state becomes ambiguous.

**If INSERT succeeds (no unique constraint):** New DISPATCHED row. Resend call fires with same `{draft_id}:1` key. Resend deduplicates via idempotency_key → only one email delivered.

**Outcome: SAFE for sends (Resend deduplication works). DATA QUALITY: orphaned DISPATCHED row from attempt 1 will remain in DISPATCHED state forever unless manually cleaned.**

### 2.3 Crash After Resend Call, Before `outreach_drafts.sent_at` Set — **CRITICAL**

**State at crash:**
- Queue row: locked
- `send_attempts`: DISPATCHED row for attempt 1
- `outreach_drafts.sent_at`: NULL (not yet set — this is a POST-SEND update labeled "non-fatal")
- Email: SENT to recipient (Resend accepted the call)

**Recovery:**
1. After 5 minutes: lock released by reclaim
2. Next cron tick: `retry_count=0`, `attempt_number = 0+1 = 1`
3. `dispatch_queued_draft` called: `draft.get("sent_at")` is NULL → guard NOT triggered
4. Pre-send assertions pass (contact not suppressed, etc.)
5. Resend call with `idempotency_key="{draft_id}:1"` — **SAME KEY as first send**

**Resend idempotency behavior:** If the first Resend API call completed and Resend accepted it, the idempotency_key `{draft_id}:1` is already registered. A second call with the same key within Resend's deduplication window (typically 24 hours) returns the original message ID without sending again.

**HOWEVER:** If Resend's deduplication window has expired (24h+), or if the idempotency record was lost at Resend, the second call will trigger a new send. **This is a real duplicate send risk for drafts that remain in orphaned-lock state for more than 24 hours.**

**Practical assessment:** The 5-minute reclaim TTL means re-dispatch occurs within 5–7 minutes of the crash. Resend's 24-hour deduplication window is almost certainly still active. In practice, the duplicate is blocked by Resend deduplication.

**However, this is a correctness guarantee that depends on Resend's external behavior, not the application's internal invariants.** It is not a first-party safety guarantee.

**Outcome: POTENTIALLY UNSAFE — relies on Resend idempotency rather than application-controlled deduplication. Severity depends on Resend's deduplication window enforcement.**

### 2.4 Crash After `outreach_drafts.sent_at` Set, Before dispatch_scheduler DELIVERED Update

**State at crash:**
- Queue row: locked
- `send_attempts`: DISPATCHED row (not yet DELIVERED)
- `outreach_drafts.sent_at`: SET (email sent)
- `outreach_drafts.resend_message_id`: SET

**Recovery:**
1. After 5 minutes: lock released
2. Next cron tick: `dispatch_queued_draft` called
3. `draft.get("sent_at")` is NOT NULL → returns `ASSERTION_FAILED`
4. `dispatch_scheduler.py` handles ASSERTION_FAILED: `_update_send_attempt(FAILED, assertion_failed)` + `_release_queue_lock()`
5. Queue row remains in queue (lock released)
6. Next tick: same path → ASSERTION_FAILED → lock released → **queue row will loop forever**

**Outcome: NO DUPLICATE SEND (safe). STUCK QUEUE ROW: the queue row can never be deleted because:**
- DELIVERED deletion path requires `dispatch_queued_draft` to return DELIVERED
- But `dispatch_queued_draft` returns ASSERTION_FAILED when sent_at is set
- ASSERTION_FAILED path releases the lock but does NOT delete the row

**Required resolution:** dispatch_scheduler.py must detect the ASSERTION_FAILED-with-draft-already-sent case and delete the queue row rather than releasing the lock. Or `dispatch_queued_draft` must return a distinct `ALREADY_DELIVERED` status that triggers queue row deletion.

### 2.5 Crash After `_update_send_attempt(DELIVERED)`, Before `_delete_queue_row()`

**State at crash:**
- Queue row: locked
- `send_attempts`: DELIVERED row
- `outreach_drafts.sent_at`: SET

**Recovery:** Same as 2.4 — ASSERTION_FAILED loop, ghost queue row.

**Outcome: NO DUPLICATE SEND. STUCK QUEUE ROW (same as 2.4).**

---

## 3. Summary: Crash Failure Matrix

| Crash Point | Duplicate Send? | Data Hazard | Recovery |
|-------------|----------------|-------------|---------|
| Before send_attempt INSERT | No | None | Reclaim → re-dispatch ✓ |
| After send_attempt INSERT, before Resend | No (same key) | Orphaned DISPATCHED row | Reclaim → re-dispatch with same key; Resend deduplicates ✓ |
| After Resend call, before sent_at set | Reliant on Resend 24h dedup | DISPATCHED row never resolved | **MITIGATE: set sent_at pre-call** |
| After sent_at set, before DELIVERED update | No | Ghost queue row (stuck ASSERTION_FAILED loop) | **MITIGATE: ALREADY_DELIVERED status** |
| After DELIVERED update, before queue delete | No | Ghost queue row (stuck ASSERTION_FAILED loop) | **MITIGATE: ALREADY_DELIVERED status** |

---

## 4. Required Fixes — Two Changes, Both PRs

### Fix 1 — Atomic Pre-Send `sent_at` Claim (engagement.py)

**Problem:** `sent_at` is currently set POST-SEND in `dispatch_queued_draft` (line 1244), labeled "non-fatal". This creates a window between Resend accepting the call and the sent_at update where a crash causes reliance on Resend's external deduplication.

**Fix:** Before calling `resend.Emails.send()`, perform an atomic conditional UPDATE:
```python
# Atomic pre-send claim — prevents duplicate dispatch if process crashes after send
claim_result = db_client.table("outreach_drafts").update({
    "sent_at": now_pre_send,
}).eq("id", draft_id).is_("sent_at", "null").execute()

if not claim_result.data:
    # Another process already claimed this draft — assertion failure, not a real error
    return QueueDispatchOutcome(status="ASSERTION_FAILED", failure_reason="concurrent_sent_at_claim")
```

This mirrors the legacy path's claim at line 593-601. A rollback should be added (set `sent_at=NULL` if Resend call fails), matching the legacy `_rollback_sent_at()` pattern.

**Effect:** Eliminates crash scenario 2.3 entirely. Crash after pre-claim but before Resend → `sent_at` is set; next claim returns ASSERTION_FAILED; no duplicate send.

**Trade-off introduced:** The pre-claim + rollback model has its own edge case (orphaned sent_at if rollback also fails). The legacy path already handles this with `_rollback_sent_at()` and logs the ORPHANED DRAFT condition. The dispatch path should implement the same rollback.

### Fix 2 — ALREADY_DELIVERED Queue Row Cleanup (dispatch_scheduler.py or dispatch_queued_draft)

**Problem:** When ASSERTION_FAILED is returned because `sent_at` is already set (scenarios 2.4, 2.5), the queue row loops indefinitely (lock released → reclaim → re-claim → ASSERTION_FAILED → repeat).

**Fix option A (in dispatch_queued_draft):** Return a distinct `ALREADY_DELIVERED` status when `draft.sent_at is not null`:
```python
if draft.get("sent_at"):
    return QueueDispatchOutcome(status="ALREADY_DELIVERED", failure_reason="draft_already_sent")
```

In `dispatch_scheduler.py`, handle `ALREADY_DELIVERED` by deleting the queue row:
```python
elif outcome.status == "ALREADY_DELIVERED":
    _update_send_attempt(db_client, attempt_id, status="DELIVERED",
                         failure_reason="already_sent_at_claim_existed",
                         resolved_at=_now_iso())
    _delete_queue_row(db_client, queue_row_id)
    result.delivered += 1  # counts as delivered for idempotency
```

**Fix option B (in dispatch_scheduler.py):** Check `sent_at` before calling `dispatch_queued_draft`:
```python
# Check for pre-existing sent_at before dispatch
draft_check = db_client.table("outreach_drafts").select("sent_at").eq("id", draft_id).execute()
if draft_check.data and draft_check.data[0].get("sent_at"):
    _update_send_attempt(db_client, attempt_id, status="DELIVERED",
                         failure_reason="already_sent", resolved_at=_now_iso())
    _delete_queue_row(db_client, queue_row_id)
    continue
```

Option A is preferred — it keeps the check in the agent where the context is richer.

---

## 5. Resend Webhook Handler — Scope and Gaps

### 5.1 What the Existing Handler Does

File: `backend/app/api/routes/webhooks.py`, route `POST /api/webhooks/resend`

Events handled: `email.delivered`, `email.opened`, `email.clicked`, `email.bounced`, `email.complained`

For each event:
1. Extracts `resend_message_id` from event payload (`data.email_id`)
2. Looks up `outreach_drafts` WHERE `resend_message_id = resend_message_id`
3. Updates `outreach_drafts` fields (bounce, open, click timestamps)
4. Creates `interactions` records
5. For bounces/complaints: creates `suppression_log` entries

### 5.2 Critical Gap — Webhook Does Not Update `send_attempts`

The Resend webhook handler updates `outreach_drafts` directly but does NOT touch `send_attempts`. This means:

- `send_attempts.status = DELIVERED` is set **synchronously** by dispatch_scheduler.py (line 310–315) at dispatch time, not via webhook
- Webhook `email.delivered` event arrives later but has no handler path to `send_attempts`
- A DISPATCHED `send_attempts` row where the dispatch was confirmed synchronously will correctly show DELIVERED
- **But:** If the dispatch call returns DELIVERED and then a bounce arrives via webhook, the `send_attempts` row stays DELIVERED with no bounce indicator

**Resolution needed:** Add bounce/complaint handling to the webhook that also updates any `send_attempts` row with the final provider-confirmed status. This is a Tier 2 quality improvement, not a safety blocker.

### 5.3 Webhook Signature Validation

The webhook handler references `resend_webhook_secret` from settings (config.py line 42: `resend_webhook_secret: str = ""`). The `RESEND_WEBHOOK_SECRET` env var is not confirmed as set in production. Without signature validation, the webhook endpoint accepts unauthenticated payloads.

**Required before production activation:** Set `RESEND_WEBHOOK_SECRET` in Railway production environment and confirm the handler validates the `svix-signature` header on every inbound event.

### 5.4 Duplicate Webhook Handling

The handler at lines 919-920 constructs a deduplication event ID:
```python
_provider_event_id = f"resend:{resend_message_id}:{event_type}"
```

This is used in `provider_events` table deduplication (migration 051 created the `idx_provider_events_dedup` UNIQUE index on `(provider, provider_event_id)`). Duplicate Resend webhooks for the same event are safely deduplicated via this mechanism.

---

## 6. Idempotency Analysis — Current State

### 6.1 Resend API Idempotency Key

Key format: `{draft_id}:{attempt_number}` (dispatch_scheduler.py line 249)

**Properties:**
- Deterministic: regenerated identically for the same draft + attempt number on any retry
- Attempt-scoped: if retry_count=0, key is `{draft_id}:1`; if retry_count=1, key is `{draft_id}:2`
- Resend's deduplication window: typically 24 hours (vendor-defined, not application-controlled)

**Gap:** The key is correctly generated in dispatch_scheduler.py and passed to engagement.py. The key IS passed to `resend.Emails.send(...)` via the call in `dispatch_queued_draft` at line 1221. Confirmed implemented.

### 6.2 Application-Level Idempotency Guarantees

| Mechanism | Implemented | Strength |
|-----------|-------------|---------|
| Resend API idempotency_key | YES | Strong within 24h; external dependency |
| `sent_at` pre-claim (atomic UPDATE WHERE NULL) | NOT in dispatch path | Missing — see Fix 1 |
| `send_attempts` DISPATCHED-before-send | YES (invariant enforced) | Strong — prevents lost attempts |
| Resend webhook deduplication (provider_events) | YES | Strong |
| Queue row ON CONFLICT DO NOTHING | YES | Prevents duplicate enqueue |
| FOR UPDATE SKIP LOCKED | YES | Prevents concurrent claims |
| ASSERTION_FAILED → ALREADY_DELIVERED cleanup | NOT IMPLEMENTED | Required — see Fix 2 |

---

## 7. Queue Drain Semantics — Authoritative Source of Truth

### 7.1 When Queue Rows Are Deleted

Queue rows are deleted from `outbound_queue` in exactly these conditions:

| Condition | Code location | State after deletion |
|-----------|---------------|---------------------|
| Resend call succeeds → DELIVERED outcome | dispatch_scheduler.py line 316 | `outreach_drafts.sent_at` set, `send_attempts.status=DELIVERED` |
| TRANSIENT_FAILED with retry_count >= max_retries | dispatch_scheduler.py line 341 | `outreach_drafts.approval_status=dispatch_failed`, `send_attempts.status=PERMANENTLY_FAILED` |
| PERMANENTLY_FAILED from dispatch_queued_draft | dispatch_scheduler.py line 367 | `outreach_drafts.approval_status=dispatch_failed`, `send_attempts.status=PERMANENTLY_FAILED` |
| Exception in dispatch_queued_draft with retry_count >= max_retries | dispatch_scheduler.py line 295 | Same as above |

Queue rows are NOT deleted in:

| Condition | Action instead |
|-----------|---------------|
| ASSERTION_FAILED | Lock released; row stays for next tick |
| TRANSIENT_FAILED (retries remaining) | next_retry_at set; lock released; row stays |
| Exception (retries remaining) | next_retry_at set; lock released; row stays |
| send_attempt INSERT failure | Lock released; retry_count NOT incremented |

### 7.2 Authoritative Source of Truth for Send Completion

**The canonical send completion record is: `outreach_drafts.sent_at IS NOT NULL`.**

Reasoning:
- Both the legacy path and the dispatch path set `outreach_drafts.sent_at` to confirm delivery
- `send_attempts` with `status=DELIVERED` is the dispatch-path confirmation record, but it is deleted from `outbound_queue` after DELIVERED (the queue row is gone)
- `send_attempts` rows persist permanently and provide the delivery audit trail
- `outreach_drafts.resend_message_id` confirms which Resend message ID corresponds to the send

**What does NOT constitute send completion:**
- Queue row absent (could be absent because PERMANENTLY_FAILED, not just DELIVERED)
- `approval_status = 'approved'` — just means the draft was approved, not sent
- `send_attempts.status = DISPATCHED` — in-flight, not confirmed

### 7.3 Retry Persistence Guarantees

When a queue row is in TRANSIENT_FAILED state:
- `outbound_queue.retry_count` incremented
- `outbound_queue.next_retry_at` set to exponential backoff time (5min, 15min, 1h, 4h)
- `outbound_queue.locked_by` and `locked_at` cleared (lock released)
- Row remains in queue, invisible to `claim_outbound_queue_batch` until `next_retry_at <= NOW()`

After maximum retries (default 4), the draft is marked `dispatch_failed` and the queue row is deleted.

---

## 8. Delivery State Transition Matrix

```
outbound_queue row lifecycle:

 [enqueued]
     │
     ├─ claim_outbound_queue_batch() ──────────────────── [locked]
     │                                                         │
     │   _insert_send_attempt() fails                         │
     │   ──────────────────────────────────────────────── [lock released]
     │                                                         │
     │   dispatch_queued_draft() → DELIVERED                  │
     │   ──────────────────────────────────────────────── [DELETED from queue]
     │                                                         │
     │   dispatch_queued_draft() → ASSERTION_FAILED           │
     │   ──────────────────────────────────────────────── [lock released; back to enqueued]
     │                                                         │
     │   dispatch_queued_draft() → TRANSIENT_FAILED           │
     │   (retries < max)  ──────────────────────────────── [next_retry_at set; back to enqueued]
     │                                                         │
     │   dispatch_queued_draft() → PERMANENTLY_FAILED         │
     │   (or retries >= max) ───────────────────────────── [DELETED from queue]
     │
 [crashed after Resend call, before sent_at set] ────── [stuck: ASSERTION_FAILED loop after reclaim]
     │                                                    [see Fix 2 — ALREADY_DELIVERED path]
     │
send_attempts row lifecycle:

 [DISPATCHED] ──────────────────────────────────────── inserted before Resend call
     │
     ├─ Resend succeeds → [DELIVERED] ────────────────── updated synchronously
     ├─ Resend 5xx/429 → [FAILED] ────────────────────── with retry_count < max
     ├─ Resend 4xx → [PERMANENTLY_FAILED] ───────────── terminal
     ├─ ASSERTION_FAILED → [FAILED] ──────────────────── failure_code=assertion_failed
     └─ Exception → [FAILED or PERMANENTLY_FAILED] ───── depends on retry_count

outreach_drafts.approval_status lifecycle:

 approved/edited ──────────────────────────────────────── initial state
     ├─ send succeeds → approval_status stays 'approved', sent_at IS NOT NULL
     └─ max retries exhausted → approval_status = 'dispatch_failed'

outreach_drafts.sent_at lifecycle (queue path):

 NULL ──────────────────────────────────────────────────── before send
     └─ after resend.Emails.send() succeeds → sent_at = now  [currently POST-SEND]
          [FIX 1: move this to PRE-SEND atomic claim]
```

---

## 9. Test Plan — Before Stage C Authorization

### Unit Tests

| Test | Expected Behavior | File |
|------|------------------|------|
| `dispatch_workspace` with empty claim | Returns BatchResult(0,0,0,0,0,0) immediately | test_dispatch_scheduler.py |
| `dispatch_workspace` with `send_attempt INSERT failure` | Lock released, errors+=1, no Resend call | test_dispatch_scheduler.py |
| `dispatch_queued_draft` with `sent_at` pre-set | Returns ASSERTION_FAILED immediately | test_engagement_dispatch.py |
| `dispatch_queued_draft` with Resend 5xx | Returns TRANSIENT_FAILED | test_engagement_dispatch.py |
| `dispatch_queued_draft` with Resend 4xx | Returns PERMANENTLY_FAILED | test_engagement_dispatch.py |
| `reclaim_stale_locks` with 0 stale rows | Returns 0, no log warning | test_dispatch_scheduler.py |
| `reclaim_stale_locks` with stale rows | Returns count, log warning fires | test_dispatch_scheduler.py |

### Integration Tests (staging only)

| Test | Steps |
|------|-------|
| Full dispatch lifecycle | Enqueue 1 draft → enable sends on staging → confirm DELIVERED + sent_at + queue delete |
| Retry lifecycle | Enqueue 1 draft → force Resend 5xx → confirm retry_count=1, next_retry_at set |
| Max retry exhaustion | Force 4 transient failures → confirm dispatch_failed + queue deleted |
| Webhook delivery | Confirm Resend webhook updates outreach_drafts.bounced_at on bounce |
| Duplicate claim guard | Insert same draft twice → confirm ON CONFLICT DO NOTHING |

### Pre-Activation Production Checks

| Check | SQL / action |
|-------|-------------|
| `send_attempts` has no orphaned DISPATCHED rows | `SELECT COUNT(*) FROM send_attempts WHERE status='DISPATCHED' AND dispatched_at < NOW()-INTERVAL '1 hour'` |
| No ghost queue rows | `SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NULL AND (SELECT sent_at FROM outreach_drafts WHERE id=draft_id LIMIT 1) IS NOT NULL` |
| RESEND_WEBHOOK_SECRET set | `curl .../api/admin/send-config` confirms secret is set (or check Railway env) |

---

## 10. Production Rollout Sequence for Delivery Lifecycle

1. **Implement Fix 1** (pre-send atomic `sent_at` claim in `dispatch_queued_draft`) — PR required; staging test; merge
2. **Implement Fix 2** (ALREADY_DELIVERED status handling in dispatch_scheduler.py) — same PR or separate; staging test; merge
3. **Set RESEND_WEBHOOK_SECRET in Railway production env** — required before any live sends
4. **Confirm webhook handler is reachable** (Railway → `/api/webhooks/resend` returns 200 for OPTIONS or health probe)
5. **Unit + integration tests pass on staging**
6. **Deploy to production** (workflow_dispatch via deploy-production.yml)
7. **Stage C: internal activation cohort** — 1–3 test addresses; confirm full lifecycle end-to-end before real prospect sends

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/DELIVERY_CORRECTNESS_ANALYSIS_001.md`
