# ProspectIQ — Validated Continuation Cohort Strategy

**Date:** 2026-05-12
**Author:** Avanish Mehrotra & Digitillis Architecture Team
**Status:** Ideation document — not yet doctrine
**Scope:** Strategic continuation of Touches 2–5 for the 397 contacted accounts, under the 90-day copilot doctrine

---

## Opening framing (read this first)

Every account in ProspectIQ is cold by definition. If you already knew the person, you would email them directly — ProspectIQ would be irrelevant. ProspectIQ exists precisely for the case where all you have is a company name, a job title, public data, and a research agent. The system's job is to turn that cold starting point into a credible, specific, relevant first contact.

Cold outreach at a 2–4% reply rate is the expected baseline — that is not a failure state, it is industry math. To generate 5 qualified conversations per month you need roughly 150–250 sends per month. To generate 20, you need 500–1,000. Volume is not the problem. The problem that caused the original failures was quality failures at scale: bad filtering, hallucinated drafts, unverified emails causing bounces, and a broken research pipeline. Those failures have been fixed. The corrected approach is: fix the pipeline, enforce quality gates, maintain appropriate volume.

No artificial account caps. No warm-connection tier. The only limits on volume are: how many accounts pass the quality gates, subdomain warmup math, and the founder's batch-approval bandwidth.

---

## 1. Account Continuation Classification

All three tiers are cold outreach. The distinction is data quality and the level of draft review, not relationship warmth.

### Tier A — High-Signal Cold Accounts

**Definition.** Accounts where the research is specific enough that a highly personalized, evidence-grounded message can be constructed with high confidence. ProspectIQ drafts; the founder edits meaningfully and sends.

**Criteria (all must be true):**
- `pqs_total >= 55`
- Research contains at least one plant-specific, verifiable fact (FDA filing, capex announcement, job posting, named equipment type, public operational challenge) — derivable entirely from the DB, no prior relationship required
- At least one verified DM contact (`email_status = 'verified'`, `is_decision_maker = true`)
- Sub_sector in active ICP (fb*, mfg*, metals*)

**Contact strategy:** ProspectIQ generates the draft. Founder edits it — meaningfully, not cosmetically — and sends. The founder's edit is where domain expertise and judgment are applied, not where the research work happens. That research work is the system's job.

**Volume:** All accounts that pass the gate. No ceiling.

---

### Tier B — Standard Cold Accounts

**Definition.** Accounts with solid ICP fit, clean enrichment, and a sendable contact. The research is good enough for a credible, evidence-grounded message but may not have a single standout plant-specific fact. ProspectIQ drafts; founder batch-approves.

**Criteria (all must be true):**
- `pqs_total >= 40`
- `research_quality_score >= 0.6`
- At least one contact with `email_status` in (`verified`, `catch_all`)
- No bounce on any contact at this company
- Sub_sector in active ICP
- For continuation (Touch 2+): Touch 1 sent between 7 and 45 days ago

**Contact strategy:** ProspectIQ drafts. Founder reviews in batch — scans for factual errors, bad angles, or integrity violations — and approves. Batch approval should take under 2 minutes per draft on average.

**Volume:** All accounts that pass the gate. No ceiling.

**Realistic continuation count from existing 397:**
- Minus ~70 bounced: ~327
- Minus ~209 disqualified (re-evaluate any premature disqualifications): ~120 on the table
- Of those: PQS >= 40 catches ~90–110
- Of those: verified or catch_all contact: ~60–80
- Of those: Touch 1 within the 7–45 day window: depends on send dates

**Net Tier B continuation cohort: whatever passes the gates.** If that is 60, send to 60. If it is 90, send to 90.

---

### Tier C — Dormant / Disqualified

**Definition.** Everything else. This is the largest tier and that is correct.

**Criteria (any of):**
- Bounced
- Disqualified
- PQS < 40
- No verified contact AND no catch_all with strong signal
- Time since Touch 1 > 45 days with no engagement
- Sub_sector outside active ICP
- Research quality score below 0.6
- Manually marked as "not a fit" by founder

