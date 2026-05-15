# Legacy Send Path Retirement Plan — 001
## ProspectIQ — Workstream 5: `send_approved` Scheduler Retirement

**Document date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** APPROVED FOR EXECUTION — retirement is a prerequisite for send activation  
**Blocking gate:** Stage C (first live dispatch) cannot proceed until this retirement is deployed

---

## 1. Purpose

This document governs the retirement of the `send_approved` APScheduler job — the legacy direct-scan send path in ProspectIQ. Retirement is required before `SEND_ENABLED` is set to `true` in any environment. Running both the legacy path and the queue path (`dispatch_loop`) simultaneously with send enabled creates a dual-dispatch race condition that violates the exactly-once delivery contract.

---

## 2. What `send_approved` Does

### Registration

`backend/app/api/main.py` lines 2140–2145:

```python
scheduler.add_job(
    _run_send_approved, "cron",
    day_of_week="mon-fri", hour="8-11", minute="0,30",
    timezone="America/Chicago",
    id="send_approved",
)
```

**Schedule:** Mon–Fri, 8–11 AM CT, every :00 and :30 — 7 ticks/day.  
**Capacity:** 7 ticks × batch_size=20 = 140 capacity; capped at daily_limit=125.

### Execution Path

`_run_send_approved()` (main.py L316) → `_send_approved_workspace(ws)` (main.py L189) → `EngagementAgent.run(action="send_approved")` → `_send_approved_drafts()` (engagement.py L329).

### How It Claims Drafts

The legacy path uses an atomic pre-send claim at `engagement.py` lines 593–601:

```sql
UPDATE outreach_drafts
SET sent_at = NOW()
WHERE id = :draft_id AND sent_at IS NULL
```

This UPDATE returns 0 rows if `sent_at` is already set — which is the legacy path's exactly-once mechanism. The draft is sent only if the claim succeeds.

### Gates in the Legacy Path

| Gate | Code location | Behavior |
|------|--------------|----------|
| `SEND_ENABLED` env var | main.py L196, engagement.py L350 | Returns without action if false |
| DB `send_enabled` | engagement.py L372 | Returns without action if false |
| `send_window_start/end` | engagement.py L376–381 | Skips sends outside configured UTC hours |
| Suppression check | engagement.py (per-draft) | Skips suppressed contacts |
| Company lock | engagement.py (per-draft) | Skips locked companies |

**Currently:** Both env and DB gates are false. `send_approved` fires on every cron tick but returns immediately at the env gate check (main.py L196). No drafts are scanned, no Resend calls are made.

---

## 3. The Dual-Path Race Condition

When `SEND_ENABLED=true`, both `send_approved` and `dispatch_loop` fire on the same cron schedule:

```
Mon-Fri 8:00 AM CT  → send_approved tick  (legacy path)
Mon-Fri 8:00 AM CT  → dispatch_loop tick  (queue path)
```

**Race scenario:**

