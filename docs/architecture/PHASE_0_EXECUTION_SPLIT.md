# ProspectIQ Phase 0 — Execution Split

**Version 1.0 | 2026-05-14**
**Author: Avanish Mehrotra & Digitillis Architecture Team**
**Status: Planning Document | No Implementation Yet**
**Reference**: docs/architecture/PHASE_0_STAGING_SETUP_PLAN.md

---

## Overview

Phase 0 is split into two discrete work units that can be partially parallelized but have a clear dependency boundary.

**Phase 0-Infra** — Console and dashboard work only. Zero repo changes. Performed by Avanish directly in Supabase, Railway, and Resend dashboards, plus psql commands against the production and staging databases. Can begin as soon as the Shared Pre-Step is complete.

**Phase 0-Code** — All repo changes. Prepared by Claude, reviewed and merged by Avanish. Can be written before Phase 0-Infra is fully complete, but cannot be fully deployed (GitHub Actions secrets step) until Phase 0-Infra credentials are collected.

**Shared Pre-Step** — Must complete before Phase 0-Infra Step 4 (migration application) and before Phase 0-Code produces `scripts/MIGRATION_ORDER.txt`. Takes approximately 15 minutes. Performed by Avanish at the production DB psql prompt.

---

## Dependency Boundary

```
Shared Pre-Step
(production DB query, ~15 min)
       |
       |-----> Phase 0-Infra  (console work, can begin immediately after)
       |              |
       |              | credentials collected
       |              v
       |-----> Phase 0-Code  (repo work, can be written in parallel;
                              secrets step requires Infra credentials)
```

Phase 0-Code does NOT need to wait for Phase 0-Infra to complete before being written. The branch can be opened and developed while Phase 0-Infra is in progress. The only Phase 0-Code step that requires Phase 0-Infra completion is: adding `STAGING_URL` and `STAGING_DATABASE_URL` as GitHub Actions secrets (Step C-3-f).

---

## Shared Pre-Step: Determine Migration Application Order

**Who**: Avanish (psql CLI against production DB)
**Repo changes**: None
**Time estimate**: 15 minutes
**Output**: A temporary note (text file, Notion page, or written note) that documents the correct application order for all 55 migrations — particularly the 5 conflicting files. This note is later formalized into `scripts/MIGRATION_ORDER.txt` in Phase 0-Code.

### Why This Is Needed

The `supabase_migrations/migrations/` directory has 55 files with duplicate numbers. The production DB has no `supabase_migrations.schema_migrations` tracking table (confirmed — migrations were applied manually via psql). The order must be determined from file content dependencies before applying to staging.

**Confirmed duplicates:**

| Filename | Header description |
|---|---|
| `002_apollo_extended_fields.sql` | ALTERs `companies` table — adds sic_codes, naics_codes, etc. |
| `002_improvements.sql` | Adds enrichment lifecycle states, completeness scoring, apollo_id |
| `003_contact_events.sql` | Creates `contact_events` table with FK to `contacts` |
| `003_dnc_priority_queue.sql` | Creates `do_not_contact` table, adds `priority_score` to contacts |
| `019_campaign_threads_hitl.sql` | Campaign Thread + HITL Queue System |
| `019_sequence_builder_v2.sql` | Creates `campaign_sequence_definitions_v2` table |
| `020_sequence_builder_v2.sql` | Header says "Migration 019" — same table name as 019_sequence_builder_v2 |

The `020_sequence_builder_v2.sql` file header reads "Migration 019: Visual Sequence Builder V2" and creates `campaign_sequence_definitions_v2` — the same table as `019_sequence_builder_v2.sql`. This is likely a revised version of the same migration that was renamed. One of them may be a no-op on a live DB (IF NOT EXISTS guard) or one of them extends the table defined by the other.

### Steps

```
PRE-1: Confirm no migration tracking table exists in production:
       psql "[PRODUCTION_DATABASE_URL]" -c \
         "SELECT * FROM supabase_migrations.schema_migrations LIMIT 1;"
       Expected result: ERROR: relation does not exist
       (Confirmed already — no tracking table)

PRE-2: Verify IF NOT EXISTS guards on the duplicate files.
       For each of the 7 conflicting files, check the first CREATE statement:

       grep -n "CREATE TABLE" supabase_migrations/migrations/002_apollo_extended_fields.sql
       grep -n "CREATE TABLE" supabase_migrations/migrations/002_improvements.sql
       grep -n "CREATE TABLE" supabase_migrations/migrations/003_contact_events.sql
       grep -n "CREATE TABLE" supabase_migrations/migrations/003_dnc_priority_queue.sql
       grep -n "CREATE TABLE" supabase_migrations/migrations/019_campaign_threads_hitl.sql
       grep -n "CREATE TABLE" supabase_migrations/migrations/019_sequence_builder_v2.sql
       grep -n "CREATE TABLE" supabase_migrations/migrations/020_sequence_builder_v2.sql

       Record: does each CREATE use IF NOT EXISTS?
       If any CREATE does NOT use IF NOT EXISTS, the order is strictly constrained
       for that file (it must come before any other migration that touches the
       same table, and it cannot be re-applied).

PRE-3: For 019_sequence_builder_v2.sql and 020_sequence_builder_v2.sql specifically:
       diff supabase_migrations/migrations/019_sequence_builder_v2.sql \
            supabase_migrations/migrations/020_sequence_builder_v2.sql

       If they are identical: only one needs to be applied. Apply 019, skip 020.
       If 020 extends 019 (adds columns to the table created in 019): apply 019 first, then 020.
       If 020 is a replacement (different schema): apply 020 only, skip 019.
       Document the decision.

PRE-4: Check whether any duplicate-numbered file references a table created in
       its sibling file (cross-dependency within the same number group):

       For 002: does 002_improvements.sql ALTER any table created ONLY in
                002_apollo_extended_fields.sql (not in 001)?
                grep -i "ALTER TABLE" supabase_migrations/migrations/002_improvements.sql

       For 003: does 003_dnc_priority_queue.sql reference contact_events (from 003_contact_events)?
                grep -i "contact_events\|REFERENCES" supabase_migrations/migrations/003_dnc_priority_queue.sql

       For 019: does 019_sequence_builder_v2.sql reference any table from 019_campaign_threads_hitl?
                grep -i "REFERENCES\|threads\|hitl" supabase_migrations/migrations/019_sequence_builder_v2.sql

PRE-5: Based on the above analysis, establish the safe application order.
       Conservative default (use this unless analysis shows a cross-dependency):
       - Within each number group: apply alphabetically
         002_apollo_extended_fields.sql THEN 002_improvements.sql
         003_contact_events.sql THEN 003_dnc_priority_queue.sql
         019_campaign_threads_hitl.sql THEN 019_sequence_builder_v2.sql
       - For 020: apply if and only if it extends 019_sequence_builder_v2
                  (adds columns or constraints). Skip if identical or replaced by 019.

PRE-6: Write the determined order as a temporary note.
       Format: numbered list of all 55 files (or 54 if 020 is skipped)
       in exact application order.
       This note becomes scripts/MIGRATION_ORDER.txt in Phase 0-Code.

PRE-7: Verify the final count of files to be applied against staging.
       ls supabase_migrations/migrations/ | wc -l  --> should be 55
       Total to apply on staging: 54 or 55 (depending on PRE-3 decision).
```

**Pre-Step no-go conditions:**
- Any CREATE TABLE statement without IF NOT EXISTS that is one of the conflicting files → must resolve the exact order constraint for that file before proceeding to Phase 0-Infra Step 4
- The 019/020 diff shows a complex schema conflict that cannot be resolved by "apply both in order" → stop and escalate to Avanish before proceeding

---

## Phase 0-Infra Work Unit

