# ProspectIQ — Infrastructure Configuration

> Single source of truth for all commercial tooling, subscriptions, and domains.
> Review renewal dates monthly. Cancel or downgrade before the flagged dates below.

Last updated: 2026-03-31

---

## CRITICAL EXPIRY ALERTS

| Item | Action Required | Deadline |
|------|----------------|----------|
| **Instantly Credits (SuperSearch)** | Use all 4,100 credits before cancellation | **2026-04-27** |
| **Instantly Email Outreach** | Upgrade to Hypergrowth before first sequences launch | **2026-04-20 (next renewal)** |

---

## Email Outreach

### Instantly — Email Outreach Plan
| Field | Value |
|-------|-------|
| Plan | Growth ($47/month) |
| Contacts | 1,000 active |
| Emails/month | 5,000 |
| Warmup slots | Included |
| Next renewal | **2026-04-20** |
| Action at renewal | Monitor daily performance. Upgrade to Hypergrowth ($97/month) when active contacts approach 800 or monthly email volume approaches 4,000. Do not upgrade on a fixed date — upgrade when capacity is actually needed. |
| URL | instantly.ai |

### Instantly — Credits (SuperSearch / Lead Finder)
| Field | Value |
|-------|-------|
| Plan | Growth Credits ($47/month) |
| Credits remaining | ~4,100 |
| Cancellation date | **2026-04-27** |
| Action | **USE ALL CREDITS BEFORE THIS DATE, THEN CANCEL** |
| Planned usage | 5 search batches: mfg1, mfg2, mfg3, mfg8, pmfg1 (~800 leads each) |
| Note | Credits do not roll over. After expiry, switch to Apollo-native discovery via ProspectIQ pipeline. |

---

## Domains

All domains registered at **Porkbun** (~$11.08/year each). Renew annually.

| Domain | Purpose | Registered | Renewal Date | Annual Cost |
|--------|---------|-----------|--------------|-------------|
| trydigitillis.com | Outreach mailbox domain 1 | 2026-03-31 | **2027-03-31** | $11.08 |
| getdigitillis.com | Outreach mailbox domain 2 | 2026-03-31 | **2027-03-31** | $11.08 |
| usedigitillis.com | Outreach mailbox domain 3 | 2026-03-31 | **2027-03-31** | $11.08 |
| meetdigitillis.com | Outreach mailbox domain 4 | 2026-03-31 | **2027-03-31** | $11.08 |

**Total domain cost: $44.32/year**

DNS to configure on each domain (after Google Workspace setup):
- MX records → Google Workspace mail servers
- SPF: `v=spf1 include:_spf.google.com ~all`
- DKIM: generate per domain in Google Admin Console → Apps → Google Workspace → Gmail → Authenticate email
- DMARC: `v=DMARC1; p=none; rua=mailto:dmarc@digitillis.com`

---

## Email Infrastructure

### Google Workspace
| Field | Value |
|-------|-------|
| Plan | Business Starter ($8.40/user/month — Flexible) |
| Users | 8 (2 mailboxes per domain × 4 domains) |
| Monthly cost | **$67.20/month** |
| Billing cycle | Monthly (Flexible — no annual commitment) |
| First billing | 2026-04-14 (trial ends) |
| Next review | 2026-05-01 |
| Admin console | admin.google.com |

**Mailbox allocation (2 per domain) — all created 2026-03-31:**
```
trydigitillis.com    → avanish@trydigitillis.com (existing), hello@trydigitillis.com
getdigitillis.com    → avanish@getdigitillis.com, hello@getdigitillis.com
usedigitillis.com    → avanish@usedigitillis.com, hello@usedigitillis.com
meetdigitillis.com   → avanish@meetdigitillis.com, hello@meetdigitillis.com
```

**Warmup schedule:**
- Start: immediately after DNS propagation (~48h after domain purchase)
- Ramp: 30 emails/day per mailbox, 50%+ reply rate via Instantly warmup pool
- Minimum warmup: 3 weeks before any cold sends
- Target send-ready date: ~2026-04-21

---

## Database

