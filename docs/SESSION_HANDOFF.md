# ProspectIQ — Session Handoff
**Date:** 2026-04-01 (end of day)
**Session:** Full product design + infrastructure session
**Purpose:** Seamless context transfer for next session

---

## What Was Accomplished This Session

### 1. Infrastructure Fixes
- **`api_costs` workspace_id warning fixed** — `log_api_cost()` in `backend/app/core/database.py` no longer calls `_inject_ws()` since `api_costs` has no `workspace_id` column
- **Migration 014 applied** (`supabase_migrations/migrations/014_tranche_campaign_cluster.sql`) — adds `tranche`, `campaign_cluster`, `outreach_mode` columns to companies
- **Backfill complete** — `backfill_tranche_cluster.py` ran successfully:
  - 7,782 companies updated with cluster + outreach_mode
  - 5,676 skipped (already set or no tier)
  - Tranche mostly NULL (needs revenue/employee count from research to populate)
  - Distribution: machinery/auto/chemicals/metals/process/fb/other clusters stamped

### 2. Research Pipeline
- Monthly API cap hit again mid-run (cap resets May 1, 2026)
- **107 companies researched this session, $2.34 committed** — batching worked, no money lost
- `run_instantly_research.py` created: batched 50/run, $1.25 max exposure per process kill
- Research resumes May 1 (or if cap is raised earlier)

### 3. Comprehensive Product Design Approved
Full redesign of ProspectIQ as a standalone AI-native outbound intelligence product. Design reviewed and approved by Avanish. Background agent (`aa307d75e76e4c5f7`) launched to build all UI.

**Design decisions locked:**
- Thread library: split-pane layout (master list left, full thread right)
- Sequence library: pre-built templates + custom template creation/saving
- Progress tracking: Weekly Cadence Tracker (pipeline velocity, reply rates, funnel progress)
- HITL activities: prominently flagged on Command Center attention bar (not buried)
- Billing: integrated into Command Center (usage widget + upgrade CTA)

### 4. Full UI Build In Progress (background agent)
All of the following are being built by background agent `aa307d75e76e4c5f7`:

**Backend additions:**
- `backend/app/api/routes/threads.py` — thread list, detail, create, message, classify endpoints
- `backend/app/api/routes/intelligence.py` — buying signals, intent, draft quality, send time, A/B, funnel, reports endpoints
- Command Center aggregate endpoint

**Frontend pages:**
- Command Center — attention bar with HITL items, pipeline KPIs, weekly cadence widget, billing usage tile
- Threads — split-pane (list + full thread)
- Outreach Hub — 4 tabs: Approved/Pending/In Flight/Done
- Sequences — library (pre-built + custom templates) + builder (6-touch, gap config, webhook toggle)
- Segments — ICP config as UI (replaces icp.yaml)
- Signals — buying/intent signal feed
- Intelligence — analytics (funnel, A/B, draft quality, reply times)
- Billing — surface in Command Center + standalone page

**Sidebar restructured:**
- Command Center (home)
- Outreach Hub
- Threads
- Sequences
- Segments
- Signals
- Intelligence
- Settings (Billing, Team, API Keys, ICP)

---

## Current Pipeline State

### Company Funnel (as of session end)
| Status | Count | Notes |
|--------|-------|-------|
| Total in DB | ~13,458 | All tiers |
| Tranche stamped | 7,782 | cluster + outreach_mode set |
| Researched | ~107–210 | From today's batches (cap hit) |
| Qualified (PQS scored) | 1,097+ | Research re-scoring ongoing |
| Approved outreach drafts | 96 | Cannot send until engagement agent fixed |

### Research Pipeline
- **Paused** — Anthropic monthly cap hit. Resets May 1, 2026.
- Cap raised during session but hit again. Consider pre-paying credits before May 1.
- Batching architecture in place: 50 companies/batch, max $1.25 exposure per kill

---

## Pending Work (Priority Order)

### P0 — Blocking
1. **Apply campaign_threads migration** (`migrations/001_campaign_threads.sql`) in Supabase SQL editor — prerequisite for Phase 2/3 sequencing
2. **Fix engagement agent send path** — wire per-cluster routing via `get_campaign_id_for_company()`, auto-provision missing Instantly campaigns (ProspectIQ creates them, not manual setup)
3. **Create Stripe products** (price IDs are placeholders in `billing_core/tier_plans.py`):
   - ProspectIQ Growth: $299/mo, $239.20/mo annual
   - ProspectIQ Scale: $799/mo, $639.20/mo annual
   - ProspectIQ API: metered (usage-based)
   - Register webhook: `/api/billing/webhooks/stripe`
   - Set env vars: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `APP_BASE_URL`
4. **Verify background agent output** — check `aa307d75e76e4c5f7` completed all 12 UI tasks

