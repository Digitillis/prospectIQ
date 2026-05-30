# ProspectIQ Survival Diagnostic — Platform Remediation Plan

*Date: 2026-05-28  |  Verdict: C — Partial Rebuild  |  Confidence: HIGH*

*Author: Avanish Mehrotra & Digitillis Technical Team*

---

Prescriptive engineering remediations to keep ProspectIQ a **cold-outbound** channel and make it 1:1 personalized. Ordered by tier; within a tier, by leverage. Each item is concrete: the problem (with code-verified evidence), the action, the location, and a binary acceptance criterion. Every item ships with a regression test (see R12) so it cannot silently revert.

Channel decision is fixed: **cold outbound.** No warm/FirstLook-anchored motion. A signal/intent layer appears below only as cold-send timing and personalization input.

---

## TIER 0 — CORRECTNESS (do before any resend; nothing downstream is trustworthy until these pass)

### R1 — Fix reply ingestion (CRITICAL)
- **Problem:** the IMAP poll searches `UNSEEN` only, so any reply the founder reads first is never ingested. The system has ingested zero replies via IMAP, ever; `reply_classifications` and `outreach_outcomes.replied_at` are empty. A real Waupaca scheduling reply was lost.
- **Action:** replace `UNSEEN` with `SINCE <last-run>` or a Gmail label-based ingestion that does not depend on read state. Backfill known replies.
- **Location:** `backend/app/integrations/gmail_imap.py:175`.
- **Acceptance:** a reply that a human has already opened is still ingested end-to-end; `reply_classifications` / `outreach_outcomes` populate; an automated test sends→reads→polls→asserts capture.

### R2 — Close the pipeline-integrity gap (CRITICAL)
- **Problem:** 46 already-rejected drafts were sent anyway. Rejection is not authoritative.
- **Action:** make `approval_status in (rejected, dispatch_failed)` a hard pre-send assertion; a rejected draft can never transition to sent.
- **Location:** dispatch path + `backend/app/core/pre_send_assertions.py` (add a `assert_not_rejected` gate in `send_path`).
- **Acceptance:** attempting to dispatch a rejected draft raises and is logged; test proves it.

### R3 — Metric integrity / bot filtering (HIGH)
- **Problem:** 94% click-to-open ratio and fully co-registered open+click events mean most "engagement" is security-scanner pixel loads, not humans (AMETEK 6 clicks on one email; Waupaca 15 opens on one email). Five companies were promoted to "engaged" on scanner clicks.
- **Action:** classify and drop bot events (open+click co-registered, sub-2-minute open-after-click gaps, repeated events on one message); report human vs bot engagement separately.
- **Location:** the Resend webhook/engagement-event handler + engagement scoring.
- **Acceptance:** open/click metrics reflect human reads; the 5 scanner-promoted companies are unmarked; "engaged" requires a non-bot signal.

---

## TIER 1 — THE PERSONALIZATION ENGINE (the core lever for "personalized per individual")

### R4 — Enforce a verifiable per-individual hook contract (CRITICAL — highest leverage)
- **Problem:** drafts *can* be company/person-specific (the top 15-20% are excellent) but are not *required* to be, so 60-65% ship as interchangeable templates. The existing integrity check already flags `fabricated_anecdote` (22x) and `unverified_confidence_metric` (38x) but only *blocks fabrication* — it does not *require* specificity, so generic-but-clean emails pass.
- **Action:** extend the draft integrity validator from "block fabrication" to "require grounding": no Step-1 draft passes unless it cites ≥1 verifiable, company- or person-specific fact (named event, named asset/equipment, role-specific detail) with a source reference from the enrichment record. Make the Waupaca / AMETEK-VAR / APP-NADCAP emails the gold-standard exemplars in the generation prompt.
- **Location:** draft-generation integrity/validation layer (the same module that emits `fabricated_anecdote` / `unverified_confidence_metric`) + `backend/app/agents/outreach.py` generation prompt.
- **Acceptance:** ≥90% of newly-generated sent emails contain a named company event or named asset tied to the recipient; drafts without a grounded hook are auto-rejected, not sent.

### R5 — Re-enable and deepen enrichment (CRITICAL — precondition for R4)
- **Problem:** the EnrichmentAgent has been PAUSED since 2026-05-07; 2,524 of 2,659 "researched" companies (95%) have no `research_intelligence` record yet were scored and drafted. You cannot write the Waupaca email at scale without per-individual data.
- **Action:** re-enable enrichment; deepen it to capture named recent events, specific assets/equipment signatures, regulatory/operational triggers, and the individual's role + recent activity. Enforce no-research-no-draft: a contact without a sufficient `research_intelligence` record is never queued for drafting.
- **Location:** EnrichmentAgent + the draft-eligibility query in `backend/app/agents/outreach.py:604` (`get_companies(status="qualified")`).
- **Acceptance:** every contact entering draft generation has a `research_intelligence` record with ≥N specific, sourced facts; companies without it are excluded.

### R6 — Kill the template fingerprints (HIGH)
- **Problem:** verbal fingerprints betray automation to any repeat recipient: "time-based maintenance" in 35%, "typically" in 56%, the three recycled stat ranges (15-20% / 23-41% / 40-65%) in ~28%, "18 days out" verbatim in 127 emails across incompatible asset classes, "Curious —" CTA in 145, "Quick question" in 106, body length clustered at 735 chars.
- **Action:** retire the recycled stat ranges (or make every stat asset-specific and sourced); ban or rotate the canned CTA openers; vary length/register; add a corpus-level fingerprint scan to the build that fails if any single phrase exceeds a repetition threshold.
- **Location:** generation prompt + a post-generation corpus linter.
- **Acceptance:** fingerprint scan shows no single phrase above the threshold (e.g. <10%); stat claims carry asset-specific grounding.

