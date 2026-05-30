# ProspectIQ Survival Diagnostic — Technical Implementation Plan

*Date: 2026-05-28  |  Verdict: C — Partial Rebuild  |  Confidence: HIGH*

*Author: Avanish Mehrotra & Digitillis Technical Team*

---

This is the engineering execution plan for remediations R1–R12 in the [Platform Remediation Plan](2026-05-28-prospectiq-survival-diagnostic-platform-remediation-plan.md). Channel decision is fixed: **cold outbound, personalized per individual.** Every reference below was verified against live code on 2026-05-28.

## How to read this
Each item lists: **Current state** (incl. what already exists), **Change**, **Touchpoints** (files / migrations / config), **Test**, **Acceptance**, **Effort** (dev-days), **Depends on**. Effort is for a single experienced backend engineer; ranges reflect the open questions noted at the end.

## Key corrections from the code review (scope is smaller than the diagnostic implied)
Grounding the plan in code changed three items materially — do not rebuild what exists:
- **R3 (bot filtering) is ~60% built.** `backend/app/core/click_classifier.py` already classifies bot vs human (90s latency floor, scanner-UA tokens, rapid-click rule) and `classify_engagement_tier()` only counts human clicks. The gaps are narrow: the Resend webhook doesn't capture `user_agent`, and the "promote to engaged" path in `webhooks.py:1091` advances on raw opens without routing through the classifier.
- **R4 (verifiable hook) is partially built.** `_check_draft_integrity()` (`outreach.py:188–235`) already enforces a Step-1 rule requiring a source URL in `personalization_notes` and flags generic phrases. The gap is that the URL is not validated to belong to the target company/person, and the recycled-stat phrasings aren't all caught.
- **R11 (CRM/handoff) mostly exists.** There are no `crm_leads`/`opportunities` tables, but `campaign_threads`, `thread_messages`, `interactions`, `engagement_sequences`, `hitl_queue`, and `deals` all exist, and warm replies already route to `hitl_queue` via `_push_reply_to_hitl()` (`main.py:796–809`). R11 becomes "surface `hitl_queue` in the dashboard + add the north-star metric," not "build a CRM."

Net effect: the Tier-0/Tier-1 gating set (R1–R4) that unblocks the cohort is ~5–7 dev-days, not weeks.

---

## WORKSTREAM A — Correctness (Tier 0; blocks any resend)

### R1 — Reply ingestion by SINCE/label, not UNSEEN
- **Current state:** `GmailImapClient.fetch_unseen_replies()` (`gmail_imap.py:164`) runs `search(None, "UNSEEN")` at `:175`; scheduled as `_run_gmail_intake` every 15 min (`main.py:2293`). A parallel Gmail-API path uses a 48h lookback. Replies write to `campaign_threads`, `thread_messages`, `interactions`, `engagement_sequences`; the classifier (`reply_classifier.py`) writes `reply_classifications` + `outreach_outcomes`. **No persistent last-run cursor exists.**
- **Change:** add a `scheduler_state(job_id, workspace_id, last_run_at)` table; in `_gmail_intake_workspace()` read `last_run_at`, IMAP-search `SINCE {last_run_at}` (first run falls back to 48h), update the cursor after each successful batch. Keep dedup (`thread_messages` window / `provider_events`). Backfill any historical replies still in the inbox.
- **Touchpoints:** new migration `*_scheduler_state.sql`; `backend/app/api/main.py:522–584`; `backend/app/integrations/gmail_imap.py:164–232`.
- **Test:** `test_reply_ingested_when_already_read()` — seed a read message, run intake, assert a row in `interactions`/`outreach_outcomes`.
- **Acceptance:** a reply already marked read in Gmail is still ingested end-to-end; cursor advances; no duplicates.
- **Effort:** 1.5–2.  **Depends on:** none. **Do first.**

