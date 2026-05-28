# ProspectIQ Platform and GTM — Tri-Persona Critical Evaluation
**Date:** 2026-05-25
**Author:** Avanish Mehrotra & Digitillis Technical Team
**Status:** Internal assessment
**Prior baseline:** [GTM Performance Assessment 2026-05-08](../GTM_PERFORMANCE_ASSESSMENT_2026-05-08.docx) — score 3.4/10, all sends halted

---

## 0. Executive Summary

ProspectIQ has matured into a moderately sophisticated outreach platform with proper governance scaffolding (atomic send claims, pre-send assertions, bounce-rate gates, human approval). The infrastructure is no longer the binding constraint.

**The binding constraint is now message quality and campaign effectiveness, not plumbing.** After ~1,300 sends, the platform is producing:

- **4.7% open rate** at Step 1, decaying to **0% at Step 3**
- **0 replies** captured in `campaign_threads` (entire history)
- **4.2% bounce rate** at Step 1, more than 2× the safe ceiling
- **154 drafts auto-rejected for "systemic" defects**, **118 for "model hallucination"**, out of ~500 rejections

This is not a sending-infrastructure problem. It is a **product–market fit problem at the messaging layer**, compounded by a list-quality problem and a feedback-loop problem. The platform is sending well-engineered emails to a poorly-qualified list with content that reads as generic, and there is no closed-loop learning when reply data is effectively zero.

**Verdict scores (this assessment):**

| Dimension | Score (10) | Direction vs. May 8 |
|---|---|---|
| Technical maturity (plumbing) | 7.0 | Up from ~5 |
| Outreach / GTM mechanism | 4.0 | Flat |
| Campaign effectiveness | 2.5 | Down from 3.4 |
| Messaging and prospect value | 3.5 | Flat |
| **Composite** | **4.3** | **Up from 3.4 but driven by infra, not outcomes** |

The infrastructure built in the last six weeks deserves credit. The GTM channel built on top of it has not yet produced a single recorded reply. That gap defines the next 60 days.

---

## 1. Methodology

Three personas evaluated the platform independently before findings were merged:

1. **Adversarial tester** — looking for silent failures, governance bypasses, integrity violations, and operational fragility.
2. **Technical expert** — evaluating architecture, data integrity, observability, scalability, and design quality.
3. **Business stakeholder** — evaluating GTM economics, message quality, conversion math, and channel viability against the cost of operation.

Evidence base: codebase walkthrough (`backend/app/agents/`, `backend/app/core/`, `backend/app/api/routes/`, `dashboard/app/approvals/`), live database snapshot (12,407 contacts, 2,091 drafts, 1,247 sends), prompt and sequence config (`config/outreach_guidelines.yaml`, `outreach.py:200-498`), and prior assessment ([May 8 GTM Performance Assessment](../GTM_PERFORMANCE_ASSESSMENT_2026-05-08.docx)).

---

## 2. Current State — The Numbers That Matter

### 2.1 Funnel reality

| Stage | Count | Comment |
|---|---|---|
| Contacts in DB | 12,407 | — |
| Enriched contacts | 8,913 | 72% of total |
| Email status known | 5,575 (45%) | **55% of contacts have null email_status — never validated** |
| Email status `verified` | 4,713 | Only 38% of total |
| `is_outreach_eligible = TRUE` | 11,571 | Eligibility flag is much wider than actual sendability |
| Step-1 sent | 1,116 | |
| Step-1 opens | 53 (4.7%) | Industry cold outreach floor for B2B is ~20% |
| Step-1 clicks | 50 (4.5%) | Suspiciously close to opens — likely bot/security-scanner clicks |
| Step-1 **bounces** | **47 (4.2%)** | **Above safe ceiling of 2%** |
| Step-2 sent | 126 | 11% of step-1 cohort followed up |
| Step-2 opens | 2 (1.6%) | |
| Step-3 sent | 5 | |
| Step-3 opens | 0 | |
| Replies (campaign_threads.status='replied') | **0** | **Zero recorded replies in entire platform history** |

The May 8 assessment noted "AMETEK + Tsubaki are the only credible human signals." Two months later, those still appear to be the only signals — and they are not in the captured reply data.

### 2.2 Draft-quality signal

| Approval status | Count | % of drafts |
|---|---|---|
| Approved | 1,213 | 58% |
| Pending | 369 | 18% |
| Rejected | 502 | 24% |