1. `dispatch_loop` claims a draft from `outbound_queue` via `claim_outbound_queue_batch()` (PostgreSQL `FOR UPDATE SKIP LOCKED`). The queue row is locked.
2. `send_approved` queries `outreach_drafts WHERE approval_status='approved' AND sent_at IS NULL`. It finds the same draft — because `sent_at` is set **after** the Resend call in the queue path (engagement.py L1244), not before.
3. `send_approved` issues its own atomic pre-send claim: `UPDATE outreach_drafts SET sent_at=NOW() WHERE id=:draft_id AND sent_at IS NULL`. This succeeds.
4. `send_approved` calls Resend for the same draft with a different idempotency key (`from_address:draft_id:timestamp` pattern — not the queue path's `draft_id:attempt_number` key).
5. Result: two independent Resend API calls for the same draft. Resend's 24h dedup window covers cases where idempotency keys match — it does NOT cover two calls with different keys.

**Outcome:** Duplicate email delivered to the contact.

**Additional hazard:** If Fix 1 from `DELIVERY_CORRECTNESS_ANALYSIS_001.md` is applied (atomic pre-send `sent_at` claim in `dispatch_queued_draft`), the race window narrows but does not close. `send_approved` can still win the pre-send claim race against `dispatch_queued_draft` if the tick timing differs.

**Conclusion:** There is no safe configuration where both jobs are active with `SEND_ENABLED=true`. Retirement is a hard prerequisite, not an optimization.

---

## 4. Retirement Procedure

### 4.1 Code Change

**File:** `backend/app/api/main.py`  
**Lines:** 2136–2145 (comment block + scheduler.add_job call)

**Before:**

```python
# send_approved (legacy direct-scan path) remains for manual/explicit-draft sends.
# _run_dispatch_loop (queue path) is the primary send path going forward.
# send_approved: Mon-Fri, 8am-11am Chicago at :00 and :30 (7 ticks/day)
# 7 ticks × batch_size=20 = 140 capacity; daily_limit=125 caps it at 125
scheduler.add_job(
    _run_send_approved, "cron",
    day_of_week="mon-fri", hour="8-11", minute="0,30",
    timezone="America/Chicago",
    id="send_approved",
)
```

**After:**

```python
# send_approved (legacy direct-scan path) RETIRED 2026-05-XX.
# Dual-path race with dispatch_loop is unresolvable when SEND_ENABLED=true.
# All send volume routes through dispatch_loop (queue path) exclusively.
# _run_send_approved and _send_approved_workspace are retained for potential
# manual invocation but are NOT registered in the scheduler.
# scheduler.add_job(
#     _run_send_approved, "cron",
#     day_of_week="mon-fri", hour="8-11", minute="0,30",
#     timezone="America/Chicago",
#     id="send_approved",
# )
```

**Change scope:** 1 file, 6 active lines commented out. No behavior change when `SEND_ENABLED=false` (current state). Full retirement effect activates on the first scheduler startup after deployment.

### 4.2 What Is NOT Changed

- `_run_send_approved()`, `_send_approved_workspace()`, and `EngagementAgent._send_approved_drafts()` are **retained in code**. They are not deleted. This preserves the ability to manually invoke the legacy path if needed and avoids a large diff.
- `_send_approved_workspace()` remains importable and callable from the REPL or a manual script.
- The DB `send_enabled` column in `outreach_send_config` is not changed by this retirement.
- No migration is required.

### 4.3 PR Requirements

| Requirement | Detail |
|-------------|--------|
| Branch name | `bugfix/retire-send-approved-scheduler` |
| Files changed | `backend/app/api/main.py` (1 file, ~6 lines commented out) |
| PR description | Must note: "retirement is prerequisite for activation — see LEGACY_SEND_PATH_RETIREMENT_001.md" |
| CI | All existing tests must pass. No new tests required for the comment-out itself. |
| Merge before activation | This PR must be deployed to production before `SEND_ENABLED` is ever set to `true` |

---

## 5. Verification After Deployment

After the retirement PR is deployed to production, verify the scheduler job is no longer registered:

### 5.1 Scheduler Job List Check

Call the Railway production instance:

```
GET /api/admin/scheduler-status
```

Expected response: `send_approved` job is **absent** from the job list. `dispatch_loop` and `reclaim_stale_locks` are present.

If no scheduler-status endpoint exists, verify via Railway logs at the next scheduler startup. Look for:

```
Registered jobs: [...] dispatch_loop [...] reclaim_stale_locks [...]
```

`send_approved` must not appear in the registered jobs list.

### 5.2 Dark-Launch Tick Verification

At the next 8–11 AM CT cron window (Mon–Fri), confirm:

- `dispatch_loop` fires and produces structured log output
- No `send_approved` log entries appear
- No EngagementAgent `_send_approved_drafts` invocations in logs
- `outbound_queue` row count unchanged (SEND_ENABLED still false at this stage)

### 5.3 Rollback Verification (Pre-Activation)

Before `SEND_ENABLED` is set to `true`, the operator must confirm this verification step is complete and documented in the Stage C activation checklist.

---

## 6. Rollback Procedure

If the retirement deployment causes unexpected issues (e.g., a manual send operation that depended on the scheduler path), revert by:

1. Uncomment the `scheduler.add_job(_run_send_approved, ...)` block
2. Deploy the revert
3. Verify `send_approved` reappears in scheduler job list

**Condition for rollback:** Only applicable when `SEND_ENABLED=false`. If for any reason `SEND_ENABLED` was changed to `true` before rollback is needed, do NOT re-enable `send_approved` until the dual-path conflict is fully analyzed. Set `SEND_ENABLED=false` first.

**Rollback is low-risk** because `send_approved` is currently inert (SEND_ENABLED=false). The retirement is a future-state protection, not an active change to current behavior.

---

## 7. Timing and Sequencing

The retirement must fit within the larger Stage C activation sequence. The required ordering is:

```
[Now]     SEND_ENABLED=false everywhere (current state)
[Step 1]  Apply Fix 1 + Fix 2 from DELIVERY_CORRECTNESS_ANALYSIS_001.md (code PRs)
[Step 2]  Deploy retirement of send_approved scheduler registration (this document)
[Step 3]  Wire Resend webhook to update send_attempts (D1 blocker)
[Step 4]  Verify RESEND_WEBHOOK_SECRET in Railway production env
[Step 5]  Avanish authorization → DB send_enabled=true
[Step 6]  Avanish authorization → SEND_ENABLED=true in Railway env
[Step 7]  First live dispatch window (Stage C)
```

**The retirement (Step 2) can be executed independently at any time after Step 1 PRs merge, because it has no behavioral effect while `SEND_ENABLED=false`.** It should be deployed no later than concurrent with Step 3.

---

## 8. Residual Risk After Retirement

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Manual invocation of `_send_approved_workspace` bypasses dual-path protection | Low — requires deliberate REPL call | Do not call `_send_approved_workspace` after Step 5. Only `dispatch_loop` is the authorized send path post-activation. |
| Retirement PR accidentally reverted in a future merge | Low | ACTIVATION_SAFETY_HARDENING_001.md pre-activation checklist includes "confirm send_approved not in scheduler jobs" |
| `dispatch_loop` alone fails to drain queue within send window | Low at batch_size=1; monitor first window | batch_size adjustment is a separate operational decision |

---

## 9. Post-Retirement State

After retirement is deployed and verified:

| Component | State |
|-----------|-------|
| `send_approved` scheduler job | NOT REGISTERED — inert, zero cron ticks |
| `_run_send_approved()` function | Present in code, not called by scheduler |
| `dispatch_loop` scheduler job | REGISTERED, firing Mon–Fri 8–11 AM CT |
| `reclaim_stale_locks` scheduler job | REGISTERED, firing every 2 minutes |
| Send path for all future sends | Exclusively `outbound_queue` → `dispatch_loop` |
| Legacy path for manual use | Available via direct function call only — not automated |

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/LEGACY_SEND_PATH_RETIREMENT_001.md`  
**Prerequisite documents:** `DELIVERY_CORRECTNESS_ANALYSIS_001.md`, `DARK_LAUNCH_RUNTIME_OBSERVATION_003.md`  
**Supersedes:** None (new document)