### P1 — Next
5. **OutreachAgent** — generate personalized email drafts from `personalization_hooks` + `trigger_events`; human approval before send
6. **Password reset** — missing from auth (login/signup exist, no reset flow)
7. **Stripe price IDs** — update `billing_core/tier_plans.py` with real Stripe IDs after creation
8. **Route protection hardening** — add `require_workspace_member()` explicitly to companies/approvals/analytics routes (currently implicit via middleware only)

### P2 — Later
9. RBAC enforcement (roles defined but not checked in handlers)
10. Audit logging
11. CRM sync (HubSpot/Salesforce)
12. Trigger monitoring (ongoing, not one-time research)

---

## Auth System Status
- **Login/Signup**: fully working (Supabase JWT, not Auth0)
- **Workspace isolation**: solid — WorkspaceMiddleware + WorkspaceContext ContextVar
- **Route protection**: ~60% explicit — key routes protected, most data routes rely on implicit context
- **RBAC**: roles stored (owner/admin/member/viewer), not enforced in handlers
- **Missing**: password reset, demo mode, full route protection
- **Not needed**: Auth0 (ProspectIQ uses Supabase natively — simpler and appropriate)

---

## Key File Locations

```
prospectIQ/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── research.py          # ResearchAgent — claude-sonnet-4-6
│   │   │   ├── qualification.py     # QualificationAgent — PQS scoring
│   │   │   ├── enrichment.py        # EnrichmentAgent — Apollo People Match
│   │   │   └── engagement.py        # EngagementAgent — Instantly integration (send path broken)
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py          # Fixed: api_costs no longer calls _inject_ws()
│   │   │   ├── auth.py              # JWT + API key auth
│   │   │   └── workspace.py         # WorkspaceContext ContextVar
│   │   └── api/
│   │       ├── main.py              # FastAPI app, middleware stack
│   │       └── routes/              # companies, approvals, pipeline, analytics, billing, auth
│   └── billing_core/
│       ├── tier_plans.py            # Starter/Growth/Scale/API tiers — price_ids are PLACEHOLDERS
│       └── stripe_client.py
├── dashboard/                       # Next.js frontend
│   ├── app/
│   │   ├── login/page.tsx
│   │   ├── signup/page.tsx
│   │   └── [all other pages being built by background agent]
│   └── middleware.ts                # Supabase session check + redirect
├── migrations/                      # Local migration files
│   └── 001_campaign_threads.sql     # NOT YET APPLIED — apply in Supabase SQL editor
├── supabase_migrations/migrations/
│   └── 014_tranche_campaign_cluster.sql  # APPLIED
├── backfill_tranche_cluster.py      # DONE — do not re-run
├── run_instantly_research.py        # Batched research runner (50/batch)
├── icp.yaml                         # ICP config — being replaced by Segments UI
└── docs/
    ├── SESSION_HANDOFF.md           # This file
    └── INCIDENT_REPORT_2026_04_01.md  # Anthropic cap incident report ($33.01 lost)
```

---

## Database Key Tables
- `companies` — 13,458 rows. `tranche`, `campaign_cluster`, `outreach_mode` now stamped for 7,782
- `contacts` — enriched contacts ready for outreach
- `api_costs` — Anthropic spend tracking (no workspace_id column)
- `pipeline_runs` — batch job tracking
- `campaign_threads` — **NOT YET CREATED** (migration 001 not applied)
- `thread_messages` — **NOT YET CREATED**
- `workspace_api_keys` — API key auth table

## Env Vars Needed (not yet set)
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
APP_BASE_URL=https://app.prospectiq.ai
INSTANTLY_SEQ_MACHINERY_VP_OPS=<id>
INSTANTLY_SEQ_MACHINERY_PLANT_MGMT=<id>
INSTANTLY_SEQ_AUTO_VP_OPS=<id>
INSTANTLY_SEQ_CHEMICALS_VP_OPS=<id>
```

---

## 3-Phase Sequencing Status
- **Phase 1** (Discovery → Research → Qualify → Enrich): ✅ Complete
- **Phase 2** (Webhook reply ingestion → re-sequence): ✅ Built, campaign_threads migration pending
- **Phase 3** (HITL classification + send confirmation): ✅ Backend logic built, UI being built by background agent
- **Gap**: Engagement agent still routes to a single Instantly campaign. Needs per-cluster routing + auto-provisioning.

---

## Cost Summary (April 1, 2026)
| Item | Amount |
|------|--------|
| Anthropic API (today total) | ~$44.12 |
| Lost to cap kill (unrecoverable) | $33.01 |
| Committed to DB (completed runs) | $11.11 |
| Research today (post-cap-fix) | $2.34 |
| Remaining Anthropic balance | ~$5.88 |
| Research cap resets | May 1, 2026 |
