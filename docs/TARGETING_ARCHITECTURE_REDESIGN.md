# ProspectIQ — Targeting & Screening Architecture Redesign

**Version:** 1.0  
**Date:** 2026-04-30  
**Status:** Approved for implementation  
**Author:** Avanish Mehrotra

---

## Background and Motivation

An audit of 249 emails (192 sent, 57 pending approvals) conducted on 2026-04-30 revealed:

- **341 contacts** (of 8,077) were wrong job function: Sales, HR, Marketing, Legal, Customer Service
- **33 emails already sent** to wrong-function contacts
- **3 emails sent to the wrong person entirely** — greeting named a different person than the email inbox owner (Fike Corporation / Kade Belcher → Michael Belcher's inbox; Waupaca Foundry / Cody Axton → Cody Rhodes-Dawson's inbox; Lucas Milhaupt / Javier Barbachano → J. Perez's inbox)
- **28 pending drafts** queued for wrong-function recipients (cancelled as part of this remediation)

**Root cause 1:** Function filtering only ran in the outreach agent — the last step in the pipeline — with a dangerous fallback that promoted wrong-persona contacts when no right-persona contacts were found.

**Root cause 2:** No email-name consistency check. Apollo sometimes assigns a contact's email to the wrong person record.

**Root cause 3 (structural):** The system was architecturally inverted. Outbound treated contact selection as a runtime concern (filter at send time) instead of a data-layer concern (only eligible records enter the pipeline at all). Every fallback clause was a load-bearing apology for upstream data that was never trusted.

### Immediate Remediation (2026-04-30)

These were applied before this redesign:

- Hardened outreach agent persona filter — removed dangerous fallbacks, added VP/C-level override, added Apollo artifact pattern detection
- Cleaned 341 wrong-function contacts in DB (status=`excluded`)
- Rejected 28 pending wrong-function drafts from approval queue
- Fixed Kade Belcher / Fike Corporation email record (email cleared, flagged for re-enrichment)
- Built `contact_filter.py` — single source of truth for all eligibility decisions, wired into discovery and enrichment agents at import time
- Built `post_send_audit.py` — weekly adversarial sweep of all sends (Sunday 7am)
- Added integrity constraint to every Claude outreach prompt: no fabricated case studies, client names, or unverifiable ROI numbers

---

## The Target Architecture

The redesign separates the **system of record** (everything Apollo returns) from the **system of action** (only verified, eligible, ranked contacts). Outreach reads only from the latter. No filters at send time. No fallbacks. Ever.

```
Apollo Search ─┐
ZoomInfo      ─┼─► raw_contacts (immutable, multi-source, append-only)
LinkedIn      ─┤        │
Clay          ─┘        ▼
                   normalize + dedupe (identity resolution)
                        │
                        ▼
                   contact_profiles (golden record, 1 per real person)
                        │
                        ▼
                   verification gates:
                   ├── email deliverability (Apollo email_status, free at enrichment time)
                   ├── email-name consistency (heuristic + nickname mapping)
                   ├── role classification (3-tier: target / borderline / excluded)
                   ├── employment recency (LinkedIn last-seen < 90 days)
                   └── Contact Confidence Score (CCS, 0–100 weighted)
                        │
                        ▼
                   outbound_eligible_contacts (separate table, not a flag)
                        │
                        ▼
                   contact_ranker (per-vertical conversion model)
                        │
                        ▼
                   sequence_orchestrator (adaptive, signal-driven)
                        │
                        ▼
                   send → track → feedback_loop → re-score ICP
```

---

## Priority 0 — Stop the Bleeding (Done + 2 additions)

### Done (2026-04-30)

- `contact_filter.py`: three-tier classifier, VP override, artifact stripping, email-name check with nickname mapping
- Import-time screening in discovery and enrichment agents
- DB-column hard gate (`is_outreach_eligible`, `email_name_verified`, `email_status`) in outreach agent
- Apollo `email_status` captured at enrichment time; `invalid` / `bounce` contacts blocked immediately
- Email-name consistency check now also runs at enrichment time (when Apollo returns a confirmed name+email pair)
- Weekly post-send audit job (Sunday 7am Chicago)
- Weekly contact profile backup to NAS (Saturday 5am Chicago, 12-week retention)
- Migration 031: `is_outreach_eligible`, `contact_tier`, `email_name_verified` columns on contacts
- Migration 032: `email_status` column + deliverability index

### P0.1 — `outbound_eligible_contacts` as a Hard SQL Gate

A boolean column on contacts is a foot-gun. Someone writes a query that forgets to filter it, and the pipeline opens back up. The permanent fix:

- Create a separate `outbound_eligible_contacts` table, populated only by a stored procedure that runs all verification gates
- The outreach agent is granted read access only to this table — it physically cannot select an ineligible contact
- The `contacts` table remains the system of record (everything Apollo returns, raw)
- Add a `gate_status JSONB` column on `outbound_eligible_contacts` showing which gates passed/failed and when — this is the audit trail

**Implementation:** One schema migration, one stored procedure, one agent refactor. ~2 days. Deploy behind a dual-read feature flag for one week before cutting over.

### P0.2 — Email Deliverability Gate (Apollo `email_status`, implemented)

Apollo's people/match enrichment endpoint returns an `email_status` field at no extra cost on every API call. This makes a paid third-party verifier (NeverBounce, ZeroBounce) unnecessary at current scale.

**Apollo `email_status` values and gate behavior:**

| Status | Action |
|---|---|
| `verified` | Allow — email confirmed deliverable |
| `catch_all` | Allow — server accepts all addresses, cannot verify individual |
| `accept_all` | Allow — same as catch_all |
| `unverified` | Allow — insufficient data but not known-bad |
| `unknown` | Allow — cannot check |
| `invalid` | **Block** — confirmed undeliverable; set `is_outreach_eligible=False` |
| `bounce` | **Block** — confirmed hard bounce; set `is_outreach_eligible=False` |

**Implemented (2026-04-30):**
- `enrichment.py`: captures `email_status` from Apollo person payload, stores to DB, sets `is_outreach_eligible=False` for `invalid` / `bounce`
- `contact_filter.py` `screen_contact_at_import()`: applies the same gate if `email_status` is present at import time (e.g., bulk uploads with prior enrichment data)
- Migration 032: `email_status` column + partial index on `('invalid', 'bounce')` for fast outreach gate queries

**When to revisit NeverBounce:** If rolling 7-day hard bounce rate exceeds 2%, engage ZeroBounce for a one-time batch scrub (~$65 for current contact list at $0.008/check). Until then, Apollo `email_status` + existing domain MX check in `domain_verify.py` provides sufficient protection.

### P0.3 — Weekly Local Contact Profile Backup (implemented)

All contact records (with linked company data) are exported to JSON every Saturday at 5am Chicago time.

- **Path:** `/Volumes/Digitillis/Data/prospectiq_backups/contacts/`
- **Format:** `YYYY-MM-DD_<workspace_id>.json` — complete JSON with all DB fields and inline company record
- **Retention:** 12 weeks (older files auto-pruned by the agent)
- **Implementation:** `ContactBackupAgent` in `backend/app/agents/contact_backup.py`, scheduled via APScheduler

This provides an offline, human-readable audit trail independent of Supabase availability — useful for incident investigation and historical targeting analysis.

---

## Priority 1 — Multi-Source Identity Resolution (3–4 weeks)

Apollo is good at discovery (finding companies) and unreliable for contact verification. Use it for the first job only.

### P1.1 — Multi-Source Contact Architecture

Build a `raw_contacts` table that is append-only and source-tagged:

```sql
raw_contacts (
  id, 
  source ENUM('apollo','linkedin','zoominfo','clay','clearbit','manual'),
  source_record_id, 
  payload JSONB, 
  fetched_at,
  ...
)
```

A resolver service produces `contact_profiles` (one row per real human) by deduping on `(normalized_full_name, normalized_company_domain)` with email and LinkedIn URL as tiebreakers. Use `rapidfuzz` for name normalization, `tldextract` for domain normalization. This is deterministic rules, not ML — 200 lines of Python.

### P1.2 — Source Strategy by Job-to-be-Done

Do not subscribe to everything. Pick by function:

| Need | Primary | Verification | Est. Cost |
|---|---|---|---|
| Company discovery (ICP search) | Apollo | — | Already have |
| Decision-maker existence | LinkedIn via PhantomBuster | Apollo | ~$69/mo |
| Email accuracy | Apollo `email_status` (free) | Domain MX check | Already included |
| Title / role accuracy | LinkedIn current title | Apollo title | Included in Phantom |
| Employment recency | LinkedIn last-active | — | Included |
| Direct dial (later) | ZoomInfo or Clay | — | Defer |

**Recommended path: buy Clay ($349/mo).** Clay orchestrates Apollo + LinkedIn + NeverBounce in one waterfall with no custom integration code. The 3 weeks saved building source orchestration pays for 2+ years of Clay. Differentiation is in the manufacturing-domain ICP and the agentic intelligence layer, not in building an enrichment pipeline that already exists off-the-shelf.

### P1.3 — Contact Confidence Score (CCS), 0–100

Replace the binary `is_outreach_eligible` flag with a numeric score. Weights:

| Gate | Points | Notes |
|---|---|---|
| Email deliverability (Apollo `email_status=verified`) | 30 | Most important: email reaches a human |
| Email-name consistency | 20 | Now implemented in `contact_filter.py` |
| LinkedIn current title matches Apollo title | 15 | Requires LinkedIn enrichment (P1.2) |
| LinkedIn last-active < 90 days | 15 | Person still works there |
| Persona tier = `target` | 10 | 3-tier classifier |
| Multi-source agreement (≥2 sources confirm) | 10 | Apollo + one other source agree |

**Thresholds:**
- CCS ≥ 70: enters `outbound_eligible_contacts`
- CCS ≥ 85: preferred for VP/C-level outreach where mis-targeting is costlier
- CCS < 70: contacts are identified but blocked from outreach until re-verified

The score is fully explainable — every send logs the CCS and which gates contributed. When something goes wrong, you can answer "which gate failed?"

---

## Priority 2 — ICP as a Living System

The YAML ICP file is a hypothesis. Treat it like one.

### P2.1 — ICP Versioning

Move ICP from `config/icp.yaml` to an `icp_definitions` table with version history. Every send records `icp_version_id`. This enables comparing reply rates across ICP versions — without it, you cannot know whether tightening or loosening targeting worked.

### P2.2 — ICP Refinement Signals

Learn weights on existing ICP dimensions from outcomes. Signals to feed back, weighted by reliability:

| Signal | Weight | Notes |
|---|---|---|
| Booked meeting | +5.0 | Highest trust, low volume |
| Positive reply (sentiment-classified) | +2.0 | Clear intent signal |
| Any reply (even negative) | +0.5 | Confirms targeting reached a human |
| Email opened ≥ 3× in 7 days | +0.2 | Weak — Apple MPP degrades open tracking |
| Hard bounce or "wrong person" reply | −3.0 | Data quality signal |
| Unsubscribe | −1.0 | Targeting miss |
| No engagement after 3 sequence steps | −0.1 | Weak negative |

Aggregate to **company-tier × industry × employee-band** cells. Below 500 sends per cell, use static weights. Above 500, compute a multiplier on the base PQS from the empirical reply rate. Implementation: regularized logistic regression per cell using scikit-learn, daily batch job. Not a neural network — the data volume does not justify it and overfitting risk is high.

### P2.3 — Negative ICP Table

The most underused tool. An `icp_exclusions` table capturing companies that: hard-bounced, replied "wrong person," replied "we don't buy that," or were flagged as competitors. Cross-referenced at discovery time. High ROI, trivially implemented.

---

## Priority 3 — Contact Selection Intelligence

### P3.1 — Persona-Conversion Model, Per-Vertical

Once 1,000+ sends with reply outcomes exist, fit a model: `P(reply | persona, industry, company_size, geography, sequence)`. This reveals, for example: "VP Operations converts 4× better than Director Operations in food & beverage but they are tied in automotive."

Implementation: daily batch job fits regularized logistic regression, writes per-segment persona priorities to `persona_rankings` table. Outreach agent reads this table at selection time. The ranker itself is ~50 lines of scikit-learn. The data infrastructure is the work.

Until data volume is sufficient, hand-code priors per industry from domain knowledge.

### P3.2 — Multi-Objective Contact Scoring

The right contact at a company maximizes:

```
expected_reply_value = P(reply) × P(meeting | reply) × deal_size_proxy × (1 − over_targeting_penalty)
```

The `over_targeting_penalty` is the critical addition: if 3 contacts at a company were emailed in 60 days with no reply, the next email's probability craters and sender reputation is damaged. Track per-company outreach density and decay it into the contact score.

### P3.3 — Tiered Title Classification

The current 3-tier classifier uses keyword matching. This is correct for the 80% obvious cases. For ambiguous titles, build a classifier hierarchy:

- **Tier 1 (deterministic):** whitelist/blacklist for obvious cases. CEO, COO, VP Ops → target. HR, Marketing, Sales → excluded. Already implemented.
- **Tier 2 (LLM, cached):** For ambiguous titles ("Director of Continuous Improvement," "Plant Operations Lead"), call Claude Haiku with the title, company industry, and ICP context. Cache by (title, industry) pair. Cost: ~$0.001/classification, runs once per unique title.
- **Tier 3 (human review queue):** Unknown or low-confidence titles flow to a review queue. After human disposition, result writes to a `title_dispositions` table. Tier 1 reads this first on future occurrences.

This is a classifier hierarchy that gets cheaper as it learns.

---

## Priority 4 — Multi-Contact Threading Strategy

### Threading Rules (Hard Limits)

- Never thread more than 2 contacts at companies under 500 employees. At that size, you will be perceived as a spray-and-pray operation.
- Stagger by at least 5 business days between first and second contact at the same company.
- Different angles, not rewrites. Contact 1: strategic angle (VP Ops on throughput). Contact 2: tactical angle (Plant Manager on a specific bottleneck from research). If two genuinely different emails cannot be written, do not send the second.
- If Contact 1 replies (positive or negative), pause Contact 2 immediately. This must be a hard system rule, not an agent heuristic.
- Threading only for accounts above PQS ≥ 65. Do not use two-shot threading on B-tier accounts.

### Threading State Machine

Add a `company_outreach_state` table that explicitly models threading state per company:

```
not_started → contact_1_queued → contact_1_sent → contact_1_engaged → paused
                                                 → contact_2_queued → contact_2_sent
```

The orchestrator reads and writes this table. Current implicit threading state (inferred from queries) is what makes threading bugs invisible until they cause a multi-contact collision.

---

## Priority 5 — Adaptive Sequences

### P5.1 — Block-Based Email Composition

Decompose email templates from monolithic strings into graphs of content blocks: opener, signal hook, value prop, proof point, CTA. Each block has variants tagged by industry, persona, signal type. Reply rate is attributed back to the block combination. Run Thompson sampling per block slot, segmented by industry × persona. After ~50 sends per arm, the bandit converges on the best combination per segment.

Do not build adaptive sequences until `outreach_outcomes` (Priority 7) is live and generating training data. Building adaptive sequences without outcome measurement is optimizing noise.

### P5.2 — Engagement-Driven Branching

After Step 1:
- Opened 0×: Step 2 uses a different subject line (opener problem, not content)
- Opened ≥ 1×, no reply: Step 2 leads with a sharper hook from a fresh signal
- Clicked link: Step 2 references the resource and offers a direct meeting
- Replied negative: Exit sequence, write to negative ICP

**Note on open tracking:** Apple Mail Privacy Protection has substantially degraded open signal reliability. Do not make critical branching decisions on opens alone. Click and reply are the only trustworthy positive signals.

---

## Priority 6 — Signal Triangulation

### P6.1 — Signal Store

A normalized `company_signals` table:

```sql
company_signals (
  company_id, signal_type, source, value, observed_at, 
  decay_half_life_days, signal_freshness_weight
)
```

Signals have a half-life. A job posting from 90 days ago is dead intelligence. Compute `freshness_weight = 0.5 ^ (days_since / half_life)` at query time. Composite signal score: `Σ (signal_weight × freshness_weight × source_trust)`. This replaces boolean trigger evaluation with a continuous signal strength measure.

### Recommended Signal Half-Lives

| Signal | Half-life | Source |
|---|---|---|
| Funding announcement | 180 days | Apollo, Crunchbase |
| Job posting (target role) | 30 days | Apollo, LinkedIn |
| New tech adoption | 90 days | BuiltWith, Apollo |
| Leadership change (target persona) | 60 days | LinkedIn, news |
| Plant expansion / capacity news | 365 days | Trade press, news |
| Compliance / quality incident | 180 days | FDA recalls, OSHA |
| Earnings call mention of operations | 90 days | (future) |

### P6.2 — Manufacturing-Specific Signal Scrapers (Durable Moat)

These signals are not in Apollo. They are highly correlated with "this company has an operational problem right now." Competitors using Apollo alone cannot match this targeting precision.

Priority scrapers:
- **FDA recalls and enforcement actions** — FSIS, FDA Food Safety for food/bev
- **OSHA citations** — manufacturing safety incidents signal maintenance/reliability gaps
- **EPA enforcement actions** — often co-occur with process control failures
- **MEP grant announcements** — Manufacturing Extension Partnership grants signal active investment in modernization
- **Manufacturing trade press** — IndustryWeek, Modern Materials Handling, Plant Engineering for expansion/consolidation news

---

## Priority 7 — Closed-Loop Feedback (Foundational)

### P7.1 — `outreach_outcomes` Table

Single source of truth for all send outcomes. Build this now, even if most columns are null. Retroactive construction of send-time context is not possible.

```sql
outreach_outcomes (
  send_id, contact_id, company_id,
  icp_version_id,          -- which ICP was active
  persona,                  -- contact tier at send time
  sequence_step,
  signals_at_send JSONB,   -- company signals active at send
  pqs_at_send,             -- PQS score at send time
  ccs_at_send,             -- Contact Confidence Score at send time
  opened_at,
  clicked_at,
  replied_at,
  reply_sentiment,         -- classified by Claude Haiku
  reply_classification,    -- interested / not_interested / wrong_person / unsubscribe / auto
  meeting_booked_at,
  deal_stage,
  deal_value,
  closed_at
)
```

### P7.2 — Reply Auto-Classification

Every incoming reply runs through Claude Haiku with a structured-output prompt returning:

```json
{
  "sentiment": "positive | neutral | negative",
  "intent": "interested | not_interested | wrong_person | unsubscribe | meeting_request | auto_reply",
  "wrong_person_flag": false,
  "key_objection": "budget | timing | not_a_fit | already_have_solution | null"
}
```

Cost: ~$0.0005/reply. Cache by reply hash. When `wrong_person_flag=true`: exclude that contact, optionally enqueue the suggested correct person for verification, decrement the company's contact-quality score for that source.

### P7.3 — Latency Targets

| Event | Target latency |
|---|---|
| Reply → classified | < 5 minutes |
| Reply → ICP weights updated | Nightly batch |
| Closed-won → ICP weights | Weekly batch |
| Hard bounce / wrong person → contact disposition | Real-time |

---

## Priority 8 — Data Governance and Audit

### P8.1 — Pre-Send Invariant Library

A set of `assert_*` checks that run before every send and log to a `send_assertions` table:

```python
assert_email_passes_deliverability(contact)
assert_email_name_consistent(contact)
assert_contact_in_outbound_eligible(contact)
assert_persona_matches_target(contact, icp_version)
assert_no_recent_send_to_company(company, days=30)
assert_ccs_above_threshold(contact, threshold=70)
assert_sender_under_daily_cap(sender)
```

Any assertion failure blocks the send and pages via Slack. This is the test-in-production safety net — it catches anything the upstream filters miss.

### P8.2 — Quality Dashboard: Leading Indicators

Track leading indicators that predict trouble before it appears in send outcomes:

| Metric | Alert Threshold | What it signals |
|---|---|---|
| % new contacts with CCS < 70 | Rising trend | Enrichment pipeline degrading |
| % pending drafts blocked by gates | Rising trend | ICP loosened or Apollo quality dropped |
| 7-day rolling hard bounce rate | > 2% | Deliverability emergency — pause sending |
| 7-day rolling wrong-person reply rate | > 1% | Email-name check failing — audit immediately |
| Spam complaint rate | > 0.1% | Existential deliverability threat — stop everything |
| Per-source bounce rate (Apollo vs LinkedIn-verified) | Diverging | One source is degrading |

**Every metric is rate-based, not volume-based.** The primary chart on the quality dashboard is `reply_rate × meeting_conversion_rate`, not `emails_sent`. What you measure is what you optimize.

### P8.3 — Weekly Post-Send Audit (Now Implemented)

`PostSendAuditAgent` runs Sunday 7am, scans all sends from the past 7 days, flags:
- Null email sends
- Name-email mismatches (detected post-send for contacts that predate the filter)
- Wrong job function that slipped through
- Over-threading (> 2 contacts at same company in 7 days)

Sends a Slack digest with severity breakdown. Adversarially sample 20 sends per week and score them 1–5 on "would you personally have sent this email to this person?" Track the score weekly.

---

## Email Integrity Policy

This is a first-class constraint applied to every Claude outreach prompt and enforced in `outreach_guidelines.yaml`.

**Prohibited:**
- "One of our clients saw X% improvement" — fabricated unless confirmed real and approved for use
- "We worked with [Company]" — never claim a past engagement that cannot be verified
- "A plant like yours reduced downtime by X%" — only if this is a published, citable industry benchmark
- Invented ROI numbers, pilot outcomes, success stories, or testimonials

**Acceptable:**
- Published industry benchmarks with source context ("plants in this sector typically run 15–20% unplanned downtime")
- Trade association statistics (SMRP, AMT, MESA, ISA)
- Regulatory data (FDA recall rates, OSHA incident rates by NAICS code)
- General manufacturing industry trends from reputable sources
- Conservative approximations framed explicitly as estimates ("operations like this typically...")

The standard: if Avanish could not defend the claim in a meeting with the prospect, it does not belong in the email. Integrity matters more than a compelling hook.

---

## Implementation Roadmap

| Week | Workstream | Deliverable |
|---|---|---|
| 1 (done) | P0 | contact_filter.py, import-time screening, post-send audit, outreach integrity rules |
| 1 (done) | P0.2 + P0.3 | Apollo email_status gate wired in enrichment + import; weekly local contact backup |
| 2 | P0.1 | outbound_eligible_contacts as hard SQL table (replaces boolean column) |
| 3 | P8.1 + P8.2 | Pre-send invariant library, quality dashboard, alerting |
| 4 | P1.2 | Clay subscription, raw_contacts table, identity resolver |
| 5 | P1.3 | CCS scoring, threshold tuning, backfill existing contacts |
| 6 | P3.3 | Tiered title classifier (deterministic → Haiku → human review) |
| 7 | P7.1 + P7.2 | outreach_outcomes table, reply auto-classification |
| 8 | P2.1 + P2.3 | ICP versioning, negative ICP exclusions table |
| 9 | P6.1 + first 2 scrapers | Signal store, FDA recalls + OSHA citations scrapers |
| 10 | P4.1 + P4.2 | Threading state machine, hardened threading rules |
| 11 | P3.1 | Persona-conversion ranker (initial version with priors) |
| 12 | P2.2 | ICP weight learner (first refined ICP version) |
| 13+ | P5.1 | Sequence block decomposition, prep for adaptive sequences |

Sequences (P5) are deferred until `outreach_outcomes` is live and generating training data. Adaptive sequences without outcome measurement optimize noise.

---

## Risks

**Sender reputation is a one-way door.** A burned domain takes months to recover. The Apollo `email_status` deliverability gate and pre-send invariant library are the highest-priority protective investments because the cost of inaction compounds faster than any other risk. If hard bounce rate exceeds 2%, engage ZeroBounce immediately for a full batch scrub.

**Apollo dependency is structural.** Have a quarterly sanity check: can you rebuild your ICP company list from LinkedIn + a manufacturing database without Apollo? You do not want to discover the answer is no when Apollo raises prices or degrades quality.

**Identity resolution edge cases compound over time.** People change jobs. Companies rebrand. The resolver needs a quarterly review of dedupe collisions and a manual override table. Budget for this ongoing.

**LLM-classified titles drift with model upgrades.** When the Haiku model version changes, re-classify the title-disposition cache or stale judgments persist. Version classifier output by model name.

**The biggest risk is not technical.** It is optimizing for sends volume rather than revenue per send. Every metric on the quality dashboard should be rate-based. What you measure is what you become.

---

*Document generated from architectural review session on 2026-04-30.*  
*Author: Avanish Mehrotra*
