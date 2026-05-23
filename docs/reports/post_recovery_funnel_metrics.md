# Post-Recovery Funnel Metrics
**Date:** 2026-05-13  
**Scope:** Phase 4 — Current pipeline state after recovery actions

---

## Funnel Summary

```
Total contacts:                9,945
  Sendable (verified/catch_all): 1,968   (19.8% of total)
  Null email status:             7,769   (78.1%) ← ZeroBounce verification needed
  Invalid/bounced:                  34    (0.3%)

Sent drafts (all time):        1,137
  Step 1 (cold outreach):        953   (83.8%)
  Step 2 (follow-up):             43    (3.8%)
  Step 3 (second follow-up):       4    (0.4%)

Draft pipeline:
  Pending approval:              269
  Approved but unsent:           101
  Total in queue:                370

Sequence health:
  Stalled (step-1 sent, no step-2): 349 eligible contacts
  Companies contacted (corrected):  857  (was 475 before backfill)

Engagement (all time):
  Email opens:                    35
  Email clicks:                   71
  Email bounces:                  45
  Interactions total:          1,097

Bounce rates:
  7-day rolling:            0.00%  (0/98 sends)   ← HEALTHY
  All-time:                 4.10%  (45/1,097)      ← Note: legacy data quality issue
```

---

## Key Ratios

| Metric | Value | Benchmark |
|---|---|---|
| Step-2 follow-up rate | 43/953 = 4.5% | Should be 80%+ of step-1 |
| Open rate | 35/685 = 5.1% | Cold outreach industry avg: 15-25% |
| Click rate | 71/685 = 10.4% | Cold outreach industry avg: 2-5% |
| 7-day bounce rate | 0.00% | Must be < 2% |

**Step-2 follow-up rate is extremely low (4.5%).** 349 contacts are eligible for step-2 but have no draft. This is the primary pipeline recovery opportunity.

---

## Status Distribution (Post-Backfill)

| Company Status | Count |
|---|---|
| contacted | 857 |
| outreach_pending | ~149 (awaiting first send) |
| researched | 980 |
| discovered | 20 |
| engaged | 9 |
| bounced | 1 |

---

## Approved but Unsent — Priority Queue

101 drafts are approved and ready to send. These will be dispatched by the next `send_approved` scheduler tick (Mon-Fri, 8am-11am Chicago, every 30 min). With `batch_size=20` and `daily_limit=125`, these 101 drafts will clear in ~1-2 days once the send window opens.

---

## Actions to Unlock Full Pipeline

| Action | Owner | Impact |
|---|---|---|
| Set `ZEROBOUNCE_API_KEY` in Railway, run `zb_verify.py` | Avanish | +7,769 contacts potentially sendable |
| Unpause research/enrichment/discovery croms | Avanish | Top-of-funnel growth resumes |
| Step-2 draft generation for 349 stalled contacts | System (automatic when croms unpaused) | 349 follow-up touchpoints |
| Approve pending drafts (269 in queue) | Avanish | 269 additional sends ready |
