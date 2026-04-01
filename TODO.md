# ProspectIQ — Active TODO
**Last updated:** 2026-04-01 (end of day session)

---

## P0 — Blocking (do these first)

- [ ] **Apply campaign_threads migration** — `migrations/001_campaign_threads.sql` in Supabase SQL editor. Prerequisite for Phase 2/3 (reply ingestion, HITL).
- [ ] **Verify background agent UI build** — check agent `aa307d75e76e4c5f7` completed all 12 tasks (Command Center, Threads, Outreach Hub, Sequences, Segments, Signals, Intelligence, Billing integration)
- [ ] **Fix engagement agent send path** — wire per-cluster Instantly routing via `get_campaign_id_for_company()`. ProspectIQ should auto-provision missing campaigns (not manual Instantly setup).
- [ ] **Create Stripe products** — Growth ($299/mo), Scale ($799/mo), API (metered). Update `billing_core/tier_plans.py` with real price IDs. Register webhook at `/api/billing/webhooks/stripe`.

## P1 — Next sprint

- [ ] **OutreachAgent** — generate personalized email drafts using `personalization_hooks` + `trigger_events` + contact persona. Human approval flow before send.
- [ ] **Password reset flow** — missing from auth. Login + signup exist. Needs `/forgot-password` + `/reset-password` pages + backend endpoint.
- [ ] **Route protection hardening** — add `require_workspace_member()` explicitly to `/api/companies`, `/api/approvals`, `/api/analytics` (currently implicit via WorkspaceMiddleware only — returns 400 not 401 if auth missing).
- [ ] **Set Instantly env vars** — `INSTANTLY_SEQ_MACHINERY_VP_OPS`, `INSTANTLY_SEQ_AUTO_VP_OPS`, `INSTANTLY_SEQ_CHEMICALS_VP_OPS`, etc. in `.env`. Required for engagement agent routing.

## P2 — Later

- [ ] RBAC enforcement — roles (owner/admin/member/viewer) stored in `workspace_members.role` but not checked in route handlers
- [ ] AUTH_DEMO_MODE fallback — for dev/demo without requiring a real Supabase project
- [ ] Audit logging — `audit_log` table exists but no events recorded
- [ ] CRM sync — HubSpot/Salesforce integration
- [ ] Trigger monitoring — ongoing signal refresh (currently one-time research)
- [ ] Lookalike discovery — find companies similar to converted accounts

## Research Pipeline

- [ ] **Resume research** — Anthropic monthly cap resets May 1, 2026. Pre-pay credits before then. Run `run_instantly_research.py` on remaining ~170 queued companies.
- [ ] **Tranche population** — most companies have NULL tranche (no revenue/employee count). Will auto-populate as research completes and backfill re-runs.

## Completed This Session ✓

- [x] Apply migration 014 (tranche + campaign_cluster + outreach_mode columns)
- [x] Run backfill — 7,782 companies stamped with cluster/mode
- [x] Fix `api_costs` workspace_id warning in `database.py`
- [x] Design and approve full ProspectIQ UI redesign
- [x] Launch background agent to build all 12 UI components
- [x] Audit auth system — confirmed complete and functional
- [x] Update SESSION_HANDOFF.md
