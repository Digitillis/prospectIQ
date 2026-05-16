# ProspectIQ Operational Doctrine and Runtime Architecture
## Institutional Memory: Phase 0 → Stage C Transition

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Date:** 2026-05-15  
**Status:** CANONICAL — do not amend without understanding all referenced invariants  
**Purpose:** Preserve the reasoning, invariants, and operational philosophy of the ProspectIQ dispatch runtime

---

## Preamble

This document exists because the most important knowledge about a production system is not in the code — it is in the understanding of why the code is the way it is.

Code shows you what the system does. This document explains what problems were solved to get here, why each design decision was made, and what happens if future contributors treat those decisions as arbitrary and reverse them.

If you are reading this as a new contributor, start here before reading any other document.

---

## Part I — The Problem This System Was Built to Solve

### 1.1 The Original Architecture and Its Failures

ProspectIQ's original outreach send path used a single function: `EngagementAgent.run(action="send_approved")`. This function fetched approved drafts, and sent them via Resend. It was registered as a cron job (`send_approved`) firing Monday through Friday, every 30 minutes during the 8–11 AM CT window.

The original architecture had no concept of a queue, no transactional claim, no pre-send invariant, and no reconciliation path. It fetched drafts that looked sendable and called Resend. If anything went wrong between "looks sendable" and "confirmed sent," the system had no way to detect it, recover from it, or produce a forensic record.

**The fundamental failures were:**

**Failure 1 — No crash recovery.** If the process crashed after Resend accepted the call but before `sent_at` was written to the database, the draft would be re-fetched on the next cron tick and sent again. There was no mechanism to detect that the first send succeeded. The result: duplicate emails to real prospects.

**Failure 2 — No pre-send record.** There was no row written to any table before the Resend call. If Resend accepted the call and the process crashed before any update completed, the send was permanently unrecorded. The draft would show `sent_at = NULL` and `approval_status = approved` — indistinguishable from a draft that had never been sent. On the next tick, it would be dispatched again.

**Failure 3 — No idempotency.** Even if the same draft was sent twice, there was nothing to prevent Resend from delivering two emails to the same recipient. Each call to Resend's API was a fresh, unrelated request.

**Failure 4 — No queue isolation.** Multiple concurrent dispatch attempts on the same draft had no exclusion mechanism. If two scheduler ticks fired close together (which can happen under infrastructure load), both could fetch the same draft and both could call Resend.

**Failure 5 — No audit trail.** There was no structured record of dispatch attempts — no timestamp, no provider message ID, no failure reason, no retry count. Operational forensics required reading application logs, which are ephemeral.

### 1.2 Why These Failures Matter More Than They Appear

Sending a duplicate email to a manufacturing executive at a target account is not a recoverable situation. The prospect receives two identical messages. They immediately understand that the sender's system is unreliable or poorly managed. The credibility of the outreach — and of the platform behind it — is destroyed.

This is not an edge case. Under the original architecture, any process restart, Railway deployment, or infrastructure glitch during a cron window would produce duplicate sends. At low send volumes (8 drafts), the probability of encountering this failure window is low. At 50+ sends per day, it becomes near-certain that it will occur at some point.

The transactional queue architecture was introduced specifically to make duplicate sends structurally impossible, not merely unlikely.

---

## Part II — The Transactional Queue Architecture

### 2.1 What Changed

The core architectural change, implemented in PR G (migrations 054/055), was the introduction of a transactional outbox pattern:

- `outbound_queue` table: holds queued draft_ids waiting for dispatch
- `claim_outbound_queue_batch()` PostgreSQL RPC: claims rows using `FOR UPDATE SKIP LOCKED`
- `send_attempts` table: records every dispatch attempt as an immutable row
- `dispatch_workspace()` function in `dispatch_scheduler.py`: orchestrates the claim, attempt, and outcome sequence
- `dispatch_queued_draft()` method in `EngagementAgent`: handles a single draft with the correct invariant sequence

### 2.2 The Invariant Sequence

The dispatch path enforces a strict ordering of operations. This ordering is not incidental — it is the specific sequence that makes crash recovery possible.

```
1. claim_outbound_queue_batch(RPC)    — atomically locks one or more queue rows
2. _insert_send_attempt()            — DISPATCHED row written BEFORE Resend call
3. pre-send claim (sent_at = NOW())  — atomic UPDATE WHERE sent_at IS NULL
4. Resend API call                   — email dispatched
5. resend_message_id written         — provider confirmation stored
6. send_attempts updated             — DELIVERED with provider_message_id
7. outbound_queue row deleted        — queue drained
```

