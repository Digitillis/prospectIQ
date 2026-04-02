# ProspectIQ — Implementation Plan
> **Author:** Avanish Mehrotra & Digitillis Architecture Team
> **Date:** 2026-04-02
> **Purpose:** Prioritized build plan for ProspectIQ as a standalone commercial product
> **Source:** Gaps identified in PROSPECTIQ_STANDALONE_PRODUCT_ANALYSIS.md

---

## Summary

Total identified work across 4 phases: **~55 days** of active development.
- Phase 0 (Launch Blockers): 11 days — nothing ships without this
- Phase 1 (Launch Readiness): 13 days — commercial-grade product
- Phase 2 (Competitive Parity): 18 days — matches and beats competitors
- Phase 3 (Differentiation): 13 days — moat-building capabilities

---

## Phase 0 — Launch Blockers
*Must be complete before the first paying customer. These are hard stops — not nice-to-haves.*

| # | Item | Layer | What to Build | Files / Location | Effort |
|---|---|---|---|---|---|
| 0.1 | **Stripe billing live** | Infrastructure | Wire Stripe products at 3 tiers ($1,500 / $3,500 / $7,500/mo). Replace placeholder price IDs. Enforce plan limits (companies/mo quota). Billing portal for self-serve changes. 14-day trial with card required. | `backend/app/billing.py`, `backend/app/billing/usage.py` | 3 days |
| 0.2 | **RBAC enforcement on all routes** | Infrastructure | Add `require_role(min_role)` dependency to all write endpoints. Owner / admin / member / viewer enforced at handler level, not just middleware. | All `backend/app/api/routes/*.py` | 2 days |
| 0.3 | **Supabase RLS on core tables** | Infrastructure | Enable Row-Level Security on `companies`, `contacts`, `outreach_drafts`, `interactions`, `api_costs`. Every query must be workspace-scoped at DB layer — middleware is not sufficient. | Supabase migration + audit all queries | 1 day |
| 0.4 | **LinkedIn automation via Unipile** | Outreach Engine | Replace manual copy-paste with automated send. `linkedin_sender.py` agent wraps Unipile API. Webhook endpoint for `connection_accepted` event → auto-queues opening DM. Daily send limit enforced (20 connection requests/day). Auto-withdraw stale invites after 21 days. Per-workspace toggle (`auto_send_enabled`) in Settings. | `backend/app/agents/linkedin_sender.py`, `backend/app/api/routes/webhooks.py`, `config/sequences.yaml` | 4 days |
| 0.5 | **Audit log population** | Infrastructure | Populate `audit_log` table on: login, plan change, pipeline run, draft approved, contact exported, workspace member change. Table exists — events just not being written. | `backend/app/core/audit.py` + call sites | 1 day |

**Phase 0 total: 11 days**

---

## Phase 1 — Launch Readiness
*Complete within the first 2 weeks post-launch. These are not blockers but are required for a credible commercial product.*

