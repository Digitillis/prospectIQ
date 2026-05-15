# Operational Readiness Assessment — 001
## ProspectIQ — Pre-Backfill Activation Gate

**Assessment date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Based on:** Steps 1–4 of Phase 3 SRE Validation Sequence  
**Status:** READY WITH CONDITIONS — controlled subset backfill authorized after prerequisite actions

---

## Evidence Base

This assessment synthesizes findings from four prior steps completed during the Phase 3 SRE validation sequence:

| Step | Document | Verdict |
|------|----------|---------|
| 1 | Backfill dry-run (51 candidates analyzed via psql) | Candidates identified; 9 ineligible, 6 require review |
| 2 | `BACKFILL_REVIEW_REPORT.md` | 36 SAFE, 6 REVIEW, 9 DO NOT BACKFILL |
| 3 | No-write verification | All zero counts confirmed; queue untouched |
| 4 | `DARK_LAUNCH_RUNTIME_OBSERVATION_001.md` | Runtime stable; all queue jobs error-free |

---

## Assessment Answers

### Q1. Is the queue runtime stable?

**YES.**

The evidence is unambiguous:

- `dispatch_loop` executes and returns in microseconds with SEND_ENABLED=false. Zero PostgREST calls per tick.
- `reclaim_stale_locks` runs every 2 minutes, hits the now-extant `outbound_queue` table, finds 0 eligible rows, and completes cleanly. Zero errors.
- All pre-migration PostgREST errors (`claim_outbound_queue_batch not found`, `outbound_queue relation not found`) are eliminated.
- APScheduler `BackgroundScheduler` has been stable since deployment at ~20:30 CT on 2026-05-15. Health endpoint responds `{"status":"ok"}` with no signs of scheduler thread crashes or restart loops.
- Send-trace confirms abort at the correct gate: `{"abort_at":"send_enabled=false","trace":[]}`.

The only active runtime error (`health_snapshot` / `company_status: "high_priority"` enum mismatch) is pre-existing, unrelated to the queue infrastructure, and does not affect dispatch or send behavior.

**Queue runtime stability: CONFIRMED.**

---

### Q2. Is production safe for controlled backfill?

**YES, with the prerequisite actions in Section H completed first.**

The following conditions are verified and in place:

| Safety condition | State |
|-----------------|-------|
| `SEND_ENABLED=false` in Railway production env | CONFIRMED (corrected 2026-05-15) |
| `outreach_send_config.send_enabled=false` in DB | CONFIRMED (migration 029) |
| `outbound_queue` table exists with correct schema | CONFIRMED (migration 054) |
| `claim_outbound_queue_batch()` function exists | CONFIRMED (migration 055) |
| `outbound_queue` row count = 0 | CONFIRMED (Step 3 no-write verification) |
| `send_attempts` row count = 0 | CONFIRMED |
| `dispatch_loop` inert at current env setting | CONFIRMED |
| All 50→55 migrations applied and verified | CONFIRMED |
| Production-staging migration parity | CONFIRMED (both at 055) |

With SEND_ENABLED=false and DB send_enabled=false, inserting rows into `outbound_queue` via the backfill script will NOT trigger any sends on the next cron tick. The dispatch guard returns before calling the RPC. The queue population event is operationally isolated from dispatch activation.

**Production is safe for controlled backfill execution once prerequisites are cleared.**

---

### Q3. Should all 51 drafts be backfilled?

**NO.**

The full 51-candidate set contains 15 drafts that must not be backfilled without prior action:

- **9 DO NOT BACKFILL:** Hard bounces, invalid emails, and one contact with no email address. Sending to these will either fail with a Resend error or reach an unintended recipient. These must be pre-rejected before executing `--execute`.
- **6 REVIEW:** Unverified or catch-all email addresses with non-trivial delivery risk. These require Avanish's decision before inclusion.

The current `backfill_outbound_queue.py` script does NOT filter against `suppression_log`. Running `--execute` on the full 51 without pre-rejecting the excluded set would enqueue ineligible drafts.

**Do not backfill all 51.**

---

### Q4. Should only a subset be backfilled?

**YES — the 36 SAFE candidates, with company-concentration gating applied.**

The 36 SAFE candidates have verified email addresses, no suppression entries, coherent step sequencing (all 20 step-2 drafts have confirmed sent step-1 predecessors), and no bounce history.

