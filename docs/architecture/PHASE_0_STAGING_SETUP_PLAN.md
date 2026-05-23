# ProspectIQ — Phase 0: Staging Environment Setup Plan

**Version 1.0 | 2026-05-14**
**Author: Avanish Mehrotra & Digitillis Architecture Team**
**Status: Execution Checklist | Pre-Implementation Planning Document**

---

## About This Document

This is the concrete, step-by-step execution plan for Phase 0 of the ProspectIQ VNext roadmap. Phase 0 is a prerequisite for all Phase 2 (Durable Execution) work. Nothing in Phase 2 or beyond is safe to build without a validated staging environment.

This document does not contain code, migrations, or SQL. It contains the ordered checklist of what must be done, by whom, with what acceptance criteria, and with what no-go conditions.

**Reference**: PROSPECTIQ_VNEXT_IMPLEMENTATION_ROADMAP.md, Tasks 0-A through 0-C

---

## Critical Pre-Condition: Migration Ordering Problem

Before any staging setup work begins, a blocking dependency must be resolved.

The `supabase_migrations/migrations/` directory contains **55 files** with **duplicate numbers**:

```
002_apollo_extended_fields.sql  <-- conflicts with
002_improvements.sql

003_contact_events.sql          <-- conflicts with
003_dnc_priority_queue.sql

019_campaign_threads_hitl.sql   <-- conflicts with
019_sequence_builder_v2.sql

020_sequence_builder_v2.sql     <-- follows two 019s
```

There is no `021` in the sequence. There is a gap after 020.

The production database has all 55 migrations applied, but the order they were actually applied is only determinable by querying the production DB's migration tracking table (if one exists) or by inferring from table dependencies.

**This must be resolved before Task 0-A Step 6 (applying migrations to staging).**

### Pre-Condition Step: Determine the Correct Migration Application Order

```
[ ] Query production DB for migration tracking:
    SELECT * FROM supabase_migrations.schema_migrations ORDER BY inserted_at;
    -- If this table does not exist, try:
    SELECT * FROM schema_migrations ORDER BY version;

[ ] If no tracking table exists: examine the duplicate-numbered files to determine
    which was applied first by looking at their content and table dependencies.
    A table that is referenced by a later migration must exist first.

[ ] Document the correct application order for all 55 files as an ordered list.
    Save this as scripts/MIGRATION_ORDER.txt before starting Task 0-A.

[ ] Note: the corrected migration 053 (WHERE approval_status <> 'rejected'::approval_status)
    is already in the file on disk. The production DB has the corrected index.
    Apply the file as-is — it will work on staging.
```

**No-go for Task 0-A Step 6**: Migration order not documented.

---

## Task 0-A: Supabase Staging Project

**Goal**: A clean, isolated Supabase project with all 55 migrations applied, seeded with synthetic test data, and confirmed safe (send_enabled=false, no real emails reachable).

---

### Step A-1: Create the Supabase Project

```
[ ] Log in to supabase.com as the project owner.

[ ] Create a new project:
    - Project name:  prospectiq-staging
    - Region:        ca-central-1  (same as production — wlyhbdmjhgvovigogdco)
    - Database password: strong, unique, saved in password manager
    - Plan: Free tier is sufficient for staging

[ ] Wait for project provisioning (typically 1-2 minutes).

[ ] Collect the following credentials from the Supabase dashboard:
    - Project reference ID (e.g., xxxxxxxxxxxxxxxxxxx)
    - SUPABASE_URL:         https://[ref].supabase.co
    - SUPABASE_KEY:         (anon/public key — Settings > API)
    - SUPABASE_SERVICE_KEY: (service_role key — Settings > API)
    - DATABASE_URL:         (Transaction pooler URL — Settings > Database > Connection string)
                            Format: postgresql://postgres.[ref]:[password]@aws-0-ca-central-1.pooler.supabase.com:5432/postgres
                            Use the TRANSACTION pooler (port 5432), not the session pooler (port 5432/6543).
                            This matches the production pattern.

[ ] Record all four values securely. Do NOT store them in the .env file committed to git.
    They will be stored in Railway staging environment variables only.
```

---

### Step A-2: Disable Dangerous Supabase Features in Staging

```
[ ] In Supabase dashboard > Authentication > Settings:
    - Disable email confirmations (staging users should not receive real emails)
    - Disable all OAuth providers (not needed for staging)

[ ] In Supabase dashboard > Database > Replication:
    - Verify no replication is set up between staging and production (they must be
      completely isolated)

[ ] Confirm: the staging project URL is distinct from the production URL
    (wlyhbdmjhgvovigogdco.supabase.co). They must not share any credentials.
```

---

### Step A-3: Verify the Correct Migration Application Order (from Pre-Condition)

```
[ ] Confirm that MIGRATION_ORDER.txt has been created (from Pre-Condition step).

[ ] For each duplicate-numbered migration pair, confirm which order is correct:
    - 002_apollo_extended_fields.sql vs 002_improvements.sql
    - 003_contact_events.sql vs 003_dnc_priority_queue.sql
    - 019_campaign_threads_hitl.sql vs 019_sequence_builder_v2.sql

[ ] Confirm that migration 053 on disk has the corrected predicate:
    WHERE approval_status <> 'rejected'::approval_status
    (not the original ::text cast version)
    Run: grep "WHERE approval_status" supabase_migrations/migrations/053_draft_hardening_trigger_unique.sql
    Expected output contains: approval_status <> 'rejected'::approval_status
```

