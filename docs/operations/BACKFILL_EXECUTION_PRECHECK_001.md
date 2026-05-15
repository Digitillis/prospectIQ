# Backfill Execution Pre-Check — 001
## ProspectIQ — Operator Sign-Off Artifact

**Date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** AWAITING OPERATOR SIGN-OFF — do not execute until all boxes are checked  
**Prerequisite documents:** `BACKFILL_REVIEW_REPORT.md`, `OPERATIONAL_READINESS_ASSESSMENT_001.md`

This document is the authoritative gate before the first `outbound_queue` population event.  
No `--execute` run occurs until Avanish reviews and approves every section.

---

## Section 1 — Current State Confirmation

Before any execution, verify the following invariants hold:

```sql
-- Run this block and confirm all results match expected values
-- before proceeding to any write operation.

SELECT
  (SELECT COUNT(*) FROM outbound_queue)                          AS queue_rows,          -- must be 0
  (SELECT COUNT(*) FROM send_attempts)                           AS attempt_rows,        -- must be 0
  (SELECT send_enabled FROM outreach_send_config LIMIT 1)        AS db_send_enabled,     -- must be false
  (SELECT COUNT(*) FROM outreach_drafts
   WHERE approval_status IN ('approved','edited')
   AND sent_at IS NULL
   AND id NOT IN (SELECT draft_id FROM outbound_queue))          AS backfill_candidates; -- must be 51
```

Expected result: `0 | 0 | false | 51`

If any value differs from expected, STOP and investigate before proceeding.

---

## Section 2 — Pre-Rejection SQL (9 DO NOT BACKFILL Drafts)

### Purpose

These 9 drafts must be set to `approval_status = 'rejected'` before running `backfill_outbound_queue.py --execute`. The backfill script does not filter suppression_log entries; without this step, it will enqueue invalid and bounced-contact records.

### Context

All 9 were identified as ineligible during the 2026-05-15 backfill dry-run analysis documented in `BACKFILL_REVIEW_REPORT.md`. The reasons are: invalid email address (1), hard bounce contact in suppression_log (7), and no email address on contact record (1).

These drafts are being rejected for email delivery ineligibility — not for content quality or business reasons. The `rejection_reason` field stores the specific cause for audit purposes.

### SQL — Copy exact block to psql; do not modify

