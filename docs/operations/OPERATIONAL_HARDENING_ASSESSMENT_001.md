# Operational Hardening Assessment — 001
## ProspectIQ — Critical Gaps Before and During Stage C Activation

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** ACTIVE — for review before Stage C initiation  
**Governing runbook:** `STAGE_C_ACTIVATION_RUNBOOK_001.md`  
**Scope:** Critical operational gaps only. No speculative architecture.

---

## Purpose

This document identifies the critical gaps in operational readiness, observability, rollback capability, and data integrity that remain open as of the Stage C activation checkpoint. Each item is classified by severity and mapped to a concrete remediation action.

This is not a feature roadmap. Items not classified as CRITICAL are excluded.

---

## Severity Classification

| Class | Meaning |
|-------|---------|
| **CRITICAL-BLOCK** | Must be resolved before ANY live send. Stage C cannot proceed. |
| **CRITICAL-STAGE1** | Must be resolved before Stage 1 (internal sink send). |
| **CRITICAL-STAGE3** | Must be resolved before Stage 3 (live cohort send). |
| **CRITICAL-ONGOING** | Must be monitored continuously across all live stages. |

---

## Section 1 — Critical Operational Gaps

### OPS-001: RESEND_WEBHOOK_SECRET Not Set in Production

**Severity:** CRITICAL-BLOCK (D8)  
**Status:** PENDING — Avanish console action required

**Gap:** The Resend webhook endpoint (`POST /resend-webhook`) accepts unauthenticated payloads when `RESEND_WEBHOOK_SECRET` is not configured. Any caller can POST a fake `email.delivered` or `email.bounced` event, causing spurious `send_attempts` reconciliation — including false PERMANENTLY_FAILED outcomes.

**Impact without fix:**
- Fake bounce webhook poisons DELIVERED row → marks draft PERMANENTLY_FAILED
- No audit trail distinguishing real vs. fake webhook events
- send_attempts state becomes untrustworthy

**Remediation:**
```
1. Resend dashboard → Webhooks → copy signing secret
2. Railway dashboard → ProspectIQ production → Variables
3. Set RESEND_WEBHOOK_SECRET = <value from Resend>
4. Deploy and confirm: GET /api/admin/send-config → resend_webhook_secret_configured = true
```

**Verification SQL (post-fix):**
No SQL — this is a Railway env var. Verify via the send-config endpoint.

---

### OPS-002: batch_size=1 Not Confirmed in Production

**Severity:** CRITICAL-BLOCK (D9)  
**Status:** PENDING — Avanish SQL action required

**Gap:** `outreach_send_config.batch_size` has not been verified as 1 in the production DB. If batch_size > 1, the `claim_outbound_queue_batch()` RPC claims multiple rows per tick, which:
- Sends multiple emails per cron fire during first live test
- Makes Stage 1 "single send" guarantee impossible
- Increases blast radius of any dispatch error

**Remediation:**
```sql
-- Verify:
SELECT batch_size FROM outreach_send_config WHERE workspace_id = '<ws_id>';

-- If not 1, fix:
UPDATE outreach_send_config SET batch_size = 1 WHERE workspace_id = '<ws_id>';
```

---

### OPS-003: No Send-Count Circuit Breaker

**Severity:** CRITICAL-STAGE1  
**Status:** Gap — no automated enforcement

**Gap:** `daily_limit` is enforced in the dispatch loop by counting send_attempts rows created today. However, there is no hard circuit breaker that prevents sends after the limit is reached — the enforcement relies on the count query path being correct and on no concurrency gap between count and claim.

**Specific risk:** If two dispatch_loop ticks fire within the same second (e.g., Railway scheduler fires twice due to infrastructure glitch), both ticks could pass the daily_limit check before either inserts a send_attempt.

**Impact:** At batch_size=1 and daily_limit=1 (Stage 1), this would produce 2 sends instead of 1.

**Remediation (immediate, no schema change):**
Confirm that the daily_limit count query in `dispatch_scheduler.py` runs INSIDE the same transaction scope as the batch claim. If it runs before the RPC, the race window exists.

**Verification action:**
```
Review dispatch_scheduler.py:
  1. Where is the daily_limit count query relative to claim_outbound_queue_batch()?
  2. Is there a DB-level check or only application-level?
  3. If application-level only, document as accepted risk at batch_size=1
     (probability low, impact = 1 extra send — recoverable)
```