**Max count:** Unbounded. Today this is roughly 355–365 of the 397 contacted, plus everything not contacted.

**Contact strategy:** None. Not "slow drip." Not "quarterly check-in." None. Tier C exists in the DB as research material and as a feedback signal for PQS tuning. It does not receive email.

**Founder weekly interaction:** Zero by default. Quarterly review (every 90 days) to see if any Tier C deserves promotion based on new external signal (funding event, leadership change, trade show appearance).

**Tension:** It will feel wrong to leave 355 accounts in Tier C when the database "knows" about them. The 0.09% reply rate is the data telling you that the cohort, as currently scored and contacted, doesn't have signal. Re-touching them with the same logic produces the same result with worse domain reputation.

---

### Tier breakdown summary

| Tier | Count (realistic) | Send method | Founder time/week | Touches/account/week |
|------|-------------------|----|----|----|
| A | 8–12 | Manual, hand-crafted | 60 min | <= 1 |
| B | 25–30 | Drafted + founder-approved | 45 min | <= 1 |
| C | ~355+ | None | 0 (quarterly review) | 0 |

**Total weekly send volume across A+B at full capacity: ~40 emails/week.** If this feels small, re-read the doctrine.

---

## 2. Continuation Eligibility Gate

### Where it lives in the pipeline

The gate runs after draft generation, before pre_send_assertions.py. Pre-send assertions are about the email (verified address, no hallucination, no NULL fields). The continuation gate is about the account's eligibility to receive any further email at all. These are different concerns.

Logical pipeline:
```
Account selection → Draft generation → Continuation gate (NEW) → pre_send_assertions → Send
```

The gate is a runtime check that reads a DB-stored flag (`is_tier_b_eligible`) refreshed nightly. This gives the founder a stable cohort he can audit, while still enforcing at send time.

### Recommendation: hybrid (rule-based gate + scoring-based prioritization)

Rules decide eligibility (binary). Scoring decides order within eligible set. Pure scoring is dangerous because PQS is itself under refinement.

### Hard disqualifiers (automatic Tier C, no override)

| Field | Condition | Reason |
|-------|-----------|--------|
| `contacts.email_status` | any contact = `bounce` or `invalid` at company | reputation |
| `companies.status` | `bounced`, `disqualified` | already decided |
| `contacts.email_status` | no contact has `verified` or `catch_all` | nothing safe to send to |
| `pqs_total` | < 40 | doctrine gate |
| `research_quality_score` | < 0.6 | weak operational angle = hallucination risk |
| `sub_sector` | not in (fb*, mfg*, metals*) | outside ICP |
| Days since Touch 1 | > 45 | re-introduce, don't continue |
| Days since Touch 1 | < 5 | too soon |

### Soft concerns (require founder review checkbox before continuing)

| Field | Condition | Why |
|-------|-----------|-----|
| `contacts.email_status` | only `catch_all` available | risk of silent bounce or spam-trap |
| `pqs_total` | 40–49 | borderline ICP |
| `contacts.ccs_score` | < 50 | weak persona match |
| `contacts.is_decision_maker` | false on all available contacts | wrong altitude |
| `research_summary` | < 200 chars or "no data found" | thin angle, hallucination risk |
| Previous touch | `approval_status = 'rejected'` | something was wrong before |

Soft concerns surface in the weekly review queue. Founder explicitly checks "proceed anyway" or moves to Tier C. No auto-pass.

### catch_all policy

Allow catch_all in Tier B with three conditions:
1. Account must have `pqs_total >= 50` (higher bar than verified)
2. Only ONE catch_all contact per account ever
3. Send flagged in a `catch_all_sends` audit table
4. Two consecutive catch_all sends in a week that soft-bounce: auto-disable catch_all policy for 14 days

### Implementation footprint (deliberately small)

- 1 new column: `companies.is_tier_b_eligible` (boolean, nullable, updated nightly)
- 1 new column: `companies.tier_b_review_required` (boolean, soft concerns flag)
- 1 nightly job: `refresh_tier_b_eligibility.py`
- 1 new pre-send assertion: `assert_tier_b_eligible`
- 1 admin view: soft-concern accounts pending founder review

