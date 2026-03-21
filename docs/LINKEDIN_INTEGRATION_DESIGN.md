# ProspectIQ — LinkedIn Integration Design

> **Status**: Design Review
> **Purpose**: Generate personalized LinkedIn messages for each prospect, track LinkedIn touchpoints, and manage the LinkedIn outreach workflow from ProspectIQ — even though actual sending is manual.

---

## Problem Statement

Cold email warmup takes 2+ weeks. LinkedIn is available immediately but requires personalized messages for each contact. Writing 10+ custom connection notes and DMs per day is time-consuming. ProspectIQ already has deep research intelligence on each company — it should generate LinkedIn messages the same way it generates email drafts.

---

## Feature Set

### Feature 1: LinkedIn Message Generation

**What**: Generate 3 personalized LinkedIn messages per contact using existing research intelligence.

| Message Type | Max Words | Tone | CTA | When to Send |
|---|---|---|---|---|
| Connection Request Note | 50 | Casual, peer-to-peer | None — just connect | Immediately |
| Opening DM | 80 | Curious, question-based | Ask about their process | After acceptance (Day 2-3) |
| Follow-up DM | 100 | Value-add, soft CTA | Suggest 15-min call | If they respond (Day 5-7) |

**Rules (different from email):**
- No signature block
- No "Best regards"
- No company pitch in connection note
- Opening DM must be a genuine question, not a pitch
- Follow-up DM can mention Digitillis but only in context of their answer
- Never use em dashes
- Must reference at least 1 specific fact about their company
- F&B contacts: ask about CCP documentation, FSMA compliance, audit prep
- Mfg contacts: ask about maintenance approach, downtime costs, equipment monitoring

### Feature 2: LinkedIn Dashboard Page (`/linkedin`)

**What**: A dedicated page showing all qualified contacts with LinkedIn URLs, their generated messages, copy-to-clipboard functionality, and send status tracking.

**Layout:**

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ LinkedIn Outreach                                           [Generate: 20]  │
│ Personalized messages ready to copy-paste into LinkedIn     [▼ Filter]      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│ Filters: [All] [Not Sent] [Connection Sent] [DM Sent] [Responded]           │
│          Vertical: [All] [F&B] [Manufacturing]                               │
│          Sort: [PQS ↓] [Company A-Z] [Most Recent]                          │
│                                                                              │
│ ┌────────────────────────────────────────────────────────────────────────┐   │
│ │  Greg Hentschel                                              PQS 59  │   │
│ │  VP Engineering — CST Industries (Food Manufacturing)                 │   │
│ │  🔗 linkedin.com/in/greghentschel                    [Open Profile]  │   │
│ │                                                                       │   │
│ │  ┌─ CONNECTION NOTE ──────────────────────────────────────────────┐   │   │
│ │  │ Hi Greg, noticed CST Industries builds bulk storage and       │   │   │
│ │  │ processing systems for food producers. I'm working on AI      │   │   │
│ │  │ compliance tools for the industry. Would love to connect.     │   │   │
│ │  └────────────────────────────────── [📋 Copy] [✏️ Edit] ───────┘   │   │
│ │                                                                       │   │
│ │  ┌─ OPENING DM ──────────────────────────────────────────────────┐   │   │
│ │  │ Thanks for connecting, Greg. Quick question — how does CST    │   │   │
│ │  │ handle CCP monitoring across your processing equipment? I'm   │   │   │
│ │  │ curious whether you've automated any of the FSMA              │   │   │
│ │  │ documentation or if it's still mostly manual logs.            │   │   │
│ │  └────────────────────────────────── [📋 Copy] [✏️ Edit] ───────┘   │   │
│ │                                                                       │   │
│ │  ┌─ FOLLOW-UP DM ───────────────────────────────────────────────┐   │   │
│ │  │ Appreciate the insight, Greg. We actually built something     │   │   │
│ │  │ that automates exactly that — continuous CCP monitoring with  │   │   │
│ │  │ auto-generated FSMA docs. Would a 15-min walkthrough be      │   │   │
│ │  │ worth your time?                                              │   │   │
│ │  └────────────────────────────────── [📋 Copy] [✏️ Edit] ───────┘   │   │
│ │                                                                       │   │
│ │  Status: ○ Not Sent  ● Connection Sent  ○ DM Sent  ○ Responded      │   │
│ │  Notes: [Add a note...]                                    [Save]    │   │
│ │                                                                       │   │
│ │  Research Hooks: "CST does bulk storage for dairy + beverage"         │   │
│ │  Pain Signals: "FSMA compliance burden, manual CCP logs"             │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│ ┌────────────────────────────────────────────────────────────────────────┐   │
│ │  Dan Bennett                                                 PQS 59  │   │
│ │  VP Manufacturing & Operations — AGC Automotive (Mfg)                 │   │
│ │  🔗 linkedin.com/in/danbennett                       [Open Profile]  │   │
│ │                                                                       │   │
│ │  ┌─ CONNECTION NOTE ──────────────────────────────────────────────┐   │   │
│ │  │ Hi Dan, saw AGC Automotive does precision glass components    │   │   │
│ │  │ for auto OEMs. I work on predictive maintenance AI for        │   │   │
│ │  │ manufacturers. Would be great to connect.                     │   │   │
│ │  └────────────────────────────────── [📋 Copy] [✏️ Edit] ───────┘   │   │
│ │  ...                                                                  │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│ Showing 1-20 of 45 contacts with LinkedIn URLs          [← Prev] [Next →]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Feature 3: LinkedIn Status Tracking

