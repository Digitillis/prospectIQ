# ProspectIQ — Operating Manual

> **Version**: 1.0
> **Last Updated**: 2026-03-22
> **Owner**: Avanish Mehrotra

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Daily Operating Rhythm](#daily-operating-rhythm)
3. [Pipeline Workflow (Step-by-Step)](#pipeline-workflow)
4. [Channel Strategy](#channel-strategy)
5. [Message Quality Standards](#message-quality-standards)
6. [Cross-Channel Coordination Rules](#cross-channel-coordination-rules)
7. [Thought Leadership Content System](#thought-leadership-content-system)
8. [Contact Event Thread System](#contact-event-thread-system)
9. [Scoring & Qualification Logic](#scoring--qualification-logic)
10. [Configuration Files](#configuration-files)
11. [Troubleshooting](#troubleshooting)
12. [Cost Tracking](#cost-tracking)
13. [Key Decisions & Rationale](#key-decisions--rationale)
14. [URLs & Access](#urls--access)

---

## System Overview

ProspectIQ is an AI-powered sales intelligence and outreach system for Digitillis. It automates prospect discovery, research, qualification, and message generation while keeping the founder in control of every outreach touch.

### Architecture

```
Apollo.io (discovery) → Perplexity (research) → Claude (analysis + messages)
     ↓                        ↓                         ↓
  Supabase DB ←──────────────────────────────────→ Dashboard (Next.js)
     ↓                                                   ↓
  Instantly.ai (email delivery)              LinkedIn (manual copy-paste)
```

### The 7+2 Agents

| Agent | What It Does | LLM | Cost/Company |
|---|---|---|---|
| **Discovery** | Apollo People Search → companies + contacts | None | Free |
| **Research** | Perplexity web research → Claude structured analysis | 2 calls | ~$0.05 |
| **Qualification** | PQS rule-based scoring (0-100 scale) | None | Free |
| **Enrichment** | Apollo People Match → verified emails | None | Free (API credits) |
| **Outreach** | Claude-generated personalized email drafts | 1 call | ~$0.02 |
| **LinkedIn** | Claude-generated connection notes + DMs | 1 call | ~$0.01 |
| **Engagement** | Instantly.ai delivery + sequence orchestration | None | Free |
| **Content** | Claude-generated thought leadership posts | 1 call | ~$0.05 |
| **Re-engagement** | Re-queue stale prospects after 90-day cooldown | None | Free |

### Dashboard Pages

| Page | URL | Purpose |
|---|---|---|
| **Today** | /today | Daily command center — everything you need to do |
| **Pipeline** | / | Bird's-eye view of prospect pipeline |
| **Actions** | /actions | Run pipeline agents with filters |
| **Approvals** | /approvals | Review/approve email drafts before sending |
| **LinkedIn** | /linkedin | LinkedIn messages with copy-paste + Intel |
| **Content** | /content | Thought leadership calendar + generator |
| **Contacts** | /contacts | Contact directory + detail pages |
| **Prospects** | /prospects | Filterable/sortable company list |
| **Analytics** | /analytics | Pipeline funnel, costs, learning outcomes |
| **Settings** | /settings | ICP, scoring, outreach/content/LinkedIn guidelines |

---

## Daily Operating Rhythm

### Morning Routine (15-20 minutes)

1. **Open https://crm.digitillis.com/today**
2. **Respond Now** — handle any hot signals or replies first
3. **AI-Recommended Actions** — execute suggested follow-ups with pre-written messages
4. **Send LinkedIn Connections** — copy 10 messages, paste into LinkedIn, mark as sent
5. **Send LinkedIn DMs** — copy DMs for accepted connections, paste, mark done
6. **Approve Emails** — review pending email drafts, approve or edit
7. **Post Content** — copy today's thought leadership post to LinkedIn
8. **Log Outcomes** — record any responses from yesterday
9. **Pipeline** — run research/qualification on new batches if needed

### Target: 20 actions/day

| Action | Daily Target |
|---|---|
| LinkedIn connection requests | 10 (5 F&B + 5 Mfg) |
| LinkedIn DMs | 5 |
| Email approvals | 3 |
| Outcome logs | 2 |
| Content posts | 1 |

---

## Pipeline Workflow

### Step-by-Step Process

```
Step 1: DISCOVERY
  Action: Actions page → Run Discovery
  Settings: Select tiers (fb1-fb3 for F&B, mfg1-mfg3 for Mfg)
            Limit: 100, Max Pages: 2
            Campaign: descriptive name (e.g., "fb_wave2")
  Result: ~200-250 companies added with contacts
  Cost: Free (Apollo People Search)

Step 2: RESEARCH
  Action: Actions page → Run Research
  Settings: Limit: 20, Status: Any
  Result: Deep company profiles via Perplexity + Claude
  Cost: ~$0.05/company ($1 for 20)
  Note: Research agent picks highest-PQS companies first

Step 3: QUALIFICATION
  Action: Actions page → Run Qualification
  Settings: Limit: 100
  Result: Companies scored 0-100 on PQS (4 dimensions)
  Cost: Free (rule-based keyword matching)
  Note: Run on "researched" status first, they get full 4-dimension scoring

Step 4: ENRICHMENT
  Action: Actions page → Run Enrichment
  Settings: Limit: 20
  Result: Verified emails + phone numbers via Apollo People Match
  Cost: Free (Apollo API credits)
  Note: Only enriches contacts at "qualified" companies

Step 5: LINKEDIN MESSAGES
  Action: LinkedIn page → Generate Messages
  Settings: Limit: 20
  Result: 3 personalized messages per contact (connection note + 2 DMs)
  Cost: ~$0.01/contact ($0.20 for 20)

Step 6: OUTREACH (email drafts)
  Action: Actions page → Run Outreach
  Settings: Limit: 20, Sequence: linkedin_to_email_fallback or email_value_first
  Result: Personalized email drafts pending approval
  Cost: ~$0.02/draft ($0.40 for 20)

Step 7: APPROVAL
  Action: Approvals page → review each draft
  Options: Approve, Edit, Reject, Send Test to Me
  Note: Nothing sends without explicit approval

Step 8: ENGAGEMENT (email sending)
  Action: Actions page → Run Engagement (only after email warmup complete)
  Result: Approved drafts delivered via Instantly.ai
  Note: Start with 10-15/day, ramp to 30-50/day
```

### Batch Cadence

| Frequency | Action |
|---|---|
| Weekly | Run Discovery (100 per vertical, 2 batches) |
| Weekly | Run Research on top 20-30 discovered |
| After research | Run Qualification on all researched |
| After qualification | Run Enrichment on top 20 qualified |
| After enrichment | Generate LinkedIn messages |
| Daily | Review/approve outreach drafts |
| Daily | Send approved via engagement agent |

---

## Channel Strategy

### LinkedIn-First Approach

LinkedIn is the primary channel. Email is the fallback.

**Why LinkedIn first:**
- Warmer than cold email (social connection vs. inbox intrusion)
- Connection acceptance = permission signal
- Profile views reveal interest before you even reach out
- Thought leadership posts build credibility passively
- No warmup period needed

### Channel Assignment Logic

| Scenario | Channel | Why |
|---|---|---|
| Has LinkedIn URL, VP/C-suite | LinkedIn first | Executives are active on LinkedIn |
| Has LinkedIn URL, Director/Manager at small company | Email first | Mid-level prefers email |
| No LinkedIn URL | Email only | Only option |
| LinkedIn ignored after 14 days | Switch to email | Different angle, fresh start |
| LinkedIn accepted + DM responded | Stay on LinkedIn | Don't switch channels mid-conversation |
| Email sequence completed | Never return to LinkedIn | Would feel stalky |

### Sequence Structure

**3 separate single-channel sequences (never blended):**

1. **linkedin_relationship** (5 steps, LinkedIn only):
   - Step 1: Connection note (Day 0) — reference one company fact, no pitch
   - Step 2: Opening DM (Day 3-5 after acceptance) — genuine question
   - Step 3: Value share (Day 7-10) — industry insight or framework
   - Step 4: Relevance (Day 10-14) — how similar companies solve this
   - Step 5: Soft ask (Day 14-21) — 15-min call offer

2. **email_value_first** (4 steps, email only):
   - Step 1: Value insight (Day 0) — lead with data, not pitch
   - Step 2: Case relevance (Day 5-7) — similar company outcome
   - Step 3: Framework share (Day 8-12) — actionable tool they can use
   - Step 4: Direct ask (Day 12-16) — binary offer, easy to say yes/no

3. **linkedin_to_email_fallback** (3 steps, email only):
   - Triggered after 14 days of LinkedIn silence
   - Different angle than LinkedIn (if LI was compliance, email is cost)
   - Never reference LinkedIn in the email

---

## Message Quality Standards

### The 3 Levels of Personalization

| Level | Quality | Example |
|---|---|---|
| **Level 1 (REJECTED)** | Generic | "I noticed you work at Parker Hannifin." |
| **Level 2 (Acceptable)** | Company-aware | "I saw Parker Hannifin makes hydraulic systems." |
| **Level 3 (REQUIRED)** | Expert-level | "I have been following Parker Hannifin's $9.25 billion Filtration Group acquisition. That scale of integration across hydraulics, pneumatics, and filtration creates fascinating operational challenges." |

### Writing Style Rules (Avanish's Voice)

- Always use first person explicitly: "I saw", "I am curious", "I have been" — never "Saw...", "Curious..."
- Use "I am" not "I'm" in connection notes (more professional first touch)
- Contractions OK in DMs (more conversational)
- No em dashes (—) anywhere. Use commas or periods.
- No sentence fragments. Every sentence must have a subject and verb.
- Short sentences. Vary length. Not corporate.

### Closing Rules by Stage

| Stage | Closing Approach | Example |
|---|---|---|
| Connection note | NO closing CTA. Content IS the close. | End with statement or observation. |
| Opening DM | Question IS the close. | "...or if it is still mostly run-to-failure?" |
| Follow-up DM | One soft door-opening sentence. | "Happy to share the framework if useful." |
| Email step 1-3 | Low-friction question, not meeting request. | "I am curious if that matches your experience." |
| Email step 4 | Binary ask. Easy yes or no. | "Would a 15-minute walkthrough be worth your time?" |

### Banned Phrases

- "I hope this finds you well"
- "Would love to connect" (without specific reason)
- "Share some ideas" (vague)
- "Just following up" / "Circling back"
- "I noticed you work at [company]" (obvious)
- "Game-changing" / "Cutting-edge" / "Revolutionary"
- Any em dashes (—)
- "Curious about..." (fragment — use "I am curious about...")

### Signature Block

```
Avanish Mehrotra
Founder & CEO
Digitillis | www.digitillis.com
avi@digitillis.com | 224.355.4500
```

---

## Cross-Channel Coordination Rules

### The 5 Rules

1. **One channel at a time per contact.** Never email AND LinkedIn in the same 14-day window.
2. **LinkedIn goes first** when both channels are available (warmer).
3. **14-day company lock.** When any contact at a company receives outreach, the entire company is locked for 14 days. Prevents two VPs comparing notes.
4. **48-hour activity check.** Before any send, check for activity in the last 48 hours across ALL channels. If found, delay 3 days.
5. **Never switch back.** Email sequence complete → never return to LinkedIn for that contact.

### Cooldown Periods

| Event | Next Channel Available |
|---|---|
| LinkedIn connection sent | Email blocked for 7 days |
| LinkedIn DM sequence complete, no response | Email after 14 days |
| Email sequence complete | LinkedIn never (permanently blocked) |
| Company-level outreach sent | Same company blocked for 14 days |

---

## Thought Leadership Content System

### Content Philosophy

McKinsey-grade insights. Zero product pitching. Pure value. The content earns the right to have a conversation.

### 4 Pillars (Rotating Weekly)

1. **Food Safety & Compliance** — FSMA, HACCP, FDA 483 patterns, audit readiness
2. **Predictive Maintenance & Reliability** — OEE, downtime costs, maintenance maturity
3. **Operations Excellence** — Industry 4.0 reality, digital transformation ROI
4. **Leadership & Strategy** — Data culture, capex frameworks, succession planning

### 4 Formats

1. **Data Insight** — Hook stat → Context → "So what?" → Question (800-1300 chars)
2. **Framework** — Name it → Visual → Explain quadrants → "Where do you fall?" (1000-1500 chars)
3. **Contrarian** — Conventional wisdom → Why it's wrong → Better frame (600-1000 chars)
4. **Benchmark** — "We analyzed X" → Key findings → Implications (1200-1500 chars)

### Auto-Generate 4-Week Calendar

One-click button at /content generates 16 posts (4/week x 4 weeks). Balanced rotation: never same pillar two days in a row, every pillar 4x/month, every format used 4 times.

Post schedule: Monday, Tuesday, Thursday, Friday.

### Quality Rules

- Lead with specific data, not opinion
- No mention of Digitillis, AI platforms, or any product
- No hashtags (reduce LinkedIn reach)
- Under 1300 characters (LinkedIn truncates)
- End with a question to drive comments
- No em dashes, no "moreover", no AI tells
- Source attribution on every data point

---

## Contact Event Thread System

### Purpose

Chronological timeline of every interaction per contact. Single source of truth for each relationship.

### Event Types

| Type | Direction | What It Records |
|---|---|---|
| outreach_sent | outbound | LinkedIn message or email sent |
| response_received | inbound | Their reply (paste the actual message) |
| connection_accepted | inbound | LinkedIn connection accepted |
| note_added | internal | Your context notes about the contact |
| meeting_scheduled | internal | Meeting booked with date/time |
| meeting_held | internal | Meeting outcome and next steps |
| email_opened | inbound | Email open detected |
| link_clicked | inbound | Email link click detected |
| status_change | internal | Company/contact status updated |

### AI-Powered Next Actions

When you log an inbound event (paste a reply), Claude analyzes:
1. **Sentiment**: positive / neutral / negative
2. **Intent signals**: what the prospect cares about
3. **Next action**: specific recommendation with suggested message
4. **Timing**: when to follow up (respects sequence timing rules)

Cost: ~$0.01-0.02 per analysis.

### How to Log Events

1. From the Contact Detail page (/contacts/[id]) — "Add Event" form
2. From the Today page — outcome logging section
3. Automatic: system creates events when you Mark Sent, approve drafts, etc.

---

## Scoring & Qualification Logic

### PQS Framework (Prospect Quality Score, 0-100)

4 dimensions, 0-25 points each:

| Dimension | Source | Max | Key Signals |
|---|---|---|---|
| **Firmographic** | Apollo data | 25 | Manufacturing/F&B (5), revenue $50-200M (5), US-based (3), employees 50-500 (3), food production NAICS 311/312 (5), private (+4), independent (+3) |
| **Technographic** | Research | 25 | Legacy CMMS (5), IoT infrastructure (5), ERP in place (4), industrial protocols (4), no existing AI (4), Industry 4.0 initiative (3) |
| **Timing** | Research | 25 | FSMA compliance pressure (5), downtime mentioned (5), new digital role (5), recent capex (4), recall risk (4), workforce challenges (3), headcount growth >10% (+5) |
| **Engagement** | Tracking | 25 | Cold (0), delivered (2), opened (5), engaged (10), interested (15), evaluating (20), committed (25) |

### Thresholds

| PQS Range | Classification | Action |
|---|---|---|
| 0-9 | Unqualified | Disqualified |
| 10-14 | Needs More Research | Flagged for review |
| 15-39 | Qualified | Move to outreach pipeline |
| 40-69 | High Priority | Qualified + priority flag |
| 70-100 | Hot Prospect | Qualified + priority flag + urgent |

---

## Configuration Files

All business logic is YAML-driven. Edit from Settings page or directly in files.

| File | What It Controls |
|---|---|
| `config/icp.yaml` | ICP definition — industries, revenue, geography, personas, Apollo filters |
| `config/scoring.yaml` | PQS dimensions, signals, keywords, thresholds |
| `config/sequences.yaml` | Outreach sequences — channels, timing, step instructions |
| `config/outreach_guidelines.yaml` | Email tone, voice, signature, banned phrases |
| `config/content_guidelines.yaml` | Thought leadership voice, pillars, topics, calendar |
| `config/linkedin_messages_guidelines.yaml` | LinkedIn DM rules, question templates |
| `config/manufacturing_ontology.yaml` | Industry knowledge — NAICS mapping, equipment, competitors |

**All configs read fresh on every agent run** — no caching. Edit in the Settings page, changes take effect immediately on the next run.

---

## Troubleshooting

### Common Issues

| Problem | Cause | Fix |
|---|---|---|
| Discovery: 0 processed, N errors | Missing DB column | Check error message. Run the ALTER TABLE SQL in Supabase. |
| Enrichment: 0 processed, N skipped | All contacts already have emails, or no qualified companies | Check company statuses. Run qualification first. |
| Qualification: all "needs research" | Companies not researched yet | Run Research first, then re-run Qualification. |
| LinkedIn messages: "I noticed you work at..." | Old prompts cached | Regenerate with `regenerate=true`. Check Railway has latest code. |
| Intel panel shows only "CONTACT: Title" | Backend not fetching company data | Verify the Supabase query includes all company columns. |
| Railway deployment crashed | Missing Python package | Check Railway logs for the import error. Add to requirements.txt. |
| Today page shows stale data | 30-second auto-refresh not triggered | Click Refresh manually. Check API response in browser dev tools. |

### Database Migrations

Always apply migrations in order via Supabase SQL Editor:
1. `001_initial_schema.sql` — core tables
2. `002_apollo_extended_fields.sql` — headcount growth, SIC/NAICS, parent company
3. `003_contact_events.sql` — contact event thread table

If a new field is added to `extract_company_data()` or `extract_contact_data()`, add the corresponding `ALTER TABLE` in Supabase.

---

## Cost Tracking

### Per-Agent Costs

| Agent | Cost Per Company | 100 Companies | 500 Companies |
|---|---|---|---|
| Discovery | $0.00 | $0.00 | $0.00 |
| Research | $0.05 | $5.00 | $25.00 |
| Qualification | $0.00 | $0.00 | $0.00 |
| Enrichment | $0.00 (API credits) | $0.00 | $0.00 |
| LinkedIn Messages | $0.01 | $1.00 | $5.00 |
| Outreach (email) | $0.02 | $2.00 | $10.00 |
| Content (post) | $0.05 | N/A | N/A |
| Event Analysis | $0.02 | N/A | N/A |

### Monthly Budget Estimate

| Item | Cost |
|---|---|
| Anthropic API (Claude) | ~$30-50/month |
| Perplexity API | ~$10-20/month |
| Apollo.io | Free tier (or $49/month for more credits) |
| Instantly.ai | $30-97/month (depending on plan) |
| Railway (backend hosting) | ~$5-10/month |
| Vercel (dashboard hosting) | Free |
| LinkedIn | Free (upgrade to Premium $59.99/month in month 2) |
| Supabase | Free tier |
| **Total** | **~$75-230/month** |

One pilot at $2,500-5,000/month pays for 10-60 months of ProspectIQ operations.

---

## Key Decisions & Rationale

### D1: LinkedIn-First, Email-Fallback
**Decision**: LinkedIn is the primary outreach channel. Email only when LinkedIn fails.
**Why**: LinkedIn is warmer, provides intel (profile views, shared connections), and doesn't require warmup. Cold email has lower response rates and risks sender reputation.

### D2: Single-Channel Sequences
**Decision**: Never blend LinkedIn and email in the same sequence.
**Why**: Prospects notice coordinated campaigns. Each channel should feel like an independent, genuine outreach. If LinkedIn fails, switch to email with a completely different angle.

### D3: 14-Day Company Lock
**Decision**: Only one active outreach thread per company at a time.
**Why**: Two VPs at the same company comparing notes kills trust. Better to go deep with one contact than wide across multiple.

### D4: AI-Researched Per Company (Not Templates)
**Decision**: Every message is AI-generated based on specific company research.
**Why**: ~$0.05 extra per company but produces genuinely unique insights. Impossible for prospects to tell it's automated if the research is deep enough.

### D5: F&B + Discrete Manufacturing (Not More Sectors)
**Decision**: Double down on two verticals until first pilots are signed.
**Why**: Adding sectors dilutes messaging, LinkedIn content, and partner development. Prove the sales motion works first, then expand.

### D6: LinkedIn Free Tier for Month 1
**Decision**: Start with free LinkedIn. Upgrade to Premium only if the channel converts.
**Why**: Free tier supports 10 connections/day with notes. Apollo handles search. Premium's value (profile views, InMails) is worth paying for only after proving LinkedIn works.

### D7: Level 3 Personalization Required
**Decision**: Every message must demonstrate domain expertise, not just company awareness.
**Why**: VPs get 50+ cold emails/week. "I noticed your company" is what everyone says. Referencing specific equipment, processes, or regulatory challenges signals real understanding.

### D8: Human-in-the-Loop on All Outreach
**Decision**: Nothing sends without explicit approval.
**Why**: One bad outreach email can permanently damage a prospect relationship. The quality bar is too important to automate fully.

---

## URLs & Access

| Service | URL | Credentials |
|---|---|---|
| ProspectIQ Dashboard | https://crm.digitillis.com | Login via dashboard |
| ProspectIQ API | https://prospectiq-production-4848.up.railway.app | API endpoints |
| Railway (backend) | https://railway.app (ProspectIQ project) | Railway account |
| Vercel (frontend) | https://vercel.com (ProspectIQ project) | Vercel account |
| Supabase (database) | https://supabase.com (project dashboard) | Supabase account |
| Apollo.io | https://app.apollo.io | Apollo account |
| Instantly.ai | https://app.instantly.ai | Instantly account |
| Anthropic (Claude) | https://console.anthropic.com | API key in Railway vars |
| Perplexity | https://www.perplexity.ai | API key in Railway vars |

### Environment Variables (Railway)

```
SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY
ANTHROPIC_API_KEY
PERPLEXITY_API_KEY
APOLLO_API_KEY
INSTANTLY_API_KEY
RESEND_API_KEY
WEBHOOK_SECRET
LOG_LEVEL=INFO
BATCH_SIZE=10
```

---

## ProspectIQ LOC Summary

| Component | Files | Lines |
|---|---|---|
| Python backend (agents + API + core) | 65+ | ~14,000 |
| TypeScript frontend (dashboard) | 35+ | ~18,000 |
| YAML config | 6 | ~1,500 |
| SQL schema | 3 | ~450 |
| Tests | 2 | ~2,800 |
| Documentation | 8 | ~3,000 |
| **Total** | **~120** | **~40,000** |

---

**Copyright 2026 Digitillis. All rights reserved.**
**Author: Avanish Mehrotra**