### Supabase (ProspectIQ)
| Field | Value |
|-------|-------|
| Plan | Free tier (current) |
| Project | prospectiq |
| Region | us-east-1 |
| Renewal | N/A (free tier) |
| Upgrade trigger | >500MB DB size or >2 concurrent connections sustained |
| Action | Upgrade to Pro ($25/month) if hitting limits |

**Migrations applied:**
- [x] Migration 010 — contact state machine, Instantly fields, outreach_state_log — done 2026-03-31
- [x] Migration 011 — company_intent_signals table, company intent score columns — done 2026-03-31
- [x] Migration 012 — linkedin_touchpoints table — done 2026-03-31
- [x] Migration 013 — ab_test_events, analytics_snapshots — done 2026-03-31

---

## Apollo.io

| Field | Value |
|-------|-------|
| Plan | (confirm current plan) |
| Used for | Company + contact enrichment via ProspectIQ DiscoveryAgent |
| API key | Set in `.env` as `APOLLO_API_KEY` |
| Rate limits | Respect pages_per_tier=5 in icp.yaml |
| Note | Primary discovery source. Instantly SuperSearch used only for supplemental leads before credits expire. |

---

## Monthly Cost Summary

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| Google Workspace (8 users) | $67.20 | $8.40/user × 8, Flexible plan |
| Instantly Email Outreach | $47.00 → $97.00 | Upgrade at Apr 20 renewal |
| Instantly Credits | $47.00 | **CANCEL by Apr 27** |
| Domains (4 × Porkbun) | $3.69 | Amortized ($44.32/year) |
| Supabase | $0 | Free tier |
| **Total (current)** | **$161.20/month** | |
| **Total (post-upgrade, post-cancel)** | **$167.89/month** | After Apr 27 |

---

## Pending Setup Checklist

### Domains & DNS
- [x] Complete Porkbun domain purchase (cart: $44.32) — done 2026-03-31
- [x] Set up Google Workspace account — Business Starter, Flexible, active 2026-03-31
- [x] Add all 4 domains to Google Workspace (secondary domains) — done 2026-03-31
- [x] Configure MX records at Porkbun for all 4 domains — smtp.google.com prio 1, done 2026-03-31
- [x] Generate and configure DKIM per domain in Google Admin — records added to Porkbun 2026-03-31, awaiting propagation
- [x] Set SPF records at Porkbun for all 4 domains — done 2026-03-31
- [x] Set DMARC records at Porkbun for all 4 domains — p=none, rua=dmarc@digitillis.com, done 2026-03-31
- [ ] Verify email delivery on all 8 mailboxes

### Instantly
- [x] Connect all 8 mailboxes to Instantly — done 2026-03-31
- [x] Enable warmup on all 8 mailboxes — started 2026-03-31, send-ready ~2026-04-21
- [ ] Run 5 SuperSearch batches before 2026-04-27 (mfg1, mfg2, mfg3, mfg8, pmfg1)
- [ ] Build 7 outreach sequences (mfg-vp-ops, mfg-maintenance-leader, mfg-plant-manager, mfg-director-ops, fb-vp-ops, fb-maintenance, mfg-general)
- [ ] Upgrade to Hypergrowth plan when active contacts approach 800 or monthly volume approaches 4,000 — monitor daily, do not upgrade on fixed date
- [x] Set `INSTANTLY_SEQ_*` environment variables in ProspectIQ `.env` — done 2026-03-31 (7 campaigns mapped)
- [ ] Register Instantly webhook → `/webhooks/instantly` — **Paywalled (Hyper Growth). Using polling workaround instead: `run_poll_instantly.py`**

### ProspectIQ Pipeline
- [x] Apply Supabase migrations 010–013 — done 2026-03-31
- [x] Run `python -m backend.scripts.backfill_personas` — done 2026-03-31: 6 removed, 63 classified, 728 re-scored
- [ ] Run ProspectIQ discovery mfg-wave3 (mfg1 first)
- [ ] Set up `daily_outreach.py` cron (weekdays 8am CT)
- [x] Fix corrupted Apollo contact: `DELETE FROM contacts WHERE title ILIKE '%Search Terms%'` — done 2026-03-31