Every step that comes before the Resend call is designed so that if the process crashes after that step, the next tick can determine what happened and respond correctly. Every step that comes after the Resend call is designed so that if it fails, the system can recover from the DB state.

### 2.3 Why `FOR UPDATE SKIP LOCKED` Is the Right Mechanism

`FOR UPDATE SKIP LOCKED` is a PostgreSQL locking primitive that serves two purposes:

1. **Claim exclusion:** When the RPC locks a row, no other concurrent session can claim the same row. This eliminates the concurrent dispatch race at the database level, not the application level.

2. **Skip, not block:** Rather than making concurrent dispatchers wait for a lock to release, `SKIP LOCKED` allows them to skip locked rows and claim the next available one. This means stale locks from a crashed process do not block all other dispatches — only the affected rows are temporarily unavailable.

Do not replace this with application-level locking. Application-level locks (Redis, advisory locks, `locked_by` without `FOR UPDATE`) can fail in ways that database-level locks cannot. A database transaction abort automatically releases all held locks. An application process crash does not automatically release a Redis lock.

### 2.4 Why `send_attempts` Must Exist Before the Resend Call

This is the single most important invariant in the dispatch system. Violating it makes the entire crash recovery model fail.

The reason is simple: if the process crashes after calling Resend (which accepted the email) but before recording any outcome, there must be some evidence in the database that the send was attempted. That evidence is the DISPATCHED row in `send_attempts`.

On crash recovery:
- The stale lock on `outbound_queue` is reclaimed after 5 minutes
- The re-dispatched draft hits the pre-send claim: `UPDATE outreach_drafts SET sent_at=NOW() WHERE id=:id AND sent_at IS NULL`
- If `sent_at` is already set (because step 3 completed before the crash), the claim returns 0 rows → ALREADY_DELIVERED outcome
- `_resolve_provider_message_id()` checks `outreach_drafts.resend_message_id` to determine whether Resend was actually called
- If yes: drain with DELIVERED status. If no: drain with FAILED status (lost_send_pre_claim_crash)
- Either way, the queue row is deleted and no retry is scheduled

Without the pre-existing DISPATCHED row, the crash recovery path has no anchor. The re-dispatch attempt would insert a new row and call Resend again — duplicate send.

### 2.5 The Atomic Pre-Send Claim and Why It Exists

The pre-send claim is this operation:
```python
UPDATE outreach_drafts SET sent_at = NOW()
WHERE id = :draft_id AND sent_at IS NULL
```

This is not a timestamp. It is an exclusive claim on the right to send this draft. The `WHERE sent_at IS NULL` clause means only one concurrent dispatch can succeed in setting it. Every other concurrent attempt to dispatch the same draft will find `sent_at IS NOT NULL` and return ALREADY_DELIVERED.

**Why this is done at the application layer, not in the RPC:** The `claim_outbound_queue_batch()` RPC handles queue-row exclusion. The pre-send `sent_at` claim handles draft-level exclusion. They protect against different failure modes. The queue lock protects against two dispatchers claiming the same queue row at the same time. The pre-send claim protects against a stale lock being reclaimed and the same draft being re-dispatched when the first send may have already succeeded.

**Why `sent_at` is rolled back on Resend failure:** If Resend fails (network error, API error, rate limit), `sent_at` is reset to NULL:
```python
UPDATE outreach_drafts SET sent_at = NULL WHERE id = :draft_id
```
This releases the claim so that the retry path can re-acquire it on the next dispatch attempt. Without this rollback, a transient Resend failure would permanently prevent a draft from being re-dispatched (every retry would hit ALREADY_DELIVERED and drain the row without sending).

---

## Part III — The SEND_ENABLED Discipline

### 3.1 What SEND_ENABLED Is

`SEND_ENABLED` is a two-layer control:
1. Railway environment variable (`SEND_ENABLED=false` in the production service)
2. Database flag (`outreach_send_config.send_enabled = false`)

Both must be `true` for the dispatch loop to proceed. Neither alone is sufficient.

The check occurs in `_dispatch_workspace()` in `main.py`:
```python
if not get_settings().send_enabled:
    return
```

This check fires before `dispatch_workspace()` is ever called. When `SEND_ENABLED=false`, the dispatch loop fires on schedule, logs `dispatch_loop: running for 1 workspace(s)`, and immediately returns. No queue rows are claimed. No send_attempts are created. No Resend calls are made.

### 3.2 Why Two Layers

A single flag creates a single point of failure. If the Railway environment variable is accidentally changed during a deployment, sends begin without intent. If the DB flag is accidentally changed via a SQL migration or admin action, sends begin without intent.

Two independent layers mean: activating sends requires two separate, independent, intentional actions. This is not paranoia — it is the correct design for a system where accidental sends are not recoverable.