### R2 — Rejected drafts can never dispatch
- **Current state:** `approve_draft_and_enqueue()` (migration 054) only enqueues `approved`/`edited`, but `claim_outbound_queue_batch()` (migration 055, lines 43–69) selects from `outbound_queue` with **no join to `outreach_drafts.approval_status`**, and `dispatch_scheduler.py:300–326` does not re-validate. Status distribution today: approved 1,214 / rejected 504 / pending 380 / pending_second_review 7.
- **Change:** (a) add `assert_not_rejected()` to `pre_send_assertions.py` and call it first in `run_pre_send_assertions()` (`:460–502`); (b) add an `approval_status IN ('approved','edited')` guard to the claim RPC `WHERE` clause (new migration) so a stale/rejected queue row can never be claimed.
- **Touchpoints:** `backend/app/core/pre_send_assertions.py`; new migration superseding the `claim_outbound_queue_batch` body; `backend/app/core/dispatch_scheduler.py:300`.
- **Test:** `test_rejected_draft_never_dispatched()` — enqueue then reject; assert claim returns nothing and send path raises.
- **Acceptance:** a rejected draft cannot be sent via any path; test proves it.
- **Effort:** 0.5–1.  **Depends on:** none.

### R3 — Finish human/bot engagement separation
- **Current state:** `click_classifier.py` classifies bot/human; `engagement.py:172` only counts human clicks for tiers. **Gaps:** webhook (`webhooks.py:1058–1121`) doesn't persist `user_agent`; the `email.opened` handler promotes `companies.status → engaged` at `:1091` on raw opens (no classifier); opens/clicks aren't deduped (Resend reuses `email_id`).
- **Change:** capture `user_agent` + event timestamp from the Resend payload into the open/click event; route the "promote to engaged" decision through `click_classifier`/`classify_engagement_tier` so only human signals promote; unmark the 5 scanner-promoted companies in a one-off backfill.
- **Touchpoints:** `backend/app/api/routes/webhooks.py:754–786, 1058–1121`; `backend/app/core/click_classifier.py`; `backend/app/agents/engagement.py:114–188`.
- **Test:** `test_scanner_open_does_not_mark_engaged()` and `test_human_dwell_click_promotes()`.
- **Acceptance:** scanner events never promote a company; engagement counts reflect human-only; the 5 false "engaged" are cleared.
- **Effort:** 1–1.5.  **Depends on:** none.

---

## WORKSTREAM B — Personalization engine (Tier 1; gates the cohort)

### R4 — Require a target-specific, verifiable hook on every email
- **Current state:** `_check_draft_integrity()` (`outreach.py:188–235`) already requires a source URL in `personalization_notes` for Step 1 (`:222–234`) and flags generic phrases (`:180–185`); rules live in `_INTEGRITY_RULES` (`:101–176`). Auto-reject sets `approval_status='rejected'`, `rejection_reason='auto_rejected|...'` (`:1029`). The attestation checklist already includes `specific_opener` and `company_is_manufacturer`.
- **Change:** (a) validate the hook URL/fact resolves to the target company/person (domain match against `companies`/`contacts`, not a generic library URL); (b) extend the contract beyond Step 1 to all steps; (c) add the recycled-stat phrasings (below in R6) to the reject set; (d) add the Waupaca / AMETEK-VAR / APP-NADCAP emails as gold-standard exemplars in `_build_system_prompt()` (`:238–400`).
- **Touchpoints:** `backend/app/agents/outreach.py:188–235, 238–400, 1006–1038`.
- **Test:** `test_generic_hook_rejected()`, `test_offtarget_url_rejected()`, `test_grounded_hook_passes()`.
- **Acceptance:** ≥90% of newly generated sent emails carry a named company event or asset tied to the recipient; generic/off-target drafts auto-reject.
- **Effort:** 1.5–2.  **Depends on:** R5 (needs real research to ground hooks).