**Who performs all steps**: Avanish (console actions, psql CLI)
**Repo changes**: None
**Duration estimate**: 2–4 hours total (mostly waiting for Supabase provisioning and Railway deploys)
**Prerequisite**: Shared Pre-Step complete

---

### Section I-1: Supabase Staging Project Creation

**Where**: supabase.com dashboard

```
[ ] I-1-1  Log in to supabase.com as project owner.

[ ] I-1-2  Click "New project". Configure:
           Organization:      same org as the production project
           Project name:      prospectiq-staging
           Database password: generate a strong unique password
                              STORE IMMEDIATELY in password manager
                              label: "ProspectIQ Supabase staging DB password"
           Region:            Canada (Central) — same as production

[ ] I-1-3  Wait for project provisioning. Typically 60–120 seconds.
           Do not close the browser tab during provisioning.

[ ] I-1-4  Once provisioned, navigate to Settings > API.
           Collect and store in password manager:
           - Project URL:       STAGING_SUPABASE_URL
             Format: https://[ref].supabase.co
             Verify: the [ref] is NOT wlyhbdmjhgvovigogdco (that is production)
           - anon/public key:   STAGING_SUPABASE_KEY
           - service_role key:  STAGING_SUPABASE_SERVICE_KEY

[ ] I-1-5  Navigate to Settings > Database > Connection string.
           Select: Transaction (pgBouncer) mode, port 5432.
           Collect and store:
           - STAGING_DATABASE_URL
             Format: postgresql://postgres.[ref]:[password]@aws-0-ca-central-1.pooler.supabase.com:5432/postgres
             Verify: the [ref] must differ from wlyhbdmjhgvovigogdco

[ ] I-1-6  Safety check: verify the staging project reference is distinct from production.
           Production ref: wlyhbdmjhgvovigogdco
           Staging ref: [newly created — must differ]
           STOP if they match. They cannot match. This would indicate a configuration error.
```

---

### Section I-2: Disable Dangerous Supabase Features in Staging

**Where**: Supabase staging project dashboard

```
[ ] I-2-1  Navigate to Authentication > Providers.
           Disable all OAuth providers (Google, GitHub, etc.).
           These are not needed in staging and could create real OAuth sessions.

[ ] I-2-2  Navigate to Authentication > Email.
           Disable "Confirm email" if enabled.
           Staging users (test/synthetic) should not trigger real email confirmations.

[ ] I-2-3  Navigate to Database > Replication.
           Confirm: no logical replication is set up.
           Confirm: no connection to the production project exists.
```

---

### Section I-3: Apply All Migrations to Staging

**Where**: Local terminal (psql)
**Requires**: STAGING_DATABASE_URL from I-1-5, migration order from Shared Pre-Step

This is the most time-consuming step. All 54 or 55 migration files are applied in the order determined in the Shared Pre-Step.

```
[ ] I-3-1  Test connectivity:
           psql "[STAGING_DATABASE_URL]" -c "SELECT current_database(), version();"
           Expected: postgres, PostgreSQL 15.x or 16.x
           If connection fails: check the DATABASE_URL format and password encoding.
           The password may contain special characters — URL-encode them if psql rejects.

[ ] I-3-2  Apply migrations in the documented order.
           For each file (in the order from the Shared Pre-Step temporary note):

           psql "[STAGING_DATABASE_URL]" -f "supabase_migrations/migrations/[filename].sql" \
             2>&1 | tee /tmp/migration_[filename].log

           Check the log after each file:
           - "CREATE TABLE", "ALTER TABLE", "CREATE INDEX", "CREATE FUNCTION",
             "CREATE TRIGGER" → success
           - "already exists" with IF NOT EXISTS → acceptable (idempotent)
           - "ERROR:" → STOP. Do not apply the next migration until the error is resolved.

           Do NOT skip migrations. Do NOT continue past an ERROR.

[ ] I-3-3  After all files apply, run the post-migration verification:
           psql "[STAGING_DATABASE_URL]" <<SQL
           SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public'
           ORDER BY table_name;
           SQL
           Record the output. Verify these tables are present:
           outreach_drafts, contacts, companies, suppression_rules,
           outreach_send_config, workflow_events, provider_events,
           policy_snapshots, context_packets

[ ] I-3-4  Verify migration 053 objects specifically:
           psql "[STAGING_DATABASE_URL]" <<SQL
           SELECT routine_name FROM information_schema.routines
           WHERE routine_schema = 'public'
           AND routine_name = 'enforce_draft_immutability';

           SELECT trigger_name, event_manipulation, action_timing
           FROM information_schema.triggers
           WHERE event_object_table = 'outreach_drafts'
           ORDER BY trigger_name;

           SELECT indexname, indexdef FROM pg_indexes
           WHERE tablename = 'outreach_drafts'
           AND indexname = 'idx_outreach_drafts_active_unique';
           SQL
           Expected: function exists, trg_draft_immutability is BEFORE UPDATE,
           index exists with predicate approval_status <> 'rejected'::approval_status

[ ] I-3-5  Insert the outreach_send_config safety row:
           psql "[STAGING_DATABASE_URL]" <<SQL
           INSERT INTO outreach_send_config (send_enabled)
           VALUES (false)
           ON CONFLICT DO NOTHING;
           SQL
           Verify: SELECT send_enabled FROM outreach_send_config;
           Expected: f

[ ] I-3-6  Record the final table count:
           psql "[STAGING_DATABASE_URL]" -c \
             "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
           Save this number. It will be used to verify staging/production schema parity
           in smoke tests.
```

**Section I-3 no-go conditions:**
- Any `ERROR:` during migration application that is not an "already exists" notice on an IF NOT EXISTS statement
- Missing any of the 9 required tables after full migration run
- `idx_outreach_drafts_active_unique` exists but with the old `::text` cast predicate (means the 053 file on disk is not the corrected version)
- `send_enabled` is anything other than `f` after Step I-3-5

---

### Section I-4: Railway Staging Environment Creation

**Where**: railway.app dashboard
**Requires**: All 4 staging Supabase credentials from I-1

```
[ ] I-4-1  Log in to railway.app. Navigate to the ProspectIQ project.

[ ] I-4-2  In the project, locate the current environment (named "production").
           Note: this environment currently auto-deploys from the main branch.

[ ] I-4-3  CRITICAL — Disable production auto-deploy BEFORE creating staging.
           Reason: once staging is created with auto-deploy from main, any push
           to main triggers staging. Production must NOT also auto-deploy from main.
           Without this step, Phase 2 schema changes in PRs could deploy to production
           before they are validated.

           Production environment > Settings > Source > GitHub integration:
           - Set "Deploy on push" to OFF (or configure to require manual deploy)
           - Confirm change is saved

           Verify: after saving, the production environment shows "Manual deploys only"
           or equivalent.

[ ] I-4-4  Create the staging environment:
           Click "New Environment" (or equivalent in Railway UI)
           Name: staging
           Source: same GitHub repository, main branch, auto-deploy ON

[ ] I-4-5  Verify the two-environment state:
           - staging: auto-deploys on push to main ✓
           - production: manual deploy only ✓
```

---

### Section I-5: Configure Staging Environment Variables

**Where**: Railway dashboard > staging environment > Variables
**Reference**: The complete env var table from PHASE_0_STAGING_SETUP_PLAN.md Section B-2

Apply each variable in the Railway staging environment Variables tab. Do NOT copy production variables wholesale — every variable must be set deliberately.