---

### Step A-4: Apply All Migrations to Staging (in Correct Order)

```
[ ] Construct the staging DATABASE_URL from Step A-1 credentials.

[ ] Run migrations in documented order. For each migration:

    psql "[STAGING_DATABASE_URL]" -f supabase_migrations/migrations/[filename].sql

    If a migration fails:
      - Read the error carefully
      - Do NOT skip the migration
      - If it's a dependency issue: re-examine the order and correct MIGRATION_ORDER.txt
      - If it's a data issue: the staging DB is fresh — this should not happen
      - Resolve and re-run from the failed migration

[ ] After all 55 migrations apply without error, run verification queries:
    psql "[STAGING_DATABASE_URL]" <<SQL
    -- Verify key tables exist
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name;
    SQL

    Expected: outreach_drafts, contacts, companies, suppression_rules,
    outreach_send_config, workflow_events, provider_events,
    policy_snapshots, context_packets all present.

[ ] Verify migration 053 objects specifically:
    psql "[STAGING_DATABASE_URL]" <<SQL
    SELECT routine_name FROM information_schema.routines
    WHERE routine_schema = 'public' AND routine_name = 'enforce_draft_immutability';

    SELECT trigger_name, event_manipulation FROM information_schema.triggers
    WHERE event_object_table = 'outreach_drafts' AND trigger_name = 'trg_draft_immutability';

    SELECT indexname FROM pg_indexes
    WHERE tablename = 'outreach_drafts'
    AND indexname = 'idx_outreach_drafts_active_unique';
    SQL

    Expected: all three objects present, matching production.
```

---

### Step A-5: Configure outreach_send_config on Staging

```
[ ] The outreach_send_config table must exist after migration 029.
    Insert the staging row with send_enabled = false:

    psql "[STAGING_DATABASE_URL]" <<SQL
    INSERT INTO outreach_send_config (send_enabled)
    VALUES (false)
    ON CONFLICT DO NOTHING;
    SQL

[ ] Verify:
    psql "[STAGING_DATABASE_URL]" -c "SELECT send_enabled FROM outreach_send_config;"
    Expected: f

[ ] This value must NEVER be changed to true on staging without explicit session
    authorization from Avanish. It is the primary safety guard.
```

---

### Step A-6: Synthetic Data Decision and Seed Script

**Decision: Synthetic data only. No sanitized production data.**

Rationale:
- Production contacts are real people at real companies. Sanitization pipelines are complex, error-prone, and still carry residual PII risk.
- Synthetic data is repeatable, resettable, and controllable.
- Staging can be torn down and rebuilt from scratch at any time without data loss risk.
- Apollo, ZeroBounce, and enrichment credit consumption risks are eliminated if contacts have no real emails.

**Seed data requirements** (what the seed script must create):

```
Workspaces (1 synthetic workspace):
  - workspace_id: a deterministic UUID (hardcoded in the seed script)
  - name: "Staging Test Workspace"
  - send_enabled override: false (controlled by outreach_send_config, not here)

Companies (10 synthetic companies):
  - 2 companies with traction_state = COLD (no engagement)
  - 2 companies with traction_state = ACTIVE (outreach started)
  - 2 companies with traction_state = WARM (opened/clicked)
  - 2 companies with traction_state = HOT (at least one reply)
  - 2 companies with suppressed contacts

  Company domain names: all must be @staging-test.invalid or similar
  (a non-deliverable TLD that guarantees no real email is ever reached)

Contacts (30 synthetic contacts, 3 per company):
  - All contact email addresses: [name]@staging-test.invalid
  - Status distribution:
    - 5 contacts: no outreach history (fresh)
    - 5 contacts: 1 sent draft, no engagement
    - 5 contacts: 1 sent draft, opened
    - 5 contacts: 1 sent draft, clicked
    - 5 contacts: 1 sent draft, replied (triggers HOT traction)
    - 5 contacts: active suppression (1 permanent, 2 temporary, 2 expired)

Outreach drafts (for the non-fresh contacts):
  - Pending drafts (approval_status = 'pending'): 5
  - Approved drafts (approval_status = 'approved'): 3
  - Sent drafts (approval_status = 'approved', sent_at IS NOT NULL): 15
  - Rejected drafts (approval_status = 'rejected'): 4
  - One draft in pending_second_review: 1

Suppression rules:
  - 1 permanent suppression (bounce reason)
  - 2 temporary suppressions with future expiry
  - 2 temporary suppressions with past expiry (to test expiry logic)

workflow_events:
  - One SEQUENCE_STARTED event per contact that has outreach history
  - Corresponding DRAFT_GENERATED and DRAFT_SENT events

policy_snapshots:
  - 1 snapshot for the staging workspace (current policy)

outreach_send_config:
  - send_enabled = false (from Step A-5)
```

```
[ ] Create the seed script at: scripts/seed_staging.py
    The script must be:
    - Idempotent (safe to re-run; uses INSERT ... ON CONFLICT DO NOTHING or
      checks before inserting)
    - Self-contained (no external API calls, no real email addresses)
    - Deterministic (same seed UUIDs on every run, so test references are stable)

[ ] Do NOT run the seed script yet — this is deferred until Task 0-A is complete
    and verified. Running it is part of the acceptance criteria.
```