Rejection breakdown is more important than the rate. The two largest categorical rejections are **systemic (154)** and **model_hallucination (118)**. Together they are over **half of all rejections**. These are **content-generation defects**, not data-quality defects. The system is generating defective drafts at industrial scale, and only a manual approval step is catching them. A platform that needs human review to filter half of its own output is not yet a platform; it is a supervised content factory.

### 2.3 Funnel decay vs. cold-outreach benchmarks

| Metric | ProspectIQ actual | B2B cold-outreach benchmark | Gap |
|---|---|---|---|
| Open rate (Step 1) | 4.7% | 20–40% | **4–8× below floor** |
| Reply rate (cumulative) | 0.00% | 1–3% | **Effectively at zero** |
| Bounce rate | 4.2% | <2% | **2× too high** |
| Click rate vs. open rate | 94% | 10–25% | **Suggests bot clicks dominate** |

The 94% click-to-open ratio is the most diagnostic number on this page. In normal cold outreach, ~10–25% of openers click a link. A 94% click-to-open ratio means most of those "clicks" are security tools and email scanners (Mimecast, Proofpoint, Microsoft Safe Links) pre-fetching URLs before a human ever sees the email. **Real human engagement is therefore below 4.7% opens** — likely closer to 2%.

---

## 3. Persona 1 — Adversarial Tester (silent failures, integrity, governance)

### 3.1 Findings

**A. Bounce-rate governance is wired but the platform is already breaching it.**
`assert_bounce_rate_ok` uses a 7-day window with a 2% ceiling (`MAX_BOUNCE_RATE`). The platform's measured Step-1 bounce rate is **4.2%**. This means one of three things is true: (a) the assertion was disabled, (b) the assertion runs in `draft_gen` context (advisory) but not `send_path` (enforcing), or (c) the rolling window is sliding fast enough that point-in-time samples stay under 2% while cumulative is above. All three are governance defects.

**B. Pre-send assertion exception handling is too broad.**
`engagement.py` catches `except Exception` around the assertion block. This means any unexpected error (network blip, transient DB failure, code regression) is indistinguishable from a legitimate governance block. Rollback fires for both. Telemetry can't tell you whether a draft was blocked for governance reasons or because of a system bug. **The audit trail of "why was this not sent" is corrupt by design.**

**C. The `send_assertions` audit table can silently fail and the platform continues.**
If the `INSERT` into `send_assertions` fails, only a WARNING is logged; the send proceeds. This is the wrong default for an audit-of-record table — a missing audit record is worse than a missed send. Should be a hard failure (refuse to send) or a transactional write.

**D. Approval gate is not yet defensible.**
The `approved_by` and `reviewed_at` columns are referenced in code but the migration is not deployed. The current fallback gate is just `approval_status='approved'`. There is no reviewer attribution, no dual-review enforcement, and no defensible chain of custody for any send. A single account compromise or stuck cron could approve every draft in the queue.

**E. Reply ingestion silently degrades.**
If Claude classifier fails on an inbound reply, the message is recorded with `intent_label='other'` and `confidence=0.0`, and `auto_actionable=False`. There is no alert. With **0 replies recorded in the system**, this defect cannot currently be observed — but the moment replies start arriving, classifier failures will look identical to "uncategorizable" replies.

**F. The outbound queue has no dead-letter queue.**
Items at `retry_count=2` (3 of 12 current queue items) are one retry away from being silently dropped, with no DLQ to inspect them. The 4 drafts removed from the queue earlier this session (email_status defects) were diagnosable only because someone went looking. There is no system that surfaces "these sends never happened" automatically.

**G. The `_clean()` em-dash sanitizer was producing the same defect it was meant to fix.**
Until fixed today, em dashes were being replaced with `  -  ` (space-hyphen-space), creating a different but equally non-compliant dash artifact. 32 of 84 Step-3 drafts and 3 of 3 Step-4 drafts were affected. **The class of bug here is "post-processing rules without round-trip validation"** — there is no automated test that takes generated content, runs it through the sanitizer, and verifies the result satisfies the brand rules. This will recur in other rules unless tested.

### 3.2 Adversarial tester verdict

The governance scaffolding looks production-grade in shape but has at least three load-bearing holes (broad exception handling, audit insert silent failure, missing approval columns). The platform's biggest risk is not catastrophic failure — it is **slow drift toward a state where the audit trail no longer matches what actually happened**, which then becomes irrecoverable.

**Score: 5/10 governance maturity. The frame is there; the joinery is not yet defensible.**

---

