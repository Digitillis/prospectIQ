# Commercial Deployment Readiness Plan — 001
## ProspectIQ — Lane 2: First Three Customer Deployments

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Date:** 2026-05-15  
**Status:** ACTIVE — governs all Lane 2 commercial readiness work  
**Scope:** Lighthouse deployments, onboarding methodology, outcome capture, success criteria

---

## Strategic Context

The platform's core dispatch runtime is operational. The commercial question is now: can ProspectIQ produce a repeatable, evidence-backed value story for manufacturing companies within a controlled activation window?

The first three customer deployments are not sales events. They are operational proving events. Each must:
- produce a documentable outcome,
- demonstrate platform reliability to the customer,
- generate the evidence artifacts that enable subsequent sales conversations.

The commercial trajectory depends entirely on whether these first deployments are disciplined and evidence-rich — not whether they are fast.

---

## Deployment Framework

### Three-Deployment Model

| Deployment | Type | Purpose |
|------------|------|---------|
| Lighthouse 1 | Internal (Digitillis) | Platform reliability validation |
| Lighthouse 2 | Warm prospect (manufacturing, known signal) | First external proof point |
| Lighthouse 3 | Referred prospect or existing relationship | Evidence-generation at scale |

**Sequencing constraint:** Lighthouse 2 does not begin until Lighthouse 1 produces documented outcomes. Lighthouse 3 does not begin until Lighthouse 2 produces documented outcomes.

---

## Required Tooling Before Any Customer Deployment

### T1 — FirstLook Operationalization

**Current state:** FirstLook assessment framework exists. It is not consistently executable as a repeatable customer deliverable.

**Required before Lighthouse 2:**
- Consistent input template (what data is collected from the customer)
- Consistent output format (what the customer receives)
- Delivery mechanism (PDF or structured report)
- Time-to-deliver target: < 5 business days from data receipt
- Review checklist: findings reviewed by Avanish before delivery

**Immediate actions:**
1. Define the standard FirstLook input questionnaire (8–12 questions covering: production lines, OEE baseline, top 3 failure modes, current maintenance approach, alert infrastructure, data availability)
2. Lock the FirstLook output format — what sections are always present, what is optional
3. Confirm PDF generation pipeline is operational end-to-end

---

### T2 — Deployment Intake Form

**Gap:** No standard intake process exists for capturing the operational context of a new customer deployment.

**Required fields:**
```
Company name:
Primary contact name + role:
Facility type (food/bev, discrete mfg, process mfg):
Number of production lines:
Primary failure modes (top 3):
Current CMMS (if any):
Current sensor infrastructure (if any):
Digitillis deployment scope: [FirstLook only / FirstLook + pilot deployment]
Expected go-live date:
Success definition (customer's own words):
```

**Deliverable:** A one-page intake form (Google Form or PDF). Completed intake is required before any customer deployment begins.

---

### T3 — Outcome Capture Framework

**Gap:** Without a structured outcome capture process, customer deployments produce anecdotes instead of evidence.

**For each intervention or recommendation delivered:**
```
Recommendation ID:
Date delivered:
Finding (what was identified):
Recommendation (what was advised):
Confidence level (High / Medium / Low):
Customer action taken:
Outcome observed (30 / 60 / 90 days):
Outcome quantified ($, hours, units):
Attribution confidence (Direct / Partial / Correlated):
```

**Infrastructure:** Track in a simple spreadsheet until volume justifies a dedicated table. At 3+ deployments with documented outcomes, migrate to structured DB tracking.

---

### T4 — Deployment Runbook Template

**Gap:** Each deployment currently requires ad hoc planning. A standard runbook template reduces preparation time and prevents critical steps from being skipped.

**Runbook sections (template):**
1. Customer context (facility type, scope, primary contacts)
2. Data collection plan (what data is needed, by when, from whom)
3. Analysis execution (which FirstLook runners apply, expected findings)
4. Delivery plan (format, date, review process)
5. Follow-up schedule (30/60/90 day check-ins)
6. Success criteria (pre-defined, agreed with customer before delivery)
7. Anomaly log (what changed from plan, and why)

