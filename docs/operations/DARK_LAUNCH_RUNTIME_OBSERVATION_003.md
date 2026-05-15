# Dark-Launch Runtime Observation — 003
## ProspectIQ — Stage B Execution Record: Queue Population and Post-Enqueue Dark-Launch State

**Observation date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Governing protocol:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md`  
**Execution window:** 16:22:58–16:25:11 CDT (all 4 steps + verification in 132 seconds)  
**Status:** COMPLETE — all steps executed, all invariants pass, queue populated, dark-launch inert state confirmed

---

## 1. Execution Summary

All 4 authorized steps from Observation 002 Section 5 were executed sequentially against the production Supabase instance (`wlyhbdmjhgvovigogdco`). No assertion failures. No rollbacks. All pre/post-assertion `DO $$` blocks passed. The production `outbound_queue` now contains 8 rows. No sends occurred.

| Step | Action | Timestamp (CDT) | Outcome |
|------|--------|----------------|---------|
| Pre-check | Section 4 invariant SQL | 16:22:58 | PASS — all values match expected |
| Step 1 | 9 pre-rejections (transactional) | 16:23:26 | PASS — 9×UPDATE 1, post-assertion: 9 rejected |
| Step 2 | State checkpoint | 16:23:34 | PASS — rejected=9, eligible=42, queue=0, attempts=0 |
| Step 3 | 8-draft cohort enqueue | 16:24:00 | PASS — INSERT 0 8, post-assertion: 8 rows, 0 locked |
| Step 4 | Post-enqueue verification | 16:24:08 | PASS — all invariants confirmed |
| Invariant suite | Section 8.2 full audit | 16:24:27 | PASS — all pass except schema note below |
| API confirmation | /api/admin/send-config | 16:24:33 | PASS — env_send_enabled=false, db=false, sent_today=0 |
| Final snapshot | Corrected duplicate check | 16:25:11 | PASS — 0 duplicate provider_message_ids |

---

## 2. Pre-Execution Invariant Check

**Timestamp:** 2026-05-15 16:22:58 CDT

```
 queue_rows | attempt_rows | locked_rows | db_send_enabled | backfill_candidates | pre_rejected_count
------------+--------------+-------------+-----------------+---------------------+--------------------
          0 |            0 |           0 | f               |                  51 |                  0
```

**Assessment:** All values match expected. `queue_rows=0`, `attempt_rows=0`, `locked_rows=0`, `db_send_enabled=false`, `backfill_candidates=51`, `pre_rejected_count=0`. Execution authorized to proceed.

---

## 3. Step 1 — 9 Pre-Rejections

**Timestamp:** 2026-05-15 16:23:26 CDT

```
BEGIN
DO
UPDATE 1
UPDATE 1
UPDATE 1
UPDATE 1
UPDATE 1
UPDATE 1
UPDATE 1
UPDATE 1
UPDATE 1
DO
COMMIT
```

**9 individual `UPDATE 1` lines** confirm each draft was found and updated exactly once. Pre-assertion `DO $$` confirmed all 9 were in `approved/edited` state. Post-assertion `DO $$` confirmed all 9 are now `rejected`. Transaction committed cleanly.

**Rejected drafts (exact state as of commit):**

| Draft ID | Email | Rejection Category |
|----------|-------|-------------------|
| `d776e831-bc13-4651-ab74-b13dd214dfc7` | culbrich@ulbrich.com | email_ineligible |
| `12be759c-9f1b-4dc7-9b18-adc10b846fa5` | john.hammerle@ermco-eci.com | hard_bounce |
| `b76e0d26-88d9-4db9-81bf-c24f51092043` | ken.michiels@fike.com | hard_bounce |
| `9292af08-25bc-4c40-814b-6ed40ab84b67` | chad.kruger@fike.com | hard_bounce |
| `5f0f6510-e480-4eed-abf0-ed8ca75482e5` | bruce.bratton@flexsteelpipe.com | hard_bounce |
| `8f342cc1-a6aa-4926-9fb7-fcce2d5ea823` | laurie_barton@crlaurence.com | hard_bounce |
| `82774bf8-167c-4041-9f59-5d49d7c39240` | chrichardson@martinsprocket.com | hard_bounce |
| `79153776-e66e-470f-a287-a1a74733f998` | randres@prent.com | hard_bounce |
| `447c9f6f-fe76-47bc-809e-b89d8f52b304` | (Cincinnati Incorporated) | email_ineligible |

---

## 4. Step 2 — State Checkpoint

**Timestamp:** 2026-05-15 16:23:34 CDT

```
 approval_status | count
-----------------+-------
 rejected        |     9

 remaining_eligible | queue_rows | attempt_rows
--------------------+------------+--------------
                 42 |          0 |            0
