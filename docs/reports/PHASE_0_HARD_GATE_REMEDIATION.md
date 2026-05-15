# Phase 0 Hard Gate Remediation

**Branch**: `infra/phase-0-hard-gate-remediation`
**Author**: Avanish Mehrotra & Digitillis Architecture Team
**Created**: 2026-05-15
**Status**: IN PROGRESS

## Purpose

PR F (outbound_queue + transactional outbox) was authorized and merged before the
four designated hard gates (IA-15 through IA-18) and several infrastructure checks
(IA-7, IA-8, IA-9, IA-13, IA-14, IA-19, IA-20) were verified.

This document tracks remediation of every unresolved IA item. No dispatch-capable
code (PR G or later) is authorized until all items below are marked PASS with
evidence recorded.

**PR G is blocked until the final recommendation at the bottom of this document
reads: SAFE FOR PR G.**

---

## Scope Constraint

This branch contains ONLY:
- Infrastructure validation evidence and runbooks
- No send-path logic changes
- No scheduler changes
- No approval behavior changes
- No new execution features
- No new migrations

---

## Unresolved Items

### IA-8 — Staging RESEND_API_KEY differs from production

**Risk if unresolved**: Staging sends (including any accidental or test sends)
would be charged against the production Resend account and could pollute
production delivery metrics or triggering production-level webhook events.

**Steps (Avanish performs in Resend dashboard)**:

```
a. Log into Resend dashboard (resend.com)
b. Navigate to: API Keys
c. Create a new API key named: prospectiq-staging
   Permissions: Sending access only (not full access)
   Domain: leave unrestricted or restrict to a staging domain if available
d. Copy the new key (shown only once)
e. In Railway staging environment → Variables:
   Update RESEND_API_KEY to the new staging key value
f. Confirm the production Railway environment still has the original key
g. Verify the two key values are different:
   - Do NOT paste either key in chat or commit them to git
   - Record evidence as: "staging key prefix differs from production key prefix"
     (e.g., "re_staging_... vs re_prod_..." — first 12 characters only)
```

**Pass condition**: Two distinct Resend API keys exist. Staging Railway env uses
the staging key. Production Railway env uses the production key. The two key
prefixes are observably different.

**Evidence to record below**:
```
Staging key prefix (first 12 chars only, not the full key): ____________
Production key prefix (first 12 chars only): ____________
Staging key created at (Resend dashboard timestamp): ____________
Railway staging RESEND_API_KEY updated at: ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-9 — All INSTANTLY_* and GMAIL_* vars are empty strings in staging

**Risk if unresolved**: If staging inherited production Instantly or Gmail
credentials, any code path that calls the Instantly API or Gmail IMAP would
connect to production systems from the staging environment, potentially
affecting production outreach campaigns or email accounts.

**Steps (Avanish performs in Railway staging dashboard)**:

```
a. Open Railway → ProspectIQ → staging environment → Variables
b. Search for each of the following variable names:
   - INSTANTLY_API_KEY
   - INSTANTLY_CAMPAIGN_ID
   - INSTANTLY_WORKSPACE_ID
   - GMAIL_USER
   - GMAIL_APP_PASSWORD
   (Search for "INSTANTLY" and "GMAIL" to catch any variants)
c. For each variable found:
   - If set to a non-empty value: set it to an empty string ""
   - If absent: no action needed
d. Save / deploy
e. Verify staging health endpoint still returns 200 after the redeploy:
   curl https://prospectiq-staging.up.railway.app/health
```

**Pass condition**: All INSTANTLY_* and GMAIL_* vars are absent or set to empty
string in staging. Health endpoint returns 200 after any changes.

**Evidence to record below**:
```
Variables found in staging (name only, not values):
  INSTANTLY_*: ____________
  GMAIL_*: ____________
Variables cleared (set to ""): ____________
Health endpoint after clearing: ____________
Railway redeploy timestamp: ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-15 — Staging outbound email isolation verified

**Risk if unresolved**: If staging and production Resend keys are shared or
SEND_ENABLED can be enabled without proper isolation, a staging operator could
accidentally send to real prospects.

**Prerequisite**: IA-8 must be PASS (staging has its own Resend API key) before
this test is meaningful.

**Steps (Avanish performs)**:

```
BEFORE:
a. Confirm send_enabled = false on staging:
   psql "$STAGING_DATABASE_URL" -c \
     "SELECT send_enabled FROM outreach_send_config LIMIT 1;"
   Expected: f

b. Note current production contact count (do not modify):
   -- Do NOT run this against production; use the known value: 9,946

TEST:
c. Temporarily set send_enabled = true in staging DB only:
   psql "$STAGING_DATABASE_URL" -c \
     "UPDATE outreach_send_config SET send_enabled = true \
      WHERE workspace_id = '00000000-0000-0000-0000-000000000001';"

d. Trigger a test send to delivered@resend.dev via the staging API:
   curl -X POST https://prospectiq-staging.up.railway.app/api/approvals/test-send \
     -H "Content-Type: application/json" \
     -d '{"test_email": "delivered@resend.dev"}'
   (Use a valid staging draft_id if the endpoint requires one)
   OR use the Resend API directly with the staging key to send a single test message.

e. In Resend staging dashboard (logged in with the staging key account):
   Confirm the test message appears in the Sent log.
   Record: message ID.

f. In Resend production dashboard (logged in with the production key):
   Confirm NO corresponding message appears.
   Record: "no activity in production Resend for this test" or describe what is seen.

RESTORE:
g. Immediately restore send_enabled = false:
   psql "$STAGING_DATABASE_URL" -c \
     "UPDATE outreach_send_config SET send_enabled = false \
      WHERE workspace_id = '00000000-0000-0000-0000-000000000001';"

h. Verify restored:
   psql "$STAGING_DATABASE_URL" -c \
     "SELECT send_enabled FROM outreach_send_config LIMIT 1;"
   Expected: f

i. Run make verify-staging to confirm all guards are green.
```

**Pass condition**: Test message visible only in staging Resend account. Production
Resend account shows no activity for this test. send_enabled restored to false.
make verify-staging passes.

**Evidence to record below**:
```
Pre-test send_enabled value: ____________
Staging Resend message ID from test: ____________
Production Resend activity during test: ____________
Post-test send_enabled value: ____________
make verify-staging result after restore: ____________
Timestamp of RESTORE step: ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-16 — Representative migration replay verified

**Risk if unresolved**: If migrations are not idempotent, a re-application during
disaster recovery or a staging rebuild would corrupt or duplicate data.

**Steps (run in terminal against staging)**:

```bash
# Re-apply each of the three representative migrations a second time.
# Expected: zero ERROR lines; only "already exists" NOTICE lines.

cd /Users/avanish/prospectIQ

echo "=== REPLAY: 002_improvements.sql ==="
psql "$STAGING_DATABASE_URL" \
  -f supabase_migrations/migrations/002_improvements.sql 2>&1

echo "=== REPLAY: 003_contact_events.sql ==="
psql "$STAGING_DATABASE_URL" \
  -f supabase_migrations/migrations/003_contact_events.sql 2>&1

echo "=== REPLAY: 019_sequence_builder_v2.sql ==="
psql "$STAGING_DATABASE_URL" \
  -f supabase_migrations/migrations/019_sequence_builder_v2.sql 2>&1

# Verify row counts unchanged after replay
echo "=== Row count verification ==="
psql "$STAGING_DATABASE_URL" -c \
  "SELECT 'contacts' AS tbl, COUNT(*) FROM contacts
   UNION ALL SELECT 'contact_events', COUNT(*) FROM contact_events
   UNION ALL SELECT 'campaign_sequence_definitions_v2', COUNT(*) FROM campaign_sequence_definitions_v2;"
```

**Pass condition**: Each re-run outputs zero `ERROR:` lines. Any output is
`NOTICE: relation "..." already exists, skipping` or equivalent. Row counts
in affected tables are identical before and after.

**Evidence to record below**:
```
002_improvements.sql replay output (full or summary):

003_contact_events.sql replay output (full or summary):

019_sequence_builder_v2.sql replay output (full or summary):

Row counts before replay:
Row counts after replay (must be identical):
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-17 — Scheduler and provider isolation verified

**Risk if unresolved**: A misconfigured env var in staging could cause the
scheduler (once PR G is deployed) to connect to production DB or send via
production Resend key.

**Steps (Avanish performs in Railway and Supabase dashboards)**:

```
a. Open Railway → ProspectIQ → staging → Deployments → most recent deploy → Logs
   Search logs for: wlyhbdmjhgvovigogdco (production DB ref)
   Expected: zero results — staging logs must never reference the production DB ref
   Record: "No production DB ref found in staging logs" or describe what is found.

b. Confirm staging RESEND_API_KEY ≠ production RESEND_API_KEY (already verified
   in IA-8 if complete — reference that evidence here).

c. Confirm INSTANTLY_* empty in staging (already verified in IA-9 if complete —
   reference that evidence here).

d. Confirm GMAIL_* empty in staging (already verified in IA-9 if complete).

e. Containment reasoning (document as a one-line note):
   "Even if SEND_ENABLED=true were set in staging, the staging RESEND_API_KEY
   has no access to the production Resend account or production contacts because
   [reason: separate API key scoped to staging Resend account / key is not
   shared with production]."
```

