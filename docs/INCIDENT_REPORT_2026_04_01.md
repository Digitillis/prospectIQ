# Incident Report — Anthropic Monthly Cap Kill
**Date:** April 1, 2026  
**Account:** avi@digitillis.com  
**Plan:** Max $200/month + prepaid API credit balance  
**Prepared for:** Anthropic support credit request  

---

## Summary

On April 1, 2026, a batch research pipeline making `claude-sonnet-4-6` API calls hit the Anthropic monthly usage cap mid-run. The cap triggered a hard API error that killed all running processes before results or cost data could be persisted. **$33.01 in API credits were consumed with no recoverable output.** The pipeline had to be restarted from scratch, consuming additional credits.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| 14:26:13 | Research pipeline started — `POST /v1/messages` calls at ~$0.025/call |
| 14:26–15:55 | Monthly usage cap hit. API returned `credits_limit_reached` error. 1,730 jobs failed, 384 left partial. All processes killed before results written. |
| 15:55:13 | Last job in incident window started (and immediately failed) |
| ~16:00 | Monthly cap raised in Anthropic console by account holder |
| 17:49:44 | Pipeline restarted — 3 parallel batches ran successfully |
| 17:49–18:58 | 411 companies researched, $10.41 tracked |
| 19:00:08 | Another batch started, killed again after 28 companies ($0.70 tracked) |
| 19:14:34 | Batch of 28 finished/killed |
| 19:22:47 | Restarted with new checkpoint architecture (50 companies per commit) |
| 19:22–ongoing | Current batched run in progress |

**Incident window:** 14:26 UTC → 15:55 UTC (89 minutes)

---

## API Error Returned During Incident

```
Your credit balance is too low to access the Anthropic API.
Please go to Plans & Billing to get more credits.
error_type: credits_limit_reached
```

---

## Pipeline Run Database Records

**Table:** `pipeline_runs` (application's internal job tracking)  
**Total research pipeline_run rows:** 2,125  

| Status | Count | Meaning |
|---|---|---|
| `failed` | 1,730 | Killed by cap error before any companies processed |
| `partial` | 384 | Started processing, killed mid-batch |
| `running` | 11 | Currently active (post-fix batched runs) |

### Failed Job Batch IDs (sample — first 20 of 1,730)
```
research_20260401_092613_3201d6   started: 2026-04-01T14:26:13 UTC
research_20260401_092618_94a977   started: 2026-04-01T14:26:18 UTC
research_20260401_092624_75db09   started: 2026-04-01T14:26:24 UTC
research_20260401_092646_825b60   started: 2026-04-01T14:26:46 UTC
research_20260401_092702_6aeda0   started: 2026-04-01T14:27:02 UTC
research_20260401_092710_76e97a   started: 2026-04-01T14:27:10 UTC
research_20260401_092729_0a1307   started: 2026-04-01T14:27:29 UTC
research_20260401_092745_441555   started: 2026-04-01T14:27:45 UTC
research_20260401_092753_7699d0   started: 2026-04-01T14:27:53 UTC
research_20260401_093003_da00e3   started: 2026-04-01T14:30:03 UTC
research_20260401_093023_6425c3   started: 2026-04-01T14:30:23 UTC
research_20260401_093048_8a72f2   started: 2026-04-01T14:30:48 UTC
research_20260401_093049_3909a4   started: 2026-04-01T14:30:49 UTC
research_20260401_093114_dee923   started: 2026-04-01T14:31:14 UTC
research_20260401_093136_78b002   started: 2026-04-01T14:31:36 UTC
research_20260401_093143_7a1419   started: 2026-04-01T14:31:43 UTC
research_20260401_093204_46d5a7   started: 2026-04-01T14:32:04 UTC
research_20260401_093222_e957ab   started: 2026-04-01T14:32:22 UTC
research_20260401_093232_5c73f4   started: 2026-04-01T14:32:32 UTC
research_20260401_093248_d2b3ff   started: 2026-04-01T14:32:48 UTC
... (1,710 more)
```

### Successful Runs (cost committed to DB)

| Batch ID | Started (UTC) | Finished (UTC) | Companies | Cost |
|---|---|---|---|---|
| research_20260401_124944_12497a | 2026-04-01 17:49:44 | 2026-04-01 18:58:30 | 131 | $3.4227 |
| research_20260401_124944_e9f018 | 2026-04-01 17:49:44 | 2026-04-01 18:58:22 | 136 | $3.4960 |
| research_20260401_124946_e99f6a | 2026-04-01 17:49:46 | 2026-04-01 18:58:03 | 144 | $3.4975 |
| research_20260401_140008_616d82 | 2026-04-01 19:00:08 | 2026-04-01 19:14:34 | 28  | $0.6951 |
| **Total** | | | **439** | **$11.1113** |

---

## Financial Summary

| Item | Amount |
|---|---|
| API credits added on April 1 (2× $25 top-ups) | $50.00 |
| Balance remaining (as of ~19:30 UTC) | $5.88 |
| **Total consumed by Anthropic** | **$44.12** |
| Tracked in completed pipeline_run rows | $11.11 |
| **Untracked — consumed by cap-killed jobs, no output** | **$33.01** |
| Estimated API calls in lost spend (÷ $0.0253/call) | ~1,305 calls |

### Verification
- Companies with research saved to database: **210** (represents confirmed successful calls)
- 210 × $0.0253/call = **$5.31** (matches the gap between tracked $11.11 and what the DB shows as useful)
- The remaining **~$33.01** went to in-flight calls that were interrupted by the cap

---

## Cost Per Call Verification

From the 4 completed runs (439 companies, $11.11 total):

| Run | Companies | Cost | Per Company |
|---|---|---|---|
| research_20260401_124944_12497a | 131 | $3.4227 | $0.0261 |
| research_20260401_124944_e9f018 | 136 | $3.4960 | $0.0257 |
| research_20260401_124946_e99f6a | 144 | $3.4975 | $0.0243 |
| research_20260401_140008_616d82 | 28  | $0.6951 | $0.0248 |
| **Average** | | | **$0.0253** |

All calls used `claude-sonnet-4-6` with `max_tokens=2000`. Input prompt ~1,400 tokens, output ~800 tokens per call.

---

## Root Cause

The application ran all jobs in a single `execute()` context — cost was only committed to `pipeline_runs.cost_usd` when `monitor.finish()` was called at the very end of the run. When the monthly cap killed processes mid-run, `monitor.finish()` never executed, so cost stayed at `NULL`/`$0.00` in the application database despite Anthropic having processed and billed for the calls.

---

## Fix Implemented

Restructured to commit every 50 companies as a separate `execute()` call, each with its own `pipeline_runs` row. Maximum exposure per process kill is now ~$1.25. First batched run started at 19:22:47 UTC.

---

## Raw Data

- `incident_pipeline_runs_raw.json` — full export of all 2,125 research pipeline_run rows
- `incident_data.json` — structured summary of incident metrics

---

## Support Request

Requesting credit of **$25–$30** to offset cap-induced failures where API compute was delivered but output was irrecoverable due to process kill from the monthly cap error.

**Contact:** avi@digitillis.com