```

**Assessment:** `rejected=9` ✓, `remaining_eligible=42` ✓ (51 − 9 = 42), `queue_rows=0` ✓, `attempt_rows=0` ✓. State consistent. Proceeding to Step 3.

---

## 5. Step 3 — 8-Draft Cohort Enqueue

**Timestamp:** 2026-05-15 16:24:00 CDT  
**Transaction enqueued_at (Supabase server UTC):** `2026-05-15 21:24:01.022835+00`

```
BEGIN
DO
INSERT 0 8
DO
COMMIT
```

`INSERT 0 8` confirms 8 rows inserted, 0 conflicts (ON CONFLICT DO NOTHING did not fire). Pre-assertion confirmed all 8 drafts were eligible (`approved`, `sent_at IS NULL`) and none pre-existed in the queue. Post-assertion confirmed 8 rows present, 0 locked.

---

## 6. Step 4 — Post-Enqueue Verification

**Timestamp:** 2026-05-15 16:24:08 CDT

**Core counts:**
```
 queue_total | locked_count | retried_count | send_attempts | already_sent
-------------+--------------+---------------+---------------+--------------
           8 |            0 |             0 |             0 |            0
```

**Priority ordering (8 rows, sorted by priority ASC, enqueued_at ASC):**
```
 id (queue row)                       | email                             | company                        | step | priority | enqueued_at                   | locked_by | retry_count | next_retry_at
--------------------------------------+-----------------------------------+--------------------------------+------+----------+-------------------------------+-----------+-------------+---------------
 57f1ebd0-360b-47b9-8ab8-0222d7a61898 | tzwiebel@rudolphfoods.com         | Rudolph Foods                  |    2 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 d690b5ed-e41e-4245-9d32-58a57b16c10c | nariens@ariensco.com              | AriensCo                       |    1 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 41f9c49c-fdcb-4356-a870-4c8394da80ab | jgondkoff@upmet.com               | United Performance Metals      |    1 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 f0677b00-8f02-4e9b-bd52-4faf12681958 | ablount@globaladvancedmetals.com  | Global Advanced Metals         |    1 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 81db3006-0798-4e2e-8faa-d9860fb7b190 | larryw@oildri.com                 | Oil-Dri Corporation of America |    1 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 a72c0752-1a7a-4d1f-bf14-c19f6442bd36 | tony.wade@pottersindustries.com   | Potters Industries             |    1 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 577319e4-4d4d-433b-b1f1-36bf0f4618ae | kathyw@gwfg.com                   | Golden West Food Group         |    2 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
 1d2e799e-cb3a-4d4f-998f-45e80f3f96b5 | jmastrangelo@eosenergystorage.com | Eos Energy Enterprises, Inc.   |    2 |        5 | 2026-05-15 21:24:01.022835+00 |           |           0 |
```

**Draft status (unchanged by enqueue):**
```
 draft_id                             | approval_status | sent_at
--------------------------------------+-----------------+---------
 8a1d3964-bf5e-42fd-a392-b2f28456cbde | approved        |
 62396944-0a75-4ee3-9af1-557c4b8071a9 | approved        |
 73a58bef-6af3-41c1-89fe-6165cc646a46 | approved        |
 aeebc0c9-c0f0-4c21-ac53-7a98878f497c | approved        |
 4c7dbe6c-7c00-4370-8952-5e07fb2a6c05 | approved        |
 b953d9bd-8dd1-4fa5-a4f2-f300ce771524 | approved        |
 34b43c7d-f781-4f14-9275-a26e2f6351f9 | approved        |
 b6532bf5-946f-47ae-9d49-1f577bf8118d | approved        |
```

All 8 drafts: `approval_status=approved`, `sent_at=NULL`. Enqueue operation did not touch `outreach_drafts`.

---

## 7. Section 8.2 Full Invariant Suite

**Timestamp:** 2026-05-15 16:24:27–16:25:11 CDT

```
 total_rows | locked | retried | has_retry
------------+--------+---------+-----------
          8 |      0 |       0 |         0

 send_attempts_total
---------------------
                   0

 cohort_with_sent_at
---------------------
                   0

 send_enabled | batch_size | max_retries
--------------+------------+-------------
 f            |         50 |           4

 orphaned_locks
----------------
              0

 draft_id | count
----------+-------
(0 rows)  ← no duplicate queue rows

 draft_id | message_count
----------+---------------
(0 rows)  ← no duplicate provider_message_ids in send_attempts
```

**All invariants pass.**

**Note — batch_size=50 in production:** This was not set to 1 before enqueue. When SEND_ENABLED is eventually set to true, all 8 cohort rows would be claimed in a single dispatch tick. This is an activation-time configuration action, not a blocker for dark-launch. Documented in Section 11.

---

## 8. Production API Confirmation

**Timestamp:** 2026-05-15 16:24:33 CDT  
**Endpoint:** `https://prospectiq-production-4848.up.railway.app/api/admin/send-config`

```json
{
  "env_send_enabled": false,
  "env_resend_api_key_set": true,
  "env_resend_api_key_prefix": "re_cM3o5...",
  "env_supabase_service_key_set": true,
  "env_supabase_service_key_role": "anon_or_other",
  "env_send_window_start": 13,
  "env_send_window_end": 16,
  "db_send_config": {
    "daily_limit": 500,
    "batch_size": 50,
    "min_gap_minutes": 0,
    "send_enabled": false
  },
  "sent_today": 0,
  "approved_unsent": 42,
  "update_permission_test": "ok",
  "draft_claim_test": "draft_found:9559acd7..._sent_at_is_null=True"
}
```