### 3.3 Why SEND_ENABLED Defaults to False in Every Environment

Every new Railway environment, every staging deployment, and every test environment starts with `SEND_ENABLED=false`. This is not a reminder — it is a hard default.

The cost of accidentally leaving `SEND_ENABLED=false` when you meant to enable sends: one missed send window. Recoverable.

The cost of accidentally having `SEND_ENABLED=true` in a staging environment that points at a real Resend account: real emails delivered to real prospects from a test run. Not recoverable.

Defaults that fail safe are not optional.

### 3.4 Why SEND_ENABLED Must Not Be Enabled Without the Full Pre-Send Checklist

Before any SEND_ENABLED flip to `true`, the operator must verify:
- `outbound_queue` contains only the intended cohort
- All queue rows are unlocked (`locked_by IS NULL`)
- `send_attempts` has 0 rows (no prior attempts on this cohort)
- `batch_size = 1`
- All cohort drafts have `sent_at IS NULL` and `approval_status = approved`
- D8 (RESEND_WEBHOOK_SECRET) is set in Railway

Any single item out of expected state is a stop condition. Do not proceed.

---

## Part IV — Staging Isolation and Why It Is Mandatory

### 4.1 The Problem with Shared Environments

Early in ProspectIQ's development, the distinction between staging and production environments was conceptual, not enforced. The risk this creates is specific: a staging test run that inadvertently points to the production Supabase database will mutate production data. A staging dispatch run with SEND_ENABLED=true will send real emails.

These are not theoretical risks. They are the predictable consequences of insufficient environment isolation.

### 4.2 The Isolation Rules

The following constraints are permanent and absolute:

**Production Supabase reference (`wlyhbdmjhgvovigogdco`) must never appear in staging credentials.** If staging uses the production DB URL, there is no staging — there is only production accessed with a staging label. Any test, migration, or dispatch run in "staging" that uses this reference is a production operation.

**Production DATABASE_URL must never be stored as a GitHub Actions secret.** CI pipelines that run migrations or tests must never have access to production credentials. A misconfigured CI job that triggers on the wrong branch could run a destructive migration against production.

**SEND_ENABLED must be false in every environment except when explicitly authorized for a specific activation step.** This constraint applies even to staging. Staging with `SEND_ENABLED=true` pointed at a real Resend account will deliver real emails.

### 4.3 Why Environment Boundaries Are Cheaper to Enforce Than to Recover From

The argument against strict environment isolation is usually: "it slows down development." This argument reverses the cost structure. The slow-down from strict isolation is a one-time setup cost paid once per environment. The cost of an environment boundary violation — duplicate emails to real prospects, corrupted production data, unauthorized sends — is paid indefinitely in lost credibility and manual recovery effort.

---

## Part V — Legacy Path Retirement and Why It Mattered

### 5.1 The Dual-Path Race Condition

At the point of PR G (queue architecture introduction), two send paths existed:
1. `send_approved`: the original path using `EngagementAgent.run(action="send_approved")`
2. `dispatch_loop`: the new queue-consumer path using `dispatch_workspace()`

Both were registered on the same cron schedule: Monday through Friday, every 30 minutes from 8 AM to 11 AM CT.

With `SEND_ENABLED=true`, this created a race condition: on any given cron tick, both `send_approved` and `dispatch_loop` could attempt to dispatch the same draft simultaneously. The `send_approved` path could claim the draft via its own atomic `sent_at` update before `dispatch_queued_draft`'s pre-send claim fired. The result would be a `sent_at` set by `send_approved` with no corresponding queue row deletion and no `send_attempts` record — leaving the queue in an inconsistent state and potentially triggering an ALREADY_DELIVERED on the next dispatch_loop tick.

### 5.2 The Retirement Decision (D7)

The retirement of `send_approved` from the scheduler was not a cleanup decision. It was a correctness decision. While both paths were registered, the transactional dispatch invariants of the new path could be violated by the old path at any tick.

The retirement was implemented by commenting out the `scheduler.add_job` call for `send_approved`:
```python
# scheduler.add_job(
#     _run_send_approved, "cron",
#     day_of_week="mon-fri", hour="8-11", minute="0,30",
#     timezone="America/Chicago",
#     id="send_approved",
# )
```

The function `_run_send_approved()` was retained — it can be called manually for diagnostic purposes. But it will never be re-registered in the scheduler without a full analysis of how it interacts with the queue-consumer path.

**Invariant:** `dispatch_loop` is the sole scheduler-registered send path. Any future contribution that re-registers `send_approved` or adds a second send path to the scheduler must prove, in a formal analysis, that it cannot race with `dispatch_loop`.

---