### R5 — Re-enable and deepen research + enrichment (precondition for R4)
- **Current state (corrected):** two distinct agents. **ResearchAgent** (`research.py:223–452`) writes `research_intelligence` (`manufacturing_type, equipment_types, known_systems, pain_points, opportunities, trigger_events, trigger_score, confidence_level`) — its scheduler job is **paused** (`main.py:2299`). **EnrichmentAgent** (`enrichment.py`) only fills contact email/phone (Apollo People Match) and is **disabled** (`limits.yaml:58`, guarded at `enrichment.py:82–88`). Draft gen reads research at `outreach.py:720` and falls back to a "No research available" summary at `:1354` instead of blocking.
- **Change:** (a) re-enable the `research` job and the `enrichment` job (respect Apollo credit guard at `enrichment.py:93`); (b) deepen `ResearchAgent` extraction to capture per-individual signals (named recent events, specific equipment signatures, role + recent activity) — extend the `research_intelligence` write; (c) enforce **no-research-no-draft**: in the draft-eligibility path (`outreach.py:604` / `:1354`), exclude companies whose `research_intelligence` is missing or `confidence_level='low'` with empty `known_systems`.
- **Touchpoints:** `backend/app/api/main.py:2299,2314`; `config/limits.yaml:58`; `backend/app/agents/research.py:223–452`; `backend/app/agents/outreach.py:604,720,1354`; possible migration to extend `research_intelligence`.
- **Test:** `test_company_without_research_not_drafted()`; `test_research_writes_named_events()`.
- **Acceptance:** every contact entering draft gen has a sufficient `research_intelligence` record; low-confidence/empty research is excluded.
- **Effort:** 3–5 (deepening extraction is the long pole).  **Depends on:** Apollo/Perplexity budget approval (see open questions).

### R6 — Kill template fingerprints
- **Current state:** fingerprints are produced by the generation prompt + proof-points config: "time-based maintenance" 35%, "typically" 56%, three stat ranges (15-20 / 23-41 / 40-65) ~28%, "18 days out" 127×, "Curious —" 145×, "Quick question" 106×. Proof points live in `config/outreach_guidelines.yaml` / `config/offer_context.yaml`; some anecdote patterns already caught in `_INTEGRITY_RULES`.
- **Change:** remove the recycled stat ranges from config (or require asset-specific, sourced stats); rotate/ban the canned CTA openers; add a **post-generation corpus linter** that fails the batch if any single phrase exceeds a repetition threshold (e.g. >10%).
- **Touchpoints:** `config/outreach_guidelines.yaml`, `config/offer_context.yaml`; `backend/app/agents/outreach.py:_INTEGRITY_RULES`; new linter util + a CI check.
- **Test:** `test_recycled_stat_phrase_rejected()`; `test_corpus_fingerprint_threshold()`.
- **Acceptance:** fingerprint scan shows no phrase above threshold; stats are asset-specific + sourced.
- **Effort:** 1–1.5.  **Depends on:** R4 (shares the integrity layer).

---

## WORKSTREAM C — Qualification + sequence (Tier 2)

### R7 — Make qualification real
- **Current state:** rule scorer `QualificationAgent` (`qualification.py`) runs every 15 min (`main.py:2305`). **Bug 1:** `qualification.py:270` `if not state or state in qualifying:` → NULL state earns the Midwest +3. **Bug 2:** `_score_technographic()` returns 0 on empty research (`:308–309`), so `no_existing_ai` (+4) behaviour is inconsistent. The **LLM 7-gate** (`llm_qualification.py`, route `llm_qualify.py`) is **not scheduled** — `llm_qualified_at` is NULL on all 4,061 companies.
- **Change:** (a) fix Bug 1 → `if state and state in qualifying`; (b) make scoring skip companies with no `research_intelligence` rather than scoring them (ties to R5 no-research gate); (c) register `_run_llm_qualification` in the scheduler and gate draft-eligibility on `llm_qualified_at` + a passing gate result.
- **Touchpoints:** `backend/app/agents/qualification.py:270,308`; `config/scoring.yaml:68–73,248–264`; `backend/app/api/main.py` (add job); `backend/app/agents/llm_qualification.py`.
- **Test:** `test_null_state_no_midwest_bonus()`; `test_unresearched_company_not_qualified()`; `test_llm_gate_populates_llm_qualified_at()`.
- **Acceptance:** `llm_qualified_at` populated; qualification correlates with verifiable fit; no company scored without research.
- **Effort:** 2.  **Depends on:** R5.

