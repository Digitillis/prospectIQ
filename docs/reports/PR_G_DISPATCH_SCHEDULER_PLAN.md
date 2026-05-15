# PR G — Dispatch Scheduler: Design Plan

**Branch**: `feature/dispatch-scheduler` (to be created)
**Author**: Avanish Mehrotra & Digitillis Architecture Team
**Created**: 2026-05-15
**Status**: PLANNING — awaiting Avanish approval before any code is written
**Prerequisite**: PR #107 (PR F) merged, PR #108 (hard gate remediation) merged and signed off

---

## Objective

Wire the `outbound_queue` table (created in PR F) to an actual dispatch loop.
Today, approved drafts are sent by `EngagementAgent._send_approved_drafts`, which
scans `outreach_drafts` directly. PR G replaces that path with a queue-consumer
that reads `outbound_queue`, claims rows with a distributed lock, calls Resend,
and writes the result to `send_attempts`.

---

## Carry-Forward Risks (must be addressed inside this PR)

### Risk 1 — Supabase connection pool saturation

**Root cause**: Five or more APScheduler jobs fire simultaneously (`:52` and `:07`
marks each 15 minutes). Each fires a PostgREST HTTP/2 request. The shared connection
pool cannot service them all simultaneously, producing `Server disconnected` errors.

**Fix inside PR G**:
- Stagger scheduler intervals so no two heavy DB jobs share the same fire time.
  Specifically: `_run_health_snapshot`, `_run_pipeline_qc`, `_run_draft_generation`,
  and `_run_gmail_intake` must not share a `:00` minute offset.
- The dispatch loop itself must serialize DB operations within a batch
  (sequential claim + send, not parallel).
- Add `httpx` timeout + retry-with-jitter on `RemoteProtocolError` for the
  Supabase client initialization.

**Not in scope**: full asyncpg migration (Workstream 2 backlog).

### Risk 2 — gmail_api_client.py missing from git

**Fix**: separate remediation PR committed before PR G merges to main.
PR G must not be merged while this file is missing from git.

### Risk 3 — SEND_ENABLED

SEND_ENABLED remains `false` in production and staging until explicitly authorized
by Avanish after PR G is merged, tested in staging, and the send-activation checklist
is completed. This plan does not authorize enabling sends.

---

## Current Send Path (pre-PR G)

```
outreach_drafts (approval_status='approved', sent_at=NULL)
  └─ _send_approved_workspace
       └─ EngagementAgent.run(action='send_approved')
            ├─ fetch approved drafts (scans outreach_drafts directly)
            ├─ atomic claim: UPDATE sent_at=NOW WHERE sent_at IS NULL
            ├─ run pre-send assertions (suppression, company lock, contact check)
            ├─ call resend.Emails.send(idempotency_key=draft_id)
            └─ record outcome (no send_attempts table used)
```

**Gaps**: No persistent retry, no send_attempts record, no queue row. Orphaned drafts
(claim set, Resend call failed before completion) are stuck with sent_at set and
no recovery path except manual intervention.

---

## Target Send Path (PR G)

```
outbound_queue (locked_by=NULL, next_retry_at=NULL)
  └─ _run_dispatch_loop (new — replaces _send_approved_workspace for the send step)
       ├─ claim batch: UPDATE locked_by=<instance_id>, locked_at=NOW
       │   WHERE locked_at IS NULL AND (next_retry_at IS NULL OR next_retry_at <= NOW)
       │   LIMIT batch_size
       │   RETURNING *
       ├─ for each claimed row:
       │    ├─ fetch draft + contact + company from outreach_drafts
       │    ├─ run pre-send assertions (suppression, company lock, contact validation)
       │    │    └─ on assertion failure: release lock (set locked_by=NULL, locked_at=NULL)
       │    │       do NOT set next_retry_at — leave for next scheduler tick
       │    ├─ INSERT send_attempts (status=DISPATCHED, attempt_number, idempotency_key)
       │    ├─ call resend.Emails.send(idempotency_key=<idempotency_key>)
       │    ├─ on 2xx (DELIVERED):
       │    │    ├─ UPDATE send_attempts SET status=DELIVERED, resolved_at=NOW
       │    │    ├─ UPDATE outreach_drafts SET sent_at=NOW
       │    │    └─ DELETE FROM outbound_queue WHERE id=<queue_row_id>
       │    ├─ on 5xx / 429 (transient FAILED):
       │    │    ├─ UPDATE send_attempts SET status=FAILED, failure_code, failure_reason
       │    │    └─ UPDATE outbound_queue SET
       │    │         retry_count = retry_count + 1,
       │    │         next_retry_at = NOW + backoff(retry_count),
       │    │         locked_by = NULL, locked_at = NULL
       │    └─ on 4xx except 429 (PERMANENTLY_FAILED):
       │         ├─ UPDATE send_attempts SET status=PERMANENTLY_FAILED
       │         ├─ UPDATE outreach_drafts SET approval_status='send_failed'  ← new enum value
       │         └─ DELETE FROM outbound_queue WHERE id=<queue_row_id>
       └─ stale lock reclaim (runs as separate sweep, every 2 minutes):
            UPDATE outbound_queue SET locked_by=NULL, locked_at=NULL
            WHERE locked_at < NOW - interval '5 minutes'
```

---

## Retry Backoff Schedule

| retry_count | next_retry_at delay | rationale |
|-------------|--------------------|-----------| 
| 0 → 1 | +5 minutes | transient network blip |
| 1 → 2 | +15 minutes | rate limit cooldown |
| 2 → 3 | +60 minutes | extended backoff |
| 3 → 4 | +4 hours | next business window |
| 4+ | PERMANENTLY_FAILED | abandon after 4 transient failures |

