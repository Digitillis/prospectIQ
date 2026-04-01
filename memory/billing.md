---
name: Billing & Stripe Setup
description: Stripe products needed, tier plan config, price IDs are placeholders
type: project
---

## Tiers (defined in `backend/billing_core/tier_plans.py`)

| Tier | Monthly | Annual | Companies/mo | Seats |
|------|---------|--------|-------------|-------|
| Starter | Free | — | 500 | 1 |
| Growth | $299 | $239.20/mo ($2,870.40/yr) | 2,000 | 5 |
| Scale | $799 | $639.20/mo ($7,670.40/yr) | 10,000 | 15 |
| API | Usage-based (metered) | — | Unlimited | — |

## Stripe Products to Create

1. **ProspectIQ Growth** — monthly ($299) + annual ($2,870.40) prices
2. **ProspectIQ Scale** — monthly ($799) + annual ($7,670.40) prices
3. **ProspectIQ API** — metered price (meter: `companies_researched` or `outreach_actions`)

Starter is free — no Stripe product needed.

## After Creating Products
Update `billing_core/tier_plans.py`:
- `growth.price_id` → monthly price ID
- `growth.annual_price_id` → annual price ID
- `scale.price_id` → monthly price ID
- `scale.annual_price_id` → annual price ID
- `api.price_id` → metered price ID

## Env Vars Needed
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
APP_BASE_URL=https://app.prospectiq.ai
```

## Webhook
Register in Stripe dashboard: `https://app.prospectiq.ai/api/billing/webhooks/stripe`

Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
