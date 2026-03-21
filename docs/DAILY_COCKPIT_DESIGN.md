# ProspectIQ — Daily Cockpit Design

> **Purpose**: A single page that tells Avanish exactly what to do today, generates the messages he needs, tracks responses/outcomes, and learns from feedback.

---

## The Problem

Right now, running ProspectIQ requires:
1. Going to Actions page → running agents manually
2. Going to Approvals → reviewing drafts
3. Going to LinkedIn → copying messages
4. Tracking responses in your head
5. No single view of "what should I do right now?"

## The Solution: Daily Cockpit (`/today`)

One page. Opens every morning. Shows exactly what to do, in priority order, with every message pre-written and ready to copy/send.

---

## Page Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Good morning, Avanish                                    Friday, March 21   │
│                                                                              │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│ │ 🔥 3        │ │ 📨 5        │ │ 💬 8        │ │ ✅ 12/20    │            │
│ │ Hot Signals │ │ Approvals   │ │ LinkedIn    │ │ Done Today  │            │
│ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SECTION 1: URGENT — Act Now (replies, hot signals)                         │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  🔥 Deli Star Corp replied to your email!                                   │
│     "Interesting timing — we're actually looking at..."                      │
│     [View Full Reply] [Draft Response] [Log Outcome ▼]                      │
│                                                                              │
│  🔥 CST Industries opened your email 4 times in 2 days                     │
│     Contact: Greg Hentschel, VP Engineering                                  │
│     [Send LinkedIn DM] [Call: 555-1234] [Log Outcome ▼]                     │
│                                                                              │
│  ─────────────────────────────────────────────────                          │
│  SECTION 2: APPROVE — Email drafts waiting (5)                              │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  📨 ILLES Foods — "Quick question about your CCP monitoring"                │
│     Quality: 92/100 | F&B | PQS 59                                          │
│     [Preview ▼] [Approve] [Edit] [Reject] [Test Email]                      │
│                                                                              │
│  📨 Daybreak Foods — "FSMA documentation at Daybreak"                       │
│     Quality: 88/100 | F&B | PQS 59                                          │
│     [Preview ▼] [Approve] [Edit] [Reject] [Test Email]                      │
│     ... 3 more                                                               │
│                                                                              │
│  ─────────────────────────────────────────────────                          │
│  SECTION 3: LINKEDIN — Today's touches (8 remaining)                        │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  Send Connection Requests (5 remaining):                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ □ Chad Crowley — VP Engineering, SunSource (Mfg)                     │   │
│  │   "Hi Chad, noticed SunSource does fluid power distribution         │   │
│  │   for industrial OEMs. I work on predictive maintenance AI          │   │
│  │   for manufacturers. Would be great to connect."                    │   │
│  │                                    [📋 Copy] [Open LI] [✓ Done]    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ □ Rebecca Sch*** — VP Food Safety, Daybreak Foods (F&B)             │   │
│  │   "Hi Rebecca, saw Daybreak Foods does egg products processing.     │   │
│  │   I'm building AI compliance tools for food manufacturers.          │   │
│  │   Would love to connect."                                           │   │
│  │                                    [📋 Copy] [Open LI] [✓ Done]    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│  ... 3 more connection requests                                              │
│                                                                              │
│  Send Opening DMs (2 — accepted your connection):                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ □ Kyle Wick — VP Engineering, Douglas Dynamics (accepted 2d ago)    │   │
│  │   "Thanks for connecting, Kyle. Quick question — how does Douglas   │   │
│  │   Dynamics handle condition monitoring on your plow manufacturing   │   │
│  │   lines? Curious if you've moved into any predictive work or       │   │
│  │   if it's still mostly scheduled maintenance."                      │   │
│  │                                    [📋 Copy] [Open LI] [✓ Done]    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Send Follow-up DMs (1 — responded to your opening DM):                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ □ Nick Ariens — President & COO, AriensCo (responded yesterday)    │   │
│  │   "Appreciate the insight, Nick. We actually built something that   │   │
│  │   addresses exactly that — monitors equipment health 24/7 and      │   │
│  │   predicts failures before they happen. Would a 15-min walkthrough │   │
│  │   be worth your time?"                                              │   │
│  │                                    [📋 Copy] [Open LI] [✓ Done]    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ─────────────────────────────────────────────────                          │
│  SECTION 4: COMMENT — Industry posts to engage with (5)                     │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  □ Food Safety Magazine — "New FDA guidance on..."    [Open Post] [✓ Done]  │
│  □ Manufacturing Leadership — "Industry 4.0..."       [Open Post] [✓ Done]  │
│  □ Reliable Plant — "Predictive maintenance..."       [Open Post] [✓ Done]  │
│  □ SQF Institute — "Audit readiness..."               [Open Post] [✓ Done]  │
│  □ SME — "Smart manufacturing..."                     [Open Post] [✓ Done]  │
│                                                                              │
│  ─────────────────────────────────────────────────                          │
│  SECTION 5: PIPELINE — Quick actions                                        │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  243 discovered waiting for research          [Run Research: 10]            │
│  10 researched waiting for qualification      [Run Qualification]           │
│  0 qualified waiting for enrichment           [—]                            │
│  5 drafts pending approval                    [Go to Approvals]             │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SECTION 6: LOG OUTCOMES — What happened today?                             │
│  ─────────────────────────────────────────────────                          │
│                                                                              │
│  Recent interactions needing your feedback:                                  │
│                                                                              │
│  Deli Star Corp — replied to email                                          │
│  Outcome: [Interested ✓] [Not Now] [Not Interested] [Wrong Person] [Bounce]│
│  Notes: [                                                          ] [Save] │
│                                                                              │
│  CST Industries — opened email 4x                                           │
│  Outcome: [Hot — Follow Up] [Warm — Wait] [Ignore]                         │
│  Notes: [                                                          ] [Save] │
│                                                                              │
│  AriensCo — LinkedIn DM response                                            │
│  Outcome: [Interested] [Asked Question] [Not Now] [Not Interested]          │
│  Notes: [                                                          ] [Save] │
│                                                                              │
│  LinkedIn connection requests — accepted today (3):                          │
│  □ Kyle Wick — Douglas Dynamics         [Queue Opening DM for tomorrow]     │
│  □ Brent Blouch — Swagelok             [Queue Opening DM for tomorrow]     │
│  □ Terri Ha*** — Central Valley Meat   [Queue Opening DM for tomorrow]     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Feature Breakdown