**Pass condition**: No production DB ref in staging logs. IA-8 and IA-9 both PASS
(confirming key isolation). Containment reasoning documented.

**Evidence to record below**:
```
Staging log search for wlyhbdmjhgvovigogdco: ____________
IA-8 reference (key isolation confirmed): ____________
IA-9 reference (INSTANTLY/GMAIL cleared): ____________
Containment reasoning: ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-18 — Observability stack verified including intentional failure injection

**Risk if unresolved**: If logs are not visible or the failure detection mechanism
does not work, the team is operating blind from the first day of PR G.

**Steps — five sub-steps**:

#### IA-18a: Railway staging logs
```
Open Railway → ProspectIQ → staging → most recent Deployment → Logs
Confirm: logs are visible, timestamped, searchable.
Record: log retention period shown in the UI (e.g., "7 days").
```

#### IA-18b: Supabase staging query logs
```
Open Supabase → prospectiq-staging → Logs → Postgres
Run this query against staging:
  psql "$STAGING_DATABASE_URL" -c "SELECT COUNT(*) FROM outreach_drafts;"
Wait up to 60 seconds.
Confirm the query appears in the Supabase Logs → Postgres panel.
Record: query visible yes/no; approximate lag.
```

#### IA-18c: Staging smoke test CI
```
Open GitHub → Digitillis/prospectIQ → Actions → CI
Find the most recent run triggered by a push to main that included Phase 0 changes.
Confirm the staging-smoke-test job ran (not skipped) and passed.
Record: GitHub Actions run URL.
```

#### IA-18d: make verify-staging full output
```
Run and save the full output:
  make verify-staging \
    STAGING_URL=https://prospectiq-staging.up.railway.app \
    STAGING_DATABASE_URL="$STAGING_DATABASE_URL"

All three checks must print "OK".
```

#### IA-18e: Intentional failure injection
```
STEP 1 — Corrupt send guard:
  psql "$STAGING_DATABASE_URL" -c \
    "UPDATE outreach_send_config SET send_enabled = true \
     WHERE workspace_id = '00000000-0000-0000-0000-000000000001';"

STEP 2 — Run verify-staging and confirm it FAILS:
  make verify-staging \
    STAGING_URL=https://prospectiq-staging.up.railway.app \
    STAGING_DATABASE_URL="$STAGING_DATABASE_URL"
  Expected: prints "FAIL: send_enabled=t (expected false)" and exits non-zero.

STEP 3 — IMMEDIATELY RESTORE:
  psql "$STAGING_DATABASE_URL" -c \
    "UPDATE outreach_send_config SET send_enabled = false \
     WHERE workspace_id = '00000000-0000-0000-0000-000000000001';"

STEP 4 — Confirm restored:
  make verify-staging \
    STAGING_URL=https://prospectiq-staging.up.railway.app \
    STAGING_DATABASE_URL="$STAGING_DATABASE_URL"
  Expected: all three OK.
```

**Pass condition**: All five sub-steps confirmed. Intentional failure produces
a FAIL exit (not a silent pass). Restoration returns to clean state.

**Evidence to record below**:
```
IA-18a: Railway log retention period: ____________
IA-18b: Supabase query log visible: ____________ / lag: ____________
IA-18c: GitHub Actions run URL (staging-smoke-test passing): ____________
IA-18d: make verify-staging output (paste full):

IA-18e: verify-staging FAIL output (paste the FAIL line):
IA-18e: RESTORE confirmed (final make verify-staging output):
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-13 / IA-19 — Production deployment log shows no unexpected deploys

**Risk if unresolved**: Undetected production deploys during Phase 0 would mean
schema changes or behavior changes reached production without authorization.

**Steps (Avanish performs in Railway dashboard)**:

```
a. Open Railway → ProspectIQ → production environment
b. Click on the production service → Deployments tab
c. Review the deployment history.
   Look for any deployment that occurred AFTER the Phase 0-Infra setup began
   (approximately 2026-05-14 through 2026-05-15).
d. For each deployment found in that window:
   - Record the deploy timestamp
   - Record the triggering commit SHA
   - Confirm it was intentional (matches a known merged PR)
e. Confirm no deploy corresponds to the test push referenced in the plan (I-7-1).
```

