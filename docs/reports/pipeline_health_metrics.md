# Pipeline Health Metrics
**Date:** 2026-05-13  
**Scope:** Phase 5 — SLOs, operational thresholds, governance breach conditions

---

## SLO Table

| Metric | SLO | Threshold | Current Value | Status |
|---|---|---|---|---|
| 7-day rolling bounce rate | < 2% | > 2% blocks sends | 0.00% | HEALTHY |
| send_path assertion coverage (7-day) | > 95% | < 50% = critical | 100% (today's sends) | HEALTHY |
| Daily send cap | ≤ 125 sends/day | N/A | Configured | OK |
| Min step gap | ≥ 5 days between steps | < 5d blocks step | Enforced | OK |
| Company cooldown | ≥ 30 days for new contacts | < 30d blocks step-1 | Enforced | OK |
| Approval pipeline lag | < 48h average draft age | > 72h = alert | Unknown | Monitor |
| Gmail intake heartbeat | Every 15 min | > 30 min gap = alert | Running | OK |
| HITL queue depth (interested) | < 10 pending | > 20 = alert | 0 | HEALTHY |

---

## Governance Breach Conditions

A **governance breach** requires immediate action:

| Condition | Severity | System response | Manual response required |
|---|---|---|---|
| 7-day bounce rate > 2% | Critical | All sends blocked | Investigate bounce source; clean list |
| Rollback failure (orphaned draft) | Critical | CRITICAL log | Manual DB cleanup + contact review |
| send_path coverage < 50% | High | None (detection only) | Review engagement.py code changes |
| Step-3 sent without step-2 confirmation | High | Blocked by assertion | Review sequence state |
| Contact emailed while suppressed | Critical | Blocked by suppression check | Review suppression list freshness |

---

## Operational Thresholds

### Send Volume

| Status | Threshold |
|---|---|
| Normal | 20-125 sends/day |
| Throttled | < 20 sends/day (check: daily_limit, batch_size, approval queue) |
| Exceeded | > 125 (daily_limit will cap this) |

### Approval Throughput

| Status | Threshold |
|---|---|
| Healthy | 50+ drafts reviewed/day |
| Needs attention | < 20 drafts reviewed/day with 50+ pending |
| Blocked | 0 reviews and > 100 pending |

### Bounce Rate Escalation

| Rate | Action |
|---|---|
| 0-1% | Normal operation |
| 1-2% | Monitor closely, investigate sources |
| > 2% | Sends auto-blocked by `assert_bounce_rate_ok` |
| > 5% | Pause all outreach pending list audit |

---

## Weekly Health Check Queries

```bash
# Run governance trace
python /Users/avanish/prospectIQ/governance_enforcement_trace.py --days 7

# Run self-test
python /Users/avanish/prospectIQ/send_path_self_test.py

# Run reply ingestion test
python /Users/avanish/prospectIQ/synthetic_reply_end_to_end_test.py
```

All three should exit with code 0.

---

## Current State (2026-05-13)

| Metric | Value | Trend |
|---|---|---|
| Total contacts | 9,945 | Stable (enrichment paused) |
| Sendable (verified/catch_all) | 1,968 | Stable |
| Null email status | 7,769 | Needs ZeroBounce run |
| Sent drafts (all time) | 1,137 | Growing |
| 7-day sends | 98 | Active |
| All-time bounces | 45 (4.1%) | Historic data quality issue |
| 7-day bounces | 0 (0%) | Healthy |
| Companies contacted (corrected) | 857 | Updated via backfill |
| Step-2 stalled | 349 | Needs cron unpausing |
| Approved unsent | 101 | Will send next window |
