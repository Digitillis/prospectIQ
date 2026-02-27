# ProspectIQ — Session Insights

Extracted from all previous Claude sessions on this repository.

---

## What Was Built

**ProspectIQ** is an AI-powered sales intelligence and outreach automation system built for **Digitillis**, a predictive maintenance / manufacturing AI platform. The goal: automate end-to-end prospecting into mid-market Midwest discrete manufacturers.

**Stack:** Python 3.11 + FastAPI (backend), Next.js 15 + React 19 (frontend), Supabase/PostgreSQL (database), Railway (backend hosting), Vercel (frontend hosting).

---

## Architecture

```
prospectIQ/
├── backend/          # Python FastAPI + 7 AI Agents
├── dashboard/        # Next.js 15 frontend (5 pages)
├── config/           # YAML-driven configuration (ICP, scoring, sequences, ontology)
├── supabase/         # PostgreSQL schema + migrations
└── Procfile          # Railway deployment
```

---

## The 7 AI Agents

| Agent | What It Does | LLM Calls |
|---|---|---|
| **Discovery** | Apollo.io people search → insert companies + contacts | None (pure API) |
| **Research** | Perplexity web research → Claude structured analysis | 2/company |
| **Qualification** | PQS rule-based scoring (0–100 scale) | None |
| **Outreach** | Claude-generated personalized email drafts | 1/message |
| **Engagement** | Instantly.ai orchestration + follow-up scheduling | None |
| **Reply** | Claude Haiku reply classification + response drafts | 1/reply |
| **Learning** | Analytics and outcome tracking for feedback loop | None |

### Agent Pipeline Flow

```
Discovery → Research → Qualification → Outreach (draft) → Human Approval
→ Engagement (send) → Reply handling → Learning outcomes
```

---

## ICP (Ideal Customer Profile)

**Target:** Midwest US Discrete Manufacturers

- **Revenue:** $500M–$8B
- **Employees:** 500–20,000
- **States:** IL, IN, MI, OH, WI, MN, IA, MO

### Industry Tiers (NAICS-based)

| Tier | Industry | NAICS |
|---|---|---|
| 1a | Industrial Machinery & Heavy Equipment | 333 |
| 1b | Automotive Parts & Components | 336 |
| 2 | Metal Fabrication & Precision Machining | 332 |
| 3 | Plastics & Injection Molding | 326 |
| 4 | Electronics Assembly & Semiconductor | 334 |
| 5 | Aerospace Components | 3364 |

### Target Contacts (Persona Priority Order)

1. `vp_ops` — VP Operations, VP Manufacturing, VP Engineering (priority 100)
2. `coo` — Chief Operating Officer (priority 95)
3. `plant_manager` — Plant Manager, General Manager (priority 90)
4. `digital_transformation` — Digital Transformation, Industry 4.0 roles (priority 85)
5. `vp_supply_chain` — VP Supply Chain (priority 80)
6. `director_ops` — Director of Operations/Manufacturing/Engineering (priority 75)
7. `cio` — CIO, CTO (priority 70)

**Excluded:** Marketing, Sales, HR, Finance, Legal, Accounting

---

## PQS Scoring Framework (0–100)

Four dimensions, max 25 pts each:

### Dimension 1: Firmographic (from Apollo data)
| Signal | Points |
|---|---|
| Discrete manufacturing (has NAICS tier) | 5 |
| Revenue $500M–$8B | 5 |
| Midwest US HQ | 5 |
| Employee count 500–20K | 3 |
| Private company | 3 |
| Multi-plant/facility signals | 4 |

### Dimension 2: Technographic (keyword-matched from research)
| Signal | Points |
|---|---|
| Legacy CMMS/APM present (Maximo, UpKeep, Fiix…) | 5 |
| IoT infrastructure mentioned | 5 |
| ERP in place (SAP, Oracle, Epicor, Infor, Plex…) | 4 |
| Industrial protocols (OPC-UA, MQTT, Modbus, PLC) | 4 |
| No existing AI/ML competitors | 4 |
| Industry 4.0 initiative mentioned | 3 |

### Dimension 3: Timing & Pain Signals (keyword-matched from research)
| Signal | Points |
|---|---|
| Recently hired digital transformation role | 5 |
| Unplanned downtime mentioned | 5 |
| Recent capex / plant expansion | 4 |
| Sustainability mandate | 3 |
| Quality issues mentioned | 3 |
| Workforce/retirement challenges | 3 |
| Recent M&A | 2 |

### Dimension 4: Engagement (from webhook events)
| Stage | Points |
|---|---|
| Cold | 0 |
| Delivered | 2 |
| Opened | 5 |
| Engaged (clicked) | 10 |
| Interested (replied) | 15 |
| Evaluating | 20 |
| Committed | 25 |

