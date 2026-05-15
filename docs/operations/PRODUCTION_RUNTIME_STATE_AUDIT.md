# Production Runtime State Audit
## ProspectIQ — Phase 1: Production Truth Establishment

**Audit date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** COMPLETE — findings require action before migration execution  
**Scope:** Snapshot of production Railway deployment state as of this date

---

## 1. Production Service Identity

| Field | Value |
|-------|-------|
| Production URL | `https://prospectiq-production-4848.up.railway.app` |
| Staging URL | `https://prospectiq-staging.up.railway.app` |
| Health status (production) | `{"status":"ok","service":"prospectiq-api"}` |
| Health status (staging) | `{"status":"ok","service":"prospectiq-api"}` |
| Startup entrypoint | `uvicorn backend.app.api.main:app` (Procfile) |
| Process type | Single Railway web service |

### Commit SHA on Production

**Status: NOT DETERMINABLE via API or CLI.**

- `deploy-production.yml` workflow has **zero recorded GitHub Actions runs**
- No `/version` or `/info` endpoint exposes a commit SHA
- Railway CLI is linked to staging environment; cannot query production deployment state
- No `GIT_COMMIT` or `COMMIT_SHA` environment variable is set in the production service

**Conclusion:** Production was deployed via Railway dashboard auto-deploy or manual `railway up` — not via `deploy-production.yml`. The exact commit SHA running on production is unverified.

**Observable evidence that PR G code is present on production:**
- `/api/admin/send-config` returns `env_send_enabled` and `db_send_config` fields (added in PR G diagnostics)
- `/api/admin/send-trace` endpoint is functional (added in PR G diagnostic suite)
- `dispatch_loop` and `reclaim_stale_locks` are registered as scheduler jobs in `main.py` (main branch, includes PR G)
- `approved_unsent: 51` from API matches production DB query result exactly

**Recommended action:** Verify exact commit SHA via Railway dashboard → Deployments tab for the production service before applying any migration.

---

## 2. Environment Variable State — CRITICAL FINDING

### Production Railway Environment

| Variable | Value | Risk |
|----------|-------|------|
| `SEND_ENABLED` | **`true`** | **CRITICAL — env-level guard is disabled** |
| `RESEND_API_KEY` | Set (prefix `re_cM3o5...`) | Active API key present |
| `SUPABASE_SERVICE_KEY` | Set (anon_or_other role) | Service key present |
| `SEND_WINDOW_START` | `13` | 1 PM (timezone TBD) |
| `SEND_WINDOW_END` | `16` | 4 PM (timezone TBD) |

### Staging Railway Environment

| Variable | Value | Status |
|----------|-------|--------|
| `SEND_ENABLED` | `false` | Correctly set |
| `RESEND_API_KEY` | Set (prefix `re_ZeW8z...`) | Different key from production |
| `SUPABASE_SERVICE_KEY` | Set | Present |

### CRITICAL: SEND_ENABLED Gap

**Production has `SEND_ENABLED=true` in its Railway environment.** The env-level guard in `_send_approved_workspace()` and `_dispatch_workspace()` both check `get_settings().send_enabled` (which reads this env var). On production this check **PASSES** — it does not return early.

The only things currently preventing live sends on production are:

1. **Legacy `send_approved` path:** `EngagementAgent.run()` has a second check at line 372: `if not send_cfg.get("send_enabled", True)` which reads `outreach_send_config.send_enabled` from the DB. The DB value is `false`. This is the sole blocking gate for the legacy path.

2. **Dispatch `dispatch_loop` path:** `dispatch_workspace()` calls `claim_outbound_queue_batch()` RPC. This function does not exist on production (migration 054 not applied). Every scheduler tick fails silently with a PostgREST error.

**Required action before any migration is applied to production:**
Set `SEND_ENABLED=false` in the Railway production environment via the Railway dashboard. This closes the env-level gap and provides defense in depth.

---

## 3. Database Migration Watermark

### Production Supabase (ref: wlyhbdmjhgvovigogdco)

| Migration | Status |
|-----------|--------|
| 001–049 | **APPLIED** |
| 050_workflow_events | **NOT APPLIED** |
| 051_provider_events | **NOT APPLIED** |
| 052_policy_snapshots_and_context_packets | **NOT APPLIED** |
| 053_draft_hardening_trigger_unique | **NOT APPLIED** |
| 054_outbound_queue_send_attempts | **NOT APPLIED** |
| 055_dispatch_schema | **NOT APPLIED** |

**Consequence:** Tables `outbound_queue` and `send_attempts` do not exist. Function `claim_outbound_queue_batch()` does not exist. Enum value `dispatch_failed` has not been added. Column `outreach_send_config.max_retries` has not been added.

### Staging Supabase

| Migration | Status |
|-----------|--------|
| 001–055 | **APPLIED** |