**Accepted risk at Stage 1–2:** At batch_size=1, duplicate send produces at most 1 extra email. The idempotency key prevents a true duplicate send to Resend. This is a recoverable anomaly, not a data loss event. Accept for Stage 1–2; revisit before Stage 4 (25+ sends).

---

### OPS-004: No Automated Alert on PERMANENTLY_FAILED or Lost Send

**Severity:** CRITICAL-STAGE3  
**Status:** Gap — operator must poll SQL manually

**Gap:** When `dispatch_scheduler.py` records a PERMANENTLY_FAILED or `lost_send_pre_claim_crash` outcome, it logs at ERROR level but sends no external alert. During Stage 3–5, if sends are failing silently, the operator will not know until they query `send_attempts`.

**Impact:** Lost sends, bounces, and crash-recovery failures accumulate undetected between operator check-ins.

**Remediation (minimal, no new schema):**
The error-level log lines already exist. Wire Railway log alerts to notify on:
- `"lost_send_pre_claim_crash"` in log output
- `"PERMANENTLY_FAILED"` in dispatch log
- `"sent_at_rollback_failed"` in dispatch log

```
Railway dashboard → ProspectIQ production → Observability → Log Alerts
Create alert: contains "lost_send_pre_claim_crash" OR "PERMANENTLY_FAILED"
Destination: email or Slack
```

This requires a Railway console action, not a code change.

---

## Section 2 — Critical Observability Gaps

### OBS-001: No Send-Trace Endpoint in Production

**Severity:** CRITICAL-STAGE1  
**Status:** Partial — `GET /api/admin/send-trace` exists but coverage unknown

**Gap:** The runbook (`STAGE_C_ACTIVATION_RUNBOOK_001.md`) references `GET /api/admin/send-trace` and `GET /api/admin/send-config` as verification endpoints. If these endpoints are not deployed and functional in production, the operator has no programmatic way to verify send gate state without direct DB access.

**Verification action (pre-Stage 1):**
```
GET /api/admin/send-config
Expected fields: env_send_enabled, db_send_enabled, batch_size, daily_limit, max_retries

GET /api/admin/send-trace
Expected fields: abort_at (if aborted), last_dispatch_loop_at, last_attempted_draft_id, etc.
```

Run these manually before Stage 1. If either 404s, do not proceed.

---

### OBS-002: send_attempts Has No Created Timestamp Index

**Severity:** CRITICAL-STAGE3  
**Status:** Gap — daily_limit count query may be slow at scale

**Gap:** The daily send count query filters `send_attempts` by `created_at >= CURRENT_DATE`. If `send_attempts` lacks an index on `created_at`, this is a full table scan. At Stage 3 (8 rows) this is trivial. At Stage 5 (100+ rows per day), it degrades.

**Impact at current scale:** None — the table is empty.  
**Impact at Stage 5:** Dispatch latency spike at count query. Risk: dispatch_loop misses its 30-minute window due to slow count → reduced throughput.

**Remediation (no urgency before Stage 3):**
```sql
-- Check if index exists:
SELECT indexname FROM pg_indexes
WHERE tablename = 'send_attempts'
  AND indexdef LIKE '%created_at%';

-- If missing, create (non-blocking):
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_send_attempts_created_at
ON send_attempts (created_at);
```

This is an additive index with no behavioral change. Safe to run at any time.

---

### OBS-003: No Webhook Receipt Confirmation in Operator Runbook

**Severity:** CRITICAL-STAGE1  
**Status:** Gap — webhook confirmation is a manual step in the runbook, not automated

**Gap:** The Stage 1 success criteria require `send_attempts.reconciled_at` to be set by the Resend webhook. If the webhook is not correctly configured (wrong URL in Resend dashboard, RESEND_WEBHOOK_SECRET mismatch, Railway routing issue), reconciliation silently fails and the operator may not notice.

**Remediation:**
Before Stage 1, verify the Resend webhook endpoint is reachable from Resend's infrastructure:
```
1. Resend dashboard → Webhooks → verify endpoint URL matches production Railway URL
2. Confirm the URL is HTTPS (not http://)
3. Send a test event from Resend dashboard → confirm Railway logs receive it
4. Confirm send_attempts.reconciled_at is set for the test event
```

This is a pre-Stage 1 console action, not a code change.

---

## Section 3 — Critical Rollback Weaknesses

### ROL-001: SEND_ENABLED=false Does Not Drain In-Flight Locks

**Severity:** CRITICAL-ONGOING  
**Status:** Known behavior — documented, not a bug