```sql
BEGIN;

-- ============================================================
-- PRE-ASSERTION: all 9 targets must currently be 'approved'
-- Abort if any have already been rejected or otherwise changed.
-- ============================================================
DO $$
DECLARE
  v_count INT;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM outreach_drafts
  WHERE id IN (
    'd776e831-bc13-4651-ab74-b13dd214dfc7',
    '12be759c-9f1b-4dc7-9b18-adc10b846fa5',
    'b76e0d26-88d9-4db9-81bf-c24f51092043',
    '9292af08-25bc-4c40-814b-6ed40ab84b67',
    '5f0f6510-e480-4eed-abf0-ed8ca75482e5',
    '8f342cc1-a6aa-4926-9fb7-fcce2d5ea823',
    '82774bf8-167c-4041-9f59-5d49d7c39240',
    '79153776-e66e-470f-a287-a1a74733f998',
    '447c9f6f-fe76-47bc-809e-b89d8f52b304'
  )
  AND approval_status NOT IN ('approved', 'edited');

  IF v_count > 0 THEN
    RAISE EXCEPTION
      'Pre-assertion failed: % draft(s) are not in approved/edited state. '
      'Investigate before proceeding.', v_count;
  END IF;
END $$;

-- ============================================================
-- REJECTION 1 — Invalid email address
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: email_status=invalid (culbrich@ulbrich.com). Identified in backfill review 2026-05-15.',
  rejection_category = 'email_ineligible',
  updated_at         = NOW()
WHERE id = 'd776e831-bc13-4651-ab74-b13dd214dfc7'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 2 — Hard bounce contact
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact in suppression_log (john.hammerle@ermco-eci.com, 2026-05-13). Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = '12be759c-9f1b-4dc7-9b18-adc10b846fa5'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 3 — Hard bounce contact
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact in suppression_log (ken.michiels@fike.com, 2026-05-04). Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = 'b76e0d26-88d9-4db9-81bf-c24f51092043'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 4 — Hard bounce contact
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact in suppression_log (chad.kruger@fike.com, 2026-05-04). Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = '9292af08-25bc-4c40-814b-6ed40ab84b67'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 5 — Hard bounce contact + domain suppression
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact (2026-05-13) AND hard_bounce_domain (flexsteelpipe.com, 2026-05-14) in suppression_log (bruce.bratton@flexsteelpipe.com). Domain-level block applies to all future flexsteelpipe.com contacts. Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = '5f0f6510-e480-4eed-abf0-ed8ca75482e5'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 6 — Hard bounce contact
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact in suppression_log (laurie_barton@crlaurence.com, 2026-05-13). Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = '8f342cc1-a6aa-4926-9fb7-fcce2d5ea823'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 7 — Hard bounce contact
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact in suppression_log (chrichardson@martinsprocket.com, 2026-05-04). Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = '82774bf8-167c-4041-9f59-5d49d7c39240'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 8 — Hard bounce contact
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: hard_bounce_contact in suppression_log (randres@prent.com, 2026-05-13). Identified in backfill review 2026-05-15.',
  rejection_category = 'hard_bounce',
  updated_at         = NOW()
WHERE id = '79153776-e66e-470f-a287-a1a74733f998'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- REJECTION 9 — No email address on contact record
-- ============================================================
UPDATE outreach_drafts SET
  approval_status    = 'rejected',
  rejection_reason   = 'email_ineligible: no email address on associated contact record (Cincinnati Incorporated). Cannot dispatch without recipient address. Identified in backfill review 2026-05-15.',
  rejection_category = 'email_ineligible',
  updated_at         = NOW()
WHERE id = '447c9f6f-fe76-47bc-809e-b89d8f52b304'
  AND approval_status IN ('approved', 'edited');

-- ============================================================
-- POST-ASSERTION: confirm all 9 are now 'rejected'
-- ============================================================
DO $$
DECLARE
  v_count INT;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM outreach_drafts
  WHERE id IN (
    'd776e831-bc13-4651-ab74-b13dd214dfc7',
    '12be759c-9f1b-4dc7-9b18-adc10b846fa5',
    'b76e0d26-88d9-4db9-81bf-c24f51092043',
    '9292af08-25bc-4c40-814b-6ed40ab84b67',
    '5f0f6510-e480-4eed-abf0-ed8ca75482e5',
    '8f342cc1-a6aa-4926-9fb7-fcce2d5ea823',
    '82774bf8-167c-4041-9f59-5d49d7c39240',
    '79153776-e66e-470f-a287-a1a74733f998',
    '447c9f6f-fe76-47bc-809e-b89d8f52b304'
  )
  AND approval_status = 'rejected';

  IF v_count <> 9 THEN
    RAISE EXCEPTION
      'Post-assertion failed: expected 9 rejected rows, found %. '
      'Rolling back — investigate before retrying.', v_count;
  END IF;
END $$;

-- ============================================================
-- COMMIT only if all assertions passed
-- ============================================================
COMMIT;
```

### Post-execution verification

After the transaction commits, run:

```sql
-- Confirm 9 rejected, 42 remaining eligible
SELECT approval_status, COUNT(*)
FROM outreach_drafts
WHERE id IN (
  'd776e831-bc13-4651-ab74-b13dd214dfc7',
  '12be759c-9f1b-4dc7-9b18-adc10b846fa5',
  'b76e0d26-88d9-4db9-81bf-c24f51092043',
  '9292af08-25bc-4c40-814b-6ed40ab84b67',
  '5f0f6510-e480-4eed-abf0-ed8ca75482e5',
  '8f342cc1-a6aa-4926-9fb7-fcce2d5ea823',
  '82774bf8-167c-4041-9f59-5d49d7c39240',
  '79153776-e66e-470f-a287-a1a74733f998',
  '447c9f6f-fe76-47bc-809e-b89d8f52b304'
)
GROUP BY approval_status;
-- Expected: rejected | 9

SELECT COUNT(*) AS remaining_eligible
FROM outreach_drafts
WHERE approval_status IN ('approved','edited')
  AND sent_at IS NULL
  AND id NOT IN (SELECT draft_id FROM outbound_queue);
-- Expected: 42
```