| # | Item | Layer | What to Build | Files / Location | Effort |
|---|---|---|---|---|---|
| 1.1 | **Awareness stage classifier** | Targeting | New field `awareness_stage` (enum: unaware / problem_aware / solution_aware / evaluating) on `companies` table. After research agent runs, lightweight Claude call classifies stage from research text + tech stack + signals. Stage passed as context to outreach agent → selects correct message angle from config. | `backend/app/agents/research_agent.py`, `supabase_migrations/`, `config/sequences.yaml` | 1 day |
| 1.2 | **Awareness-stage outreach variants** | Outreach Engine | 4 outreach prompt variants in `sequences.yaml` — one per awareness stage. Educate (unaware) / Validate (problem_aware) / Differentiate (solution_aware) / Prove (evaluating). Each variant has distinct angle, CTA strength, and proof-point framing. | `config/sequences.yaml`, `backend/app/agents/outreach_agent.py` | 1 day |
| 1.3 | **Seller offer context in workspace setup** | Outreach Engine | "Offer Context" step in workspace onboarding. Captures: one-sentence offer statement, before-state description, after-state transformation, top 5 objections, why-now angles. Stored in `workspace_settings`. Fed into every outreach prompt — outreach agent now knows what it's selling, not just who it's selling to. | `backend/app/api/routes/workspaces.py`, `dashboard/app/settings/`, DB migration | 1 day |
| 1.4 | **Pre-send filter before research** | Targeting | Move PQS filtering to pre-research stage. Fast rule-based scoring (Haiku + firmographic rules) filters out 40–60% of leads before any Perplexity call. Only high-confidence prospects proceed to expensive research. Estimated cost reduction: 30–40% per batch run. | `backend/app/agents/discovery_agent.py`, `backend/app/core/scoring.py` | 1 day |
| 1.5 | **Cost per meeting dashboard** | Learning Loop | Primary analytics view showing: total API spend, meetings booked, cost per meeting (API spend / meetings booked), cost breakdown by agent (Perplexity, Claude, Apollo). This is the north star metric. Operators must be able to see their ROI at a glance. | `dashboard/app/analytics/page.tsx`, `backend/app/api/routes/analytics.py` | 1 day |
| 1.6 | **Model tiering (Haiku for scoring)** | Learning Loop | Enforce model tier separation throughout agent pipeline. Haiku for: PQS scoring, reply classification, awareness stage classification, pre-send filtering. Sonnet for: outreach generation, research extraction, reply drafting. Perplexity for: web research only. Target: reduce per-lead cost from ~$0.50 to ~$0.15. | All agent files — `ANTHROPIC_MODEL` config per agent | 1 day |
| 1.7 | **Google OAuth + 2FA** | Infrastructure | Add Google OAuth via Supabase social auth. Add TOTP-based 2FA via Supabase MFA. Required for enterprise buyer trust. | `backend/app/api/routes/auth.py`, `dashboard/app/auth/` | 1 day |
| 1.8 | **Sentry + structured logging** | Infrastructure | Sentry SDK in backend (FastAPI) and frontend (Next.js). Add `workspace_id` + `batch_id` to all log lines. Pipeline run IDs logged throughout. Cost alerts: email when workspace API spend exceeds configurable threshold. | `backend/app/main.py`, all agent files, `dashboard/src/` | 1 day |
| 1.9 | **ICP onboarding wizard** | Targeting | Replace blank YAML config with 10-question guided onboarding. Questions map to: ideal customer profile, industry verticals, company size range, pain signals, top 3 past best customers, anti-ICP disqualifiers, seller offer statement. Claude parses answers into `config/icp.yaml` + `config/scoring.yaml` + `config/outreach_guidelines.yaml`. Non-technical users can set up in 15 minutes. | `dashboard/app/onboarding/`, `backend/app/api/routes/onboarding.py` | 3 days |
| 1.10 | **Rate limiting on API endpoints** | Infrastructure | Per-workspace + per-IP rate limiting on all pipeline trigger endpoints. Prevent abuse and runaway API costs from misconfiguration. | `backend/app/middleware/rate_limit.py` | 0.5 day |
| 1.11 | **API key hashing** | Infrastructure | Store only SHA-256 hash of workspace API keys — never plaintext. Rotate any existing keys. | `backend/app/core/api_keys.py`, DB migration | 0.5 day |

**Phase 1 total: 13 days**

---

## Phase 2 — Competitive Parity
*Weeks 5–12 post-launch. These close the remaining gaps vs. Beeze, Clay, and AI SDR competitors.*

