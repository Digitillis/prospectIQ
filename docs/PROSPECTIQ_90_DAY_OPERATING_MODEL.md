# ProspectIQ — 90-Day Precision GTM Operating Model

> **Status: LOCKED DOCTRINE — 2026-05-12**
> This document governs ProspectIQ's operating model for the 90-day period beginning 2026-05-12.
> Do not expand scope, add autonomous features, or redesign architecture during this period.
> Revise only after the day-60 retrospective with GTM data to justify changes.

---

## Operating Philosophy

ProspectIQ is a **copilot, not a pilot.**

It prepares Avanish for conversations. It does not have conversations.

Every decision about which accounts matter, which messages go out, and what happens after a response is a human decision. The system's job is to make those human decisions faster, better-informed, and operationally credible.

**Three constraints that must not erode:**

1. **Founder bandwidth is the scarcest resource.** The system must fit inside four to six hours of focused GTM work per week. Anything requiring more is the wrong design.

2. **Reputation is harder to rebuild than to protect.** One hallucination reaching a connected manufacturing executive costs more than six months of careful outreach earns. Every governance decision biases toward protection over throughput.

3. **Learning is the primary output for 90 days, not pipeline.** The goal is to identify what combination of account profile, message frame, and timing earns a qualified conversation. That learning is what scales.

**Success metric:** qualified manufacturing conversations, not emails sent, not pipeline volume, not agent runs completed.

---

## Weekly Operating Cadence

Total founder time: **4–5 hours per week.**

| Day | Block | Time | What Happens |
|---|---|---|---|
| **Monday** | Account Intelligence Review | 30 min | Review top-50 Google Sheet. Check new signals (Google Alerts, Apollo). Update account stages. Flag any action items. |
| **Tuesday** | Research and Briefing Review | 60 min | Trigger research agent on new accounts. Review briefs for accounts moving to Active. 10 min max per brief. Flag briefs without at least one sourced, operationally specific fact. |
| **Wednesday** | Messaging Review and Approval | 90 min | Review AI-generated drafts. Make at least one substantive edit per draft. Remove unsourced claims. Approve or reject. Max 10 drafts per session. |
| **Thursday** | Send and Follow-up | 30 min | Execute week's sends (max 20/day, verified only). Handle any HubSpot follow-up items. Personal response to any engagement signals within 24 hours. |
| **Friday** | Weekly Retrospective | 30 min | Add rows to GTM Learning Log. Write one observation. Update STRATEGIC_INTELLIGENCE.md open questions if anything surfaced. |

---

## Account Stage Model

Seven stages. Clear gates between each. Hard cap of **30 accounts in Active Outreach** for the first 60 days.

### Stage 1 — Watchlist
Companies identified as potentially relevant. No research run. Pool from which Active accounts are drawn. Can hold 100+ companies.

**Gate to Researched:** Avanish decides the account is worth the research investment.

### Stage 2 — Researched
Research agent has run. Structured brief exists. Avanish has read and validated the key claims.

**Gate to Active Outreach — all three must be true:**
- PQS score ≥ 40
- At least one verified email exists for a contact at appropriate seniority
- At least one timing signal present (trigger event, hiring signal, compliance deadline, or existing engagement)

### Stage 3 — Active Outreach
On the send list. Max 30 accounts. First message approved or ready for approval. One to three contacts per account, three touches maximum, spaced 7–14 days apart. Avanish reviews every first touch.

**Gate to Engaged:** any engagement signal (reply, multiple opens, link click).
**Gate to Dormant:** full 3-touch sequence complete, no engagement after 14 days past final touch.

### Stage 4 — Engaged
Account showed a signal. Exits automated pipeline immediately.

**Action:** Avanish notified immediately. Personal non-templated response within 24 hours. Added to HubSpot as active deal. Research brief refreshed if older than 2 weeks.

**Gate to Conversation Active:** Avanish has had an actual exchange (reply and response, LinkedIn message, call scheduled).

### Stage 5 — Conversation Active
Real dialogue happening. ProspectIQ role: zero. HubSpot is the system of record. Avanish manages every touch personally.

**Gate to Dormant:** conversation stalls after 3 attempts to re-engage over 4 weeks.
**Gate to Disqualified:** Avanish determines not a fit.

### Stage 6 — Dormant
Was Active or Engaged. No response after full sequence. Parked, not deleted.

**Review cycle:** every 90 days. Reactivate to Researched if a new trigger signal appears.

### Stage 7 — Disqualified
Researched or engaged but not a fit. **Always record the reason.** Reasons are learning data.

---

## Founder Workflow

### Time Budget
4–6 hours per week. Ceiling, not floor.

### What ProspectIQ Does for Avanish
- Generates research briefs on demand (15 min compute vs. 3 hours manual)
- Produces evidence-constrained first-draft outreach for review
- Scores and ranks accounts by PQS
- Tracks sends, engagement signals, and bounces
- Delivers approved messages via Resend with verification confirmed

