# ADR-002 — Audit-record immutability: app-layer status-transition guard

**Status:** Accepted  
**Date:** 2026-06-04

## Context

`send_attempts` rows and `outreach_drafts.approval_status` are audit records. Their status fields are lifecycle state machines; moving backward (e.g. DELIVERED → DISPATCHED, or approved → pending) corrupts accounting and compliance evidence.

The ART Stage 1 assessment (SEC-013) found that the application layer has no guard against illegal backward transitions. Any route or agent that updates these tables can accidentally (or maliciously) regress a terminal status.

Two options were evaluated:

- **Option A (this ADR):** Application-layer guarded-transition check: reject writes that would move a record to a status that is earlier in the lifecycle. One legitimate exception: DELIVERED → PERMANENTLY_FAILED is allowed (bounce reconciliation path).
- **Option B:** PostgreSQL CHECK constraint or trigger. Rejected for this cycle because the Supabase service-role key has `BYPASSRLS` and can bypass row-level guards. A trigger would work but adds DB migration surface for a guard that the app layer can enforce equally well.

## Decision

Add an application-layer guard in `dispatch_scheduler.py` that validates status transitions before writing:

```
Allowed forward transitions (non-exhaustive):
  DISPATCHED → DELIVERED | FAILED | PERMANENTLY_FAILED
  FAILED → (retry — DISPATCHED again, new row) | PERMANENTLY_FAILED
  PERMANENTLY_FAILED → (terminal — no further writes)
  DELIVERED → PERMANENTLY_FAILED (bounce reconciliation only)
```

Any attempt to write a backward transition raises a logged error and returns without writing. The guard does not raise an HTTP exception (writes happen in background workers) — it logs `ERROR` and the caller's normal error path handles it.

## What is NOT built this cycle

- DB-level trigger / CHECK constraint — deferred to: first enterprise customer requires auditor sign-off or SOC2 auditor engaged (Q4 2026 baseline, per deferral list).
- Tamper-evident hash chain (OST-009) — same trigger.

## Rationale for app-layer guard now

The bounce reconciliation path (DELIVERED → PERMANENTLY_FAILED) is a legitimate backward-looking transition that a DB-level constraint would either block or need to explicitly allow. The app layer can express the business rule precisely without migration surface.
