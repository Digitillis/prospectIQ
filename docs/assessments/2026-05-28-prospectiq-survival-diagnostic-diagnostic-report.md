# ProspectIQ Survival Diagnostic — Diagnostic Report

*Date: 2026-05-28  |  Verdict: C — Partial Rebuild  |  Confidence: HIGH*

*Author: Avanish Mehrotra & Digitillis Technical Team*

---

FINDINGS, EVIDENCE, ROOT CAUSES, SEVERITY. All four load-bearing technical claims independently verified against live code in /Users/avanish/prospectIQ on 2026-05-28.

== SEVERITY: CRITICAL ==

F1 — Reply capture is structurally broken; a live opportunity was silently lost. ROOT CAUSE (verified): /Users/avanish/prospectIQ/backend/app/integrations/gmail_imap.py:175 runs self._conn.search(None, "UNSEEN"). Because the founder reads his own Gmail before the 15-minute cron fires, every reply is SEEN before ingestion. EVIDENCE: gmail_imap interactions = 0 (never ingested a reply via IMAP); reply_classifications table = 0 rows; outreach_outcomes.replied_at = 0 rows; all 105 inbox messages SEEN. Nathan Thayne (Waupaca Foundry) sent two genuine replies — May 11 (substantive technical engagement) and May 16 (explicit scheduling invitation "call whenever or send me an email next week"). The May 16 reply has NO database record anywhere. Waupaca is NOT marked engaged. SEVERITY CRITICAL because it lost the single warm opportunity the entire campaign produced. FIX: replace UNSEEN with SINCE-last-run or Gmail label-based ingestion before any resend.

F2 — Qualification is circular; "qualified" is keyword-matching against AI-generated text. ROOT CAUSE (verified): /Users/avanish/prospectIQ/backend/app/agents/outreach.py:604 drafts only for get_companies(status="qualified"). But the LLM 7-gate (LLMQualificationAgent in backend/app/agents/llm_qualification.py) is referenced ONLY by the on-demand API route backend/app/api/routes/llm_qualify.py — it is NOT registered in the scheduler. backend/app/api/main.py registers _run_qualification (rule-based PQS keyword scorer) every 15 min and _run_draft_generation every 5 min; there is no _run_llm_qualification job. Consistent with llm_qualified_at = NULL on all 4,061 companies. EVIDENCE: "qualified" therefore means keyword-matched against research_intelligence text that is itself AI-generated, frequently confidence=low with empty known_systems. 2,524 of 2,659 "researched" companies (95%) have no research_intelligence record yet were scored. The "no_existing_ai" signal awards 4 points by default (absence of competitor evidence scored as positive). The Midwest geography bonus fires on state=NULL (62% of contacts), awarding +3 for missing data. SEVERITY CRITICAL because the 38.9-42% "qualified" rate is activity, not signal — it does not protect the funnel (2 of 5 "engaged" companies are non_mfg-tagged, one is Planesense, a fractional-jet company clearly off-ICP).

== SEVERITY: HIGH ==

F3 — Message corpus is bimodal; 60-65% is recognizable templated output. EVIDENCE: "time-based maintenance" in 35% of all 1,250 emails; "typically" introducing a generic benchmark in 56%; three recycled stat ranges (15-20% / 23-41% / 40-65%) attributed to SMRP 2023 / LNS 2024 in near-identical phrasing across steel, dairy, foundry, aerospace; "18 days out" verbatim in 127 emails across foundry furnaces AND offshore compressors. Body length clusters at 735 chars with low variance — a machine tell. The top 15-20% (Waupaca, AMETEK VAR, ECMS carve-out, Sekisui/Boeing) are asset-specific and event-hooked; the single confirmed reply came from this cohort. ROOT CAUSE: unconstrained AI generation with no retrieval grounding; the May 12 evidence-constraint fix removed fabricated anecdotes but generic claims ("plants running similar setups") still pass the integrity regex. SEVERITY HIGH because the templated bulk earns conditioned deletes from experienced buyers — this is a real reply-suppressor independent of the soft CTA.

F4 — Per-email human approval is a rubber stamp and the autonomy split is inverted. EVIDENCE: 99.3% approval rate on 1,250 emails; 8 genuine quality rejections total. 46 already-rejected drafts were sent anyway (pipeline integrity gap). The scheduler runs draft generation autonomously every 5 minutes while a human serially reviews every draft before send. ROOT CAUSE: judgment placed at the wrong layer — downstream per-email instead of upstream signal/ICP precision. SEVERITY HIGH because it consumes the founder's scarcest resource, filters nothing, and manufactures false confidence.

F5 — Sequence abandoned; campaign never tested. EVIDENCE: 1,116 of 1,250 sends are Step 1 (89%); 126 Step 2; 8 Step 3/4. 88.8% of contacts received only Step 1. Of 126 Step-2 emails, 120 (95%) do not reference Step 1 — they re-introduce the product from scratch, signaling no human is behind the outreach. 41 contacts who opened Step 1 were never followed up. SEVERITY HIGH because the value prop (Steps 3+) was never delivered — the 0-reply result cannot be read as a demand verdict.

== SEVERITY: MEDIUM ==

F6 — No signal/intent layer. ProspectIQ sends to static Apollo pulls with no trigger timing. Detectable manufacturing buying signals (new Maintenance/Reliability Director hire, CMMS/ERP replacement, capex, reliability-engineer job postings) are all uncaptured. Every 2026 competitor runs at minimum a Layer-3 signal stack. MEDIUM at 1,250 sends, CRITICAL at scale.

F7 — Engagement metrics inflated by bots. EVIDENCE: 94% click-to-open ratio (norm 10-25%); fully co-registered open/click events; 36 of 51 clicks carry bot signatures (opened-after-clicked or sub-2-minute gaps); AMETEK shows 6 click events for one email, Waupaca 15 open events for one email. Genuine human reads ~20-30, not 53. The two "human-engagement signals" cited in the May 8 baseline (AMETEK, Tsubaki) were scanner clicks; AMETEK's contact email is at grahampackaging.com (stale enrichment), not an AMETEK domain.

F8 — Sending architecture misaligned. Nine sending domains (getdigitillis.com, meetdigitillis.com, trydigitillis.com, usedigitillis.com, digitillis.io) fragment brand and trip spam heuristics. Resend is a transactional provider used for cold outbound; Instantly (warm-up only) is now paused with 4 hello@ mailboxes deleted. Live send capability is effectively halted.

== RESOLVED / RETIRE-THE-CONCERN ==

F9 — Bounce gate IS enforcing. Verified: backend/app/core/pre_send_assertions.py:359 — assert_bounce_rate_ok defaults assertion_context="send_path" and raises AssertionFailure to block all sends when 7-day contact-scoped bounce rate exceeds 2%. The recurring May 25 "is it advisory or enforcing?" question is closed in code; documentation never caught up. This staleness is itself diagnostic of F10.

F10 — Chronic diagnose-claim-rediscover loop (organizational root). The timeline shows every defect declared FIXED then rediscovered 1-2 weeks later (bounce gate, reply tracking, email_status nulls, hallucinations, approved_by/reviewed_at fields, pacing config daily_limit 500→50 never applied). 50+ docs produced; outcomes never moved. The May 12 "copilot not pilot" doctrine was contradicted by 1,247 autonomous sends. This is the meta-cause that perpetuates F1-F8.