**Gap:** Setting SEND_ENABLED=false in Railway prevents new claims but does NOT release rows already locked by a concurrent dispatch_loop tick. Locked rows are held for `STALE_LOCK_MINUTES=5` before `reclaim_stale_locks()` releases them.

**Impact on emergency freeze:** After setting SEND_ENABLED=false, there is a 5-minute window during which a row that was claimed before the flag flip may still have its send attempted (if the process is mid-dispatch).

**Mitigation (already in place):**
- `reclaim_stale_locks()` fires every 2 minutes
- After Railway redeploy (which the flag flip triggers), any in-flight process is killed — stale locks reclaimed on next cycle
- Lock TTL = 5 minutes means max exposure = 5 minutes

**Operator action on emergency freeze:**
```sql
-- After SEND_ENABLED=false flip, wait 5 minutes, then confirm:
SELECT * FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Expected: 0 locked rows

-- If rows still locked after 10 minutes, manually clear:
UPDATE outbound_queue SET locked_by = NULL, locked_at = NULL
WHERE locked_at < NOW() - INTERVAL '5 minutes';
```

This behavior is acceptable at batch_size=1. Document in each stage evidence package.

---

### ROL-002: No Row-Level Audit Trail for Manual Queue Manipulation

**Severity:** CRITICAL-STAGE3  
**Status:** Gap — no trigger or audit table

**Gap:** The runbook prescribes manual SQL for queue and send_config manipulation (during Stage transitions). These SQL changes are not logged at the DB level. If a manual UPDATE to `outreach_send_config` or `outbound_queue` is incorrect, there is no automatic audit trail showing the prior value.

**Impact:** During incident investigation, operator cannot determine if a misconfiguration was pre-existing or introduced during manual intervention.

**Remediation (immediate, no schema change required):**
Before every manual SQL action, capture the prior state:
```sql
-- BEFORE any manual UPDATE, run:
SELECT * FROM outreach_send_config WHERE workspace_id = '<ws_id>';
SELECT * FROM outbound_queue;
-- Copy the output into the current stage evidence document.
```

This is a protocol change, not a code change. Already incorporated into runbook Step 2.

---

### ROL-003: Rollback SQL Missing from Stage Evidence Templates

**Severity:** CRITICAL-STAGE1  
**Status:** Gap in document templates (not in code)

**Gap:** The Stage 1–4 evidence templates (defined in `STAGED_ACTIVATION_PROGRESSION_001.md`) include post-send SQL verification but do not include the rollback SQL to undo each specific stage's configuration changes.

**Remediation:**
Each stage evidence document must include a rollback section:

```
Stage 1 Rollback SQL:
  -- If Stage 1 fails:
  UPDATE outreach_send_config SET send_enabled = false, daily_limit = 125
    WHERE workspace_id = '<ws_id>';
  -- Railway: Set SEND_ENABLED = false
  -- Delete test draft from outbound_queue:
  DELETE FROM outbound_queue WHERE draft_id = '<test_draft_id>';

Stage 3 Rollback SQL:
  -- If Stage 3 must be halted mid-drain:
  UPDATE outreach_send_config SET send_enabled = false WHERE workspace_id = '<ws_id>';
  -- Railway: Set SEND_ENABLED = false
  -- Do NOT delete remaining queue rows — they are the live cohort
  -- Let stale lock reclaim clear any in-flight locks
```

---

## Section 4 — Critical Data Integrity Risks

### DI-001: send_attempts Orphan Risk on Crash During Queue Delete

**Severity:** CRITICAL-ONGOING  
**Status:** Known behavior — not a bug, but requires monitoring

**Risk:** The dispatch_scheduler sends the email, updates `send_attempts` to DELIVERED, then calls `_delete_queue_row()`. If the process crashes between the DELIVERED update and the queue delete, the `outbound_queue` row remains locked. On stale lock reclaim, the row is re-claimed, `dispatch_queued_draft` fires again, and the atomic pre-send claim catches `sent_at` already set → returns ALREADY_DELIVERED → drain fires → queue row deleted.

**Net result:** The send_attempts table gets a second row (from the re-dispatch) with status DELIVERED and `failure_reason = "already_delivered_drain: ..."`. This is the correct behavior but produces a second DB row.

**Monitoring query:**
```sql
-- Check for multiple send_attempts per draft_id:
SELECT draft_id, COUNT(*) AS attempt_count
FROM send_attempts
GROUP BY draft_id
HAVING COUNT(*) > 1;
-- Expected at Stage 3+: 0 rows (all clean)
-- If > 0: investigate for crash-recovery drain events
```

