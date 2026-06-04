# ADR-001 — Multi-instance scheduler: Postgres advisory lock

**Status:** Accepted  
**Date:** 2026-06-04

## Context

`recompute_and_persist` and `enqueue_todays_schedule` in `send_scheduler.py` are called by APScheduler cron jobs inside each Railway dyno. When Railway runs two or more dynos (e.g. during a rolling deploy or horizontal scale-out), both dynos fire the 7:55am `enqueue_schedule` and the 2:30am `schedule_recompute` jobs concurrently.

Two concurrent `enqueue_todays_schedule` calls produce duplicate `outbound_queue` rows for every draft — one row per dyno. The dispatch loop then sends each draft twice. Two concurrent `recompute_and_persist` calls race on the `DELETE ... WHERE status='scheduled'` / `UPSERT` pair, producing a corrupt or doubled schedule.

## Decision

Wrap both functions in a PostgreSQL session-level advisory lock obtained via `pg_try_advisory_lock(key)` at function entry. A process that cannot acquire the lock (because the other dyno already holds it) logs a warning and returns immediately without mutating state. The lock is released explicitly via `pg_advisory_unlock(key)` in a `finally` block, and is auto-released when the connection closes.

**Lock keys** (fixed, stable across deploys):
- `recompute_and_persist`: `0xA3F1C2E4` (MD5("prospectiq:recompute")[:4] as uint32)
- `enqueue_todays_schedule`: `0x7B9D4F2A` (MD5("prospectiq:enqueue")[:4] as uint32)

## Why not a distributed mutex (Redis/etc.)?

ProspectIQ already holds an open Postgres connection for every scheduler tick. Adding Redis adds an external dependency and a second failure mode. Postgres advisory locks are transactionally safe and require no additional infrastructure.

## Why `pg_try_advisory_lock` (non-blocking) vs `pg_advisory_lock` (blocking)?

A blocking call would queue the second dyno behind the first. Since the second run would produce an identical result (idempotent recompute), it is wasteful. Skip-and-log is cheaper and leaves a visible audit trail.

## Why is this defence-in-depth, not the primary safety net?

The schedule is idempotent (same state → same output) and the dispatch path uses `FOR UPDATE SKIP LOCKED` + atomic `sent_at` pre-claim. Even without the advisory lock a second recompute would produce the same schedule. The advisory lock prevents the specific corrupt interleave where dyno A deletes rows while dyno B is mid-insert.

## Fallback

If `pg_try_advisory_lock` itself fails (e.g. the RPC is not exposed via Supabase), the wrapper logs a warning and allows the call to proceed. This degrades to the prior behaviour rather than silently blocking all sends.