---

### T5 — ROI Instrumentation

**Gap:** No standard framework exists for translating ProspectIQ findings into customer-comprehensible financial impact.

**Required calculation inputs (per deployment):**
- Downtime cost per hour (customer-provided or industry benchmark)
- Average MTBF improvement estimated from recommendation
- Implementation cost (customer estimate)
- Payback period calculation

**Standard formula:**
```
Annual avoided downtime value = (hours avoided × $/hour)
Payback period = implementation cost / annual avoided downtime value
ROI multiple = annual avoided downtime value / annual platform cost
```

**Deliverable:** A one-page ROI worksheet delivered with every FirstLook report. Values are explicitly labeled as estimates where the customer has not provided precise inputs.

---

## Lighthouse 1 — Internal Validation Deployment

### Scope

Use ProspectIQ to analyze a manufacturing dataset that Digitillis has internal access to (either from a prior customer engagement, a public dataset, or a synthetic dataset that faithfully represents a real facility). Execute the full FirstLook pipeline. Deliver a FirstLook report to Avanish as if he were the customer.

**Purpose:** Validate that the full deployment workflow — intake, analysis, delivery, ROI worksheet — can be executed by Avanish alone in under 5 business days with no surprises.

### Success Criteria

```
[ ] Full intake form completed (even if filled by Avanish for a synthetic customer)
[ ] FirstLook analysis executed on representative data
[ ] FirstLook PDF produced — all sections present, no placeholder text
[ ] ROI worksheet produced with quantified estimates
[ ] Delivery reviewed by Avanish as if receiving it as a customer
[ ] Feedback documented: what would a customer not understand, not trust, or not act on?
[ ] All gaps identified and addressed before Lighthouse 2
```

### Evidence Artifacts

- Completed intake form
- FirstLook PDF report
- ROI worksheet
- Internal review notes

### Timeline

Target completion: within 2 weeks of Monday observation CLEAN verdict.

---

## Lighthouse 2 — First External Customer Deployment

### Target Profile

Manufacturing company with:
- A prior signal of interest (responded to outreach, attended a call, or referred by a known contact)
- At least one identifiable operational problem (reliability, OEE, downtime cost)
- Willingness to share basic operational data (not proprietary — production schedule, failure history at category level)
- Decision-maker accessible (plant manager, VP Operations, or equivalent)

**Candidate pool:** AMETEK and Tsubaki are the two credible human signals from the GTM assessment (2026-05-08). Evaluate which is further along the relationship before initiating Lighthouse 2.

### Deployment Sequence

```
Week 1: Intake call + form completion
Week 2: Data collection from customer
Week 3: FirstLook analysis execution
Week 4: Internal review of findings
Week 5: Delivery of FirstLook report + ROI worksheet
Week 6-14: 30-day follow-up + outcome capture
```

### Success Criteria

```
[ ] Intake form completed
[ ] Customer provided basic operational data
[ ] FirstLook report delivered on time (within 5 business days of data receipt)
[ ] Customer confirmed receipt and reviewed findings
[ ] At least one recommendation acknowledged as actionable by the customer
[ ] 30-day follow-up scheduled and completed
[ ] Outcome data captured (even if preliminary)
```

### Risk Factors

| Risk | Mitigation |
|------|-----------|
| Customer does not provide data | Reduce data requirement to 3 questions minimum; offer to run on industry benchmarks |
| FirstLook findings are generic | Ensure analysis uses customer-specific inputs, not generic templates |
| Customer does not act on recommendations | Expected at this stage — outcome is engagement, not implementation |
| Recommendation contradicts customer's existing approach | Frame as a hypothesis, not a conclusion — invite their response |

---

## Lighthouse 3 — Evidence-Generation Deployment