Run this query after every Stage 3+ dispatch window.

---

### DI-002: resend_message_id NULL After Successful Send (Webhook Race)

**Severity:** CRITICAL-STAGE3  
**Status:** Known window — no code fix needed, monitoring required

**Risk:** After `dispatch_queued_draft` completes successfully, `outreach_drafts.resend_message_id` is set and `send_attempts.status = DELIVERED`. However, `send_attempts.reconciled_at` is set only after the Resend `email.delivered` webhook fires. In the window between send and webhook (typically 0–30 seconds, but up to minutes if webhook is delayed), `reconciled_at` is NULL.

This is expected behavior. However, if an operator queries `send_attempts` in this window and sees `reconciled_at IS NULL`, they may incorrectly diagnose a webhook failure.

**Monitoring guidance:**
```sql
-- Check reconciled_at NULL rows — check if sent_at was recent:
SELECT sa.id, sa.status, sa.reconciled_at, d.sent_at, d.resend_message_id
FROM send_attempts sa
JOIN outreach_drafts d ON sa.draft_id = d.id
WHERE sa.reconciled_at IS NULL
  AND sa.status = 'DELIVERED';

-- If sent_at is < 30 minutes ago AND resend_message_id is set: normal, webhook pending
-- If sent_at is > 2 hours ago AND resend_message_id is set: webhook may have failed
```

**Threshold for escalation:** If `reconciled_at IS NULL` and `sent_at` is > 2 hours old, investigate Resend webhook delivery logs.

---

### DI-003: Draft Approval Status Not Validated at Dispatch

**Severity:** CRITICAL-STAGE1  
**Status:** Gap — no runtime assertion on approval_status

**Risk:** `dispatch_queued_draft` asserts certain draft preconditions before sending. However, if `outreach_drafts.approval_status` has been modified after enqueue (e.g., set to 'rejected' or 'draft' by a background process or manual SQL), the dispatch loop currently has no check on approval_status at claim time.

**Impact:** A draft could be sent after it was manually de-approved post-enqueue.

**Verification action (pre-Stage 1, no code change):**
```sql
-- Before any live send, confirm all queued drafts are still approved:
SELECT oq.draft_id, d.approval_status, d.sent_at
FROM outbound_queue oq
JOIN outreach_drafts d ON oq.draft_id = d.id
WHERE d.approval_status != 'approved'
   OR d.sent_at IS NOT NULL;
-- Expected: 0 rows

-- Incorporate this check into every pre-send verification step
```

The `dispatch_queued_draft` function already fetches the draft and asserts preconditions. If `approval_status` is not in the assertion list, add a review note — but do not add new code without Avanish authorization (per operational stabilization constraint).

---

## Section 5 — Pre-Stage 1 GO/NO-GO Addendum

The following items from this assessment must be resolved before Stage 1 can begin:

| Item | Action Owner | Blocking? |
|------|-------------|-----------|
| OPS-001: RESEND_WEBHOOK_SECRET set | Avanish (Railway console) | CRITICAL-BLOCK |
| OPS-002: batch_size=1 confirmed | Avanish (SQL) | CRITICAL-BLOCK |
| OBS-001: send-config endpoint verified | Avanish + operator | CRITICAL-STAGE1 |
| OBS-003: Resend webhook URL verified in dashboard | Avanish (Resend console) | CRITICAL-STAGE1 |
| ROL-003: Stage evidence templates include rollback SQL | Per-stage (at time of execution) | CRITICAL-STAGE1 |
| DI-003: Approval status pre-flight query run | Operator | CRITICAL-STAGE1 |

Items classified CRITICAL-STAGE3 and CRITICAL-ONGOING may be deferred until Stage 3 without blocking Stage 1.

---

## Items Explicitly Out of Scope

The following were considered and excluded as non-critical at current scale:

- Alerting webhook retries / Resend webhook retry configuration (Resend handles internally)
- Read replica / connection pool tuning (dispatch is low-frequency)
- Multi-tenant isolation review (single workspace in current cohort)
- Rate-limit backoff configuration for Resend API (Resend free/paid tier limits far above 8 sends)
- Async dispatch architecture (sync is correct and sufficient at current batch_size)
- Dead letter queue (PERMANENTLY_FAILED outcome + operator SQL is sufficient recovery)

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/OPERATIONAL_HARDENING_ASSESSMENT_001.md`  
**Governing runbook:** `STAGE_C_ACTIVATION_RUNBOOK_001.md`
