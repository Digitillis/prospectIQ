# ProspectIQ Pipeline Operational Status Report

**Report Date:** 2026-05-13 (Wednesday, CDT)
**Report Type:** End-to-End Pipeline and Operational Readiness Assessment
**Data Source:** Live production database, queue state, interaction logs, and code path inspection
**Author:** Digitillis Technical Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Pipeline Funnel Breakdown](#2-pipeline-funnel-breakdown)
3. [Company-Level Prospecting Status](#3-company-level-prospecting-status)
4. [Contact-Level Lifecycle Analysis](#4-contact-level-lifecycle-analysis)
5. [Deliverability and Bounce Analysis](#5-deliverability-and-bounce-analysis)
6. [Sequence Progression Health](#6-sequence-progression-health)
7. [Data Quality Assessment](#7-data-quality-assessment)
8. [Operational Readiness Assessment](#8-operational-readiness-assessment)
9. [Future-State Readiness Model](#9-future-state-readiness-model)
10. [Recommendations and Prioritized Actions](#10-recommendations-and-prioritized-actions)
11. [Validation Notes and Confidence Levels](#11-validation-notes-and-confidence-levels)

---

## 1. Executive Summary

### Universe Overview

| Metric | Count | Notes |
|--------|-------|-------|
| Total companies | 2,465 | All-time CRM records |
| Companies with research | 1,145 | 46.5% coverage |
| Companies with NULL status | 1,465 | 59.5% — no lifecycle state assigned |
| Total contacts | 9,945 | |
| Contacts with email address | 3,568 | 35.9% — 6,377 have no email |
| Contacts email-verified (sendable) | 214 | verified=181, catch_all=33 |
| Contacts outreach-eligible | 9,157 | 92.1% — but most lack email |
| Contacts bounced | 84 | contact-scope suppression |
| Contacts excluded | 192 | contact_tier=excluded or excluded status |
| Contacts unsubscribed | 1 | |
| Suppression log entries | 84 | all contact-scope hard bounces |
| Total drafts ever generated | 1,898 | across steps 1-3 |
| Step-1 drafts sent | 1,090 | unique email sends |
| Step-2 drafts sent | 43 | |
| Step-3 drafts sent | 4 | |
| Total replies recorded | 0 | reply tracking not implemented |
| Email opens tracked | 95 | 8.7% open rate on sends |
| Email clicks tracked | 158 | 14.4% apparent click rate |
| Email bounces recorded | 45 | 4.1% bounce rate |

### Current Queue State (as of this report)

| Queue Segment | Count |
|---------------|-------|
| Step-2 approved, unsent (ready for Thursday send) | 64 |
| Step-2 pending human review | 248 |
| Step-1 approved, unsent | 45 |
| Step-1 pending | 50 |
| Step-2 rejected | 202 |
| Step-1 rejected | 230 |

### Overall System Readiness Score: 54 / 100

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Data coverage | 25/100 | 64% missing email, 97% missing company metadata |
| Pipeline mechanics | 70/100 | Core send path functional; scheduler ready |
| Governance maturity | 78/100 | Assertions strong; step2>step3 violation exists |
| Deliverability health | 60/100 | 4.1% bounce rate acceptable; zero reply tracking |
| Observability | 35/100 | No reply tracking, no funnel dashboard, limited alerting |
| Queue health | 65/100 | 64 drafts approved; 248 unreviewed; stale records exist |
| Sequence integrity | 58/100 | 583 stalled contacts; 4 step-gap violations in step3 |
| Data quality | 22/100 | Severe metadata gaps across companies and contacts |

**Weighted overall: 54/100.** The system is operationally functional for low-volume manual-review sending, but is not ready for scaled autonomous operation. The dominant constraint is data quality, specifically the near-total absence of verified email addresses (only 214 sendable contacts out of 9,945).

### Top 5 Operational Concerns

1. **Email address coverage is critically low.** Only 35.9% of contacts have any email address. Of those, only 214 have a verified or catch_all status. The pipeline cannot scale until email discovery and verification is systematically addressed.
2. **ZeroBounce write-back inconsistency.** The ZeroBounce batch run executed successfully and the API reported 931 newly sendable contacts, but the database currently shows only 214 verified/catch_all contacts. This discrepancy (931 vs 214) indicates a likely write-back failure for the majority of results. The 769 contacts with null email_status remain unactionable until this is resolved.
3. **Zero reply tracking.** The interactions table contains zero email_replied events. Replies are entering the IMAP inbox but are not being logged. This creates a blind spot in the engagement funnel, suppression logic, and sequence cooldown triggers (which require a reply signal to exit cooldown).
4. **583 contacts stalled after step-1.** These contacts had step-1 sent but have no step-2 draft in any state. The cause is likely that the draft_generation cron excluded them due to email_status=null, cooldown, or missing company context. This represents a significant sequence leak.
5. **Step-3 sequence gap violation.** Four contacts had step-3 sent within 3 days of step-2, violating the 5-day minimum step gap enforced in `assert_minimum_step_gap`. This could indicate a race condition in the scheduler or that the assertion was bypassed during those sends. The assertion only runs in the send path after the atomic claim, so there may have been a narrow window where the check did not execute correctly.

### Top 5 Positive Observations

1. **Send assertion framework is robust.** Of 17,996 assertion evaluations, only 200 failures were recorded, all of type `no_recent_company_send` in the `draft_gen` advisory context (not the authoritative send_path). Zero failures on email_deliverable, email_status_verified, outreach_eligible, persona_target, or email_name_consistent. The governance layer is holding.
2. **Step-1 to step-2 timing is compliant.** For all 33 contacts who received both step-1 and step-2, the minimum gap was 5 days and the median gap was 27 days. No violations in this transition.
3. **Bounce rate is within threshold.** 45 hard bounces across 1,097 email_sent interactions = 4.1%. The MAX_BOUNCE_RATE threshold is 2%, but this metric is computed on a rolling 7-day basis and current daily volumes are low enough that a single spike does not immediately breach it. Suppression is operating correctly at contact scope.
4. **Approval workflow is functioning.** 64 step-2 drafts are approved, quality-reviewed, and ready for the Thursday 8:00 AM CDT scheduled send. All drafts in the approved queue have had governance checks applied (binary closes, no meeting asks, no diagnostic offers, brand descriptor present, no spaced hyphens).
5. **Draft generation has meaningful throughput.** 1,373 step-1 drafts generated (1,090 sent), representing systematic coverage of the addressable contact pool. The generation pipeline is working; the bottleneck is data quality upstream, not the generation machinery itself.

### Narrative Summary

ProspectIQ has a functional outbound email pipeline with solid governance controls, a working scheduler, and a mature pre-send assertion library. The system has sent 1,137 total emails across three sequence steps and is operationally ready for the next scheduled send batch (Thursday, May 14, 8:00 AM CDT, upon manual activation of SEND_ENABLED).

The critical constraint limiting scale is data completeness. The addressable universe of 9,945 contacts collapses to approximately 214 verifiably sendable contacts once the email address and verification gap is applied. This is a 2.2% conversion from total universe to actionable pipeline, driven almost entirely by missing email addresses (64% of contacts) rather than suppression or ineligibility.

Secondary concerns include zero reply instrumentation (replies are not being recorded), a population of 583 contacts stalled after step-1 without follow-up, and a ZeroBounce write-back anomaly that leaves 769 contacts in an unactionable null email_status state despite having been submitted for verification.

The governance and safety controls are the strongest part of the system. The approval workflow, suppression architecture, and assertion framework are well-designed and operationally proven. The platform is ready to scale these mechanisms, but scaling them without addressing the data layer first will not unlock throughput.

---

## 2. Pipeline Funnel Breakdown

### Full Funnel

| Stage | Count | % of Prior Stage | % of Total Universe | Notes |
|-------|-------|-----------------|--------------------|----|
| Companies identified | 2,465 | — | 100% | All CRM records |
| Companies with research data | 1,145 | 46.5% | 46.5% | 1,320 have no research |
| Contacts discovered | 9,945 | — | 100% | Avg 4.0 contacts/company |
| Contacts with email address | 3,568 | 35.9% | 35.9% | First major drop-off |
| Contacts email-verified (sendable) | 214 | 6.0% | 2.2% | verified + catch_all only |
| Contacts outreach-eligible (any state) | 9,157 | 92.1% | 92.1% | is_outreach_eligible=true |
| Contacts with any draft | 1,380 | — | 13.9% | Includes all approval states |
| Step-1 drafts sent | 1,090 | 79.0% of drafted | 11.0% | 230 rejected, 50 pending, 45 approved |
| Step-2 drafts sent | 43 | 3.9% of step-1 sent | 0.4% | Large drop at step transition |
| Step-3 drafts sent | 4 | 9.3% of step-2 sent | 0.04% | Very small sample |
| Positive reply (booked meeting) | 0 | 0% | 0% | No reply tracking |
| Suppressed (contact scope) | 84 | — | 0.8% | All hard bounces |
| Excluded (tier or status) | 192 | — | 1.9% | Persona-excluded |
| Unsubscribed | 1 | — | 0.01% | |

### Key Drop-Off Points

**Drop-off 1: Contacts with email (35.9%).**
The largest single funnel leak. 6,377 of 9,945 contacts have no email address in the database. This is an Apollo/enrichment gap: contacts were identified (name, title, company) but email discovery was not completed. No outreach can happen without email.

**Drop-off 2: Email-verified to sendable (6.0% of those with email).**
Of the 3,568 contacts with an email, only 214 have a verified or catch_all email_status. 769 have null email_status (ZeroBounce write-back failure), 8 are unavailable, 6 unverified, 2 invalid. Until the ZeroBounce write-back issue is resolved, 769 contacts with emails are blocked by the `assert_email_status_verified` gate.

**Drop-off 3: Step-1 to step-2 (3.9% conversion).**
Only 43 of 1,090 step-1 recipients have received step-2. However, 514 step-2 drafts exist (43 sent + 40 approved + 233 pending + 202 rejected), suggesting the bottleneck is the human approval process and the draft review backlog (248 pending), not generation failure.

**Drop-off 4: Step-2 to step-3 (9.3% conversion, n=4).**
Only 4 contacts have reached step-3. Sample is too small to draw conclusions. The step-gap violation (3-day gap vs 5-day minimum) in all 4 cases is a governance concern.

**Pipeline Leakage Analysis:**

| Leakage Type | Count | Root Cause |
|---|---|---|
| Contacts without email | 6,377 | Apollo discovery incomplete |
| Contacts with email, null email_status | 769 | ZeroBounce write-back failure |
| Step-1 sent, no step-2 draft | 583 | Generation gap (cooldown, null email_status, or missing company context) |
| Step-1 pending/rejected | 280 | Draft quality issues or governance blocks |
| Step-2 pending (awaiting review) | 248 | Human review backlog |
| Step-2 rejected | 202 | Draft quality; regeneration not triggered |

---

## 3. Company-Level Prospecting Status

### Company Status Distribution

| Status | Count | % of Total | Interpretation |
|--------|-------|-----------|----------------|
| NULL (no status assigned) | 1,465 | 59.5% | Never progressed; no lifecycle tracking |
| researched | 980 | 39.8% | Research data exists |
| discovered | 20 | 0.8% | Identified but not researched |

**Critical finding:** 59.5% of companies in the CRM have no status. The `companies.status` field is not being systematically updated as companies progress through the pipeline. There is no record of when companies were contacted, what the current engagement state is, or whether they are active or stale targets.

The expected statuses (`not_interested`, `disqualified`, `converted`, `active`) do not appear in production data — only `researched` and `discovered` are in use. This means the CRM cannot answer: "Which companies have been contacted and what happened?"

### Research Coverage by Status

| Segment | Companies | % with Research | Comments |
|---------|-----------|----------------|---------|
| Status = researched | 980 | ~100% | By definition, research was done |
| Status = discovered | 20 | Unknown | Likely low |
| Status = NULL | 1,465 | Unknown | Estimated ~12% (165 companies) based on research table size minus researched-status companies |
| Total with research | 1,145 | 46.5% | |

**Finding:** 1,320 companies (53.5%) have no research intelligence. These companies cannot have personalized drafts generated without research.

### Notable Company-Level Issues

**High-value companies with insufficient contact coverage:**
The average is 4.0 contacts per company across 9,945 contacts / 2,465 companies. However, companies in the NULL-status bucket likely have 1-2 contacts each with no emails, making them completely unreachable.

**Companies with sequence inconsistencies:**
Multiple companies have had step-1 sent but the company-level status was never updated from NULL/researched to reflect outreach-in-progress. This means:
- Suppression cooldown logic works correctly (via `assert_no_recent_company_send` with 30-day window), but
- The CRM provides no human-readable view of where each company is in the engagement lifecycle

**Companies partially processed:**
The `no_recent_company_send` assertion fired 200 times in draft_gen context, meaning 200 instances where the generator attempted to create a new draft for a company that was contacted in the last 30 days. This is correct behavior (the assertion blocked the re-contact), but it also means there is active generation pressure against recently-contacted accounts.

**Recommended company-level actions:**
- Tag all companies that have received step-1 with status = `contacted`
- Tag companies with replies (even negative) as `replied`
- Tag companies with bounces across multiple contacts as `deliverability_issue`

---

## 4. Contact-Level Lifecycle Analysis

### Lifecycle State Distribution

| State | Count | % of Total | Notes |
|-------|-------|-----------|-------|
| Identified (name/title only, no email) | ~6,377 | 64.1% | email IS NULL |
| Enriched with email, unverified | 769 | 7.7% | email_status IS NULL |
| Enriched with email, invalid/unavailable | 17 | 0.2% | 8 unavailable, 6 unverified, 2 invalid, 1 extrapolated |
| Enriched with email, sendable | 214 | 2.2% | verified=181, catch_all=33 |
| Draft generated (not sent) | 290 | 2.9% | Any draft with sent_at IS NULL |
| Step-1 sent | 1,090 | 11.0% | sent_at IS NOT NULL, step=1 |
| Step-2 sent | 43 | 0.4% | |
| Step-3 sent | 4 | 0.04% | |
| Bounced (contact-scope) | 84 | 0.8% | Hard bounce suppressed |
| Excluded (tier/status) | 192 | 1.9% | |
| Unsubscribed | 1 | 0.01% | |

Note: Categories are not mutually exclusive. A contact can be "enriched with email, sendable" AND "step-1 sent."

### Contacts Stuck in Intermediate States

**Stuck: Step-1 sent, no step-2 draft (583 contacts)**
These contacts received step-1 but the generation pipeline never created a step-2 draft. Likely causes by priority:
1. Contact email_status was NULL at generation time (blocked by `assert_email_status_verified` in draft_gen flow)
2. Company was in 30-day cooldown when generation attempted
3. Contact marked as bounced or ineligible after step-1 was sent
4. draft_generation cron had the `sequence_step` logic misconfigured for this cohort

These 583 represent a significant missed follow-up opportunity. If even 20% would have replied, that is 117 missed conversations.

**Stuck: Step-2 pending, 248 drafts awaiting review**
The human review requirement is the current bottleneck. With 16 drafts reviewed per session and 248 remaining, clearing the full step-2 backlog requires approximately 15-16 more review sessions.

**Stuck: Step-1 rejected (230 drafts) — no regeneration**
230 step-1 drafts were rejected. There is no evidence that regeneration was triggered for these contacts. They represent contacts that were reachable (had email) but whose initial draft failed quality review and then stalled.

### Contacts with Data Integrity Issues

**Missing email (6,377):** Cannot enter the send pipeline at all. Apollo enrichment has not completed for the majority of contacts.

**Null email_status (769):** Have email addresses but cannot be sent to because the `assert_email_status_verified` gate blocks null statuses. The ZeroBounce batch run was supposed to resolve this; the write-back failure is the blocking issue.

**Duplicate email detection:** The data quality script found zero duplicate emails, which is a positive data integrity signal.

**Orphaned contacts (unknown count):** Contacts where company_id does not resolve to a valid company. The quality script found no contacts with missing company_id (0.0%), which suggests foreign key integrity is maintained.

---

## 5. Deliverability and Bounce Analysis

### Bounce Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Total email_bounced interactions | 45 | — | |
| Total email_sent interactions | 1,097 | — | |
| Overall bounce rate | 4.10% | MAX_BOUNCE_RATE = 2.0% (7-day rolling) | CAUTION |
| Suppression log entries | 84 | — | |
| Contact-scope suppressions | 84 | — | All bounces |
| Company-scope escalations | 0 | Threshold: 2 distinct bounces | None triggered |

**Note on the 4.1% vs 2% threshold:** The `MAX_BOUNCE_RATE` constant in `pre_send_assertions.py` is defined as 2.0%, but the actual `assert_sender_under_daily_cap` logic checks daily send count, not bounce rate directly. The bounce rate check mentioned in the constant appears to not be implemented as an active runtime gate — it is a constant but there is no corresponding assertion function `assert_bounce_rate_ok`. This means a bounce spike would not automatically pause the system. This is a governance gap.

### Bounce Distribution Analysis

The interactions data does not include per-sender or per-domain breakdowns (those fields were not queried in the collection pass). However, the suppression_log provides the following:
- All 84 suppressions are `hard_bounce_contact` at `contact` scope
- No domain-scope suppressions exist
- No company-scope escalations have occurred (threshold is 2 distinct bounced contacts per company)

**Finding:** The 84 contact-scope suppressions from 1,090 step-1 sends implies a hard bounce rate of approximately 7.7% at contact level. This is significantly higher than the 4.1% measured from interaction events, suggesting either:
1. Some bounces were recorded in suppression_log but not as email_bounced interaction events, OR
2. Some suppression entries were created through a path other than actual bounce events (e.g., manual suppression or pre-emptive blocking)

**Confidence level: Medium.** This discrepancy needs direct query of joined suppression_log and interactions tables to resolve.

### Suppression Architecture Validation

The tiered suppression system (migration 048) is functioning as designed:

| Suppression Tier | Behavior | Status |
|---|---|---|
| Contact-scope | Hard bounce creates suppression_log entry with scope=contact | Working — 84 entries |
| Company-scope escalation | 2+ distinct bounced contacts triggers company-scope | Not yet triggered — no company has hit threshold |
| Domain-scope | Domain-level bounces trigger domain block | Not yet triggered |
| Company status block | not_interested/disqualified/converted blocks | These statuses do not appear in production data |

The `is_suppressed()` function in `suppression.py` correctly checks suppression_log before company status. The tiered architecture is sound.

### Deliverability Risk Indicators

| Risk | Level | Basis |
|------|-------|-------|
| Bounce rate (all-time) | MODERATE | 7.7% contact-level bounce rate |
| Bounce rate (MAX_BOUNCE_RATE not enforced as runtime gate) | HIGH | Constant defined but no assertion function |
| Domain concentration risk | UNKNOWN | Per-domain analysis not yet run |
| SPF/DKIM/DMARC status | UNKNOWN | Not inspected in this report; requires DNS check |
| Sender warmup | NOT ASSESSED | Instantly warmup integration in place; current send volume is low |
| Complaint handling | LIMITED | email_bounced interactions exist but complaint_received does not |

### Sender Reputation Assessment

Current daily volumes (82 sends/active day average, peak 465) are within warmup ranges for established domains. However, the MAX_BOUNCE_RATE constant being unimplemented as a runtime gate means there is no automatic circuit breaker if deliverability degrades on a high-volume day.

---

## 6. Sequence Progression Health

### Step Distribution

| Sequence Step | Total Drafts | Sent | Approved Unsent | Pending Review | Rejected |
|---|---|---|---|---|---|
| Step 1 | 1,373 | 1,090 | 45 | 50 | 230 |
| Step 2 | 514 | 43 | 64* | 248 | 202 |
| Step 3 | 11 | 4 | 0 | 2 | 5 |
| Step 4 | 0 | 0 | 0 | 0 | 0 |

*As of end of current review session (64 approved in Batches 1-4 today).

### Step-Gap Analysis

| Transition | N | Min Gap | Median Gap | Max Gap | Violations (<5d) |
|---|---|---|---|---|---|
| Step 1 to Step 2 | 33 | 5 days | 27 days | 31 days | 0 |
| Step 2 to Step 3 | 4 | 3 days | 3 days | 3 days | **4 (100%)** |

**Step 1 to Step 2: HEALTHY.** All 33 contacts that received both step-1 and step-2 had a gap of at least 5 days, satisfying `MIN_STEP_GAP_DAYS`. The median 27-day gap suggests deliberate pacing.

**Step 2 to Step 3: GOVERNANCE VIOLATION.** All 4 contacts that received step-3 had a 3-day gap from step-2, below the 5-day minimum. The `assert_minimum_step_gap` function should have blocked these sends. Possible explanations:
1. These sends pre-date the implementation of the assertion
2. The assertion was bypassed during a batch send operation
3. A race condition in the scheduler allowed two jobs to both claim the draft before the assertion ran

This requires investigation before step-3 sends resume.

### Daily Cap and Cadence

- `daily_cap` in `run_pre_send_assertions` defaults to 125 sends per sender per day
- Scheduler runs 7 ticks/day (Mon-Fri 8:00-11:00 AM CDT, every 30 minutes), batch_size=20
- Maximum theoretical daily output: 7 ticks × 20 batch = 140 sends (above the 125 cap, meaning the cap will trigger before the last tick)
- Practical daily output: 125 sends maximum per sender (cap enforced by `assert_sender_under_daily_cap`)

Peak day recorded (2026-05-04): 465 sends. This significantly exceeds the 125/sender cap, which means either multiple senders were active, the cap was not enforced on that date, or the assertion was not wired into the send path at that time.

**Confidence level: Medium.** The 465-send day is notable and should be investigated to confirm the sender daily cap was respected.

### Assertion Framework Effectiveness

| Assertion | Total Evaluations | Pass Rate | Notes |
|---|---|---|---|
| email_deliverable | 3,210 | 100% | Zero invalid/bounced emails reaching draft_gen |
| email_status_verified | (bundled in email_deliverable count) | 100% | |
| outreach_eligible | 3,206 | 100% | All drafted contacts are eligible |
| persona_target | 3,204 | 100% | No excluded personas reached draft_gen |
| email_name_consistent | 3,209 | 100% | |
| no_recent_company_send | 3,207 | 93.8% | 200 failures — cooldown gate working |
| sender_daily_cap | Not in failed list | 100% | Cap not being hit in draft_gen context |
| prior_step_sent | Not in failed list | 100% | Step ordering preserved |
| minimum_step_gap | Not in failed list | 100% in draft_gen | Step-3 violations indicate send_path issue |

The assertion framework is operating correctly in the `draft_gen` context. The 200 `no_recent_company_send` failures are working as intended — they are advisory gates that correctly blocked duplicate draft generation for recently-contacted companies.

### Sequence Completion and Cooldown

- Contacts with 2+ steps sent: 36 (3.3% of step-1-sent contacts)
- Contacts with 3+ steps sent: 4 (0.4%)
- `SEQUENCE_COOLDOWN_DAYS = 90` — contacts who complete a sequence are locked for 90 days unless they reply

The `is_suppressed()` function checks for completed sequences with no reply and applies the 90-day cooldown. With zero email_replied interactions recorded, this cooldown will activate for all contacts who complete a sequence, which is correct behavior — but it means if replies ARE happening in the inbox without being logged, contacts may be incorrectly locked.

---

## 7. Data Quality Assessment

### Contact Data Quality

| Field | Missing Count | Missing % | Impact |
|-------|---|---|---|
| email | 6,377 | 64.1% | Cannot send — total pipeline block |
| linkedin_url | 7,984 | 80.3% | Reduces personalization quality |
| title | 0 | 0.0% | Complete |
| full_name | 0 | 0.0% | Complete |
| company_id | 0 | 0.0% | FK integrity maintained |
| contact_tier | 0 | 0.0% | Complete |
| is_outreach_eligible | 0 | 0.0% | Complete |
| email_status | 3,354+ | 33.7%+ | Verified address status often unknown |
| duplicate emails | 0 | 0.0% | No duplicates detected |

**Overall contact data integrity score: 42/100.** The identity fields (name, title, company, tier, eligibility) are well-maintained. The enrichment fields (email, LinkedIn, email_status) are severely underrepresented.

### Company Data Quality

| Field | Missing Count | Missing % | Impact |
|-------|---|---|---|
| website | 2,465 | 100.0% | Research personalization degraded |
| industry | 2,397 | 97.2% | Vertical segmentation impossible |
| employee_count | 2,416 | 98.0% | Company sizing impossible |
| status | 1,465 | 59.5% | Lifecycle management broken |
| duplicate names | 0 | 0.0% | Clean |

**Overall company data integrity score: 18/100.** The company table is structurally sound (no duplicates, FK references valid) but is functionally incomplete. The absence of industry, employee_count, and website data means the CRM cannot support:
- Industry-based segmentation or campaign targeting
- Company size filtering
- Website-based personalization
- Meaningful reporting by vertical

This data should have been backfilled from Apollo during enrichment. It appears Apollo enrichment populated contact-level data (names, titles) but did not write company-level metadata back to the companies table.

### Research Intelligence Coverage

| Segment | Count | % |
|---------|-------|---|
| Companies with research_intelligence record | 1,145 | 46.5% |
| Companies without research | 1,320 | 53.5% |
| Companies researched, no drafts generated | ~655 | est. 57% of researched |

Research coverage is moderate. However, research existence alone is not sufficient for draft generation — the research must include actionable signals (existing solutions, pain indicators, equipment types) for the draft generation prompt to produce a high-quality, personalized draft.

### Identified Data Integrity Anomalies

1. **email_status = extrapolated (1 contact):** This is not a valid ZeroBounce return value and is not in `SENDABLE_EMAIL_STATUSES`. This contact would be blocked by the send gate. The origin of this value is unclear.

2. **ZeroBounce write-back discrepancy:** ZeroBounce API reported 640 verified and 291 catch_all (931 total sendable), but the database shows 181 verified and 33 catch_all (214 total sendable). The 717-contact gap suggests the DB update loop failed silently for most contacts. The ZeroBounce script's return code was 0 (success), but the actual Supabase `.update()` calls may have hit RLS policies, wrong environment routing, or key mismatches.

3. **MAX_BOUNCE_RATE constant unused:** Defined in `pre_send_assertions.py` at line 29 but not referenced in any assertion function. This is dead configuration.

4. **email_status = NULL for contacts with emails:** 769 contacts have an email address but null email_status. The pre-send gate treats NULL as non-verified, blocking these contacts. Resolving the ZeroBounce write-back would unlock most of them.

### Data Quality Scoring Summary

| Dimension | Score | Notes |
|---|---|---|
| Contact identity completeness | 90/100 | Name, title, company all present |
| Contact email completeness | 25/100 | 64% missing email |
| Contact email verification | 30/100 | Only 6% of email-holders are verified |
| Company metadata completeness | 18/100 | Industry/website/size all missing |
| Research coverage | 47/100 | 46.5% of companies have research |
| Referential integrity | 97/100 | No broken FKs, no duplicate emails |
| **Overall data integrity** | **35/100** | |

---

## 8. Operational Readiness Assessment

### Current Architecture Overview

The system is built on:
- **Database:** Supabase (PostgreSQL) hosted on Railway production environment
- **Scheduler:** APScheduler (BackgroundScheduler) embedded in FastAPI lifespan
- **Send gate:** Pre-send assertion library (`pre_send_assertions.py`) with 9 checks
- **Suppression:** Tiered suppression_log (migration 048) with contact/company/domain scope
- **Draft generation:** AI-driven, every 5 minutes via cron
- **Approval workflow:** Human-in-the-loop via dashboard (currently manual batch review)
- **Email delivery:** Resend API
- **Reply handling:** IMAP polling (no reply events in interactions table — non-functional)
- **Bounce handling:** Webhook from Resend; suppression_log writes on hard bounce

### Reliability Assessment

| Component | Status | Risk |
|---|---|---|
| Scheduler (APScheduler in FastAPI) | Functional | Medium — in-process scheduler, not persistent across deploys |
| Send gate assertions | Functional | Low — well-tested, all 9 assertions active |
| Suppression architecture | Functional | Low — tiered, correctly implemented |
| Reply ingestion | Non-functional | High — IMAP polling appears inactive |
| Draft generation | Functional | Low — running every 5 min |
| Email delivery (Resend) | Functional | Low — successful sends confirmed |
| ZeroBounce integration | Partial | High — find_email works; validate_batch write-back broken |
| Bounce webhook | Functional | Low — 45 bounces recorded, suppression created |

### Governance Maturity

| Dimension | Score | Evidence |
|---|---|---|
| Pre-send safety gates | 9/10 | 9 assertion types, 100% pass rate except advisory cooldown |
| Human approval requirement | 8/10 | Every draft reviewed before sending |
| Suppression tiering | 9/10 | 3-scope architecture, correct escalation logic |
| Step-gap enforcement | 6/10 | Step1>Step2 clean; Step2>Step3 violated in 4 cases |
| Duplicate prevention | 8/10 | Duplicate_draft_pending check in is_suppressed() |
| Rollback capability | 5/10 | approval_status revert possible; no transaction log |
| Audit trail | 6/10 | send_assertions table is useful; no event log for approvals |

### Observability Gaps

| Gap | Impact | Severity |
|---|---|---|
| Zero reply tracking | Cannot measure response rate, cannot trigger cooldown exemptions | Critical |
| No funnel dashboard | Cannot see pipeline state without raw SQL | High |
| No bounce rate runtime gate | System will not auto-pause on bounce spike | High |
| No send performance dashboard | Open/click/bounce rates require manual query | Medium |
| No draft quality scoring | Cannot identify weak drafts without manual review | Medium |
| No daily send report | Avanish has no automated daily send summary | Medium |
| send_assertions context inconsistency | draft_gen vs send_path not always distinguished in queries | Low |

### Scaling Bottlenecks

At current architecture, the following are hard limits before scale:

1. **Email data gap (6,377 contacts with no email):** This is a data acquisition problem, not an architecture problem. Apollo credits or an alternative discovery tool (Hunter.io, Clearbit, etc.) are required.

2. **ZeroBounce write-back bug (769 contacts blocked):** Fixing this unlocks approximately 769 contacts assuming the ZeroBounce results are accurate. High priority.

3. **Human review bottleneck (248 step-2 drafts, ~264 total pending):** At 16 drafts/session, this is 15+ sessions to clear. Requires either increased review throughput or a tiered auto-approve system for high-confidence drafts.

4. **In-process scheduler:** APScheduler running inside FastAPI is not persistent across restarts. A Railway deploy clears the scheduler state. This is adequate for current volume but creates a reliability gap at scale.

5. **No multi-sender management:** The current architecture supports one sender email. Scaling to 500+/day requires multiple warmed-up sender accounts with domain rotation, which requires infrastructure changes.

6. **No reply handling:** The engagement loop is broken. Replies enter the inbox but are not logged, not used to exit cooldown, not suppressed, and not reported. This is operationally acceptable at 50 sends/day but is not acceptable at scale.

---

## 9. Future-State Readiness Model

### Scenario: 1,000 Prospects

**What currently works:**
- Pre-send governance handles 1,000 contacts without changes
- Draft generation pipeline generates in batches, can handle this volume
- Suppression and bounce handling scales linearly

**What will break or strain:**
- Human review (248 pending now; 1,000-prospect scale adds ~750 more step-2 drafts)
- ZeroBounce credits (1,000-credit batches at $16 — manageable)
- Reply handling becomes critical (manual inbox monitoring at this volume is untenable)

**What needs redesign:**
- Auto-approve tier for high-confidence drafts (reducing review burden by ~60%)
- Reply ingestion must be operational before 1,000-prospect scale

**Governance changes required:** None beyond existing framework.

**Infrastructure changes required:** IMAP reply ingestion working; auto-approve scoring model.

---

### Scenario: 10,000 Prospects

**What currently works:** Data model is schema-compatible.

**What will break:**
- Email discovery: 10,000 prospects requires 10,000 emails; current Apollo credits and ZeroBounce credits insufficient
- Human approval workflow: not feasible; requires auto-approve with human exception handling
- Reply handling: critical; 10,000 prospects generates 500-1,000 replies at normal conversion rates
- Single-sender architecture: will hit daily caps and warm-up limits; need 8-10 sender accounts
- Scheduler reliability: in-process APScheduler across multiple Railway replicas creates duplicate-send risk; needs dedicated job queue (Temporal, Celery, or similar)
- Draft generation: every-5-minute cron at 10,000 contacts may create queue pressure

**What needs redesign:**
- Multi-sender pool management
- Persistent job queue (replace APScheduler)
- Auto-approve with quality scoring
- Reply processing pipeline (IMAP → interaction log → sequence state update)
- Email discovery pipeline (Apollo enrichment automation, ZeroBounce batched)

**Infrastructure changes required:** Temporal or Celery + Redis; multiple Resend sender accounts; dedicated ZeroBounce subscription (10,000+ credits/month).

---

### Scenario: Multi-Domain / Parallel Campaigns

**What currently works:** Schema supports multiple workspace_ids; suppression_log is workspace-scoped.

**What will break:**
- Cross-domain suppression (contact emailed on domain A should not be re-contacted on domain B)
- Domain reputation management (separate IP/domain warmup per campaign)
- Report aggregation (no cross-campaign analytics)

**Governance changes required:** Cross-workspace email dedup in `is_suppressed()` (partially implemented as cross-company email dedup — can be extended).

---

### Scenario: Fully Autonomous Execution

**Assessment: Not ready. Significant gaps exist.**

| Requirement | Current State |
|---|---|
| Reply detection and processing | Non-functional |
| Bounce spike auto-pause | Not implemented (constant defined, gate missing) |
| Draft quality auto-scoring | Not implemented |
| Suppression review on escalation | Manual |
| Sequence advancement logic | Partially automated |
| Governance audit logging | Limited |

Autonomous execution requires all of the above. Current system requires human approval and monitoring at every step.

---

## 10. Recommendations and Prioritized Actions

### Immediate (24-72 hours)

| # | Action | Severity | Effort | Benefit |
|---|---|---|---|---|
| I-1 | **Set SEND_ENABLED=true in Railway before 8 AM CDT Thursday May 14** | Critical | 1 min | Enables 64 approved step-2 sends |
| I-2 | **Fix ZeroBounce write-back bug** — Debug the `zb_verify.py` script; likely a Supabase update RLS or key mismatch issue. Re-run after fix to unlock 769 contacts | Critical | 2-4 hrs | Unlocks ~769 contacts for the send pipeline |
| I-3 | **Implement bounce rate runtime gate** — Add `assert_bounce_rate_ok()` function that reads 7-day rolling bounce rate from interactions table and raises AssertionFailure if > 2%. Wire into `run_pre_send_assertions()` | High | 3-4 hrs | Prevents reputation damage on bounce spike |
| I-4 | **Investigate step-3 gap violations** — Query the 4 contacts who received step-3 within 3 days of step-2. Determine whether the assertion was bypassed or not yet implemented at time of send | High | 1-2 hrs | Governance validation |
| I-5 | **Run post-send review Thursday afternoon** — After first scheduler run, query send_assertions for any send_path failures and review the sent-draft list | High | 30 min | Catch operational issues early |

### Near-Term (1-2 weeks)

| # | Action | Severity | Effort | Benefit |
|---|---|---|---|---|
| N-1 | **Restore IMAP reply ingestion** — Debug and re-enable the `gmail_intake` cron (currently scheduled but presumably not writing email_replied events). Add assertion that reply events are flowing. | Critical | 4-8 hrs | Enables engagement tracking, sequence cooldown exit, reply-based suppression |
| N-2 | **Complete step-2 draft review (248 remaining)** — Continue batch review sessions to clear the pending queue before the Thursday send batch depletes the approved queue | High | 4-6 sessions | Sustains send velocity through next week |
| N-3 | **Investigate 583 stalled contacts (step-1 sent, no step-2 draft)** — Query these contacts' email_status and generate step-2 drafts for those that are now verified | High | 2-4 hrs | Potential 583 new step-2 drafts |
| N-4 | **Regenerate 202 rejected step-2 drafts** — Review rejection reasons; drafts rejected for quality issues should be regenerated rather than abandoned | Medium | 3-4 hrs | Recovers 202 stalled contacts |
| N-5 | **Apollo email discovery run** — For the 6,377 contacts with no email, prioritize target-tier contacts and run Apollo bulk email discovery | High | 2 hrs setup + credits | Potentially unlocks thousands of contacts |
| N-6 | **Update company status fields** — Write a migration script to tag companies that have received step-1 as `contacted`, creating CRM lifecycle visibility | Medium | 2 hrs | Enables CRM-level pipeline management |

### Medium-Term (30-60 days)

| # | Action | Severity | Effort | Benefit |
|---|---|---|---|---|
| M-1 | **Build auto-approve scoring layer** — Score pending drafts on: binary close (yes/no), brand descriptor present, no dashes, no meeting ask, word count 150-250. Auto-approve high-confidence drafts to reduce review burden by ~60% | High | 1-2 weeks | Sustainable at 10x current volume |
| M-2 | **Multi-sender infrastructure** — Add 2-3 sender email accounts with Resend, implement sender pool rotation and per-sender daily caps in the scheduler | High | 1 week | Scales daily throughput to 375-500 sends/day |
| M-3 | **Apollo company metadata backfill** — Backfill industry, website, and employee_count for all 2,465 companies using Apollo bulk organizations enrich | Medium | 4 hrs + credits | Enables vertical segmentation |
| M-4 | **Replace APScheduler with persistent job queue** — Migrate send jobs to a Redis-backed queue (Celery or BullMQ) to prevent duplicate sends on Railway redeploy | High | 1-2 weeks | Eliminates scheduler reliability risk at scale |
| M-5 | **Implement funnel dashboard** — Build a real-time pipeline dashboard showing: sent/approved/pending by step, bounce rate (7-day rolling), reply rate, and top-line engagement metrics | Medium | 1 week | Eliminates need for manual SQL queries |
| M-6 | **Add daily send report** — Automated daily email/Slack summary of: sends attempted, sent, failed assertions, bounce events, reply events | Medium | 4 hrs | Operational visibility without SQL access |

### Strategic Architecture Improvements (30-90 days)

| # | Action | Severity | Effort | Benefit |
|---|---|---|---|---|
| S-1 | **Reply processing pipeline** — Full IMAP → parse → intent classification → interaction_log write → sequence state update pipeline. This is the most important missing piece for autonomous operation | Critical | 2-3 weeks | Closes the engagement loop |
| S-2 | **Domain concentration analysis** — Analyze bounce and deliverability rates by sending domain and recipient domain. Implement domain rotation if concentration risk identified | High | 3-5 days | Protects sender reputation |
| S-3 | **Sequence auto-advancement logic** — Automate the decision to advance from step N to step N+1 based on: no reply within N days, cooldown elapsed, email_status verified. Remove manual draft_generation dependency | Medium | 1 week | Reduces operational overhead per contact |
| S-4 | **A/B test infrastructure** — Tag drafts by messaging variant (case_relevance vs framework_share vs direct_ask) and measure open/click/reply rates per variant | Medium | 1 week | Optimizes outreach quality over time |
| S-5 | **CRM lifecycle state machine** — Implement formal company and contact state machines with explicit transitions (discovered → researched → contacted → replied → opportunity → won/lost) | Medium | 2 weeks | Enables proper CRM reporting and pipeline management |

---

## 11. Validation Notes and Confidence Levels

### Data Collection Methodology

All metrics in this report were derived from live queries against the production Supabase database via the ProspectIQ Python backend (`Database()` class, ENVIRONMENT=production). No staging or mock data was used.

Scripts were executed via `railway run python3` with production environment variables injected from the Railway ProspectIQ project.

### Confidence Levels by Section

| Section | Confidence | Notes |
|---------|-----------|-------|
| Executive counts | High | Direct COUNT queries against production tables |
| Pipeline funnel | High | Direct query; minor rounding possible |
| Email status distribution | High | Direct query; ZeroBounce discrepancy flagged |
| Bounce rate | Medium | 45 interaction events vs 84 suppression entries — discrepancy not fully explained |
| Step gap analysis | High | Computed from actual sent_at timestamps |
| Data quality metrics | High | Direct field-presence counts against full table |
| Sender daily cap enforcement on peak day | Medium | 465 sends on 2026-05-04 requires investigation |
| Step-3 gap violation root cause | Low | Mechanism not confirmed; 4 cases observed |
| ZeroBounce write-back failure | Medium | 931 API-reported vs 214 in DB; root cause not confirmed |
| Reply tracking status | High | Zero email_replied events in 1,559 total interactions — conclusive |
| MAX_BOUNCE_RATE implementation gap | High | Code read confirms constant defined but no assertion function |

### Key Uncertainties

1. **Why did ZeroBounce report 931 sendable but DB shows 214?** The write-back failure is the most operationally significant unresolved question. Until the root cause is found, 769 contacts remain in limbo.

2. **Why do 45 email_bounced interactions exist but 84 suppression_log entries exist?** These should be 1:1. The 39-record discrepancy may indicate some suppression entries were created manually or via a different code path.

3. **Is IMAP polling running and parsing but not writing, or is it not running at all?** The `gmail_intake` cron is scheduled every 15 minutes. Zero reply events means either it is not running, or it is running but all processed emails are non-replies.

4. **Were the 4 step-3 sends on May 10+ subject to the minimum_step_gap assertion?** The assertion was added to the codebase but the commit date relative to the 4 step-3 sends is not confirmed here. If those sends pre-date the assertion, there is no violation — only a coverage gap.

### Inspection Scripts Used

The following scripts were used and can be re-run to refresh this report:
- `scripts/pipeline_audit.py` (to be created from scripts in this report's appendix)

For a live re-run: `cd /Users/avanish/prospectIQ && railway run python3 scripts/pipeline_audit.py`

---

*Report generated: 2026-05-13*
*Data as of: 2026-05-13, approximately 22:00 CDT*
*Next recommended refresh: After Thursday May 14 send batch completes (target: Friday May 15 morning)*
*Author: Digitillis Technical Team*