**What**: Track where each contact is in the LinkedIn outreach lifecycle.

**Statuses:**
```
not_generated → generated → connection_sent → connection_accepted → dm_sent → responded → meeting_booked
```

**Status changes:**
- `not_generated` → `generated`: Automatic when messages are generated
- `generated` → `connection_sent`: User clicks "Mark Connection Sent"
- `connection_sent` → `connection_accepted`: User clicks "Mark Accepted"
- `connection_accepted` → `dm_sent`: User clicks "Mark DM Sent"
- `dm_sent` → `responded`: User clicks "Mark Responded"
- Any → `meeting_booked`: User clicks "Meeting Booked!"

Each status change logs an interaction in the interactions table for pipeline tracking.

### Feature 4: Daily LinkedIn Queue

**What**: A focused view showing exactly what to do today on LinkedIn.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Today's LinkedIn Actions                                    March 22    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│ 🔵 SEND CONNECTION REQUESTS (10 today)                                  │
│    □ Greg Hentschel — CST Industries (F&B)           [📋 Copy] [Done]  │
│    □ Dan Bennett — AGC Automotive (Mfg)              [📋 Copy] [Done]  │
│    □ Chad Crowley — SunSource (Mfg)                  [📋 Copy] [Done]  │
│    ...7 more                                                             │
│                                                                          │
│ 🟢 SEND OPENING DMs (to accepted connections)                           │
│    □ Kyle Wick — Douglas Dynamics (accepted 2d ago)  [📋 Copy] [Done]  │
│    □ Jarrod Osborn — Waupaca Foundry (accepted 1d)   [📋 Copy] [Done]  │
│    ...                                                                   │
│                                                                          │
│ 🟡 FOLLOW UP (responded to opening DM)                                  │
│    □ Nick Ariens — AriensCo (responded yesterday)    [📋 Copy] [Done]  │
│    ...                                                                   │
│                                                                          │
│ 💬 COMMENT ON POSTS (5 today)                                           │
│    □ Food Safety Magazine — latest post              [Open]             │
│    □ Manufacturing Leadership Council                [Open]             │
│    □ Reliable Plant                                  [Open]             │
│    ...                                                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Feature 5: Generate Button on Actions Page

**What**: Add "Generate LinkedIn Messages" as a 7th agent card on the Actions page.

| Setting | Options |
|---|---|
| Tiers | fb1-fb5, mfg1-mfg3 (same tier pills as other agents) |
| Limit | Default 20, max 50 |
| Vertical | F&B / Manufacturing / Both |
| Regenerate | Checkbox — regenerate messages for contacts that already have them |

### Feature 6: Inline Edit + Custom Notes

**What**: Each generated message can be edited inline before copying. Notes field per contact for tracking conversation context.

- Click "Edit" → message becomes editable textarea
- Click "Save" → persists edited version
- Notes field: free-text, saved per contact, visible on prospect detail page too
- Edited messages persist — regenerating doesn't overwrite edits unless "Regenerate" is checked

### Feature 7: Analytics Integration

**What**: LinkedIn activity feeds into the existing analytics pipeline.

| Metric | Source |
|---|---|
| Connection requests sent | Status change tracking |
| Acceptance rate | Accepted / Sent |
| DM response rate | Responded / DM Sent |
| Meetings from LinkedIn | meeting_booked status |
| LinkedIn vs Email conversion | Compare channels in analytics |

Shows on existing Analytics page as a "LinkedIn" tab alongside Campaigns and Sequences.

---

## Data Model

### No New Tables Required

Uses existing tables with LinkedIn-specific values:

**`outreach_drafts` table** (existing):
- `channel`: `"linkedin"` (existing enum value)
- `sequence_name`: `"linkedin_connection"` / `"linkedin_dm_opening"` / `"linkedin_dm_followup"`
- `sequence_step`: 1, 2, or 3
- `subject`: Not used for LinkedIn (null)
- `body`: The message text
- `approval_status`: `"pending"` → `"approved"` (auto-approved for LinkedIn since it's copy-paste)

**`interactions` table** (existing):
- `type`: `"linkedin_connection"` / `"linkedin_message"` (existing enum values)
- `channel`: `"linkedin"` (existing enum value)
- `metadata`: `{ "linkedin_status": "connection_sent" | "accepted" | "dm_sent" | "responded" }`

**`contacts` table** (existing):
- `linkedin_url`: Already populated from Apollo enrichment
- `status`: Updated when LinkedIn engagement happens

### New Field on Contacts (1 column addition)

```sql
ALTER TABLE contacts ADD COLUMN linkedin_outreach_status TEXT DEFAULT 'not_generated';
-- Values: not_generated, generated, connection_sent, connection_accepted,
--         dm_sent, responded, meeting_booked
```

---

## Prompt Design

### Connection Request Note Prompt

```
Write a LinkedIn connection request note for {contact_name}, {title} at {company_name}.

RULES:
- Maximum 50 words (LinkedIn connection notes are strictly limited)
- DO NOT pitch or sell anything
- Reference ONE specific thing about their company from the research
- Mention what you work on in 5 words or less
- Casual, warm tone — like reaching out to a peer at a conference
- No em dashes, no "I'd love to", no "I came across"

RESEARCH ON {company_name}:
{research_summary}
{personalization_hooks}

VERTICAL CONTEXT:
- If F&B company: mention food safety / quality / compliance angle
- If Manufacturing: mention predictive maintenance / operations angle

OUTPUT: Just the message text, nothing else. No quotes.
```

### Opening DM Prompt

```
Write a LinkedIn DM for {contact_name} at {company_name}. They just accepted your connection request.

RULES:
- Maximum 80 words
- This must be a GENUINE QUESTION about their operation — NOT a pitch
- Start with "Thanks for connecting" or similar acknowledgment
- Ask about a specific challenge relevant to their role:
  - F&B VP Quality/Food Safety: Ask about CCP monitoring, FSMA documentation, audit prep
  - Mfg VP Operations: Ask about maintenance approach, downtime tracking, equipment monitoring
- DO NOT mention Digitillis or any product
- Conversational, like a peer asking for insight

RESEARCH ON {company_name}:
{research_summary}
{pain_signals}

OUTPUT: Just the message text, nothing else.
```

### Follow-up DM Prompt

```
Write a LinkedIn follow-up DM for {contact_name} at {company_name}. They responded to your opening question about {their_topic}.

RULES:
- Maximum 100 words
- Acknowledge their response (even though you don't have it — write generically)
- NOW you can mention what you're building, but frame it as relevant to their answer
- End with a specific, low-friction CTA: "Would a 15-min walkthrough be worth your time?"
- Still conversational, not formal
- No em dashes

THEIR ROLE CONTEXT:
{contact_title} — {persona_type}

COMPANY CONTEXT:
{research_summary}

OUTPUT: Just the message text, nothing else.
```

---

## Navigation & Sidebar

Add to sidebar between "Contacts" and "Activity":

```
🔍 Search
📊 Pipeline
📈 Trends (existing)
⚡ Actions
📋 Approvals
👤 Contacts
💬 LinkedIn          ← NEW
🕐 Activity
...
```

---

## Implementation Estimate

| Component | Effort | Files |
|---|---|---|
| LinkedIn sequence config in YAML | 15 min | `config/sequences.yaml` |
| LinkedIn message generation in outreach agent | 30 min | `backend/app/agents/outreach.py` |
| API endpoint for generation + status tracking | 30 min | `backend/app/api/routes/pipeline.py`, `companies.py` |
| LinkedIn dashboard page | 60 min | `dashboard/app/linkedin/page.tsx` |
| Sidebar nav update | 5 min | `dashboard/app/sidebar.tsx` |
| Daily queue section on LinkedIn page | 30 min | Part of LinkedIn page |
| Migration for contact linkedin_outreach_status | 5 min | `supabase_migrations/` |
| Actions page: add LinkedIn card | 10 min | `dashboard/app/actions/page.tsx` |
| **Total** | **~3 hours** | 7 files |

---

## What This Enables

**Daily LinkedIn workflow (15 minutes):**
1. Open ProspectIQ → LinkedIn page
2. See today's queue: 10 connection requests + 3 opening DMs + 1 follow-up
3. For each: click Copy → switch to LinkedIn → paste → send → click "Done" in ProspectIQ
4. All touches logged automatically in the pipeline

**Compared to without ProspectIQ:**
- Without: Open Apollo → find contact → research company → write custom message → send → track in spreadsheet (5-8 min per contact)
- With ProspectIQ: Copy → Paste → Done (30 seconds per contact)

**10 LinkedIn touches/day goes from 60-80 minutes → 5 minutes.**