---

### Step A-7: Task 0-A Acceptance Criteria

```
[ ] Staging Supabase project exists and is accessible via psql with the staging DATABASE_URL.
[ ] All 55 migrations applied without errors.
[ ] enforce_draft_immutability() function exists in staging DB.
[ ] trg_draft_immutability trigger exists on outreach_drafts in staging DB.
[ ] idx_outreach_drafts_active_unique index exists with correct predicate.
[ ] outreach_send_config.send_enabled = false.
[ ] Staging project credentials are stored securely (NOT in the committed .env file).
[ ] MIGRATION_ORDER.txt exists at scripts/MIGRATION_ORDER.txt.
[ ] Seed script exists at scripts/seed_staging.py.
[ ] Seed script runs without errors and produces the described synthetic dataset.
[ ] Table count on staging DB: SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';
    Record the count. It must match production (±2 for any staging-specific tables).
```

---

## Task 0-B: Railway Staging Environment

**Goal**: A staging Railway environment that auto-deploys from `main`, uses only staging credentials, and cannot affect production data.

---

### Step B-1: Create the Railway Staging Environment

```
[ ] Log in to railway.app as the project owner.

[ ] Navigate to the ProspectIQ project.
    Current state: one environment named "production" with auto-deploy from GitHub main.

[ ] Click "New Environment" and name it "staging".

[ ] In the staging environment, configure it to auto-deploy from the main branch
    of the GitHub repository (same as production currently does).

[ ] In the production environment, CHANGE the auto-deploy setting:
    - Go to production environment > Settings > Source
    - Disable "Auto-deploy" from GitHub
    - Production must now be deployed manually
    - This is the critical Railway change for production deploy discipline

[ ] Verify by checking both environments:
    - Staging: auto-deploy ON from main branch
    - Production: auto-deploy OFF
```

---

### Step B-2: Configure Staging Environment Variables

The staging environment requires a specific set of environment variables. Each variable is categorized below with its staging value guidance.

**DB and Core (staging-specific values required):**
```
[ ] SUPABASE_URL         = https://[staging-ref].supabase.co
[ ] SUPABASE_KEY         = [staging anon key]
[ ] SUPABASE_SERVICE_KEY = [staging service key]
[ ] DATABASE_URL         = postgresql://postgres.[staging-ref]:[password]@aws-0-ca-central-1.pooler.supabase.com:5432/postgres
```

**Safety guards (must be set exactly as shown):**
```
[ ] SEND_ENABLED          = false
[ ] ENVIRONMENT           = staging     (NEW variable — add to both staging and production)
                                         Production value: production
[ ] LEARNING_AUTO_APPLY   = false
```

**Sending identity (staging-specific — must NOT be the production sending identity):**
```
[ ] FROM_EMAIL            = ProspectIQ Staging <staging@digitillis.io>
                            (or a subdomain/alias that is clearly non-production)
                            This prevents staging-sent emails (if SEND_ENABLED is ever
                            briefly enabled) from appearing to come from the production address.
[ ] RESEND_API_KEY        = [staging Resend API key — see Task 0-B Step 3]
```

**External services — DISABLED in staging (set to empty string or sentinel value):**
```
[ ] INSTANTLY_API_KEY          = (empty — Instantly must not connect in staging)
[ ] INSTANTLY_WEBHOOK_SECRET   = (empty)
[ ] INSTANTLY_SEQ_MFG_VP_OPS   = (empty)
[ ] INSTANTLY_SEQ_MFG_MAINTENANCE = (empty)
[ ] INSTANTLY_SEQ_MFG_PLANT_MANAGER = (empty)
[ ] INSTANTLY_SEQ_MFG_DIRECTOR_OPS = (empty)
[ ] INSTANTLY_SEQ_MFG_GENERAL  = (empty)
[ ] INSTANTLY_SEQ_FB_VP_OPS    = (empty)
[ ] INSTANTLY_SEQ_FB_PLANT_MANAGER = (empty)
[ ] INSTANTLY_SEQ_FB_VP_QUALITY = (empty)
[ ] INSTANTLY_SEQ_FB_DIR_QUALITY = (empty)

[ ] GMAIL_USER             = (empty — IMAP reply checking disabled in staging)
[ ] GMAIL_APP_PASSWORD     = (empty)
    Note: any code that reads GMAIL credentials must handle empty gracefully
    without crashing the application. Verify this before deploying.
```

**External services — USE REAL KEYS with limited scope:**
```
[ ] ANTHROPIC_API_KEY     = [real key, same as production]
                            Risk: staging draft generation consumes Claude credits.
                            Acceptable: no autonomous generation running in Phase 0.
                            Mitigation: SEND_ENABLED=false prevents automated loops.

[ ] APOLLO_API_KEY        = [real key, same as production]
                            Risk: staging enrichment consumes Apollo credits.
                            Acceptable: no enrichment loops running in Phase 0.
                            Mitigation: no scheduler jobs in staging yet.

[ ] PERPLEXITY_API_KEY    = [real key, same as production]
                            Same risk profile as ANTHROPIC. Acceptable.
```