### What Remains Fully Human
- Every account selection decision
- Reading and validating every research brief before an account goes Active
- Substantive edit to every first-touch draft before approval
- All post-engagement communication
- Weekly retrospective

### How to Consume a Research Brief
Read in 10 minutes. Highlight 1–3 facts that would demonstrate genuine operational knowledge in a conversation. Note the single most relevant pain signal. Note whether the timing signal is strong or weak.

Ask: could I use this fact in a sentence to a plant manager without sounding like I'm reading from a script? If no, the brief is not ready.

### Message Approval Rule
**Avanish must make at least one substantive edit before approving any draft.**

Substantive = rewrite of the opening line, replacement of a generic claim with a specific one, removal of a prohibited pattern, or revision of the call to action.

Cosmetic edits (punctuation, capitalization, minor word swaps) do not count.

If you cannot find something to improve, you have not read it carefully enough. Read it again.

### Engagement Escalation
Any reply, multiple opens, or link click → immediate personal response within 24 hours → HubSpot active deal → research brief refresh → no further automated touches on this account.

---

## ProspectIQ Role Boundaries

### ProspectIQ IS:
- Research generator (on demand, structured intelligence briefs)
- Draft generator (evidence-constrained candidates for founder review)
- Contact database (Apollo-enriched, ZeroBounce-verified)
- Send executor (delivers Avanish-approved messages via Resend)
- Engagement tracker (sent / opened / clicked / replied)
- Qualification scorer (manufacturing-specific PQS model)

### ProspectIQ IS NOT:
- Account selector
- Decision maker
- Conversation manager
- CRM (HubSpot is the CRM)
- Autonomous SDR
- Signal monitor (Google Alerts handles this for now)
- Learning system (GTM Learning Log in Google Sheets handles this)

### System Boundary
> ProspectIQ prepares Avanish to have conversations.
> Everything after "a conversation begins" is human territory.

### Components Frozen for 90 Days
The following components are **out of scope** for this operating period. Do not expand, fix bugs in, or invest engineering time in these:

| Component | Reason Frozen |
|---|---|
| `LearningAgent` | 1 reply total — no training signal |
| `DiscoveryAgent` autonomous pipeline | Replaced by curated human selection |
| AB test infrastructure | No volume for meaningful tests |
| HITL queue system | Empty; `outreach_drafts` approval is sufficient |
| Multi-tenant workspace architecture | ProspectIQ has one workspace |
| Intent signal monitoring agent | Signal sources not integrated |
| Reply classifier agent | Classify manually at current volume |
| Post-send audit agent | Not needed at current send volume |
| Personalization refresh job | Burns API credits on non-active accounts |
| Voice of prospect routes | Not on critical path |
| Multi-thread / ghostwriting / deals / meetings routes | CRM feature; HubSpot handles this |
| Health snapshots (15-min job) | Overhead for a one-user tool |

---

## Account Discovery Model

### Primary Sources (in priority order)
1. **Existing ProspectIQ database** — 2,465 companies already in system. Filter by PQS ≥ 40, verified email, timing signal. Top-30 list for first 90 days drawn primarily from here.
2. **Founder's own knowledge** — accounts Avanish already knows are strong fits go directly to Watchlist.
3. **Trade publications** — IndustryWeek, Manufacturing Engineering, Food Manufacturing, Plant Engineering. 15-min read twice weekly surfaces 2–3 high-quality candidates with timing signal already baked in.
4. **Apollo manual search** — deliberate monthly run with specific ICP filters. Avanish reviews results and manually selects. Not automated. ~30 min/month.
5. **Signal-triggered additions** — Google Alerts keyword hits surface companies at the moment a timing signal fires.
6. **Network and referrals** — any manufacturing contact or industry event connection goes directly to Watchlist.

### What Does NOT Drive Discovery
- Autonomous DiscoveryAgent pipeline (frozen for 90 days)
- Unsupervised Apollo crawls
- High-volume company ingestion without human selection gate

---

## Messaging Governance

### Trust Rules
Every specific operational claim in an outreach message must trace to a sourced field in the company record. Before approving any draft, verify every claim has a source. If you cannot trace a claim, remove it.

**The test:** could you defend this claim in a conversation if the recipient challenged it? If no, the claim does not belong in the message.

### Evidence Hierarchy
| Source Type | Status in Outreach |
|---|---|
| Primary (press release, official announcement, SEC filing) | Can be stated as fact |
| Secondary (trade coverage, job posting, LinkedIn company post) | Stated with hedging: "based on your recent hiring activity..." |
| Inferred (model knowledge, industry pattern, no external source) | Context frame only — never stated as company-specific fact |

