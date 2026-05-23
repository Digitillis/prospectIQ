# ProspectIQ VNext — Engineering Implementation Roadmap

**Version 1.0 | 2026-05-14**
**Author: Avanish Mehrotra & Digitillis Architecture Team**
**Status: Execution Reference | Derived from PROSPECTIQ_VNEXT_ARCHITECTURE.md**

---

## About This Document

This roadmap translates the canonical architecture doctrine into a sequenced engineering plan. It governs what gets built, in what order, with what gates, and with what safety conditions.

**What this document is**: a phased PR sequence with dependencies, migration requirements, test requirements, rollback plans, acceptance criteria, risks, and explicit no-go conditions.

**What this document is not**: implementation instructions, code, SQL, or migrations. Those belong in PR-level work, not here. The architecture doctrine (PROSPECTIQ_VNEXT_ARCHITECTURE.md) defines what the system should become. This roadmap defines how to get there.

**Relationship to the doctrine**: every PR in this roadmap serves the architecture. No PR may introduce architectural patterns that contradict the doctrine. If a PR requires a doctrine change, the doctrine is updated first, with written rationale, before the PR is opened.

---

## Global Constraints

These constraints apply to every PR in this roadmap. They are not phase-specific.

**G1 — SEND_ENABLED stays false until explicitly authorized.** No PR in this roadmap re-enables sends. Authorization requires Avanish's explicit instruction, per session.

**G2 — All PRs require staging validation before production.** Once staging exists (Phase 0), every migration and behavioral change is validated on staging before production. No exceptions.

**G3 — All migrations require a preflight query.** Any migration that creates a UNIQUE index, adds a NOT NULL column, or modifies a trigger must have a corresponding preflight query that verifies the data is clean before the migration runs.

**G4 — Append-only tables are never modified destructively.** The tables classified as Category A (append-only event records) in the doctrine may never have rows deleted, updated, or backfilled except under explicit data-correction procedures approved by Avanish.

**G5 — No PR may touch the send path while SEND_ENABLED is true.** The send path is a production-critical code path. Changes to it require SEND_ENABLED=false before the PR is merged.

**G6 — PR scope must be minimal and independently deployable.** No PR may bundle unrelated changes. Each PR must be independently mergeable without requiring future PRs to make the system consistent.

---

## Phase 0 — Staging Environment

**Status**: Not yet built. This is a prerequisite for all work in Phase 2 and beyond.

### What Phase 0 Establishes

ProspectIQ currently has one Supabase project and one Railway environment, both production. This is the root cause of the absence of safe validation space for migrations and behavioral changes. Phase 0 creates the engineering infrastructure that makes all subsequent phases safe to develop and deploy.

Phase 0 is not a PR against the ProspectIQ codebase. It is an infrastructure task with its own acceptance criteria.

---

### Task 0-A: Supabase Staging Project

**Scope**: Create a new Supabase project dedicated to staging. Same region (ca-central-1). Independent DB, independent API keys. No data sharing with production.

**Configuration requirements**:
- New Supabase project with all migrations applied in order (001 through current)
- Staging-specific service key, anon key, and DATABASE_URL stored as Railway staging environment variables
- `send_enabled = false` in `outreach_send_config` at setup, always
- Resend configured with a test/sandboxed sending domain (not the production domain) to prevent real emails escaping staging
- An explicit `ENVIRONMENT=staging` env var distinguishable from production

**Seed data requirements**:
- Synthetic workspace, contacts, and companies (not real prospect data)
- At least one workspace with 20+ contacts in various states: pending drafts, sent drafts, suppressed, bounced
- Contacts covering all engagement levels (NONE, WARM, HOT, SUPPRESSED) to exercise full workflow paths
- Seed data is maintained in a `scripts/seed_staging.py` script (not applied to production, ever)

**Acceptance criteria**:
- All existing migrations run cleanly on the new project without errors
- `preflight_053.sql` Block 1 returns zero rows on the staging DB
- A test connection from the Railway staging environment successfully queries the staging DB
- Sends cannot reach real email addresses (sandboxed domain enforced)

**No-go conditions**:
- Staging DB must never share connection credentials with production
- Staging `DATABASE_URL` must never appear in production Railway environment variables
- Staging must never have `SEND_ENABLED=true` without explicit session authorization

---

### Task 0-B: Railway Staging Environment

**Scope**: Create a second Railway environment (staging) within the ProspectIQ project, separate from the production environment.

**Deployment configuration**:
- Staging deploys automatically on every push to `main`
- Production deploys manually via `railway deploy` or a tagged release (not auto-deploy)
- This inverts the current behavior (currently production auto-deploys on main push)
- Staging environment uses staging Supabase credentials exclusively

**CI/CD changes**:
- Add a "staging deploy" step to the GitHub Actions CI workflow that deploys to staging and runs smoke tests
- Add a "staging migration gate" step: before any PR is merged to main, the migration (if any) must have been run and verified on staging
- The PR checklist template must include a staging validation checkbox

**Acceptance criteria**:
- Push to `main` triggers a staging deploy; production is NOT auto-deployed
- Production deploy requires explicit manual trigger
- A failing smoke test on staging blocks the merge queue

---

### Task 0-C: Migration Pipeline Hardening

**Scope**: Establish the migration deployment process that all future PRs follow.

**Process definition**:
1. Preflight query runs against staging DB — must return zero qualifying rows
2. Migration runs on staging
3. Post-migration verification queries run on staging
4. Rollback-wrapped smoke tests run on staging
5. If all pass: PR is eligible for merge to main
6. Post-merge: migration runs on production using the same preflight + verification + smoke test sequence
7. If production preflight fails: migration does not run; emergency review required

**Tooling**:
- A `scripts/run_migration.sh` wrapper that enforces the preflight → migrate → verify sequence
- Accepts `--env staging|production` flag
- Refuses to run on production if the most recent staging run was not within 24 hours

**Acceptance criteria**:
- Running `run_migration.sh --env staging` for migration 053 completes without error
- Running `run_migration.sh --env production --skip-staging-check` is rejected (flag does not exist)
- CI workflow calls `run_migration.sh --env staging` before deploying to staging

---

## Phase 2 — Durable Execution

**Doctrine reference**: Part VI (Durable Execution Model), Part VIII (Operational Model — dead-letter handling)

**Phase goal**: Every authorized send is durably tracked, idempotent, and recoverable from process crash. The system can answer "what is the current delivery status of every send?" from DB records alone.

**Phase prerequisite**: Phase 0 complete (staging environment exists and is operational).

**Phase 2 does NOT**:
- Enable autonomous sending (SEND_ENABLED stays false)
- Change the approval UX
- Introduce workflow state machines
- Wire context packets into the generation path

---

### PR F — Outbound Queue and Transactional Outbox

**Scope**: Introduce `outbound_queue` and `send_attempts` tables. Modify the approval path so that a draft approval atomically enqueues the send in the same transaction. No dispatch logic yet — only the outbox insertion.

**Depends on**: Phase 0 complete. All Phase 1 PRs merged (A through E and D).

**What changes**:
- New `outbound_queue` table: columns for draft_id, workspace_id, enqueued_at, priority, retry_count, locked_by, locked_at, next_retry_at
- New `send_attempts` table: columns for draft_id, attempt_number, idempotency_key, status (DISPATCHED / DELIVERED / FAILED / PERMANENTLY_FAILED), dispatched_at, resolved_at, provider_message_id, provider_response_body, failure_code, failure_reason, reconciled_at
- Approval endpoint (`PATCH /{thread_id}/draft/{draft_id}/approve` or equivalent): wraps the existing approval DB write + outbound_queue INSERT in a single transaction
- If the transaction rolls back for any reason, neither the approval event nor the queue row exists — atomicity guaranteed
- `send_attempts` is not written yet in this PR — that belongs to PR G (dispatch)

