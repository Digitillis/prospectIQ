# ProspectIQ — Strategic Intelligence & Ideation Log

> Living document. Updated continuously across sessions.
> Captures pipeline analysis, architectural critique, strategic redesign thinking, and course correction decisions.
> Most recent entry at the top of each section.

---

## Index

1. [Pipeline Status Snapshots](#pipeline-status-snapshots)
2. [Failure Analysis](#failure-analysis)
3. [Adversarial Strategic Redesign](#adversarial-strategic-redesign)
4. [Architecture Decisions & Course Corrections](#architecture-decisions--course-corrections)
5. [Signal Intelligence Backlog](#signal-intelligence-backlog)
6. [Open Questions](#open-questions)

---

## Pipeline Status Snapshots

### 2026-05-12 — Full Pipeline Status

**Discovery & Coverage**

| Layer | Count |
|---|---|
| Companies in database | 2,465 |
| Contacts (enriched records) | 9,945 |
| Raw contacts (pre-dedup pool) | 1,746 |

**Company pipeline status**

| Status | Count |
|---|---|
| Researched | 1,140 |
| Outreach pending | 542 |
| Contacted | 397 |
| Disqualified | 209 |
| Qualified | 80 |
| Bounced | 70 |
| Discovered (raw) | 20 |
| Engaged | 7 |

Avg PQS score: **31.5 / 100**

**Enrichment**

| Status | Contacts |
|---|---|
| Enriched | 5,211 (52%) |
| Needs enrichment | 4,664 (47%) |
| Failed | 69 |
| Has email | 5,653 |
| Decision makers flagged | 6,186 |
| Outreach eligible | 9,157 |
| Companies with research summary | 1,156 / 2,465 (47%) |

**Drafts**

| Status | Count |
|---|---|
| Total generated | 1,898 |
| Approved | 1,131 (60%) |
| Rejected | 437 (23%) |
| Pending review | 330 (17%) |

**Sends — all time**

| Month | Sent |
|---|---|
| March 2026 | 9 |
| April 2026 | 144 |
| May 2026 (through May 12) | 931 |
| Total | 1,084 |

**Engagement funnel**

| Event | Count | Rate |
|---|---|---|
| Sent | 1,084 | — |
| Opened | 94 | 8.7% |
| Clicked | 158 | 14.6% |
| Replied | 1 | 0.09% |
| Bounced | 45 | 4.2% |

**API spend — all time: $291.30**

| Provider / Model | Spend |
|---|---|
| Anthropic — Sonnet 4.6 | $114.65 |
| Apollo — people_match | $107.76 |
| Anthropic — Sonnet 4.6 + web search | $56.00 |
| Anthropic — Haiku 4.5 | $6.43 |
| Perplexity — sonar-pro | $3.46 |
| Anthropic — legacy Sonnet | $3.00 |
| ZeroBounce | $0 |

Monthly burn: Feb $2.62 / Mar $9.48 / Apr $36.55 / May (12 days) $242.66

**Engaged companies (active signal, no follow-up as of 2026-05-12)**

| Company | Contacts | Last Touch (CDT) |
|---|---|---|
| Waupaca Foundry | 42 | May 11 |
| Richline Group (Berkshire Hathaway) | 30 | May 11 |
| Precoat Metals | 26 | May 11 |
| Friedman Industries | 16 | May 11 |
| Westrock Coffee | 12 | May 11 |
| AMETEK Specialty Metal Products | 8 | May 5 |
| Tsubaki Nakashima | 2 | May 5 |

---

## Failure Analysis

### 2026-05-12 — Root Cause Analysis

**Why the system is idle**

1. Send pipeline deliberately paused 2026-05-08. Config note: "PAUSED 2026-05-08 — GTM assessment complete. Domain reputation risk (6.6% bounce on digitillis.com). Halted pending subdomain migration + 30-contact founder-signed diagnostic test."

2. Data pipeline (research/enrichment/qualification) last ran 2026-04-03. Pipeline orchestrator is not running. 11 stale "running" records never marked finished. The APScheduler lives inside the FastAPI/uvicorn process on Railway — when that process restarted after April 3, the scheduler did not resume.

3. Monthly API budget cap ($200) exceeded — May spend at $242.66. `workspace_budget_ok()` returns false, blocking pipeline discovery even if scheduler were running.

4. May 4-5 burst (837 sends in two days) was not part of a healthy ongoing cadence — it was a manual push that exposed the bounce problem and triggered the pause.

**Research agent — 82% failure rate**

- 1,730 failed runs out of 2,120 total
- 78,147 individual error records, single failure mode: `parse_error` — "Claude research returned no valid JSON"
- Root cause: fragile JSON fence-strip only handled responses starting with exactly triple-backtick; Claude frequently adds language label (```json), preamble text, or whitespace variation
- **Fix shipped 2026-05-12 — PR #76** — multi-strategy extractor handles all variants
- 1,309 companies still lack research summary as a result of this failure

**Enrichment agent — Apollo 422 errors**

- 27,003 failures, all `422 Unprocessable Entity` on `/api/v1/people/match`
- Apollo's endpoint requires minimum fields (name + company domain or email); input records are arriving with insufficient data
- 4,664 contacts stuck in `needs_enrichment`
- Apollo spend: $107.76 for 7,447 calls — credits burned on failed calls
- Fix needed: input validation gate before Apollo call — reject records missing (first_name + last_name + domain) or (email)

**Bounce rate — above threshold**

- 45 / 1,084 = 4.15% hard bounce rate (danger threshold: 2%)
- 55% of bounces had no email verification done at all before send
- 32% were marked "verified" but still bounced (ZeroBounce false positive rate)
- ZeroBounce integration exists but was not enforced as a pre-send gate
- Fix needed: `outreach_eligible = true` must require `email_status = 'verified'`

**Draft quality — hallucination rate**

- 246 of 437 rejections (56%) are hallucination or fabrication
  - 155 auto-rejected: step 1 logic error (follow-up drafted before step 1 confirmed sent)
  - 126 auto-rejected: fabricated anecdote (uncategorized)
  - 120 model hallucination (labeled and caught)
  - 28 wrong persona (non-buyer role passed into draft queue)
- Root cause: draft agent has access to LLM's general knowledge — generation is unconstrained; filter catches obvious fabrications but root cause not addressed
- Fix needed: retrieval-constrained generation — draft agent receives only sourced fields from company record, not open generation space

**Pipeline run health**

| Status | Count |
|---|---|
| Completed | 4,463 |
| Failed | 2,252 (27%) |
| Partial | 1,462 (18%) |
| Running (stale) | 11 |

**Qualification agent** — relatively healthy. 3,889 completed, 409 failed (502 DB timeout, not code). Only 133 / 2,465 companies (5.4%) LLM-qualified; 2,123 (86%) not yet through qualification.

---

## Adversarial Strategic Redesign

### 2026-05-12 — First Principles Critique

#### The Fundamental Thesis

ProspectIQ is currently a high-volume outbound automation system built on a SaaS SDR playbook applied to an industrial enterprise market. That mismatch is not a configuration problem. It is a philosophical one.

The 0.09% reply rate is not a messaging failure. It is the market communicating, at statistically significant scale, that the model is wrong. The correct response is not to fix the parser and try harder. It is to interrogate the premise.

The core strategic question: are we mistakenly building a scaled outbound automation system when we should be building an Industrial Account Intelligence Platform?

---

#### 1. Industrial GTM Philosophy — What the SaaS Playbook Gets Wrong

Modern outbound is designed for high-volume, fast-cycle, desk-bound buyers. It works for SMB SaaS. It was never designed for industrial enterprise.

**What breaks down structurally:**

- The buyer is not at a desk. Plant Managers are on the floor six hours a day. Maintenance Directors start at 5am. These are operations-native buyers whose inbox is not their decision surface.
- Trust has a completely different cost structure. Industrial buyers have been burned by ERP implementations and consultants who didn't understand their process. The trust threshold to get a serious conversation requires demonstrated operational credibility — specific knowledge of their process, familiarity with their equipment class. You cannot fake this. They will know immediately.
- Buying cycles are 12 to 24 months minimum. The three-touch sequence model is calibrated for 30-day decision cycles. A manufacturer evaluating AI manufacturing intelligence is in a fundamentally different temporal frame.
- The manufacturing community is small and connected. Serious industrial buyers know each other. A hallucinated anecdote or obviously AI-generated email doesn't just fail — it circulates. The manufacturing market is a relationship network with long institutional memory.

**The biggest misconception technical founders have:** manufacturing is just another vertical to apply outbound automation to, and the friction is operational rather than philosophical. The friction is philosophical. Manufacturing buyers do not want to be sold to. They want to be understood.

---

#### 2. ICP and Segmentation — The Ontology Is Wrong

"Manufacturing" as an ICP is a census category, not a buying segment. The current tier system (mfg1-8, fb1-5) is firmographic classification — it segments by what companies are, not what they need or when they're ready to buy.

Two $200M manufacturers with identical SIC codes can have completely different operational realities and completely different buying readiness. Firmographic segmentation cannot distinguish them.

**A world-class industrial segmentation ontology organizes around two orthogonal axes:**

**Primary axis — Operational Transformation Readiness (predicts buying cycle length and deal size):**

- Stage 0 — Reactive and dark: paper-based, no sensors, no CMMS. Cannot buy yet. Not your market.
- Stage 1 — Instrumented but unanalyzed: sensors, historian, siloed data. Largest mid-market segment. Primary addressable market.
- Stage 2 — Analytically aware but capability-constrained: knows predictive maintenance is valuable, lacks internal expertise to build it. Highest conversion rate.
- Stage 3 — Sophisticated and selective: full reliability engineering team, existing analytics. Long cycle, large deal, high competition.
- Stage 4 — Already solved: in-house team, existing platform. Not a buyer.

**Secondary axis — Asset Class (predicts message frame and technical credibility requirement):**

- Rotating equipment: pumps, compressors, motors, fans. Ubiquitous, universal starting point, lowest barrier to first value.
- Thermal processes: furnaces, kilns, reactors, boilers. High downtime cost, fewer but more expensive events, strong ROI case.
- Discrete assembly lines: cycle time and quality variation are primary pain. Different sensors and algorithms.
- Packaging and filling lines: OEE is the metric, changeover and seal quality are specific pain points.

**Third dimension — Operational Pain Acuity:** Is there a specific, recent, expensive operational event that makes the conversation relevant now? A furnace that went down last quarter. A recall that cost $8M. An OSHA citation. These events create buying windows. Without detecting them, you are reaching companies with a great product pitch and no situational urgency.

The combination of Transformation Stage + Asset Class + Pain Acuity is meaningfully more predictive of buying behavior than any firmographic segmentation.

---

#### 3. ProspectIQ as Industrial Intelligence Infrastructure

The current architecture treats intelligence as instrumental. Research exists to write better emails. Intelligence is in service of the outbound motion.

**The right architecture treats outbound as a byproduct of intelligence, not the purpose of it.**

ProspectIQ should be building a continuously updated operational intelligence layer for every account in its universe. The intelligence exists because it is valuable in itself. Outreach is one output of that intelligence system.

**Proprietary knowledge layers that become defensible moats:**

1. **Operational inference engine** — the ability to infer operational characteristics (maintenance maturity, OT stack, downtime patterns) from public signals. Hard to build, hard to copy once built.

2. **Industrial signal taxonomy** — a structured ontology of what different signals mean operationally. "Hiring a Reliability Engineer" means something specific. "New Plant Manager from a technology company" means something else. This ontology is the moat.

3. **Longitudinal account intelligence** — tracking how accounts evolve over time. Most systems are point-in-time. A platform that understands the trajectory can identify buying windows before they become obvious.

4. **Outcome-correlated scoring model** — every closed and lost deal is training data. At 50 closed deals, patterns emerge. At 200, you have a proprietary model calibrated on win/loss history in this specific market that no competitor can access.

---

#### 4. Research Architecture — The Sequence Is Wrong

**Current sequence:** Company → research → enrich → qualify → draft

This is a data pipeline. It answers descriptive questions: who are they, what do they do, do they fit our ICP, what should we say. It is missing the most important question: what is happening at this account right now that makes them ready to hear from us?

**Better architecture:**

1. **Classify** — operational archetype classification. What production model? What asset classes are critical? What does a bad day look like for them?

2. **Infer** — what can be concluded about current operational state from observable signals? Job postings reveal technology gaps. OSHA records reveal safety incidents. LinkedIn activity reveals transformation journey stage.

3. **Score** — on two dimensions simultaneously:
   - Operational fit: is this a good candidate in principle
   - Timing acuity: is there a signal that makes now a better moment than six months ago
   These are orthogonal. A company can be high fit / low timing or low fit / high timing. Timing acuity is what ProspectIQ is almost entirely missing.

4. **Contextualize** — given archetype, inferred state, and timing signals, what is the specific, credible, operationally grounded angle that makes Digitillis relevant to this account at this moment?

5. **Narrativize** — turn the contextualization into an outreach artifact. Last step, not the organizing frame.

**What the system should infer before any outreach begins:**

- Maintenance leadership composition and philosophy
- Technology infrastructure (SCADA/DCS/PLC vendors) from job postings, LinkedIn skills, conference mentions
- Downtime cost magnitude estimated from production model and asset class
- Operational pain event history from OSHA, FDA, press coverage
- Buying trigger calendar: regulatory deadlines, CapEx cycles, system replacements, leadership transitions

---

#### 5. Human vs. Automation — The Current Balance Is Backwards

ProspectIQ is automating the parts of industrial GTM that should not be automated, and leaving manual the parts that benefit most from AI assistance.

**Never automate:**

- Initial outreach to any tier-1 account. A template-generated message to a VP Operations or Plant Manager at a target account is not appropriate. The first touch carries the full weight of the company's credibility. It must be written by Avanish.
- The judgment of what to say. The synthesis of "given everything we know about this account, here is the credible angle" requires industrial domain knowledge and contextual awareness. AI prepares inputs. A human makes the synthesis judgment.
- Any communication after engagement signals. Three clicks means a human conversation, not a sequence event.

**Should remain founder-led:**

- Top 30 accounts actively managed by Avanish directly — genuine relationship management, not approved drafts
- Narrative framing before each campaign wave — a human-authored answer to "why is this account ready now and what makes us credible with them"

**AI-assisted but not AI-executed:**

- Research synthesis: AI produces research, human reads it and decides relevance
- Draft generation: AI produces draft, human edits and owns it
- Signal monitoring: AI surfaces signals, human interprets significance
- Contact prioritization: AI ranks, human validates top 10

**The honest reframe:** The current ProspectIQ is built for a volume playbook. Volume plays work in high-volume, fast-cycle markets. Manufacturing enterprise is a precision play. You should be sending 20 emails a week, not 465 in a day. Those 20 should be genuinely excellent.

---

#### 6. Trust Architecture — Structural, Not Cosmetic

The hallucination problem is the inevitable consequence of building a system that generates claims in an unconstrained space and then filters for obvious fabrications at the output. Building a filter on the output of an unconstrained generator will always fail at some rate. In industrial enterprise, even a 1% failure rate is unacceptable.

The fix is upstream constraint, not downstream filtering.

**Evidence Grounding as a First-Class Data Structure**

Every claim in the company record should carry provenance:

- Source type hierarchy: primary (official filings, press releases) > secondary (trade coverage, job postings) > tertiary (LinkedIn profiles) > inferred (pattern-based, model knowledge with no external source)
- Confidence level
- Timestamp and URL where available

Claims from primary sources are facts. Claims from inferred sources are hypotheses with explicit confidence bounds.

**Retrieval-Constrained Generation**

The draft agent should have access only to the structured evidence store for that company — not the LLM's general knowledge. Prompt instruction: "You may reference only the information provided below. If you cannot support a claim from the provided context, do not make it."

This is a constraint on the generation space, not a filter on the output.

**Operational Plausibility Layer (rule-based)**

Before draft generation:
- Does this message reference equipment consistent with this production model?
- Does the claimed pain signal align with known failure patterns for this industry?
- Does the trigger event reference have a specific date? (Undated events are almost always fabricated.)

**Approval Workflow That Signals Understanding**

Replace binary approve/reject with claim-confirmation. When approving a draft, the approver should confirm specific claims: "This message references an annealing furnace risk — confirm this is consistent with what you know about this company." This creates a human attestation trail and forces genuine engagement with the content.

---

#### 7. Messaging Philosophy — The Credibility Gap

"AI-powered manufacturing intelligence platform" fails on every dimension for an industrial buyer:

- "AI" is noise. Every vendor is AI. Zero signal value.
- "Platform" is an IT word. Plant managers do not buy platforms. They solve operational problems.
- "Manufacturing intelligence" is undefined. Intelligence about what, to achieve what?

**The governing principle:** operational specificity at the equipment or process level.

The message that works does not say "we help manufacturers reduce downtime." It says "at facilities running continuous annealing lines, the most expensive unplanned event is typically a furnace zone temperature controller failure — because by the time the alarm fires, you're already in a scrap event." That sentence demonstrates genuine operational understanding. It earns 30 seconds of continued reading.

**By vertical:**

- **Foundries:** furnace lining life, ladle thermal cycling, melt shop reliability. Buyer is Melt Shop Superintendent or Maintenance Manager, not VP Operations. Subject lines should reference furnace operations, not AI.
- **Steel and metals:** rolling mill cobble events, roll wear prediction, surface defect causality. Credibility requires knowing what a cobble event costs.
- **Food processing:** FSMA frame is underutilized. Compliance urgency is a better door opener than efficiency. The buy is compliance + OEE, not AI platform.
- **Discrete manufacturing:** spindle utilization, tooling life, first-pass yield. The specific operational KPIs they manage, not "manufacturing intelligence."
- **Packaging:** OEE on filling and sealing lines, changeover efficiency, seal integrity failure rates.

**The deeper problem:** manufacturing buyers test you in the first conversation. They ask something specific about their process to see if you actually understand it. If the answer is generic, the conversation ends. The messaging must earn a conversation with someone who will then immediately test whether the underlying credibility is real. The credibility has to be real, not simulated.

---

#### 8. Signal Intelligence — What the System Cannot See

The current research relies primarily on Claude's training knowledge plus basic web presence. This is a shallow signal set. The signals that actually predict buying behavior are largely unmonitored.

**Regulatory and compliance signals (most underutilized high-value class):**

- OSHA Form 300 logs — public data for facilities above threshold size. Recent incidents create compliance pressure and buying appetite for monitoring technology.
- FDA Form 483 observations (food/pharma) — regulatory deficiency creates remediation timeline and urgency.
- FSMA implementation deadlines — compliance calendar is knowable; companies approaching FSMA 204 deadline are in procurement mode.
- EPA enforcement actions — creates compliance technology appetite.

**Talent signals (highest signal, most accessible, most underutilized):**

- Hiring "Reliability Engineer" with no prior reliability postings = building the capability for the first time. Six-month buying window.
- "Predictive Maintenance Engineer" in job title = explicitly building what you sell. Either a future customer or already buying from a competitor.
- New Plant Manager from a technology-forward industrial company = cultural disposition toward technology adoption. Leadership change creates buying window.
- CMMS migration language in job postings = technology evaluation in progress.

**CapEx and facility signals:**

- Building permits for plant expansions (county public records)
- US Customs import records — equipment arriving from industrial automation vendors indicates modernization cycle
- Industrial real estate transactions — new facility contexts trigger technology evaluation

**Financial and earnings signals:**

- Earnings call language analysis for public mid-market manufacturers: "operational efficiency," "reducing unplanned downtime rate," "investing in production infrastructure" = explicit buying signals
- Mid-market debt covenant disclosures — financial pressure creates operational efficiency urgency

**Industry community signals:**

- Conference speaking (IMTS, FABTECH, SMRP, ProFood World) = operational leadership engaged with technology conversation. High-conversion target.
- Trade publication bylines = visible, credible, peer-networked leader. Responds to messages referencing their operational philosophy, not generic pain points.

---

#### 9. Long-Term Vision — What This Could Become

If the strategic pivot is made — from volume outbound to precision intelligence — ProspectIQ in three years becomes:

**The Industrial Operations Intelligence Network**

A continuously updated intelligence layer on the operational state of North American manufacturing — organized by facility, by asset class, by transformation stage, and by buying readiness.

**What makes it defensible:** the data assembly and normalization is hard. Integrating OSHA records, FSMA filings, job posting taxonomies, customs data, trade publication coverage, LinkedIn activity, earnings call NLP, and industrial equipment databases into a coherent operational fingerprint requires significant domain knowledge to normalize correctly. The normalization layer — the industrial ontology that makes signals interpretable — is where the moat is. Most competitors will not have done this work.

**What makes it valuable to multiple buyers:** the same intelligence infrastructure that powers Digitillis's own GTM is valuable to other industrial technology vendors, PE firms with manufacturing portfolios, and management consultancies. This is a path from internal tool to standalone intelligence product.

**The compounding flywheel:** every closed and lost deal trains the outcome-correlated scoring model. Every deal makes the model better. The model makes every subsequent deal more efficient. This flywheel requires building the intelligence infrastructure correctly first.

**What this becomes that's truly differentiated:** a private intelligence layer on the industrial economy that doesn't exist anywhere else. Bloomberg has this for financial markets. No one has built it for manufacturing operations.

---

#### 10. Brutally Honest Assessment

**What is still being underestimated:**

The cost of a bad send in a network-connected market. Manufacturing is not an anonymous market of email addresses. It is a professional community. A fabricated anecdote that reaches a connected Maintenance Director becomes a data point in the community's mental model of Digitillis. This damage does not show up in bounce rates. It shows up later as "we heard about them, not the right fit" without anyone being able to explain why.

The credibility bar. Buyers who can actually sign a contract for an AI manufacturing platform have been pitched by Siemens, Rockwell, GE Digital, IBM, and every industrial technology startup for a decade. They have a finely tuned detector for vendors who claim to understand their operation but do not. Your first meeting has to clear that detector.

The patience requirement. The right first 10 customers probably come from 30 serious conversations over 18 months, not from a pipeline of 1,084 cold emails. This is a different time constant than most technical founders are comfortable with.

**What is SaaS-like but wrong for industrial:**

- Optimizing for email engagement metrics. The only metric that matters is qualified meetings with decision-makers who have budget authority and operational pain. One qualified meeting from 20 targeted sends beats zero meetings from 1,000 automated sends.
- Treating automation depth as a measure of system maturity. 32 agents, 57 tables, and 1,898 drafts is not more mature than 10 well-researched accounts, 10 founder-written messages, and 5 follow-up meetings booked.
- Building for throughput before validating the motion. The correct order: find 3 accounts manually, close 1, understand exactly why you won, build the system to replicate winning conditions. Current order is inverted.

**Likely failure modes:**

- Domain reputation deterioration makes email GTM impossible before the model is validated. This has already begun.
- A single high-profile hallucination incident in the manufacturing community creates disproportionate reputation damage.
- Intelligence infrastructure never gets built because outbound infrastructure consumes all attention.
- Scaling a broken motion after raising capital accelerates the damage.

**What would make this truly world-class:**

Stop measuring sends. Start measuring conversations. Build the intelligence layer as if it were the product. If cold email became impossible tomorrow, what would ProspectIQ be worth? Treat founder-led outreach as the primary GTM motion for the first 20 customers. Invest in industrial community presence — one talk at IMTS or FABTECH is worth more than 10,000 cold emails in this market.

**What would make this impossible to defend:**

Building a volume outbound system in a precision market and calling it an intelligence platform. If the product narrative is "AI manufacturing intelligence" but the GTM motion is cold email blasts, the narrative and the motion are in contradiction. Industrial buyers notice the contradiction.

---

#### The Strategic Recommendation

Redesign ProspectIQ around this core belief: **in industrial enterprise, intelligence is the product and precision is the motion.**

Immediate implication: stop volume outbound entirely. Not because the infrastructure is broken (though it is) but because it is the wrong motion. Use the pause to rebuild.

Build a genuine industrial intelligence layer: signal ingestion, evidence grounding, operational fingerprinting, buying window scoring. Make the intelligence valuable in itself.

Operate a top-50 precision list. Run founder-led outreach on the top 10 accounts at any given time, backed by the full intelligence infrastructure. Measure qualified meetings booked, not emails sent.

Reserve automation for what it is actually good at: making the founder impossibly well-informed, surfacing new trigger signals as they emerge, preparing account briefings that would take a researcher a week to compile, and continuously updating the scoring model as you learn.

The system should make Avanish the most operationally credible voice in the AI manufacturing intelligence market. Not the system with the highest email throughput. The most credible voice.

---

## Architecture Decisions & Course Corrections

### 2026-05-12 — Fixes Applied

| # | Area | Status | PR |
|---|---|---|---|
| 1 | Research JSON parse bug (78K errors) | Shipped | #76 |
| 2 | Apollo 422 enrichment validation gate | Pending | — |
| 3 | Email verification pre-send gate | Pending | — |
| 4 | Retrieval-constrained draft generation | Pending | — |
| 5 | Pipeline orchestrator restart (Railway) | Pending — operational | — |
| 6 | Subdomain migration + 30-contact diagnostic | Pending — operational | — |
| 7 | Monthly budget cap raise | Pending — config | — |

### 2026-05-08 — Send Pause

Outbound deliberately paused due to 6.6% bounce rate on `digitillis.com`. Config: `outreach_send_config.send_enabled = false`. Conditions to re-enable: subdomain DNS authentication verified, 30-contact founder-signed diagnostic passes with < 2% bounce.

### 2026-05-02 — Web Search Augmentation Disabled

Cost $0.098/call vs. $0.013/Perplexity — 7.5x premium with no reply rate data to justify it. Re-enable via `web_search_enabled=true` in workspace settings once reply data proves ROI.

---

## Signal Intelligence Backlog

Signals the system should monitor that it does not currently:

**Regulatory**
- OSHA Form 300 logs (public, facilities above threshold)
- FDA Form 483 observations (food/pharma)
- FSMA 204 compliance deadlines
- EPA enforcement actions

**Talent (high predictive value)**
- First-time "Reliability Engineer" posting at a facility = 6-month buying window
- "Predictive Maintenance Engineer" job title = active evaluation
- New Plant Manager from technology-forward industrial company
- CMMS migration language in job postings

**CapEx and Facility**
- Building permits for plant expansions (county records)
- US Customs equipment import records
- Industrial real estate transactions

**Financial and Earnings**
- Earnings call language NLP: "operational efficiency," "unplanned downtime," "investing in production"
- Mid-market debt covenant disclosures

**Community**
- Conference speaking at IMTS, FABTECH, SMRP, ProFood World
- Trade publication bylines by plant/operations leadership

---

## Open Questions

*Items requiring a decision or further investigation*

- **2026-05-12:** Is the strategic direction "precision intelligence over volume outbound" confirmed? What is the timeline for pausing volume outbound permanently vs. resuming with better controls?
- **2026-05-12:** What is the target account list for the top-50 precision list? Criteria for inclusion?
- **2026-05-12:** Should ProspectIQ eventually become a standalone intelligence product sold to other industrial technology vendors? If so, when does that roadmap begin?
- **2026-05-12:** What is the right sequencing between fixing the current outbound infrastructure and rebuilding around the intelligence-first model?