### Prohibited Patterns
- "We noticed you recently [unsourced event]"
- Reference to internal operational incident not confirmed in public records
- Claims about technology systems unless confirmed from job postings, website, or press
- Subject lines containing "AI," "platform," or "solution"
- Messages over 200 words for first touch; over 300 words for any touch
- Undated trigger events (no date = likely fabricated)
- Opening compliments about the company unless the referenced event is real, sourced, and relevant

### Tone Principles
- **Operational, not aspirational** — describe what is happening or could happen operationally, not in business outcome abstractions
- **Specific, not categorical** — name the equipment type, the failure mode, the process step; never "your manufacturing operations"
- **Credible, not promotional** — every sentence should be something a person who deeply understands manufacturing would say
- **Peer-level, not pitch-level** — reaching out as someone who understands their world, not as someone selling
- **Brief** — if it does not fit in a mobile email preview pane, it is too long

### Founder Review Rule
**One substantive edit minimum before any approval. No exceptions.**

---

## Tool Stack

| Function | Tool | Notes |
|---|---|---|
| Account list management | Google Sheets | Top-50 list, stages, signals, last touch |
| CRM / meeting tracking | HubSpot free | Deal stages, meeting notes, follow-up cadence |
| Signal monitoring | Google Alerts + Apollo signals | One alert per active account |
| Email verification | ZeroBounce (enforced gate in ProspectIQ) | Hard block — unverified contacts cannot enter send queue |
| Email warmup | Instantly | Running — do not change |
| Email delivery | Resend | Running — do not change |
| Contact enrichment | Apollo people/match (validated inputs) | Evaluate Clay at day 30 if 422 errors persist |
| One-off account briefs | Claude chat | For <5 accounts/week — no code needed |
| Second opinion on drafts | ChatGPT | Cross-check tier-1 first touches before approval |
| Code implementation | Claude Code | Repository changes only |
| Strategy / doctrine | Claude Code conversation | Decisions logged to STRATEGIC_INTELLIGENCE.md |

---

## Collaboration Model

| Task | Tool | Notes |
|---|---|---|
| Strategic decisions | Claude Code (this tool) | Document in STRATEGIC_INTELLIGENCE.md |
| Account research briefs (one-off) | Claude chat | Paste sourced company record, ask for angles |
| Draft iteration (important accounts) | Claude chat | Paste draft, ask for critique from plant manager POV |
| Draft tone-check (tier-1 first touches) | ChatGPT | Second opinion before approval |
| Batch research and drafts | ProspectIQ agents | Weekly cadence |
| Code changes | Claude Code | PR per fix, tests required |

---

## Meeting Preparation Workflow

**30-minute standard brief before any first manufacturing conversation.**

| Step | Time | Content |
|---|---|---|
| Operational fingerprint | 10 min | What they make, critical equipment, what a bad day looks like, maintenance posture |
| Technology context | 5 min | Known or inferred SCADA/DCS/CMMS/ERP — shapes the integration story |
| Recent signal summary | 5 min | What happened in the last 12 months that makes the conversation timely |
| Credibility test prep | 5 min | Write 3 specific operational questions they might ask to test you. Answer them. |
| Value hypothesis | 5 min | For THIS account specifically: what is the first operational win in operational terms, not platform terms |

**Post-meeting debrief (10 min, same day) — 5 bullets in HubSpot:**
1. What did they care about most?
2. What did they dismiss?
3. What question showed genuine interest?
4. What is their biggest concern?
5. Fit assessment: yes / conditional / no, and why.

---

## Learning Capture Process

**Minimum viable — Google Sheet + 15-minute weekly ritual.**

### GTM Learning Log Columns
`Date | Account | Vertical | Transformation Stage | Asset Class | Message Angle | PQS Score | Outcome | Resonance Notes | Follow-up`

Fill one row per send. Outcome: no response / bounce / unsubscribe / open only / click / reply / meeting booked / disqualified.

### Weekly Pattern Review (Friday, 5 min)
Answer: is there a pattern in which accounts responded? Which message angles got engagement? Which verticals/stages are more responsive? Write one sentence.

### Monthly ICP Refinement (first Monday, 30 min)
Review past month. Make one concrete update to account selection criteria or PQS weighting. Ground it in actual data. No updates on intuition alone.

### After Every Meeting (same day, 10 min)
Write 5-bullet debrief in HubSpot. Commit any strategic insight to STRATEGIC_INTELLIGENCE.md.

### After Every Closed or Lost Deal (60 min post-mortem)
Full deal debrief committed to STRATEGIC_INTELLIGENCE.md. For a win: what signals predicted it, what opened the door. For a loss: what was the real reason, what would you do differently.

---

## KPI Framework

**Four metrics only. Review weekly. Nothing else for 90 days.**