---

## Section 3 — REVIEW Package (6 Drafts — Avanish Decision Required)

Each entry below provides: the specific concern that triggered REVIEW classification, the actual delivery risk in plain terms, the business value of the contact, a recommendation, and a confidence level.

---

### REVIEW-1: jmondello@vicorpower.com

| Field | Value |
|-------|-------|
| Draft ID | `870b2cfd-f24d-4508-891f-357f40a35c8e` |
| Email | jmondello@vicorpower.com |
| Name / Title | Joe Mondello — Manager, Continuation Engineering / RMA |
| Company | Vicor |
| Sequence step | 1 (initial touch) |
| Draft age | 43 days (created 2026-04-02) |
| Email status | `unverified` |

**Why REVIEW?** Two independent risk factors compound: email is unverified (ZeroBounce could not confirm delivery) and the draft is 43 days old (extreme cold-outreach staleness).

**Delivery risk:** Unverified addresses carry a meaningfully higher bounce probability. A hard bounce from vicorpower.com would enter the suppression_log and block all future Vicor outreach via that contact. The 43-day gap also means the draft content likely references market context that is no longer fresh.

**Business value:** Continuation Engineering / RMA is a middle-manager role, not a direct buyer of operational intelligence. Vicor is a solid power electronics company but this specific contact's title limits the likelihood of conversion.

**Recommendation: EXCLUDE.** The combination of unverified email + extreme staleness + non-ideal title creates more downside risk (bounce, domain flag) than upside value. If Vicor is a target account, run ZeroBounce verify on this address and regenerate a fresh draft before including.

**Confidence: HIGH EXCLUDE**

**Actions if Avanish overrides to INCLUDE:**
1. Run ZeroBounce verify on `jmondello@vicorpower.com` before backfill
2. Review and potentially refresh the 43-day-old draft body before enqueue

---

### REVIEW-2: jgondkoff@upmet.com

| Field | Value |
|-------|-------|
| Draft ID | `73a58bef-6af3-41c1-89fe-6165cc646a46` |
| Email | jgondkoff@upmet.com |
| Name / Title | Josh Gondkoff — General Manager |
| Company | United Performance Metals |
| Sequence step | 1 (initial touch) |
| Draft age | 12 days (created 2026-05-03) |
| Email status | `catch_all` |

**Why REVIEW?** `catch_all` means the upmet.com mail server accepts all delivery attempts regardless of whether the specific mailbox exists. ZeroBounce cannot confirm whether `jgondkoff@upmet.com` is a live inbox.

**Delivery risk:** Catch_all domains do not generate hard bounces at the SMTP level — the risk is a soft bounce or silent discard after delivery. The email will appear delivered in Resend logs. If the address is invalid at the application layer, it won't enter suppression_log; no domain reputation damage.

**Business value:** General Manager at a specialty metals distributor is a high-value title. United Performance Metals is a relevant manufacturing-sector account. This contact is worth the moderate delivery uncertainty.

**Recommendation: INCLUDE.** The bounded delivery risk (soft bounce or discard, not hard bounce) paired with a high-value title and fresh draft (12 days) makes this worth including. Accept the catch_all uncertainty.

**Confidence: MEDIUM-HIGH INCLUDE**

---

### REVIEW-3: kathyw@gwfg.com

| Field | Value |
|-------|-------|
| Draft ID | `34b43c7d-f781-4f14-9275-a26e2f6351f9` |
| Email | kathyw@gwfg.com |
| Name / Title | Kathy Weitmann — COO Private Label and Shared Services |
| Company | Golden West Food Group |
| Sequence step | 2 (follow-up) |
| Draft age | 9 days (created 2026-05-06) |
| Email status | `catch_all` |

**Why REVIEW?** `catch_all` domain.