**Staging requirements**:
- Migration runs on staging first
- Smoke test: approve a test draft via the API; verify `outbound_queue` row exists; verify `outreach_drafts.approval_status` = `approved`; verify both are consistent
- Failure test: simulate a DB error during the outbox INSERT (via forced constraint violation); verify the draft remains in `pending` status and no queue row exists

**Migration requirements**:
- Two new tables: `outbound_queue`, `send_attempts`
- Indexes required on `outbound_queue`: `(locked_at, locked_by)` for scheduler pickup; `(next_retry_at)` for retry scheduling; `(draft_id)` for uniqueness check
- Indexes required on `send_attempts`: `(draft_id)` for reconciliation; `(status, dispatched_at)` for stale-dispatch queries; unique on `(draft_id, attempt_number)`
- No changes to `outreach_drafts` in this PR (context_packet_id FK comes later in PR N)
- Preflight: verify no orphaned `approval_status = approved` drafts with no corresponding queue row (expected: all existing approved drafts predate this PR; the preflight is a baseline count)

**Tests required**:
- Atomic outbox insertion: approving a draft writes both `approval_status=approved` and a queue row in the same transaction
- Atomic rollback: if the queue INSERT fails, the approval write is rolled back; draft remains pending
- Queue row contains correct draft_id, workspace_id, priority, and enqueued_at
- Idempotency: approving a draft that is already approved does not create a duplicate queue row (must be guarded)
- Rejecting a draft does not create a queue row

**Rollback plan**:
- Drop `outbound_queue` and `send_attempts` tables (no rows yet in send_attempts at this stage)
- Revert approval endpoint to previous behavior (approval without outbox insert)
- SEND_ENABLED is false; no sends are affected by rollback
- `outreach_drafts.approval_status` values already set to `approved` before the rollback remain approved — this is acceptable; they are not in the queue but can be manually re-queued after rollback is resolved

**Acceptance criteria**:
- Every draft approval via API produces exactly one `outbound_queue` row, atomically
- Every draft rejection via API produces zero `outbound_queue` rows
- A simulated DB failure during queue insertion leaves the draft in `pending` status
- Existing approved drafts (pre-PR F) are not automatically backfilled into the queue (they predate the outbox; they will be handled by a manual migration or left as legacy)
- All existing PR D tests continue to pass (the immutability trigger must not be affected)

**Risks**:
- PgBouncer transaction mode: the approval endpoint must issue `outreach_drafts UPDATE` and `outbound_queue INSERT` within a single transaction context. If the endpoint previously used two separate Supabase client calls, they must be consolidated into a single explicit transaction block.
- If a draft was approved before PR F merged, it has no queue row. These drafts are in a liminal state. A one-time manual operation (not a migration backfill) must address them before enabling dispatch.

**No-go conditions**:
- SEND_ENABLED=true in production at time of merge
- Staging smoke test showing non-atomic behavior (draft approved but no queue row, or queue row with no approval event)
- Any existing test suite failure not introduced by this PR

---

### PR G — Dispatch Mechanics, Retry Model, and Dead-Letter Queue

**Scope**: Implement the scheduler job that picks up `outbound_queue` rows and dispatches them via Resend. Introduce the retry model. Introduce dead-letter queue for exhausted attempts.

**Depends on**: PR F merged and validated on staging.

**What changes**:
- New scheduler job: `dispatch_queue_job` — runs every N seconds (configurable), picks up eligible `outbound_queue` rows using `SELECT FOR UPDATE SKIP LOCKED`
- Dispatch flow per row: acquire row lock → create `send_attempts` record (status=DISPATCHED) → call Resend API → on success: update send_attempt (status=DELIVERED, provider_message_id), set `outreach_drafts.sent_at`, delete queue row → on failure: handle per failure type
- Transient failure handling (5xx, timeout, rate limit): increment `retry_count`, set `next_retry_at` = now + backoff(retry_count), release lock (set `locked_by=NULL`), do NOT delete queue row; the attempt record is created but marked FAILED with failure details
- Permanent failure handling (4xx except 429): create `send_attempts` record (status=PERMANENTLY_FAILED), create `dead_letter_queue` record, delete queue row
- Retry exhaustion (retry_count >= max_retries): same as permanent failure path
- New table: `dead_letter_queue` — columns for draft_id, send_attempt_id, workspace_id, reason, reason_detail, created_at, resolved_at, resolved_by, resolution_notes
- Backoff schedule: attempt 1 → immediate; attempt 2 → 5 minutes; attempt 3 → 30 minutes; beyond → dead-letter

**Staging requirements**:
- SEND_ENABLED must be set to true in staging ONLY for this PR's validation (not production)
- Staging must use a sandboxed Resend domain so no real emails are sent
- End-to-end test: approve a test draft on staging → scheduler picks it up → Resend test call succeeds → `sent_at` is set → queue row is gone → `send_attempts` record is DELIVERED
- Simulated failure test: mock the Resend call to return 500 → verify retry_count increments and queue row remains with updated `next_retry_at`
- Simulated permanent failure: mock Resend to return 422 → verify dead-letter record created, queue row deleted
- Concurrent pickup test: verify two parallel scheduler ticks do not double-dispatch the same queue row

**Migration requirements**:
- New table: `dead_letter_queue` with the columns described above
- Index on `dead_letter_queue(created_at)` for operational alerting
- Index on `dead_letter_queue(draft_id)` for lookups
- No changes to `outbound_queue` or `send_attempts` schema (defined in PR F)

**Tests required**:
- Happy path: queue row dispatched → send_attempt DELIVERED → queue row deleted → draft sent_at set
- Transient failure: retry_count increments, next_retry_at set correctly for each attempt number, queue row remains
- Max retries exhausted: dead-letter record created, queue row deleted, send_attempt PERMANENTLY_FAILED
- Permanent failure (non-retriable): dead-letter immediately, no retry
- Concurrent dispatch safety: two workers picking simultaneously; only one processes each row (SKIP LOCKED behavior validated)
- Idempotency: if dispatch job runs twice due to a bug, the second run finds no eligible rows (already locked or already processed)
- `sent_at` immutability: the dispatch job must not be able to re-set `sent_at` on an already-sent draft (the trigger from PR D enforces this; verify it fires correctly in this flow)

**Rollback plan**:
- Disable `dispatch_queue_job` in scheduler configuration (feature flag: `DISPATCH_ENABLED=false` env var)
- `outbound_queue` rows remain and are safe (they are just pending work items)
- `send_attempts` records are append-only; they remain as historical records
- `dead_letter_queue` records remain as informational records
- If a send was dispatched and confirmed (sent_at set, queue row deleted), that send cannot be undone — rollback only stops future dispatch
- SEND_ENABLED=false in production makes this rollback zero-risk from a sending perspective

**Acceptance criteria**:
- End-to-end staging test: approve → schedule tick → dispatched → DELIVERED, with all DB records consistent at every step
- Every Resend API call has a corresponding `send_attempts` record created before the call
- No `send_attempts` record exists without a corresponding dispatch attempt
- The `sent_at` immutability trigger (PR D) fires correctly during the dispatch path
- Dead-letter records are created for all exhausted and permanently-failed attempts
- No queue row remains after successful dispatch

**Risks**:
- The backoff implementation must not rely on `time.sleep()` inside the scheduler job. The `next_retry_at` column is the correct mechanism — the scheduler simply skips rows where `next_retry_at > now`.
- The `SELECT FOR UPDATE SKIP LOCKED` query must run within a transaction that is committed or rolled back before the connection is returned to PgBouncer. Do not hold this transaction across the Resend HTTP call.
- If the Resend call succeeds but the subsequent DB transaction (update send_attempt + delete queue row) fails, the draft has been sent but the DB does not know it. The reconciliation job (PR H) is the recovery mechanism for this scenario.