### R8 — Sequence-completion engine
- **Current state:** `sequence_step` lives on `outreach_drafts`. Send-time assertions already enforce `assert_prior_step_sent()` and `assert_minimum_step_gap()` (Step 2 = 3d, Step 3+ = 2d). **But no explicit orchestrator generates Step 2+ after Step 1 sends**, Step-2 drafts don't reference Step-1 (only 5% do), and openers aren't auto-followed-up (41 dropped). Daily cap is **125** (`limits.yaml:81`) — the "500" in code is a fetch-pool size, not a send cap.
- **Change:** build/clarify the step orchestrator: after Step N sends and the gap elapses, generate Step N+1 for non-repliers; pass prior-step subject/body into the generation context and add a draft-validation rule that Step N must reference Step N-1; auto-queue follow-ups on openers.
- **Touchpoints:** `backend/app/core/dispatch_scheduler.py`; `backend/app/agents/engagement.py:_process_due_sequences` (sequence state in `engagement_sequences`); `backend/app/agents/outreach.py` (step context + validation).
- **Test:** `test_step2_generated_after_step1_gap()`; `test_step2_references_step1()`.
- **Acceptance:** contacts advance through the full sequence unless they reply/opt out; Step-2 without a Step-1 reference fails validation.
- **Effort:** 3–5 (orchestrator location is an open question).  **Depends on:** R4/R5.

---

## WORKSTREAM D — Deliverability + autonomy (Tier 3)

### R9 — Domain consolidation + proper cold sender
- **Current state:** sender chosen by `_pick_sender()` (`engagement.py:466–475`, MD5 hash % pool) from `outreach_send_config.sender_pool` (DB) or YAML; reply-to hardcoded `avi@digitillis.io`. Instantly is imported but **not used for sends** (Resend is exclusive). 9 domains in play; 4 `hello@` mailboxes deleted; Instantly paused.
- **Change:** consolidate to 1–2 warmed dedicated cold domains with coherent brand pages; trim `sender_pool`; set per-mailbox caps (100–200/day) and inbox rotation; run a deliverability/placement test before resuming. Largely ops + config, modest code.
- **Touchpoints:** `outreach_send_config` rows; `config/outreach_guidelines.yaml`; DNS/brand (non-code); `engagement.py:434–475`.
- **Test:** `test_sender_pool_only_warmed_domains()`.
- **Acceptance:** one coherent sender identity survives a Google check; placement test passes; caps enforced.
- **Effort:** 2–3 incl. DNS/warm-up lead time.  **Depends on:** none (parallelizable).

### R10 — Fix the inverted autonomy split
- **Current state:** full job list mapped (`main.py:2211–2449`): `draft_generation` every 5 min, `qualification` every 15 min, `dispatch_loop` Mon–Fri 8–11 Chicago (sole send path; `send_approved` retired; `auto_approve` disabled 2026-05-08). Approval via `POST /api/approvals/{id}/approve` with an attestation object; Tier-1 dual-review exists; per-reviewer daily cap default 500.
- **Change:** stop relying on serial per-email approval. With R4/R6 enforcing quality automatically, switch the human checkpoint to (a) **ICP/list approval upstream** and (b) **sampled QA** (e.g. review a 20% sample, not 100%); keep dual-review only for a defined high-risk tier. Move reply-handoff judgment downstream (R11).
- **Touchpoints:** `backend/app/api/routes/approvals.py:375–650`; `dashboard/app/approvals/page.tsx`; scheduler config in `main.py`.
- **Test:** `test_sampled_qa_routing()` (only a sample requires human approval; the rest auto-clear via R4 gate).
- **Acceptance:** founder no longer reviews every email; rejection rate reflects real gating; human checkpoints exist at ICP-in and reply-out.
- **Effort:** 2–3 (part process design).  **Depends on:** R4, R6.

---

## WORKSTREAM E — Learning loop + anti-regression (Tier 4)

