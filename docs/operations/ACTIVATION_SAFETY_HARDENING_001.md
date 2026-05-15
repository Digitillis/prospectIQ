# Activation Safety Hardening — 001
## ProspectIQ — Stage C Readiness: GO/NO-GO Gate

**Document date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** ANALYSIS COMPLETE — Stage C execution pending prerequisite resolution  
**Coverage:** Workstreams W4 (send window), W6 (claim ordering), dependency graph D1–D16, rollout sequence, proof obligations, GO/NO-GO criteria

---

## 1. Summary Disposition

| Workstream | Blocker status | Resolution |
|-----------|---------------|-----------|
| W1 — Delivery lifecycle | **HARD BLOCKER** — webhook does not update send_attempts | D1: Wire webhook handler (separate PR) |
| W2 — Exactly-once safety | **HARD BLOCKER** — two crash scenarios, one causing stuck rows | Fix 1 + Fix 2 from DELIVERY_CORRECTNESS_ANALYSIS_001.md |
| W3 — Queue drain semantics | RESOLVED — DELETE on DELIVERED/PERMANENTLY_FAILED confirmed in dispatch_scheduler.py L316, L341 | No action needed |
| W4 — Send window consistency | RESOLVED AS DOCUMENTATION — send_window only in legacy path; dispatch_loop has no window check | Legacy path retirement removes all window logic from active path |
| W5 — Legacy path retirement | **HARD BLOCKER** — dual-path race prevents activation | Retire send_approved scheduler job (LEGACY_SEND_PATH_RETIREMENT_001.md) |
| W6 — Deterministic claim ordering | ADVISORY — non-deterministic only when multiple rows have identical enqueued_at | Recommendation: add enqueue_sequence column; not blocking Stage C |

**Stage C activation requires: D1 resolved + W2 fixes deployed + W5 retirement deployed + Resend webhook secret set + Avanish explicit authorization.**

---

## 2. Workstream 4: Send Window Consistency

### 2.1 Finding

The `send_window_start` and `send_window_end` configuration values (UTC hour integers) are used **exclusively** in the legacy `_send_approved_drafts()` path at `backend/app/agents/engagement.py` lines 376–381:

```python
if settings.send_window_end > 0:
    now_hour = datetime.utcnow().hour
    if not (settings.send_window_start <= now_hour < settings.send_window_end):
        logger.info("Outside send window (%s–%s UTC). Skipping.", ...)
        return result
```

The `dispatch_scheduler.py` module has **no send window check**. `dispatch_workspace()` will execute on any cron tick regardless of the time of day, subject only to the `SEND_ENABLED` env gate.

**Production values:** `SEND_WINDOW_START=13`, `SEND_WINDOW_END=16` (UTC) = 8:00–11:00 AM CDT. These values align with the cron schedule `hour="8-11"` in Chicago timezone, meaning the legacy path's software window check and the scheduler's cron trigger are redundant and always agree.

### 2.2 Disposition After Legacy Path Retirement

After `send_approved` is retired:

- `send_window_start` / `send_window_end` env vars become irrelevant to the active send path
- `dispatch_loop` cron schedule (`hour="8-11", timezone="America/Chicago"`) is the sole send window enforcement mechanism
- No code change to `dispatch_scheduler.py` is required
- The env vars may remain set — they are harmless

### 2.3 Winter vs. Summer Time Drift

The cron `timezone="America/Chicago"` parameter handles DST automatically. When clocks change, 8–11 AM CT shifts from UTC 13–16 (summer) to UTC 14–17 (winter). The scheduler correctly tracks this. The legacy `send_window_start/end` values (hardcoded at 13/16) would have drifted by 1 hour in winter — this was a latent bug in the legacy path. The dispatch cron has no such drift.

**W4 is closed as documentation.** No code change required for this workstream.

---

## 3. Workstream 6: Deterministic Claim Ordering

### 3.1 Current Behavior