### Feature 1: Morning Briefing (Section 1)

**What**: Shows urgent items that need immediate attention — replies, hot buying signals, bounces.

**Data sources:**
- `interactions` table: filter for `email_replied` in last 24h
- Buying signal detector: companies with multi-opens, link clicks
- `engagement_sequences` table: sequences that failed/bounced

**Actions available:**
- View full reply text
- "Draft Response" → generates a reply using Claude (like outreach but in response context)
- "Log Outcome" → dropdown with: Interested, Not Now, Not Interested, Wrong Person, Bounce

### Feature 2: Email Approval Queue (Section 2)

**What**: Inline version of the Approvals page — approve/reject without leaving the cockpit.

**Data source**: `outreach_drafts` where `approval_status = 'pending'`

**Actions**: Same as Approvals page — Approve, Edit, Reject, Test Email

### Feature 3: LinkedIn Action Queue (Section 3)

**What**: Pre-generated LinkedIn messages for today's touches, with copy buttons and status tracking.

**How daily queue is determined:**
- Connection requests: Pick top 5 F&B + 5 Mfg from qualified contacts who have a LinkedIn URL but `linkedin_outreach_status = 'generated'` (not yet sent)
- Opening DMs: Contacts where `linkedin_outreach_status = 'connection_accepted'` and acceptance was 2+ days ago
- Follow-up DMs: Contacts where `linkedin_outreach_status = 'dm_sent'` and they responded

**Actions:**
- Copy message to clipboard
- "Open LI" → opens their LinkedIn profile in new tab
- "Done" → marks as sent, logs interaction, advances linkedin_outreach_status
- Edit message inline before copying

### Feature 4: Industry Comment Queue (Section 4)

**What**: Suggested industry posts to comment on today.

**Implementation**: Static list of industry publication LinkedIn pages, rotated daily. User marks as done.

**Configurable via Settings**: List of LinkedIn pages/accounts to follow for commenting.

### Feature 5: Pipeline Quick Actions (Section 5)

**What**: Summary of pipeline bottlenecks with one-click actions.

**Data source**: Company counts by status from existing pipeline API.

**Actions**: "Run Research: 10", "Run Qualification", "Go to Approvals" — triggers agent runs inline.

### Feature 6: Outcome Logger (Section 6)

**What**: Log what happened with each interaction — the feedback loop that makes the system smarter.

**Outcome types by channel:**

| Channel | Outcomes |
|---|---|
| Email reply | Interested, Not Now, Not Interested, Wrong Person, Bounce, Out of Office |
| Email open (hot signal) | Hot — Follow Up, Warm — Wait, Ignore |
| LinkedIn DM response | Interested, Asked Question, Not Now, Not Interested |
| LinkedIn connection | Accepted (→ queue DM), Ignored (after 7 days) |
| Meeting | Booked, No-Show, Completed — Interested, Completed — Not a Fit |

**What happens when you log an outcome:**
1. Interaction record created with outcome metadata
2. Company status updated (e.g., "Interested" → status becomes "engaged")
3. PQS engagement score bumped
4. Learning outcome recorded (feeds into the Learning agent for pattern analysis)
5. If "Not Interested" → company suppressed from future outreach
6. If "Interested" → Slack notification + priority flag
7. If "Meeting Booked" → company status → "meeting_scheduled"

### Feature 7: Progress Tracker

**What**: "12/20 Done Today" counter in the header. Tracks completed actions across all sections.

**Resets daily at midnight. Gamification element — hit 20/20 every day.**

