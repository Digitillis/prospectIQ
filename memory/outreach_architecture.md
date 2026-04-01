---
name: Outreach Architecture — ProspectIQ owns everything
description: ProspectIQ is the orchestration layer. Instantly is delivery rail only. Never attach leads/accounts in Instantly UI.
type: feedback
---

ProspectIQ owns the full outreach stack end-to-end:
- Sequences (built in ProspectIQ sequence builder — 7 campaign templates copied from Instantly as starting structure)
- Lead groups / segments (prospects clustered in ProspectIQ, attached to campaigns in ProspectIQ)
- Personalized messages (OutreachAgent generates from research + hooks + persona)
- HITL approval (ProspectIQ approval queue)
- Send logic (ProspectIQ engagement agent calls Instantly API as delivery rail)

**Instantly's role:** Email delivery infrastructure only. Warmed inboxes. API endpoint for sending. Nothing else.

**Never:** Attach leads in Instantly UI. Attach email accounts to Instantly campaigns directly. Create lead pools in Instantly. Route prospects through Instantly sequences manually.

**The 7 Instantly campaigns (mfg-vp-ops, mfg-plant-manager, mfg-director-ops, mfg-general, mfg-maintenance-leader, fb-vp-ops, fb-maintenance) are TEMPLATES only** — their 6-step structure and gap timing gets copied into ProspectIQ's sequence builder. They sit idle in Instantly.

**Why:** We decided ProspectIQ generates personalized messages per-prospect using research + personalization_hooks + trigger events + contact persona. Generic Instantly sequences don't fit this model. ProspectIQ is being built as a standalone AI-native outbound intelligence product.

**How to apply:** Any time outreach, campaigns, or sending comes up — the answer is ProspectIQ UI + engagement agent → Instantly API. Never Instantly UI configuration.
