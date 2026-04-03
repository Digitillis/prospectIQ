# ProspectIQ — Naming Analysis & Rename Guide
> **Author:** Avanish Mehrotra & Digitillis Architecture Team
> **Date:** 2026-04-02
> **Purpose:** Brand name evaluation, alternatives, and technical rename scope

---

## 1. Assessment of "ProspectIQ"

**Verdict: Works as an internal codename. Does not work as a standalone commercial brand.**

### Why It Falls Short

**"IQ" suffix is saturated.**
Dozens of B2B SaaS products use the X+IQ pattern — SalesIQ, LeadIQ, DemandIQ, UserIQ. The suffix signals "smart tool" generically and communicates nothing distinctive about the product.

**"Prospect" is too literal and too limiting.**
The product does far more than prospecting — signal intelligence, qualification, conversation management, post-meeting tracking, content generation. As the platform expands, the name constrains the brand narrative and requires constant clarification ("it's not just a prospecting tool").

**It doesn't own a position.**
Nothing in "ProspectIQ" communicates manufacturing depth, signal-triggered timing, or full-cycle pipeline differentiation. A competitor could name themselves ProspectIQ Pro and create immediate confusion.

**Crowded namespace.**
At least two other companies operate under variations of this name in the sales tools space.

---

## 2. What the Name Should Do

- Suggest intelligence and precision — not just "finding leads"
- Feel authoritative to a VP Sales buyer — not startup-cute
- Work as the product expands beyond manufacturing to other B2B verticals
- Be short (2–3 syllables), distinctive, and spellable after hearing it once
- Work cleanly on a `.ai` or `.io` domain

---

## 3. Name Options

### Intelligence That Reveals What's Hidden

**Revelo**
From the Latin *revelare* — to reveal or uncover. The product reveals deep intelligence about buyers that others can't see. Clean three syllables, action-oriented, entirely distinctive in the market.
- Domain: `revelo.ai`
- Tone: Modern, purposeful, slightly elevated

**Tessera**
Latin for a single tile in a mosaic. The metaphor: ProspectIQ assembles fragmented signals (job postings, tech stack, news, engagement, competitor activity) into a complete picture of a buyer. Sophisticated, unique, memorable.
- Domain: `tessera.ai`
- Tone: Intellectual, precise, differentiated

**Infera**
From *infer* — the platform draws conclusions from signals rather than just displaying raw data. Hints at AI reasoning layered on top of data collection.
- Domain: `infera.ai`
- Tone: Technical, intelligent, modern

---

### Precision and Calibration

**Caliber**
Already a strong English word meaning both precision measurement and quality level. "High-caliber intelligence." Immediately understood by any VP Sales buyer with zero explanation. No brand ambiguity.
- Domain: `caliber.ai`
- Tone: Authoritative, confident, premium

**Acuitas**
Latin for sharpness or keenness of perception. Sophisticated, entirely distinctive in the B2B software market, says exactly what the platform does — it sharpens how sales teams see their buyers.
- Domain: `acuitas.ai`
- Tone: Intellectual, premium, enterprise-grade

**Axara**
Axis (the central line of orientation) + -ara. The platform is the axis around which the GTM motion is oriented. Short, clean, invented, no conflicting brands in the space.
- Domain: `axara.ai`
- Tone: Modern, neutral, scalable across verticals

---

### Signal and Timing

**Presage**
Foreknowledge — identifying buying intent before it becomes obvious. What good intelligence does: it presages the conversation. Slightly elevated vocabulary that works well for a premium B2B product at the $3,500+/mo price point.
- Domain: `presage.ai`
- Tone: Confident, strategic, premium

**Ferox**
Latin for bold, fierce, spirited. Very short, punchy, immediately distinctive. Suggests the product has energy and intent behind it — active intelligence, not passive data.
- Domain: `ferox.ai`
- Tone: Direct, assertive, memorable

---

## 4. Recommendation