**Operational config (staging-appropriate values):**
```
[ ] SEND_WINDOW_START     = 09:00
[ ] SEND_WINDOW_END       = 17:00
[ ] DAILY_SEND_LIMIT      = 10       (low limit; extra safety guard)
[ ] BATCH_SIZE            = 5        (small batches for staging)
[ ] LOG_LEVEL             = DEBUG    (more verbose in staging)
[ ] WEBHOOK_SECRET        = [new secret, different from production]
```

---

### Step B-3: Resend Staging Configuration

Resend does not have a built-in "sandbox mode" that prevents real delivery. The safety strategy is layered:

**Layer 1 — SEND_ENABLED=false (primary guard)**: For Phase 0 and Phase 2 (PR F, PR G setup), no Resend API calls are made. This is the primary protection.

**Layer 2 — Staging API key**: Create a separate Resend API key for staging. This key is associated with a staging domain or subdomain.

**Layer 3 — Staging sending domain**: The staging FROM_EMAIL must use a domain or subdomain that:
- Is verified in Resend for the staging API key
- Is NOT the production sending domain (digitillis.io)
- Is clearly identifiable as non-production in any email headers

**Layer 4 — Resend test recipient addresses**: When SEND_ENABLED is briefly set to true for Phase 2 PR G validation, ALL test recipient email addresses must be Resend-provided test addresses:
- `delivered@resend.dev` — simulates successful delivery
- `bounced@resend.dev` — simulates a hard bounce
- `complained@resend.dev` — simulates a spam complaint

These addresses are processed by Resend's infrastructure without delivering to a real inbox.

```
[ ] In Resend dashboard:
    - Create a new API key named "prospectiq-staging"
    - If a staging subdomain is available (e.g., staging.digitillis.io),
      add and verify it in Resend for the staging key
    - If no staging subdomain exists: document this as a pending task and
      use the same sending domain for now but ensure FROM_EMAIL clearly
      indicates staging. This is acceptable for Phase 0 only.

[ ] Store the staging Resend API key in the Railway staging environment as RESEND_API_KEY.
    The production Railway environment must keep its own separate RESEND_API_KEY.

[ ] Verify: staging and production Resend API keys are different.
    grep-confirm by key prefix difference in Railway environment variable list.

[ ] Document in the Phase 2 PR G checklist: "All staging smoke tests involving
    sends must use @resend.dev test addresses only."
```

---

### Step B-4: Instantly Behavior in Staging

Instantly is used for email warmup only — not for the primary send path (Resend handles sends). In staging:

```
[ ] All INSTANTLY_* variables must be empty in the Railway staging environment
    (confirmed in Step B-2).

[ ] Verify that any code paths that call the Instantly API handle missing credentials
    gracefully. The application must start and serve requests without Instantly credentials.
    If any startup code crashes on missing INSTANTLY_API_KEY, that is a bug to fix
    before declaring Phase 0 complete.

[ ] No Instantly webhook endpoint should be registered or active in staging.
    If the Instantly webhook handler reads INSTANTLY_WEBHOOK_SECRET, it must
    reject all incoming webhooks with a 401 when the secret is empty.

[ ] No warmup campaign IDs (INSTANTLY_SEQ_*) are configured in staging.
    Any code that reads these IDs must handle empty/missing values gracefully.
```

---

### Step B-5: Gmail/IMAP Behavior in Staging

Gmail is used for receiving replies via IMAP. In staging:

```
[ ] GMAIL_USER and GMAIL_APP_PASSWORD are empty in the Railway staging environment
    (confirmed in Step B-2).

[ ] The IMAP polling job must handle missing credentials by:
    - Logging a warning at startup: "Gmail credentials not configured — IMAP polling disabled in staging"
    - NOT throwing an unhandled exception
    - NOT crashing the application

[ ] Future decision (not for Phase 0): when Phase 2 PR G requires testing the full
    reply-reception path, create a dedicated test Gmail account
    (e.g., prospectiq-staging-test@gmail.com) and configure it in staging.
    For now, IMAP is disabled.

[ ] Document this as a deferred Phase 2 prerequisite:
    "Create test Gmail account for staging IMAP testing before PR G merge validation."
```

---

### Step B-6: Trigger First Staging Deployment

```
[ ] Ensure all staging environment variables from Step B-2 are set in Railway.

[ ] Push a small, harmless change to the main branch
    (e.g., add a comment to PHASE_0_STAGING_SETUP_PLAN.md)
    to trigger the first staging auto-deploy.

[ ] Monitor the staging deployment in Railway dashboard.
    Expected: deployment succeeds; health check endpoint returns 200.

[ ] Verify staging is running and healthy:
    curl https://[staging-railway-url]/health
    or the actual health endpoint if different.

[ ] Verify staging is NOT using production DB:
    On the staging Railway service, check the SUPABASE_URL environment variable.
    It must contain the staging project reference, not wlyhbdmjhgvovigogdco.

[ ] Verify production is NOT auto-deploying:
    After the push to main that triggered staging, confirm that the production
    environment in Railway did NOT auto-deploy. It should show its previous
    deployment as the current one.
```

---

### Step B-7: Task 0-B Acceptance Criteria