```
CORE DB (staging-specific — use values collected in I-1):
[ ] I-5-1   SUPABASE_URL          = https://[staging-ref].supabase.co
[ ] I-5-2   SUPABASE_KEY          = [staging anon key]
[ ] I-5-3   SUPABASE_SERVICE_KEY  = [staging service role key]
[ ] I-5-4   DATABASE_URL          = [staging transaction pooler URL]

SAFETY GUARDS (must be set exactly as shown):
[ ] I-5-5   SEND_ENABLED          = false
[ ] I-5-6   LEARNING_AUTO_APPLY   = false
[ ] I-5-7   ENVIRONMENT           = staging
            Note: also add ENVIRONMENT=production to the production environment
            variables at the same time (same dashboard session — do not forget this).

SENDING IDENTITY (staging-specific):
[ ] I-5-8   FROM_EMAIL            = ProspectIQ Staging <staging@digitillis.io>
            If staging@digitillis.io does not exist: use avanish+staging@digitillis.io
            or any address clearly marked as non-production.
[ ] I-5-9   RESEND_API_KEY        = [staging Resend API key — set after Section I-6]
            Leave as placeholder until I-6 is complete.

EXTERNAL SERVICES — DISABLED:
[ ] I-5-10  INSTANTLY_API_KEY          = (set to empty string "")
[ ] I-5-11  INSTANTLY_WEBHOOK_SECRET   = (empty string)
[ ] I-5-12  INSTANTLY_SEQ_MFG_VP_OPS   = (empty string)
[ ] I-5-13  INSTANTLY_SEQ_MFG_MAINTENANCE = (empty string)
[ ] I-5-14  INSTANTLY_SEQ_MFG_PLANT_MANAGER = (empty string)
[ ] I-5-15  INSTANTLY_SEQ_MFG_DIRECTOR_OPS = (empty string)
[ ] I-5-16  INSTANTLY_SEQ_MFG_GENERAL  = (empty string)
[ ] I-5-17  INSTANTLY_SEQ_FB_VP_OPS    = (empty string)
[ ] I-5-18  INSTANTLY_SEQ_FB_PLANT_MANAGER = (empty string)
[ ] I-5-19  INSTANTLY_SEQ_FB_VP_QUALITY = (empty string)
[ ] I-5-20  INSTANTLY_SEQ_FB_DIR_QUALITY = (empty string)
[ ] I-5-21  GMAIL_USER             = (empty string)
[ ] I-5-22  GMAIL_APP_PASSWORD     = (empty string)

EXTERNAL SERVICES — REAL KEYS (acceptable; no autonomous loops in Phase 0):
[ ] I-5-23  ANTHROPIC_API_KEY      = [same as production]
[ ] I-5-24  APOLLO_API_KEY         = [same as production]
[ ] I-5-25  PERPLEXITY_API_KEY     = [same as production]

OPERATIONAL CONFIG:
[ ] I-5-26  SEND_WINDOW_START      = 09:00
[ ] I-5-27  SEND_WINDOW_END        = 17:00
[ ] I-5-28  DAILY_SEND_LIMIT       = 10
[ ] I-5-29  BATCH_SIZE             = 5
[ ] I-5-30  LOG_LEVEL              = DEBUG
[ ] I-5-31  WEBHOOK_SECRET         = [generate a new random string — different from production]

POST I-5: Double-check production environment variables.
[ ] I-5-32  In production Railway environment > Variables:
            Add ENVIRONMENT = production
            Verify SEND_ENABLED = false (it should already be set from previous sessions)
            Verify DATABASE_URL still points to wlyhbdmjhgvovigogdco
```

---

### Section I-6: Resend Staging Key

**Where**: resend.com dashboard

```
[ ] I-6-1  Log in to resend.com.

[ ] I-6-2  Navigate to API Keys. Create a new key:
           Name: prospectiq-staging
           Permission: Full access (or Sending access if available)

[ ] I-6-3  Copy the key immediately — it is shown only once.
           Store in password manager: label "ProspectIQ Resend staging API key"

[ ] I-6-4  Return to Railway staging environment Variables.
           Set RESEND_API_KEY = [new staging key] (replacing the placeholder from I-5-9).

[ ] I-6-5  Verify the two Resend keys differ:
           Production RESEND_API_KEY in Railway: begins with re_...
           Staging RESEND_API_KEY in Railway: begins with re_...
           They must be different values. If the same: stop and regenerate.

[ ] I-6-6  Sending domain for staging:
           Option A (preferred): add and verify a staging subdomain in Resend
                  (e.g., staging.digitillis.io) for the staging key.
                  This requires a DNS record addition.
           Option B (acceptable for Phase 0 if DNS change is not available now):
                  Use the same verified domain as production but confirm that
                  SEND_ENABLED=false in staging prevents any actual sends.
                  Document: "Staging Resend domain isolation deferred — SEND_ENABLED=false
                  is the primary guard. DNS staging subdomain to be added before Phase 2 PR G."

[ ] I-6-7  Document which option was chosen for I-6-6.
           If Option B: add "Add staging.digitillis.io DNS record for Resend" to
           the Phase 2 PR G prerequisite checklist.
```

---

### Section I-7: Trigger First Staging Deploy and Verify

**Where**: GitHub (push) and Railway dashboard (monitor)

```
[ ] I-7-1  Push a trivial commit to the main branch to trigger the first staging deploy.
           The commit can be: updating the ENVIRONMENT variable comment in PHASE_0_STAGING_SETUP_PLAN.md
           or adding a blank line. Something that cannot break anything.
           This commit does NOT need a PR — it is an infra verification commit.

           Caution: verify production auto-deploy is OFF before pushing (Step I-4-3).
           If I-4-3 was not completed, do NOT push until it is.

[ ] I-7-2  Monitor Railway staging environment deployment.
           Expected: deployment completes within 3–5 minutes.
           The startup command is:
           pip install -r backend/requirements.txt && uvicorn backend.app.api.main:app ...
           Watch for any startup errors in Railway deploy logs.

[ ] I-7-3  Verify staging health:
           curl -s -o /dev/null -w "%{http_code}" https://[STAGING_RAILWAY_URL]/health
           Expected: 200
           If 404: find the actual health check route in backend/app/api/main.py

[ ] I-7-4  Verify staging uses staging DB (not production):
           psql "[STAGING_DATABASE_URL]" -c "SELECT count(*) FROM contacts;"
           Expected: 0 (no seed data yet)
           This count must differ from production (9,946 contacts).
           A count of 9,946 on staging means the staging DATABASE_URL is pointing at production. STOP.

[ ] I-7-5  Verify production did not auto-deploy:
           In Railway production environment: check the deployment timestamp.
           The most recent production deployment timestamp should be older than the push in I-7-1.
           If production shows a new deployment triggered by the push: I-4-3 did not take effect.
           Immediately investigate and disable production auto-deploy before any further pushes.

[ ] I-7-6  Verify ENVIRONMENT variable is staging:
           If the application exposes an info/version endpoint, confirm ENVIRONMENT=staging.
           If not: this check is deferred to Phase 0-Code (the app may not expose it yet).

[ ] I-7-7  Verify Instantly graceful handling:
           Check Railway staging deployment logs for any error or warning related to
           INSTANTLY_API_KEY being empty.
           Acceptable: "Instantly not configured — skipping" or similar warning.
           Not acceptable: unhandled exception, crash, or 500 on startup.
           If crash: Phase 0-Code must add graceful handling before Phase 0-Infra is complete.

[ ] I-7-8  Verify Gmail graceful handling:
           Same as I-7-7 but for GMAIL_USER / GMAIL_APP_PASSWORD being empty.
```

---

### Section I-8: Phase 0-Infra Acceptance Criteria

Phase 0-Infra is complete when all of the following are true. IA-1 through IA-14
are infrastructure establishment criteria. IA-15 through IA-18 are hard gates
that must pass before Phase 2 (PR F) is authorized. IA-19 and IA-20 confirm clean
application startup.