## Part VI — Replay, Reconciliation, and Why Auditability Is Non-Negotiable

### 6.1 The Replay Problem

After any crash, restart, or failure, the system must be able to answer three questions for every queue row:

1. Was the email sent?
2. If yes, was the provider's confirmation received?
3. If no, is it safe to retry?

Without structured answers to these questions, the operator must either guess (risking duplicate sends) or do nothing (leaving drafted cohort members uncontacted).

The replay model in ProspectIQ answers these questions via DB state, not log analysis:

| `sent_at` | `resend_message_id` | Interpretation | Action |
|-----------|--------------------|--------------|-|
| NULL | NULL | Not yet sent | Dispatch normally |
| SET | NULL | Pre-send claim succeeded; Resend never called | ALREADY_DELIVERED → Scenario E → drain as FAILED(lost_send) |
| SET | SET | Email sent and confirmed | ALREADY_DELIVERED → Scenario C → drain as DELIVERED |
| NULL | SET | Not possible (resend_message_id written after send) | Investigate |

This matrix is exhaustive. Every crash scenario maps to exactly one row in this table. The system does not need log analysis, operator judgment, or external coordination to determine the correct recovery action. The DB state is the single source of truth.

### 6.2 Webhook Reconciliation and Why It Closes the Loop

The Resend API is fire-and-forget from the application's perspective: you call it, it returns 200 and a `resend_message_id`, and you update your local state to DELIVERED. But "delivered" at the provider level (accepted by Resend's API) is not the same as "delivered" at the recipient level (received in the inbox).

The webhook reconciliation path (D1) closes this gap:
- `email.delivered`: Resend confirms the message was accepted by the recipient's mail server → `send_attempts.reconciled_at` is set
- `email.bounced`: Resend confirms the message could not be delivered → `send_attempts.status = PERMANENTLY_FAILED`, `failure_code = bounce`

Without this reconciliation, the platform can only report that it dispatched an email — not that the email was delivered. The `reconciled_at` field is the evidence of delivery at the recipient level.

**Why `reconciled_at` is a separate field from `resolved_at`:** `resolved_at` marks when the dispatch cycle completed (the system's perspective). `reconciled_at` marks when the provider confirmed the delivery (the recipient's perspective). These are different events that may occur minutes or hours apart. Conflating them would make it impossible to distinguish "we dispatched it" from "we know it was delivered."

### 6.3 Why send_attempts Is an Audit Trail, Not Just a Status Table

Every row in `send_attempts` is a forensic record. It contains:
- `attempt_number`: which attempt this was (1, 2, 3...)
- `idempotency_key`: the exact key passed to Resend (draft_id:attempt_number)
- `status`: the current outcome
- `failure_code`: what failed, if anything
- `failure_reason`: human-readable detail
- `provider_message_id`: Resend's identifier for this send
- `reconciled_at`: when the provider confirmed delivery

A future contributor who removes or simplifies `send_attempts` to "just track the latest status" loses the ability to:
- prove that a draft was not sent twice (no attempt_number history)
- reconstruct the idempotency key for a specific attempt
- distinguish a send that failed on attempt 1 but succeeded on attempt 2

Do not simplify this table.

---

## Part VII — The Dark-Launch Protocol and Its Lessons

### 7.1 What the Dark-Launch Proved

The dark-launch period (running with `SEND_ENABLED=false`, cohort in queue, scheduler active) was not a precaution. It was a proof of correctness of the runtime model.

The three things the dark-launch validated:

1. **Scheduler determinism:** `dispatch_loop` fires at exactly the scheduled times (Mon–Fri, :00 and :30, 8–11 AM CT). It does not fire at unexpected times, does not fire twice, and does not fail silently.

2. **Queue inertness under closed gates:** With `SEND_ENABLED=false`, the queue remains completely unchanged across multiple send windows. No rows are claimed, no locks are set, no state transitions occur.

3. **Reclaim loop correctness:** `reclaim_stale_locks` fires every 2 minutes and correctly reports no stale locks when none exist. If stale locks appeared, they would be reclaimed before the next dispatch tick.

The absence of anomalies during the dark-launch is itself evidence. A system that fires on schedule, touches nothing it shouldn't touch, and produces exactly the expected log output across multiple observation windows is a system that can be trusted with the first live send.

### 7.2 The Most Important Observation Is the One That Doesn't Happen

During dark-launch observation, the operator watches for absence: no `dispatch.claim_batch` log line, no send_attempts rows, no queue mutations. This is different from watching for presence.

Most operational monitoring focuses on detecting things that happen. Dark-launch observation is different — the critical signal is the non-occurrence of events that should not occur. When `SEND_ENABLED=false`, every dispatch tick that fires without claiming a queue row is a confirmation that the gate is working.