```
[ ] Railway staging environment exists and is separate from production.
[ ] Staging auto-deploys on push to main. Production does NOT auto-deploy.
[ ] Staging deployment is healthy (HTTP 200 on health endpoint).
[ ] Staging is confirmed to be using the staging Supabase project (not production DB).
[ ] All 28 environment variables are correctly set in staging.
[ ] SEND_ENABLED=false confirmed in staging Railway environment.
[ ] ENVIRONMENT=staging confirmed in staging Railway environment.
[ ] ENVIRONMENT=production confirmed in production Railway environment.
[ ] Staging Resend API key is different from production Resend API key.
[ ] Instantly credentials are absent from staging environment.
[ ] Gmail credentials are absent from staging environment.
[ ] Production Railway environment shows no change in deployment after a push to main.
[ ] A second push to main confirms: staging redeploys, production is unchanged.
```

---

## Task 0-C: CI/CD Hardening

**Goal**: Fix the pre-existing CI failure. Add a staging smoke test job to CI. Add a manual production deploy workflow. Enforce that production deploys require explicit action.

---

### Step C-1: Fix the Pre-Existing CI Test Failure

The current CI fails on every run with:
```
FAILED backend/tests/test_app_import_smoke.py::test_app_entrypoint_imports_cleanly
ImportError: email-validator is not installed, run `pip install 'pydantic[email]'`
```

This pre-dates Phase 0 but must be fixed before adding new CI jobs. A broken CI baseline makes it impossible to distinguish Phase 0 failures from pre-existing ones.

```
[ ] Identify whether pydantic[email] is missing from requirements.txt or whether
    the requirements.txt install in ci.yml is correct.

[ ] Fix: either add `pydantic[email]` to requirements.txt (if it should be there),
    or add it as an extra install step in ci.yml (if it's a CI-only dependency).

[ ] Run CI locally (act or direct pytest) to confirm the fix resolves the failure
    without breaking any other tests.

[ ] Confirm all existing tests in backend/tests/ pass before proceeding to Step C-2.
    Current test files to pass:
    - test_pr_d_draft_hardening.py (9 tests)
    - test_pr_e_context_intelligence.py (10 tests)
    - test_app_import_smoke.py (1 test — the failing one)
```

---

### Step C-2: Add ENVIRONMENT Variable to Production

The new `ENVIRONMENT` variable (set in Step B-2 for staging) must also be set in production so that the application can distinguish between environments at runtime.

```
[ ] In Railway production environment, add:
    ENVIRONMENT = production

[ ] Verify by checking the Railway production environment variable list.
    This is a non-breaking additive change.
```

---

### Step C-3: Add Staging Smoke Test to CI

The current `ci.yml` runs lint and pytest but has no staging-environment test. Add a smoke test job that runs after a push to main, once Railway has deployed to staging.

The challenge: Railway's auto-deploy is triggered independently of GitHub Actions. There is a race condition if CI tries to hit staging immediately after a push. The practical solution is a timed wait plus a retry-capable health check, not a direct dependency on Railway webhooks.

```
[ ] Add a new job to .github/workflows/ci.yml:

    Job name: "Staging smoke test"
    Trigger: push to main branch ONLY (not on PRs, not on feature branches)
    Depends on: lint and test jobs passing
    Steps:
      1. Wait 120 seconds (allow Railway staging deployment to complete)
      2. Retry-capable health check: hit the staging health endpoint up to 5 times
         with 30-second intervals, expecting HTTP 200
      3. Run staging DB smoke queries via psql (using STAGING_DATABASE_URL secret)
      4. Verify SEND_ENABLED=false on staging via DB query

    GitHub Secrets required:
      STAGING_URL: the Railway staging deployment URL
      STAGING_DATABASE_URL: the staging Supabase transaction pooler URL

[ ] Store these as GitHub Actions secrets in the repository settings:
    - Settings > Secrets and variables > Actions > New repository secret
    - STAGING_URL = https://[staging-railway-url]
    - STAGING_DATABASE_URL = [staging DB connection string]

    IMPORTANT: STAGING_DATABASE_URL is a DB credential. It must be stored as a
    GitHub Actions secret (encrypted), not as a plain environment variable.
    Production DATABASE_URL must NEVER be stored as a GitHub Actions secret.
```

---

### Step C-4: Add Manual Production Deploy Workflow

Create a new GitHub Actions workflow file that enables manual production deploys via Railway CLI.

```
[ ] Create: .github/workflows/deploy-production.yml
    Trigger: workflow_dispatch (manual only — no push trigger)
    Inputs:
      - confirm: string (must equal "deploy-production" to prevent accidental runs)
    Steps:
      1. Validate the confirm input equals "deploy-production" exactly
      2. Install Railway CLI
      3. Run: railway up --environment production
         using RAILWAY_TOKEN GitHub secret
    On failure: the deployment is aborted; production is not affected

    GitHub Secrets required:
      RAILWAY_TOKEN: the Railway authentication token
      (this may already exist — confirm in Settings > Secrets)

[ ] Verify the deploy-production.yml workflow appears in GitHub Actions > Workflows
    as a manually-triggerable workflow with the "Run workflow" button.

[ ] Test the workflow by triggering it with an incorrect confirm value.
    Expected: workflow fails at the validation step; no Railway deploy occurs.

[ ] Do NOT test with the correct confirm value until all staging validation is
    confirmed complete. The first real production deploy via this workflow will
    be after Phase 0 acceptance criteria are met.
```

---

### Step C-5: Add Migration Makefile Targets

