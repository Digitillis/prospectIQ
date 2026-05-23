# Phase 3 — Stalled Pipeline Recovery Plan

**Date:** 2026-05-13  
**Scope:** 583 contacts with step-1 sent, no step-2 draft

---

## Immediate Actions (Today)

### Action 1: Verify step-2 generation for 310 eligible contacts

The 310 contacts in Segment E (verified/catch_all, not blocked, cooldown elapsed) should be picked up by the next `_run_draft_generation` cron tick (every 5 minutes).

**Verify:**
```sql
-- Check new step-2 pending drafts created after today's ZB run
SELECT COUNT(*) FROM outreach_drafts
WHERE sequence_step = 2
  AND approval_status = 'pending'
  AND created_at > '2026-05-13T00:00:00'
```

**Expected outcome:** 200-310 new step-2 pending drafts appearing over the next 1-2 hours.

**If drafts do NOT appear:** The draft_generation cron may have a bug in how it identifies step-2-eligible contacts. Check the engagement.py or outreach.py cron logic to confirm it queries for contacts where step-1 is sent but step-2 does not exist.

### Action 2: Run ZeroBounce second pass for 1,504 null-status contacts

This unlocks Segment A (159 stalled contacts) plus 1,345 other contacts with emails that haven't been verified.

```bash
# Dry run first to confirm count and cost
python3 docs/reports/remediation/replay_verification_results.py

# Then execute after confirming credit balance
python3 docs/reports/remediation/replay_verification_results.py --execute
```

**Expected outcome:** ~148 of the 159 Segment A stalled contacts become verified/catch_all and eligible for step-2 generation.

---

## Near-Term Actions (This Week)

### Action 3: Review 248 step-2 pending drafts

The step-2 review backlog is the current bottleneck for the non-stalled population. 248 drafts are pending human review. At 16 drafts/session, this is ~15 sessions.

Consider:
- Prioritize by company tier or PQS score
- Batch review by company vertical to maintain context

### Action 4: Address 202 rejected step-2 drafts

202 step-2 drafts were rejected. Rejection does not automatically trigger regeneration. These contacts are not in the "stalled" category (they have a draft) but they are functionally blocked.

Review rejection reasons and regenerate for:
- Drafts rejected for quality issues (not governance violations)
- Contacts still outreach-eligible and email-verified

**Estimated recovery:** 100-150 additional step-2 drafts if regenerated.

---

## Recovery Metrics

| Action | Contacts Unblocked | Timeline |
|--------|-------------------|----------|
| ZB second pass | ~148 (Segment A) | Today |
| Draft gen picks up Seg E | 310 | Next 1-2 hours |
| Review 248 pending | 248 (if approved) | 15 sessions |
| Regenerate 202 rejected | ~150 | 3-4 hours |
| **Total potential** | **~856** | **1 week** |

This would increase the active step-2 pipeline from 43 sent to approximately 400+ contacts progressed to step-2, representing nearly 10x pipeline advancement.

---

## Monitoring

After running recovery actions, check:

```python
# Stalled contacts remaining (should decrease)
python3 docs/reports/remediation/regenerate_step2_candidates.py

# Step progression health
SELECT sequence_step, COUNT(*) 
FROM outreach_drafts 
WHERE sent_at IS NOT NULL 
GROUP BY sequence_step
```

**Success criteria:**
- Segment E drops to 0 (all 310 have step-2 drafts generated)
- Segment A drops by ~148 after ZB pass
- Total step-2 sent increases from 43 toward 200+ over the next 2 weeks