**No-go conditions**:
- PR F not merged and validated
- SEND_ENABLED=true in production
- Staging sandboxed domain not confirmed (risk of real email delivery during validation)
- Concurrent dispatch test not passing (double-send risk)
- Any scenario where a draft can be dispatched without a `send_attempts` record preceding the Resend call

---

### PR H — Reconciliation Job and Provider Event Linkage

**Scope**: Introduce the reconciliation scheduled job. Link incoming provider webhook events to their corresponding `send_attempts` records. Establish the three-mechanism delivery confirmation model from the doctrine.

**Depends on**: PR G merged and validated on staging.

**What changes**:
- New scheduler job: `reconciliation_job` — runs every 15 minutes (configurable); queries for `send_attempts` with status=DISPATCHED and `dispatched_at` older than a configurable timeout (default: 10 minutes); for each such record, queries the Resend API for current delivery status using the `idempotency_key` or `provider_message_id`; updates `send_attempt.status` and `reconciled_at` accordingly
- Provider event linkage: when a `provider_events` record is created (from the webhook handler), attempt to link it to a `send_attempts` record via `resend_message_id` (from the `provider_events` payload). Write the `send_attempt_id` foreign key on the provider event record if a match is found. If no match (webhook arrived before provider_message_id was stored), a periodic linkage job reconciles unlinked events.
- Reconciliation report: daily scheduled job generates a summary row in an `operational_reports` table (or logs to a structured location) covering: total DISPATCHED-then-reconciled, total DELIVERED, total BOUNCED, total PERMANENTLY_FAILED, total in dead-letter, oldest unresolved item
- New column on `provider_events`: `send_attempt_id UUID REFERENCES send_attempts(id) ON DELETE SET NULL` — nullable, populated on match

**Staging requirements**:
- Test scenario: dispatch a draft on staging; before the webhook arrives, query for DISPATCHED records; run the reconciliation job; verify it queries the Resend API and updates the send_attempt status correctly
- Test scenario: deliver a webhook that arrives before `provider_message_id` is stored; verify the linkage job eventually links it

**Migration requirements**:
- New column on `provider_events`: `send_attempt_id` with FK to `send_attempts`
- New index on `provider_events(send_attempt_id)` for linkage queries
- New table (optional at this phase): `operational_reports` for daily summary records, or defer this to Phase 5 operator cockpit