The Makefile currently has only four targets (install, api, dashboard, dev). Add targets for the migration workflow.

```
[ ] Add to Makefile:

    migrate-staging:
      (runs migration preflight, applies migration, runs verification for staging)
      Requires: MIGRATION variable (e.g., make migrate-staging MIGRATION=053)
      Uses: STAGING_DATABASE_URL environment variable

    migrate-production:
      (same sequence for production)
      Requires: MIGRATION variable
      Requires: PRODUCTION_DATABASE_URL environment variable
      Guard: prints a confirmation prompt before running
             "Are you sure you want to migrate PRODUCTION? Type 'yes' to continue:"
             If input is not 'yes', aborts.

    verify-staging:
      Runs the staging smoke test queries (DB connectivity, table existence,
      send_enabled check) without requiring a full CI run.

[ ] These targets do not need to exist before Phase 0 is complete.
    They are a quality-of-life improvement that can be added as part of the
    Task 0-C PR. They are listed here so the PR author knows to include them.
```

---

### Step C-6: Task 0-C Acceptance Criteria

```
[ ] All existing tests pass in CI (no pre-existing failures).
[ ] The staging smoke test CI job runs successfully on a push to main.
[ ] The staging smoke test CI job confirms:
    (a) staging health endpoint returns 200
    (b) staging send_enabled = false
    (c) staging DB is reachable from CI
[ ] The deploy-production.yml workflow exists and is triggerable manually.
[ ] The deploy-production.yml workflow fails gracefully on incorrect confirm input.
[ ] Production has NOT auto-deployed as a side effect of any CI/CD changes.
[ ] STAGING_URL and STAGING_DATABASE_URL are stored as GitHub Actions secrets.
[ ] RAILWAY_TOKEN is confirmed present (or added) as a GitHub Actions secret.
```

---

## Task 0-D: Staging Smoke Test Suite

This is the formal set of smoke tests that must pass before Phase 0 is declared complete, and before each Phase 2 PR is merged.

These tests are run manually against staging (via psql and curl) and are also automated in CI (Step C-3). The manual runbook is preserved here so it can be re-run during any maintenance window without relying on CI.

---

### DB Smoke Tests (run via psql against STAGING_DATABASE_URL)

```
[ ] Connectivity: psql connection succeeds
    psql "[STAGING_DATABASE_URL]" -c "SELECT 1;"
    Expected: 1

[ ] Migration completeness: all required tables exist
    psql "[STAGING_DATABASE_URL]" -c "
    SELECT count(*) FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name IN ('outreach_drafts','contacts','companies',
    'suppression_rules','outreach_send_config','workflow_events',
    'provider_events','policy_snapshots','context_packets');"
    Expected: 9

[ ] Send guard: SEND_ENABLED is false
    psql "[STAGING_DATABASE_URL]" -c "SELECT send_enabled FROM outreach_send_config;"
    Expected: f

[ ] Immutability trigger: present and attached
    psql "[STAGING_DATABASE_URL]" -c "
    SELECT trigger_name FROM information_schema.triggers
    WHERE event_object_table='outreach_drafts'
    AND trigger_name='trg_draft_immutability';"
    Expected: 1 row

[ ] Unique index: present with correct predicate
    psql "[STAGING_DATABASE_URL]" -c "
    SELECT indexname FROM pg_indexes
    WHERE tablename='outreach_drafts'
    AND indexname='idx_outreach_drafts_active_unique';"
    Expected: 1 row

[ ] No production data: confirm staging is isolated
    psql "[STAGING_DATABASE_URL]" -c "
    SELECT count(*) FROM contacts
    WHERE email NOT LIKE '%staging-test.invalid%'
    AND email NOT LIKE '%@resend.dev%';"
    Expected: 0 (or count matches only synthetic data with known non-real emails)
    NOTE: before the seed script has been run, this will also be 0. After the
    seed script runs, it must still be 0.

[ ] Seed data present (after seed script has been run):
    psql "[STAGING_DATABASE_URL]" -c "SELECT count(*) FROM contacts;"
    Expected: 30 (as defined in seed script)

    psql "[STAGING_DATABASE_URL]" -c "SELECT count(*) FROM outreach_drafts;"
    Expected: 28 (as defined in seed script: 5+3+15+4+1)
```

---

### API Smoke Tests (run via curl against staging Railway URL)

```
[ ] Health check:
    curl -s -o /dev/null -w "%{http_code}" https://[STAGING_URL]/health
    Expected: 200
    (or whatever the actual health endpoint is — check app.py for the route)

[ ] CORS and headers: staging API responds with correct headers
    curl -I https://[STAGING_URL]/health
    Expected: no production domain in CORS headers

[ ] Verify ENVIRONMENT variable is readable (if the app exposes it):
    If there is a /info or /version endpoint: confirm ENVIRONMENT=staging in response
    If not: skip this check (the Railway env var is sufficient)
```

---

### Safety Isolation Tests