```
[ ] IA-1   Staging Supabase project exists, reachable via psql, distinct from production.
[ ] IA-2   All migrations applied without errors. Key tables confirmed present.
[ ] IA-3   Migration 053 objects present with correct syntax on staging:
           enforce_draft_immutability() function, trg_draft_immutability trigger,
           idx_outreach_drafts_active_unique with approval_status <> 'rejected'::approval_status.
[ ] IA-4   outreach_send_config.send_enabled = false on staging.
[ ] IA-5   Railway staging environment exists and auto-deployed successfully.
[ ] IA-6   Railway production environment is confirmed on manual-deploy-only.
[ ] IA-7   All 31 environment variables (including ENVIRONMENT) configured in staging.
[ ] IA-8   ENVIRONMENT=production set in production Railway environment.
[ ] IA-9   SEND_ENABLED=false confirmed in staging Railway environment.
[ ] IA-10  Staging RESEND_API_KEY is different from production RESEND_API_KEY.
[ ] IA-11  All INSTANTLY_* variables are empty strings in staging.
[ ] IA-12  GMAIL_USER and GMAIL_APP_PASSWORD are empty strings in staging.
[ ] IA-13  Staging health endpoint returns 200.
[ ] IA-14  Staging contact count = 0 (pre-seed). Production contact count = 9,946.
           These must differ to confirm DB isolation.

--- PR F HARD GATES (all four required before Phase 2 authorization) ---

[ ] IA-15  Staging outbound email isolation verified.
           Steps:
             a. With SEND_ENABLED=false still in place, temporarily set it to true
                in the staging Railway environment for this test only.
             b. Trigger a test send from staging to a Resend sink address:
                delivered@resend.dev (simulates successful delivery without real delivery)
             c. Confirm Resend staging dashboard shows the send under the staging API key.
             d. Confirm Resend production dashboard shows NO corresponding activity.
             e. Confirm production contact table is unchanged (count still 9,946).
             f. Set SEND_ENABLED=false again in staging immediately after the test.
             g. Record: staging Resend message ID from the test send.
           Pass condition: test send appears only in staging Resend account; production
           metrics, logs, and contact table are completely unaffected.
           Fail condition: any staging send activity visible in production Resend account,
           or any change to production contact count.

[ ] IA-16  Representative migration replay verified.
           Steps:
             a. Select at least one migration from each conflict group that was applied
                to staging in Step I-3-2:
                - 002_improvements.sql
                - 003_contact_events.sql
                - 019_sequence_builder_v2.sql
             b. Re-apply each selected file to the staging DB a second time:
                psql "[STAGING_DATABASE_URL]" -f "supabase_migrations/migrations/[file].sql" 2>&1
             c. Inspect the output of each re-run.
           Pass condition: all three re-runs complete with zero ERROR lines; any output
           is "already exists" notices from IF NOT EXISTS guards; row counts in affected
           tables are unchanged from before the re-run.
           Fail condition: any ERROR line that is not an "already exists" notice;
           any unexpected row deletion or duplication.

[ ] IA-17  Scheduler and provider isolation verified.
           Steps:
             a. In Railway staging deployment logs, confirm the scheduler starts and
                connects to the staging DATABASE_URL (not wlyhbdmjhgvovigogdco).
                Grep logs for the staging Supabase ref to confirm.
             b. Confirm staging scheduler cannot trigger sends via production Resend:
                staging RESEND_API_KEY must differ from production — verified in IA-10.
                Confirm the staging key is active only in the staging Resend account.
             c. Confirm Instantly is inert: with all INSTANTLY_* env vars empty, attempt
                any action that would normally call the Instantly API (or confirm no such
                call is attempted in staging logs at startup or during the deploy window).
             d. Confirm Gmail IMAP polling is disabled: staging logs show a warning
                ("Gmail credentials not configured" or equivalent) rather than an
                attempt to connect to Gmail.
             e. Hypothetical containment test: mentally (not operationally) confirm that
                even if SEND_ENABLED were set to true in staging, the staging RESEND_API_KEY
                can only send via the staging Resend account — it has no access to the
                production Resend account or production contacts.
                Document this reasoning as a one-line note in the evidence record.
           Pass condition: all five sub-steps confirmed; no staging scheduler activity
           references the production DB ref or production Resend key.
           Fail condition: any log line connecting staging scheduler to production DB;
           any INSTANTLY or GMAIL connection attempt in staging logs.

[ ] IA-18  Observability stack verified.
           Steps:
             a. Railway staging logs: open the Railway staging environment > deployment logs.
                Confirm logs are visible, timestamped, and retained for the current deploy.
                Confirm you can search/filter logs. Record: log retention period displayed.
             b. Supabase staging logs: open Supabase staging dashboard > Logs > Postgres.
                Confirm query logs are visible. Run a known query against staging DB and
                confirm it appears in the logs within 60 seconds.
             c. staging-smoke-test CI job: confirm the job ran green on the most recent
                push to main that included all Phase 0-Code changes. All three checks
                (health, send_enabled, isolation) must show "OK" in the job output.
                Record: GitHub Actions run URL for the passing staging-smoke-test job.
             d. verify-staging output: run make verify-staging and save the full terminal
                output as evidence. All three checks must print "OK".
             e. Intentional failure injection: temporarily set send_enabled = true
                in staging DB via psql, then run make verify-staging.
                Expected: verify-staging prints "FAIL: send_enabled=..." and exits 1.
                Restore send_enabled = false immediately after confirming the failure.
                Record: terminal output showing the FAIL line and the subsequent fix.
           Pass condition: all five sub-steps confirmed and evidence recorded.
           Fail condition: any sub-step produces no visible output or silent pass
           (e.g., smoke test skips rather than checks); intentional failure not detected.

---

[ ] IA-19  Production deployment log shows no new deploy after the test push in I-7-1.
[ ] IA-20  Application starts cleanly in staging with empty Instantly and Gmail credentials
           (no unhandled exceptions in deployment logs).
```

#### PR F Authorization Rationale

PR F changes the system from governed CRUD execution into durable autonomous execution.
These additional gates (IA-15 through IA-18) validate isolation, replay safety, scheduler
containment, and operational observability before queue-backed execution is introduced.

Without IA-15: a bug in staging send path wiring could silently affect production
delivery metrics or real contacts before the team is aware.

Without IA-16: idempotency claims for migrations are assumed, not tested — a replay
failure on staging would predict the same failure during any future disaster-recovery
or staging-rebuild scenario.

Without IA-17: a misconfigured env var in staging (e.g., SEND_ENABLED accidentally
true) could reach production systems if provider keys are shared or scheduler
isolation is not confirmed.

Without IA-18: Phase 2 introduces background queue processing and retry loops. If
failures in those systems are not visible in logs before they are introduced, the
team is operating blind from day one of Phase 2.

### Section I-9: Phase 0-Infra Rollback Plan

Phase 0-Infra changes are reversible because no production data or behavior is changed.

```
Full rollback (revert all Phase 0-Infra work):
  [ ] Delete the staging Supabase project (supabase.com > project settings > Delete project)
      Note: Supabase has a 30-day pause before deletion is permanent. Immediate delete
      removes access. This is sufficient for rollback purposes.
  [ ] Delete the staging Railway environment (Railway dashboard > staging env > Delete)
  [ ] Re-enable production auto-deploy in Railway (production env > Settings > Source > ON)
  [ ] Delete the staging Resend API key (Resend dashboard > API Keys > Delete)
  [ ] Remove ENVIRONMENT=production from production Railway env vars (it was newly added)
      Only if this causes any issue — it is a benign variable and can be left.

Partial rollback (keep Supabase, revert Railway changes):
  [ ] If Railway staging causes issues: delete staging Railway environment only
  [ ] Re-enable production auto-deploy if it was disabled and not yet replaced with
      the manual deploy workflow from Phase 0-Code
      CRITICAL: if Phase 0-Code's deploy-production.yml has not been merged yet,
      and production auto-deploy is disabled, there is no way to deploy to production.
      Ensure deploy-production.yml is merged before permanently disabling auto-deploy.
```