**Lesson:** Build observability for both expected events and expected non-events. The absence of a send_attempt during a dark-launch window is as important to document as the presence of a delivered send during activation.

### 7.3 Why Dark-Launch Preceded Every Activation Stage

The activation sequence was:
1. Queue architecture deployed
2. Dark-launch observation (SEND_ENABLED=false, scheduler active, cohort present)
3. Observation window confirmed CLEAN
4. Stage 1 internal sink activation (single send)
5. Stage 2 single real recipient
6. Stage 3 live cohort
7. ...

The temptation at each stage is to skip the preceding observation step. "We already ran dark-launch — why do we need another observation before Stage 3?"

The answer is that each observation window is not a repetition of the previous one. It is a verification of the specific state immediately preceding the next activation. The queue state, scheduler state, draft state, and send config state at the moment of activation must all be verified — even if they were verified 24 hours earlier. Configuration drift, partial deployments, and manual SQL actions can change state between observations.

---

## Part VIII — Activation Sequencing and Why It Is Structured as It Is

### 8.1 The Stage Model

Activation proceeds through defined stages, each of which must be completed before the next begins:

| Stage | Max sends | What it proves |
|-------|-----------|---------------|
| Stage 0 | 0 (dark-launch) | Scheduler determinism, queue inertness |
| Stage 1 | 1 (internal sink) | Full send path executes correctly end-to-end |
| Stage 2 | 1 (real external) | Resend delivery to real inbox, webhook reconciliation |
| Stage 3 | 8 (live cohort) | Multi-send correctness, queue drain, daily_limit |
| Stage 4 | 25 (limited) | Multi-company correctness, bounce handling |
| Stage 5 | Daily_limit | Full operational pace |

Each stage exists because it proves something that the previous stage could not prove. Stage 1 proves the code path executes. Stage 2 proves Resend delivery actually reaches an inbox. Stage 3 proves the queue drains correctly across multiple ticks. No stage can be skipped because skipping a stage means skipping the proof that stage was designed to produce.

### 8.2 Why Evidence Documents Are Mandatory at Each Stage

Every stage transition requires a documented evidence package. This is not bureaucracy. It is the institutional record of what was observed at each stage, which will be referenced when diagnosing problems at later stages.

If Stage 3 produces a bounce and the operator needs to know whether the same email address bounced in Stage 2, the answer is in the Stage 2 evidence document — not in the logs, which may have rotated, and not in memory, which may have faded.

Evidence documents also enforce activation discipline. An operator who knows they must produce a documented evidence package before the next stage is less likely to rush through observation. The documentation burden is by design.

### 8.3 Operational Impatience Is the Highest Risk After Stage 1

Once Stage 1 succeeds (a real email is delivered end-to-end), the natural instinct is to accelerate. "Everything is working — let's scale up."

This is the most dangerous moment in the activation sequence.

Stage 1 proves that the system can execute a send correctly once. It does not prove:
- what happens when the daily_limit is approached
- what happens when a bounce occurs mid-cohort
- what happens when a send_attempts row shows TRANSIENT_FAILED
- what happens when the operator is not actively watching the window

Each of these scenarios is only provable by experiencing it in a controlled context where the blast radius is limited. The staged activation sequence is the mechanism for limiting blast radius. Collapsing it because "everything looks good" eliminates that protection.

---

## Part IX — Architectural Invariants

These constraints are not preferences. They are invariants — conditions that must hold for the system to behave correctly. Future contributors should treat any PR that touches these as requiring a full formal analysis of the invariant they are modifying.

### Invariant 1 — Pre-Send Record Before Resend Call

`_insert_send_attempt()` must complete successfully before `resend.Emails.send()` is called. If the insert fails (DB error, connection timeout), the dispatch must abort for this draft — release the lock, do not call Resend.

**Why:** If Resend is called without a DISPATCHED row, a crash between the call and any subsequent DB write produces a permanently unrecorded send. The idempotency key prevents a duplicate send at the provider level, but does not give the application any way to know the first send succeeded.

### Invariant 2 — Atomic Pre-Send Claim Before Resend Call

`UPDATE outreach_drafts SET sent_at=NOW() WHERE id=:id AND sent_at IS NULL` must complete before `resend.Emails.send()` is called, and the result must be checked. If 0 rows updated, return ALREADY_DELIVERED — do not call Resend.

**Why:** If `sent_at` is already set when the claim is attempted, either a prior dispatch already claimed and sent the draft, or a prior dispatch crashed after claiming but before Resend was called. Either way, calling Resend again is the wrong action.

### Invariant 3 — Rollback sent_at on Resend Failure