```
[ ] Verify staging cannot reach production DB:
    On staging Railway instance, run a test that queries the DB.
    The result must be staging seed data, NOT production data.
    Simplest check: count of contacts on staging should be 30 (seed), not 9,946 (production).

[ ] Verify staging cannot send emails:
    SEND_ENABLED=false means no Resend calls are made.
    Verify: no outbound_queue table exists yet (it's created in PR F).
    Verify: send_enabled = false in outreach_send_config on staging.

[ ] Verify Instantly is disconnected:
    Any endpoint that calls Instantly must return gracefully when INSTANTLY_API_KEY is empty.
    If there is a health-check or status endpoint that shows connected services,
    Instantly should appear as "disconnected" or "not configured".

[ ] Verify Gmail/IMAP is disconnected:
    Same as Instantly: must fail gracefully, not crash.
```

---

## Phase 0 Master Execution Order

This is the exact sequence to follow. Do not proceed to the next step until the current step is complete and its checkbox is checked.

```
PREREQUISITE
  [ ] Pre-Condition: Determine correct migration application order from production.
      Save as scripts/MIGRATION_ORDER.txt.

SUPABASE SETUP (Tasks 0-A)
  [ ] A-1: Create Supabase staging project. Collect all 4 credentials.
  [ ] A-2: Disable dangerous Supabase features (email confirmation, OAuth).
  [ ] A-3: Confirm migration order and verify 053 disk version is correct.
  [ ] A-4: Apply all 55 migrations in order. Verify key objects.
  [ ] A-5: Insert outreach_send_config with send_enabled=false.
  [ ] A-6: Write seed script at scripts/seed_staging.py. (Do not run yet.)
  [ ] A-7: Confirm all Task 0-A acceptance criteria.

RAILWAY SETUP (Task 0-B) — can begin once A-1 credentials are collected
  [ ] B-1: Create Railway staging environment.
           CRITICAL: Disable production auto-deploy at the same time.
  [ ] B-2: Configure all 28 environment variables in staging.
  [ ] B-3: Configure Resend staging API key. Store in Railway staging.
  [ ] B-4: Verify Instantly is absent from staging env vars.
  [ ] B-5: Verify Gmail is absent from staging env vars. Document deferred IMAP decision.
  [ ] B-6: Trigger first staging deployment. Verify healthy. Verify production unchanged.
  [ ] B-7: Confirm all Task 0-B acceptance criteria.

CI/CD HARDENING (Task 0-C) — can begin once B-6 is confirmed
  [ ] C-1: Fix pre-existing CI test failure (pydantic[email]).
  [ ] C-2: Add ENVIRONMENT=production to production Railway env vars.
  [ ] C-3: Add staging smoke test job to ci.yml.
           Store STAGING_URL and STAGING_DATABASE_URL as GitHub Actions secrets.
  [ ] C-4: Create .github/workflows/deploy-production.yml (manual workflow_dispatch).
  [ ] C-5: Add Makefile targets (migrate-staging, migrate-production, verify-staging).
  [ ] C-6: Confirm all Task 0-C acceptance criteria.

SEED AND SMOKE TESTS
  [ ] Run the seed script against staging: python scripts/seed_staging.py
  [ ] Run all DB smoke tests from Task 0-D checklist.
  [ ] Run all API smoke tests from Task 0-D checklist.
  [ ] Run all Safety Isolation tests from Task 0-D checklist.

FINAL SIGN-OFF
  [ ] All acceptance criteria from 0-A, 0-B, 0-C are met.
  [ ] All smoke tests from 0-D pass.
  [ ] Production deploy mechanism is confirmed manual.
  [ ] CI is green on the staging smoke test job.
  [ ] Avanish confirms Phase 0 complete. Phase 2 (PR F) may begin.
```

---

## Phase 0 Acceptance Criteria (Summary)

Phase 0 is complete when ALL of the following are true:

```
[ ] 1. A Supabase staging project exists, fully isolated from production,
       with all 55 migrations applied without errors.

[ ] 2. The staging DB contains the migration 053 objects: immutability trigger,
       trg_draft_immutability trigger attachment, and
       idx_outreach_drafts_active_unique partial unique index.

[ ] 3. outreach_send_config.send_enabled = false on staging.

[ ] 4. A Railway staging environment exists and auto-deploys from main.

[ ] 5. The Railway production environment does NOT auto-deploy from main.

[ ] 6. All 28 environment variables are correctly set in staging.
       Staging credentials are different from production credentials for:
       SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY, DATABASE_URL,
       RESEND_API_KEY, FROM_EMAIL, WEBHOOK_SECRET, ENVIRONMENT.

[ ] 7. INSTANTLY_API_KEY and all INSTANTLY_SEQ_* vars are absent from staging.

[ ] 8. GMAIL_USER and GMAIL_APP_PASSWORD are absent from staging.

[ ] 9. CI passes on push to main: lint, test, and staging smoke test all green.

[ ] 10. A manual production deploy workflow exists and is confirmed functional
        (tested with incorrect confirm input; does not fire on push to main).

[ ] 11. Synthetic seed data is loaded in staging:
        ~30 contacts, all @staging-test.invalid, covering all engagement states.

[ ] 12. The staging API health endpoint returns 200.

[ ] 13. scripts/MIGRATION_ORDER.txt exists and documents the correct application
        order for all 55 migrations including the duplicate-numbered files.

[ ] 14. scripts/seed_staging.py exists and is idempotent.
```

---

## Phase 0 No-Go Conditions

The following conditions represent hard blockers. Phase 0 is not complete, and Phase 2 may not begin, if any of these are true.

