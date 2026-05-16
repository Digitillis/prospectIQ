# Enterprise Hardening Gap Assessment — 001
## ProspectIQ — Lane 4: Enterprise Readiness Gap Analysis

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Date:** 2026-05-15  
**Status:** ACTIVE — governs all Lane 4 gap assessment work  
**Scope:** Current state vs future enterprise requirements; severity classification; deferability

---

## Scope and Constraints

This assessment covers what must change for ProspectIQ to be credibly deployable to an enterprise manufacturing customer. It does not cover microservices, Kubernetes, distributed system redesign, or horizontal scaling — those are not the relevant enterprise readiness questions at current scale.

The relevant questions are:
- Can we recover from a failure without data loss?
- Can we prove to a customer that their data is isolated from other customers?
- Can we define and hold service commitments?
- Can we produce an audit trail?
- Can we demonstrate access governance?

---

## Severity Classification

| Class | Meaning |
|-------|---------|
| **CRITICAL** | Blocks enterprise sales conversations; customer will ask about this in first meeting |
| **HIGH** | Required before signing a paid enterprise contract |
| **MEDIUM** | Required before a 6-month enterprise engagement closes |
| **LOW** | Required before enterprise at scale (> 10 customers) |

---

## Section 1 — Disaster Recovery

### GAP-DR-1: No Formal Recovery Time Objective (RTO) or Recovery Point Objective (RPO)

**Current state:** The platform runs on Railway (compute) + Supabase (database). Railway handles process restarts. Supabase handles DB persistence with its own backup infrastructure. There is no defined RTO or RPO for ProspectIQ as a service.

**Enterprise requirement:** Any enterprise procurement conversation will include "what happens if your system goes down?" and "how much data could we lose?" Undefined RTO/RPO is a procurement blocker.

**Gap:** RTO and RPO have not been defined, measured, or documented.

**Remediation:**
1. Define initial targets (not aspirational — achievable with current infrastructure):
   - RTO: < 30 minutes (Railway process restart is near-instant; the 30-minute window accounts for incident detection and response)
   - RPO: < 5 minutes (Supabase continuous backup)
2. Document the recovery procedure: what does "restore from backup" mean, step by step?
3. Test recovery annually (or after any significant infrastructure change)

**Severity:** HIGH  
**Deferability:** Can defer until first paid enterprise contract discussion, but must be answerable at that point  
**Estimated effort:** 4 hours (documentation + one recovery test)

---

### GAP-DR-2: No Recovery Procedure for Railway Process Failure

**Current state:** If the Railway process crashes mid-dispatch, the stale lock reclaim mechanism handles queue recovery. But there is no documented procedure for a full process restart scenario (restart at wrong time, deployment failure, environment variable corruption).

**Gap:** Documented recovery procedure does not exist for:
- Railway service restart during an active send window
- Deployment failure (bad deploy interrupts scheduler registration)
- Environment variable corruption (wrong SEND_ENABLED value at restart)

**Remediation:**
Document a Railway incident recovery procedure covering:
```
If Railway service restarts during an active send window:
  1. Check outbound_queue for locked rows
  2. Wait for stale lock reclaim (5 minutes)
  3. Confirm all locks released
  4. Verify scheduler registered correctly (GET /api/admin/scheduler-health)
  5. Verify send gates are in expected state
  6. Resume observation; no manual intervention required
```

**Severity:** MEDIUM  
**Deferability:** Can defer to Stage 3 preparation  
**Estimated effort:** 2 hours (documentation)

---

## Section 2 — Tenant Isolation

### GAP-TI-1: Tenant Isolation Not Formally Validated

**Current state:** The dispatch path is workspace-scoped (`workspace_id` on every relevant table, `claim_outbound_queue_batch` is workspace-scoped, `outreach_send_config` is workspace-scoped). Multi-tenant isolation is structurally implemented but has not been formally validated.

**Enterprise requirement:** A customer will ask "can another customer see my data?" The answer must be "no" with supporting evidence, not "we believe not."

**Gap:** No formal tenant isolation validation has been executed. No test exists that proves workspace A cannot read or mutate workspace B's data through any application path.

**Remediation:**
1. Create a tenant isolation validation checklist:
   - `outbound_queue`: filtered by workspace_id at all access points
   - `send_attempts`: filtered by workspace_id at all access points
   - `outreach_send_config`: filtered by workspace_id at all access points
   - `outreach_drafts`: filtered by workspace_id at all access points
   - Webhook reconciliation: does not cross workspace boundaries