**Delivery risk:** Same bounded risk as REVIEW-2 — no hard bounce risk from catch_all. Critically, this is a step-2 draft, which means step-1 was dispatched to this exact address (`kathyw@gwfg.com`) and was classified as `sent`. If the address were invalid, the step-1 would have hard bounced and entered suppression_log. The confirmed step-1 delivery provides meaningful confidence that this address is live.

**Business value:** COO-level at a food group company — high-value decision-maker title. The step-2 follow-up is the right timing to capitalize on any step-1 visibility.

**Recommendation: INCLUDE.** The step-1 delivery effectively validates the address, negating the primary catch_all concern. COO title with 9-day-old follow-up timing makes this one of the stronger REVIEW candidates.

**Confidence: HIGH INCLUDE**

---

### REVIEW-4: tzwiebel@rudolphfoods.com

| Field | Value |
|-------|-------|
| Draft ID | `8a1d3964-bf5e-42fd-a392-b2f28456cbde` |
| Email | tzwiebel@rudolphfoods.com |
| Name / Title | Todd Zwiebel — Director of QA |
| Company | Rudolph Foods |
| Sequence step | 2 (follow-up) |
| Draft age | 6 days (created 2026-05-09) |
| Email status | `unverified` |

**Why REVIEW?** Email is `unverified`.

**Delivery risk:** Unverified carries hard bounce risk. However, same mitigating logic as REVIEW-3: this is a step-2 draft, meaning step-1 was dispatched to `tzwiebel@rudolphfoods.com` and reached `sent` status. A non-deliverable address would have surfaced as a hard bounce in the step-1 attempt.

**Business value:** Director of QA at a snack food manufacturer. Rudolph Foods is a solid manufacturing sector account. Director-level title is a genuine buyer profile for operational intelligence.

**Recommendation: INCLUDE.** The step-1 delivery provides effective address confirmation. Fresh draft (6 days), coherent follow-up, relevant title, real manufacturing company.

**Confidence: HIGH INCLUDE**

---

### REVIEW-5: ronny.hoff@alterainfra.com

| Field | Value |
|-------|-------|
| Draft ID | `f24e49a0-5413-40ce-abba-2a888fe224e2` |
| Email | ronny.hoff@alterainfra.com |
| Name / Title | Ronny Hoff — Project Process and Systems Manager |
| Company | Altera Infrastructure |
| Sequence step | 1 (initial touch) |
| Draft age | 11 days (created 2026-05-03) |
| Email status | `null` (ZeroBounce not run) |

**Why REVIEW?** `null` email_status — ZeroBounce was never run on this address. No delivery data exists.

**Delivery risk:** Without ZeroBounce data, hard bounce probability is unknown. If the address is invalid, a bounce would enter suppression_log and Resend may flag the event. This is a first touch (step-1), so there is no prior delivery to validate the address.

**Business value:** Project Process and Systems Manager at Altera Infrastructure (offshore energy infrastructure operations). Moderate-to-strong profile for operational tech. The title suggests someone who manages operational workflows — relevant buyer profile.

**Recommendation: VERIFY THEN INCLUDE.** Run ZeroBounce verify (`ronny.hoff@alterainfra.com`) before backfill decision. If result is `verified` or `catch_all` → include. If `invalid` or `do_not_mail` → exclude and pre-reject. If `unknown` → operator judgment.

**Confidence: CONDITIONAL — high if verified, high exclude if invalid**

---

### REVIEW-6: yina.hernandez@richlinegroup.com

| Field | Value |
|-------|-------|
| Draft ID | `33c5604a-75ad-4427-b917-e020934b9ba3` |
| Email | yina.hernandez@richlinegroup.com |
| Name / Title | Yina Hernandez — Encargada de Gestión Humana (Human Resources Manager) |
| Company | Richline Group, a Berkshire Hathaway Company |
| Sequence step | 1 (initial touch) |
| Draft age | 14 days (created 2026-04-30) |
| Email status | `null` (ZeroBounce not run) |

**Why REVIEW?** `null` email_status — ZeroBounce never run.

**Delivery risk:** Same unknown-address risk as REVIEW-5. Step-1 with no prior delivery validation.

