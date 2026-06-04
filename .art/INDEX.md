# ProspectIQ ART Ledger Index
Generated: 2026-06-04. All clusters assessed Quick tier (Stage 1 only). Dashboard excluded.

| Cluster | RAG | Composite | Red-block dim | Critical | High | State | Ledger |
|---|---|---|---|---|---|---|---|
| Reply, Thread, Meetings & LinkedIn | 🔴 Red | 2.5 | trust_governance | 4 | 9 | ASSESSED | reply-thread-meetings-linkedin.yaml |
| CRM Sync | 🔴 Red | 2.7 | economic_defensibility | 4 | 6 | ASSESSED | crm-sync.yaml |
| Analytics & Reporting | 🔴 Red | 3.0 | economic_defensibility | 1 | 6 | ASSESSED | analytics-reporting.yaml |
| Orchestration & Pipeline | 🔴 Red | 3.0 | claim_validity | 2 | 6 | ASSESSED | orchestration-pipeline.yaml |
| HITL / Approvals / Review | 🔴 Red | 3.0 | trust_governance | 4 | 5 | ASSESSED | hitl-approvals.yaml |
| Lead Acquisition & Enrichment | 🔴 Red | 3.4 | trust_governance | 2 | 7 | ASSESSED | lead-acq-enrichment.yaml |
| Draft Generation & Personalization | 🔴 Red | 3.7 | trust_governance | 2 | 7 | ASSESSED | draft-personalization.yaml |
| Qualification & Scoring | 🔴 Red | 3.9 | technical_integrity | 3 | 7 | ASSESSED | qualification-scoring.yaml |
| Billing & Quota | 🔴 Red | 3.9 | technical_integrity | 2 | 5 | ASSESSED | billing-quota.yaml |
| **Platform Security** | 🔴 Red | — | trust_governance | 2 | 6 | PLANNED | platform-security.yaml |
| **Send & Dispatch Pipeline** | 🔴 Red | 5.0 | trust_governance | 3 | 7 | PLANNED | send-dispatch-pipeline.yaml |

**TOTAL (all 11 clusters): 26 Critical · 58 High · 81 Medium/Low across the 9 sweep clusters alone.**
(Send pipeline adds 3C+7H; platform security adds 2C+6H from Stage 3.)

## Totals across all clusters
- Critical: 33 (26 sweep + 3 send-pipeline + 2 security + 2 send-pipeline new = ~33 unique)
- High: 71+
- Every single cluster: RED / red-block

## Remediation priority order (by composite + blast radius)
1. **Reply / Thread / LinkedIn** (2.5) — CAN-SPAM/CASL crash, cross-workspace cache poisoning
2. **CRM Sync** (2.7) — 8 unauthenticated endpoints, fabricated deal values written to external CRMs
3. **Analytics** (3.0) — all funnel counts are all-time totals (date filter is dead), fabricated p<0.05
4. **Orchestration** (3.0) — scheduler excludes every live draft, autonomous advance is commented out
5. **HITL / Approvals** (3.0) — unauthenticated write endpoints, reviewer-columns migration unrun
6. **Platform Security** (Red) — 2 Critical auth gaps, fail-open webhooks → send-pipeline remediation
7. **Lead Acquisition** (3.4) — cross-tenant backup, NAICS gate wired to None
8. **Draft Generation** (3.7) — workspace scoping missing on API path
9. **Qualification** (3.9) — LLM gates default to PASS on exception, gates 4-7 run on empty context
10. **Billing** (3.9) — webhook swallows all exceptions → 200, annual billing silently ignored
11. **Send & Dispatch** (5.0) — duplicate-send, env load, ramp throttle → in remediation now

## Next steps
- Deep-dives: start with the bottom 5 composites (Reply, CRM, Analytics, Orchestration, HITL)
- Remediation: send-pipeline handoff already dispatched. These clusters need separate handoffs.
- The cross-cluster root causes (workspace scoping, fail-open exception handlers, unauthed endpoints,
  heuristics-as-AI claims) suggest platform-wide doctrine changes not just per-cluster patches.