No new agent. No new service. No new ML model.

---

## 3. Sequence Philosophy: Touches 2–5

### Operating principle

Each touch is a different operational lens on the same buyer. Not a repetition with new urgency. If you can't articulate what the touch is *doing differently*, the touch shouldn't go out.

### The 4-touch role definition

| Touch | Role | Operational purpose | What changes vs prior touch |
|-------|------|---------------------|------------------------------|
| **Touch 2** | Specificity escalation | Narrow Touch 1's broad pain to one concrete, named operational scenario at their plant | Adds plant-specific evidence (line, asset class, public quote, recent capex) |
| **Touch 3** | Peer-anchored proof | Re-frame the pain through a near-peer's experience (verifiable, not vague) | Shifts from "you" to "a peer like you" — releases pressure |
| **Touch 4** | Inversion / cost of inaction | Reframe what not solving this costs operationally, with a number | Changes the verb: from "solve" to "stop bleeding" |
| **Touch 5** | Clean exit / opt-out | Acknowledge silence, offer a no-pressure asset, explicitly release them | Permission-giving close — preserves brand |

**No Touch 6.** If 5 didn't move it, the account moves to Tier C or back to Tier A for manual re-engagement in 90 days.

### Operational angle progression

| Touch | Angle | Buyer feels |
|-------|-------|-------------|
| 1 | Hypothesis-driven outreach | "He thinks he understands our space" |
| 2 | Plant-specific evidence | "He actually looked at our plant" |
| 3 | Peer credibility | "Other people in my world are doing this" |
| 4 | Cost of inaction | "What if I'm leaving money on the table" |
| 5 | Permission to disengage | "He's not desperate. Maybe later." |

### Touch 2 — Specificity escalation

**What it must do:** Take the broad pain from Touch 1 and show you've done work to find evidence of that pain specifically at their site. Cite something verifiable — press release, job posting, capex announcement, regulatory filing, trade publication mention.

**What it must NOT do:** Repeat Touch 1's pitch. Open with "circling back." Apologize for emailing.

**Food & Beverage (strong):**
- "Saw the FDA 483 you received in March mentioned cross-contact controls on Line 4. Most ops leaders treat this as a labor problem first. It's usually a sensor-coverage problem. Worth a quick look at what we found at a peer plant?"
- "Your job posting for a Sr. Quality Engineer specifically called out PCQI experience and Listeria environmental program scaling. The scaling part is where we've seen the most stuck attempts in dairy. Two questions if you have a minute."

**Food & Beverage (weak — do not send):**
- "Following up on my note last week — wanted to see if food safety is still a priority for you."

**Discrete manufacturing (strong):**
- "The capex disclosure in your Q1 8-K mentioned $14M for the Findlay stamping line. We've seen two ways teams approach press-monitoring on a retrofit like that: instrument the dies or instrument the press itself. They give you very different data. Curious which way you're leaning."
- "Noticed Sandvik just opened a service hub 40 minutes from your Marion plant. That usually means tooling spend goes up 12–18% in the first year. We help shops on machining-heavy lines benchmark that quickly. 15 minutes?"

**Discrete manufacturing (weak):**
- "Just wanted to circle back on predictive maintenance — is this on your roadmap?"

### Touch 3 — Peer-anchored proof

Cite a verifiable peer (named company, public quote, conference talk, published case study). Frame the buyer's pain through the peer's experience. The peer must be at the same altitude or one rung above, never below.

**Food & Beverage (strong):**
- "Westrock Coffee's VP Quality gave a talk at IFT last fall about why their Listeria swab program kept showing the same hits even after cleaning protocol changes. The fix wasn't the cleaning — it was the swab cadence. We've replicated their approach at two co-packers. Worth a 15-minute walk-through?"

**Discrete manufacturing (strong):**
- "Friedman Industries' team has been public about how they reduced unplanned downtime on their hot-rolled coil lines by 31% without adding sensors. The trick was reusing existing PLC data they already had. Same principle applies to your Decatur facility. Quick look?"
- "Waupaca's foundry team published a case on what they call the 'shift-change drift' problem — quality variance in the first 90 minutes of every shift. Same pattern shows up in most die casting operations we audit. Curious if you see it at your plant."