```
NG-0-1: Staging DATABASE_URL resolves to the production Supabase project
         (wlyhbdmjhgvovigogdco).
         This would cause all Phase 2 test work to run against real production data.
         Catastrophic. Verify before every migration run.

NG-0-2: Production auto-deploy from main is still enabled in Railway.
         If production auto-deploys when Phase 2 schema changes merge to main,
         those changes go live before production validation. Not acceptable.

NG-0-3: SEND_ENABLED=true in either staging or production.
         No sends are authorized. This value must be false in both environments
         at Phase 0 completion.

NG-0-4: Any real prospect email address (non-@staging-test.invalid) present
         in the staging contacts table.
         Real contacts in staging risk accidental outreach if SEND_ENABLED is
         ever briefly enabled for PR G testing.

NG-0-5: INSTANTLY_API_KEY present in the staging Railway environment.
         Instantly warmup and campaign activity must never be triggered from staging.

NG-0-6: The staging and production Resend API keys are the same key.
         A staging send (even accidental) would share quota, domain reputation,
         and potentially routing with production sends.

NG-0-7: STAGING_DATABASE_URL stored as a plain text file, a .env entry committed
         to git, or anywhere other than a GitHub Actions encrypted secret and
         Railway environment variables (which are also encrypted).

NG-0-8: Any of the 55 migration files fail to apply on staging without a
         documented reason. Silent failures or partially-applied migrations
         leave staging in an unknown schema state that cannot be trusted for
         Phase 2 validation.

NG-0-9: The migration order for the duplicate-numbered files (002, 003, 019)
         is not determined and documented before migrations are applied.
         Applying them in wrong order may cause schema dependency failures
         that appear as bugs in Phase 2 testing.

NG-0-10: CI smoke test job passes by checking a non-staging URL.
          The STAGING_URL secret must be confirmed to point at the Railway
          staging deployment, not production or localhost.
```

---

## Environment Variable Reference Card

This card summarizes every env var, its staging value guidance, and its safety classification.

| Variable | Staging Value | Safety Class |
|---|---|---|
| SUPABASE_URL | staging project URL | CRITICAL — must differ from prod |
| SUPABASE_KEY | staging anon key | CRITICAL — must differ from prod |
| SUPABASE_SERVICE_KEY | staging service key | CRITICAL — must differ from prod |
| DATABASE_URL | staging pooler URL | CRITICAL — must differ from prod |
| ENVIRONMENT | `staging` | NEW — add to both environments |
| SEND_ENABLED | `false` | CRITICAL — never true without authorization |
| RESEND_API_KEY | staging-specific key | CRITICAL — must differ from prod |
| FROM_EMAIL | `ProspectIQ Staging <staging@...>` | Must be non-production identity |
| WEBHOOK_SECRET | new staging secret | Must differ from prod |
| ANTHROPIC_API_KEY | same as production | Acceptable — no autonomous loops in P0 |
| APOLLO_API_KEY | same as production | Acceptable — no enrichment loops in P0 |
| PERPLEXITY_API_KEY | same as production | Acceptable |
| INSTANTLY_API_KEY | EMPTY | REQUIRED EMPTY — safety critical |
| INSTANTLY_SEQ_* (9 vars) | EMPTY | REQUIRED EMPTY |
| INSTANTLY_WEBHOOK_SECRET | EMPTY | REQUIRED EMPTY |
| GMAIL_USER | EMPTY | Required empty at Phase 0 |
| GMAIL_APP_PASSWORD | EMPTY | Required empty at Phase 0 |
| SEND_WINDOW_START | `09:00` | Staging default |
| SEND_WINDOW_END | `17:00` | Staging default |
| DAILY_SEND_LIMIT | `10` | Conservative staging value |
| BATCH_SIZE | `5` | Conservative staging value |
| LEARNING_AUTO_APPLY | `false` | Must be false |
| LOG_LEVEL | `DEBUG` | More verbose in staging |

---

## Known Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Duplicate-numbered migrations apply in wrong order | Medium | High — schema errors in Phase 2 testing | Pre-condition step: document order before starting |
| Staging accidentally uses production DB | Low (if setup followed) | Catastrophic | Verify DATABASE_URL on first staging deploy; smoke test checks row count |
| Resend staging key shares domain with production | Medium | Medium — reputation risk if sends occur | Use staging subdomain or separate Resend project |
| Production auto-deploy not disabled in Railway | Low (manual step) | High — Phase 2 schema changes deployed to production prematurely | Verify explicitly in B-7 acceptance criteria |
| pydantic[email] fix introduces new regressions | Low | Medium | Run full test suite locally before pushing |
| Gmail empty credentials causes application crash | Medium | Medium — staging health check fails | Check graceful handling before deploying |
| Anthropic/Apollo/Perplexity credit consumption from staging | Low (no automation in Phase 0) | Low | Monitor usage; no autonomous loops in Phase 0 |
| Seed script uses real email-format addresses | Low (if designed correctly) | High | Mandate @staging-test.invalid for all seed contacts |

---

*End of Phase 0 setup plan.*

---

**Document status**: This plan is the execution reference for Phase 0. When all acceptance criteria are met and all no-go conditions are confirmed clear, Avanish signs off on Phase 0 completion. Phase 2 (PR F) may begin immediately after sign-off.

**Next document**: PROSPECTIQ_VNEXT_IMPLEMENTATION_ROADMAP.md, PR F section.