### Section I-9 Rollback Pre-Condition Warning

**Do not permanently disable production auto-deploy without first confirming that `deploy-production.yml` (Phase 0-Code) is merged to main.** During the window between Step I-4-3 (auto-deploy disabled) and the merge of `deploy-production.yml`, production can only be deployed by running `railway up --environment production` manually from the CLI. Document this window explicitly. It should be short (Phase 0-Code should be merged within hours of Phase 0-Infra completion).

---

### Section I-10: Phase 0-Infra No-Go Conditions

```
NG-I-1  Staging DATABASE_URL resolves to wlyhbdmjhgvovigogdco (production).
         Verify immediately after collecting credentials in I-1-5.
         Do not proceed to any other step if this is true.

NG-I-2  Production auto-deploy is still enabled when a push to main occurs
         during Phase 0-Infra work. This would deploy schema changes (from Phase 2)
         to production prematurely.
         Step I-4-3 must be verified complete before any push to main.

NG-I-3  Any migration fails with ERROR: during I-3-2 (non-IF NOT EXISTS error).
         Do not continue to the next migration file until the error is resolved.

NG-I-4  send_enabled = true (or not present) in outreach_send_config on staging
         after Step I-3-5.

NG-I-5  Staging and production share the same RESEND_API_KEY value.

NG-I-6  The application crashes at startup in staging due to empty Instantly or Gmail
         credentials. This indicates ungraceful handling that must be fixed in Phase 0-Code
         before Phase 0-Infra can be declared complete.

NG-I-7  idx_outreach_drafts_active_unique exists on staging with the wrong predicate:
         WHERE approval_status::text != 'rejected'  (the old broken version)
         rather than: WHERE approval_status <> 'rejected'::approval_status
         This means the migration file on disk has not been updated with the fix.
         Verify with: grep "WHERE approval_status" on the 053 file before applying.
```

---

## Phase 0-Code Work Unit

**Who performs steps**: Claude prepares; Avanish reviews and merges
**Repo changes**: Yes — 6 files changed or created
**Branch name**: `infra/phase-0-staging-code`
**Single PR**: opened against main after all changes are ready
**Prerequisite**: Shared Pre-Step complete (migration order known)
**Dependency**: Can be written before Phase 0-Infra completes; GitHub secrets step (C-3-f) requires Phase 0-Infra credentials

---

### Section C-1: Resolve Migration Order and Create MIGRATION_ORDER.txt

**File**: `scripts/MIGRATION_ORDER.txt` (new file)
**Who**: Claude writes based on Shared Pre-Step findings; Avanish confirms

This file formalizes the migration application order determined in the Shared Pre-Step. It is the durable reference for anyone setting up a new DB from scratch (staging rebuild, local dev, DR recovery).

```
Content of scripts/MIGRATION_ORDER.txt:
  - One migration filename per line
  - In exact application order
  - Comments for each duplicate group explaining the resolution
  - Total file count noted at the top
  - A "SKIP" note for any file that should not be applied (e.g., if 020_sequence_builder_v2.sql
    is identical to 019_sequence_builder_v2.sql, mark it SKIP with explanation)

Example format:
  # ProspectIQ Migration Application Order
  # Total: 54 files (020_sequence_builder_v2.sql skipped — identical to 019)
  # See: docs/architecture/PHASE_0_STAGING_SETUP_PLAN.md
  # Determined: 2026-05-14 by querying production DB and inspecting file headers.
  #
  001_initial_schema.sql
  002_apollo_extended_fields.sql
  002_improvements.sql  # Applied after 002_apollo_extended_fields (alphabetical; no cross-dependency)
  003_contact_events.sql
  003_dnc_priority_queue.sql  # Applied after 003_contact_events (alphabetical; no cross-dependency)
  ...
  019_campaign_threads_hitl.sql
  019_sequence_builder_v2.sql  # Creates campaign_sequence_definitions_v2
  # 020_sequence_builder_v2.sql SKIPPED — identical to 019_sequence_builder_v2.sql
  ...
  053_draft_hardening_trigger_unique.sql
```

**Verification**:
- Manually check the file count matches Phase 0-Infra (the number applied in I-3-2)
- Confirm the file exists and is readable: `cat scripts/MIGRATION_ORDER.txt | wc -l`
- Confirm no production DATABASE_URL or credentials appear in the file

**No-go**: File contains real credentials, real email addresses, or a different count from what was applied in Phase 0-Infra.

---

### Section C-2: Fix Pre-Existing CI Test Failure

**File**: `requirements.txt` (or `.github/workflows/ci.yml`)
**Who**: Claude investigates and fixes; Avanish confirms

The CI currently fails with:
```
FAILED backend/tests/test_app_import_smoke.py::test_app_entrypoint_imports_cleanly
ImportError: email-validator is not installed, run `pip install 'pydantic[email]'`
```

This must be fixed before new CI jobs are added. A broken baseline makes it impossible to distinguish Phase 0-Code failures from pre-existing ones.

**Investigation required before writing the fix**:
```
[ ] C-2-1  Check if pydantic[email] is in requirements.txt:
           grep -i "pydantic\|email-validator" requirements.txt

[ ] C-2-2  Check what imports email-validator:
           grep -rn "EmailStr\|pydantic.*email\|email_validator" backend/ | head -20

[ ] C-2-3  Check the failing test:
           cat backend/tests/test_app_import_smoke.py
           Understand exactly what triggers the import error.
```

**Fix options** (Claude will determine which applies after C-2-1 through C-2-3):

Option A — If `pydantic[email]` is absent from `requirements.txt`:
- Add `pydantic[email]>=2.0.0` to requirements.txt
- This is the correct fix if email validation is a production dependency