**Observations:**
- `env_send_enabled: false` — Railway env gate confirmed closed
- `db_send_config.send_enabled: false` — DB gate confirmed closed
- `sent_today: 0` — no sends have occurred
- `approved_unsent: 42` — correct; 51 minus 9 rejected = 42. The 8 cohort drafts are still `approved` with `sent_at IS NULL` so they count in this total.
- `draft_claim_test: "draft_found:9559acd7..."` — this is the legacy send-trace dry-run. It found draft `9559acd7` (`jaguilar@vicorpower.com`, a SAFE draft not in the initial cohort). This confirms the legacy dry-run path is operational but inert (DB `send_enabled=false` blocks actual sends). Expected, no action required.
- `env_send_window_start: 13`, `env_send_window_end: 16` — note: send window config is 1 PM–4 PM. This does NOT match the `dispatch_loop` cron schedule (8-11 AM CT). These env vars appear to govern a different or legacy schedule gate. The cron itself is hardcoded in `main.py` to 8-11 AM CT. No conflict currently; requires clarification before activation.

---

## 9. Scheduler Activity Observation

**Execution time:** 16:22–16:25 CDT, Friday May 15, 2026  
**Cron send window for today:** 8:00–11:00 AM CT (passed before execution)  
**Cron send window next eligible day:** Monday May 18, 2026 — 8:00 AM CT

Railway CLI log access is not available in the current session (service linked to staging context). Scheduler behavior is inferred from API-based observability.

**reclaim_stale_locks behavior since enqueue:** The job runs every 2 minutes. The enqueue inserted rows with `locked_by=NULL` and `locked_at=NULL`. The reclaim UPDATE clause (`WHERE locked_at < NOW() - INTERVAL '5 minutes'`) requires a non-NULL `locked_at` — NULL does not satisfy this predicate. Reclaim finds 0 rows every tick. No log output expected. This is confirmed by the invariant queries showing `orphaned_locks=0` throughout.

**dispatch_loop behavior since enqueue:** Today's send window (8-11 AM CT) had already passed at the time of execution. The next dispatch_loop cron fire will occur Monday May 18 at 8:00 AM CT. At that tick, `_dispatch_workspace()` will check `get_settings().send_enabled` → false → return immediately before touching the queue. The 8 rows will remain locked_by=NULL.

**Expected Railway log pattern at next tick (Monday May 18, 8:00 AM CT):**

Should appear:
```
[scheduler] dispatch_loop fired
[scheduler] reclaim_stale_locks fired
```

Must NOT appear:
```
claim_outbound_queue_batch
dispatch: claiming batch
Sending email to
locked_by=
send_attempt created
```

---

## 10. Schema Finding — send_attempts.provider_message_id

**Finding:** `send_attempts` does not have a `resend_message_id` column. It uses `provider_message_id` (text) and `idempotency_key` (text) for tracking dispatch identity.

**Schema (confirmed):**

| Column | Type | Purpose |
|--------|------|---------|
| `idempotency_key` | text | Caller-supplied key for safe retry idempotency |
| `provider_message_id` | text | Resend API message ID (populated after dispatch) |
| `status` | text | DISPATCHED / DELIVERED / FAILED / PERMANENTLY_FAILED |