If `resend.Emails.send()` raises an exception, `sent_at` must be reset to NULL before returning a TRANSIENT_FAILED or PERMANENTLY_FAILED outcome.

**Why:** If `sent_at` remains set after a failed send, the next retry attempt will hit the pre-send claim and find `sent_at IS NOT NULL`. It will return ALREADY_DELIVERED. `_resolve_provider_message_id()` will find `resend_message_id IS NULL` (because Resend never confirmed). The draft will be drained with `lost_send_pre_claim_crash`. The email is never sent. The retry window is permanently closed.

### Invariant 4 — Queue Row Deleted After Every Terminal Outcome

Every terminal outcome — DELIVERED, PERMANENTLY_FAILED, ALREADY_DELIVERED — must delete the queue row. Non-terminal outcomes — TRANSIENT_FAILED, ASSERTION_FAILED — must either schedule a retry or release the lock.

**Why:** An undeleted queue row for a terminal draft means the draft will be re-dispatched on the next claim. A PERMANENTLY_FAILED draft re-dispatched will fail again, consuming a retry slot. A DELIVERED draft re-dispatched will hit ALREADY_DELIVERED and drain correctly, but produces a spurious `send_attempts` row that pollutes the audit trail.

### Invariant 5 — dispatch_loop Is the Sole Scheduler-Registered Send Path

No other function may be registered in the APScheduler that calls Resend, claims queue rows, or sets `sent_at` on any draft. The `send_approved` function exists but must not be added back to the scheduler without a formal race analysis.

**Why:** Two paths on the same schedule create a race condition where both paths can compete to dispatch the same draft. The transactional claim semantics of `dispatch_loop` cannot prevent interference from a second path that uses different claim semantics.

### Invariant 6 — Idempotency Key Format Must Be Stable

The idempotency key for every Resend call is `f"{draft_id}:{attempt_number}"`. This format must not change.

**Why:** The idempotency key is the mechanism by which Resend deduplicates sends at the provider level. If the key format changes between an initial send and a retry (because the format was modified in a code change), Resend treats the retry as a new, unrelated send. The deduplication guarantee is broken. Duplicate emails to recipients become possible.

### Invariant 7 — STALE_LOCK_MINUTES Must Not Be Reduced Below Process Completion Time

The stale lock TTL (`STALE_LOCK_MINUTES = 5`) defines the minimum time a queue row remains locked while being dispatched. A row locked at T=0 cannot be reclaimed until T=5.

**Why:** If the TTL is reduced to, say, 1 minute, and a dispatch attempt takes longer than 1 minute (due to a slow Resend API response or a slow DB write), the stale lock reclaim will fire mid-dispatch, releasing the lock. Another dispatcher can then claim the same row, creating a concurrent dispatch of the same draft. At `batch_size=1` and typical Resend latency (< 500ms), this is extremely unlikely — but reducing the TTL is not safe to do without analyzing worst-case dispatch latency.

### Invariant 8 — `send_attempts.status` CHECK Constraint Values Are Fixed

The `send_attempts.status` column has a CHECK constraint: `('DISPATCHED', 'DELIVERED', 'FAILED', 'PERMANENTLY_FAILED')`. These are the only valid statuses.

`ALREADY_DELIVERED` is a Python-level outcome status in `QueueDispatchOutcome.status` — it is never written to `send_attempts`. On an ALREADY_DELIVERED outcome, the DB sees either DELIVERED (Scenario C) or FAILED (Scenario E). This distinction matters: `ALREADY_DELIVERED` in the DB would mean the CHECK constraint fails and the entire dispatch transaction rolls back.

Do not add `ALREADY_DELIVERED` or any other status to `send_attempts.status` without a migration that updates the CHECK constraint and a full analysis of what code paths write to this column.

---

## Part X — Operational Anti-Patterns

These are the failure modes discovered during the Phase 0–Stage C transition. Each one was either directly observed in the original architecture or identified as a latent risk through formal analysis. Future contributors should recognize these patterns and avoid them.

### Anti-Pattern 1 — Post-Send Claim

**Pattern:** Writing `sent_at` or any "this was sent" marker to the DB after calling the send API.

**Why it's wrong:** Creates a crash window between "Resend accepted the call" and "DB confirmed the send." Any crash in this window produces an unrecorded send that will be retried.

**Correct approach:** Set the pre-send claim before calling Resend. The pre-send claim is not a record of a successful send — it is an exclusive claim on the right to attempt the send.

---

### Anti-Pattern 2 — Single-Path Assumption

**Pattern:** Designing the dispatch system to assume that only one path ever dispatches a given draft.