### Touch 4 — Inversion / cost of inaction

Change the framing from "here's what we can do" to "here's what continuing without a change is costing you." Use a defensible number anchored to their plant size or output. Manufacturing leaders don't say ROI — they say "cost per hour of downtime," "scrap rate," "yield loss."

**Food & Beverage (strong):**
- "Quick math on your Akron facility: at ~280 packaging hours/week and a conservative 6% unplanned downtime rate, you're losing roughly 17 hours/week. At your line throughput that's ~$84K/month of foregone output. Not pitching anything — just wanted to put a number on the silence."

**Discrete manufacturing (strong):**
- "Stamping operations your size typically run 4–7% scrap on press-to-press variance. At your reported tonnage that's ~$1.1M/year. Even cutting that by a third is real money. Worth showing you what that diagnostic looks like? 20 minutes."
- "If your CNC cells are still on time-based PM cycles, the typical waste is ~22% of maintenance hours spent on machines that didn't need attention yet. For your shop size that's roughly two FTE-weeks/month. Happy to send you the assessment template — no call needed."

### Touch 5 — Clean exit / opt-out

Acknowledge silence directly. Offer something of value with no ask. Explicitly tell them you'll stop.

**Universal (strong):**
- "Won't keep emailing. Two things before I step back: (1) here's the operational diagnostic we'd run for a plant like yours [link] — yours to use whether we talk or not; (2) if the timing changes in Q3, just reply 'reach out' and I'll pick this up then. Otherwise good luck on the [specific thing from Touch 2 evidence]."

### Anti-patterns — hard prohibited (add as rejection_reasons)

1. **`anti_pattern_followup_filler`** — Contains "following up," "circling back," "just wanted to check in," "wanted to see if," "any thoughts on my last," "did you get a chance to"
2. **`anti_pattern_repeated_pitch`** — Touch N body has >40% token overlap with Touch N-1 body
3. **`anti_pattern_invented_peer`** — Touch 3 references a peer company without a verifiable source URL in draft metadata
4. **`anti_pattern_unsupported_number`** — Touch 4 contains a $ or % figure without anchor field (asset_count, line_count, reported_revenue, or research_summary citation)
5. **`anti_pattern_guilt_close`** — Touch 5 contains "I guess," "haven't heard back," "must not be a fit," "should I take this as a no"
6. **`anti_pattern_altitude_mismatch`** — Body addresses tactical specifics that don't match the recipient's persona (COO receiving PLC tag questions)
7. **`anti_pattern_count_disclosure`** — Body references which touch number this is ("This is my fourth email...")

These are not soft warnings. They block send.

---

## 4. Message Angle Taxonomy

### Purpose

Build a learning loop. After 12 weeks, the founder should be able to answer: "What operational angles produce manufacturing replies, and what produces silence?" At the level of operational angle, not good email vs bad email.

### Recommended taxonomy (6 dimensions)

| Dimension | Values (controlled vocabulary) |
|-----------|-------------------------------|
| **operational_angle** | quality_compliance, unplanned_downtime, scrap_yield, energy_efficiency, labor_productivity, shift_variance, capex_optimization, regulatory_pressure, supply_chain, ehs_safety |
| **trigger_type** | fda_483, capex_disclosure, job_posting, leadership_change, earnings_callout, trade_press, conference_talk, peer_referral, none |
| **asset_class** | cnc_machining, stamping_fabrication, die_casting, heat_treatment, food_processing_line, packaging_line, batch_process_reactor, coil_line, none |
| **archetype** | high_mix_low_volume, low_mix_high_volume, continuous_process, batch_process, hybrid |
| **transformation_stage** | greenfield, modernization, expansion, consolidation, stabilization, unknown |
| **outcome** | replied_positive, replied_neutral, replied_negative, opened_no_reply, no_engagement, bounced, unsubscribed |

### Where it lives

**In the DB, on `outreach_drafts`, populated manually.**