Migration 055 was applied as part of the PR G staging validation workflow run (PR #111 → #113).

---

## 4. Database Send State

### Production

| Metric | Value | Source |
|--------|-------|--------|
| `outreach_send_config.send_enabled` | `false` | DB (applied migration 029) |
| `outreach_send_config.daily_limit` | `500` | DB |
| `outreach_send_config.batch_size` | `50` | DB |
| `outreach_send_config.min_gap_minutes` | `0` | DB |
| `outbound_queue` row count | N/A | Table does not exist |
| `send_attempts` row count | N/A | Table does not exist |
| Approved drafts (sent_at IS NULL) | **51** | `outreach_drafts` query |
| Drafts sent today | `0` | `outreach_drafts.sent_at` |
| `approval_status` enum values | pending, approved, rejected, edited, pending_second_review | `dispatch_failed` NOT present |

### Production Draft Inventory (from send-trace)

Sample of approved, unsent drafts visible to the legacy send path:

| Draft ID | Company | Status |
|----------|---------|--------|
| `dc2832a8` | Ulbrich Stainless Steels & Special Metals | `locked` (contact reached 3d ago) |
| `ead28407` | Aluminum Precision Products | `locked` (contact reached 4d ago) |
| `12be759c` | ERMCO-ECI | **`would_send: true`** — not suppressed, not locked |

The ERMCO-ECI draft would be dispatched immediately if the DB `send_enabled` were set to true or if the EngagementAgent's DB check were bypassed.

### Staging

| Metric | Value |
|--------|-------|
| `outreach_send_config.send_enabled` | `false` |
| `outreach_send_config.daily_limit` | `30` |
| `outreach_send_config.batch_size` | `10` |
| Approved drafts (sent_at IS NULL) | `0` |
| `outbound_queue` row count | `0` |

---

## 5. Scheduler Job Registration

The current `main.py` (main branch, includes PR G) registers the following jobs at startup:

| Job ID | Type | Schedule | PR |
|--------|------|----------|----|
| `health_snapshot` | interval | 15 min | pre-G |
| `pipeline_qc` | interval | 15 min (+45s offset) | pre-G |
| `send_approved` | cron | Mon-Fri 8–11 AM CT :00 :30 | pre-G (legacy) |
| `dispatch_loop` | cron | Mon-Fri 8–11 AM CT :00 :30 | **PR G** |
| `reclaim_stale_locks` | interval | 2 min | **PR G** |
| `process_due` | interval | 1 hr | pre-G |
| `poll_instantly` | interval | 6 hr | pre-G |
| `hitl_snoozed` | interval | 15 min | pre-G |
| `hitl_auto_archive` | interval | 1 hr | pre-G |
| `personalization_refresh` | interval | 24 hr | pre-G |
| `jit_pregenerate` | interval | 24 hr | pre-G |
| `gmail_intake` | interval | 15 min (+90s offset) | pre-G |
| `qualification` | interval | 15 min (+30s offset) | pre-G |
| `draft_generation` | interval | 5 min | pre-G |

**Paused/commented-out jobs:** research, enrichment, pipeline_monitor_email, auto_approve, pipeline_advance_heartbeat.

**PR G jobs running on production right now:**
- `dispatch_loop`: runs at each cron tick, `send_enabled=true` (env) passes, calls `dispatch_workspace()`, fails silently because `outbound_queue` doesn't exist. No sends. No error surfaced to user.
- `reclaim_stale_locks`: runs every 2 min, calls `reclaim_stale_locks(db_client, ws_id)`, fails silently because `outbound_queue` doesn't exist.

Both jobs are producing silent PostgREST errors on every tick. These errors are swallowed by the `except Exception as exc: logger.error(...)` blocks in `_run_dispatch_loop` and `_run_reclaim_stale_locks`. Sentry may be capturing them if DSN is set.

---

## 6. Deploy History and Release Mechanism

| Mechanism | Status |
|-----------|--------|
| `deploy-production.yml` (workflow_dispatch) | **Zero recorded runs** — never triggered |
| Railway dashboard auto-deploy | Unknown — cannot verify without dashboard access |
| Manual `railway up` from local CLI | Possible — no audit trail in GitHub |

**Gap:** There is no verified production deployment record. The `deploy-production.yml` workflow is the designated production deploy gate, but it has never been used. Production must have been deployed via Railway's direct integration at some point.

**Required action:** Establish `deploy-production.yml` as the exclusive production deploy path going forward. Every deployment must produce a GitHub Actions run record with SHA, timestamp, and actor.

---

## 7. Send Gate Assessment — Current State

The table below documents every active gate and its current state on production:

| Gate | Location | Value | Blocks sends? |
|------|----------|-------|---------------|
| `SEND_ENABLED` env var | Railway production env | `true` | **NO — gate OPEN** |
| `outreach_send_config.send_enabled` | DB (migration 029) | `false` | YES (legacy path only) |
| `outbound_queue` table existence | DB (migration 054) | Not created | YES (dispatch path only) |
| `claim_outbound_queue_batch()` existence | DB (migration 055) | Not created | YES (dispatch path only) |
| `outbound_queue` row count | N/A | 0 rows (table absent) | YES (dispatch path only) |
| Daily limit remaining | DB | 500 (sent_today=0) | NO |
| Resend API key | Railway env | Set | NO |

**Summary:** Sends are blocked by a combination of DB-level flag and missing schema — NOT by the env-level gate. The env-level gate is open. This is an unsafe configuration.

---

## 8. Send Activation Risk Chain

If migrations 050–055 are applied to production **without first setting `SEND_ENABLED=false` in Railway env:**

| Step | Event | Outcome |
|------|-------|---------|
| 1 | Migration 054 applied | `outbound_queue` and `send_attempts` tables created, empty |
| 2 | Migration 055 applied | `claim_outbound_queue_batch()` function created |
| 3 | `dispatch_loop` next tick | `SEND_ENABLED=true` (env) passes; `claim_outbound_queue_batch()` returns 0 rows; no sends |
| 4 | Backfill script run | 51 rows inserted into `outbound_queue` |
| 5 | `dispatch_loop` next tick (Mon-Fri 8–11 AM CT) | **51 messages dispatched; sends go out** |
| 6 | Legacy `send_approved` tick | DB `send_enabled=false` still blocks; no sends via legacy path |

The risk is narrow but real: if backfill runs before SEND_ENABLED is corrected in the Railway env, and a cron tick fires before the DB flag is changed, sends go out unintentionally.

**Correct sequence:**
1. Set `SEND_ENABLED=false` in Railway production env **first**
2. Apply migrations 050–055 sequentially
3. Verify schema
4. Run backfill dry-run; review with Avanish
5. Only then: coordinate explicit activation (DB + env) with Avanish approval

---

## 9. Parity Delta: Production vs Staging

| Dimension | Production | Staging | Delta |
|-----------|-----------|---------|-------|
| Migration watermark | 049 | 055 | 6 unapplied migrations on prod |
| `SEND_ENABLED` env | `true` | `false` | **INVERTED — production more permissive** |
| `send_config.send_enabled` | `false` | `false` | Same |
| `outbound_queue` table | Absent | Present | 6 migrations behind |
| Approved unsent drafts | 51 | 0 | Prod has live backfill candidates |
| PR G scheduler jobs | Registered (failing silently) | Registered | Same code, different schema |
| Resend API key | `re_cM3o5...` (production key) | `re_ZeW8z...` (staging key) | Correctly separate |

---

## 10. Immediate Required Actions (Priority Order)

These actions must be taken by Avanish before any production migration is applied:

### P0 — Must complete before any migration

**Action 1: Set `SEND_ENABLED=false` in Railway production environment**
- Where: Railway dashboard → ProspectIQ project → production environment → Variables tab
- Set: `SEND_ENABLED` = `false`
- Verify: `curl https://prospectiq-production-4848.up.railway.app/api/admin/send-config` → `env_send_enabled` should be `false`
- Risk if skipped: Applying migration 054 + running backfill triggers unintended sends on next cron tick

**Action 2: Verify exact production commit SHA via Railway dashboard**
- Where: Railway dashboard → ProspectIQ project → production service → Deployments tab
- Record: commit SHA, deploy timestamp, source
- This confirms whether PR G code is definitively deployed or whether production is on an older commit

### P1 — Before migrations proceed

**Action 3: Establish deploy-production.yml as the exclusive production deploy gate**
- All future production deployments must go through `deploy-production.yml`
- Document the current deployment mechanism and disable direct Railway auto-deploy from main (if configured)

**Action 4: Suppress or monitor scheduler errors**
- `dispatch_loop` and `reclaim_stale_locks` are failing silently on every tick
- Add Sentry DSN check and alert to surface these failures, or apply migration 054 to eliminate the failure condition

---

## 11. Audit Evidence Log

All findings in this document are based on direct API queries against the live production service and git repository analysis conducted on 2026-05-15.

| Evidence | Source | Value |
|----------|--------|-------|
| Health endpoint response | `curl .../health` | `{"status":"ok","service":"prospectiq-api"}` |
| `env_send_enabled` | `/api/admin/send-config` | `true` |
| `db_send_config.send_enabled` | `/api/admin/send-config` | `false` |
| `approved_unsent` | `/api/admin/send-config` | `51` |
| `sent_today` | `/api/admin/send-config` | `0` |
| ERMCO-ECI `would_send: true` | `/api/admin/send-trace` | Confirmed |
| Migration 054 not applied | Production DB psql query | `outbound_queue` not in pg_tables |
| Migration 055 not applied | Production DB psql query | `claim_outbound_queue_batch` not in pg_proc |
| `approval_status` enum | Production DB psql query | `dispatch_failed` not present |
| `deploy-production.yml` run history | `gh run list` | Zero runs |
| Railway CLI environment | `railway status` | Linked to staging |
| PR G jobs in main.py | Code review | `dispatch_loop`, `reclaim_stale_locks` registered |

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/PRODUCTION_RUNTIME_STATE_AUDIT.md`  
**Next document:** `docs/operations/PRODUCTION_CONVERGENCE_RUNBOOK.md` (Phase 2)