### PQS Thresholds
| Score | Classification | Status |
|---|---|---|
| 0–29 | Unqualified | `disqualified` |
| 30–45 | Research Needed | (flagged for review) |
| 46–69 | Qualified | `qualified` |
| 70–84 | High Priority | `qualified` + `priority_flag=true` |
| 85–100 | Hot Prospect | `qualified` + `priority_flag=true` |

**Minimum firmographic score for research:** 10 pts (companies below this skip research)

---

## Company Lifecycle (Status State Machine)

```
discovered
    → researched
        → qualified
        → disqualified
    qualified
        → outreach_pending
            → contacted
                → engaged
                    → meeting_scheduled
                        → pilot_discussion
                            → pilot_signed
                                → active_pilot
                                    → converted
(any state) → not_interested | paused | bounced
```

---

## Integrations

| Service | Use Case | Cost Model |
|---|---|---|
| Apollo.io | People + company search by ICP | Free (people search), credits for enrichment |
| Perplexity sonar-pro | Web-grounded company research | ~$3/$15 per 1M tokens |
| Claude Sonnet | Research analysis + outreach generation | ~$3/$15 per 1M tokens |
| Claude Haiku | Reply classification | ~$0.80/$4 per 1M tokens |
| Instantly.ai | Cold email delivery + sequence orchestration | SaaS subscription |
| Resend | Internal/transactional emails only (not cold outreach) | Per-email |
| Supabase | All data persistence | DB hosting |

---

## Database Schema (8 Tables)

### companies (51 fields)
Core company record + all enriched intelligence:
- Firmographic: `name`, `domain`, `industry`, `naics_code`, `tier`, `employee_count`, `estimated_revenue`, `state`, `territory`
- AI-enriched: `research_summary`, `technology_stack` (JSONB), `pain_signals` (JSONB), `manufacturing_profile` (JSONB), `personalization_hooks` (JSONB)
- PQS: `pqs_total`, `pqs_firmographic`, `pqs_technographic`, `pqs_timing`, `pqs_engagement`
- Lifecycle: `status`, `status_changed_at`, `priority_flag`
- Tracking: `campaign_name`, `batch_id`

### contacts (22 fields)
People at each company:
- `persona_type`, `is_decision_maker`, `seniority`
- `email`, `linkedin_url`, `title`
- FK → `companies(id)`

### research_intelligence (22 fields)
Structured output from Perplexity + Claude:
- Raw: `perplexity_response`, `claude_analysis`
- Structured: `manufacturing_type`, `equipment_types`, `known_systems`, `iot_maturity`, `maintenance_approach`
- Intelligence: `pain_points`, `opportunities`, `existing_solutions`, `funding_status`
- Quality: `confidence_level` (high/medium/low)

### outreach_drafts (15 fields)
AI-generated messages with approval workflow:
- `approval_status`: pending → approved | rejected | edited
- `subject`, `body`, `personalization_notes`
- Sending: `sent_at`, `instantly_lead_id`, `instantly_campaign_id`

### interactions (11 fields — immutable event log)
All prospect touchpoints:
- Types: `email_sent`, `email_opened`, `email_clicked`, `email_replied`, `email_bounced`, `linkedin_connection`, `linkedin_message`, `phone_call`, `meeting`, `note`, `status_change`
- Sources: `instantly_webhook`, `manual`, `apollo`, `system`

### engagement_sequences (11 fields)
Per-company/contact sequence state machine:
- `current_step`, `next_action_at`, `next_action_type`
- Status: `active` | `paused` | `completed` | `cancelled`

### api_costs (10 fields)
Every API call logged:
- `provider`, `model`, `endpoint`, `input_tokens`, `output_tokens`, `estimated_cost_usd`
- Linked to `company_id` and `batch_id` for ROI analysis

### learning_outcomes (10 fields)
Outreach approach → outcome tracking:
- `outreach_approach`, `channel`, `message_theme`, `personalization_level`
- `outcome`: opened | replied_positive | replied_negative | no_response | meeting_booked
- Context: `company_tier`, `persona_type`, `pqs_at_time`

---

## Configuration Files (YAML-driven)

Everything is version-controlled YAML — no hardcoded business logic.

### config/icp.yaml
Defines target market, Apollo search filters, persona classification rules, discovery batch settings.

### config/scoring.yaml
Full PQS framework: dimension definitions, signal keywords, point values, thresholds, classification labels.

### config/sequences.yaml
Multi-stage engagement sequences:
- **initial_outreach** (5 steps, 10 days): Email → LinkedIn → Email × 3
- **warm_follow_up** (3 steps, 7 days): For opens without reply
- **reply_positive** (2 steps): For interested replies → meeting booking

