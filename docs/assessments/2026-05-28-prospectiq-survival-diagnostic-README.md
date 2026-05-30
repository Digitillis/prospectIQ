# ProspectIQ Survival Diagnostic — Index

*Date: 2026-05-28  |  Verdict: C — Partial Rebuild  |  Confidence: HIGH*

*Author: Avanish Mehrotra & Digitillis Technical Team*

---

**Channel decision (fixed 2026-05-28):** ProspectIQ stays a **cold-outbound** channel. An earlier draft recommended a warm/FirstLook-anchored pivot; that is **withdrawn at founder direction.** The lever is per-individual personalization + platform remediation, not a channel change.

**Recommendation one-liner:** Keep the working plumbing; rebuild the personalization, enrichment, sequence, qualification, and measurement layers so every COLD email is genuinely 1:1 personalized (the Waupaca standard), and remediate the platform defects before any resume. Not retire, not scale, not a from-scratch replace.

## Deliverables

- [Executive Assessment](2026-05-28-prospectiq-survival-diagnostic-executive-assessment.md)
- [Diagnostic Report](2026-05-28-prospectiq-survival-diagnostic-diagnostic-report.md)
- [Architecture Assessment](2026-05-28-prospectiq-survival-diagnostic-architecture-assessment.md)
- [Strategic Recommendation](2026-05-28-prospectiq-survival-diagnostic-strategic-recommendation.md)
- [Platform Remediation Plan](2026-05-28-prospectiq-survival-diagnostic-platform-remediation-plan.md) — prescriptive engineering fixes (R1-R12)
- [Technical Implementation Plan](2026-05-28-prospectiq-survival-diagnostic-implementation-plan.md) — code-grounded execution plan (files, migrations, tests, effort, sequencing)
- [90-Day Recovery Plan](2026-05-28-prospectiq-survival-diagnostic-90-day-recovery-plan.md)

## Top evidence points driving the verdict

1. VERIFIED IN CODE: reply capture is broken — gmail_imap.py:175 polls UNSEEN-only; gmail_imap interactions=0, reply_classifications=0 rows, outreach_outcomes.replied_at=0 rows; the system has never ingested a reply via IMAP. Nathan Thayne's May 16 scheduling invitation ('call whenever or send me an email next week') has NO database record anywhere — a live opportunity silently lost.
2. VERIFIED IN CODE: qualification is circular — outreach.py:604 drafts only for status='qualified', but the LLM 7-gate (llm_qualification.py) is wired ONLY to the on-demand route routes/llm_qualify.py, never registered in the scheduler (main.py registers rule-based _run_qualification, not _run_llm_qualification). llm_qualified_at is NULL on all 4,061 companies. 'Qualified' = keyword-matching against AI-generated, often confidence=low research text.
3. VERIFIED IN CODE: autonomy split is inverted — main.py registers _run_draft_generation every 5 min and _run_qualification every 15 min (both autonomous), while sends are gated behind per-email human review that passed 99.3% of 1,250 emails (8 genuine rejections total). The human is a rubber stamp at the wrong layer.
4. VERIFIED IN CODE: the bounce gate IS enforcing — pre_send_assertions.py:359 assert_bounce_rate_ok defaults to send_path and raises AssertionFailure to block sends above 2%. The recurring May 25 'is it advisory?' concern is closed in code; docs never caught up — itself proof of the diagnose-claim-rediscover loop.
5. Engagement is bot-inflated: 94% click-to-open ratio (norm 10-25%), fully co-registered open/click events, 36 of 51 clicks carry scanner signatures. Genuine human reads are ~20-30, not the 53 reported — so '0 replies' sits on a far smaller real-reader base than headline numbers suggest.
6. The corpus is bimodal and the templating is measurable: 'time-based maintenance' in 35% of emails, 'typically' in 56%, three recycled stat ranges (15-20%/23-41%/40-65%) sprayed identically across foundries/dairies/aerospace, '18 days out' verbatim in 127 emails across asset classes it cannot uniformly apply to.
7. The single confirmed reply (Waupaca Foundry, Nathan Thayne, Melt Manager) came from the most asset-specific email in the corpus — proving personalized outreach works while templated bulk does not. The best 15-20% (Waupaca, AMETEK VAR, ECMS carve-out, Sekisui/Boeing) are good enough to send today.
8. Targeting is NOT the problem: 77.9% decision-maker flag, Plant Manager+COO+VP Ops = 64.8% of sends; the alarming '239 non_mfg contacts' is a labeling bug (Tsubaki Nakashima, Dezurik, GKN are real manufacturers); true contamination ~30-50 companies (4-6%).
9. The sequence was abandoned, not completed: 89% of sends were Step 1, 88.8% of contacts got only Step 1, and 120 of 126 Step-2 emails (95%) do not reference Step 1 — so '0 replies' is not a demand verdict, it is a truncated, memoryless early sequence.
10. The strategic error is volume over precision plus an unused warm asset: ProspectIQ has NO signal layer (every 2026 competitor has one) and never uses the FirstLook diagnostic, which converts at 3-5x a cold opener per Gong/ZoomInfo comparables. Scaling makes it worse — the AI-SDR collapse shows deliverability falling 90%->under-60% by week 4 and $150-300/meeting at volume.
11. The organizational root is a chronic diagnose-claim-rediscover loop: every defect declared FIXED then rediscovered 1-2 weeks later (bounce gate, reply tracking, email_status nulls, hallucinations, approved_by fields, pacing config never applied); 50+ docs produced while commercial outcomes never moved; the May 12 'copilot not pilot' doctrine contradicted by 1,247 autonomous sends.
12. 46 already-rejected drafts were sent anyway (pipeline integrity gap), and the quality filter correctly caught hallucinations (fabricated_anecdote x22, unverified_confidence_metric x38) yet 1,250 passed with softer versions of the same claims — the gate filters the obvious and lets the systemic through.