---

## TIER 2 — QUALIFICATION + SEQUENCE (make the pipeline mean something)

### R7 — Make qualification real (CRITICAL)
- **Problem:** "qualified" = rule-based keyword matching against AI-generated research text. The LLM 7-gate (`LLMQualificationAgent`) exists but is wired only to the on-demand route `backend/app/api/routes/llm_qualify.py`; it is NOT registered in the scheduler, so `llm_qualified_at` is NULL on all 4,061 companies. The rule scorer awards +4 for absence of competitor evidence and +3 Midwest bonus on `state=NULL` (62% of contacts). Verdict from the evidence: ACTIVITY, not signal; criteria not meaningful.
- **Action:** register the LLM 7-gate in the scheduler (add `_run_llm_qualification`); fix the rule scorer's `state=NULL` and `no_existing_ai` default-positive bonuses; never score a company that has no `research_intelligence` record.
- **Location:** `backend/app/api/main.py` (job registration), `backend/app/agents/llm_qualification.py`, the PQS scorer.
- **Acceptance:** `llm_qualified_at` populated; qualification correlates with verifiable, company-specific fit; no company scored without enrichment.

### R8 — Sequence-completion engine (HIGH)
- **Problem:** 89% of contacts received only Step 1 (1,116 of 1,250); 8 sends ever reached Step 3-4; 95% of Step-2 emails do not reference Step 1 (re-introduce the product cold); 41 contacts who opened Step 1 were never followed up. The campaign was never actually run.
- **Action:** build the dispatcher to progress contacts through the full 4-5 step sequence; enforce Step-N-references-Step-(N-1) as a draft-validation rule; auto-queue follow-ups on openers.
- **Location:** `backend/app/core/dispatch_scheduler.py` + sequence orchestration + draft validation.
- **Acceptance:** contacts advance through all steps unless they reply/opt out; a Step-2 draft that does not reference Step-1 content fails validation; openers are followed up.

---

## TIER 3 — DELIVERABILITY + AUTONOMY (cold, done right)

### R9 — Domain consolidation (HIGH)
- **Problem:** 9 fragmented sending domains (getdigitillis.com, meetdigitillis.com, trydigitillis.com, usedigitillis.com, digitillis.io) split brand and trip spam heuristics; a recipient who Googles any of them gets an unclear picture. Resend (transactional) is being used for cold; Instantly (warm-up) is now paused with 4 hello@ mailboxes deleted.
- **Action:** consolidate to one or two warmed, dedicated cold domains with coherent brand pages; adopt proper cold-sending infra with inbox rotation and per-mailbox caps (100-200/day); run placement/deliverability testing before resuming.
- **Location:** sending configuration (`backend/app/core/config.py` send settings) + DNS/brand + sender selection.
- **Acceptance:** a single coherent sender identity survives a Google check; placement test passes; per-mailbox caps enforced.

### R10 — Fix the inverted autonomy split (HIGH)
- **Problem:** draft generation runs autonomously every 5 min and qualification every 15 min, but sending is gated by per-email human review that passed 99.3% of 1,250 (8 rejections total) — a rubber stamp that filters nothing and manufactures false confidence.
- **Action:** automate generation + the R4 personalization gate; replace serial per-email approval with sampled QA on personalization quality; move human judgment upstream to ICP/list approval and downstream to reply handoff.
- **Location:** scheduler job config (`backend/app/api/main.py`) + review workflow + send gate.
- **Acceptance:** founder no longer reviews every email; rejection rate reflects real gating via R4; a documented human checkpoint exists at ICP-in and reply-out.

---

## TIER 4 — LEARNING LOOP + ANTI-REGRESSION

### R11 — Minimal CRM + north-star metric (MEDIUM)
- **Problem:** no CRM tables exist; "engaged" is a status-field hack; there is no cost-per-qualified-conversation metric. Reply outcomes do not refine targeting.
- **Action:** add a minimal CRM/handoff table; route warm replies to handoff records; compute cost per qualified manufacturing conversation; feed reply sentiment back into ICP/list refinement.
- **Location:** new migration + handoff path + a metrics job.
- **Acceptance:** warm replies create handoff records; the north-star metric is computed and visible; a closed loop from reply → ICP update exists.

### R12 — Close the diagnose-claim-rediscover loop (HIGH — organizational root cause)
- **Problem:** every defect is declared FIXED then rediscovered 1-2 weeks later (bounce gate doc-vs-code drift, reply tracking, `email_status` nulls, hallucinations, `approved_by`/`reviewed_at` fields, pacing config `daily_limit` 500→50 never applied). 50+ docs produced; outcomes never moved.
- **Action:** every remediation R1-R11 ships with a regression test/assertion that fails loudly if the behavior reverts. Maintain ONE append-only run log; ban new audit/triage/strategy docs. (Note: the bounce gate is already enforcing in code at `pre_send_assertions.py:359` — the recurring doubt was documentation drift, not a code defect; this is the pattern to kill.)
- **Location:** test suite + a single run-log file.
- **Acceptance:** each fixed item has a test in CI; a reverted behavior breaks the build; no new process documents are created.

---

## Sequencing summary

Tier 0 (R1-R3) before any send. Tier 1 (R4-R6) is the heart of "personalized per individual" and gates the cohort. Tier 2 (R7-R8) makes the pipeline honest and the sequence real. Tier 3 (R9-R10) makes the cold channel deliverable and frees founder time. Tier 4 (R11-R12) makes outcomes measurable and stops the regression loop. The 90-Day Recovery Plan maps these to weeks.