**Business value:** This is the weakest REVIEW candidate on both dimensions simultaneously:
1. **Wrong role:** "Encargada de Gestión Humana" is a Spanish-language HR/People manager title. HR managers do not purchase or evaluate operational intelligence platforms.
2. **Wrong vertical alignment:** Richline Group is a jewelry manufacturer and distributor (Berkshire Hathaway subsidiary). The manufacturing profile is not aligned with heavy industrial / discrete manufacturing focus.

**Recommendation: EXCLUDE.** Wrong role, likely-misaligned vertical, null email status compounds the risk. Even if the email is valid, this contact is unlikely to be a conversion pathway. Excluding saves one delivery slot for a better-qualified prospect.

**Confidence: HIGH EXCLUDE**

---

### REVIEW Decision Summary

| Draft ID | Contact | Recommendation | Confidence |
|----------|---------|---------------|------------|
| `870b2cfd` | jmondello@vicorpower.com | EXCLUDE | HIGH |
| `73a58bef` | jgondkoff@upmet.com | INCLUDE | MEDIUM-HIGH |
| `34b43c7d` | kathyw@gwfg.com | INCLUDE (step-1 confirmed) | HIGH |
| `8a1d3964` | tzwiebel@rudolphfoods.com | INCLUDE (step-1 confirmed) | HIGH |
| `f24e49a0` | ronny.hoff@alterainfra.com | VERIFY THEN INCLUDE/EXCLUDE | CONDITIONAL |
| `33c5604a` | yina.hernandez@richlinegroup.com | EXCLUDE (wrong role/vertical) | HIGH |

**If Avanish accepts all recommendations:** Include 3 (jgondkoff, kathyw, tzwiebel) + conditional 1 (ronny.hoff pending verify) + exclude 2. This brings total SAFE-to-backfill count to 39 or 40 depending on REVIEW-5 verify result.

---

## Section 4 — Operational Cohort Recommendation (Stage B)

Per the `OPERATIONAL_READINESS_ASSESSMENT_001.md` recommendation, do NOT enqueue all eligible drafts simultaneously. Enqueue a small operational cohort first to validate queue behavior under populated conditions before scaling.

### Recommended initial cohort (8 drafts)

Selection criteria applied: verified email, no concentration risk, step diversity, no staleness, varied industries.

| Draft ID | Contact | Company | Step | Age (days) |
|----------|---------|---------|------|------------|
| `8a1d3964` | tzwiebel@rudolphfoods.com | Rudolph Foods | 2 | 6 |
| `34b43c7d` | kathyw@gwfg.com | Golden West Food Group | 2 | 9 |
| One Eos Energy contact (TBD: jmastrangelo or jgreggs or jmahaz) | Eos Energy | 2 | 5 |
| One Potters Industries contact | Potters Industries | 1 | TBD |
| One Global Advanced Metals contact | Global Advanced Metals | 1 | TBD |
| One AriensCo contact | AriensCo | 1 or 2 | TBD |
| jgondkoff@upmet.com (if included) | United Performance Metals | 1 | 12 |
| One additional verified step-1 from 7–14-day bucket | Various | 1 | 7–14 |

**Purpose:** validate that `reclaim_stale_locks` handles populated queue rows correctly, `claim_outbound_queue_batch()` returns the right rows in priority order, and lock lifecycle is clean — all while SEND_ENABLED=false keeps sends inert.

**The remaining SAFE drafts** (28+ depending on REVIEW decisions) should be enqueued in a second pass after DARK_LAUNCH_RUNTIME_OBSERVATION_002 confirms clean behavior.

---

## Section 5 — Operator Sign-Off Checklist

This checklist must be fully checked before any `--execute` is run.

### R1 — Pre-rejection (Section 2)
```
[ ] I have read the 9 draft entries above and confirm the rejection reasons are correct
[ ] I have run the Section 2 SQL block against production DB
[ ] The post-assertion confirmed 9 rejected rows
[ ] The remaining-eligible count confirmed 42
```

