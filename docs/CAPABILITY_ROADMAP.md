# ProspectIQ — Capability Ideation & Build Roadmap

**Created:** 2026-04-02 | **Author:** Avanish Mehrotra & ProspectIQ Technical Team
**Status:** Active — updated each planning session

---

## Overview

This document tracks every capability idea evaluated for the ProspectIQ platform:
what was built, what is planned, what was deferred and why, and the evaluation
criteria used. It serves as the living product ideation record across sessions.

---

## Evaluation Framework

| Criterion | Question |
|-----------|----------|
| **Outreach impact** | Does this directly improve reply rate, meeting rate, or pipeline velocity? |
| **User stickiness** | Does this bring users back daily, not just weekly? |
| **Build cost** | How much of the infrastructure already exists? |
| **Data dependency** | Does this require data we don't have yet? |
| **Product focus** | Does this strengthen the core prospecting identity, or dilute it? |

---

## Session Builds — April 2026 Sprint

All capabilities below were built in a single sprint session (2026-04-02).
Each is on its own feature branch, awaiting PR review and merge.

| # | Capability | Branch | Migration | What was built |
|---|-----------|--------|-----------|----------------|
| PIQ-1 | OutreachAgent | `feature/outreach-agent` | — | OutreachAgent with persona prompts, cluster context, 4 API routes, draft quality scorer |
| PIQ-2 | Reply HITL Queue | `feature/reply-hitl` | 019 | campaign_threads, thread_messages, hitl_queue tables; ReplyClassifier (8 intent categories, Haiku); HITL review interface |
| PIQ-3 | Personalization Engine | `feature/personalization-engine` | — | PersonalizationEngine with trigger extraction (Haiku), hook generation (Sonnet), readiness score; Intelligence leaderboard page |
| PIQ-4 | Visual Sequence Builder | `feature/sequence-builder` | 020 | campaign_sequence_definitions_v2; drag-and-drop step canvas, delay configurator, condition branches |
| PIQ-6 | Analytics & Revenue Attribution | `feature/analytics-revenue` | — | FunnelData/CohortAnalysis/VelocityMetrics models; Revenue Intelligence page with FunnelChart, CohortTable, RevenueProjection |
| PIQ-7 | Lookalike Discovery Engine | `feature/lookalike-discovery` | 022 | LookalikeEngine (cluster/tranche/PQS/employee/revenue/tech scoring); dual-panel discovery page; seed profile card |
| PIQ-9 | Signal Monitoring / Trigger Engine | `feature/signal-monitoring` | — | Trigger rules engine; APScheduler jobs; trigger feed UI |
| PIQ-10 | Password Reset + Auth Hardening | `feature/password-reset` | 023 | Forgot-password flow, reset-password with strength indicator, security settings (sessions + audit log), rate limiting, auth_audit_log |

---

## Current Build Pipeline — Waves A through H

Waves run in parallel with Digitillis builds. ProspectIQ builds are launched
alongside their DIG counterpart each wave.

### Wave A — Multi-Thread Orchestration
**What it is:** Automatically reach multiple contacts at the same target account
simultaneously, coordinating messaging so contacts receive complementary
(not duplicate or conflicting) outreach.

**Why now:** Enterprise deals require multi-threaded outreach. Single-threading
is the #1 reason deals stall at manager level. Straightforward to build on the
existing campaign and sequence infrastructure.

**Key design:** One parent campaign per account; child threads per contact;
shared account-level suppression to prevent duplicate sends; coordinator logic
that staggers contacts by 48h.

---

### Wave B — Ghostwriting Engine
**What it is:** Generates LinkedIn posts, short-form articles, and thought
leadership content in the user's voice, calibrated from a style sample.

**Why now:** Content marketing compounds outreach — prospects who see your posts
before receiving your message have 3× higher reply rates. Fast to build, high
daily stickiness.

**Key design:** Voice profile builder (paste 3 existing posts → Sonnet extracts
tone, vocabulary, sentence structure) → content generator with topic seeding →
one-click post to LinkedIn (or copy to clipboard).

---

### Wave C — Voice-of-Prospect Agent
**What it is:** Analyses patterns across all received replies to surface:
what messaging resonates, what objections repeat, which personas engage most,
and which sequence steps have the highest drop-off.

**Why now:** Every reply is a data point. Haiku can process them cheaply.
Insight compounds in value the longer the platform runs — this is a moat builder.

**Key design:** Weekly batch job over reply corpus; Haiku extracts themes and
sentiment per intent category; dashboard card showing top 5 resonance themes
and top 3 objection patterns.