| # | Item | Layer | What to Build | Files / Location | Effort |
|---|---|---|---|---|---|
| 2.1 | **Real-time signal monitor agent** | Targeting | `signal_monitor.py` — cron agent (daily for Growth+, weekly for Starter). Re-researches tracked companies for new signals via Perplexity: leadership changes, CapEx/plant expansion, M&A activity, competitor evaluation, sustainability mandates, workforce challenges, regulatory pressure. Fires `signal_detected` event → re-queues company for outreach refresh. Surfaces on `/signals` page + company profile. | `backend/app/agents/signal_monitor.py`, `dashboard/app/signals/page.tsx` | 3 days |
| 2.2 | **Trigify integration (competitor engagement monitoring)** | Targeting | `signal_hunter.py` agent — connects to Trigify webhook (or documented as user self-setup at Starter tier). When a prospect company employee engages with a configured competitor's LinkedIn post → creates `intent_signal` record → surfaces in `/signals` + triggers PQS recalculation. Workspace config: `config/competitors.yaml` (list of competitor LinkedIn URLs to monitor). **Highest-value single signal for manufacturing ICP.** | `backend/app/agents/signal_hunter.py`, `backend/app/api/routes/webhooks.py`, `config/competitors.yaml` | 1 day |
| 2.3 | **PQS temporal recalculation** | Targeting | PQS recalculates automatically when new signals arrive, not just at initial research time. Signal event → score delta → re-sort prospect list → optional alert if company crosses qualification threshold. | `backend/app/core/scoring.py`, event handlers | 1 day |
| 2.4 | **Post-meeting intelligence agent** | Conversation | `post_meeting.py` agent. Webhook: `POST /api/webhooks/fathom` (or Fireflies). Transcript text → Claude extraction: summary, pain points confirmed, tech stack mentioned, budget signal, decision-maker status, BANT/MEDDIC coverage, timeline, follow-up email draft, deal stage update, next-step tasks. Auto-updates `companies` status + logs `interactions` + queues follow-up draft for HITL approval. Extends ProspectIQ from discovery-to-outreach → discovery-to-close. | `backend/app/agents/post_meeting.py`, `backend/app/api/routes/webhooks.py` | 2 days |
| 2.5 | **BANT/MEDDIC scoring in post-meeting** | Conversation | Part of post-meeting agent output. Flag which qualification dimensions were established vs. missing: Budget confirmed / Authority identified / Need validated / Timeline stated. Updates company qualification confidence score. | Built into `post_meeting.py` | 0.5 day |
| 2.6 | **HubSpot CRM sync** | Infrastructure | Two-way sync: companies, contacts, interactions, deal stage. Sync triggered on: company status change, meeting booked, interaction logged. HubSpot OAuth + webhook for inbound updates (deal stage changes reflected in ProspectIQ). First CRM integration — Salesforce second. | `backend/app/integrations/hubspot.py`, `dashboard/app/settings/integrations/` | 5 days |
| 2.7 | **Outreach quality gate (Hormozi check)** | Outreach Engine | Pre-return self-critique pass in outreach agent prompt. Before draft is returned, Claude checks: (1) Does this reference a specific outcome for THIS company? (2) Is there a believable proof point? (3) Is the CTA low-friction? If any check fails → rewrite that sentence before returning. Applied to all outreach and LinkedIn message generation. | `backend/app/agents/outreach_agent.py`, `backend/app/agents/linkedin_sender.py` | 1 day |
| 2.8 | **Forbidden phrase guardrails** | Outreach Engine | Add negative constraint list to `config/outreach_guidelines.yaml`. Detect and rewrite: "many manufacturers", "companies like yours", "significant downtime", "improve your operations", "cutting-edge AI", "industry-leading", "we help companies", "reach out to learn more", "would love to connect". Each flagged phrase replaced with something grounded in company-specific research. | `config/outreach_guidelines.yaml`, `backend/app/agents/outreach_agent.py` | 0.5 day |
| 2.9 | **Research auto-refresh on signal fire** | Research | When `signal_detected` event fires for a company, auto-queue for research refresh if last research is >14 days old. Fresh context = more relevant outreach. | `backend/app/agents/research_agent.py`, event handlers | 1 day |
| 2.10 | **Reply strategy variants** | Conversation | Add named reply handling strategies to `config/sequences.yaml`: (1) Positive reply → transition to call (offer to help, not "book a call") (2) No-reply follow-up → add new value, don't just bump (3) "Tell me more" → three response variants: concise / story / flip-the-question. Reply classification agent selects strategy by reply type. | `config/sequences.yaml`, `backend/app/agents/reply_agent.py` | 1 day |
| 2.11 | **Benchmark metrics display** | Learning Loop | Show operators how their numbers compare to target benchmarks: reply rate (target 18% vs. 1–3% industry average), cost per lead (target $0.15 vs. $0.50+ untiered), meetings per 100 prospects. Toggle to expose benchmarks to clients in Settings (admin controls visibility). | `dashboard/app/analytics/`, `backend/app/api/routes/analytics.py` | 1 day |
| 2.12 | **A/B testing with significance tracking** | Learning Loop | Pair message variants at generation time. Track reply rates per variant. Calculate statistical significance when sufficient sample reached (min 30 sends per variant). Surface winning variant + confidence in analytics. | `backend/app/core/ab_testing.py`, analytics endpoints | 1 day |