### Target Profile

A second external deployment running concurrently with Lighthouse 2 follow-up, or immediately after. Target a company with:
- Higher operational urgency (active pain point, not theoretical interest)
- Faster decision cycle (SME manufacturer, not enterprise procurement)
- Referral or warm introduction preferred

### Purpose

Lighthouse 3 is designed to produce the first independently verifiable outcome story. The evidence from Lighthouse 2 establishes that the platform works. The evidence from Lighthouse 3 establishes that it is repeatable.

### Additional Requirements for Lighthouse 3

By the time Lighthouse 3 begins, the following must exist from Lighthouse 1 and 2:
- At least one delivered FirstLook report with confirmed customer engagement
- At least one outcome data point (even partial)
- ROI worksheet validated against at least one real customer context
- Delivery process executed end-to-end with no critical gaps

---

## Customer Onboarding Sequence (Standard)

Applicable from Lighthouse 2 onward:

```
Phase 1 — Discovery (1 week)
  - Intake call (30 minutes)
  - Intake form completed
  - Scope agreement: what FirstLook will and will not cover
  - Success criteria agreed in writing (email is sufficient)

Phase 2 — Data Collection (1 week)
  - Minimum data request sent
  - Customer provides data or confirms use of industry benchmarks
  - Data quality review (Avanish confirms analysis is executable)

Phase 3 — Analysis (1 week)
  - FirstLook runners executed
  - Findings reviewed by Avanish before delivery
  - ROI worksheet completed

Phase 4 — Delivery (1 day)
  - FirstLook PDF delivered
  - ROI worksheet delivered
  - Brief delivery call (30 minutes) to walk through findings

Phase 5 — Follow-Up (ongoing)
  - 30-day check-in: did the customer act on any finding?
  - 60-day check-in: any measurable outcome?
  - 90-day check-in: outcome quantification for evidence record
```

**Target time from intake to delivery:** 15 business days (3 weeks).

---

## Evidence Capture Framework

Every deployment must produce the following evidence record, regardless of outcome:

### Tier 1 — Minimum Evidence (every deployment)
- Completed intake form
- FirstLook PDF delivered
- Customer acknowledgment of receipt (email confirmation)
- Outcome: "Did the customer act on any recommendation?" (YES / NO / UNKNOWN)

### Tier 2 — Strong Evidence (target for Lighthouse 2+)
- Documented customer action taken (what did they do as a result?)
- Quantified outcome (downtime hours saved, cost avoided, process change implemented)
- Customer quote suitable for reference use (with permission)

### Tier 3 — Reference Evidence (target for Lighthouse 3+)
- Customer willing to be referenced in sales conversations
- Quantified ROI documented and verified by customer
- Case study narrative (1 page, approved by customer)

---

## Measurable Success Metrics

| Metric | Target (Lighthouse 1–3) |
|--------|------------------------|
| Time from intake to delivery | < 15 business days |
| FirstLook completion rate | 100% (all 3 complete) |
| Customer engagement rate | 2 of 3 customers engage with findings |
| Actionable recommendation rate | At least 1 per deployment |
| Outcome capture rate | At least 1 deployment with documented outcome |
| Reference willingness | At least 1 customer willing to be referenced |

---

## Commercial Deployment Gate Criteria

Before ProspectIQ is offered to a 4th customer:

```
[ ] Lighthouse 1 internal validation: COMPLETE
[ ] Lighthouse 2 delivery: COMPLETE + customer engaged
[ ] Lighthouse 3 delivery: COMPLETE
[ ] At least 1 documented outcome (any tier)
[ ] Delivery process repeatable: Avanish can execute without custom preparation
[ ] FirstLook output format stable: no major revisions between Lighthouse 2 and 3
[ ] ROI worksheet validated against real customer context
[ ] Pricing model defined for paid engagements
```

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/commercial/COMMERCIAL_DEPLOYMENT_READINESS_PLAN_001.md`