---

### Wave D — Intent Data Surge (free signals)
**What it is:** Detects when a prospect company is actively in a buying window
by monitoring free public signals: job postings (hiring for roles that indicate
a pain point), funding announcements, tech stack changes (BuiltWith diff),
LinkedIn activity spikes.

**Why now:** Reaching out when someone is actively researching buys dramatically
improves timing. All signals used are free — no paid intent data dependency.

**Note:** Paid intent data (Bombora, G2) deferred until post-revenue. Re-evaluate
at $200K ARR.

---

### Wave E — ICP Evolution Engine
**What it is:** Automatically refines the Ideal Customer Profile based on which
companies actually replied, booked meetings, or converted — creating a learning
feedback loop from outcomes.

**Condition:** Activate evolution logic only after 50+ closed outcomes are
recorded. Build outcome feedback collection hooks in this wave; evolution runs
as a scheduled job once threshold is reached.

**Key design:** Outcome tagging on campaign threads (won/lost/no-response);
Sonnet compares winning vs losing company profiles; surfaces updated ICP
attributes ranked by signal strength.

---

### Wave F — Automated Social Proof
**What it is:** Dynamically inserts relevant case study snippets, data points,
or testimonials into outreach messages based on the prospect's industry, company
size, and pain theme.

**Condition:** Requires a curated library of 5–10 proof point assets before the
insertion engine has anything to work with. Build the asset library and tagging
UI first; the insertion logic follows naturally.

**Key design:** Proof point library (title, industry tags, company size range,
pain theme, snippet text); insertion hook in OutreachAgent that matches and
injects the best-fit snippet per draft.

---

### Wave G — Competitive Battlecard Engine
**What it is:** On-demand generation of competitive positioning cards — user
inputs "I'm competing against [tool]" and gets a battlecard: key differentiators,
common objections from that competitor's users, recommended reframe language.

**Framing:** User-driven (not auto-detected). Simpler, more accurate, and avoids
the stale-data problem of automated competitive monitoring.

**Key design:** Competitor database (name, category, known weaknesses from public
reviews, G2 data); Sonnet generates positioning language per competitor; saved
battlecards per workspace.

---

### Wave H — Revenue Forecasting
**What it is:** Predicts pipeline yield from current outreach activity:
given N contacts in sequence at stage X, with historical conversion rates at
each stage, what revenue should be expected in 30/60/90 days.

**Condition:** Needs 3+ months of outcome data to produce meaningful predictions.
The analytics foundation from PIQ #6 (funnel/cohort/velocity models) already
provides the data layer.

**Key design:** Stage-weighted pipeline model; per-stage conversion rates updated
weekly from actuals; confidence interval shown alongside projection to avoid
false precision.

---

## Deferred Backlog

| Capability | Deferred reason | Re-evaluate when |
|-----------|----------------|-----------------|
| **Warm Introduction Graph** | LinkedIn API heavily restricted. Alumni/mutual connection data is hard to source programmatically. | LinkedIn API access or data partnership (e.g. Clay, Apollo graph) secured |
| **Discovery Call Intelligence** | Recording + transcription + analysis is a product category by itself (Gong/Chorus). Significant infrastructure scope. | ProspectIQ ARR > $500K and customers explicitly requesting it |
| **Churn/Expansion Tracker** | Dilutes core prospecting identity. More CRM/CS tooling than outreach intelligence. | Post-acquisition revenue motion confirmed; customers explicitly asking for it |
| **RBAC Full Enforcement** | Single-user per account today. RBAC exists in DB but not enforced at route level. Zero urgency. | First multi-user workspace team about to onboard |
| **Paid Intent Data Integration** | Bombora/G2 start at ~$30K/year. Not cost-effective pre-revenue. | ARR > $200K with clear intent data ROI case |

---

## Security Fixes Pending Merge

| Branch | Description | Priority |
|--------|-------------|----------|
| `fix/require-human-approval-all-channels` | LinkedIn drafts were auto-approved at creation. Fixed to `pending`. 87 affected records reverted to pending in DB. | **Critical — merge immediately** |

---

## Build Summary Totals

| | Completed (April sprint) | In pipeline (Waves A–H) | Deferred |
|---|---|---|---|
| **ProspectIQ** | 8 | 8 | 5 |

---

*Author: Avanish Mehrotra & ProspectIQ Technical Team*
*Copyright © 2026 ProspectIQ. All rights reserved.*