- 6 nullable columns on `outreach_drafts`, controlled vocabulary enforced at app layer
- Founder tags during weekly review (~30 seconds per draft)
- `outcome` auto-populates from reply detection and bounce detection
- No tagging UI needed in v1 — Supabase admin view is enough

Putting it in the DB (not a spreadsheet) matters because eventually this trains PQS refinement.

### Why not auto-tag with LLM?

The whole point of this phase is the founder developing tacit pattern recognition. If an LLM tags it for him, he never builds the intuition that should eventually flow back into PQS feature engineering. Auto-tagging is Phase 2, post-90-days.

### 12-week math

- 30 accounts x ~1 send/week x 12 weeks = ~360 tagged sends
- ~5 Tier A sends/week x 12 = ~60 tagged sends
- Total: ~420 tagged messages across 6 dimensions

That is enough to see directional patterns like "trigger_type=capex_disclosure + asset_class=stamping_fabrication" producing 4x the reply rate of "trigger_type=none + operational_angle=quality_compliance." It is not enough for statistical confidence — that is fine; this is pattern hunting, not science.

### Weekly review: 15 minutes Friday

Pivot: operational_angle x outcome. Look for:
1. Angles that produce any reply (positive or negative — both are signal)
2. Angles that consistently produce silence across diverse accounts (kill these next week)

---

## 5. Sequence Governance

### Founder review requirements

| Event | Founder review required? | How |
|-------|-------------------------|-----|
| Tier A any send | Yes, every send | Manual draft |
| Tier B any touch | Yes, every send | Batch approval Tuesday |
| Move account A to B | Yes | Weekly review |
| Move account B to C | No (system demotes) | Logged, founder reviews log Friday |
| Move account C to B | Yes | Requires explicit promotion |
| Catch_all send | Yes, with extra confirmation | Highlighted in batch |
| Re-send after rejection | Yes | Re-enters approval queue |

### Hard stop rules (system enforces, no override)

1. Rolling 7-day bounce rate on outreach.digitillis.com > 1.5% — pause all sends
2. Any spam complaint — pause domain, alert founder
3. Rolling 14-day reply rate < 0.3% AND >= 40 sends in window — pause cohort, mandatory review
4. Any draft failing two or more anti-pattern checks in a week — pause draft generation 24h
5. Verified-pool eligible Tier B accounts drops below 15 — pause new sequence starts

### Max send rates

| Scope | Limit | Rationale |
|-------|-------|-----------|
| Per day, total | 12 emails | Subdomain warmup |
| Per week, total | 50 emails | Founder approval bandwidth |
| Per account, per week | 1 email | Anti-fatigue |
| Per account, per sequence | 5 touches | Doctrine |
| Per sub_sector, per week | 20 emails | Diversification of learning |
| Catch_all sends, per week | 5 emails | Reputation guard |

### Engagement escalation (reply handling)

| Reply signal | Action | Timing |
|--------------|--------|--------|
| Positive reply | Auto-pause sequence, notify founder, promote to Tier A | Within 15 min |
| Neutral reply | Auto-pause sequence, notify founder, founder decides | Within 15 min |
| Negative reply | Auto-pause sequence, mark `disengaged`, move to Tier C, suppress | Within 15 min |
| Out-of-office | Pause sequence 14 days, resume automatically | Auto |
| Unsubscribe | Suppress at contact AND domain level, irrevocable | Immediate |
| Forward indicator | Pause original sequence, founder reviews for cross-contact strategy | Within 1h |

### Dormancy logic (B to C demotion mid-sequence)

Account demotes B to C automatically when any of:
- Touch 4 sent with no engagement on any touch
- 45 days elapsed since last touch with no engagement
- Bounce on any contact at the company
- Founder manually demotes during weekly review

Demotion is logged, not silent. Friday review includes the week's demotion list.

### Reputation kill switch

| Signal | Action |
|--------|--------|
| Domain bounce rate > 2% rolling 7-day | Auto-pause all sends, alert founder |
| Domain spam rate > 0.1% | Auto-pause all sends, alert founder |
| Postmaster Tools complaint | Auto-pause, manual investigation |
| Any send to known suppression email | Block at pre_send, alert |