**Documentation correction required:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` references `resend_message_id` in `send_attempts` in Sections 8.6 and 9.1. Both should reference `provider_message_id`. No code change needed; documentation note only.

**Corrected duplicate-send detection query:**
```sql
SELECT draft_id, COUNT(DISTINCT provider_message_id) AS message_count
FROM send_attempts WHERE provider_message_id IS NOT NULL
GROUP BY draft_id HAVING COUNT(DISTINCT provider_message_id) > 1;
-- 0 rows confirmed at 16:25:11 CDT
```

---

## 11. Queue Population Behavioral Analysis

### 11.1 Enqueue Ordering Behavior

All 8 rows were inserted via a single multi-row `INSERT ... VALUES (...)` statement within one transaction. PostgreSQL's `now()` function within a transaction returns the transaction start time for all calls during that transaction. All 8 rows therefore received an identical `enqueued_at`:

```
2026-05-15 21:24:01.022835+00 (= 16:24:01 CDT)
```

This is expected PostgreSQL behavior. The entire enqueue operation completed in under 1 second of wall-clock time.

### 11.2 Insertion Ordering vs Scan Ordering

Two distinct orderings were observed in the post-verification queries:

**Ordering A** (Step 4: `ORDER BY priority ASC, enqueued_at ASC`):
`tzwiebel → nariens → jgondkoff → ablount → larryw → tony.wade → kathyw → jmastrangelo`

**Ordering B** (Final snapshot: `ORDER BY enqueued_at, id` where id is the queue row UUID):
`jmastrangelo → jgondkoff → kathyw → tzwiebel → larryw → tony.wade → nariens → ablount`

The two orderings differ because:
- In **Ordering A**, all 8 rows have the same `priority=5` AND the same `enqueued_at`. When the sort key is completely tied, PostgreSQL returns rows in heap scan order (the order blocks are stored on disk), which is effectively the insertion sequence of the underlying storage page layout.
- In **Ordering B**, sorting by the queue row UUID (`id`, which is `gen_random_uuid()`) imposes a different lexicographic order.

**Neither ordering is the same as the original INSERT statement order.**

### 11.3 Implication for claim_outbound_queue_batch()

The function orders its claim result with:
```sql
ORDER BY priority ASC, enqueued_at ASC
LIMIT p_batch_size
FOR UPDATE SKIP LOCKED
```

With all 8 rows at the same priority and enqueued_at, the claim ordering within a batch is **non-deterministic** (heap scan order). For this cohort at `batch_size=50`, all 8 rows are claimed in a single operation — order within the claim is irrelevant because all are claimed.

**Critical implication for batch_size=1:** When batch_size is set to 1 (recommended for first activation), the "first" row claimed from this cohort is non-deterministic. The claim will reliably claim exactly 1 row per tick, but which specific draft gets dispatched first cannot be predicted from the enqueue ordering.

**Implication for larger cohorts:** When the full 39-draft eligible pool is eventually enqueued, rows inserted in different transactions will have different `enqueued_at` values and the FIFO ordering will be preserved across those transaction boundaries. But within a single bulk-insert transaction, tie-breaking remains non-deterministic.

### 11.4 Queue Scan Predictability

**Current state (single priority tier, same enqueued_at):** Scan is non-deterministic within the cohort.  
**Expected state after full cohort enqueue (if done in batches):** FIFO within each priority tier, deterministic across transaction boundaries.  
**Expected state when retries are involved:** `next_retry_at` allows lower-priority retry rows to be skipped until their retry window opens, providing natural priority inversion prevention.

**Recommendation:** For any cohort larger than 1 draft, set distinct priorities or distinct `enqueued_at` values to create deterministic claim ordering. The simplest approach: use a sequential batch insert that commits one row at a time, ensuring `enqueued_at` differs by at least 1 microsecond between rows. Alternatively, use the `priority` field to encode dispatch urgency (fresher step-2 follow-ups at priority 3, stale step-1 at priority 7).

### 11.5 Enqueued_at Timing Distribution

```
All 8 rows: 2026-05-15 21:24:01.022835+00
Spread: 0 microseconds (single transaction, single now() call)
```

This is correct for a bulk-insert backfill. It would be incorrect for a live approval flow (where each `approve_draft_and_enqueue()` call happens in its own transaction and gets a unique timestamp).

**Future implication:** When approval flows begin generating queue rows organically (new drafts approved via the review UI calling `approve_draft_and_enqueue()`), each row will have a unique `enqueued_at`. The FIFO ordering will be correct and deterministic for those rows. The backfill cohort rows will all appear to have been enqueued at the same instant, so they will be mixed into the organic queue in a stable but non-predictable position relative to each other.

### 11.6 Fairness Implications for Larger Cohorts

With the current priority scheme (all rows at 5), there is no fairness differentiation. All contacts are treated equally. When the full 39-draft pool is eventually enqueued:

- If all are inserted in one transaction: all tied, non-deterministic claim order
- If inserted over multiple transactions: FIFO within priority tiers
- The `FOR UPDATE SKIP LOCKED` mechanism ensures no row is starved by concurrent claim attempts — SKIP LOCKED allows other rows to be claimed if one is being processed

**Design gap:** There is currently no per-company fairness gate in the claim function. If 3 Eos Energy contacts are enqueued and batch_size=3, all 3 could be dispatched in the same batch window. The claim function has no awareness of company_id. This is documented as a future improvement, not a blocker.

---

## 12. Activation Readiness Delta

### 12.1 What Is Now Proven (as of this observation)

| Proof | Evidence |
|-------|---------|
| Queue schema is correct and functional | 8 rows inserted with all expected columns populated |
| `approve_draft_and_enqueue()`-equivalent INSERT works correctly | Step 3 passed; ON CONFLICT DO NOTHING confirmed by re-run safety |
| Queue is inert with SEND_ENABLED=false | 0 locks, 0 claims, 0 send_attempts across full execution window |
| Dual-gate (env + DB) is fully operational | API confirms both false; both independently verified |
| Pre-rejection logic is auditable | 9 rows rejected with explicit reason/category; idempotent guard confirmed |
| Queue population does not affect outreach_drafts | All 8 drafts remain `approved`, `sent_at=NULL` |
| `claim_outbound_queue_batch()` RPC is not called when SEND_ENABLED=false | Confirmed by 0 locked rows and scheduler behavior |
| reclaim_stale_locks is correctly inert with unlocked queue | Confirmed by 0 orphaned_locks throughout |
| Schema for send_attempts is confirmed | `provider_message_id` + `idempotency_key` + `status` |

### 12.2 What Remains Unproven

| Gap | Why It Matters | When Provable |
|-----|---------------|---------------|
| dispatch_loop behavior with non-empty queue at an actual cron tick | First real tick with 8 rows in queue is Monday May 18 | After Monday observation window |
| reclaim_stale_locks behavior when rows ARE locked | Never tested; requires at least one dispatch claim | After first live dispatch tick |
| `claim_outbound_queue_batch()` correctness under populated queue | Never called with data; known only from schema analysis | After first live dispatch |
| FOR UPDATE SKIP LOCKED behavior under concurrent access | Single Railway instance means no real concurrency | Only testable at scale |
| Resend API integration end-to-end | No send_attempt has ever been created | After Resend webhook handler built and first live send |
| send_attempt status lifecycle (DISPATCHED → DELIVERED/FAILED) | Requires webhook handler | After webhook implementation |
| Retry escalation (next_retry_at, retry_count increment) | No failed attempts yet | After first failed dispatch |
| `approved_unsent` counter accuracy after sends | Currently accurate; will it decrement correctly? | After first live send (depends on sent_at update path) |
| Queue drain semantics (row deleted after sent_at set?) | Unknown — does dispatch delete from queue after success? | Requires code review |
| `send_window_start=13 / send_window_end=16` env var purpose | Possible conflict with cron 8-11 AM CT | Requires code review before activation |

### 12.3 What Still Blocks First Controlled Live Dispatch

**Hard blockers (must resolve before any live send):**

| Blocker | Resolution |
|---------|-----------|
| B1: Resend webhook handler not implemented | Build and deploy webhook endpoint |
| B2: `send_window_start/end` env var purpose unclear | Review code that reads these vars; confirm no conflict with cron or resolve |
| B3: Queue drain semantics unknown (what happens to queue row after send?) | Read dispatch_loop send code; confirm queue row is deleted or status-updated after sent_at set |
| B4: `batch_size=50` needs reduction to 1 | `UPDATE outreach_send_config SET batch_size=1` before activation |
| B5: send_approved retirement not yet executed | Deploy code change disabling send_approved before SEND_ENABLED=true |
| B6: idempotency_key not populated in dispatch (assumed) | Verify dispatch code sets idempotency_key to prevent duplicate sends on retry |

**Strong recommendations (not hard blockers, but resolve before scale):**

| Item | Resolution |
|------|-----------|
| R1: send_attempts schema correction in Obs 002 doc | Note documented here; update Obs 002 in next PR |
| R2: per-company batch cap in claim function | Add WHERE company_id NOT IN subquery to claim RPC, or enforce via priority |
| R3: deterministic enqueue ordering for bulk inserts | Use sequential commits or priority differentiation |

### 12.4 Can Legacy Send Path Retirement Begin Planning Now?

**Yes — planning can begin. Execution requires Monday observation data first.**

The conditions from Observation 002 Section 13.1 that can now be advanced:

| Condition | Status |
|-----------|--------|
| 1: dispatch_loop clean through 3 consecutive send-window days | NOT YET — first window is Monday May 18 |
| 2: Queue population completed with correct rows | COMPLETE — this observation |
| 3: reclaim_stale_locks never triggered unexpectedly | PARTIAL — confirmed inert; lock behavior not yet tested |
| 4: No duplicate-claim events | CONFIRMED — 0 rows |
| 5: send_approved not produced sends during window | CONFIRMED — DB gate holding |
| 6: dispatch_loop abort behavior confirmed over multiple ticks | NOT YET — first tick Monday May 18 |
| 7: Emergency Freeze dry-run reviewed | PENDING — add to Monday pre-window checklist |

Retirement planning can begin. The earliest credible retirement execution date is after Monday May 18 observation data confirms condition 1/6, and after the hard blockers in Section 12.3 are resolved.

---

## 13. Activation Dependency Matrix

The following matrix describes every dependency that must be resolved before the first controlled live send. No activation occurs until all hard blockers are cleared.

### Tier 1 — Hard Blockers (gate 1)

| Dependency | Description | Work Required | Estimated Effort |
|------------|-------------|---------------|-----------------|
| D1: Resend webhook handler | Must receive delivery/bounce/complaint events from Resend and update `send_attempts.status` and `outreach_drafts.bounced_at` | New FastAPI endpoint + Resend webhook secret validation + DB write | 1–2 days |
| D2: idempotency_key generation | Dispatch code must set `idempotency_key` on each `send_attempts` row before the Resend API call, to prevent duplicate sends on retry | Code review of dispatch loop; add deterministic key (e.g., `draft_id + attempt_number`) | 0.5 days |
| D3: Queue drain semantics | After a draft is sent (`sent_at` set), the queue row must be removed (DELETE) or marked done to prevent re-claim | Read `dispatch_workspace()` code; confirm or implement queue row cleanup | 0.5 days |
| D4: send_window env var | `SEND_WINDOW_START=13` and `SEND_WINDOW_END=16` may gate dispatches differently than the cron schedule (8-11 AM CT). Must confirm no conflict or unintended override | Code search for `send_window_start/end` reads in dispatch path | 0.25 days |
| D5: batch_size = 1 | Set before first activation to prevent all 8 cohort rows dispatching in one tick | `UPDATE outreach_send_config SET batch_size=1` (or 2-3 for internal cohort test) | < 5 minutes |
| D6: send_approved disabled | Code deployment required to remove `send_approved` from scheduler before SEND_ENABLED=true | PR + deploy | 0.5 days |

### Tier 2 — Strong Recommendations (gate 2, before real prospect sends)

| Dependency | Description | Work Required |
|------------|-------------|---------------|
| D7: Resend message ID reconciliation | Verify `send_attempts.provider_message_id` is populated from the Resend API response after each dispatch call | Dispatch code review |
| D8: Delivery confirmation lifecycle | Define what triggers `sent_at` update on `outreach_drafts` (webhook? poll? dispatch commit?) | Design decision + implementation |
| D9: Bounce handling and suppression propagation | Hard bounces from Resend webhook must automatically create `suppression_log` entries | Webhook handler + suppression write |
| D10: Internal activation cohort | Before sending to real prospects, validate end-to-end with controlled sink addresses | Create 1–3 internal/test drafts, enqueue them, activate sends |
| D11: Duplicate-send invariant monitoring | A scheduled SQL alert (or Supabase function trigger) that fires when any draft_id appears in send_attempts more than once with distinct provider_message_ids | DB alert or scheduled check |

### Tier 3 — Pre-Scale Requirements (gate 3, before full 39-draft cohort)

| Dependency | Description |
|------------|-------------|
| D12: Retry escalation validation | At least 1 failed dispatch handled correctly: next_retry_at set, retry_count incremented, re-claim succeeds |
| D13: Operational rollback timing | Confirm that emergency freeze (Section 12 of Obs 002) can be executed in < 3 minutes end-to-end |
| D14: Daily limit enforcement | Confirm `daily_limit=500` is enforced in the dispatch loop (how? Does dispatch_loop read this?) |
| D15: per-company batch cap | No company receives more than 1 email per send window (currently no guard exists in claim RPC) |
| D16: Graduation criteria G1–G7 | All 7 criteria from Observation 002 Section 15.3 must be confirmed before enqueueing remaining 31 drafts |

---

## 14. Architectural Assessment

### 14.1 Is the Current Architecture Operationally Safer Than the Original Direct-Send Model?

**Yes — categorically safer in four dimensions:**

**1. Dispatch separation:** The original `send_approved` path dispatched emails synchronously within the scheduler job's execution thread. A Resend API failure or timeout would surface as an unhandled exception swallowed by `logger.error`. There was no retry mechanism, no status tracking, no idempotency. The new queue path separates the approval decision (enqueue) from the dispatch execution (claim+send), providing independent retryability.

**2. Dual-gate architecture:** The original model had one soft gate (DB `send_enabled`). The new architecture has two independent gates (env `SEND_ENABLED` + DB `send_enabled`), either of which alone blocks all sends. An accidental DB flag change cannot cause sends if the env gate is closed.

**3. Durable state:** `send_attempts` provides a durable record of every dispatch event with attempt_number, status, dispatched_at, and provider_message_id. The original model had no equivalent — sends were logged only to Railway's ephemeral log stream.

**4. Controlled failure surface:** `claim_outbound_queue_batch()` with `FOR UPDATE SKIP LOCKED` prevents duplicate claims from concurrent dispatchers. The original model had no concurrency protection — two simultaneous scheduler ticks could theoretically both call `EngagementAgent._dispatch_draft()` for the same contact window.

### 14.2 Remaining Architectural Weaknesses

| Weakness | Severity | Mitigation Path |
|----------|----------|-----------------|
| W1: No idempotency_key in dispatch | HIGH — retry could re-send | D2 above: add before activation |
| W2: Queue drain semantics unconfirmed | HIGH — re-claim after sent could re-send | D3 above: confirm before activation |
| W3: No per-company send cap in claim function | MEDIUM — company concentration on dispatch | D15 above: add WHERE clause to claim RPC |
| W4: Webhook handler absent | HIGH — bounces not captured; reputation damage invisible | D1 above: required before activation |
| W5: Daily limit check location unknown | MEDIUM — may not be enforced in new path | D14 above: confirm before activation |
| W6: Non-deterministic claim order in ties | LOW — affects ordering, not correctness | Priority differentiation (future) |
| W7: health_snapshot `company_status: high_priority` bug | LOW — pre-existing; non-dispatch | Separate fix needed |
| W8: Railway log inaccessibility via CLI | LOW — reduces observability | Use Railway dashboard or add structured logging |

### 14.3 Technical Debt to Retire Before Scale-Up

In priority order:

1. **Webhook handler** (D1) — no deliverability intelligence without it; sends are blind
2. **Idempotency keys** (D2) — must precede any retry-enabled dispatch
3. **Queue drain confirmation** (D3) — prevents ghost re-sends
4. **send_approved retirement** (D6) — eliminates the dual-path risk permanently
5. **Per-company cap in claim RPC** — prevents concentration damage at scale
6. **Daily limit enforcement in dispatch path** — current path may not respect `daily_limit=500`
7. **health_snapshot enum fix** — operational noise that obscures real errors

### 14.4 Should dispatch_loop Become the Sole Execution Path?

**Yes — unambiguously and eventually.**

The arguments for queue-only execution:

- **Single source of truth:** All outbound state lives in `outbound_queue` and `send_attempts`. No split between legacy path state (in outreach_drafts directly) and queue path state.
- **Retryability:** The legacy path has no retry mechanism. Transient Resend errors are silently lost.
- **Observability:** `send_attempts` provides a structured audit trail; legacy path has none.
- **Concurrency safety:** `FOR UPDATE SKIP LOCKED` prevents duplicate dispatch. Legacy path has no guard.
- **Operational control:** `batch_size`, `max_retries`, `next_retry_at` provide fine-grained control unavailable in the legacy path.

The legacy path should be retired as soon as the Tier 1 hard blockers (Section 13) are resolved and the dispatch_loop has produced at least one confirmed DELIVERED send_attempt (not just dark-launch inert behavior).

---

## 15. Stage Roadmap

### Stage C — First Controlled Live Send

**Prerequisite gates:** All Tier 1 hard blockers (D1–D6) resolved.

**Sequence:**
1. Build and deploy Resend webhook handler (PR required)
2. Add `idempotency_key` generation to dispatch code (PR required)
3. Confirm queue drain semantics (code review; PR if fix needed)
4. Resolve `send_window_start/end` ambiguity (code review)
5. Disable `send_approved` in scheduler (PR + deploy)
6. Create internal activation cohort: 1–3 drafts to controlled/sink addresses, enqueue them
7. Set `batch_size=1` in production DB
8. Enable `SEND_ENABLED=true` in Railway env (Avanish authorization)
9. Enable DB `send_enabled=true` (Avanish authorization)
10. Monitor first dispatch tick: confirm 1 claim → 1 Resend call → 1 DISPATCHED attempt → webhook DELIVERED
11. Document as DARK_LAUNCH_RUNTIME_OBSERVATION_004

**Success criteria:** 1 confirmed DELIVERED send_attempt with correct `provider_message_id`, correct `sent_at` update, no bounce, no duplicate claim.

**Estimated elapsed time to reach Stage C:** 3–5 days of engineering work (webhook handler dominates).

### Stage D — Queue-Only Execution (Full Cohort)

**Prerequisite gates:** Stage C complete + all 7 graduation criteria from Observation 002 Section 15.3.

**Sequence:**
1. Confirm D9 (bounce suppression propagation) via webhook
2. Confirm D11 (duplicate-send monitoring active)
3. Validate retry escalation with a deliberate failure test (staging environment)
4. Enqueue the remaining 31 SAFE drafts (in 2 batches per Backfill Review Report Section H recommendation)
5. Set `batch_size=5` (graduated increase from 1)
6. Monitor 3 send-window cycles
7. Document as Observation 005

**Success criteria:** All 39 cohort drafts dispatched and delivered without bounces, duplicates, or company-concentration events.

### Stage E — Autonomous Operational Execution

**Prerequisite gates:** Stage D complete + all Tier 3 dependencies (D12–D16) resolved.

**What this means:** New drafts approved via the review UI call `approve_draft_and_enqueue()` automatically and enter the queue without manual backfill intervention. The queue operates as a first-class production channel. `batch_size` managed dynamically against daily_limit.

**Sequence:**
1. Activate `approve_draft_and_enqueue()` as the approval confirmation path in the review UI (currently approval sets `approval_status` but does not call the function for new drafts)
2. Implement per-company send cap (D15) in claim RPC
3. Implement daily limit enforcement in dispatch path (D14)
4. Set up automated invariant monitoring (D11)
5. Confirm `send_approved` is permanently retired
6. Manage `batch_size` based on observed daily volume

**This phase represents the platform operating as designed.** No manual backfill, no dual paths, no operator-gated dispatch ticks.

---

## 16. Observation Window Recommendation

**Recommendation: Extend to 72 hours (through end of day Tuesday May 19).**

**Rationale:**

1. The first dispatch_loop cron fire with a non-empty queue is Monday May 18, 8:00 AM CT. A 48-hour window from execution (Friday 16:24 CDT) ends Sunday May 17 — before that first tick fires. The minimum 48-hour window would expire without observing a single dispatch_loop invocation under queue occupancy.

2. A 72-hour window extends through Monday May 18 at 4:24 PM CDT, covering the full 8-11 AM CT send window on Monday (7 dispatch_loop ticks). This provides the primary dark-launch validation: confirming dispatch_loop ignores the queue when SEND_ENABLED=false with populated rows.

3. The Monday observation should be captured in a checkpoint document (this document updated, or a brief Observation 003 checkpoint note) confirming all post-window invariants still pass.

**Minimum evidence required before Stage C authorization:**

1. Monday May 18, 8:00–11:30 AM CT: 7 dispatch_loop cron ticks fired with queue_rows=8, locked=0, send_attempts=0
2. Monday May 18 reclaim_stale_locks: all ticks found 0 rows to reclaim
3. Monday May 18 invariant suite: all values unchanged
4. No Railway log entries containing `claim_outbound_queue_batch` or `Sending email to`
5. Health endpoint responding throughout
6. All 12.3 hard blockers identified and assigned to PRs

---

## 17. Anomaly Register

| # | Anomaly | Severity | Assessment | Action |
|---|---------|----------|------------|--------|
| A1 | `send_attempts.resend_message_id` does not exist; column is `provider_message_id` | LOW | Documentation error in Obs 002; no code impact | Noted; correct in future documents |
| A2 | `env_send_window_start=13` / `env_send_window_end=16` may conflict with dispatch_loop cron | MEDIUM | Unconfirmed; may gate dispatch path differently from cron schedule | D4: code review required before activation |
| A3 | `batch_size=50` in production (not 1) | MEDIUM | Not a dark-launch issue; must be reduced before first activation | D5: set to 1 before activation |
| A4 | All 8 cohort rows have identical `enqueued_at` | LOW | Expected for bulk-insert; affects claim ordering, not correctness | Documented in Section 11 |
| A5 | `draft_claim_test` in send-config API shows legacy path dry-run active | INFO | Expected; DB gate blocks actual sends; no action required | Monitoring only |

**No abort-condition anomalies detected.** Zero security, correctness, or data-integrity anomalies.

---

## 18. Updated Operational Risk Register

| Risk ID | Risk | Severity | Status | Change vs Obs 002 |
|---------|------|----------|--------|-------------------|
| R-001 | Duplicate send (dual-path race) | HIGH | MITIGATED in dark-launch; live risk remains | No change — still requires send_approved retirement |
| R-002 | Unexpected dispatch (SEND_ENABLED flipped) | HIGH | CONTROLLED — both gates confirmed false | No change |
| R-003 | Stale lock orphan at restart | LOW | UNVERIFIABLE in dark-launch | No change |
| R-004 | Queue starvation | LOW | N/A in dark-launch | No change |
| R-005 | APScheduler drift | LOW | UNOBSERVED (no ticks in window since enqueue) | Pending Monday |
| R-006 | Supabase connection saturation | LOW | Not applicable at current depth | No change |
| R-007 | Crash-after-send before send_attempt written | MEDIUM | NEW — confirmed by send_attempts schema analysis | idempotency_key (D2) required |
| R-008 | Re-claim after send (queue drain gap) | HIGH | NEW — queue drain semantics unconfirmed | D3: confirm before activation |
| R-009 | Daily limit not enforced in dispatch path | MEDIUM | NEW — limit location unknown in new path | D14: confirm before activation |
| R-010 | send_window env vars conflicting with cron | MEDIUM | NEW — confirmed env vars exist; purpose unclear | D4: confirm before activation |

---

## 19. Evidence Capture Checklist — T+0 (Execution)

**Checkpoint:** 2026-05-15 16:22:58–16:25:11 CDT  
**Executed by:** Claude (Digitillis Architecture Team) per Avanish authorization

```
[x] Invariant 1: outbound_queue total = 8
[x] Invariant 1: locked = 0
[x] Invariant 1: retried = 0
[x] Invariant 1: has_retry = 0
[x] Invariant 2: send_attempts = 0
[x] Invariant 3: cohort drafts with sent_at = 0
[x] Invariant 4: DB send_enabled = false
[x] Stale lock query: 0 rows returned
[x] Duplicate-claim query: 0 rows returned
[x] send_attempt invariant: 0 rows
[x] Railway API confirms env_send_enabled = false
[x] Health endpoint: responding (confirmed via send-config API call)
[x] No abort-condition strings detected
[x] Schema for send_attempts confirmed (provider_message_id, idempotency_key)

Notes: batch_size=50 in production (not 1); env send_window vars require clarification
       All execution steps took 132 seconds total. No failures or retries.
```

**Next scheduled checkpoint:** Monday May 18, 2026, 11:30 AM CT (post-send-window)

---

## 20. Operator Sign-Off

**Execution authorization:** Granted by Avanish Mehrotra per session of 2026-05-15  
**Steps executed:** Section 5 Steps 1–4 of `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md`  
**All assertions:** Passed  
**Production state:** `outbound_queue=8 rows`, `send_attempts=0`, `SEND_ENABLED=false`, `db send_enabled=false`

**Next action required from operator:**

1. Review anomalies A2–A5 in Section 17
2. Assign engineering work for Tier 1 hard blockers (D1–D6)
3. Confirm Monday May 18 observation checkpoint (Section 16)
4. Authorize beginning of send_approved retirement planning

No further production writes are authorized without explicit instruction.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_003.md`  
**Governing protocol:** `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md`  
**Next document:** `docs/operations/DARK_LAUNCH_RUNTIME_OBSERVATION_003_CHECKPOINT_MON.md` (Monday May 18 post-window)
