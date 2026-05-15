# Staged Activation Progression — 001
## ProspectIQ — Controlled Live-Send Authorization Sequence

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** ACTIVE — not yet initiated  
**Governing runbook:** `STAGE_C_ACTIVATION_RUNBOOK_001.md`  
**Prerequisite:** Monday 2026-05-18 observation window CLEAN verdict issued in `DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`

---

## Purpose

This document defines the exact staged progression for transitioning ProspectIQ from dark-launch (SEND_ENABLED=false) to governed live sends. Each stage must produce a documented evidence package before the next stage is authorized. No stage may be skipped or combined.

**Authorization model:** Avanish issues explicit verbal authorization at each stage boundary. Claude may not self-advance between stages.

---

## Current Pre-Activation State

| Item | Value |
|------|-------|
| `outbound_queue` rows | 8 (enqueued 2026-05-15) |
| Queue locked rows | 0 |
| `send_attempts` rows | 0 |
| SEND_ENABLED (Railway) | false |
| DB `send_enabled` | false |
| `batch_size` | 1 (to be confirmed D9) |
| `daily_limit` | 125 |
| `max_retries` | 4 |
| Active send window | Mon–Fri 8–11 AM CT |

---

## Stage Map

```
Stage 0 — Dark Launch Validation (COMPLETE pending Monday observation)
Stage 1 — Internal Sink Only
Stage 2 — Single Real Recipient (internal)
Stage 3 — Single-Company Cohort (8 drafts, production queue)
Stage 4 — Limited Production Cohort (up to 25 sends)
Stage 5 — Gradual Expansion (up to daily_limit)
```

---

## Stage 0 — Dark Launch Validation

**Status:** In progress. Monday 2026-05-18 observation window pending.

**Completion criteria:**
- `DARK_LAUNCH_RUNTIME_OBSERVATION_004.md` fully populated, overall verdict = CLEAN
- No unexpected `send_attempts` rows
- No queue mutations
- No provider activity in Resend dashboard
- Scheduler stability confirmed over full 8–11 AM CT window

**Authorizes:** Stage 1

---

## Stage 1 — Internal Sink Only

### Overview