---

## 6. Salvageability Assessment

### How many of 397 are salvageable?

**Honest estimate: 25–40 accounts (6–10%).**

Funnel:
- 70 bounced: unsalvageable
- ~209 disqualified: mostly unsalvageable, maybe 5–10 prematurely killed
- Remaining ~120: PQS >= 40 catches ~50–70%, verified contact cuts another ~50%: 30–45 candidates
- Distinct Touch 2 angle available: 25–40

### Strategic value: continue vs abandon

**Cost of abandoning all 397:**
- Loss of Touch 1's research investment
- Loss of the pattern data in their non-responses
- Loss of accounts where timing was wrong, not fit

**Cost of continuing carelessly:**
- Domain reputation damage at the moment of subdomain migration
- Bounce rate stays >2% on the new subdomain, kills the recovery
- Founder spends weeks on a cohort that has self-selected as low-signal

**Verdict:** Salvage the 25–40, abandon the rest. Treating the cohort as small-and-deliberate is the doctrine working correctly.

### Does the contacted list have real ICP signal?

Mixed, leaning weak. Average PQS of 31.5 vs a 40-gate means the bottom 40% of the database was contacted before the gate existed. The 80 qualified accounts and 7 engaged accounts are real signal. The other ~310 are weakly-scored noise.

The corrective is not to re-touch the noise. It is to use the noise to refine PQS so the next inflow is better scored.

### Should Touch 2 reference Touch 1?

| Days since Touch 1 | Touch 2 approach |
|--------------------|------------------|
| 5–14 days | Light reference ("when I wrote last week about..."), pivot fast to new angle |
| 15–30 days | No reference, fresh angle |
| 31–45 days | No reference, fresh angle, fresh subject line |
| > 45 days | Not Touch 2 — re-introduction, treat as new sequence |

At 15+ days, the prospect doesn't remember Touch 1. Referencing it makes the founder feel continuity the buyer doesn't share.

---

## 7. What NOT to Build

| Do NOT build | Why not (now) | Revisit when |
|--------------|---------------|--------------|
| Auto-generated Touch 2-5 content from templates | Templates produced the 0.09% reply rate | After 90 days, evidence-grounded generation with founder-tuned prompts — never as templates |
| New engagement scoring agent | PQS already unreliable; stacking scores makes it worse | After 12-week tagging data stabilizes PQS |
| Automated tier promotion (C to B to A) | Auto-promotion removes the learning | After 90-day learning phase ends |
| Re-engagement of bounced domains | Reputation poison | Never at the company level |
| Frontend dashboard for cohort management | Supabase admin view is enough | When >2 humans need read-access |
| Multi-domain sending (rotating sender domains) | Reputation diversification is a volume play | If volume legitimately scales to >500/week |
| LinkedIn outreach automation | Mixing channels mixes learning signal | After email cohort produces 5+ Tier A wins |
| A/B testing framework for subject lines | Statistical power requires volume we don't have | At >= 400 sends/week sustained |
| CRM bidirectional sync | Premature for a 30-account cohort | At >= 100 active accounts, or when non-founder operates ProspectIQ |
| Automated peer-citation generation (Touch 3) | High hallucination risk; peer claims must be human-verified | After integrity rules stabilize and curated peer-evidence DB exists |
| Reply intent classification ML model | At ~50 replies/quarter, a binary classifier is overkill | At >= 200 replies/month |
| Bulk re-enrichment of 9,945 contacts | Most won't be contacted in this phase; wasted Apollo credits | Quarterly refresh of Tier A/B contacts only |

---

## 8. Immediate Next Actions

### The 5 highest-leverage actions, in priority order

1. **Build the Tier B eligibility flag and nightly refresh job.** (~1 day.) This operationalizes the entire doctrine. Without it, the 30-account cap is aspirational. With it, it is mechanical.

2. **Stand up the message angle taxonomy on `outreach_drafts`.** (~half day.) 6 columns + an admin view. Tagging must start the same week sends resume — it cannot be retroactive.