2. Execute validation (manual SQL audit, not a code change)
3. Document: "Tenant isolation validated on DATE by AUTHOR — method: workspace boundary audit"

**Severity:** HIGH  
**Deferability:** Can defer until Lighthouse 2 (first external customer), must be complete before Lighthouse 2 data touches the system  
**Estimated effort:** 4 hours (SQL audit + documentation)

---

### GAP-TI-2: No Row-Level Security (RLS) at DB Layer

**Current state:** Tenant isolation is enforced at the application layer (workspace_id filters in every query). The DB itself does not enforce isolation — a raw SQL connection with the DB password can read any workspace's data.

**Enterprise requirement:** Enterprise customers with data sensitivity requirements (especially in regulated manufacturing) will ask about database-layer access controls.

**Gap:** Supabase supports Row Level Security (RLS) policies but they are not enabled on the dispatch-critical tables.

**Remediation:**
RLS implementation is a non-trivial migration (requires enabling RLS per table, defining policies, and testing with the actual service role). This should be scoped separately.

**Assessment:** This is a MEDIUM risk at current scale. The application-layer filtering is correct. The risk of internal access control gaps is low given the single-operator context. However, it becomes HIGH before any enterprise customer signs.

**Severity:** MEDIUM (now) → HIGH (before first enterprise signed contract)  
**Deferability:** Defer until Lighthouse 3 or first paid contract — whichever comes first  
**Estimated effort:** 8–12 hours (RLS policy authoring + validation + migration)

---

## Section 3 — SLO Definitions

### GAP-SLO-1: No Service Level Objectives Defined

**Current state:** ProspectIQ has no defined SLOs — no uptime commitment, no dispatch latency target, no data freshness SLA.

**Enterprise requirement:** Enterprise procurement will request SLAs. Without defined SLOs internally, there is no basis for an SLA externally.

**Gap:** No SLO document exists.

**Remediation:**
Define initial SLOs (achievable, not aspirational):

| Metric | Target | Measurement method |
|--------|--------|--------------------|
| Service availability | 99.5% monthly (allows ~3.6h downtime/month) | Railway uptime monitoring |
| Dispatch window execution | 8 of 8 scheduled ticks fire per window | Railway log verification |
| Queue drain completeness | All claimed rows resolve within 24h | send_attempts settled count |
| Webhook reconciliation latency | 95% of sends reconciled within 2 hours | reconciled_at vs created_at delta |
| Scheduler recovery after restart | < 15 minutes from restart to scheduler active | Railway restart + scheduler-health endpoint |

**Note:** These are internal operational targets, not customer SLAs. They become the basis for customer SLA definition when a paid contract is negotiated.

**Severity:** HIGH (before first paid contract)  
**Deferability:** Defer until Lighthouse 2 is complete — at that point the operational data exists to validate whether the targets are achievable  
**Estimated effort:** 3 hours (documentation)

---

## Section 4 — Backup Verification

### GAP-BK-1: Supabase Backup Not Verified at Application Level

**Current state:** Supabase provides continuous backups at the infrastructure level. However, the recoverability of ProspectIQ-specific data (outbound_queue, send_attempts, outreach_drafts, outreach_send_config) from a backup has never been tested.

**Enterprise requirement:** "Can you restore my data if something goes wrong?" requires a tested answer, not an assumed one.

**Gap:** No backup recovery test has been executed. The procedure for restoring specific tables from a Supabase backup is not documented.

**Remediation:**
1. Document the Supabase point-in-time recovery procedure for ProspectIQ tables
2. Execute one recovery test to a staging environment (not production)
3. Confirm recovered data matches expected state (row counts, constraint integrity)
4. Document: "Recovery tested on DATE — result: [PASS/FAIL]"

**Severity:** HIGH  
**Deferability:** Can defer until Lighthouse 2, but must be done before any paid enterprise contract  
**Estimated effort:** 4 hours (procedure documentation + one test execution)

---

## Section 5 — Audit Export Capability

### GAP-AE-1: No Structured Audit Export

**Current state:** All audit data exists in the DB (send_attempts, outbound_queue history, webhook events). But there is no mechanism to produce a structured export of "everything that happened to a specific draft" or "all sends in a date range" in a format a customer or auditor can use.

**Enterprise requirement:** A customer may request evidence of what was sent on their behalf — especially if ProspectIQ is used as part of a managed outreach service. An auditor may request a structured send log.

**Gap:** No audit export endpoint or query-to-export workflow exists.