**Phase 2 total: 18 days**

---

## Phase 3 — Differentiation & Moat
*Weeks 13–24. These are the capabilities that separate ProspectIQ from anything else in the market for the manufacturing ICP.*

| # | Item | Layer | What to Build | Files / Location | Effort |
|---|---|---|---|---|---|
| 3.1 | **Brunson story arc sequence variant** | Outreach Engine | New email sequence template variant in `config/sequences.yaml`: `email_story_followup`. Structure: Character (a manufacturer like them) → Wall (the problem they faced) → Epiphany (what changed) → Transformation (measurable outcome) → soft CTA. Used as alternative angle for prospects who haven't responded to value-first approach after 2+ touches. | `config/sequences.yaml`, `backend/app/agents/outreach_agent.py` | 1 day |
| 3.2 | **Manufacturing-specific signal library** | Targeting | Extend signal monitor with 9 manufacturing-specific signals Beeze doesn't have: skilled trades job postings, plant expansion / CapEx press releases, ERP/CMMS upgrade RFPs, ESG mandate announcements, FDA warning letters (F&B), food safety audit failures, ISO/AS9100 certification drives, competitor contract wins, post-M&A plant consolidation. Each signal has a detection method, weight adjustment, and outreach angle. | `backend/app/agents/signal_monitor.py`, `config/signal_weights.yaml` | 2 days |
| 3.3 | **Cross-channel email + LinkedIn coordination** | Outreach Engine | Sequence orchestrator coordinates email and LinkedIn at the company level — not independently. If prospect receives email on Day 1, LinkedIn connection request queues for Day 3. If email gets a positive reply, LinkedIn outreach pauses. Prevents the same prospect receiving uncoordinated touches from both channels simultaneously. | `backend/app/agents/sequence_orchestrator.py` | 3 days |
| 3.4 | **Content agent: pillar-based calendar** | Content | Restructure content agent output: 1× long-form post (800–1,200 words, data-driven insight) per week → 3–4 short derived posts + 1 engagement question + 1 contrarian take. Same Claude API spend, more coherent narrative thread through the content calendar. Add `example_posts[]` (curated high-performing manufacturing posts) as few-shot examples in prompt. | `backend/app/agents/content_agent.py`, `config/content_guidelines.yaml` | 1 day |
| 3.5 | **Salesforce CRM sync** | Infrastructure | Extend HubSpot integration pattern to Salesforce. Same data model: companies, contacts, interactions, deal stage. OAuth + webhook. Salesforce is the dominant CRM at Scale tier ($7,500/mo) enterprise buyers. | `backend/app/integrations/salesforce.py` | 3 days |
| 3.6 | **ICP refinement from conversion data** | Learning Loop | When a company converts (meeting booked → deal won), its firmographic + signal profile reinforces PQS scoring weights for similar future prospects. Over time, scoring self-calibrates from real outcomes — not just initial config. Requires `ml_feedback` table and periodic reweighting job. | `backend/app/core/scoring.py`, `backend/app/agents/learning_agent.py` | 3 days |
| 3.7 | **"Ask ProspectIQ" company Q&A** | Product Surface | Chat interface: user types "What do we know about Douglas Dynamics?" → RAG over `research_intelligence` + `interactions` tables → summarized answer. Lays groundwork for full ARIA-style conversational access to the prospect database. Low priority but high user experience leverage for the daily active user. | `dashboard/app/`, `backend/app/api/routes/chat.py` | 2 days |
| 3.8 | **SAML/SSO for enterprise** | Infrastructure | Supabase enterprise auth for Scale tier ($7,500/mo) accounts. Required by enterprise security requirements. Defer until first enterprise prospect asks for it. | Supabase enterprise auth configuration | P3 — on demand |

**Phase 3 total: 15 days** *(3.8 deferred until demand)*

---

## Consolidated Priority View

### By Priority Tier