**Why it's wrong:** Systems evolve. A function added "temporarily" for debugging gets registered in the scheduler. A new feature introduces a second dispatch trigger. The system no longer has the single-path assumption it was designed for.

**Correct approach:** Design for concurrency. The pre-send atomic claim (`WHERE sent_at IS NULL`), the queue's `FOR UPDATE SKIP LOCKED`, and the idempotency key all work correctly whether there is one dispatch path or ten. The system is safe under concurrent access by design, not by assumption.

---

### Anti-Pattern 3 — Fetch-Based State Checks as Locks

**Pattern:** Fetching a draft, checking a field (e.g., `sent_at IS NULL`), and treating the result as a lock on the right to dispatch.

**Why it's wrong:** The check and the subsequent action are not atomic. Between the fetch and the dispatch, another process can modify the field. By the time the dispatch happens, the state the decision was based on is stale.

**Correct approach:** Use an atomic conditional update: `UPDATE ... WHERE field = expected_value`. The update succeeds only if the condition holds at the moment of the update, not at the moment of the preceding read.

---

### Anti-Pattern 4 — Silent Failure Acceptance

**Pattern:** Catching exceptions from send operations, logging a warning, and continuing as if the send completed.

**Why it's wrong:** A silent failure that looks like a success leaves the queue row in an indeterminate state. The row may be deleted as if the send succeeded (orphan), left locked (stuck), or retried without proper state cleanup.

**Correct approach:** Every exception from a send operation must produce a specific, classified outcome (TRANSIENT_FAILED or PERMANENTLY_FAILED) with a corresponding state transition in both `send_attempts` and `outbound_queue`. No exception is silent.

---

### Anti-Pattern 5 — Scheduler Redesign Under Operational Load

**Pattern:** Modifying the scheduler registration, cron schedule, or trigger mechanism while the system is in active use (SEND_ENABLED=true, cohort in queue).

**Why it's wrong:** A scheduler modification can cause ticks to fire at unexpected times, miss ticks, or fire multiple times in rapid succession. Under active sends, any of these outcomes can produce duplicate sends, missed cohort drafts, or lock contention.

**Correct approach:** All scheduler changes require SEND_ENABLED=false during the change, followed by a verification window (at minimum one full observation window) before re-enabling sends.

---

### Anti-Pattern 6 — Optimistic Batch Size Increases

**Pattern:** Increasing `batch_size` incrementally without corresponding observability and without evidence from the previous batch size.

**Why it's wrong:** `batch_size=N` means up to N drafts are dispatched per tick. At `batch_size=1`, anomaly analysis is simple — one claim per tick, one send_attempts row per tick, one queue row deleted per tick. At `batch_size=10`, the same anomaly is 10x harder to trace. The operational complexity of anomaly investigation scales with batch size.

**Correct approach:** Increase batch_size only when there is concrete evidence from operations at the current batch_size that the system handles all outcomes correctly and the operator can diagnose anomalies at the current complexity level. `batch_size=1` is not a limitation — it is the correct setting for the current scale.

---

## Part XI — No-Go Conditions

These are conditions under which sends must not proceed. If any of these is true, SEND_ENABLED must remain (or be set) to false.

| Condition | Reason |
|-----------|--------|
| `outbound_queue` contains rows with `locked_by IS NOT NULL` before a send window | A prior dispatch did not complete cleanly. Investigate before sending. |
| `send_attempts` contains rows with `status = 'DISPATCHED'` and `created_at` > 10 minutes ago | A dispatch started but did not resolve. Investigate before sending. |
| Any cohort draft has `sent_at IS NOT NULL` and `resend_message_id IS NULL` | Pre-send claim is set but no send was recorded. Could be a lost send. Investigate. |
| `batch_size` > 1 at Stage 1–2 | Multiple sends per tick cannot be controlled with single-operator observation. |
| `RESEND_WEBHOOK_SECRET` not set in Railway | Webhook reconciliation is unauthenticated. Any caller can inject fake delivery events. |
| D8 or D9 not confirmed | Pre-activation verification incomplete. |
| Observation window not completed | The runtime model has not been verified for the current cohort state. |
| Any anomaly from the preceding observation window is unresolved | An unexplained anomaly may indicate a hidden activation path or a runtime coupling that was not accounted for. |

---

## Part XII — Principles for Future Contributors

If you are making a change to the dispatch system, read these before writing a line of code.

**1. Correctness before performance.** Every optimization to the dispatch path (faster claiming, larger batches, parallel dispatch) makes the system harder to reason about under failure. The current dispatch path is deliberately simple. Do not optimize it unless you have concrete evidence that its performance is limiting commercial outcomes.