**Remediation:**
Short-term (no code): The forensic reconstruction query in the Operational Maturity Roadmap (P1-6) provides the raw data. Add a documented export procedure:
```
1. Run the forensic reconstruction query for the relevant workspace + date range
2. Export from Supabase SQL editor as CSV
3. Include in evidence package for customer
```

Long-term (when needed): A dedicated `/api/admin/audit-export` endpoint that returns a signed CSV download.

**Severity:** MEDIUM (now) → HIGH (before first paid enterprise customer)  
**Deferability:** Can use manual SQL export until first paid customer  
**Estimated effort (short-term):** 2 hours (documentation)  
**Estimated effort (long-term endpoint):** 6 hours

---

## Section 6 — Access Governance

### GAP-AG-1: No Formal Access Control Policy

**Current state:** Access to the ProspectIQ system involves: Railway dashboard access (Avanish), Supabase dashboard access (Avanish), API access (JWT-authenticated), and DB direct access (Supabase service role key).

**Enterprise requirement:** A customer will ask "who has access to our data?" The answer must be specific, documented, and bounded.

**Gap:** No formal access control policy exists. Access rights are not documented. There is no defined process for access review or revocation.

**Remediation:**
1. Document all current access points:
   - Railway: who has admin access?
   - Supabase: who has admin access? what roles exist?
   - API: what authentication is required for each endpoint?
   - DB direct: who holds the service role key?
2. Define access review cadence (quarterly at minimum)
3. Define access revocation procedure (what happens when access must be removed?)

**Severity:** HIGH (before Lighthouse 2, first external customer)  
**Deferability:** Cannot be deferred past Lighthouse 2  
**Estimated effort:** 3 hours (documentation)

---

### GAP-AG-2: No API Authentication Audit

**Current state:** The API uses JWT authentication. Admin endpoints (send-config, trigger-send, scheduler-health) are protected, but the exact authentication requirements per endpoint have not been formally audited.

**Gap:** No endpoint-level access control matrix exists. It is unclear whether all admin endpoints require authentication, and what happens if the auth token is invalid vs missing.

**Remediation:**
1. Enumerate all admin endpoints
2. Test each with: valid token, invalid token, missing token
3. Document expected behavior
4. Confirm no admin endpoint is accessible without valid authentication

**Severity:** HIGH  
**Deferability:** Can defer until Lighthouse 2 preparation  
**Estimated effort:** 4 hours (audit + documentation)

---

## Section 7 — Operational Attestation

### GAP-OA-1: No Operational Attestation Capability

**Current state:** There is no mechanism for ProspectIQ to attest to a customer that the system behaved correctly during a specific period. "Trust us, we checked the logs" is the current answer.

**Enterprise requirement:** An enterprise customer who relies on ProspectIQ recommendations may eventually require a periodic attestation: "for the period X to Y, the following sends were executed, with the following outcomes, and no unauthorized activity occurred."

**Gap:** No attestation format or generation process exists.

**Remediation:**
Design a quarterly attestation package format:
```
Attestation Period: [start date] to [end date]
Workspace: [workspace_id / customer name]
Sends executed: [count]
Sends delivered: [count]
Sends failed: [count with failure codes]
Webhook reconciliation rate: [% reconciled within 2 hours]
Unauthorized activity: NONE (or: see anomaly log)
Attestation prepared by: Avanish Mehrotra
Attestation date: [date]
```

This is a documentation format, not a code feature. The data to populate it already exists in `send_attempts`.

**Severity:** LOW (now) → MEDIUM (before any enterprise contract renewal)  
**Deferability:** Defer until first enterprise contract is signed  
**Estimated effort:** 2 hours (format design + documentation)

---

## Section 8 — Evidence Immutability

### GAP-EI-1: Send History Is Mutable

**Current state:** `send_attempts` rows can be updated (status, failure_code, reconciled_at are all writable). There is no immutability guarantee on the send history record. A misconfigured UPDATE or a future migration could inadvertently alter the historical record.

**Enterprise requirement:** An audit of "what did you send and when" requires that the send record cannot be altered after the fact.

**Gap:** No immutability control exists at the DB or application layer. The service role key can UPDATE any send_attempts row at any time.

**Remediation:**
Short-term: Document a policy: "send_attempts rows are final after resolved_at is set — no UPDATE to status, failure_code, or resolved_at after that point." Enforce at application layer (dispatch_scheduler already follows this pattern).