| Metric | Definition | Target |
|---|---|---|
| **Qualified conversations** | Real dialogue with operational decision-maker about a specific problem | 0 (wks 1–2) → 1/wk (wk 4) → 2/wk (wk 8) |
| **Active accounts** | Accounts in Active Outreach stage | 10 (wk 2) → 20 (wk 4) → 30 (wk 6) |
| **Bounce rate** | Hard bounces / sends, rolling 7-day | Below 2% always. Kill switch if exceeded. |
| **Draft approval rate** | Approved / total drafts reviewed | Above 60%. Below 50% = research or prompt quality problem. |

**Do NOT track:** emails sent, open rates, click rates, pipeline volume, enrichment completion, agent run counts, PQS averages, contacts discovered.

---

## 90-Day Blueprint

### Days 1–14 — Foundation
**Engineering:** merge PR #76 (done), fix Apollo 422 input validation, fix email verification gate, implement evidence-constrained draft generation, confirm Railway scheduler, raise budget cap.

**Account management:** build top-30 list in Google Sheets from existing database (PQS ≥ 40, verified email, timing signal). Run research on 7 engaged accounts.

**Tooling:** set up HubSpot free with 7-stage account model. Set up Google Alerts for all 30 accounts. Create GTM Learning Log.

**Outreach:** Avanish writes personal first-touch messages to all 7 engaged accounts **this week, before any code changes.**

**Expected output:** infrastructure fixed, top-30 populated, first 7 sends executed, HubSpot and learning log operational.

---

### Days 15–30 — First Cadence
**Priority:** establish weekly rhythm. Begin first real send wave.

- Research on all 30 active accounts. Review all 30 briefs.
- Weekly cadence running: first wave 10 accounts, verified only, Avanish-reviewed drafts.
- First entries in GTM Learning Log.
- **Day 30 retrospective:** 2 paragraphs in STRATEGIC_INTELLIGENCE.md.

**Expected output:** weekly rhythm established, 10–15 accounts in Active Outreach, first engagement signals visible, 10 rows in learning log.

---

### Days 31–45 — Controlled Expansion
**Priority:** full top-30 active. First engaged conversions. Learning from patterns.

- All 30 accounts in Researched or Active by day 40.
- Follow-up touches running for first-wave accounts.
- Engagement signals moved to Engaged stage and handled personally.
- Monthly ICP review at day 45. One concrete update to selection criteria.

**Target:** at least 1 qualified conversation booked by day 45.

---

### Days 46–60 — Learning and Adjustment
**Priority:** apply what has been learned. Refine account profile and message frame.

- Apply first lessons (if compliance angle works for food processing, all food processing drafts lead with compliance).
- Accounts with completed sequences and no engagement move to Dormant. Replace with Watchlist candidates.
- **Day 60 evaluation:** is cadence sustainable? At least 2 qualified conversations? Expand to 50? Evaluate Clay?

---

### Days 61–75 — Validated Motion
**Priority:** confirm the pattern. Run a second cohort with refined model.

- 3–4 qualified conversations total by day 75.
- Clear picture of which account archetypes respond.
- Clear picture of which message angles work.
- Expand to 50 accounts only if weekly rhythm can absorb without quality degradation.

---

### Days 76–90 — Retrospective and Planning
**Priority:** document learning. Design what comes next.

- 90-day retrospective committed to STRATEGIC_INTELLIGENCE.md.
- Next 90-day engineering and GTM plan — based on proven GTM data only.
- 5+ qualified conversations total. At least 1 in active discovery stage.

**The rule:** do not design the next phase until this phase has produced the learning to justify it.

---

## Anti-Patterns to Avoid

1. **Approving drafts without editing them.** The edit is the quality gate. No exceptions.
2. **Letting the account list exceed the cadence's capacity.** Cut accounts before cutting quality.
3. **Treating an engaged account as a pipeline statistic.** Personal response within 24 hours. Always.
4. **Optimizing for sends instead of conversations.** 5 sends and 1 qualified reply beats 50 sends and 0 replies.
5. **Building new ProspectIQ features before the day-60 retrospective.** The four-item fix list is the complete engineering scope for the first 30 days.
6. **Email as the only channel.** LinkedIn, community engagement, and trade publications run in parallel. Tracked in HubSpot manually.
7. **Waiting for the system to be perfect.** The 7 engaged accounts get personal messages this week, before any code changes.

---

## First Action Item

**Send personal, founder-written first-touch messages to all 7 engaged accounts this week.**

Waupaca Foundry · Richline Group · Precoat Metals · Friedman Industries · Westrock Coffee · AMETEK Specialty Metal Products · Tsubaki Nakashima

Use the existing research briefs. No pipeline needed. No code needed. These accounts showed signal. They have been waiting.

---

*Document owner: Avanish Mehrotra*
*Locked: 2026-05-12*
*Next review: 2026-07-11 (day 60 retrospective)*