Daily targets (configurable):
- 5 email approvals
- 5 LinkedIn connection requests
- 3 LinkedIn DMs
- 5 industry comments
- 2 outcome logs
= 20 actions/day

---

## Backend Changes

| Component | Change |
|---|---|
| `GET /api/today` | New endpoint — aggregates all daily actions into one response |
| `POST /api/today/log-outcome` | Log outcome for an interaction |
| `POST /api/today/mark-done` | Mark a LinkedIn/comment action as done |
| `GET /api/today/linkedin-queue` | Get today's LinkedIn messages with copy-ready text |
| LinkedIn message generation | New mode in outreach agent for connection notes + DMs |
| `contacts` table | Add `linkedin_outreach_status` column |
| `dashboard/app/today/page.tsx` | New page — the Daily Cockpit |
| `dashboard/app/sidebar.tsx` | Add "Today" as first nav item with notification badge |

---

## Daily Automation

At midnight (or configurable time), ProspectIQ auto-generates tomorrow's queue:
1. Picks next 10 contacts for LinkedIn connection requests (5 F&B + 5 Mfg)
2. Generates personalized connection notes for each
3. Identifies contacts who accepted connections → generates opening DMs
4. Identifies contacts who responded to DMs → generates follow-up DMs
5. Refreshes industry comment suggestions
6. Calculates pipeline bottleneck summary

This can run as a scheduled job (APScheduler, already in the backend) or on-demand when you open the page.

---

## Implementation Estimate

| Component | Effort |
|---|---|
| `GET /api/today` aggregation endpoint | 45 min |
| Outcome logging endpoints | 30 min |
| LinkedIn message generation (3 message types) | 45 min |
| Daily Cockpit page (`/today`) | 90 min |
| Sidebar update + notification badge | 10 min |
| LinkedIn status tracking on contacts | 15 min |
| Comment queue (static list + done tracking) | 20 min |
| Progress tracker component | 15 min |
| **Total** | **~4.5 hours** |

---

## Cross-Channel Coordination — No Double-Bombing

**Problem**: If you send a LinkedIn connection request on Monday and a cold email on Tuesday to the same person, it looks desperate and coordinated (because it is). Prospects notice.

**Rule: One channel at a time per contact, with cooldown between channel switches.**

### Channel Priority Logic

```
For each contact, the system assigns ONE active channel:

1. If contact has LinkedIn URL + no email → LinkedIn only
2. If contact has email + no LinkedIn → Email only
3. If contact has both:
   a. Start with LinkedIn (warmer, higher response rate)
   b. If LinkedIn connection ignored after 7 days → switch to email
   c. If LinkedIn connection accepted → stay on LinkedIn until DM sequence completes
   d. If LinkedIn DM sequence completes with no response → switch to email (14-day gap)
   e. If email sequence completes with no response → do NOT switch back to LinkedIn
```

### Cooldown Rules

| Scenario | Cooldown Before Next Channel |
|---|---|
| LinkedIn connection sent → email | 7 days minimum (wait for acceptance first) |
| LinkedIn DM sequence complete → email | 14 days (they've seen your name enough) |
| Email sequence complete → LinkedIn | Never (would feel stalky) |
| LinkedIn accepted + DM sent → email | Only after DM sequence completes + 14 days |

### How It's Enforced

1. **Suppression check enhanced**: `is_suppressed()` now checks `active_channel` on the contact. If a contact has `active_channel = 'linkedin'` and you try to generate an email draft, it's blocked.

2. **Contact-level field**: `active_channel` (email | linkedin | none) + `channel_switch_eligible_at` (datetime)

3. **Outreach agent check**: Before generating an email draft, checks if the contact has any LinkedIn activity in the last 14 days. If yes, skips.

4. **LinkedIn generation check**: Before generating LinkedIn messages, checks if the contact has any pending/sent email drafts. If yes, skips.

5. **Daily cockpit visibility**: The Today page shows which channel is active per contact. No option to send via the blocked channel.

### Database Changes

```sql
ALTER TABLE contacts ADD COLUMN active_channel TEXT DEFAULT 'none';
-- Values: none, linkedin, email

ALTER TABLE contacts ADD COLUMN channel_switch_eligible_at TIMESTAMPTZ;
-- NULL = can switch anytime. Set when a channel sequence completes.
```

### UI Indicator

On every contact card (LinkedIn page, Prospect detail, Today page):
```
Channel: 🔵 LinkedIn (active) | ✉️ Email (available Day 28)
```
or
```
Channel: ✉️ Email (active) | 💬 LinkedIn (blocked — email in progress)
```

---

## What This Replaces

| Before | After |
|---|---|
| Open 5 different pages to figure out what to do | One page: `/today` |
| Write LinkedIn messages from scratch | Copy pre-written messages |
| Track outcomes in your head | Log with one click |
| No feedback loop | Every outcome feeds learning agent |
| No daily discipline | Gamified 20-action daily target |
| Manual pipeline management | One-click "Run Research" buttons inline |