Long-term: Add a DB trigger that prevents updates to `send_attempts` rows where `resolved_at IS NOT NULL`, except for `reconciled_at` (which is written by the webhook handler after resolution).

**Severity:** MEDIUM (now) → HIGH (before first enterprise contract)  
**Deferability:** Short-term policy can cover until first paid customer; trigger implementation deferred to then  
**Estimated effort (policy):** 1 hour  
**Estimated effort (DB trigger):** 3 hours

---

## Section 9 — Security Posture Inventory

### GAP-SP-1: No Security Posture Document

**Current state:** Security controls exist (JWT auth, HTTPS, Railway secrets management, Supabase RLS partially in place). But there is no single document that states what security controls are active, what their current status is, and what known gaps exist.

**Enterprise requirement:** Enterprise procurement will include a security questionnaire. Without a documented security posture, each questionnaire requires a fresh investigation.

**Gap:** No security posture document exists.

**Remediation:**
Produce a one-page security posture inventory:

| Control | Status | Notes |
|---------|--------|-------|
| HTTPS everywhere | Active | Railway enforces TLS |
| JWT API authentication | Active | All non-public endpoints |
| Secrets management | Active | Railway secrets, not git |
| DB credential isolation | Active | Service role key not in code |
| RESEND_WEBHOOK_SECRET | Pending (D8) | Set before Stage 1 |
| Row-level security (DB) | Partial | Application-layer only |
| Access control documentation | Gap | See GAP-AG-1 |
| Audit log | Partial | send_attempts + Railway logs |
| Backup + recovery | Partial | Supabase infra; not tested |
| Penetration testing | Not done | Not required before Lighthouse 2 |

**Severity:** HIGH (before Lighthouse 2)  
**Deferability:** Cannot be deferred past Lighthouse 2  
**Estimated effort:** 4 hours (inventory + documentation)

---

## Consolidated Gap Priority Table

| Gap | Severity | Deferability | Effort |
|-----|----------|-------------|--------|
| GAP-DR-1: RTO/RPO undefined | HIGH | Before first paid contract | 4 hrs |
| GAP-DR-2: Railway recovery procedure | MEDIUM | Before Stage 3 | 2 hrs |
| GAP-TI-1: Tenant isolation not validated | HIGH | Before Lighthouse 2 | 4 hrs |
| GAP-TI-2: No DB-layer RLS | MEDIUM→HIGH | Before first paid contract | 8–12 hrs |
| GAP-SLO-1: No SLOs defined | HIGH | Before first paid contract | 3 hrs |
| GAP-BK-1: Backup not tested | HIGH | Before first paid contract | 4 hrs |
| GAP-AE-1: No audit export | MEDIUM→HIGH | Manual SQL covers now | 2 hrs (doc) |
| GAP-AG-1: No access control policy | HIGH | Before Lighthouse 2 | 3 hrs |
| GAP-AG-2: API auth audit | HIGH | Before Lighthouse 2 | 4 hrs |
| GAP-OA-1: No attestation capability | LOW→MEDIUM | Before first renewal | 2 hrs |
| GAP-EI-1: Send history mutable | MEDIUM→HIGH | Policy now; trigger later | 1 hr (policy) |
| GAP-SP-1: No security posture doc | HIGH | Before Lighthouse 2 | 4 hrs |

**Total estimated effort (all gaps):** ~40–45 hours  
**Before Lighthouse 2 (external customer):** ~18 hours of documentation and validation work  
**Before first paid contract:** additional ~22 hours

---

## Sequencing Recommendation

**Before Lighthouse 2 (first external customer):**
1. GAP-AG-1: Access control policy (3 hrs)
2. GAP-AG-2: API auth audit (4 hrs)
3. GAP-TI-1: Tenant isolation validation (4 hrs)
4. GAP-SP-1: Security posture document (4 hrs)
5. GAP-EI-1: Immutability policy (1 hr)

**Before first paid contract:**
6. GAP-DR-1: RTO/RPO definition + recovery test (4 hrs)
7. GAP-SLO-1: SLO definitions (3 hrs)
8. GAP-BK-1: Backup recovery test (4 hrs)
9. GAP-AE-1: Audit export endpoint (6 hrs)
10. GAP-TI-2: RLS implementation (8–12 hrs)

**Before enterprise at scale:**
11. GAP-OA-1: Attestation format (2 hrs)
12. GAP-DR-2: Full recovery procedures (2 hrs)
13. GAP-EI-1: DB immutability trigger (3 hrs)

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/ENTERPRISE_HARDENING_GAP_ASSESSMENT_001.md`