3. **Author the 7 anti-pattern checks as new pre_send_assertions.** (~1 day.) The anti-patterns in §3 become rejection_reasons. This is where the integrity work from this session pays off.

4. **Complete subdomain authentication (SPF/DKIM/DMARC on outreach.digitillis.com) and run the 30-contact diagnostic.** Nothing else matters until this is green. Diagnostic: 30 verified contacts from current Tier B candidates, sent at Touch-1 quality, monitored for 5 days.

5. **Founder manually classifies the current 397 into A/B/C in a Supabase view, by hand, in one sitting.** (~2 hours.) Do not automate this. The founder doing it manually is how he builds the pattern recognition the rest of the system depends on.

### During the subdomain setup window (before sends resume)

- Tag all 7 engaged accounts with operational_angle and trigger_type retroactively — this is the seed dataset
- Write the first round of Touch 2 drafts for 8–12 Tier A accounts manually — have them ready to send day-of
- Run a query: of the 209 disqualified, are any disqualified for a reason that has since changed? Cap the rescue at 5 accounts
- Document the operational angle for each of the ~30 Tier B candidates in their research_summary — if it can't be written in two sentences, the account doesn't belong in B
- Compose the Touch 5 "clean exit" template as a single canonical version with two variables — this is the only touch where templating is acceptable

### First 30 days of the continuation cohort

| Week | Activity | Total sends |
|------|----------|-------------|
| 1 | Touch 2 to Tier A (hand-drafted) + Touch 2 to Tier B (founder-approved) | ~35–40 |
| 2 | Tier A advances from replies + Touch 3 for Week 1 Tier B (min 7 days gap) | ~35–40 |
| 3 | Mix of Touch 2 (new starts) and Touch 3 (continuations) + first demotion review | ~35–40 |
| 4 | T2/T3/T4 in flight + first Touch 5 candidates + founder retrospective | ~35–40 |

### Founder weekly cadence

| Day | Activity | Time |
|-----|----------|------|
| Monday | Tier A review + manual drafts | 60 min |
| Tuesday | Tier B draft approval + tagging | 45 min |
| Wednesday | Reply triage + Tier A advancement | 20 min |
| Thursday | Reply triage + light send | 20 min |
| Friday | Cohort review + taxonomy pivot + demotion log | 30 min |

**Total founder time/week: ~3 hours.** If less than 2.5 hours, the founder is under-engaging. If more than 4, the cohort is too large.

### One-paragraph internal framing

> ProspectIQ is no longer a pipeline tool. It is a structured way for the founder to run 30 high-quality manufacturing conversations a quarter, learn what operational angles actually move VP Ops and Plant Managers, and feed that learning back into how Digitillis scores and approaches every future account. The system handles the safety rails — eligibility, anti-patterns, reputation guards, sequence governance. The founder handles the angle, the evidence, and the read of every reply. Volume is intentionally low, learning velocity is intentionally high, and every email that goes out has to defend its existence on operational specificity, not template fluency.

---

## Closing tensions

| Tension | Resolution |
|---------|------------|
| 30-account cap feels small vs 9,945 contacts | The 9,945 are research material, not inventory. Cap stays. |
| Manual approval slows velocity | Velocity is not the goal; learning is. Slowness is intentional. |
| Tier C feels wasteful | Tier C is feedback to PQS, not abandonment. |
| Specificity is hard to write at any scale | That is exactly why the cap is 30. |
| Touch 5 looks like giving up | It is brand preservation. Touch 6+ is what broke ProspectIQ. |
| catch_all exclusion narrows ICP | Allowed with limits — see §2. |

---

## Open questions for founder decision

1. Does the Tier A ceiling of 8–12 accounts feel right, given 7 engaged accounts already?
2. Should catch_all be hard-excluded for the first 30 days until subdomain reputation is established, rather than allowed with conditions?
3. Should Touch 2 be fully founder-drafted for the entire first cohort, or is draft-then-approve acceptable for Tier B?

---

*Save updates and retrospective notes directly to this file after each weekly review.*
*Next update: end of Week 4 (approximately 2026-06-09).*