Send one email to an internal sink address (Avanish's email or a test inbox), using a non-production draft that is NOT in the live `outbound_queue`. Purpose: confirm the full send path fires correctly end-to-end in production Rails + Supabase environment before touching the live cohort.

### Configuration for Stage 1

| Parameter | Value |
|-----------|-------|
| Max sends | 1 |
| Send target | Internal sink address only |
| Draft source | Manually inserted test draft — NOT from live cohort |
| SEND_ENABLED | true (Railway) |
| DB `send_enabled` | true (outreach_send_config) |
| `batch_size` | 1 |
| `daily_limit` | 1 (temporarily — prevents accidental live cohort send) |
| Observation duration | One send window (max 3 hours) |
| Window | First Mon–Fri 8–11 AM CT window after Stage 0 CLEAN verdict |

### Pre-Stage 1 Operator Actions (Avanish)

```sql
-- 1. Insert a test draft (internal sink recipient only)
--    Use workspace_id matching the production workspace
--    Use a non-production recipient email (e.g., avanish.mehrotra@gmail.com or a test inbox)
--    draft must have approval_status = 'approved', sent_at IS NULL

-- 2. Enqueue only the test draft
--    SELECT claim_outbound_queue_batch(...) — do NOT enqueue live cohort drafts
--    OR manually insert into outbound_queue:
INSERT INTO outbound_queue (draft_id, workspace_id, priority)
VALUES ('<test_draft_id>', '<workspace_id>', 5);

-- 3. Set daily_limit = 1 to prevent any queue overflow
UPDATE outreach_send_config
SET daily_limit = 1
WHERE workspace_id = '<workspace_id>';

-- 4. Confirm outbound_queue contains ONLY the test draft row
SELECT id, draft_id, locked_by FROM outbound_queue;
-- Expected: 1 row (test draft), 0 locked rows

-- 5. Confirm live cohort drafts are NOT in outbound_queue
-- (Live cohort was enqueued 2026-05-15 — verify those 8 rows are separate
--  or have been removed before Stage 1 begins)
```

### SEND_ENABLED Flip Sequence (Avanish)

```
1. Railway dashboard → ProspectIQ production service → Variables
2. Set SEND_ENABLED = true
3. Confirm deployment completes
4. GET /api/admin/send-config → verify env_send_enabled = true

5. Run SQL:
   UPDATE outreach_send_config SET send_enabled = true WHERE workspace_id = '<ws_id>';

6. GET /api/admin/send-config → verify db_send_enabled = true

7. Wait for 8 AM CT dispatch_loop fire
```

### Success Criteria

```
[ ] dispatch_loop claims the test draft row
[ ] send_attempts row inserted with status = DISPATCHED before Resend call
[ ] sent_at set on outreach_drafts BEFORE Resend call (atomic pre-send claim)
[ ] Resend API returns 200 with resend_message_id
[ ] outreach_drafts.resend_message_id populated
[ ] outreach_drafts.sent_at remains set (not rolled back)
[ ] send_attempts.status updated to DELIVERED after Resend response
[ ] outbound_queue row deleted (queue drained)
[ ] Internal sink inbox receives the email
[ ] Resend dashboard shows 1 delivered email
[ ] email.delivered webhook fires → send_attempts.reconciled_at populated
[ ] No error-level log lines
[ ] No queue row orphaned
```

### Rollback Criteria

Immediately set SEND_ENABLED = false in Railway if ANY of:
- Resend API returns error and send_attempts shows DISPATCHED not updated
- More than 1 send_attempts row created
- outbound_queue row NOT deleted after send
- Duplicate send detected (resend_message_id appears on two send_attempts rows)
- sent_at rollback triggered (log: `dispatch_queued_draft sent_at_rollback_failed`)
- Any live cohort draft_id appears in send_attempts

### Mandatory Evidence Capture

```
Document: STAGE1_EVIDENCE_001.md

Section 1: Pre-send SQL state
  - outbound_queue row count and content
  - send_attempts row count (expected: 0)
  - outreach_drafts.sent_at for test draft (expected: NULL)
  - outreach_drafts.resend_message_id for test draft (expected: NULL)
  - send_config state (send_enabled, batch_size, daily_limit)

Section 2: Dispatch execution log
  - Exact log lines from Railway for dispatch_loop fire
  - Exact log line for _insert_send_attempt (DISPATCHED)
  - Exact log line for Resend API call
  - Exact log line for post-send update
  - Queue row deletion confirmation

Section 3: Post-send SQL state
  - outbound_queue row count (expected: 0 — row deleted)
  - send_attempts row and status (expected: DELIVERED)
  - send_attempts.provider_message_id populated (expected: resend_message_id)
  - outreach_drafts.sent_at (expected: set)
  - outreach_drafts.resend_message_id (expected: set)

Section 4: Webhook confirmation
  - Resend dashboard screenshot: delivered status
  - send_attempts.reconciled_at (expected: set after webhook)
  - Webhook log line in Railway

Section 5: Email receipt confirmation
  - Screenshot or header dump of received email
  - From address, recipient, subject, body preview

Section 6: Stage 1 verdict: [PASS / FAIL]
```

**Authorizes (on PASS):** Stage 2

---

## Stage 2 — Single Real Recipient

### Overview

Send one email to a single real external recipient — a known warm contact (prospect who has previously engaged, or a trusted partner who has consented). Purpose: confirm Resend delivers to a real external inbox without issues. Not the live cohort — a fresh test draft for a single contact.

### Configuration for Stage 2

| Parameter | Value |
|-----------|-------|
| Max sends | 1 |
| Send target | Single external recipient, known warm contact |
| Draft source | Fresh test draft, NOT from live cohort |
| `daily_limit` | 2 (allow Stage 1 + Stage 2 sends in same day if needed) |
| SEND_ENABLED | true (already set from Stage 1) |
| Observation duration | 24 hours (for bounce/delivery confirmation) |

### Pre-Stage 2 Operator Actions

```sql
-- Confirm Stage 1 outbound_queue is empty
SELECT COUNT(*) FROM outbound_queue;
-- Expected: 0

-- Confirm Stage 1 send_attempts settled
SELECT id, status, provider_message_id, reconciled_at
FROM send_attempts
ORDER BY created_at DESC LIMIT 5;
-- Expected: Stage 1 row shows DELIVERED + reconciled_at set

-- Confirm daily_limit allows Stage 2 send
UPDATE outreach_send_config SET daily_limit = 2 WHERE workspace_id = '<ws_id>';

-- Insert fresh test draft for real recipient
-- (draft must be pre-written, vetted, appropriate for external delivery)
-- Enqueue:
INSERT INTO outbound_queue (draft_id, workspace_id, priority)
VALUES ('<stage2_draft_id>', '<workspace_id>', 5);
```

### Success Criteria

Same as Stage 1, plus:
```
[ ] External recipient confirms receipt (or Resend shows delivered)
[ ] No spam folder delivery (if verifiable)
[ ] No bounce (email.bounced webhook not fired within 24 hours)
[ ] No unsubscribe triggered
[ ] send_attempts.reconciled_at set after delivery webhook
```

### Rollback Criteria

Set SEND_ENABLED = false if ANY of:
- Bounce received for test recipient
- Email flagged as spam
- Any live cohort draft_id appears in send_attempts
- Resend domain reputation warning appears in dashboard

### Mandatory Evidence Capture

```
Document: STAGE2_EVIDENCE_001.md

Same sections as STAGE1_EVIDENCE_001.md plus:

Section 5: External delivery confirmation
  - Resend dashboard: delivered status for recipient domain
  - Webhook reconciled_at set within 60 minutes of send
  - Bounce log (expected: empty within 24 hours)
  - Unsubscribe log (expected: empty)

Section 6: Stage 2 verdict: [PASS / FAIL]
```

**Authorizes (on PASS):** Stage 3

---

## Stage 3 — Single-Company Cohort (Live Queue)

### Overview

Enable live sends from the existing 8-draft cohort (enqueued 2026-05-15) for the first real prospect company. This is the first time the live `outbound_queue` is touched with SEND_ENABLED=true.

**Scope:** The 8-draft cohort contains drafts for a single target company. Send all 8 at batch_size=1 across Monday–Friday morning windows. Do NOT enqueue additional drafts during Stage 3.

### Configuration for Stage 3

| Parameter | Value |
|-----------|-------|
| Max sends | 8 (existing cohort only) |
| Draft source | Live outbound_queue cohort (8 rows, enqueued 2026-05-15) |
| `batch_size` | 1 |
| `daily_limit` | 2 (max 2 sends per day — conservative pacing) |
| SEND_ENABLED | true |
| Observation duration | Full cohort drain (≤ 4 business days at daily_limit=2) |
| Advance check | D13 SQL re-run — confirm 8 rows, all unlocked, retry_count=0 |

### Pre-Stage 3 Operator Actions

```sql
-- Confirm cohort state unchanged since enqueue
SELECT id, draft_id, locked_by, locked_at, retry_count, next_retry_at
FROM outbound_queue
ORDER BY enqueued_at;
-- Expected: 8 rows, all NULL locked_by, all retry_count=0

-- Set daily_limit = 2
UPDATE outreach_send_config
SET daily_limit = 2
WHERE workspace_id = '<ws_id>';

-- SEND_ENABLED is already true from Stage 1/2
-- No additional Railway change needed
```

### Per-Send Verification (each dispatch window)

After each send window completes:
```sql
-- How many were sent today?
SELECT COUNT(*) FROM send_attempts
WHERE created_at >= CURRENT_DATE
  AND status IN ('DELIVERED', 'DISPATCHED');

-- Queue state
SELECT COUNT(*) AS remaining FROM outbound_queue;
SELECT id, draft_id, retry_count, next_retry_at FROM outbound_queue;

-- Any failures?
SELECT * FROM send_attempts WHERE status IN ('FAILED', 'PERMANENTLY_FAILED');

-- Any rollback events?
-- Check Railway logs for: sent_at_rollback_failed, ALREADY_DELIVERED, PERMANENTLY_FAILED
```

### Success Criteria

```
[ ] All 8 drafts dispatched without duplicate sends
[ ] Each send: send_attempts row DELIVERED + reconciled_at set within 24h
[ ] No retry loop observed (retry_count stays 0 for successful sends)
[ ] outbound_queue fully drained after all 8 sends
[ ] No bounce for any recipient
[ ] No spam reports (monitor Resend dashboard)
[ ] daily_limit respected: ≤ 2 sends per calendar day
[ ] batch_size=1 confirmed: each tick dispatches exactly 1 draft
[ ] No PERMANENTLY_FAILED send_attempts rows
[ ] Resend domain reputation: no degradation warnings
```

### Rollback Criteria

Set SEND_ENABLED = false and STOP immediately if:
- Duplicate send detected (same draft_id appears in 2 send_attempts rows with DELIVERED)
- Any send_attempts row shows `lost_send_pre_claim_crash` failure_code
- 3 or more TRANSIENT_FAILED outcomes on the same draft_id
- Bounce rate > 20% within Stage 3
- Resend domain reputation warning
- Queue row count INCREASES (unexpected enqueue)
- `retry_count` reaches `max_retries` on any queue row

### Mandatory Evidence Capture

```
Document: STAGE3_EVIDENCE_001.md

Section 1: Pre-Stage 3 SQL state (cohort baseline)
Section 2: Per-send log (one entry per dispatch tick):
  - Tick timestamp
  - draft_id dispatched
  - send_attempts row: status, provider_message_id
  - outbound_queue remaining row count
  - Any anomalies

Section 3: Post-drain SQL state
  - outbound_queue row count (expected: 0)
  - send_attempts row count (expected: 8, all DELIVERED)
  - reconciled_at set on all rows
  - No PERMANENTLY_FAILED rows

Section 4: Resend dashboard summary
  - 8 delivered, 0 bounced, 0 spam

Section 5: Stage 3 verdict: [PASS / FAIL]
```

**Authorizes (on PASS):** Stage 4

---

## Stage 4 — Limited Production Cohort

### Overview

Enqueue a second cohort of up to 25 additional drafts (covering multiple companies). daily_limit raised to 5. This is the first multi-company send batch.

**Authorization required from Avanish:** explicit instruction to enqueue next batch and raise daily_limit.

### Configuration for Stage 4

| Parameter | Value |
|-----------|-------|
| Max sends | 25 (across multiple companies) |
| `batch_size` | 1 |
| `daily_limit` | 5 |
| Observation duration | Full cohort drain + 48h post-drain monitoring |
| Additional prerequisite | Stage 3 evidence package reviewed and accepted |

### Pre-Stage 4 Operator Actions

```sql
-- Confirm Stage 3 drain complete
SELECT COUNT(*) FROM outbound_queue;
-- Expected: 0

-- Review Stage 3 send_attempts
SELECT status, COUNT(*) FROM send_attempts GROUP BY status;
-- Expected: all DELIVERED

-- Set daily_limit = 5
UPDATE outreach_send_config
SET daily_limit = 5
WHERE workspace_id = '<ws_id>';

-- Enqueue next cohort (up to 25 drafts)
-- Execute enqueue procedure — explicit Avanish instruction required
```

### Success Criteria

```
[ ] All 25 sends complete without duplicates
[ ] Bounce rate < 5%
[ ] No spam reports
[ ] No PERMANENTLY_FAILED rows (other than expected bounces)
[ ] Queue fully drains within expected window
[ ] daily_limit respected
[ ] Resend domain reputation stable
```

### Rollback Criteria

Same as Stage 3. Additionally:
- Bounce rate > 5% → STOP, do not advance to Stage 5
- Any duplicate send detected → immediate freeze

### Mandatory Evidence Capture

```
Document: STAGE4_EVIDENCE_001.md
Same structure as STAGE3_EVIDENCE_001.md at larger scale.
Include: per-company delivery breakdown, bounce analysis.
```

**Authorizes (on PASS):** Stage 5

---

## Stage 5 — Gradual Expansion

### Overview

Raise `daily_limit` toward the configured maximum (125). Expand cohort size incrementally. This stage is ongoing operational mode, not a single event. Advancement within Stage 5 requires no new document — only continued monitoring via standard operational procedures.

### Configuration for Stage 5

| Parameter | Starting value | Max value |
|-----------|---------------|-----------|
| `batch_size` | 1 | 1 (do not raise without explicit authorization) |
| `daily_limit` | 10 | 125 |
| Cohort size | 25–50 per batch | As authorized |
| Observation cadence | Daily review | Weekly review once stable |

### Incremental `daily_limit` Progression

```
Stage 5a: daily_limit = 10
Stage 5b: daily_limit = 25 (after 5a stable for 5 business days)
Stage 5c: daily_limit = 50 (after 5b stable for 5 business days)
Stage 5d: daily_limit = 125 (after 5c stable for 5 business days)
```

Each step requires Avanish authorization and no bounce-rate degradation.

### Ongoing Success Criteria

```
[ ] Bounce rate < 3% (target); < 5% (maximum before pause)
[ ] Spam complaint rate < 0.1%
[ ] All send_attempts rows settle to DELIVERED or PERMANENTLY_FAILED within 48h
[ ] No queue row orphans (retry_count > max_retries without resolution)
[ ] Resend domain reputation: green
[ ] No duplicate sends (validate weekly via send_attempts dedup query)
```

### Permanent Rollback Capability

At any point in Stage 5:
```
1. SET SEND_ENABLED = false in Railway (immediate effect — no redeploy needed)
2. UPDATE outreach_send_config SET send_enabled = false WHERE workspace_id = '<ws_id>';
3. Queue rows remain intact — no sends will fire
4. Resume by re-enabling after investigation
```

---

## Stage Transition Authorization Log

| Stage | Authorized by | Authorization date | Evidence doc | Verdict |
|-------|--------------|-------------------|-------------|---------|
| Stage 0 → 1 | Avanish | TBD | DARK_LAUNCH_RUNTIME_OBSERVATION_004.md | PENDING |
| Stage 1 → 2 | Avanish | TBD | STAGE1_EVIDENCE_001.md | PENDING |
| Stage 2 → 3 | Avanish | TBD | STAGE2_EVIDENCE_001.md | PENDING |
| Stage 3 → 4 | Avanish | TBD | STAGE3_EVIDENCE_001.md | PENDING |
| Stage 4 → 5 | Avanish | TBD | STAGE4_EVIDENCE_001.md | PENDING |

---

## Emergency Freeze Procedure (Any Stage)

```
1. Railway dashboard → ProspectIQ production → Variables
2. Set SEND_ENABLED = false
3. Confirm deploy completes
4. Run: UPDATE outreach_send_config SET send_enabled = false WHERE workspace_id = '<ws_id>';
5. Confirm no in-flight locks: SELECT * FROM outbound_queue WHERE locked_by IS NOT NULL;
6. Wait 5 minutes for stale lock reclaim to fire
7. Confirm: SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL;
   Expected: 0
8. Document freeze in current stage evidence document (anomaly section)
```

**Reference:** `STAGE_C_ACTIVATION_RUNBOOK_001.md` Part 4 (Emergency Freeze Procedure).

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/STAGED_ACTIVATION_PROGRESSION_001.md`  
**Governing runbook:** `STAGE_C_ACTIVATION_RUNBOOK_001.md`