Max retries is configurable via `outreach_send_config.max_retries` (new column, default 4).
A single new column added via migration 055.

---

## Pre-PR F Approved Drafts (Backfill Problem)

Drafts approved before PR F was deployed have:
- `approval_status IN ('approved', 'edited')`
- `sent_at IS NULL`
- NO row in `outbound_queue`

PR G's dispatch loop will never see these drafts because it only reads `outbound_queue`.

**Resolution**: `scripts/backfill_outbound_queue.py` — a one-time script that:
1. Selects all drafts matching the above conditions
2. INSERTs them into `outbound_queue` using `ON CONFLICT DO NOTHING`
3. Prints a count of rows inserted

Avanish runs this script manually after PR G merges and before SEND_ENABLED
is set to true. It is reviewed and explicitly authorized before execution — it is
NOT run automatically.

---

## New `approval_status` Enum Value: `send_failed`

For permanently failed sends, the draft needs a terminal status distinct from
`rejected` (human decision) and `approved` (ready to send). `send_failed` is
added to the `approval_status` enum in migration 055.

This ensures the review UI can surface permanently failed drafts for human
triage rather than leaving them in an ambiguous `approved` state.

---

## Connection Pool Fix — Scheduler Staggering

Current: five jobs fire at :52 and :07 simultaneously.

Proposed job offsets (all intervals remain the same — only initial offsets change):

| Job | Current | Proposed offset |
|-----|---------|-----------------|
| `_run_health_snapshot` | :00 mark | +0s |
| `_run_pipeline_qc` | :00 mark | +45s |
| `_run_gmail_intake` | :00 mark | +90s |
| `_run_draft_generation` | :00 mark | +30s |
| `_run_dispatch_loop` (new) | :00 mark | +120s |

Staggering by 30–120 seconds prevents simultaneous PostgREST connection pool
exhaustion without changing any business logic.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/agents/engagement.py` | Replace `_send_approved_drafts` with queue-consumer entrypoint; keep assertions |
| `backend/app/core/dispatch_scheduler.py` | NEW — queue claim, Resend call, retry logic, stale lock reclaim |
| `backend/app/core/database.py` | Add: `claim_outbound_queue_batch`, `release_queue_lock`, `delete_queue_row`, `upsert_send_attempt`, `schedule_retry` |
| `backend/app/api/main.py` | Replace `_send_approved_workspace` with `_dispatch_workspace`; add stale-lock reclaim job; stagger job offsets |
| `supabase_migrations/migrations/055_dispatch_schema.sql` | `send_failed` enum value; `max_retries` column on `outreach_send_config` |
| `scripts/backfill_outbound_queue.py` | NEW — one-time manual backfill |
| `backend/tests/test_pr_g_dispatch.py` | NEW — dispatch loop, retry logic, stale lock, permanently failed path |
| `scripts/MIGRATION_ORDER.txt` | Append 055 |

---

## What is NOT in PR G

- Resend webhook receiver (for delivery confirmation callbacks) — Workstream 2
- Per-sender daily cap enforcement — Workstream 5
- Queue depth / send funnel dashboard — Workstream 2
- asyncpg migration (replacing PostgREST HTTP) — Workstream 2
- SEND_ENABLED authorization — explicit session approval required from Avanish

---

## Migration 055 — Minimal Schema

```sql
-- Add send_failed to approval_status enum
ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'send_failed';

-- Add max_retries to outreach_send_config
ALTER TABLE outreach_send_config
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 4;
```

No new tables. No RLS changes. Fully additive.

---

## Test Coverage (PR G)

| Test class | What it covers |
|------------|----------------|
| `TestQueueClaim` | Batch claim sets locked_by/locked_at; second claim skips already-locked rows |
| `TestDispatchSuccess` | DELIVERED path: send_attempts DELIVERED, queue row deleted, sent_at set |
| `TestTransientFailure` | 5xx path: send_attempts FAILED, retry_count++, next_retry_at set, lock released |
| `TestPermanentFailure` | 4xx path: send_attempts PERMANENTLY_FAILED, queue row deleted, approval_status=send_failed |
| `TestMaxRetries` | At retry_count >= max_retries, treat as PERMANENTLY_FAILED regardless of error type |
| `TestStaleLockReclaim` | Rows locked > 5 min ago have lock cleared |
| `TestAssertionFailure` | Pre-send assertion failure releases lock without writing send_attempts |
| `TestIdempotency` | Resend "already sent" response treated as DELIVERED |
| `TestSendEnabledGate` | dispatch_loop exits immediately if send_enabled=False |

---

## Open Questions for Avanish Before Implementation

1. **`send_failed` enum value** — is this the right name, or do you prefer `dispatch_failed`?

2. **Backfill authorization** — confirmed that backfill of pre-PR F approved drafts
   is a manual step you run after reviewing the script output. No auto-backfill on deploy.

3. **Max retries default** — 4 attempts acceptable, or should the limit be higher/lower?

4. **Stale lock timeout** — 5 minutes proposed. Is this too short (false reclaims under
   slow Resend API responses) or acceptable?

5. **Scheduler stagger** — proposed offsets above look acceptable? These are code changes
   to APScheduler initialization in `main.py`.

---

## Authorization Gate

Implementation does not begin until Avanish responds to the open questions above
and explicitly says to proceed.

SEND_ENABLED is not changed by this PR. Enabling sends is a separate explicit action.
