# ADR-003 — Tenant RLS: deferral + fail-closed _filter_ws

**Status:** Accepted  
**Date:** 2026-06-04

## Context

ProspectIQ uses Supabase's service-role key for all backend DB access. Supabase's service-role key has `BYPASSRLS` — PostgreSQL Row-Level Security policies are silently skipped for every query. Enabling RLS policies on tables while using the service-role key is a no-op; the policies are compiled but never evaluated.

The ART Stage 1 assessment (SEC-014) identified this and flagged two risks:
1. Real RLS would give a false sense of security if the service-role key is in use.
2. The `Database._filter_ws()` helper fails open when `workspace_id` is not set (returns an unfiltered query), which can leak data across workspaces on routes that do not call `require_workspace_member` first.

## Decision

### Defer real Postgres RLS

Enabling Postgres RLS requires migrating to a per-role connection (not service-role) for every query. That is a substantial refactor. Trigger: first paid contract or Lighthouse 2 milestone, whichever comes first.

### Harden `_filter_ws` to fail closed — build now

`_filter_ws` must raise `RuntimeError` (or equivalent) when `workspace_id` is None instead of returning an unfiltered query. This ensures that any route that forgets to set the workspace context gets a 500 (visible error) rather than silently leaking all-tenant data.

The implementation is a one-line change in `database.py`:

```python
def _filter_ws(self, query):
    if not self.workspace_id:
        raise RuntimeError("_filter_ws: workspace_id is not set — refusing to return unfiltered query")
    return query.eq("workspace_id", self.workspace_id)
```

### Add 2-tenant regression test

A test that creates two fake workspace_ids and verifies that `_filter_ws` with workspace A cannot see workspace B's rows.

## Why fail-closed matters more than RLS right now

At pre-revenue solo-founder stage, with one real workspace, a cross-tenant data leak is primarily a risk from code bugs (missing `require_workspace_member`) rather than from a multi-tenant exploit. Fail-closed `_filter_ws` catches the bug category immediately (500 in development, logged ERROR in production) without requiring a Postgres-level config change.

## BYPASSRLS note for future auditors

The service-role key has `BYPASSRLS`. RLS policies that appear in migrations are **not enforced** for backend API queries. Do not rely on them for tenant isolation until the key type changes. This is documented here as a permanent record.