| Name | Best For | Domain | Risk |
|---|---|---|---|
| **Caliber** | Immediate comprehension, zero explanation needed | `caliber.ai` | Common English word — verify trademark availability |
| **Revelo** | Distinctive brand with strong meaning, scales well | `revelo.ai` | Minimal — relatively clean namespace |
| **Tessera** | Brand story matters, sophisticated buyer | `tessera.ai` | Minimal — unique in software space |
| **Presage** | Premium positioning, strategic positioning | `presage.ai` | Verify domain + trademark |
| **Acuitas** | Most distinctive, most defensible trademark | `acuitas.ai` | Requires brand education (invented word) |

**Top pick if comprehension is the priority:** Caliber — a VP Sales buyer reads it and understands the positioning instantly.

**Top pick if brand distinctiveness is the priority:** Revelo or Tessera — neither carries limiting associations, both scale cleanly as the product expands beyond manufacturing.

**Names to avoid:** Anything with "Prospect" in it, anything ending in -IQ/-ly/-ify (overused patterns), anything that could be confused with a manufacturing equipment brand.

---

## 5. Technical Rename Scope

### Difficulty: Low

The codebase uses "ProspectIQ" almost entirely in comments, display strings, and email templates. None of the actual logic, routing, or data layer uses the name as an identifier. A rename carries essentially zero functional risk.

### What Needs to Change

| Category | Files / Location | Effort |
|---|---|---|
| Code comment headers | ~100 Python files (first-line docstrings) | 10 min — global find-replace |
| Email templates | `backend/app/core/notifications.py` — 20+ display strings | 30 min — targeted replacement |
| Email sender address | `notifications@prospectiq.ai` in `notifications.py` | Requires new domain + Resend verification |
| LLM prompt string | `backend/app/core/thread_coordinator.py` — one instance | 5 min |
| Frontend localStorage keys | `prospectiq_guide_dismissed`, `prospectiq_notification_prefs` | 10 min — find-replace in TSX |
| Download filename | `prospectiq_import_template.csv` in `dashboard/app/import/` | 2 min |
| Default campaign name | `prospectiq_discovery` in `backend/scripts/import_cli.py` | 2 min |
| `package.json` name | `prospectiq-dashboard` | 2 min |
| Root folder name | `/prospectIQ/` on local disk | `mv` + update git remote |
| Railway project name | Railway dashboard | 5 min |
| Vercel project name | Vercel dashboard | 5 min |
| Supabase project name | Supabase dashboard | 5 min |
| Docs and memory files | 60+ `.md` files | 20 min — global find-replace |

### What Does NOT Need to Change

- **Database table names** — none reference the product name
- **Environment variables** — no `PROSPECTIQ_` prefix pattern anywhere in the codebase
- **API route paths** — no product name in any URL
- **Python module/import paths** — all under `backend/app/`, fully name-agnostic
- **Supabase schema** — neutral naming throughout (`companies`, `contacts`, `workspaces`)
- **Git history** — old commits retain the old name; this is normal and expected

### Email Domain — Not a Hard Dependency

`notifications@prospectiq.ai` references a domain that is **not live and not yet registered**. This removes what would otherwise be the only item with real lead time.

The email sender update is a simple string change:
1. Purchase the new domain for the chosen name
2. Configure DNS + MX records and verify with Resend (~24 hours propagation)
3. Update `_DEFAULT_FROM` constant in `notifications.py`

Because no live email traffic runs through `prospectiq.ai`, there is no migration, no active sender reputation to preserve, and no user-facing disruption during the transition.

### Recommended Sequence

1. **Decide the name**
2. **Do the code rename** (2–3 hours) — global find-replace + targeted review
3. **Rename external services** — Railway, Vercel, Supabase (30 min)
4. **Purchase the new domain** and configure Resend sender verification
5. **Update `_DEFAULT_FROM`** once domain is verified
6. **Smoke test** email notifications end-to-end

**Total wall-clock time:** A few hours of active work + ~24 hours waiting for DNS propagation. No blocking dependencies.

---

*Copyright 2026 Digitillis. All rights reserved. Author: Avanish Mehrotra*