**Tests required**:
- Reconciliation job finds DISPATCHED records older than threshold
- Reconciliation correctly handles Resend API returning: delivered, bounced, not found (still in transit — leave as DISPATCHED)
- Reconciliation is idempotent: running it twice on the same stale record produces the same final state
- Provider event linkage: a webhook with a matching `resend_message_id` links to the correct `send_attempts` record
- A webhook received before `provider_message_id` is stored is eventually linked by the linkage reconciliation pass
- Receiving the same webhook twice: second processing is a no-op (idempotency already enforced by PR B's dedup; verify it still holds after the linkage column is added)

**Rollback plan**:
- Disable `reconciliation_job` in scheduler configuration
- The `send_attempt_id` column on `provider_events` is nullable; removing the column is a non-breaking migration if needed
- No behavioral changes to the send path; rollback affects only the corrective mechanism

**Acceptance criteria**:
- A `send_attempts` record left in DISPATCHED for more than the threshold is discovered and resolved by the reconciliation job without manual intervention
- Every incoming provider event that matches a send attempt has its `send_attempt_id` populated
- Running the reconciliation job 10 times in a row produces no duplicate DB writes
- The daily summary captures accurate counts for all delivery outcome categories

**Risks**:
- Resend's API for querying delivery status by idempotency key or message ID must be confirmed as available and stable. If the API is not available for status queries, the reconciliation mechanism must fall back to webhook-only confirmation, and the stale DISPATCHED window grows.
- The reconciliation job makes external API calls. It must have a timeout and must not block the scheduler loop if Resend is slow.

**No-go conditions**:
- PR G not merged
- Reconciliation job produces duplicate DB writes in staging tests
- No confirmed Resend API endpoint for delivery status queries (document the fallback before merging)

---

## Phase 3 — Orchestration Runtime

**Doctrine reference**: Part IV (Orchestration Model), Part VII (Governance Architecture), Part VIII (Operational Model — scheduler philosophy)

**Phase goal**: The system advances workflows autonomously. The scheduler evaluates gate conditions, requests drafts, and manages the approval lifecycle. Humans review and approve at defined HITL checkpoints. Sends are authorized by policy, not by manual queue processing.

**Phase prerequisite**: Phase 2 complete (all three PRs merged and validated on staging and production).

**Phase 3 does NOT**:
- Wire context packets into the generation path (Phase 4)
- Enable sends in production without explicit authorization
- Build the operator cockpit UI (Phase 5)

---

### PR I — Scheduler Decomposition and Singleton Lock

**Scope**: Decompose the current monolithic scheduler into three distinct job categories. Introduce the DB-row-based singleton lock. This PR does not change what the jobs do — it changes how they are organized, registered, and protected against concurrent execution.

**Depends on**: PR H merged. This PR is the foundation for all subsequent Phase 3 orchestration work.

**What changes**:
- New table: `scheduler_lock` — columns: lock_name (VARCHAR, primary key), locked_by (instance identifier), locked_at (timestamptz), heartbeat_at (timestamptz), lock_expires_at (timestamptz)
- Scheduler startup: attempt to acquire the `main_scheduler` lock row. If the row does not exist, INSERT it. If it exists but `heartbeat_at + tolerance_window < now`, the lock is stale — UPDATE it to claim ownership. If it exists and is fresh, the current instance does not run the scheduler.
- Heartbeat: the lock-holding instance updates `heartbeat_at` every 30 seconds. If the instance dies, the heartbeat stops, and the next instance can claim the lock after the tolerance window (default: 90 seconds).
- Three job registries — advancement jobs (high frequency: every 60 seconds), reconciliation jobs (medium frequency: every 15 minutes), housekeeping jobs (low frequency: once daily). Each job type is registered separately. Each job is independently configurable for frequency.
- Current scheduler jobs are categorized and moved into the appropriate registry. No behavioral changes to any job — only organizational refactoring.

**Why this PR is its own step**: The singleton lock is a prerequisite for all Phase 3 orchestration work. Without it, deploying a new version of the app while the old is still running could result in two schedulers simultaneously advancing workflows. That is a correctness risk.

**Staging requirements**:
- Simulate two instances of the backend starting simultaneously on staging; verify only one holds the scheduler lock at a time
- Simulate lock holder dying (kill the process); verify the second instance acquires the lock within the tolerance window
- Verify heartbeat updates appear in the `scheduler_lock` table at the expected interval

**Migration requirements**:
- New table: `scheduler_lock` (one row per named lock; initially only `main_scheduler` will exist)
- No changes to existing tables

**Tests required**:
- Single instance: acquires lock on startup, updates heartbeat, holds lock
- Two instances: second instance does not acquire lock while first is alive and updating heartbeat
- Stale lock takeover: if heartbeat_at is beyond tolerance, second instance claims lock
- Lock release on graceful shutdown: lock row is updated to indicate released state (or deleted)
- Each job type (advancement, reconciliation, housekeeping) is invocable independently in tests without the full scheduler running

**Rollback plan**:
- Drop `scheduler_lock` table
- Revert scheduler initialization to previous (no-lock) behavior
- Multiple-instance risk during rollback window is low (Railway runs one instance at a time currently)

**Acceptance criteria**:
- With two processes running simultaneously on staging, exactly one holds the lock at all times
- Heartbeat is updated within 30 seconds on every tick observed
- Stale lock is claimed within 2x the tolerance window after the holder dies
- All existing scheduler jobs run correctly under the new three-category organization

**Risks**:
- Session-level advisory locks (`pg_try_advisory_lock`) are NOT used — this was confirmed as incompatible with PgBouncer transaction mode. The heartbeat row is the correct mechanism. Do not introduce advisory locks.
- The tolerance window must be longer than the worst-case scheduler tick duration. If a heavy housekeeping job causes a 45-second tick, a 30-second tolerance window causes false stale-lock detection.

**No-go conditions**:
- Any use of `pg_try_advisory_lock` or session-level locks
- Two instances shown to concurrently hold the scheduler lock in staging tests
- Any existing scheduler job broken by the reorganization

---

### PR J — Workflow State Machine and Sequence Progress

**Scope**: Introduce the `sequence_progress` table as the explicit workflow state per (workspace, contact, sequence). Implement the advancement logic that moves contacts through sequence steps. The scheduler's advancement job evaluates gate conditions and advances eligible workflows.

**Depends on**: PR I merged.

**What changes**:
- New table: `sequence_progress` — columns: id (UUID), workspace_id, contact_id, sequence_name, current_step (int), status (ACTIVE / PAUSED / COMPLETED / FAILED / ABANDONED), paused_reason (text), gate_blocked_until (timestamptz), created_at, updated_at
- Index: unique on `(workspace_id, contact_id, sequence_name)` — one progress row per contact per sequence
- Advancement logic: the advancement scheduler job queries for `sequence_progress` rows where status=ACTIVE, then evaluates whether the current_step's gate conditions are satisfied; if satisfied, advances `current_step` by 1 and requests draft generation for the next step (currently: creates a draft in `pending` state); if not satisfied, sets `gate_blocked_until` to the earliest time the gate might open
- Gate conditions evaluated per step: suppression check (reads `suppression_rules`), send window check (reads workspace config), contact frequency check (counts recent sends in `outreach_drafts`), approval status check (is the current step's draft approved and sent?)
- Advancement does NOT evaluate company traction gate yet — that is PR M
- New `workflow_events` event types: `SEQUENCE_STARTED`, `SEQUENCE_STEP_ADVANCED`, `SEQUENCE_PAUSED`, `SEQUENCE_COMPLETED`, `SEQUENCE_ABANDONED` — written on each state transition
- Existing `outreach_drafts` receive a `sequence_progress_id` FK column (nullable) for newly-generated drafts; existing drafts without a `sequence_progress_id` are legacy

**Staging requirements**:
- Seed staging with a contact that is not suppressed and has no recent sends
- Start the contact on a sequence (insert a `sequence_progress` row with status=ACTIVE, current_step=1)
- Trigger the advancement job; verify a draft is created in `pending` status for step 1
- Approve the draft (simulated); verify the advancement job recognizes step 1 as complete and advances to step 2
- Simulate a suppression; verify the advancement job sets gate_blocked_until and does not advance

**Migration requirements**:
- New table: `sequence_progress`
- New column on `outreach_drafts`: `sequence_progress_id UUID REFERENCES sequence_progress(id) ON DELETE SET NULL` (nullable)
- New `workflow_events` event type enum values (additive to existing enum)
- Preflight: none required (new tables; additive column is nullable)

**Tests required**:
- Advancement job advances an eligible ACTIVE sequence to the next step
- Advancement job does not advance a sequence that is suppressed
- Advancement job does not advance a sequence that is within the send window gate
- Advancement job does not advance a sequence where the current step's draft has not been sent yet
- State transitions write the correct `workflow_events` records
- Completing the final step of a sequence sets status=COMPLETED
- A suppressed contact does not advance; gate_blocked_until is set to suppression expiry
- The unique index on `(workspace_id, contact_id, sequence_name)` prevents duplicate progress rows

**Rollback plan**:
- Disable advancement job in scheduler configuration
- Drop `sequence_progress` table and remove `sequence_progress_id` column from `outreach_drafts`
- Existing `workflow_events` records with new event types are harmless if the table remains
- The outbox (PR F) and dispatch (PR G) are unaffected; any drafts that were generated and approved before rollback remain in the queue

**Acceptance criteria**:
- A contact can be enrolled in a sequence and advance through all steps via scheduler ticks without manual database manipulation
- Every state transition produces a `workflow_events` record
- A suppressed contact's sequence is paused, not abandoned
- The advancement job is idempotent: running it twice in a row on the same state produces no duplicate actions

**Risks**:
- Enrolling existing contacts (pre-PR J) into `sequence_progress` requires a data migration or manual backfill. The decision of whether to enroll legacy contacts in the new workflow model must be made before this PR ships. Legacy contacts not enrolled remain on the old manual path.
- The draft generation request (creating a `pending` draft) must not happen until the gate conditions for that step are satisfied. If draft generation happens optimistically and the draft sits pending for weeks, the context becomes stale.

**No-go conditions**:
- PR I not merged
- Advancement job shown to produce duplicate drafts for the same sequence step in staging tests
- Any non-idempotent behavior in the advancement job

---

### PR K — Policy Evaluation Chain and Governance Decisions

**Scope**: Implement the formal policy evaluation chain producing recorded governance dispositions. Every potential send action — whether triggered by the scheduler or by manual approval — passes through this chain and produces a `governance_decisions` record.

**Depends on**: PR J merged.

**What changes**:
- New table: `governance_decisions` — columns: id (UUID), workspace_id, contact_id, draft_id (nullable — pre-draft evaluations may not have a draft yet), action (text: `ADVANCE_SEQUENCE`, `APPROVE_DRAFT`, `DISPATCH_SEND`), disposition (enum: `ALLOW_AUTONOMOUS` / `REQUIRE_APPROVAL` / `BLOCK_TEMPORARY` / `BLOCK_PERMANENT`), policy_snapshot_id (FK to `policy_snapshots`), evaluated_at, reason (text), retry_after (timestamptz — for BLOCK_TEMPORARY)
- Five evaluators (each a pure, independently testable function): `suppression_evaluator`, `traction_gate_evaluator` (placeholder — fully wired in PR M), `send_window_evaluator`, `frequency_guard_evaluator`, `approval_requirement_evaluator`
- The chain: run evaluators in doctrine-defined order; first blocking disposition short-circuits; if all pass, return the highest-priority disposition (ALLOW_AUTONOMOUS or REQUIRE_APPROVAL)
- Write `governance_decisions` record for every evaluation, including passing ones
- The advancement job (PR J) now calls the policy chain before advancing a sequence step; if the disposition is BLOCK_TEMPORARY, set `gate_blocked_until` and do not advance; if BLOCK_PERMANENT, set status=PAUSED with reason
- The approval endpoint calls the policy chain before accepting an approval; if the disposition has changed to BLOCK since the draft was generated, the approval is rejected with a 409
- `policy_snapshots` table: must contain the workspace's current policy configuration at evaluation time. A policy snapshot is written each time workspace policy changes, and the most recent one is used for each evaluation. If no snapshot exists, a default snapshot is created from workspace config.

**Staging requirements**:
- Configure a staging workspace with a send window (e.g., 9am–5pm CST) and a frequency limit (1 send per contact per 7 days)
- Test BLOCK_TEMPORARY: trigger an evaluation outside the send window; verify BLOCK_TEMPORARY disposition is recorded; verify gate_blocked_until is set correctly
- Test ALLOW: trigger an evaluation during the send window for an eligible contact; verify ALLOW_AUTONOMOUS disposition is recorded
- Test REQUIRE_APPROVAL: configure the workspace to require approval for all drafts; verify REQUIRE_APPROVAL disposition; verify that the draft is not enqueued until a human approves

**Migration requirements**:
- New table: `governance_decisions`
- Index on `governance_decisions(workspace_id, evaluated_at)` for dashboard queries
- Index on `governance_decisions(draft_id)` for draft-level audit queries
- If `policy_snapshots` does not yet have a content column with the full policy JSON, add one (must verify against migration 052 definition)
- Preflight: none required (new table)

**Tests required**:
- Each evaluator tested independently with mocked policy and state inputs
- Full chain tested with mock evaluators: short-circuit on first block is verified
- BLOCK_TEMPORARY: correct reason and retry_after in the record
- BLOCK_PERMANENT: reason recorded, no retry_after
- ALLOW_AUTONOMOUS: no reason field, no retry_after
- REQUIRE_APPROVAL: correct disposition, draft not enqueued
- Policy snapshot is linked correctly: the snapshot ID on the decision record matches the snapshot used at evaluation time
- A policy change (new snapshot created) after an evaluation does not alter the historical decision record

**Rollback plan**:
- Remove the policy chain call from the advancement job and approval endpoint (revert to previous behavior: no governance_decisions written)
- Drop `governance_decisions` table
- Existing behavior is restored; the system reverts to unevaluated approvals
- This is a significant regression from a governance standpoint, but it is safe from a data-loss standpoint

**Acceptance criteria**:
- Every advancement job tick that considers advancing a workflow produces a `governance_decisions` record, whether the result is ALLOW, BLOCK, or REQUIRE_APPROVAL
- Every draft approval attempt produces a `governance_decisions` record reflecting the policy at the time of the approval attempt
- A governance decision's policy_snapshot_id is always a valid reference to the policy snapshot active at evaluation time
- The chain short-circuits correctly: a BLOCK_PERMANENT does not trigger subsequent evaluators
- The REQUIRE_APPROVAL disposition causes a draft to await a human approval event before being enqueued

**Risks**:
- This PR changes the approval endpoint behavior. Previously, any approval was accepted. Now, a policy evaluation may reject an approval attempt with a 409 (e.g., if the contact was suppressed between draft generation and the approval attempt). This is a behavior change visible to API callers. The API contract change must be documented.
- The `policy_snapshots` table was introduced in migration 052. Verify that its schema supports the governance_decisions FK and the full policy JSON content required by the evaluators.

**No-go conditions**:
- PR J not merged
- Any evaluator that mutates state (evaluators must be pure functions — they read, they do not write)
- governance_decisions table producing duplicate rows for the same evaluation event
- Approval endpoint behavior tested on staging before production merge

---

### PR L — Approval Service Consolidation

**Scope**: Consolidate the approval, rejection, and governance gate logic into a single `ApprovalService` Python module. This PR does not change external behavior — it restructures internal code so that all approval-path logic lives in one place, with the transaction guarantee enforced at the service layer.

**Depends on**: PR K merged.

**What changes**:
- New module: `backend/app/services/approval_service.py`
- `ApprovalService.approve(draft_id, reviewer_id, attestation)`: evaluates policy chain → writes governance_decision → writes approval_event → inserts outbound_queue row → updates draft status — all in one transaction
- `ApprovalService.reject(draft_id, reviewer_id, reason_category, reason_note)`: writes rejection event → updates draft status → writes contact operational memory annotation (the annotation write is non-transactional — it is a best-effort enrichment, not a correctness requirement)
- `ApprovalService.autonomous_approve(draft_id, policy_snapshot_id)`: writes autonomous_approval event (attributed to policy, not a reviewer) → inserts outbound_queue row → updates draft status — same transaction guarantee as human approval
- The approval-related endpoints in `threads.py` are refactored to delegate to `ApprovalService`
- The advancement job (PR J) calls `ApprovalService.autonomous_approve()` when the policy disposition is ALLOW_AUTONOMOUS

**Why a separate PR**: this is a non-trivial refactor that touches the approval endpoint and the advancement job. Keeping it separate from PR K (which introduces the governance chain) allows each PR to be independently validated.

**Staging requirements**:
- Full approval flow tested on staging through the new service: approve a draft → verify outbound_queue row → verify approval_event → verify governance_decision all exist, written in the same transaction
- Full rejection flow: reject a draft → verify rejection event → verify draft status → verify contact operational memory annotation (or note if annotation write is deferred)
- Autonomous approval path: trigger the advancement job on a workflow with ALLOW_AUTONOMOUS disposition → verify autonomous_approval event written

**Migration requirements**:
- No new tables
- New `approval_events` table may be needed if it does not already exist (verify against existing schema — there may be an existing approval mechanism in `outreach_drafts` that writes to a different log)
- If an `approval_events` table does not exist: columns for id, draft_id, workspace_id, reviewer_id (nullable for autonomous), event_type (APPROVED / REJECTED / AUTONOMOUS_APPROVED), attestation (jsonb), policy_snapshot_id, reason_category, reason_note, occurred_at

**Tests required**:
- Human approval: all three DB writes (governance_decision + approval_event + outbound_queue) occur atomically
- Human approval DB failure: all three writes rolled back; draft remains pending
- Rejection: rejection event written; draft status updated; operational memory annotation attempted (failure of annotation write does not roll back the rejection)
- Autonomous approval: approval_event attributed to policy_snapshot_id (no reviewer_id); outbound_queue row created; draft status updated
- No regression on PR D immutability: attempting to approve and modify body of a sent draft is still blocked by the trigger

**Rollback plan**:
- Revert `threads.py` to inline logic
- Remove `approval_service.py` module
- The data model changes (approval_events table if new) can remain — no data loss

**Acceptance criteria**:
- All approval-path logic lives exclusively in `ApprovalService`
- No approval-related DB writes exist in `threads.py` outside of delegate calls to `ApprovalService`
- An autonomous approval event is distinguishable from a human approval event by `reviewer_id IS NULL` and a populated `policy_snapshot_id`
- Behavior on staging is identical before and after this refactor

**Risks**:
- This is a refactor PR. The risk is regression in existing approval behavior. The staging validation must reproduce every existing approval scenario.

**No-go conditions**:
- PR K not merged
- Any scenario where the approval path produces partial writes (approval_event without outbound_queue row, or vice versa) in staging tests

---

### PR M — Sibling Traction and Autonomous Approval Activation

**Scope**: Wire company traction state into the governance chain. Implement the sibling traction hold mechanic. Activate the autonomous approval path (gated by workspace policy). This PR is the final Phase 3 PR and brings the orchestration model to functional completeness.

**Depends on**: PR L merged and validated. Full end-to-end approval flow verified on staging.

**What changes**:
- New table: `company_traction_state` — columns: company_id, workspace_id, traction_level (enum: COLD / ACTIVE / WARM / HOT / CHAMPION_IDENTIFIED), hot_contact_id (nullable — the contact who triggered HOT), hot_since (timestamptz), last_updated_at, engagement_event_count
- The `traction_gate_evaluator` (introduced as a placeholder in PR K) is fully implemented: reads `company_traction_state` for the contact's company; if traction_level = HOT and workspace policy defines a traction hold, returns BLOCK_TEMPORARY with a reason indicating which contact is HOT
- Traction state update: when a `workflow_events` record is written for a HOT-level engagement (reply, meeting click), a trigger or post-event handler updates `company_traction_state` for the relevant company
- Autonomous approval activation: workspace policy can be configured to set `requires_approval = false` for specific conditions (e.g., step-1 drafts only, or all drafts during a defined campaign window); when the advancement job evaluates ALLOW_AUTONOMOUS, it calls `ApprovalService.autonomous_approve()` without waiting for a human
- The `company_traction_state` projection is rebuildable from `workflow_events` at any time

**Staging requirements**:
- Test sibling traction hold: enroll two contacts at the same company in a sequence; advance contact A to HOT (inject a workflow_event for a reply); verify contact B's advancement is blocked with a BLOCK_TEMPORARY disposition citing contact A's traction
- Test autonomous approval activation: configure the staging workspace with `requires_approval = false`; verify that a qualifying draft is autonomously approved and enqueued without human action; verify the approval event is attributed to the policy, not a reviewer

**Migration requirements**:
- New table: `company_traction_state`
- Index on `company_traction_state(company_id, workspace_id)` (unique)
- Index on `company_traction_state(traction_level)` for governance queries
- Seed `company_traction_state` from existing `workflow_events` (projection rebuild): a one-time backfill script (not a migration) computes traction state for all existing companies from historical events

**Tests required**:
- Traction gate evaluator: COLD company → ALLOW; HOT company with hold policy → BLOCK_TEMPORARY; HOT company without hold policy → ALLOW
- Traction state update: HOT workflow_event updates company_traction_state correctly
- Traction projection rebuild: drop and rebuild company_traction_state from workflow_events; result matches pre-rebuild state
- Autonomous approval: ALLOW_AUTONOMOUS disposition → autonomous_approval event written → no human review required → draft enqueued
- Autonomous approval writes the correct policy_snapshot_id on the approval event
- Sibling traction hold is cleared when the HOT contact's traction level is manually downgraded or a workspace operator resolves the hold

**Rollback plan**:
- Disable the traction gate evaluator (revert the evaluator to the placeholder that returns ALLOW)
- Drop `company_traction_state` table
- Revert autonomous approval setting in workspace config (set requires_approval=true)
- The governance chain still runs; it just no longer blocks on traction state

**Acceptance criteria**:
- A company with a HOT contact causes all other contacts' advancement to be blocked (when hold policy is configured)
- An autonomous approval produces an approval_event with no reviewer_id and a valid policy_snapshot_id
- The full end-to-end flow on staging works without SEND_ENABLED=true in production: approve → queue → (no dispatch in prod) but the DB state is fully correct

**Risks**:
- Autonomous approval in production is a significant behavioral change. The workspace must have `requires_approval = false` configured explicitly. The default must be `requires_approval = true`. This default is safety-critical — verify it before merging.
- The traction hold mechanic may create unintended pipeline freezes. If a company has a permanently-HOT contact (e.g., a long-running engagement), all other contacts at that company are held indefinitely. The workspace policy must define a traction hold TTL or a manual resolution mechanism.

**No-go conditions**:
- Default workspace policy is anything other than `requires_approval = true`
- Autonomous approval activatable in production without explicit workspace policy configuration
- Sibling traction hold shown to be non-clearable (stuck holds) in staging tests
- PR L not merged and end-to-end approval flow not validated

---

## Phase 4 — Contextual Intelligence

**Doctrine reference**: Part II (Intelligence Layer, Memory Layer), Part V (Context Intelligence Architecture)

**Phase goal**: Every generated draft is grounded in what is known about the recipient. Context Packets are assembled, validated, and linked to every draft in the production generation path. Prior interaction history informs future generation. Rejection annotations feed back into operational memory.

**Phase prerequisite**: Phase 3 complete. The orchestration runtime is running in staging. The full approval flow (human and autonomous) is validated.

---

### PR N — Context Packet Production Path Wiring

**Scope**: Graduate the Context Intelligence Layer (introduced in shadow mode in PR E) to the production draft generation path. Every draft generation request must assemble a Context Packet before calling the LLM. The context packet ID is linked to the draft record.

**Depends on**: PR M merged. Phase 3 fully operational on staging.

**What changes**:
- The draft generation function (wherever the LLM call is made) is modified to: (1) call `ContextPacketBuilder.build()` before the LLM call; (2) pass the context packet to the LLM prompt as structured data; (3) store the `context_packet.id` on the draft record after successful generation
- New column on `outreach_drafts`: `context_packet_id UUID REFERENCES context_packets(id) ON DELETE SET NULL` (nullable — legacy drafts have no context packet; the nullable FK is not a violation)
- The draft detail API response is extended to include the context packet fields when available (for display in the review interface)
- Context Packet validation: if `ContextPacketBuilder.build()` returns a packet with validation errors (ungrounded claims, missing required fields), the generation request is flagged but not blocked — it proceeds with whatever context is available, and the validation warnings are attached to the draft record
- New column on `outreach_drafts`: `context_warnings (jsonb)` — stores any validation warnings from context assembly
- The prohibited claims check is enforced: if the context packet contains a prohibited claim category (per workspace policy), the claim is removed from the context before it is passed to the LLM

**Staging requirements**:
- Generate a new draft on staging for a contact that has enrichment data; verify the context packet is assembled and linked to the draft
- Generate a draft for a contact with no enrichment data; verify the context packet is assembled with appropriate "NONE" values and a warning annotation
- Verify the prohibited claims check: configure a prohibited claim category in staging workspace policy; include that claim in a contact record; verify the claim is absent from the assembled context packet

**Migration requirements**:
- New column on `outreach_drafts`: `context_packet_id` (nullable FK)
- New column on `outreach_drafts`: `context_warnings` (jsonb, nullable)
- Preflight: none required (additive nullable columns)

**Tests required**:
- Context packet is assembled and linked for every new draft generation request
- Legacy drafts (no context_packet_id) are not affected by this change
- Prohibited claims are filtered before the context packet is passed to the LLM
- Context validation warnings are stored on the draft, not raised as errors
- LLM is not called if context assembly raises a hard exception (only hard exceptions block generation; warnings do not)
- Context packet TTL: if a cached context packet is retrieved that is past its TTL, a new one is assembled

**Rollback plan**:
- Revert the generation function to the pre-context-packet behavior (LLM called without context packet)
- The `context_packet_id` and `context_warnings` columns remain on `outreach_drafts` but are unused
- All context packets already assembled remain in the `context_packets` table (no deletion)

**Acceptance criteria**:
- Every draft generated after PR N is merged has a non-null `context_packet_id`
- The context packet surfaced in the draft detail API includes contact profile, engagement history, company intelligence, and traction context
- Prohibited claims are confirmed absent from the LLM prompt context
- Legacy drafts with null `context_packet_id` function correctly through the approval and dispatch flow

**Risks**:
- The `ContextPacketBuilder.build()` call is synchronous and adds latency to draft generation. If the builder performs many DB queries, generation latency may increase. Profile this on staging before merging.
- The shadow mode tests (PR E) validated assembly logic but not the full integration with the LLM prompt. The prompt format must be tested end-to-end on staging.

**No-go conditions**:
- PR M not merged
- ContextPacketBuilder shown to produce ungrounded claims in staging tests
- LLM call made before context packet is assembled and linked

---

### PR O — Operational Memory and Prior Interaction Loop

**Scope**: Introduce the `contact_operational_memory` table. After each draft is sent, write a summary to operational memory. After each rejection, write the rejection annotation. When context packets are assembled, include prior interaction history from operational memory.

**Depends on**: PR N merged.

**What changes**:
- New table: `contact_operational_memory` — columns: id (UUID), contact_id, workspace_id, interaction_type (enum: DRAFT_SENT / DRAFT_REJECTED / ENGAGEMENT_RECEIVED / CONTEXT_NOTE), content_summary (text — a structured summary of what was said, not the full body), engagement_outcome (text: OPENED / CLICKED / REPLIED / IGNORED / BOUNCED / NONE), outcome_at (timestamptz), occurred_at, source_draft_id (nullable FK to outreach_drafts)
- After a draft is confirmed sent (sent_at set): write a `DRAFT_SENT` memory record with a content summary (subject line + brief body summary, not the full body)
- After a draft is rejected: write a `DRAFT_REJECTED` memory record with the rejection reason category and note (this is the feedback loop from `ApprovalService.reject()` introduced in PR L — currently the annotation write is best-effort; after PR O it writes to this table)
- After an engagement event is received (open, click, reply): write an `ENGAGEMENT_RECEIVED` memory record with the outcome type, linked to the source draft
- `ContextPacketBuilder.build()` is extended to query `contact_operational_memory` and include prior interaction history in the assembled context packet (doctrine: Engagement History component of the Context Packet)

**Staging requirements**:
- Full prior interaction loop on staging: generate and send a draft → verify DRAFT_SENT memory record → simulate open event → verify ENGAGEMENT_RECEIVED record → reject the next draft for this contact → verify DRAFT_REJECTED record → generate a third draft → verify the context packet includes the prior interaction history
- Verify content_summary is a meaningful summary, not a truncated body (the full body is not stored in operational memory)

**Migration requirements**:
- New table: `contact_operational_memory`
- Indexes: `(contact_id, workspace_id, occurred_at)` for context assembly queries (most recent N records)
- Indexes: `(source_draft_id)` for audit queries

**Tests required**:
- DRAFT_SENT record written when sent_at is set on a draft
- DRAFT_REJECTED record written when a draft is rejected via ApprovalService
- ENGAGEMENT_RECEIVED record written when an engagement event is processed by the signal layer
- Context packet assembly includes prior interaction history for contacts with memory records
- Context packet assembly for a contact with no memory records correctly represents "first contact"
- The content_summary field is populated, not null, for DRAFT_SENT records
- Operational memory records are never deleted (append-only behavior)

**Rollback plan**:
- Revert ContextPacketBuilder to not query contact_operational_memory (context packets assembled without prior interaction history — this was the PR N state)
- Revert the sent/rejection/engagement handlers to not write memory records
- The contact_operational_memory table and its records remain (no data loss)

**Acceptance criteria**:
- A contact with 3 prior interactions has all 3 represented in the context packet for their next draft
- The review interface shows the reviewer what has been said to this contact before (via the context packet in the draft detail API)
- A reviewer's rejection reason appears in the next context packet for the same contact, influencing the generation prompt

**Risks**:
- The content_summary must be generated at write time (when the draft is sent), not at read time. If the summary generation fails (e.g., LLM error during summarization), the memory record should still be written with a fallback summary (subject line only). Do not fail the send because the memory summarization fails.

**No-go conditions**:
- PR N not merged
- Memory records shown to contain full draft body text (privacy/size risk)
- Context packet assembly shown to include stale memory records beyond the intended lookback window

---

## Phase 5 — Governance Maturity

**Doctrine reference**: Part VII (Governance Architecture — risk scoring, escalation, audit), Part VIII (Observability Requirements)

**Phase goal**: Governance is observable, configurable, and surfaced to operators. Risk scoring informs human reviewers. The operator cockpit API enables non-technical operators to understand the governance posture of the system without engineering assistance.

**Phase prerequisite**: Phase 4 complete.

---

### PR P — Risk Scoring and Escalation

**Scope**: Implement draft risk scoring. Store the risk score on each draft. Use the risk score to trigger escalation to `pending_second_review` status for high-risk drafts.

**Depends on**: PR O merged.

**What changes**:
- Risk score calculation: a function that takes (contact engagement history, company traction state, context packet completeness, draft age, recent suppression activity) and returns an integer 0–100
- Risk factors and their weights (configurable in workspace policy):
  - Contact sent to before with no engagement: +20
  - Company traction is COLD: +15
  - Context packet completeness below threshold (missing required fields): +25 per missing category
  - Draft age over N days since generation: +15
  - Suppression was recently lifted for this contact (within 30 days): +30
- New column on `outreach_drafts`: `risk_score (smallint, nullable)` — populated at draft generation time
- Escalation: if `risk_score >= workspace_policy.escalation_threshold` (default: 70), set `approval_status = pending_second_review` instead of `pending`
- The draft review API response includes the risk score and the risk factors that contributed to it
- `pending_second_review` already exists as a valid `approval_status` enum value — no schema change needed for that

**Staging requirements**:
- Generate a draft for a contact with multiple prior non-engaged sends; verify risk score > 0 and escalation threshold is evaluated correctly
- Generate a draft for a well-enriched contact with no prior sends; verify risk score is low and approval_status is pending (not pending_second_review)
- Configure escalation_threshold in staging workspace policy; verify it is respected

**Migration requirements**:
- New column on `outreach_drafts`: `risk_score (smallint, nullable)`
- New column on `outreach_drafts`: `risk_factors (jsonb, nullable)` — stores the individual factor scores for review interface display
- Preflight: additive nullable columns; no preflight required

**Tests required**:
- Risk score calculated correctly for each factor independently
- Composite score is the sum of applicable factors (capped at 100)
- Escalation threshold triggers `pending_second_review` correctly
- Risk factors stored in `risk_factors` column accurately reflect the calculation
- Drafts generated before PR P have null risk_score and are not affected
- The `pending_second_review` status correctly prevents autonomous approval (the autonomous path must check for this status)

**Rollback plan**:
- Risk score calculation is additive; revert the generation function to not call the scorer
- Set `risk_score` to NULL for all affected drafts (the column remains but is ignored)
- `pending_second_review` drafts that were correctly escalated remain in that status; they require manual intervention to approve or downgrade

**Acceptance criteria**:
- Every newly generated draft has a non-null risk_score
- The risk_score correctly differentiates between low-risk (well-enriched, first-contact, fresh draft) and high-risk (repeat non-engaged, low context, old draft)
- Escalation threshold is respected per workspace policy configuration

**No-go conditions**:
- PR O not merged
- Risk score shown to be static (all drafts get same score) in staging tests
- Autonomous approval path shown to bypass `pending_second_review` status

---

### PR Q — Operator Cockpit API

**Scope**: Implement the operational metrics API. These endpoints are the foundation for a future operator cockpit UI. They serve data from existing tables — no new tables are introduced.

**Depends on**: PR P merged.

**What changes**:
- New API router: `backend/app/api/routes/metrics.py`
- Eight endpoints (all read-only, workspace-scoped):
  - `GET /api/metrics/pipeline-health` — draft counts by approval_status, sent_at IS NULL vs NOT NULL
  - `GET /api/metrics/queue-depth` — count of rows in outbound_queue by workspace
  - `GET /api/metrics/suppression-state` — count of suppression_rules by level and expiry window
  - `GET /api/metrics/disposition-distribution` — count of governance_decisions by disposition for last N days
  - `GET /api/metrics/send-success-rate` — count of send_attempts by status for last N days
  - `GET /api/metrics/workflow-velocity` — count of SEQUENCE_STEP_ADVANCED workflow_events per day for last N days
  - `GET /api/metrics/review-queue-age` — oldest open review gate (oldest pending or pending_second_review draft, with time-since-created)
  - `GET /api/metrics/context-coverage` — fraction of drafts generated in last 7 days with non-null context_packet_id
- All queries are bounded (no unbounded SELECTs) — each query uses a defined lookback window with a default and an optional `?days=N` parameter (max 90)
- All endpoints are workspace-scoped (workspace_id from auth context, not query parameter)

**Staging requirements**:
- Each endpoint tested with staging data that exercises non-trivial cases (not just zero-counts)
- Query performance: each endpoint must return in under 500ms on the staging DB with realistic data volume

**Migration requirements**:
- No new tables
- Consider adding a materialized view or summary table for `disposition_distribution` and `send_success_rate` if query performance on the live tables is insufficient. Defer the materialized view to a follow-up if not needed at staging data volume.

**Tests required**:
- Each endpoint returns correctly structured JSON for a workspace with data
- Each endpoint returns sensible zero-values for a workspace with no data (not 500 errors)
- All queries are bounded — verify no endpoint executes a full table scan in a test with large staging data
- Workspace isolation: workspace A cannot see workspace B's metrics via query parameter manipulation

**Rollback plan**:
- Remove the metrics router; the underlying data tables are unchanged

**Acceptance criteria**:
- All eight endpoints return correct data on staging
- No endpoint takes more than 500ms on staging
- A non-technical operator, given access to the API responses, can answer all eight observability questions from the doctrine without engineering assistance

**Risks**:
- Some metrics queries (especially disposition_distribution and send_success_rate) may scan large tables. Use indexed timestamp columns and the lookback window parameter to bound all queries. Add `EXPLAIN ANALYZE` output to the PR description for each query.

**No-go conditions**:
- Any endpoint performing an unbounded query (no WHERE clause on timestamp)
- Any endpoint leaking cross-workspace data

---

## Phase 6 — Multi-Channel Intelligence (Deferred)

**Doctrine reference**: Part X (Multi-Channel Future)

Phase 6 is deferred until Phase 5 is fully operational and stable. It begins only after:

1. The full governance model (Phases 2–5) is running in production
2. The operator cockpit API is in active use and showing healthy metrics
3. A second channel (LinkedIn) has been confirmed as the next business priority by Avanish

**When Phase 6 begins, the first PR is**:
- Define the Channel Adapter Interface and Channel Manifest as abstract types
- Refactor the Resend adapter to conform to the interface (it is the reference implementation)
- This PR has zero behavioral changes — it is purely structural

No Phase 6 PRs are defined in detail here until the above conditions are met.

---

## Phase 7 — Self-Improving Intelligence (Deferred)

**Doctrine reference**: Part XIII Phase 7

Phase 7 begins only after Phase 6 is operational (or after Phase 5 if multi-channel is deprioritized). It requires a sufficient body of outcome signal data in `contact_operational_memory` and `workflow_events` to be meaningful. Minimum threshold: 90 days of operational data post-Phase 4 deployment.

---

## Global No-Go Conditions

These conditions block any PR from merging, regardless of phase.

**NG-1: SEND_ENABLED=true in production without explicit session authorization from Avanish.**

**NG-2: A migration that creates a UNIQUE index or adds a NOT NULL column without a preflight query being run and returning zero qualifying rows.**

**NG-3: A staging validation that fails for the PR being merged.** The PR must not merge until staging validation passes, even if the failure seems unrelated.

**NG-4: Any append-only table (Category A per the doctrine) that receives an UPDATE or DELETE in the new code path.**

**NG-5: Any governance decision that is written without a valid policy_snapshot_id reference.** Governance decisions without a linked policy snapshot are audit violations.

**NG-6: An approval path that sends without a recorded approval event.** Whether human or autonomous, every send requires a traceable authorization record.

**NG-7: The scheduler lock not being tested for correct singleton behavior before the first Phase 3 PR merges to production.** Running two schedulers concurrently without the lock is a correctness risk.

**NG-8: Any new API endpoint that does not apply workspace-scoped filtering.** Cross-workspace data leakage is a multi-tenancy violation.

**NG-9: Phase 3 (orchestration runtime) enabled before Phase 2 (durable execution) is fully validated in production.** The orchestration runtime advances workflows and triggers sends. Without durable execution, those sends have no idempotency guarantee.

**NG-10: Autonomous approval activated in a workspace without explicit configuration by that workspace's operator.** The default must always be `requires_approval = true`. Autonomous approval is opt-in, never opt-out.

---

## PR Dependency Map

```
Phase 0 (Staging)
  Task 0-A: Supabase Staging Project
  Task 0-B: Railway Staging Environment
  Task 0-C: Migration Pipeline Hardening
       |
       | (all Phase 0 tasks complete)
       v
Phase 2 (Durable Execution)
  PR F: Outbound Queue + Transactional Outbox
       |
       v
  PR G: Dispatch Mechanics + Retry Model + Dead-Letter
       |
       v
  PR H: Reconciliation Job + Provider Event Linkage
       |
       | (Phase 2 complete)
       v
Phase 3 (Orchestration Runtime)
  PR I: Scheduler Decomposition + Singleton Lock
       |
       v
  PR J: Workflow State Machine + Sequence Progress
       |
       v
  PR K: Policy Evaluation Chain + Governance Decisions
       |
       v
  PR L: Approval Service Consolidation
       |
       v
  PR M: Sibling Traction + Autonomous Approval Activation
       |
       | (Phase 3 complete)
       v
Phase 4 (Contextual Intelligence)
  PR N: Context Packet Production Path Wiring
       |
       v
  PR O: Operational Memory + Prior Interaction Loop
       |
       | (Phase 4 complete)
       v
Phase 5 (Governance Maturity)
  PR P: Risk Scoring + Escalation
       |
       v
  PR Q: Operator Cockpit API
       |
       | (Phase 5 complete)
       v
Phase 6 (Multi-Channel) — Deferred
Phase 7 (Self-Improving Intelligence) — Deferred
```

All PRs within a phase are strictly sequential. No PR may begin until its predecessor is merged AND validated on staging.

---

## Staging Validation Checklist Template

The following checklist applies to every PR in this roadmap. Each item must be checked before the PR is eligible for merge.

```
PR: [letter and name]
Staging validation date: [date]

[ ] Migration preflight query executed on staging — zero qualifying rows confirmed
[ ] Migration executed on staging — no errors
[ ] Post-migration verification queries run — schema objects confirmed present
[ ] Smoke tests run on staging — all pass, all rolled back (no persistent test data)
[ ] End-to-end behavioral test run — described behavior observed on staging
[ ] No regression in existing behavior (prior PR acceptance criteria still met)
[ ] SEND_ENABLED=false confirmed in production
[ ] PR author has reviewed staging logs for unexpected errors
[ ] Go/no-go decision: [ ] GO  [ ] NO-GO
[ ] No-go reason (if applicable): ___________
```

---

## Estimated Phase Complexity

This is a complexity assessment, not a time estimate. Time estimates depend on engineering availability and scope clarity at execution time.

| Phase | PRs | Complexity | Primary Risk |
|---|---|---|---|
| Phase 0 | 3 tasks | Low — infra setup | Staging data contamination |
| Phase 2 | 3 PRs | Medium — new tables + dispatch path | PgBouncer transaction scope |
| Phase 3 | 5 PRs | High — orchestration + governance chain | Behavior regression in approval path |
| Phase 4 | 2 PRs | Medium — wiring existing layer | LLM prompt integration quality |
| Phase 5 | 2 PRs | Low-Medium — metrics + scoring | Query performance at scale |
| Phase 6 | TBD | High — channel abstraction | Orchestration fork risk |
| Phase 7 | TBD | Medium | Requires Phase 4 data maturity |

The highest-risk transition is **Phase 2 to Phase 3**. Phase 2 introduces the execution substrate. Phase 3 builds the decision-making layer on top of it. A flaw in the Phase 2 execution model (e.g., non-atomic outbox, incorrect retry semantics) will be amplified when Phase 3 begins issuing autonomous decisions. Phase 2 must be validated thoroughly in production before Phase 3 begins.

---

*End of implementation roadmap.*

---

**Document status**: This roadmap is a living document. It should be updated when PR scope changes, when new risks are identified, or when phase sequencing changes. Every update should include the date and a one-line rationale. The architecture doctrine (PROSPECTIQ_VNEXT_ARCHITECTURE.md) is not modified to reflect implementation decisions — it remains the canonical reference.
