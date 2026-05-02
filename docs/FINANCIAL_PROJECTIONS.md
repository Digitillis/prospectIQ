# ProspectIQ — Financial Projections & Actuals Tracker

> Shoestring budget. Self-funded. Every dollar must earn its keep.
> Last updated: 2026-05-02

---

## Model Routing Policy (Approved 2026-05-02)

| Task | Model | Rationale |
|---|---|---|
| Research — low firmographic PQS (<20) | Haiku | ~90% of companies. Triage-level task. |
| Research — high firmographic PQS (≥20) | Sonnet | ~10% of companies. Full intelligence extraction. |
| Research web search augmentation | **DISABLED** | $0.098/call vs $0.013/Perplexity. No reply data to justify 7.5x premium. Re-enable when reply rate proves ROI. |
| Draft — step-1 cold opens | **Sonnet** | First impression. User cannot uplift email content. Quality drives reply rates. |
| Draft — step-2 and step-3 follow-ups | **Haiku** | Formulaic. Prospect has context. User scans for anomalies only. |
| Draft quality scorer | Haiku | Classification task. Switched from Sonnet. |
| LLM qualification gates (persona/fit/intent) | Sonnet | Requires reasoning. Sparingly used. |
| Reply classification | Haiku | Correct. |
| Title classification | Haiku | Correct. |
| Daily report | Haiku | Correct. |

**Trigger to revisit step-1 model:** If step-1 draft user-approval rate drops below 40% for 2 consecutive weeks vs prior Sonnet baseline, investigate and consider reverting step-1 to Sonnet.

**Trigger to re-enable web search:** ≥500 sends under this regime + measured reply rate + rate below 2%. Even then: PQS ≥20 only, capped at 20 calls/day.

---

## Cost Basis (Empirical, from api_costs table — May 2026)

| Model | Avg input tokens | Avg output tokens | Cost/call |
|---|---|---|---|
| `claude-sonnet-4-6` | 1,994 | 1,069 | $0.0220 |
| `claude-haiku-4-5-20251001` | 1,500 | 600 | $0.0036 |
| `claude-sonnet-4-6+web_search` | — | — | $0.0982 (DISABLED) |
| Perplexity `sonar-pro` | — | — | $0.0130/query |
| Apollo `people_match` | — | — | $0.0088/credit (flat plan: $114/mo) |

---

## Planned Costs by Scale

Pipeline assumptions:
- Sequence depth: 3 steps per company (1 research → 3 draft attempts)
- Draft approval rate: 57% (will improve as prompt quality improves)
- Apollo: flat $114/month plan, 4,000 credits/month included

| Volume | Claude/mo | Perplexity/mo | Apollo | Infra | **Total/mo** |
|---|---|---|---|---|---|
| 50 sends/day (current) | $12 | $6 | $114 | $52 | **$184** |
| 150 sends/day (1-month ramp) | $36 | $20 | $114 | $54 | **$224** |
| 300 sends/day (2-month target) | $73 | $39 | $114 | $57 | **$283** |
| 450 sends/day (full target) | $109 | $58 | $114 | $64 | **$345** |

**Budget cap: $150/month Anthropic API.** Scheduler pauses research + draft generation at 80% of cap.

---

## Month-by-Month Actuals

### Historical (from api_costs + billing screenshots)

| Month | Claude API | Apollo plan | Perplexity | Infra | Total | Sends | Cost/send |
|---|---|---|---|---|---|---|---|
| Feb 2026 | $1.20 | $114 | ~$0 | $50 | ~$165 | ~0 | — |
| Mar 2026 | $7.50 | $114 | ~$1 | $50 | ~$173 | ~0 | — |
| Apr 2026 | $33.60 | $114 | $2 | $50 | ~$200 | 192* | ~$1.04 |
| May 2026 (MTD) | $73.55 | $114** | $0.46 | $50 | ~$238 | 0 (new) | — |

*192 cumulative sends; most executed in April.
**Apollo billing period Apr 27–May 27; 729/6,050 credits used as of May 2.

### May 2026 — Planned vs Actual

| Week | Planned Claude | Actual Claude | Variance | Planned sends | Actual sends |
|---|---|---|---|---|---|
| May 1–7 | $12 | $73.55 (MTD) | **+$61.55 (web_search anomaly)** | ~50 | 0 (window Mon) |
| May 8–14 | $12 | — | — | ~50 | — |
| May 15–21 | $12 | — | — | ~50 | — |
| May 22–31 | $15 | — | — | ~60 | — |
| **May total** | **$51** | — | — | **~210** | — |

> Week 1 variance explained: web_search triggered 570 times on May 2 before cap was implemented. Fix applied May 2 (disabled web_search). Should not recur.

---

## Waste Identified & Eliminated

| Item | Old cost | New cost | Monthly saving at 450/day |
|---|---|---|---|
| Web search augmentation (all high-PQS) | $0.0982/call × 570/day | $0 (disabled) | ~$1,400 |
| Draft Sonnet → Haiku | $0.0220/call | $0.0036/call | ~$310 |
| Separate draft scorer call (Sonnet) | $0.0220/call | merged into draft (Haiku) | ~$310 |
| **Total eliminated** | | | **~$2,020/mo at 450/day** |

---

## Trigger Events (Re-enable web_search)

Web search will be re-evaluated when ALL three conditions are met:
1. At least 500 emails sent under the Haiku-only regime
2. Measured reply rate available (minimum 2 weeks of data)
3. Reply rate is below 2% — indicating personalization may need a boost

Even then: enable only for companies with firmographic PQS ≥ 20, capped at 20 calls/day max.

---

## Open Questions / Review Points

- [ ] Apollo plan: 5,308 `people_match` calls tracked in api_costs vs 729 credits this billing period — investigate rollover or prior-plan credits
- [ ] Perplexity plan: confirm current tier and rate limit to ensure research agent won't be throttled at 150 companies/day
- [ ] Draft approval rate improvement target: get from 57% → 70%+ by refining Haiku prompts — reduces draft calls needed per send
- [ ] Railway costs: confirm actual monthly spend (estimate $50, may be lower)