## 4. Persona 2 — Technical Expert (architecture, design, scalability)

### 4.1 Architecture summary

The platform is composed of three loosely coupled subsystems:

1. **Discovery → Enrichment → Qualification** (Apollo + Perplexity + Claude-as-judge) — produces candidate contacts and persona-typed personas.
2. **Generation → Approval → Send** (Claude Opus + dashboard + Resend) — produces drafts, gates them through human review, dispatches them.
3. **Engagement → Reply → Classification** (Resend webhooks + Gmail IMAP + Claude classifier) — captures opens/clicks/bounces and inbound replies, classifies intent.

All three communicate through the Supabase database. There is **no message bus, no event log, no workflow engine**. Coordination is done by polling schedules in `weekend_run.py`, `run_pipeline_loop.sh`, and the in-API job runner.

### 4.2 Strengths

- **Atomic send claim** (`sent_at` set before the Resend API call). This is the right pattern and is correctly implemented. It closes the at-least-once vs. at-most-once question.
- **Workspace scoping** is consistent across the data model.
- **Webhook deduplication** via `provider_events` is defensive.
- **Sender selection is deterministic** (md5 hash of contact email mod pool size) — preserves thread continuity for follow-ups.
- **Integrity check** at draft generation runs regex validators against banned phrases.

### 4.3 Weaknesses

- **No orchestration framework.** Every scheduled job is hand-rolled with `time.sleep()` and `while True`. No retry semantics, no DLQ, no observability, no idempotency keys. The May 2026 stack already includes durable workflow primitives in the parent Digitillis platform (Temporal is the chosen primitive per `project_agentic_platform_roadmap.md`), but ProspectIQ has not adopted them. **This is the single largest architectural debt.**
- **No structured event log.** State transitions (draft → approved → sent → opened → replied) are inferred from timestamps on `outreach_drafts`, not from append-only events. This makes accurate funnel analytics impossible without joins across multiple mutating tables, and makes "rebuild state from events" recovery impossible.
- **Tables are over-loaded with mutable state.** `outreach_drafts` carries 33 columns including approval state, send state, engagement state, rejection state, and content. **A single row tells five different stories**, all of which can be partially true at different times. Event sourcing would split this cleanly.
- **No feature contracts on the messaging layer.** Digitillis-platform has `FeatureContract.from_training()` for ML inputs. ProspectIQ's draft generation accepts a free-form prompt payload that may include `tech_stack`, `pain_signals`, `awareness_level`, or may not — each absence silently degrades draft quality. There is no contract enforcing that a Step-1 prompt has *at least one verifiable hook* from research.
- **Reply path is single-threaded IMAP polling.** Gmail rate limits or transient auth failures stall the loop. At current reply volume (zero) this is invisible; at scale (10/day) it is a Friday-afternoon outage waiting to happen.
- **No observability stack.** No metrics dashboard, no alerts. Operational state is reconstructed by running ad-hoc SQL after the fact. The most-asked question — "are sends going out, and are they working?" — currently requires a human to write a query.
- **Two repos, blurred ownership.** ProspectIQ at `/Users/avanish/prospectIQ/` is a separate codebase from Digitillis-platform at `/Users/avanish/digitillis-platform/`. There is no shared library for primitives like `WorkspaceContext`, `EventLog`, `PreSendAssertion`. Each subsystem reinvents these. **The longer this dual-repo state continues, the harder consolidation becomes.**

### 4.4 Data layer concerns

- **FK relationships are weak.** No explicit `ON DELETE` cascades. Orphan rows are possible if a contact is deleted while drafts reference them.
- **`email_status` is null on 55% of contacts.** This is the field every governance check depends on. Either the validator is not running on enrichment, or the runs are not persisting. This is the **single most impactful data-quality defect on the platform**.
- **No campaign-level aggregation table.** Funnel metrics are recomputed from row-level scans every time. This will not scale beyond 50K contacts.

### 4.5 Technical expert verdict

The platform is at the stage where **a single founder can hold the entire system in their head and operate it**. That is its strength and its ceiling. Every weakness above is solvable in 1–3 sprints if there is engineering capacity. None are existential. But the dual-repo state and the absence of a real event log are compounding — the longer they persist, the more expensive the eventual consolidation becomes.

**Score: 6/10 technical maturity. Production-credible scaffolding, hand-rolled wiring, no event log.**

---

## 5. Persona 3 — Business Stakeholder (channel viability, message value, conversion math)

### 5.1 Channel economics