### R2 — REVIEW decisions (Section 3)
```
[ ] I have reviewed each REVIEW draft entry
[ ] REVIEW-1 (jmondello): decision = INCLUDE / EXCLUDE
[ ] REVIEW-2 (jgondkoff): decision = INCLUDE / EXCLUDE
[ ] REVIEW-3 (kathyw): decision = INCLUDE / EXCLUDE
[ ] REVIEW-4 (tzwiebel): decision = INCLUDE / EXCLUDE
[ ] REVIEW-5 (ronny.hoff): ZeroBounce run = YES / NO; result = ______; decision = INCLUDE / EXCLUDE
[ ] REVIEW-6 (yina.hernandez): decision = INCLUDE / EXCLUDE
```

### R3 — Environment confirmation
```
[ ] I have confirmed SEND_ENABLED=false in Railway production env
    (curl https://prospectiq-production-4848.up.railway.app/api/admin/send-config)
    env_send_enabled must be false
[ ] I have confirmed outbound_queue row count = 0 immediately before --execute
[ ] I have confirmed DB send_enabled = false
```

### R4 — Concentration gating (recommended)
```
[ ] Eos Energy: confirmed only 1 of 3 contacts will be in initial cohort
[ ] Ulbrich: confirmed only dplum in initial run (dorozco deferred)
[ ] Aluminum Precision: confirmed gbornman (step-2) goes first; hharwood/ctodd reviewed for staleness
```

### Final authorization
```
[ ] All R1–R3 boxes above are checked
[ ] I, Avanish Mehrotra, authorize execution of:
    python scripts/backfill_outbound_queue.py --execute
    on production with the initial cohort defined above
[ ] Authorized date/time (CDT): ____________________
```

---

## Section 6 — Post-Execution Verification

After `--execute` completes, run immediately:

```sql
-- Confirm row count matches cohort size
SELECT COUNT(*) FROM outbound_queue;
-- Must equal number of drafts in selected cohort (not 42)

-- Confirm no locks exist (freshly enqueued rows should be unlocked)
SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Must be 0

-- Confirm no send_attempts were created (sends must remain inert)
SELECT COUNT(*) FROM send_attempts;
-- Must be 0

-- Confirm draft statuses unchanged
SELECT approval_status, COUNT(*)
FROM outreach_drafts
WHERE id IN (SELECT draft_id FROM outbound_queue)
GROUP BY approval_status;
-- All should still be 'approved' (enqueue does not change approval_status)

-- Spot check priority ordering
SELECT od.contact_id, oq.priority, oq.enqueued_at
FROM outbound_queue oq
JOIN outreach_drafts od ON od.id = oq.draft_id
ORDER BY oq.priority ASC, oq.enqueued_at ASC
LIMIT 10;
```

After the next scheduler tick (within 2 minutes — reclaim_stale_locks):

```sql
-- Confirm reclaim job ran cleanly (rows should remain unlocked)
SELECT COUNT(*) FROM outbound_queue WHERE locked_by IS NOT NULL;
-- Must be 0 (no dispatch has run; locks should never have been set)
```

---

## Section 7 — Rollback Procedure

If any post-execution verification fails, or if any unintended writes are observed:

```sql
-- Emergency rollback: remove all queue rows (does not affect outreach_drafts)
BEGIN;
DELETE FROM outbound_queue;
DELETE FROM send_attempts;
COMMIT;

-- Verify rollback
SELECT COUNT(*) FROM outbound_queue;   -- must be 0
SELECT COUNT(*) FROM send_attempts;    -- must be 0
```

The `backfill_outbound_queue.py` script uses `approve_draft_and_enqueue()` which calls `ON CONFLICT DO NOTHING`. Re-running `--execute` after rollback is safe — it will re-insert without creating duplicates.

The pre-rejection SQL (Section 2) uses `rejection_reason` to record the reason. Rejection is intentionally not rolled back — those 9 drafts are ineligible regardless.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/BACKFILL_EXECUTION_PRECHECK_001.md`  
**This document supersedes:** the informal prerequisite checklist in `OPERATIONAL_READINESS_ASSESSMENT_001.md Section H`
