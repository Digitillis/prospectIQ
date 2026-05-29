# ProspectIQ Survival Diagnostic — Architecture Assessment

*Date: 2026-05-28  |  Verdict: C — Partial Rebuild  |  Confidence: HIGH*

*Author: Avanish Mehrotra & Digitillis Technical Team*

---

CURRENT ARCHITECTURE (as built and verified):
Pipeline: Apollo sourcing -> EnrichmentAgent (PAUSED 2026-05-07) -> rule-based PQS qualification (_run_qualification, every 15 min, autonomous) -> AI draft generation (_run_draft_generation, every 5 min, autonomous) -> per-email human approval (99.3% pass) -> dispatch_loop send via Resend (Mon-Fri 8-11 Chicago) -> Instantly warm-up (PAUSED) -> IMAP reply poll (UNSEEN-only, broken). No CRM tables. No signal layer. No closed-loop learning. Pre-send governance: 9 assertion types including a working bounce gate.

WHAT IS SOUND:
- Sourcing/targeting: 77.9% decision-maker, correct persona mix; contamination only ~4-6%.
- Draft generation mechanics: functional; top 15-20% of output is genuinely good.
- Delivery: Resend 94.3% delivered, 0 complaints (for low volume).
- Bounce governance: assert_bounce_rate_ok enforces in send_path, blocks above 2% (verified pre_send_assertions.py:359).
- Atomic send-claim, JSON-parse fix (PR #76), tiered suppression: all real and working.

THE GAP (current vs required):
1. AUTONOMY SPLIT INVERTED. Current: autonomous at draft-gen + qualification, manual rubber-stamp at send. Required: autonomous at research/enrichment/draft-prep, human at (a) upstream signal-tier targeting decision and (b) warm-reply -> conversation handoff. Verified inversion: _run_draft_generation every 5 min vs per-email serial review.
2. NO SIGNAL LAYER. Current: static Apollo list, no timing. Required: trigger-based prioritization (Maintenance/Reliability Director hires, CMMS/ERP evals, capex, reliability job postings). Every 2026 competitor has this as baseline.
3. QUALIFICATION IS DECORATIVE. Current: keyword PQS on AI-generated text; LLM 7-gate wired only to on-demand route, never to scheduler (llm_qualified_at NULL everywhere). Required: evidence-grounded qualification with verifiable company-specific facts, OR drop the pretense and use signal-tier routing.
4. NO ENFORCED PERSONALIZATION + STARVED ENRICHMENT. Current: drafts can be — but are not required to be — company/person-specific, so 60-65% ship as interchangeable templates; the EnrichmentAgent is PAUSED (since 2026-05-07) and 95% of "researched" companies have no research_intelligence record to personalize from. Required: a hard per-individual personalization gate (no verifiable, named, company/person-specific hook -> no send) fed by re-enabled, deepened enrichment. This keeps the channel cold; it makes the cold email 1:1. (Channel decision: cold outbound, fixed. A warm/FirstLook-anchored motion is explicitly out of scope per founder direction.)
5. WRONG DELIVERY STACK. Current: 9 domains + transactional Resend for cold + paused Instantly. Required: ONE warmed dedicated cold domain, inbox rotation, 100-200/day/mailbox caps, placement testing.
6. BROKEN MEASUREMENT. Current: UNSEEN-only IMAP (0 replies ingested ever), bot-inflated opens, no CRM. Required: SINCE-last-run/label-based ingestion, scanner-click filtering, a minimal CRM/handoff table, a cost-per-qualified-conversation metric.
7. NO CLOSED-LOOP LEARNING. Current: reply outcomes do not refine targeting. Required: reply sentiment -> ICP/signal update -> upstream list refinement.

VERDICT: The substrate (sourcing, drafting, delivery, governance) is reusable. The per-individual personalization gate, enrichment depth, sequence engine, qualification semantics, delivery consolidation, and measurement/learning loop need to be rebuilt — all in service of a better COLD channel, not a channel change. This is partial rebuild, not full replace and not incremental patching — the layers above the plumbing are wrong even though the mechanics are right.