Option B — If `pydantic[email]` is a dev/test-only dependency:
- Add it to a `requirements-dev.txt` (creating it if it doesn't exist)
- Update `ci.yml` test job to install `requirements-dev.txt` in addition to `requirements.txt`

Option C — If the import in the application code is optional (guarded by try/except):
- The application code may not actually need email-validator at runtime
- The test may be testing an import that doesn't need to succeed in production
- Fix: update the test to use `pytest.importorskip` or fix the application import guard

**Verification after fix**:
```
[ ] C-2-4  Run locally: pip install -r requirements.txt && pytest backend/tests/ -x -q --tb=short
           Expected: all tests pass, including test_app_import_smoke.py
[ ] C-2-5  Confirm the fix does not add a heavyweight dependency that inflates
           Railway deploy time significantly
[ ] C-2-6  Confirm all 20 existing tests (9 from PR D + 10 from PR E + 1 smoke) pass
```

**No-go**: The fix causes any previously passing test to fail.

---

### Section C-3: Add Staging Smoke Test to ci.yml

**File**: `.github/workflows/ci.yml` (modified)
**Who**: Claude writes; Avanish reviews

**Current ci.yml state**: two jobs (lint, test), both triggered on any push to any branch and on PRs to main.

**New job to add**: `staging-smoke-test`

**Trigger**: only on push to `main` (not on PRs, not on feature branches — staging doesn't need to be tested for every PR, only after merge).

**Dependencies**: must run after both `lint` and `test` pass.

**Behavior**:
1. Wait for Railway staging deployment to complete (Railway deploys asynchronously from GitHub push; there is a race condition)
2. Retry-capable health check on staging URL
3. Verify staging DB safety invariants via psql

**Proposed job structure**:
```yaml
staging-smoke-test:
  name: Staging smoke test
  runs-on: ubuntu-latest
  needs: [lint, test]
  if: github.ref == 'refs/heads/main' && github.event_name == 'push'
  steps:
    - name: Wait for Railway staging deployment
      run: sleep 120   # 2-minute wait for Railway to pick up and deploy the push
                       # Adjust if Railway deployment is consistently faster or slower

    - name: Staging health check (with retry)
      run: |
        for i in 1 2 3 4 5; do
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" ${{ secrets.STAGING_URL }}/health)
          if [ "$STATUS" = "200" ]; then
            echo "Staging healthy (attempt $i)"
            exit 0
          fi
          echo "Attempt $i: got $STATUS, retrying in 30s..."
          sleep 30
        done
        echo "Staging health check failed after 5 attempts"
        exit 1

    - name: Install psql client
      run: |
        sudo apt-get update -qq
        sudo apt-get install -y postgresql-client

    - name: Staging DB safety invariants
      env:
        STAGING_DATABASE_URL: ${{ secrets.STAGING_DATABASE_URL }}
      run: |
        # Verify send_enabled is false
        SEND_ENABLED=$(psql "$STAGING_DATABASE_URL" -t -c "SELECT send_enabled FROM outreach_send_config LIMIT 1;")
        if [ "$(echo $SEND_ENABLED | tr -d ' ')" != "f" ]; then
          echo "FAIL: send_enabled is not false on staging"
          exit 1
        fi
        echo "PASS: send_enabled=false confirmed"

        # Verify staging is not production (contact count must be under 1000)
        CONTACT_COUNT=$(psql "$STAGING_DATABASE_URL" -t -c "SELECT count(*) FROM contacts;")
        CONTACT_COUNT=$(echo $CONTACT_COUNT | tr -d ' ')
        if [ "$CONTACT_COUNT" -gt 1000 ]; then
          echo "FAIL: staging contact count $CONTACT_COUNT exceeds 1000 — may be pointing at production"
          exit 1
        fi
        echo "PASS: staging contact count=$CONTACT_COUNT (not production)"

        # Verify key tables exist
        TABLE_COUNT=$(psql "$STAGING_DATABASE_URL" -t -c "
          SELECT count(*) FROM information_schema.tables
          WHERE table_schema='public'
          AND table_name IN ('outreach_drafts','contacts','workflow_events',
                             'provider_events','policy_snapshots','context_packets');")
        TABLE_COUNT=$(echo $TABLE_COUNT | tr -d ' ')
        if [ "$TABLE_COUNT" != "6" ]; then
          echo "FAIL: expected 6 required tables, found $TABLE_COUNT"
          exit 1
        fi
        echo "PASS: all 6 required tables present"
```

**GitHub Actions secrets required** (added by Avanish in GitHub dashboard after Phase 0-Infra):
```
[ ] C-3-a  STAGING_URL:           https://[Railway staging deployment URL]
[ ] C-3-b  STAGING_DATABASE_URL:  [staging Supabase transaction pooler URL]

These must be added to GitHub repository Settings > Secrets and variables > Actions
AFTER Phase 0-Infra credentials are confirmed (Step I-1-4 and I-1-5).
These are encrypted secrets — never plain text in the workflow file.
The STAGING_DATABASE_URL value contains the staging password — treat as sensitive.
```

**Verification**:
```
[ ] C-3-c  The job only runs on push to main (not on feature branch pushes or PRs)
[ ] C-3-d  The job depends on lint and test passing (needs: [lint, test])
[ ] C-3-e  The health check retries 5 times with 30-second intervals (total max wait: 2.5 min)
[ ] C-3-f  The DB check fails (exits 1) if contact count > 1000
           (catches accidental production DATABASE_URL in secrets)
[ ] C-3-g  The sleep value is documented with a comment — it can be tuned after
           observing actual Railway staging deployment duration in practice
```

**No-go**:
- Staging smoke test passes by skipping the psql checks (e.g., if psql install fails, the job must fail, not skip)
- STAGING_DATABASE_URL hardcoded in ci.yml (must be a secret reference, not a plaintext URL)
- Job runs on feature branch pushes (it must be main-only)

---

### Section C-4: Create Manual Production Deploy Workflow

**File**: `.github/workflows/deploy-production.yml` (new file)
**Who**: Claude writes; Avanish reviews

This workflow enables controlled manual production deploys via Railway CLI, replacing the auto-deploy that was disabled in Phase 0-Infra Step I-4-3.

**Requirements**:
- Trigger: `workflow_dispatch` only (no push, no PR trigger)
- Input: a typed confirmation string that must equal `"deploy-production"` to prevent accidental runs
- Uses Railway CLI to deploy to the production environment
- Fails gracefully if RAILWAY_TOKEN secret is missing or invalid

**Proposed workflow structure**:
```yaml
name: Deploy to Production

on:
  workflow_dispatch:
    inputs:
      confirm:
        description: 'Type "deploy-production" to confirm'
        required: true
        type: string

jobs:
  deploy:
    name: Deploy to production
    runs-on: ubuntu-latest
    environment: production   # Optional: can add a GitHub environment with
                              # required reviewers for extra protection
    steps:
      - name: Validate confirmation
        run: |
          if [ "${{ github.event.inputs.confirm }}" != "deploy-production" ]; then
            echo "Confirmation string does not match. Aborting."
            exit 1
          fi
          echo "Confirmation accepted."

      - name: Checkout
        uses: actions/checkout@v4

      - name: Install Railway CLI
        run: npm install -g @railway/cli

      - name: Deploy to production
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: railway up --environment production --detach
        # --detach: starts the deploy and returns immediately.
        # Railway dashboard should be monitored for deploy completion.
        # A --wait flag or polling step can be added later if synchronous
        # confirmation is needed.
```

**GitHub secrets required**:
```
[ ] C-4-a  RAILWAY_TOKEN: the Railway authentication token
           Check: does this secret already exist in GitHub repository secrets?
           If not: generate one from Railway dashboard > Account > Tokens > Create Token
           Store in password manager: "ProspectIQ Railway deploy token"
           Add to GitHub repository secrets.
```

**Verification**:
```
[ ] C-4-b  Workflow appears in GitHub Actions > Workflows with "Run workflow" button
[ ] C-4-c  Triggering with confirm="wrong-value" exits at the validation step (exit code 1),
           no Railway deploy occurs
[ ] C-4-d  Triggering with confirm="deploy-production" reaches the Railway deploy step
           NOTE: do not run this test until Phase 0 is fully validated.
           The test with incorrect input is sufficient for now.
[ ] C-4-e  The workflow does NOT appear in push-triggered CI runs
           (workflow_dispatch trigger only)
```

**No-go**:
- Workflow can be triggered by a push to main (must be workflow_dispatch only)
- Confirmation validation step can be bypassed (it must be the first step)
- RAILWAY_TOKEN hardcoded in the workflow file

---

### Section C-5: Create scripts/seed_staging.py

**File**: `scripts/seed_staging.py` (new file)
**Who**: Claude writes; Avanish reviews

This script creates the synthetic staging dataset described in PHASE_0_STAGING_SETUP_PLAN.md Section A-6.

**Design requirements** (Claude will implement these; Avanish will review):

Connectivity: reads `STAGING_DATABASE_URL` from environment (not hardcoded); refuses to run if the URL contains `wlyhbdmjhgvovigogdco` (the production project ref) as a safety guard.

Safety guard (must be first check in the script):
```python
import os
DATABASE_URL = os.environ["STAGING_DATABASE_URL"]
if "wlyhbdmjhgvovigogdco" in DATABASE_URL:
    raise RuntimeError(
        "STAGING_DATABASE_URL points to the production database. "
        "Refusing to seed. Set STAGING_DATABASE_URL to the staging database."
    )
```

Idempotency: all INSERTs use `ON CONFLICT DO NOTHING` with stable deterministic UUIDs (hardcoded in the script). Re-running the script produces no duplicates and no errors.

Email domain: every contact email must be `[something]@staging-test.invalid`. The `.invalid` TLD is defined in RFC 2606 as guaranteed non-routable. No `@gmail.com`, `@yahoo.com`, or any real domain.

Dataset coverage (minimum):
```
1 workspace  (stable UUID: deterministic)
10 companies (stable UUIDs)
30 contacts  (stable UUIDs, all @staging-test.invalid)
  - 5 contacts: no outreach (fresh)
  - 5 contacts: 1 sent draft, no engagement (unopened)
  - 5 contacts: 1 sent draft, opened (engagement_level WARM)
  - 5 contacts: 1 sent draft, replied (triggers HOT company traction)
  - 5 contacts: active suppression (2 temporary, 2 permanent, 1 expired)
  - 5 contacts: pending drafts (approval_status = 'pending')
15+ outreach_drafts (matching the contact scenarios above)
5 suppression_rules
3 workflow_events (one per scenario type)
1 policy_snapshot (for the staging workspace)
```

**Verification** (after running):
```
[ ] C-5-a  Script runs without error:
           STAGING_DATABASE_URL=[staging URL] python scripts/seed_staging.py
[ ] C-5-b  Script is idempotent: running it twice produces no errors and no duplicates
[ ] C-5-c  No real email addresses in the output:
           psql "[STAGING_DATABASE_URL]" -c \
             "SELECT email FROM contacts WHERE email NOT LIKE '%staging-test.invalid';"
           Expected: 0 rows
[ ] C-5-d  Script refuses to run with production DATABASE_URL:
           STAGING_DATABASE_URL=[production URL] python scripts/seed_staging.py
           Expected: RuntimeError about production database
[ ] C-5-e  Contact count after seeding: 30
           psql "[STAGING_DATABASE_URL]" -c "SELECT count(*) FROM contacts;"
```

**No-go**:
- Any real email address in seed data
- Script does not have the production URL guard
- Script is not idempotent (second run throws constraint errors)

---

### Section C-6: Add Makefile Targets

**File**: `Makefile` (modified)
**Who**: Claude writes; Avanish reviews

Add the following targets to the existing Makefile:

```makefile
## Verify staging environment is healthy and correctly configured.
## Runs DB safety checks against STAGING_DATABASE_URL.
## Usage: STAGING_DATABASE_URL=[url] make verify-staging
verify-staging:
	@echo "--- Checking staging connectivity ---"
	@psql "$(STAGING_DATABASE_URL)" -c "SELECT 1;" > /dev/null 2>&1 \
		&& echo "PASS: DB connected" \
		|| (echo "FAIL: cannot connect to staging DB" && exit 1)
	@SEND=$(shell psql "$(STAGING_DATABASE_URL)" -t -c "SELECT send_enabled FROM outreach_send_config LIMIT 1;" 2>/dev/null | tr -d ' '); \
		[ "$$SEND" = "f" ] \
		&& echo "PASS: send_enabled=false" \
		|| (echo "FAIL: send_enabled is not false (got: $$SEND)" && exit 1)
	@echo "PASS: staging verified"

## Apply a single migration file to staging.
## Usage: STAGING_DATABASE_URL=[url] make migrate-staging MIGRATION=053_draft_hardening_trigger_unique.sql
migrate-staging:
	@test -n "$(MIGRATION)" || (echo "Usage: make migrate-staging MIGRATION=<filename>" && exit 1)
	@echo "Applying migration $(MIGRATION) to STAGING..."
	@psql "$(STAGING_DATABASE_URL)" -f "supabase_migrations/migrations/$(MIGRATION)" \
		&& echo "Done." \
		|| (echo "Migration FAILED. Review output above." && exit 1)

## Apply a single migration file to production.
## Requires manual confirmation prompt.
## Usage: PRODUCTION_DATABASE_URL=[url] make migrate-production MIGRATION=053_...
migrate-production:
	@test -n "$(MIGRATION)" || (echo "Usage: make migrate-production MIGRATION=<filename>" && exit 1)
	@echo ""
	@echo "WARNING: You are about to apply migration $(MIGRATION) to PRODUCTION."
	@echo "Type 'yes' to proceed, anything else to abort:"
	@read CONFIRM; \
		[ "$$CONFIRM" = "yes" ] \
		|| (echo "Aborted." && exit 1)
	@echo "Applying migration $(MIGRATION) to PRODUCTION..."
	@psql "$(PRODUCTION_DATABASE_URL)" -f "supabase_migrations/migrations/$(MIGRATION)" \
		&& echo "Done." \
		|| (echo "Migration FAILED. Review output above." && exit 1)

## Seed the staging database with synthetic test data.
## Usage: STAGING_DATABASE_URL=[url] make seed-staging
seed-staging:
	@test -n "$(STAGING_DATABASE_URL)" || (echo "STAGING_DATABASE_URL is required" && exit 1)
	@STAGING_DATABASE_URL=$(STAGING_DATABASE_URL) python scripts/seed_staging.py \
		&& echo "Seed complete." \
		|| (echo "Seed FAILED." && exit 1)
```

**Verification**:
```
[ ] C-6-a  make verify-staging passes with staging credentials
[ ] C-6-b  make verify-staging fails if STAGING_DATABASE_URL is not set
[ ] C-6-c  make migrate-production prompts for confirmation and aborts on non-"yes" input
[ ] C-6-d  make seed-staging runs seed_staging.py correctly
[ ] C-6-e  No make target uses hardcoded credentials
```

---

### Section C-7: Phase 0-Code PR Definition

**Branch**: `infra/phase-0-staging-code`
**Target**: main
**PR title**: `infra(staging): phase-0 code setup — migration order, CI, seed, deploy workflow`

**Files changed** (total: 6 files):

| File | Change type | Description |
|---|---|---|
| `scripts/MIGRATION_ORDER.txt` | New | Documented migration application order |
| `scripts/seed_staging.py` | New | Idempotent synthetic staging seed script |
| `requirements.txt` | Modified | Add pydantic[email] or equivalent fix |
| `.github/workflows/ci.yml` | Modified | Add staging-smoke-test job |
| `.github/workflows/deploy-production.yml` | New | Manual production deploy workflow |
| `Makefile` | Modified | Add verify-staging, migrate-staging, migrate-production, seed-staging targets |

**PR size**: ~200–350 lines. No migration SQL. No application logic changes. No send path. No scheduler. No outbound_queue, send_attempts, or orchestration runtime.

**PR checklist items**:
```
[ ] All 6 files are in scope of the PR
[ ] No migration SQL files changed
[ ] No application route or business logic changed
[ ] pydantic[email] fix is the only requirements.txt change
[ ] All existing tests pass (20 tests: 9 PR D + 10 PR E + 1 smoke)
[ ] Staging smoke test job runs on push to main only
[ ] deploy-production.yml uses workflow_dispatch trigger only
[ ] seed_staging.py passes production URL guard test
[ ] MIGRATION_ORDER.txt count matches the count applied in Phase 0-Infra I-3-2
[ ] GitHub Actions secrets (STAGING_URL, STAGING_DATABASE_URL, RAILWAY_TOKEN)
    are confirmed stored in GitHub repository secrets before the PR is merged
    (otherwise the staging smoke test job will fail on first push to main)
```

---

### Section C-8: Phase 0-Code Acceptance Criteria

```
[ ] CA-1   All 20 existing tests pass in CI.
[ ] CA-2   scripts/MIGRATION_ORDER.txt exists and lists all migrations in order.
           Count matches Phase 0-Infra application count.
[ ] CA-3   pydantic[email] CI failure is resolved. test_app_import_smoke.py passes.
[ ] CA-4   scripts/seed_staging.py passes production URL guard test.
[ ] CA-5   scripts/seed_staging.py is idempotent (second run has no errors or duplicates).
[ ] CA-6   Staging smoke test CI job runs on push to main and passes.
[ ] CA-7   Staging smoke test CI job does NOT run on feature branch pushes or PRs.
[ ] CA-8   deploy-production.yml exists and is triggerable manually in GitHub Actions.
[ ] CA-9   deploy-production.yml aborts on incorrect confirm string.
[ ] CA-10  Makefile targets: verify-staging, migrate-staging, migrate-production,
           seed-staging all present and functional.
[ ] CA-11  GitHub Actions secrets STAGING_URL, STAGING_DATABASE_URL, and RAILWAY_TOKEN
           are confirmed stored and referenced correctly.
[ ] CA-12  No application code changes in this PR (no routes, no schemas, no models).
```

### Section C-9: Phase 0-Code Rollback Plan

```
Phase 0-Code is a single PR against main. Rollback = revert the PR.

Reverting the PR restores:
  - ci.yml to its previous state (two jobs only, staging smoke test removed)
  - Makefile to its previous state (four targets only)
  - requirements.txt to its previous state
  - deploy-production.yml is deleted (or was not merged)
  - seed_staging.py and MIGRATION_ORDER.txt are deleted

Effect on Phase 0-Infra:
  - Phase 0-Infra changes (Supabase, Railway) are NOT rolled back by reverting this PR
  - The staging Railway environment continues to exist
  - Production auto-deploy remains disabled (this was set in Phase 0-Infra)
  - CRITICAL: if deploy-production.yml is reverted before a production deploy is needed,
    production deploys must be done via railway CLI directly until the PR is re-merged:
    railway up --environment production

Rollback should only be needed if the staging smoke test job causes CI instability,
the pydantic[email] fix has unintended consequences, or the seed script has a correctness issue.
All of these can be resolved in a follow-up commit rather than a full revert.
```

### Section C-10: Phase 0-Code No-Go Conditions

```
NG-C-1  Any existing test fails after the pydantic[email] fix.
         The fix must not break anything that was passing before.

NG-C-2  Staging smoke test job can be triggered on a feature branch push.
         It must be main-only.

NG-C-3  STAGING_DATABASE_URL is hardcoded in ci.yml.
         It must be a GitHub Actions secret reference: ${{ secrets.STAGING_DATABASE_URL }}

NG-C-4  seed_staging.py does not include the production URL guard.
         The guard is the primary safety mechanism preventing accidental production seeding.

NG-C-5  seed_staging.py contains any non-@staging-test.invalid email address.

NG-C-6  deploy-production.yml can be triggered by a push to any branch.

NG-C-7  MIGRATION_ORDER.txt file count does not match the count applied in Phase 0-Infra.
         A mismatch means the documented order is wrong.

NG-C-8  The PR touches any route, schema, model, or business logic file.
         Phase 0-Code is infrastructure only.

NG-C-9  GitHub Actions secrets are not stored before the PR is merged.
         The staging smoke test job will fail on the first push to main without them.
         Confirm secrets exist before merging.
```

---

## Combined Phase 0 Acceptance Criteria

Phase 0 is complete when **all** of the following are true. This is the sign-off checklist.

```
STAGING ENVIRONMENT
[ ] P0-1  Staging Supabase project exists, isolated from production, with all migrations applied.
[ ] P0-2  Migration 053 objects confirmed on staging: function, trigger, correct index predicate.
[ ] P0-3  send_enabled=false on staging DB.
[ ] P0-4  Railway staging environment exists, auto-deploys from main, runs without errors.
[ ] P0-5  Railway production environment requires manual deploy only.
[ ] P0-6  Staging contact count = 30 (seed data loaded). Does not equal 9,946.

ENVIRONMENT ISOLATION
[ ] P0-7  Staging and production Supabase projects have different URLs and credentials.
[ ] P0-8  ENVIRONMENT=staging in Railway staging; ENVIRONMENT=production in Railway production.
[ ] P0-9  All INSTANTLY_* and GMAIL_* variables are empty strings in staging.
[ ] P0-10 Staging and production RESEND_API_KEY values are different.

CI AND DEPLOY
[ ] P0-11 All 20 existing tests pass in CI (no pre-existing failures).
[ ] P0-12 Staging smoke test CI job passes on push to main.
[ ] P0-13 Staging smoke test CI job does NOT run on feature branch pushes.
[ ] P0-14 deploy-production.yml exists and requires correct confirmation string.
[ ] P0-15 No production auto-deploy occurs as a side effect of any push to main.

TOOLING
[ ] P0-16 scripts/MIGRATION_ORDER.txt exists and is correct.
[ ] P0-17 scripts/seed_staging.py is idempotent and protected by production URL guard.
[ ] P0-18 Makefile targets verify-staging and migrate-staging are functional.

SIGN-OFF
[ ] P0-19 Avanish confirms Phase 0 complete.
[ ] P0-20 Phase 2 (PR F) is authorized to begin.
```

---

## Execution Order Summary

```
SHARED PRE-STEP (~15 min — Avanish at psql):
  PRE-1 through PRE-7: determine migration order, record temporarily

PHASE 0-INFRA (~2–4 hours — Avanish at consoles):
  I-1: Create Supabase staging project, collect all 4 credentials
  I-2: Disable dangerous Supabase features
  I-3: Apply all migrations in determined order, verify 053 objects
  I-4: Create Railway staging environment + DISABLE production auto-deploy (same session)
  I-5: Configure all 31 staging env vars + add ENVIRONMENT=production to production
  I-6: Create staging Resend API key, configure in Railway staging
  I-7: Trigger first staging deployment, verify health and isolation
  I-8: Confirm all Phase 0-Infra acceptance criteria

PHASE 0-CODE (~2–3 hours — Claude writes, Avanish reviews):
  C-1: Write MIGRATION_ORDER.txt  [no Phase 0-Infra dependency — can begin now]
  C-2: Fix pydantic[email]        [no Phase 0-Infra dependency — can begin now]
  C-3: Add staging smoke test     [requires STAGING_URL + STAGING_DATABASE_URL from I-1]
       C-3-a: Write ci.yml changes (can be written before secrets exist)
       C-3-b: Add secrets to GitHub (requires Phase 0-Infra credentials)
  C-4: Write deploy-production.yml [requires RAILWAY_TOKEN — may already exist]
  C-5: Write seed_staging.py       [no Phase 0-Infra dependency — can begin now]
  C-6: Write Makefile targets      [no Phase 0-Infra dependency — can begin now]
  C-7: Open PR infra/phase-0-staging-code
       Merge only after:
         - Phase 0-Infra acceptance criteria met (IA-1 through IA-20, including PR F hard gates IA-15 through IA-18)
         - GitHub Actions secrets confirmed present (STAGING_URL, STAGING_DATABASE_URL, RAILWAY_TOKEN)
         - All CI checks pass including the new staging smoke test
  C-8: Confirm all Phase 0-Code acceptance criteria

PHASE 0 SIGN-OFF:
  Run combined acceptance criteria checklist P0-1 through P0-18.
  Avanish confirms P0-19.
  Phase 2 (PR F) authorized at P0-20.
```

---

*End of Phase 0 execution split plan.*

**Next document upon Phase 0 completion**: return to PROSPECTIQ_VNEXT_IMPLEMENTATION_ROADMAP.md, PR F section.
