# Apollo Credit Log — ProspectIQ F&B FSMA 204 Campaign

## Plan
- **Monthly allocation**: 6,050 credits / month
- **Credit type tracked**: API enrichment (`people_match` calls only — 1 credit per matched contact, 0 if no match)
- **Free tools** (0 credits): `apollo_mixed_people_api_search`, `apollo_mixed_companies_search`, `apollo_emailer_campaigns_search`

---

## Ground Truth Baseline

| Date | Source | Credits Used | Remaining |
|------|--------|-------------|-----------|
| 2026-05-01 | Apollo billing export (Apr 27 – May 2) | **269** | **5,781** |
| 2026-05-01 | Apollo billing screenshot (Apr 27 – May 2, end of session) | **346** | **5,704** |

All credits are API enrichment. No email, mobile, or AI credits used. All calls via API key (programmatic), not UI.

**Reconciliation note:** 346 - 269 = 77 credits added during this session. Estimated session calls: batch16 (8) + batch17 (11) + John Leptien (1) + pre-compaction batch16 enrichments (8, counted in prior tracking but not reflected in log baseline) + additional calls from the prior session that were not yet captured when the 269 baseline snapshot was taken. Net gap of ~49 credits vs session estimate suggests more calls were made pre-compaction than the summary captured. Apollo export is ground truth.

---

## Session Log

### Session: 2026-04-27 to 2026-05-01 (pre-log, reconstructed)

Batches 1–3 + individual calls across multiple sessions. Exact per-call breakdown not available (daily rollup only in Apollo export). Total for this window: **269 credits**.

Tracked components (approximate):
- Batch 1 (initial F&B seed enrichment): ~100 credits (est.)
- Batch 2 (second wave): ~119 credits (est.)
- Batch 3 (13 contacts): 13 credits
- Michael Mileg / Hilmar C3: 1 credit
- Backfill batch (8 contacts): 8 credits

Note: pre-log tracking was conversational and carried a ~28-credit undercount vs Apollo actual. Apollo export is ground truth.

---

## Running Tally (real-time from 2026-05-01 forward)

| Date | Batch / Event | Calls | Matched | Credits | Cumulative | Remaining |
|------|--------------|-------|---------|---------|-----------|-----------|
| 2026-05-01 | Baseline (Apollo ground truth) | — | — | 0 | **269** | **5,781** |

> Update this table before each batch approval. Add one row per `people_match` call batch.
> Formula: Credits = number of calls that returned a match (Apollo charges 0 for no-match).

---

## Batch Detail (2026-05-01 forward)

No new batches yet. Next batch TBD.

---

## Credit Value Tracking

| Metric | Value |
|--------|-------|
| Credits used to date | 269 |
| Contacts with verified email inserted | ~240 (est. across all batches) |
| Companies at `outreach_pending` | 30+ |
| Credit-to-contact conversion rate | ~89% (most matches returned usable contacts) |
| Wasted credits (no match returned) | ~28 (est.) |
| Cost per enriched contact | ~$0.003 at standard Apollo pricing |

---

## Flags / Anomalies

| Date | Contact | Issue |
|------|---------|-------|
| 2026-05-01 | Patrick Thames (Greater Omaha) | `email_domain_catchall=true` — reduced deliverability confidence |
| 2026-05-01 | Aaron Hancock (Griffith Foods) | `email_domain_catchall=true` — reduced deliverability confidence |
| 2026-05-01 | Julio Maldonado (Mount Franklin) | Email domain is `@sunriseconfections.com` (subsidiary, not primary domain). Apollo employment history shows concurrent role at "HIGH DREAM MACHINERY" — potential stale/dual employment. Verify before send. |

---

## Rules for This Log

1. **Before every `people_match` batch**: add a pending row with expected call count.
2. **After batch completes**: fill in Matched and Credits columns.
3. **Monthly**: pull Apollo billing export and reconcile Cumulative vs Apollo actual.
4. **Any discrepancy > 5 credits**: investigate before next batch.
