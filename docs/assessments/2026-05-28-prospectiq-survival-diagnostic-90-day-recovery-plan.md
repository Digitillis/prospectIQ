# ProspectIQ Survival Diagnostic — 90-Day Recovery Plan

*Date: 2026-05-28  |  Verdict: C — Partial Rebuild  |  Confidence: HIGH*

*Author: Avanish Mehrotra & Digitillis Technical Team*

*Revised 2026-05-28: channel fixed to COLD outbound. FirstLook/warm-hook steps removed.*

---

90-DAY RECOVERY PLAN. Sequenced, week-by-week. ProspectIQ stays a cold-outbound channel; the work is to make it 1:1 personalized and to fix the platform. No new sends until the personalization gate and measurement are in place. Hard kill-criteria named. No new process/audit/strategy documents — append to one run log only. Engineering specifics are in the companion **Platform Remediation Plan** (this is the schedule; that is the spec).

PHASE 1 — FIX MEASUREMENT + CORRECTNESS (Weeks 1-2). Nothing else is trustworthy until measurement works. (Remediations R1-R3, R9-start.)
- Week 1: (a) Replace UNSEEN-only IMAP with SINCE-last-run OR Gmail label-based ingestion (gmail_imap.py:175) so replies are captured even after a human reads them. (b) Close the pipeline-integrity gap so a rejected draft can never send (46 did). (c) Add scanner/bot-click filtering (drop co-registered open+click, sub-2-min gaps) so engagement metrics are real. (d) Stand up a minimal CRM/handoff table; unmark the 5 scanner-promoted companies; mark Waupaca engaged.
- Week 2: (a) Begin domain consolidation: pick one or two warmed dedicated cold domains with coherent brand pages; retire the rest; move off transactional-Resend-for-cold to a proper cold sender. (b) Instrument the single north-star metric: cost per qualified manufacturing conversation. (c) Write the one-page hard ICP (1-2 verticals, e.g. foundry/casting + aerospace-composites, with equipment signature and a regulatory/operational trigger). A deliverable, not a process doc.
- KILL-CRITERION (end Week 2): if reply ingestion cannot capture a test reply end-to-end, escalate — do not proceed to sends.

PHASE 2 — BUILD THE PERSONALIZATION ENGINE (Weeks 3-5). Make the cold email 1:1. (Remediations R4-R8.)
- Week 3: (a) Re-enable and DEEPEN enrichment (EnrichmentAgent, paused 2026-05-07): per-individual facts — named recent events, specific assets/equipment signatures, the contact's role and recent activity. No-research-no-draft. (b) Wire the existing LLM 7-gate qualification into the scheduler (today it is only on an on-demand route; llm_qualified_at is NULL everywhere) and fix the rule-based scorer's broken bonuses (state=NULL Midwest +3, no_existing_ai default +4).
- Week 4: (a) Enforce the verifiable-hook contract: no Step-1 draft passes integrity unless it cites at least one company- or person-specific fact with a source. Make the Waupaca / AMETEK-VAR / APP-NADCAP email the template standard. (b) Retire the three recycled stat ranges and the "18 days out" verbatim claim; kill the "time-based maintenance" / "typically" / "Curious —" / "or is it something else" template fingerprints (block or rotate). (c) Hand-curate ~100-200 high-fit Tier-1 accounts.
- Week 5: (a) Build the sequence-completion engine (89% of contacts only ever got Step 1; abandon nothing). Enforce Step-2-references-Step-1 (only 5% do today); auto-follow-up on openers (41 openers were dropped). (b) Replace per-email rubber-stamp review with the automated personalization gate + sampled QA; move human judgment to ICP/list approval (upstream) and reply handoff (downstream). (c) One-time: founder reviews the first batch of personalized Step-1 emails to calibrate the gate, then steps out of serial review.

PHASE 3 — THE GO/NO-GO COHORT (Weeks 6-10). One decisive cold experiment, done right.
- Weeks 6-9: Run the 100-200 account cold campaign on the warmed domain — every email meeting the specificity bar, fully sequenced (all steps), qualification real, measurement clean. A/B personalization depth (deep asset-specific vs lighter event-hook) to learn what specificity threshold actually converts. Measure: genuine open rate (post bot-filter), reply rate, qualified conversations, meetings.
- Week 10: Read results against kill-criteria.

PHASE 4 — DECISION (Weeks 11-13).
- If the cohort succeeds: codify the playbook, scale to 200-400 accounts/month at the proven specificity (NOT volume), keep the human at ICP/list + handoff. Verdict holds: partial rebuild succeeded; ProspectIQ continues as a cold channel.
- If the cohort fails: verdict flips to RETIRE-OUTBOUND. Reallocate to phone/peer-referral/industry-event motion. Do not iterate the email machine further.

HARD KILL-CRITERIA (binary, observable — these break the diagnose-claim-rediscover loop):
1. Week 2: reply capture not proven end-to-end -> STOP, do not send.
2. Week 10: cohort genuine open rate (post-bot-filter) < 15% -> deliverability/domain still broken; do not scale.
3. Week 10: cohort reply rate < 1.5% on a completed, fully-personalized sequence -> message/value-prop fails even at specificity; retire outbound.
4. Week 10: zero qualified manufacturing conversations from 100-200 fully-sequenced, deeply-personalized cold accounts -> retire outbound, pivot to phone/referral/events.
5. Any phase: a "FIXED" item rediscovered unfixed in the run log -> the org-loop has reasserted; escalate to founder before continuing.

GUARDRAILS THROUGHOUT: channel stays cold (no warm/FirstLook motion); no volume increase beyond 100-200/day/mailbox; no autonomous sends without the personalization gate passing; no new audit/triage/strategy documents (one append-only run log); every remediation ships with a regression test so it cannot silently revert.