**Concentration risk note:** Eos Energy has 3 step-2 drafts targeting the same company. The `claim_outbound_queue_batch()` function orders by `priority ASC, enqueued_at ASC` but does not enforce a per-company cap. The current `batch_size=10` (staging) and `batch_size=50` (production) both allow multi-contact-per-company within a single batch.

**Recommended approach:** Before executing `--execute`, set `outreach_send_config.batch_size=1` in production DB, or modify the backfill script to set `priority` values such that no two contacts from the same company occupy the same batch window (Eos Energy's 3 drafts should be spaced ≥ 1 send window apart via `next_retry_at` offsets or priority ordering).

---

### Q5. Should some drafts be discarded instead of backfilled?

**YES — the 9 DO NOT BACKFILL candidates should be set to `approval_status='rejected'` before running `--execute`.**

Pre-rejection is the correct action because:

1. Leaves a clear audit trail in `outreach_drafts` (status = rejected, not silently excluded)
2. Prevents these drafts from being picked up by the backfill script or any future automated path
3. Aligns with the `dispatch_failed` terminal state design intent — only dispatch should set `dispatch_failed`; human exclusion should use `rejected`

The 9 candidates to reject:

| Contact email | Reason |
|--------------|--------|
| culbrich@ulbrich.com | Invalid email (bad format) |
| john.hammerle@* | Hard bounce (suppression_log) |
| ken.michiels@* | Hard bounce (suppression_log) |
| chad.kruger@* | Hard bounce (suppression_log) |
| bruce.bratton@* (domain bounce) | Hard bounce — domain-level suppression |
| laurie_barton@* | Hard bounce (suppression_log) |
| chrichardson@* | Hard bounce (suppression_log) |
| randres@* | Hard bounce (suppression_log) |
| Cincinnati Incorporated contact | No email address on record |

These rejections can be executed via a targeted SQL UPDATE (not via backfill script) and should be reviewed by Avanish before execution.

---

### Q6. Is observability sufficient?

**PARTIAL — sufficient for dark-launch; not sufficient for active dispatch.**

**Currently sufficient:**
- `/api/admin/send-config` returns `env_send_enabled`, `db_send_config`, `approved_unsent`, `sent_today`
- `/api/admin/send-trace` returns dry-run trace with abort point
- `/health` endpoint returns service liveness
- `outbound_queue` and `send_attempts` row counts queryable via psql
- `reclaim_stale_locks` running correctly — detects orphaned locks when queue is populated

**Gaps for active dispatch (not blocking dark-launch; required before send activation):**

| Gap | Risk | Mitigation |
|-----|------|-----------|
| No delivery webhook processing | Resend `delivered` / `bounced` events not updating `send_attempts` | Must wire Resend webhook handler before enabling sends |
| No alert on `send_attempts.status = FAILED` | Failed sends invisible until manual psql query | Add monitoring query or Supabase alert |
| Railway log access blocked via CLI | Cannot stream scheduler logs in real-time | Use Railway dashboard logs tab during first active dispatch window |
| `health_snapshot` agent failing | Health capture data incomplete | Fix `company_status` enum mismatch — pre-existing bug |
| No per-workspace send summary API | Post-send audit requires raw SQL | Low priority; not blocking |

**Observability is sufficient for the current dark-launch phase.** It is not sufficient for the transition to active dispatch. The Resend webhook gap is a hard blocker for send activation.

---

### Q7. Is the scheduler stable enough for activation?

**YES for dark-launch continuation; CONDITIONAL for send activation.**

**Dark-launch (current state):** Scheduler is stable. Both PR G jobs are registered and executing correctly. APScheduler `BackgroundScheduler` has been stable through at least 1 full deployment lifecycle. No thread crashes, no restart loops.

**Send activation conditions (must be verified before enabling):**

1. **Overlap risk resolved:** `send_approved` (legacy) and `dispatch_loop` both fire at Mon-Fri 8-11 AM CT :00 :30. Before activation, `send_approved` must be disabled (commented out or paused in APScheduler) and `dispatch_loop` must be the sole active send path. Running both with SEND_ENABLED=true would allow the legacy path to attempt sends via `EngagementAgent` while the queue path also claims rows — dual-dispatch risk.

2. **PgBouncer transaction mode:** `claim_outbound_queue_batch()` uses `FOR UPDATE SKIP LOCKED` inside a plpgsql function called via Supabase RPC. Transaction mode PgBouncer is safe here because the lock acquisition and the UPDATE are within a single function call (one connection, one transaction). No additional connection pooling work required.

3. **Instance ID isolation:** `claim_outbound_queue_batch()` takes `p_instance_id` as a lock identifier. The current `dispatch_workspace()` generates an instance ID per call. Single-instance Railway deployment means no concurrent dispatchers — no conflict risk. If Railway is ever scaled to multiple replicas, the instance ID mechanism correctly prevents duplicate claiming.

**Scheduler stability: CONFIRMED for dark-launch. Conditional for activation (disable send_approved first).**

---

### Q8. Are additional safeguards required before enqueue execution?

**YES — four actions are required before running `backfill_outbound_queue.py --execute`:**

#### Required (blocking)

| # | Action | Owner | Blocker if skipped |
|---|--------|-------|--------------------|
| R1 | Pre-reject 9 DO NOT BACKFILL drafts in `outreach_drafts` | Avanish approval → execute via SQL | Backfill script enqueues invalid/bounced contacts |
| R2 | Avanish decision on 6 REVIEW drafts (include / verify / exclude) | Avanish | 6 uncertain candidates enter queue without human sign-off |
| R3 | Confirm SEND_ENABLED=false in production Railway env immediately before executing `--execute` | Avanish | If env was changed, populated queue dispatched on next cron tick |

#### Recommended (non-blocking but strongly advised)

| # | Action | Why |
|---|--------|-----|
| R4 | Set `outreach_send_config.batch_size=1` in production DB before backfill, or add priority offsets to Eos Energy drafts | Prevents Eos Energy's 3 contacts from being claimed in the same dispatch batch |

#### Not required for backfill execution (required for send activation, defer to that gate)

- Resend webhook handler
- Legacy `send_approved` disable
- health_snapshot enum fix
- RAILWAY_TOKEN rotation in GitHub Actions

---

## Overall Verdict

| Dimension | Status |
|-----------|--------|
| Queue runtime stability | STABLE — all errors eliminated, jobs executing correctly |
| Production safety for backfill | SAFE — with R1/R2/R3 prerequisites completed |
| Backfill scope | 36 SAFE immediately; 6 REVIEW pending Avanish decision; 9 REJECT |
| Observability | SUFFICIENT for dark-launch; Resend webhook gap blocks send activation |
| Scheduler stability | STABLE for dark-launch; send_approved overlap must be resolved before activation |
| Additional safeguards | 3 blocking (R1, R2, R3); 1 recommended (R4) |

**The system is operationally ready for controlled queue population (backfill execution) once R1, R2, and R3 are completed and Avanish issues explicit authorization to run `--execute`.**

**The system is NOT yet ready for send activation.** Send activation is a separate gate requiring: Resend webhook wiring, `send_approved` scheduler disable, SEND_ENABLED env change, and DB `send_enabled` change — none of which are authorized in this session.

---

## Prerequisite Checklist for Backfill Execution

```
[ ] R1 — Avanish reviews and approves SQL to reject 9 DO NOT BACKFILL drafts
[ ] R1 — Execute pre-rejection SQL UPDATE on outreach_drafts
[ ] R2 — Avanish issues decision on 6 REVIEW drafts (include / exclude)
[ ] R3 — Verify SEND_ENABLED=false in Railway production env immediately before running --execute
[ ] R4 (recommended) — Confirm batch_size or priority offsets for Eos Energy concentration risk
[ ] Authorization — Avanish issues explicit authorization to run backfill_outbound_queue.py --execute
```

No code changes, schema changes, or new PRs are required to clear this checklist. All items are configuration and data decisions.

---

## What Comes After Backfill (Not Authorized in This Session)

For the record — these steps are blocked pending future explicit authorization:

1. Monitor first populated-queue dark-launch window (DARK_LAUNCH_RUNTIME_OBSERVATION_002, Friday 2026-05-16 8–11:30 AM CT)
2. Wire Resend delivery webhook handler
3. Disable `send_approved` legacy scheduler job
4. Coordinate send activation: DB `send_enabled` → true, Railway env `SEND_ENABLED` → true (Avanish explicit authorization required)
5. Monitor first live dispatch window (DARK_LAUNCH_RUNTIME_OBSERVATION_003)

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/OPERATIONAL_READINESS_ASSESSMENT_001.md`  
**Prerequisite documents:** `BACKFILL_REVIEW_REPORT.md`, `DARK_LAUNCH_RUNTIME_OBSERVATION_001.md`
