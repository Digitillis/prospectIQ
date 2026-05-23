# Operational State Consistency Report

**Run at:** 2026-05-13 23:05:05 UTC

## Check Results

| Check | Value |
|-------|-------|
| ordering_canonical_vs_created_match_first_64 | False |
| approved_unsent_with_gov_violations | 29 |
| approved_drafts_suppressed_after_approval | 0 |
| sent_drafts_total | 500 |
| sent_drafts_without_assertions | 100 |
| assertion_coverage_pct | 80.0 |
| step2_approved_without_step1_sent | 0 |
| review_manifests_table_exists | True |

## Issues Found

### [HIGH] ordering_drift
Canonical sort (company/last_name) differs from created_at DESC in positions 1-64

### [HIGH] approved_governance_drift
29 approved drafts have contacts that are now ineligible
Examples: [{'draft_id': 'a5ce96b9', 'contact_id': '14f8602b', 'email_status': 'null', 'is_eligible': True}, {'draft_id': '2ea23249', 'contact_id': '66c860bb', 'email_status': 'null', 'is_eligible': True}, {'draft_id': '62396944', 'contact_id': '1a941e28', 'email_status': 'null', 'is_eligible': True}]
Count: 29