The current channel produces:
- ~1,300 cold sends in ~6 weeks
- ~60 estimated genuine opens (after stripping bot clicks)
- **0 recorded replies**
- 0 meetings booked
- 0 pilots opened

The operating cost includes Apollo (~$0/mo on free tier, ~$114/mo prior), Resend (~$0/mo at current volume), Instantly warmup ($47/mo through June 20), Anthropic API (~$20 burn rate), ZeroBounce ($16 spent), human review time (~30 min/day). **Cost per recorded reply is undefined (division by zero).** Cost per opener is approximately $20–30, which is acceptable; cost per qualified human reader is unknown because we cannot distinguish humans from scanners in the current click data.

### 5.2 List quality is the upstream root cause

Of 12,407 contacts:
- 55% have null `email_status`
- 4.2% bounce rate at Step 1 confirms the list is not clean
- Apollo free tier (75 credits/mo) cannot keep enrichment current
- ZeroBounce credits are exhausted

We are sending to an **unverified majority of the database** and being surprised when nothing happens. The platform is over-investing in message generation and under-investing in list hygiene.

### 5.3 Message quality — the qualitative read

The closure emails drafted by Opus today (Flux Power / Weber Metals / NY Blower) are good. They are specific, they leave a useful takeaway, and they exit cleanly. **Two of three contacts in that batch had three prior emails with zero engagement.** This is the pattern:

- The platform can produce good emails when the prompt is specific and the contact is hand-curated.
- The platform cannot produce good emails at scale because the generation prompt under-specifies what "good" looks like.
- The integrity regex blocks obvious fabrication but allows generic claims ("manufacturers like yours," "plants in your sector") to pass.
- The four-email arc does not actually escalate — each email is a slightly different angle on the same ask.

### 5.4 The 0-reply problem reframed

A platform that sends 1,300 emails and gets 0 replies is not a sending problem. It is one or more of:
1. **The list is wrong** — these people don't have the pain we're claiming.
2. **The message is wrong** — it doesn't make them feel known.
3. **The offer is wrong** — "15-minute call" is too small to value and too large to commit to without trust.
4. **The brand is wrong** — Digitillis is not yet a known name, and cold email without name recognition needs an aggressive value-first hook.
5. **All four.**

The May 8 assessment scored this 3.4/10. Six weeks of message-quality fixes, sender-pool consolidation, and bounce-rate governance have not moved the reply needle. The conclusion that follows is uncomfortable but inescapable: **the binding constraint is not in the platform. It is in the targeting and the offer.**

### 5.5 Business stakeholder verdict

Cold outreach as currently constructed is **not yet a working channel**. It is consuming engineering attention and operating expense and producing no business signal. If this were a third-party agency invoice, we would have cancelled the contract by week three. The fact that we built it ourselves should not give it special status.

**Two options exist**:
1. **Fix the upstream** — invest one focused sprint in list quality, verification, ICP refinement, and message specificity, then re-test with a small (50–100 contact) cohort.
2. **Decommission the channel** — accept that founder-led inbound, partner channels, and warm intros are likely to be 10× more efficient at this stage, and put cold outreach on ice until we have either (a) a customer who validates the ICP or (b) a budget for an experienced outbound operator.

**Score: 3/10 channel viability. Currently producing no commercial signal.**

---

## 6. Cross-Cutting Issues

### 6.1 No closed-loop learning
Drafts are rejected at industrial scale (502 of 2,091) but the rejection reasons are not fed back into prompt evolution. The same defects recur. A platform that doesn't learn from its own mistakes is a static system pretending to be adaptive.

### 6.2 No experimentation framework
There is no A/B testing, no holdout, no message-variant tracking. We do not know whether `email_value_first` is better or worse than `thought_leadership` (the latter has 1 historical send) because there is no apparatus for that question to be asked.

### 6.3 The auto-generation/auto-rejection cycle is the worst of both worlds
The platform generates drafts automatically (via prompt), then a human filters out half of them. The human time spent on rejection is not paid back in any learning. Either:
- Automate the rejection (codify the rules better in the prompt and integrity checks)
- Or human-write the templates and let Claude do per-prospect personalization only (a much narrower task)

The current middle ground is the most expensive option.

### 6.4 Brand and quality drift
Today's session surfaced em-dash defects in 35 drafts and dropped-subject defects in 6. These are mechanical rules the prompt explicitly states. **The model violates explicit rules even when they're in the system prompt.** This is not a tone problem — it is a fundamental signal that prompt-based rules without post-validation are unreliable for production output.

