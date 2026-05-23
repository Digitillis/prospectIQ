# Phase 5 — Enrichment Strategy

**Date:** 2026-05-13  
**Confidence:** HIGH (live DB counts)

---

## Contact Email Coverage

### Current State

| Population | Count | Notes |
|------------|-------|-------|
| Total contacts | 9,945 | |
| Contacts with email | 3,568 | 35.9% |
| Contacts without email | 6,377 | 64.1% — cannot be contacted |
| Sendable (verified/catch_all) | 1,968 | 19.8% of those with email |
| After ZB second pass (est.) | ~3,367 | If 93% of remaining 1,504 are sendable |

### Contact Tier Distribution for No-Email Contacts

| Tier | Count | Priority |
|------|-------|----------|
| target | 5,851 | Highest |
| borderline | 40 | Medium |
| excluded | 486 | Do not enrich |

**Finding:** All no-email contacts are in three tiers. The contact_tier column uses `"target"` and `"excluded"` (not `"tier_1"/"tier_2"` as assumed in the original plan). The full 5,851 `"target"` population is the priority enrichment pool.

---

## Company Metadata Coverage

### Current State

| Field | NULL Count | NULL % | Impact |
|-------|-----------|--------|--------|
| website | 2,465 | 100.0% | Cannot use website in research |
| industry | 2,397 | 97.2% | No vertical segmentation |
| employee_count | 2,416 | 98.0% | No size filtering |
| status | 0 | 0.0% | Fully populated |

**Finding:** Company metadata (industry, employee_count, website) is near-completely absent. Research intelligence (`research_intelligence` table) exists for 1,145 companies but does not populate the companies table metadata fields.

---

## Priority Enrichment Actions

### Priority 1: ZeroBounce Second Pass — IMMEDIATE

- Target: 1,504 null-status contacts with emails
- Cost: $12.03 (1,504 × $0.008)
- Expected yield: ~1,399 new sendable contacts
- Action: Run `replay_verification_results.py --execute`

### Priority 2: Apollo Bulk Email Discovery for Target-Tier Contacts

- Target: 5,851 `target`-tier contacts with no email
- Expected match rate: 60-70% (Apollo's typical bulk match rate for manufacturing contacts)
- Expected new emails: ~3,500-4,000
- Credits required: ~5,851 (bulk people match)
- Cost estimate: ~$175 at $0.03/credit (varies by Apollo plan)

#### Recommended Batching Strategy

| Batch | Criteria | Size | Est. Cost |
|-------|----------|------|----------|
| Batch 1 | target-tier, company researched | ~2,000 | ~$60 |
| Batch 2 | target-tier, company contacted | ~800 | ~$24 |
| Batch 3 | target-tier, remaining | ~3,051 | ~$92 |
| **Total** | | **~5,851** | **~$176** |

Run Batch 1 first (companies with existing research get the most value from new contacts — the draft generator can immediately use the research to create personalized outreach).

#### Apollo Bulk Match Script

Use the existing Apollo bulk match capability:
```python
from backend.app.integrations.apollo import ApolloClient

# Batch 1: target-tier contacts in researched companies
# Export contact IDs from: SELECT c.id, c.full_name, c.title, co.name AS company_name
#   FROM contacts c JOIN companies co ON c.company_id = co.id
#   WHERE c.email IS NULL AND c.contact_tier = 'target' AND co.status = 'researched'
# Run through ApolloClient.bulk_people_match(contacts)
```

### Priority 3: Apollo Company Metadata Backfill

- Target: 2,465 companies with null industry/employee_count/website
- API endpoint: Apollo Organizations Bulk Enrich
- Expected match rate: 70-80% for named manufacturing companies
- Credits: ~2,465
- Cost estimate: ~$74 at $0.03/credit

**Value:** Enables vertical segmentation for campaign targeting. Industry field enables company-size-appropriate messaging. With this data, the 1,145 already-researched companies can be properly scored and prioritized.

---

## Expected Pipeline State After Enrichment

| Metric | Current | After ZB | After Apollo Discovery | After Both |
|--------|---------|----------|----------------------|-----------|
| Sendable contacts | 1,968 | ~3,367 | ~1,968 + 3,500 = ~5,468 | ~6,867 |
| Stalled Seg A resolved | — | ~148 | — | ~148 |
| New step-2 candidates | 310 | ~458 | ~3,000+ | ~3,000+ |

---

## Apollo Credit Budget Estimate

| Action | Credits | Cost | Priority |
|--------|---------|------|----------|
| ZeroBounce 2nd pass | 1,504 ZB credits | $12 | P0 — this week |
| Apollo contact discovery (target-tier) | ~5,851 | ~$176 | P1 — this month |
| Apollo company metadata backfill | ~2,465 | ~$74 | P2 — this month |
| **Total recommended** | | **~$262** | |

### Credit Conservation Note

Before running Apollo discovery, check current credit balance:
```python
from backend.app.integrations.apollo import ApolloClient
with ApolloClient() as apollo:
    info = apollo.get_credits()
    print(f"Remaining: {info.get('credits_remaining')}")
```

The `apollo_credits_ok()` function in `workspace_scheduler.py` stops enrichment when remaining credits fall to 200. This is the correct guard for automated runs.

---

## Do Not Enrich

| Population | Count | Reason |
|------------|-------|--------|
| excluded-tier contacts | 486 | Below outreach threshold |
| Bounced contacts | 84 | Already suppressed |
| Disqualified companies | 209 | Intentionally excluded |

Total: 779 contacts/companies excluded from enrichment priority.