**P0 — Launch blocked without these (11 days)**
- Stripe billing live
- RBAC enforcement
- Supabase RLS
- LinkedIn automation (Unipile)
- Audit log population

**P1 — Required for credible commercial product (13 days)**
- Awareness stage classifier + outreach variants
- Seller offer context
- Pre-send filter
- Cost per meeting dashboard
- Model tiering
- Google OAuth + 2FA
- Sentry + logging
- ICP onboarding wizard
- Rate limiting + API key hashing

**P2 — Competitive parity with Beeze/Clay/AI SDR tools (18 days)**
- Signal monitor agent (Perplexity-based)
- Trigify integration
- PQS temporal recalculation
- Post-meeting intelligence agent (BANT/MEDDIC included)
- HubSpot CRM sync
- Outreach quality gate
- Forbidden phrase guardrails
- Research auto-refresh
- Reply strategy variants
- Benchmark metrics display
- A/B testing with significance

**P3 — Differentiation and moat (15 days)**
- Story arc sequence variant
- Manufacturing-specific signal library (9 signals Beeze doesn't have)
- Cross-channel email + LinkedIn coordination
- Content pillar calendar
- Salesforce CRM sync
- ICP refinement from conversion data
- "Ask ProspectIQ" Q&A interface
- SAML/SSO (on demand)

---

### By Effort/Impact

| Item | Effort | Impact | Phase |
|---|---|---|---|
| LinkedIn automation (Unipile) | 4 days | Highest — closes biggest behavioral gap vs. competitors | P0 |
| Stripe billing | 3 days | Highest — revenue blocked without it | P0 |
| ICP onboarding wizard | 3 days | High — removes non-technical barrier to first use | P1 |
| HubSpot CRM sync | 5 days | High — every paying customer will ask for this | P2 |
| Post-meeting intelligence | 2 days | High — extends coverage from outreach to close | P2 |
| Signal monitor agent | 3 days | High — closes static vs. live signal gap | P2 |
| Awareness classifier + variants | 2 days | High — most leverage on reply rate | P1 |
| Model tiering | 1 day | High — 60% cost reduction, funds growth | P1 |
| Pre-send filter | 1 day | High — 30–40% cost reduction per batch | P1 |
| Seller offer context | 1 day | High — closes personalization gap immediately | P1 |
| RBAC + RLS | 3 days | Critical — security required for launch | P0 |
| Trigify integration | 1 day | High — real-time competitor engagement signal | P2 |
| Cost per meeting dashboard | 1 day | High — north star metric for operators | P1 |
| Outreach quality gate | 1 day | Medium — incremental quality improvement | P2 |
| Manufacturing signal library | 2 days | Medium — differentiates from Beeze on domain depth | P3 |
| Cross-channel coordination | 3 days | Medium — nice-to-have coherence | P3 |
| ICP refinement from conversions | 3 days | Medium — long-term intelligence loop | P3 |
| Salesforce sync | 3 days | Medium — Scale tier requirement | P3 |
| A/B significance tracking | 1 day | Medium — analytics depth | P2 |
| Sentry + logging | 1 day | High — operations visibility | P1 |

---

## Recommended Sequencing

### Weeks 1–2: Unlock Revenue
Complete all P0 items. At the end of week 2, ProspectIQ can accept its first paying customer: billing works, RBAC is enforced, data is isolated, LinkedIn sends automatically.

### Weeks 3–4: Make It Good
Complete P1 items. By end of week 4: non-technical users can onboard in 15 minutes, every message knows what it's selling, costs are tiered correctly, operators can see their ROI, and the product is observable in production.

### Weeks 5–10: Match the Market
Complete P2 items. By end of week 10: real-time signal detection, post-meeting coverage, HubSpot sync, quality gates, and benchmarked analytics. ProspectIQ now matches Beeze's automation depth and exceeds it on intelligence.

### Weeks 11–24: Build the Moat
Complete P3 items. These are the capabilities no competitor can replicate quickly: manufacturing-specific signal library, cross-channel coordination, ICP self-calibration from outcome data. The product earns its $3,500–$7,500/mo positioning.

---

*Copyright 2026 Digitillis. All rights reserved. Author: Avanish Mehrotra*