**Pass condition**: Every production deployment in the Phase 0 window is
accounted for. No unintended deploys occurred.

**Evidence to record below**:
```
Production deployments since 2026-05-14 (list timestamp + SHA):

Each deployment accounted for: ____________
Any unintended deploys: ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-14 — deploy-production.yml confirmation guard tested

**Risk if unresolved**: If the guard does not actually block on incorrect input,
a mistaken workflow dispatch could deploy to production without intent.

**Steps (Avanish performs in GitHub Actions)**:

```
a. Open GitHub → Digitillis/prospectIQ → Actions → Deploy to Production
b. Click "Run workflow"
c. In the confirmation input, type something WRONG: e.g., "yes" or "deploy"
   (anything other than exactly "deploy-production")
d. Click Run workflow
e. Observe: the "guard" job should fail immediately with:
   "ABORTED: Confirmation text does not match."
   The "deploy" job should not run (it depends on guard).
f. Record: the Actions run URL and result.
g. DO NOT run the workflow with the correct confirmation text "deploy-production"
   unless an actual production deployment is intended.
```

**Pass condition**: Workflow with incorrect confirmation text fails at the guard
job. The deploy job does not execute.

**Evidence to record below**:
```
GitHub Actions run URL (failed guard test): ____________
Guard job result: ____________
Deploy job result (must be "skipped" or "not run"): ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

### IA-20 — Application starts cleanly with empty Instantly/Gmail credentials

**Risk if unresolved**: If empty credentials cause an unhandled exception at
startup, the staging service would be unreliable and any scheduler work could
fail immediately on deploy.

**Steps**:

```
This item is contingent on IA-9 being complete (vars cleared).
After IA-9 is complete and Railway staging has redeployed:

a. Open Railway → ProspectIQ → staging → most recent Deployment → Logs
b. Search logs for any of these patterns:
   - "exception"
   - "unhandled"
   - "AttributeError"
   - "KeyError"
   - "INSTANTLY"
   - "GMAIL"
c. Confirm any Instantly/Gmail references are warnings only (not exceptions).
d. Confirm health endpoint still returns 200:
   curl https://prospectiq-staging.up.railway.app/health
```

**Pass condition**: No unhandled exceptions in startup logs related to missing
Instantly or Gmail credentials. Health endpoint returns 200.

**Evidence to record below**:
```
Log search for "exception" / "INSTANTLY" / "GMAIL": ____________
Any warnings found (warning text, not crash): ____________
Health endpoint result after IA-9 changes: ____________
```

**Result**: [ ] PASS  [ ] FAIL
**Notes**:

---

## Execution Order

Complete items in this order to minimize re-work:

```
1. IA-8    — Create staging Resend key (dashboard, 5 min)
2. IA-9    — Clear INSTANTLY/GMAIL vars in staging (dashboard, 5 min)
             → triggers Railway redeploy automatically
3. IA-20   — Review startup logs after IA-9 redeploy (5 min)
4. IA-16   — Migration replay (terminal, 5 min)
5. IA-18   — Observability + failure injection (terminal + dashboards, 20 min)
6. IA-15   — Send isolation test — requires IA-8 complete (terminal + dashboards, 15 min)
7. IA-17   — Scheduler isolation — references IA-8, IA-9 (dashboards, 10 min)
8. IA-13/IA-19 — Production deploy log review (dashboard, 5 min)
9. IA-14   — Workflow guard test (GitHub Actions, 5 min)
```

Estimated total: 75 minutes of focused work.

---

## Final Recommendation

Complete the evidence fields for all items above before filling in this section.

```
IA-8:    [ ] PASS  [ ] FAIL
IA-9:    [ ] PASS  [ ] FAIL
IA-15:   [ ] PASS  [ ] FAIL
IA-16:   [ ] PASS  [ ] FAIL
IA-17:   [ ] PASS  [ ] FAIL
IA-18:   [ ] PASS  [ ] FAIL
IA-13/19:[ ] PASS  [ ] FAIL
IA-14:   [ ] PASS  [ ] FAIL
IA-20:   [ ] PASS  [ ] FAIL

Overall: [ ] SAFE FOR PR G   [ ] NOT SAFE FOR PR G

Signed off by: _________________________ Date: _____________
```

PR G is not authorized until this section is signed off as SAFE by Avanish.