### R11 — Surface the handoff + north-star metric
- **Current state (corrected):** warm replies already route to `hitl_queue` via `_push_reply_to_hitl()` (`main.py:796–809`, priority interested=1/referral=2/objection=3/question=3); HITL routes exist (`/api/hitl/queue*`). No dashboard view; no cost-per-qualified-conversation metric. No `crm_leads`/`opportunities` tables (use `campaign_threads` + `hitl_queue`).
- **Change:** add a dashboard `/hitl` page over the existing queue with the action set (continue_sequence / manual_reply / mark_converted / unsubscribe / archive / snooze); add a metrics job computing cost per qualified manufacturing conversation; feed reply sentiment into ICP/list refinement.
- **Touchpoints:** `dashboard/app/hitl/` (new); `backend/app/api/routes/hitl*`; new metrics job in `main.py`.
- **Test:** `test_interested_reply_enters_hitl_queue()`.
- **Acceptance:** warm replies are visible + actionable in one view; north-star metric computed.
- **Effort:** 2.  **Depends on:** R1 (replies must be ingested first).

### R12 — Close the diagnose-claim-rediscover loop
- **Current state:** pytest suite (`tests/test_workflow.py`, `test_e2e.py`, `conftest.py`); CI at `.github/workflows/ci.yml` runs ruff + compileall + pytest + a staging smoke test. (Note: CI invokes `pytest backend/tests/` while test files live in `tests/` — verify the path before relying on it.)
- **Change:** every remediation R1–R11 ships with the regression test named above, wired into CI so a reverted behaviour breaks the build. Maintain ONE append-only run log; create no new audit/strategy docs. (The bounce gate is already enforcing at `pre_send_assertions.py:359` — the recurring "is it advisory?" doubt was doc drift, the exact pattern to kill.)
- **Touchpoints:** `tests/`; `.github/workflows/ci.yml`; one run-log file.
- **Acceptance:** each fixed item has a CI test; reverting any fix fails CI; no new process docs.
- **Effort:** 1–2 baseline + the per-item tests already counted above.  **Depends on:** all.

---

## Sequencing (maps to the 90-Day Recovery Plan)

```
Phase 1 (Wk 1-2)  Correctness:  R1 → R2 → R3        + R12 CI scaffold        ~3-4.5 dev-days
Phase 2 (Wk 3-5)  Personalize:  R5 → R4 → R6 ; R7   (R5 is the long pole)    ~8-12 dev-days
                  Sequence:     R8                                            ~3-5 dev-days
Phase 3 prep      Deliver/auto: R9 (parallel) ; R10 ; R11                     ~6-8 dev-days
Phase 3 (Wk 6-10) Run the 100-200 account cohort on the above
Phase 4 (Wk 11-13) Go/No-Go against the kill-criteria
```

**Critical path:** R5 (research depth) gates R4, R6, R7, R8 — start R5 on day 1 in parallel with the Tier-0 fixes. R1 gates R11. R4/R6 gate R10.

**Total backend effort:** ~25–35 dev-days, front-loaded so the cohort-gating set (R1–R8) is ready by end of Week 5.

## Migrations required
1. `*_scheduler_state.sql` (R1) — last-run cursor.
2. `*_claim_queue_approval_guard.sql` (R2) — add `approval_status` filter to `claim_outbound_queue_batch`.
3. `*_research_intelligence_extend.sql` (R5, if deepening the schema) — per-individual signal columns.
(R11 reuses existing tables; no new CRM migration.)

## Open questions to resolve before starting
1. **Budget (R5):** re-enabling research + enrichment spends Apollo/Perplexity credits. Per standing policy, raising any spend cap needs explicit approval — confirm the budget before un-pausing. The Apollo credit guard (`enrichment.py:93`) stays in place regardless.
2. **Sequence orchestrator (R8):** no explicit Step-2 generator was found in the read window; confirm whether step advancement lives in `engagement.py:_process_due_sequences` or a `sequences.yaml`-driven path before estimating the upper bound.
3. **`no_existing_ai` default (R7):** awarding +4 when research is blank is arguably wrong (absence of evidence ≠ positive signal). Recommend skipping unresearched companies entirely (ties to R5) rather than defaulting the bonus — confirm intent.
4. **CI test path (R12):** reconcile `pytest backend/tests/` (in `ci.yml`) vs the `tests/` directory before depending on CI to catch regressions.
5. **Demo/protected paths:** none of R1–R12 touch the FirstLook client-facing assets; if any dashboard work strays into protected paths, it needs founder approval first.