### 6.5 Sender pool and warmup discipline
The May 25 work consolidated 9 senders to 5. The remaining 5 senders have completed warmup. But there is no automated daily-cap enforcement at the *cohort* level (across all senders) — only at the per-sender level. A spike could oversend across the pool while staying under per-sender caps, increasing the perceived spam pressure on the cohort.

---

## 7. Prescriptive Initiatives

Numbered by priority. Each carries an estimated cost in engineering-days, an owner candidate, and a measurable success criterion.

### P1 — Stop sending until upstream is fixed (immediate)

**P1.1 — Pause all cold outreach for 14 days.**
Cost: 0 days. Owner: Avanish.
Success: zero new step-1 sends.
Rationale: continuing at 4.7%/0% open/reply is destroying domain reputation and consuming attention with no return.

**P1.2 — Resolve email_status null cohort.**
Cost: 1 day. Owner: ops.
Success: 0 contacts with `is_outreach_eligible=TRUE` and `email_status IS NULL`. Either fill via fresh ZeroBounce credits, or exclude.
Rationale: half the database is being treated as sendable without verification.

**P1.3 — Fix the bounce-rate governance breach.**
Cost: 0.5 day. Owner: engineering.
Success: bounce-rate assertion fires in `send_path` context (not `draft_gen`), tested against a synthetic 5% bounce dataset, and blocks sends as expected.

**P1.4 — Wire approval attribution and dual-review for Tier 1.**
Cost: 1 day. Owner: engineering.
Success: `approved_by` and `reviewed_at` migration deployed; dual-review gate on companies in Tier 1.

### P2 — Rebuild the upstream (week 2)

**P2.1 — Define a hard ICP for the next 90 days.**
Cost: 2 days. Owner: Avanish.
Success: one-page ICP doc covering: vertical (1–2 only), revenue band, employee band, equipment signature, regulatory trigger, and at least three "must have" data points. Apply retroactively to the existing list — drop anything outside.

**P2.2 — Cohort-based test campaign (≤100 contacts).**
Cost: 3 days. Owner: Avanish + engineering.
Success: 100 hand-curated contacts inside ICP receive a hand-written first email (not LLM-generated). Measure: open rate ≥ 15%, reply rate ≥ 1%. Treat this as the proof point that lets us scale, not the other way around.

**P2.3 — Build verifiable hook contract.**
Cost: 2 days. Owner: engineering.
Success: a Step-1 draft cannot pass integrity check unless it cites at least one company-specific fact with a source URL stored in `personalization_notes`. No source URL → auto-reject.

### P3 — Rebuild the message engine (week 3–4)

**P3.1 — Adopt sub-sector message libraries.**
Cost: 5 days. Owner: Avanish + content.
Success: separate Step-1 prompts and example libraries for at least 3 sub-sectors (e.g., aerospace forging, food thermal processing, custom fan manufacturing). Each library carries: 5 real industry pain points with sources, 3 regulatory triggers, and 5 verified equipment classes with typical model names.

**P3.2 — Replace four-step "different angle" sequence with a real arc.**
Cost: 3 days. Owner: Avanish + engineering.
Success: a defined narrative arc across 4 emails: hook → diagnostic question → framework leave-behind → closure. The closure email (drafted today for Step 4) is the prototype for the arc's final beat.

**P3.3 — Semantic integrity check (LLM-as-judge).**
Cost: 3 days. Owner: engineering.
Success: a second-pass evaluator (Sonnet) rates each draft on: (a) specificity (Level 1–3), (b) verifiable-claim density, (c) implied-engagement leakage. Drafts under threshold are auto-rejected and the rejection feeds back into a weekly prompt-tuning report.

**P3.4 — Remove the demo link from Step 1 signature.**
Cost: 0.1 day. Owner: engineering.
Success: Step-1 signature carries no links. Demo link returns in Step 3 only.

### P4 — Rebuild the technical core (sprint, 30 days)

**P4.1 — Event log as the source of truth.**
Cost: 8 days. Owner: engineering.
Success: an append-only `outreach_events` table records draft_generated, draft_approved, draft_sent, email_opened, email_clicked, email_bounced, reply_received. All status columns on `outreach_drafts` become read-only projections of this log. Funnel reports are rebuilt from the log.

**P4.2 — Adopt Temporal (or equivalent) for scheduled jobs.**
Cost: 5 days. Owner: engineering.
Success: `weekend_run.py`, `run_pipeline_loop.sh`, and the in-API scheduler are replaced by 5 Temporal workflows with retry, DLQ, and a UI for stuck jobs.