Global principles: peer-to-peer tone, manufacturing language (OEE, MTBF, RUL), no manipulation tactics, single CTA per message.

### config/manufacturing_ontology.yaml
Deep domain knowledge:
- NAICS sub-sector mapping with equipment types and Digitillis fit rating
- Technology systems catalog (30+ ERP/CMMS/SCADA/MES/PLC systems)
- AI/ML competitor list with differentiation notes
- Value messaging by tier (primary pains, value hooks, opener angles)
- Territory mapping: state → sales territory

---

## FastAPI Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/companies` | List with filters (status, tier, min_pqs, limit, offset) |
| GET | `/api/companies/{id}` | Detail + contacts + research + 20 recent interactions |
| PATCH | `/api/companies/{id}` | Update fields |
| POST | `/api/companies/{id}/interactions` | Log note or status change |
| GET | `/api/approvals` | Pending outreach drafts |
| POST | `/api/approvals/{id}/approve` | Approve (optionally edit body) |
| POST | `/api/approvals/{id}/reject` | Reject with reason |
| POST | `/api/pipeline/run/{agent}` | Execute an agent (discovery/research/qualification/outreach/engagement/reply) |
| GET | `/api/analytics/pipeline` | Company counts by status |
| GET | `/api/analytics/costs` | API costs by provider and batch |
| GET | `/api/analytics/learning` | Learning outcome aggregates |
| POST | `/api/webhooks/instantly` | Instantly.ai event handler |

---

## Frontend Dashboard Pages (Next.js 15)

| Page | Route | Purpose |
|---|---|---|
| Pipeline | `/` | Kanban board — company cards by lifecycle stage |
| Prospects | `/prospects` | Filterable/sortable list of all companies |
| Prospect Detail | `/prospects/[id]` | Full profile: PQS, research intel, contacts, interaction history, add note |
| Approvals | `/approvals` | Review/edit/approve outreach drafts before sending |
| Analytics | `/analytics` | Pipeline funnel, PQS distribution, API costs, learning outcomes |
| Actions | `/actions` | Active sequences with next_action_at and due date countdown |

---

## Key Technical Decisions

### 1. Python 3.9 Compatibility Fix
Added `from __future__ import annotations` to all 18 backend Python files. However, FastAPI route parameters still need `Optional[str]` (not `str | None`) because FastAPI evaluates route annotations at runtime — future annotations don't help there.

### 2. Config Patching in get_settings()
If an environment variable exists in the shell but is empty (`ANTHROPIC_API_KEY=""`), Python's `os.environ` overrides `.env` file values. Fixed by re-reading `.env` with `dotenv_values()` and patching any fields where the env var was empty but the file had a value.

### 3. YAML-Driven Business Logic
ICP, scoring rules, sequences, and manufacturing ontology are all in version-controlled YAML files. Non-technical users can update targeting, scoring thresholds, or message templates without code changes.

### 4. Cost Tracking at Every Agent Call
Every external API call (Anthropic, Perplexity, Apollo, Instantly) is logged to `api_costs` with token counts and estimated USD cost, linked to `company_id` and `batch_id` for per-prospect ROI analysis.

### 5. Rule-Based Qualification (No LLM)
The qualification agent uses keyword matching against research text for all 4 PQS dimensions. This makes it fast, transparent, and auditable — no LLM black-box in scoring decisions.

### 6. Human-in-the-Loop Approval
All outreach drafts go through an approval workflow (pending → approved/rejected/edited) before Instantly.ai delivers them. This prevents bad outreach and maintains Avi's voice.

### 7. Deterministic Territory Mapping
States deterministically map to sales territories via the manufacturing ontology YAML — consistent for routing and regional analytics.

---

## Deployment

### Backend — Railway
```
Procfile: web: pip install -r backend/requirements.txt && uvicorn backend.app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
```
- Python 3.11.9 (`runtime.txt`)
- Environment variables set in Railway dashboard

### Frontend — Vercel
- `vercel.json` rewrites `/api/*` → Railway backend URL
- Security headers: HSTS, CSP, X-Content-Type-Options, X-Frame-Options
- Environment: `NEXT_PUBLIC_API_URL` for the API client
- Digitillis brand: primary blue palette, Inter font, slide animations from Digitillis platform

---

## Digitillis Product Details (Used in Outreach)

- **32 specialized AI agents** across 7 manufacturing domains
- **Predictive maintenance:** 18+ day advance failure warning at 87% confidence
- **Anomaly detection:** across 100+ sensors
- **35+ production ML models**, 847ms avg response time
- **OEE analytics, quality defect prediction, energy optimization, ESG reporting**
- **ARIA:** Conversational AI copilot for plant floor
- **Pilot:** 6–8 weeks, no long-term commitment
- **Founder:** Avi, Co-Founder & MD — `avi@digitillis.com`