`claim_outbound_queue_batch()` orders candidates by:

```sql
ORDER BY priority ASC, enqueued_at ASC
```

All 8 cohort rows were enqueued in a single transaction at `2026-05-15 21:24:00.XXXXXX UTC` — identical `enqueued_at` to microsecond precision. For rows with equal `priority` and equal `enqueued_at`, PostgreSQL resolves ties by **heap scan order** (physical tuple order on the table page). This is non-deterministic across vacuums, updates, and page rewrites.

**Practical consequence:** The 8-draft cohort will be claimed in an order that is correct but unpredictable at the contact level. Because the cohort was intentionally de-risked (different contacts, different companies except Eos Energy's 3 drafts), non-deterministic ordering does not cause a safety failure. It only affects which contacts receive emails in which batch window.

**Eos Energy specific:** The 3 Eos Energy drafts (Michael Finnigan, Kevin Mahoney, James Maguire) will be claimed in unpredictable relative order. With `batch_size=1` (the recommended pre-activation setting from OPERATIONAL_READINESS_ASSESSMENT_001.md Section Q4), they will be dispatched across 3 separate send windows — non-determinism does not cluster them.

### 3.2 Recommendation: Add `enqueue_sequence` Column

For production scale (>10 contacts/window), deterministic ordering is operationally important. The recommended fix is:

**Migration (additive, safe):**

```sql
ALTER TABLE outbound_queue
ADD COLUMN IF NOT EXISTS enqueue_sequence BIGSERIAL;
```

`BIGSERIAL` is a sequence-backed auto-increment — each INSERT gets the next sequence value regardless of transaction ordering. Rows inserted in the same transaction get distinct sequence values with the order determined by the INSERT statement execution order within the transaction.

**Updated claim ordering:**

```sql
ORDER BY priority ASC, enqueued_at ASC, enqueue_sequence ASC
```

**Tradeoffs:**

| Aspect | Current | With enqueue_sequence |
|--------|---------|----------------------|
| Ordering within same priority+enqueued_at | Heap scan (non-deterministic) | Insertion order within transaction (deterministic) |
| Migration risk | N/A | Additive — no existing row behavior changes |
| Backfill | Existing rows get NULL → sort as last within group | Acceptable |
| Performance | No change | Negligible (one additional sort key on indexed column) |

**Timing:** This migration is **not blocking Stage C**. The 8-draft cohort has acceptable non-determinism given the de-risked composition. The migration should be applied before expanding the backfill to the remaining 31 drafts (batch expansion gate).

### 3.3 Disposition

W6 is classified **ADVISORY**. Not blocking Stage C. Recommended before batch expansion.

---

## 4. Activation Dependency Matrix

All dependencies for Stage C (first live dispatch) and Stage D (batch expansion). Tiers reflect sequencing requirements.

### Tier 1 — Hard Blockers (Stage C cannot start)

| ID | Dependency | Status | Owner | Action |
|----|-----------|--------|-------|--------|
| D1 | Resend webhook handler updates `send_attempts` on delivery/bounce events | **OPEN** | Engineering | Wire `send_attempts` update in `POST /api/webhooks/resend`; add `RESEND_WEBHOOK_SECRET` to Railway prod env |
| D2 | Idempotency key per attempt | **RESOLVED** — `f"{draft_id}:{attempt_number}"` confirmed in dispatch_scheduler.py L249 | — | No action |
| D3 | Queue drain on terminal states | **RESOLVED** — DELETE on DELIVERED (L316) and PERMANENTLY_FAILED (L341/L367) | — | No action |
| D5 | `sent_at` atomic pre-send claim in `dispatch_queued_draft` | **OPEN** — currently set POST-SEND at engagement.py L1244 | Engineering | Fix 1 from DELIVERY_CORRECTNESS_ANALYSIS_001.md |
| D6 | `ALREADY_DELIVERED` stuck-row handling | **OPEN** — ASSERTION_FAILED loop when `sent_at` set before queue row deleted | Engineering | Fix 2 from DELIVERY_CORRECTNESS_ANALYSIS_001.md |
| D7 | `send_approved` legacy path retired from scheduler | **OPEN** | Engineering | LEGACY_SEND_PATH_RETIREMENT_001.md |
| D8 | `RESEND_WEBHOOK_SECRET` set in Railway production env | **OPEN** | Avanish (Railway console) | Set env var before enabling receives |

### Tier 2 — Required Before Activation Event (D9–D13)

| ID | Dependency | Status | Owner | Action |
|----|-----------|--------|-------|--------|
| D9 | `batch_size=1` confirmed in production DB `outreach_send_config` | **OPEN** | Avanish SQL | `UPDATE outreach_send_config SET batch_size=1 WHERE workspace_id=...` |
| D10 | Avanish confirms DB `send_enabled=true` authorization | **PENDING** | Avanish | Explicit sign-off in activation session |
| D11 | Avanish confirms `SEND_ENABLED=true` in Railway env authorization | **PENDING** | Avanish | Explicit sign-off in activation session — separate from D10 |
| D12 | 72h dark-launch observation window complete (no anomalies) | **PENDING** — window started 2026-05-15 16:24 CDT | — | First mandatory checkpoint: Monday 2026-05-18 8–11 AM CT tick |
| D13 | Stage C activation cohort verified (8 rows still in queue, unlocked) | **PENDING** | Pre-activation SQL check | `SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NULL` |

### Tier 3 — Required Before Batch Expansion (D14–D16, Stage D gate)

| ID | Dependency | Status | Owner | Action |
|----|-----------|--------|-------|--------|
| D14 | `enqueue_sequence` BIGSERIAL column added to `outbound_queue` | Advisory | Engineering | W6 recommendation — before expanding beyond 8-draft cohort |
| D15 | REVIEW candidates decided (ronny.hoff ZeroBounce result) | **PENDING** | Avanish | ZeroBounce verification of ronny.hoff@alterainfra.com |
| D16 | `send_attempts.status = FAILED` monitoring alert configured | Advisory | Engineering | Railway log alert or Supabase pg_cron query |

---

## 5. Exact Stage C Rollout Sequence

Stage C is the first live dispatch activation. All steps must be executed in order. No step may be skipped.

### Pre-Stage C: Engineering PRs (no activation yet)

```
[PR-FIX-1]   Apply atomic pre-send sent_at claim in dispatch_queued_draft
              Branch: bugfix/dispatch-atomic-sent-at-claim
              File: backend/app/agents/engagement.py (~line 1240)
              Risk: Medium — changes send atomicity. Requires staging soak.

[PR-FIX-2]   Add ALREADY_DELIVERED handling in dispatch_scheduler.py
              Branch: bugfix/dispatch-already-delivered-status
              File: backend/app/core/dispatch_scheduler.py (~line 309)
              Risk: Low — adds a new outcome handler branch. No existing path changed.

[PR-RETIRE]  Comment out send_approved scheduler registration
              Branch: bugfix/retire-send-approved-scheduler
              File: backend/app/api/main.py (lines 2140-2145)
              Risk: Low — no behavioral effect while SEND_ENABLED=false.

[PR-WEBHOOK] Wire send_attempts update in Resend webhook handler
              Branch: feature/resend-webhook-send-attempts
              File: backend/app/api/routes/webhooks.py
              Risk: Medium — requires send_attempts UPDATE on webhook receipt;
                    requires RESEND_WEBHOOK_SECRET validation.
```

All four PRs must be merged and deployed before Stage C activation.

### Stage C Activation Sequence (Avanish-gated steps)

**Step C1 — Pre-activation state verification (SQL, no mutations)**

```sql
-- Must ALL return expected values before proceeding
SELECT COUNT(*) FROM outbound_queue;                             -- Expect: 8
SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL; -- Expect: 0
SELECT COUNT(*) FROM send_attempts;                              -- Expect: 0
SELECT send_enabled, batch_size, daily_limit, max_retries
  FROM outreach_send_config WHERE workspace_id = :ws_id;
-- Expect: send_enabled=false, batch_size=1, daily_limit=125, max_retries=4
```

**If any count is unexpected, STOP. Do not proceed to Step C2.**

**Step C2 — Confirm RESEND_WEBHOOK_SECRET is set in Railway production**

Verify in Railway dashboard: environment variable `RESEND_WEBHOOK_SECRET` is present and non-empty. This must be set before any email is dispatched so that the first delivery event is captured.

**Step C3 — Set DB send_enabled = true (Avanish authorization required)**

```sql
UPDATE outreach_send_config
SET send_enabled = true
WHERE workspace_id = :ws_id;
```

**This change takes effect immediately.** With `SEND_ENABLED=false` still set in Railway env, the dispatcher continues to abort at the env gate. This step arms the DB gate only.

**Step C4 — Set SEND_ENABLED = true in Railway production env (Avanish authorization required)**

In Railway dashboard: set `SEND_ENABLED=true` for the production environment. Railway triggers a redeploy. The scheduler resumes on the new instance.

**This is the activation event.** The next cron tick (Mon–Fri 8–11 AM CT) will execute `dispatch_loop` without the env gate abort, claim up to `batch_size=1` rows from `outbound_queue`, and dispatch the first email.

**Step C5 — Confirm activation tick**

At the first cron tick after activation:

```
Expected log sequence:
1. _run_dispatch_loop fired
2. dispatch_workspace called: workspace_id=<ws>, batch_size=1, max_retries=4
3. Claimed 1 row from outbound_queue
4. _insert_send_attempt: attempt 1 for draft <id> — DISPATCHED
5. dispatch_queued_draft returned: DELIVERED
6. _update_send_attempt: status=DELIVERED, provider_message_id=<resend_id>
7. _delete_queue_row: deleted row <id>
8. Result: dispatched=1, delivered=1, transient=0, permanent=0, errors=0
```

**Step C6 — Post-first-send verification (SQL)**

```sql
SELECT COUNT(*) FROM outbound_queue;          -- Expect: 7 (one row consumed)
SELECT status, draft_id, provider_message_id,
       created_at, delivered_at
  FROM send_attempts
  ORDER BY created_at DESC LIMIT 5;           -- Expect: 1 DELIVERED row
SELECT sent_at FROM outreach_drafts WHERE id = :dispatched_draft_id;
-- Expect: non-null timestamp (set in dispatch_queued_draft pre-send or post-send)
```

**If Step C6 shows unexpected state, execute Emergency Freeze (Section 7 of this document).**

---

## 6. Rollback Procedures

### 6.1 Pre-Activation Rollback (Before Step C4)

Steps C1–C3 are individually reversible:

| Step | Rollback |
|------|---------|
| C3 (DB send_enabled=true) | `UPDATE outreach_send_config SET send_enabled=false WHERE workspace_id=:ws_id` — takes effect immediately, no deploy needed |
| PR-FIX-1, PR-FIX-2 deployed | Revert PRs — no behavioral effect while SEND_ENABLED=false |
| PR-RETIRE deployed | Revert PR — no behavioral effect while SEND_ENABLED=false |
| PR-WEBHOOK deployed | Revert PR — no behavioral effect until Resend events arrive |

### 6.2 Activation Rollback (After Step C4)

If anomalies are detected at Step C5 or C6:

**Immediate halt:**

```
Railway dashboard → production env → SEND_ENABLED → set to false
```

Railway triggers redeploy. `dispatch_loop` will abort at env gate on next tick. No further sends will be dispatched from the queue.

**Confirm halt via send-trace:**

```
GET /api/admin/send-trace
Expected: {"abort_at": "send_enabled=false", "trace": []}
```

**Assess damage:**

```sql
SELECT COUNT(*) FROM outbound_queue;
SELECT COUNT(*) FROM send_attempts;
SELECT status, draft_id, error_message, created_at
  FROM send_attempts
  ORDER BY created_at DESC;
```

**Determine if re-queue is needed:**

- If a row was deleted from `outbound_queue` but `send_attempts.status` is not DELIVERED, the draft was consumed but delivery is unknown. Check Resend dashboard for the `provider_message_id`.
- If delivery confirmed in Resend: no re-queue needed. The `outreach_drafts.sent_at` should be set.
- If delivery not confirmed: the contact may not have received the email. Assess manually before re-queuing.

**DB send_enabled rollback:**

```sql
UPDATE outreach_send_config
SET send_enabled = false
WHERE workspace_id = :ws_id;
```

**Full rollback state:** `outbound_queue` rows intact (minus any DELIVERED/PERMANENTLY_FAILED), `SEND_ENABLED=false` in env, `send_enabled=false` in DB. System returns to dark-launch state.

---

## 7. Emergency Freeze Procedure (Quick Reference)

The canonical Emergency Freeze Procedure is in `DARK_LAUNCH_RUNTIME_OBSERVATION_002.md` Section 12. This section provides the operator-facing quick reference.

**To halt all sends immediately:**

1. **Railway dashboard** → Production environment → `SEND_ENABLED` → change to `false`
2. Wait for Railway redeploy (typically 60–120 seconds)
3. Verify: `GET /api/admin/send-trace` returns `{"abort_at":"send_enabled=false"}`
4. Verify: `GET /api/admin/send-config` shows `env_send_enabled: false`
5. Execute DB gate: `UPDATE outreach_send_config SET send_enabled=false WHERE workspace_id=:ws_id`
6. Document: capture queue count, send_attempts count, timestamps
7. Do not re-enable without Avanish authorization

**No code deployment is required for emergency halt.** Railway env var change triggers immediate redeploy.

---

## 8. Proof Obligations Before First Live Send

The following must be demonstrably true — verified via SQL output or log confirmation — before the activation event (Step C4):

| # | Obligation | Verification method | Evidence required |
|---|-----------|--------------------|--------------------|
| P1 | `dispatch_queued_draft` sets `sent_at` atomically BEFORE Resend call | Code review of Fix 1 deployment | PR diff + commit SHA in deployment |
| P2 | `dispatch_scheduler.py` handles ALREADY_DELIVERED by deleting queue row | Code review of Fix 2 deployment | PR diff + commit SHA in deployment |
| P3 | Resend webhook updates `send_attempts` on `email.delivered` and `email.bounced` | Code review of PR-WEBHOOK deployment | PR diff + commit SHA in deployment |
| P4 | `RESEND_WEBHOOK_SECRET` is set in Railway production env | Railway env var inspection | Variable present, non-empty |
| P5 | `send_approved` scheduler job is NOT registered | Scheduler status API or Railway startup logs | Job list without `send_approved` |
| P6 | `outbound_queue` contains exactly 8 rows, all unlocked | SQL output | COUNT(*)=8, locked_by IS NULL count=8 |
| P7 | `send_attempts` contains 0 rows | SQL output | COUNT(*)=0 |
| P8 | `batch_size=1` in `outreach_send_config` | SQL output | batch_size=1 |
| P9 | `SEND_ENABLED=false` in production env immediately before changing to true | Railway env var inspection | Variable reads `false` before C4 step |
| P10 | 72h dark-launch window observation complete without anomalies | DARK_LAUNCH_RUNTIME_OBSERVATION_003 checkpoint document | Monday 2026-05-18 checkpoint documented |

All 10 obligations must be satisfied and documented before proceeding to Step C4.

---

## 9. GO / NO-GO Criteria for Stage C

### GO Criteria

All must be true:

```
[ ] D1 RESOLVED — Resend webhook updates send_attempts (PR-WEBHOOK deployed)
[ ] D5 RESOLVED — sent_at set atomically pre-send in dispatch_queued_draft (PR-FIX-1 deployed)
[ ] D6 RESOLVED — ALREADY_DELIVERED status exits stuck queue row loop (PR-FIX-2 deployed)
[ ] D7 RESOLVED — send_approved scheduler registration commented out (PR-RETIRE deployed)
[ ] D8 RESOLVED — RESEND_WEBHOOK_SECRET set in Railway production env
[ ] D9 RESOLVED — batch_size=1 in production outreach_send_config
[ ] D12 RESOLVED — 72h dark-launch observation window complete, no anomalies
[ ] D13 RESOLVED — 8 queue rows present, all unlocked
[ ] P1–P10 all satisfied and documented
[ ] Avanish explicit authorization: "authorize Stage C activation"
```

### NO-GO Conditions (any single condition blocks activation)

```
[ ] Any of D1, D5, D6, D7, D8, D9 unresolved
[ ] Dark-launch observation documented anomalies (stale locks not reclaimed,
    scheduler thread crash, APScheduler restart loop, DB connectivity loss)
[ ] send_attempts row count > 0 (prior partial send detected)
[ ] outbound_queue row count != 8 (unexpected mutation)
[ ] Any locked queue row (locked_by IS NOT NULL) at activation time
[ ] SEND_ENABLED already true in Railway env (unauthorized change detected)
[ ] DB send_enabled already true (unauthorized change detected)
[ ] Avanish authorization not received in current session
```

**If any NO-GO condition is present, activation is blocked.** Document the blocking condition in the activation checklist and assign a resolution owner before reconvening.

---

## 10. Stage D and E Readiness (Post-Activation)

These stages are not authorized in this session. Documented here for planning.

### Stage D — Batch Expansion (10 → 31 remaining drafts)

**Prerequisites:**
- Stage C complete with 8-draft cohort fully dispatched and delivered (confirmed via Resend + send_attempts)
- D14: `enqueue_sequence` migration applied
- D15: ronny.hoff ZeroBounce result received (include or exclude)
- Avanish authorization for batch expansion
- `batch_size` increase authorized (currently 1 → target TBD)

### Stage E — Ongoing Operations

**Prerequisites:**
- D16: send_attempts.status=FAILED monitoring alert configured
- Retry behavior validated (TRANSIENT_FAILED → exponential backoff → re-claim confirmed)
- PERMANENTLY_FAILED disposition reviewed (3 bounces = suppression logic validated)
- Webhook dedup tested (Resend may fire duplicate delivery events)
- Per-workspace send summary API or monitoring query established

---

## Appendix A: Two-Gate Send Architecture

For reference — the two independent gates that must both be `true` for any send to proceed:

```
Gate 1: SEND_ENABLED env var (Railway)
  - Checked in: _send_approved_workspace() L196, _dispatch_workspace() L217
  - Effect: immediate return, no Resend call, no DB mutation
  - Change requires: Railway env var update + redeploy

Gate 2: outreach_send_config.send_enabled (Supabase DB)
  - Checked in: _send_approved_drafts() L372, dispatch_workspace() reads batch config
  - Effect: engagement.py returns without sends; dispatch_scheduler does not check this gate directly (batch_size/max_retries are read from same table)
  - Change requires: SQL UPDATE, takes effect immediately
```

**For activation:** Gate 1 change (SEND_ENABLED=true) triggers deploy and is the externally visible activation event. Gate 2 change (DB send_enabled=true) takes effect immediately without deploy. Both must be true for sends to flow.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/ACTIVATION_SAFETY_HARDENING_001.md`  
**Prerequisite documents:** `DELIVERY_CORRECTNESS_ANALYSIS_001.md`, `LEGACY_SEND_PATH_RETIREMENT_001.md`, `DARK_LAUNCH_RUNTIME_OBSERVATION_003.md`, `OPERATIONAL_READINESS_ASSESSMENT_001.md`