**P4.3 — Audit table as transactional.**
Cost: 1 day. Owner: engineering.
Success: `send_assertions` insert is wrapped in the same transaction as the `sent_at` claim. A failed insert blocks the send.

**P4.4 — Observability baseline.**
Cost: 3 days. Owner: engineering.
Success: a single Grafana (or equivalent) dashboard showing: queue depth, daily send rate, opens/clicks/bounces by step, reply rate, assertion failure rate, scheduler heartbeat. PagerDuty (or email) alert when reply rate drops to zero for 7 days.

### P5 — Channel decision (day 60)

**P5.1 — Go/No-Go on cold outreach as a channel.**
Cost: 0.5 day. Owner: Avanish.
Success: a written decision based on the P2.2 cohort result. If reply rate ≥ 1% from hand-curated cohort: scale with the rebuilt platform. If < 1%: shelf cold outreach until a customer signs (per the pre-customer deferral list in CLAUDE.md), and redirect platform attention to capabilities that compound when customers are present.

---

## 8. Structural Recommendations

Beyond the numbered initiatives, three structural questions deserve a separate decision:

### 8.1 Two-repo or one-repo?
ProspectIQ at `/Users/avanish/prospectIQ/` and Digitillis-platform at `/Users/avanish/digitillis-platform/` are diverging. Shared primitives (workspace context, pre-send assertions, audit logs, prompt templates) are being reinvented in each. **Either consolidate now, or commit to a published API contract between them.** Indecision is the most expensive option.

### 8.2 Human-in-the-loop, or human-out-of-the-loop?
The current model is the worst of both: LLM generates, human reviews, half the output is rejected. Choose one:
- **In the loop**: human writes templates, LLM personalizes within them. Drastically narrower LLM scope, higher floor on quality.
- **Out of the loop**: invest in prompt + integrity + judge to push rejection rate below 5%, then auto-approve at Tier 2+ with sampled review.

Both are coherent. The current middle is incoherent.

### 8.3 Customer-driven or platform-driven?
The pre-customer deferral list (CLAUDE.md) is explicit about what gets built before customer 1. The cold-outreach channel is consuming engineering attention that the deferral list reserves for capabilities triggered by customer events. **Either cold outreach earns its keep by producing a first customer in the next 30 days, or it goes on the deferral list itself**, with a re-activation trigger ("when sales bandwidth exists" or "when a first customer wants intro to peers").

---

## 9. What Good Looks Like in 90 Days

If P1–P4 execute, the platform in 90 days has:

- Email-verified, ICP-fitting contact base (no null `email_status`, no off-ICP companies)
- Hand-curated 100-contact pilot cohort with measured open ≥ 15%, reply ≥ 1%
- Sub-sector message libraries supporting at least 3 verticals
- Event-log-driven funnel analytics
- Temporal-orchestrated jobs with DLQ and retry
- A single dashboard showing reply rate trend, queue health, governance failures
- A clean signature in Step 1 (no demo link)
- Semantic integrity check in addition to regex
- A documented Go/No-Go decision at day 60 with data behind it

If the channel passes that test, the platform graduates from "supervised content factory" to "outbound system." If it fails, the platform earns its right to be shelved while engineering attention goes to capabilities that compound after a first customer signs.

---

## 10. Appendix — Source Material

- Live database snapshot (2026-05-25): 12,407 contacts, 2,091 drafts, 1,247 sends, 0 replies
- Prior baseline: `/Users/avanish/Documents/.../GTM_PERFORMANCE_ASSESSMENT_2026-05-08.docx`
- Operating doctrine: `/Users/avanish/digitillis-platform/CLAUDE.md` (Lean Operating Mode, pre-customer deferral list)
- Sending architecture: `/Users/avanish/prospectIQ/docs/SENDING_ARCHITECTURE.md`
- Outreach guidelines: `/Users/avanish/prospectIQ/config/outreach_guidelines.yaml`
- Generation prompt: `/Users/avanish/prospectIQ/backend/app/agents/outreach.py:198-498`
- Pre-send assertions: `/Users/avanish/prospectIQ/backend/app/core/pre_send_assertions.py`
- Approval UI: `/Users/avanish/prospectIQ/dashboard/app/approvals/page.tsx`

---

**Author: Avanish Mehrotra & Digitillis Technical Team**
**Copyright 2026 Digitillis. All rights reserved.**