---

## AI/ML Competitors Tracked

| Category | Competitors |
|---|---|
| Direct | Uptake, SparkCognition, Augury, Senseye (Siemens) |
| Partial | C3.ai, Sight Machine, MachineMetrics, Falkonry |

**Digitillis differentiators:** 32 agents vs generic platforms, explainable AI with evidence packages, multi-protocol integration, ROI quantification, faster deployment.

---

## Value Messaging by Tier

| Tier | Primary Pains | Value Hook |
|---|---|---|
| 1a (Machinery) | Unplanned downtime ($10K–100K+/hr), retiring workforce, reactive maintenance (60%+ budget) | Predict failures 18+ days out |
| 1b (Automotive) | Zero-defect mandates, JIT pressure, traceability requirements | Defect prediction + quality analytics |
| 2 (Metal Fab) | Machine utilization <65%, tool wear, scrap rates | OEE uplift + tool life prediction |
| 3 (Plastics) | Process drift, mold maintenance, energy costs | Condition-based maintenance + energy optimization |
| 4 (Electronics) | First-pass yield, SMT accuracy, reflow optimization | Quality ML models |
| 5 (Aerospace) | AS9100 compliance, NDT bottlenecks, zero scrap tolerance | Compliance + NDT scheduling |

---

## Codebase Size

| Component | Lines |
|---|---|
| Python backend (agents + API + integrations + core) | ~4,910 |
| TypeScript frontend (5 pages + lib) | ~1,376 |
| SQL schema | ~407 |
| YAML config | ~975 |
| **Total** | **~7,668** |

---

## Environment Variables Required

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key

# Anthropic (Claude)
ANTHROPIC_API_KEY=your-anthropic-api-key

# Perplexity
PERPLEXITY_API_KEY=your-perplexity-api-key

# Apollo.io
APOLLO_API_KEY=your-apollo-api-key

# Instantly.ai
INSTANTLY_API_KEY=your-instantly-api-key

# Resend
RESEND_API_KEY=your-resend-api-key

# Webhook verification
WEBHOOK_SECRET=your-webhook-secret

# App settings
LOG_LEVEL=INFO
BATCH_SIZE=10
```

---

## Open Items / Next Steps

Based on the architecture, logical next steps are:

1. **Connect real API keys** and run the first discovery batch against the live ICP
2. **Tune PQS thresholds** after seeing actual pipeline data (current thresholds are assumptions)
3. **LinkedIn outreach** — sequences.yaml already has LinkedIn steps but Instantly.ai is email-only; would need a separate LinkedIn automation tool
4. **Learning loop activation** — `learning_outcomes` table is populated but no automated feedback to prompt tuning yet
5. **Instantly.ai webhook** — needs the Railway URL configured in Instantly dashboard to start receiving open/click/reply events and drive `pqs_engagement` scoring (Hyper Growth plan required; polling fallback now available via `POST /api/pipeline/run/poll-instantly`)
6. **Supabase RLS policies** — schema has no Row Level Security configured; should add before any multi-user access
7. **Rate limiting on API** — FastAPI currently has no rate limiting; should add before exposing to production

---

## TODO: Multi-Sector Configuration Page

**Idea:** Add a UI configuration page to ProspectIQ so the same system can serve different industries, geographies, and company profiles without code changes.

**Why it has merit:**
- All business logic is already YAML-driven (`icp.yaml`, `scoring.yaml`, `sequences.yaml`, `manufacturing_ontology.yaml`) — the foundation is there
- Digitillis may want to expand beyond Midwest discrete manufacturing (different verticals, geographies, or company sizes)
- A non-technical user (e.g. sales/founder) could reconfigure the system without touching code or YAML files

**What the config page would cover:**

| Section | Fields |
|---|---|
| **Target Industries** | Industry categories, NAICS codes, sub-sectors, priority tiers |
| **Geography** | Target states/regions, territory mapping |
| **Company Size** | Employee count range, revenue range |
| **Personas** | Target job titles, seniority levels, exclusion list |
| **ICP Scoring** | PQS dimension weights, threshold values (qualified/hot/disqualified) |
| **Sequences** | Steps, delay days, channels (email/LinkedIn), per-step instructions |
| **Value Messaging** | Pain points and value hooks per tier |
| **Sender Identity** | Sender email, founder name, product description for outreach prompts |

**Implementation approach when ready:**
- Backend: CRUD API endpoints that read/write the YAML config files (or migrate config to Supabase for easier editing)
- Frontend: New `/config` dashboard page with tabbed sections per config area
- Validation: Schema validation before saving (prevent broken configs going live)
- Versioning: Keep a history of config changes so rollback is possible