**2. The invariant sequence is a unit.** The 7-step dispatch sequence (claim → insert DISPATCHED → pre-send claim → Resend call → write resend_message_id → update DELIVERED → delete queue row) is designed as a whole. Changing the order of any step requires re-analyzing all crash scenarios. Do not move steps without doing that analysis.

**3. Add observability before adding complexity.** If you are adding a new code path, add a log line and a DB state you can inspect before deploying. Never deploy a change to the dispatch path without being able to verify its correct execution through logs or DB state.

**4. Staging first, always.** Every behavioral change to the dispatch path must be deployed to staging and validated with SEND_ENABLED=true in staging before it touches production. This is true even for "trivial" changes. The dispatch path has no trivial changes.

**5. SEND_ENABLED=false is the correct default.** If you are ever uncertain about whether a change is safe to deploy to production while sends are active, set SEND_ENABLED=false, deploy, verify, then re-enable. The cost of a missed send window is a recoverable inconvenience. The cost of a duplicate send is a credibility loss that cannot be undone.

**6. The audit trail is not optional.** `send_attempts` is the forensic record of every dispatch attempt. Do not add "optimization" paths that bypass it. Do not add bulk operations that write to `outreach_drafts.sent_at` without a corresponding `send_attempts` row. If the operation does not leave a complete audit trail, it should not happen in the send path.

**7. Document the why, not just the what.** If you are making a change that is not obviously correct from the code, write a comment or a doc update explaining why. The next contributor who reads your change will not have the context of the conversation in which the decision was made. Preserve that context.

**8. Operational confidence must precede scale increases.** Before increasing `batch_size`, `daily_limit`, or cohort size, ask: "do I have evidence from operations at the current scale that the system handles all outcomes correctly?" If the answer is "not yet," do not increase. Evidence from successful operations is not the same as the absence of observed failures.

**9. Respect the activation stage gates.** Each activation stage exists because it produces a proof that the previous stage could not. Skipping a stage is not a time-saver — it is trading a controlled observation for an uncontrolled surprise.

**10. The system is now in operational mode, not construction mode.** Architectural expansion is frozen unless it directly supports operational reliability, correctness, or customer deployment readiness. New features wait behind operational proof. This is not a temporary constraint — it is a strategic choice about where value is created.

---

## Part XIII — Governance Assumptions

These are the assumptions about how decisions are made for the ProspectIQ dispatch system. They must be preserved as the team grows.

**Authorization model:** All activation decisions (SEND_ENABLED flip, cohort enqueue, daily_limit increase, batch_size increase) require explicit verbal authorization from Avanish in the current session. Autonomous activation, autonomous limit increases, and autonomous cohort expansion are not permitted.

**Evidence before advancement:** Every stage transition requires a documented evidence package. No stage transition occurs on the basis of "it seemed fine" or "I watched the logs."

**No production data mutation without explicit approval:** Any SQL that modifies `outbound_queue`, `outreach_send_config`, `outreach_drafts.sent_at`, or `outreach_drafts.resend_message_id` in production requires explicit operator authorization. These fields are the operational state of the dispatch system — they are not configuration values.

**Code changes during activation require freeze + verify:** Any PR merged while a send cohort is in queue requires SEND_ENABLED=false before the deploy, followed by a verification window before re-enabling.

**Rollback must always be possible.** Every activation step must have a documented rollback procedure that can be executed in under 5 minutes by a single operator with Railway and Supabase dashboard access. If a proposed change cannot be rolled back in this timeframe, it requires additional design work before implementation.

---

## Summary: What Must Not Be Lost

The following is the irreducible core of this doctrine. If you read nothing else, read this:

1. **Duplicate sends are not a performance issue — they are a trust-destruction event.** The entire architecture exists to make them structurally impossible.

2. **The pre-send DISPATCHED row and the atomic `sent_at` claim are not redundant.** They protect against different failure modes. Removing either one creates a crash window that the other cannot cover.

3. **SEND_ENABLED=false is not a temporary restriction.** It is the correct state for any deployment that has not explicitly been authorized for sends. It is the first step of every rollback procedure.

4. **Operational confidence is earned through observation, not assumed from successful deployment.** A deployed system that has never been observed across a full send window has not been validated — it has been installed.

5. **The activation stage model is not a bureaucratic overhead.** It is the mechanism by which the system proves its correctness incrementally, with the blast radius of each stage limited to what can be controlled and recovered from.

6. **Future contributors inherit both the system and the operational discipline.** The dispatch runtime works correctly because specific decisions were made, specific anti-patterns were avoided, and specific invariants were enforced. Those decisions remain load-bearing even after the people who made them have moved on.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/OPERATIONAL_DOCTRINE_001.md`  
**Classification:** Canonical operational doctrine — do not amend without full invariant review
