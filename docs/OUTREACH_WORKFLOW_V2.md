# ProspectIQ — Outreach Workflow V2: Natural Relationship Building

> **Status**: Design for approval
> **Principle**: Every touchpoint should feel like a genuine human decision, not step N of an automated sequence.

---

## The Core Problem With Sequences

Traditional outreach sequences (Email Day 0, LinkedIn Day 2, Email Day 5) fail because prospects can reverse-engineer the playbook. The moment someone thinks "this is a sequence," trust is dead.

**The fix: Don't sequence channels. Sequence relationships.**

Instead of "touch 1, touch 2, touch 3" → think "introduction, curiosity, value, social proof, ask." Each stage has a natural channel. The channel follows the relationship stage, not a calendar.

---

## The Relationship Arc (5 Stages)

```
Stage 1: RECOGNITION    — "I know who you are and what you do"
         → LinkedIn connection note
         → Channel: LinkedIn only
         → Personalization: Company-specific fact from research

Stage 2: CURIOSITY       — "I'm genuinely curious about your perspective"
         → LinkedIn opening DM (question, not pitch)
         → Channel: LinkedIn only
         → Personalization: Role-specific question about their actual process

Stage 3: VALUE           — "Here's something you might find useful"
         → LinkedIn DM OR Email (depends on whether LinkedIn worked)
         → Channel: Whichever they're responsive on
         → Personalization: Industry insight, data point, or framework relevant to their sub-sector

Stage 4: RELEVANCE       — "Others in your position handle this differently"
         → Email (if LinkedIn didn't convert) OR LinkedIn (if connected)
         → Channel: The one with signal
         → Personalization: Reference how similar companies (same NAICS, same size) approach the problem

Stage 5: ASK             — "Would a 15-minute call be worth your time?"
         → Same channel as Stage 4
         → Channel: Stay where they're engaged
         → Personalization: Specific to what you've learned about them across stages 1-4
```

---

## Channel Selection Logic (Revised)

### Who Gets LinkedIn vs. Email

| Scenario | Channel | Why |
|---|---|---|
| Has LinkedIn URL, no email | LinkedIn only | Only option |
| Has email, no LinkedIn | Email only | Only option |
| Has both, VP/Director level | LinkedIn first | Warmer, higher acceptance for senior titles |
| Has both, Manager level | Email first | Managers are less active on LinkedIn |
| Has both, already a 2nd-degree connection | LinkedIn first | Shared connection = higher acceptance |
| Has both, company has 2+ contacts | LinkedIn to primary, email to secondary (staggered by 14 days) | Multi-thread without collision |

### Multi-Contact Company Rules

This is where most systems fail. Two people at the same company comparing notes is fatal.

**Rule: Never contact two people at the same company via the same channel in the same week.**

| Contact 1 | Contact 2 | Timing |
|---|---|---|
| LinkedIn connection Day 0 | Nothing until Day 14 | VP Ops gets LinkedIn, VP Quality waits |
| LinkedIn DM Day 5 | LinkedIn connection Day 14 | Stagger by 14 days minimum |
| If Contact 1 responds | Don't contact Contact 2 | One conversation per company at a time |
| If Contact 1 goes silent (Day 21+) | Email Contact 2 | Different channel, different angle, 3-week gap |

---

## Where This System Will Fail (And Fixes)

### Failure Mode 1: Reply Lag
**Problem**: You send a LinkedIn DM Monday. They reply Wednesday. But the system already queued an email for Tuesday.
**Fix**: Before any send, the system checks for activity in the last 48 hours across ALL channels. If any interaction (sent or received) exists in the last 48h, delay the next touch by 3 days. This is a real-time check, not a pre-scheduled rule.

### Failure Mode 2: Multi-Contact Cross-Talk
**Problem**: VP Food Safety and VP Operations at the same company both receive outreach. They mention it to each other at a meeting.
**Fix**: Company-level send lock. When any contact at a company receives outreach (LinkedIn or email), the entire company is locked for 14 days. Only one active outreach thread per company at a time.

### Failure Mode 3: Content Echo
**Problem**: Your LinkedIn DM says "How do you handle CCP monitoring?" and your email subject is "Quick question about your CCP monitoring." They're clearly the same campaign.
**Fix**: Each stage uses a DIFFERENT angle, not a different version of the same angle.
- LinkedIn: Ask about their PROCESS ("How do you handle...")
- Email (if needed later): Share an INSIGHT ("67% of food manufacturers fail this audit point...")
- Never reference the other channel. Never say "I reached out on LinkedIn" in an email.

### Failure Mode 4: Timing Patterns
**Problem**: Every touchpoint arrives exactly 3 or 7 days apart. Prospects notice the pattern.
**Fix**: Add randomized jitter. Instead of "Day 7," use "Day 5-9" (random within range). The system picks a random day within the window. This breaks the pattern that makes sequences feel automated.

### Failure Mode 5: Stale Research
**Problem**: Research was done 3 weeks ago. The company announced a major recall since then. Your "How's compliance going?" DM arrives the day after their recall news.
**Fix**: Before generating any outreach message, check if the company's last research date is > 14 days old. If so, flag for re-research or at minimum note "research may be stale" in the quality check. For F&B companies specifically, a pre-send check against the FDA recall database would prevent embarrassing timing.

### Failure Mode 6: LinkedIn Connection Ignored ≠ Not Interested
**Problem**: They didn't accept your connection. You assume they're not interested and move to email. But they just don't check LinkedIn often.
**Fix**: Connection request ignored for 7 days doesn't mean "rejected." It means "hasn't seen it." Wait 14 days (not 7) before switching to email. Some VPs check LinkedIn once a week. The system should also check: did they VIEW your profile? If yes + didn't accept → they looked and passed. If no profile view → they probably just didn't see it.

### Failure Mode 7: Referral Collision
**Problem**: A food safety consultant introduces you to Company X. But Company X is already in your cold outreach pipeline.
**Fix**: When logging a warm intro (manual interaction type), the system should immediately check if that company is in any active sequence. If yes: CANCEL the cold sequence, mark the company as "warm_intro" status, and switch to a completely different (warmer, shorter) follow-up sequence. Warm intros should never collide with cold outreach.

### Failure Mode 8: Channel Preference Drift
**Problem**: They accepted your LinkedIn connection and responded to your DM positively. But your system switches to email for the "value" stage because that's how the sequence is configured.
**Fix**: Once a prospect engages on a channel, STAY on that channel. Don't switch to email because the sequence says so. The channel follows the relationship, not the calendar. If they're talking to you on LinkedIn, keep talking on LinkedIn.

---

## Personalization Framework (5 Layers)

Generic personalization ("Hi {first_name}") is worthless. Here's what actual personalization looks like at each layer:

### Layer 1: Company-Level (from Apollo + Research)
- What they manufacture (products, processes)
- Where they're located (city, state — reference local context)
- Company size and growth trajectory (hiring signals from Apollo)
- Recent news (expansion, recall, new facility, leadership change)

### Layer 2: Role-Level (from persona classification)
- VP Food Safety: FSMA compliance, FDA audits, CCP documentation, recall prevention
- VP Operations: OEE, downtime costs, maintenance approach, throughput
- VP Engineering: Equipment selection, automation, process optimization
- Plant Manager: Day-to-day floor challenges, staffing, shift management
- Maintenance Director: CMMS frustrations, reactive vs. predictive, spare parts

### Layer 3: Sub-Sector Level (from tier classification)
- Meat processing: USDA/FSIS dual regulation, thermal processing, Listeria risk
- Dairy: Pasteurization CCPs, cold chain, allergen management
- Bakery: Thermal validation, allergen changeover, SQF/BRC certification
- CNC machining: Tool wear, spindle bearing failure, vibration monitoring
- Metal fabrication: Press maintenance, die wear, weld quality

### Layer 4: Timing Level (from research pain signals)
- Recently hired a digital transformation role → budget allocated, looking for solutions
- Recent plant expansion → new equipment, scaling challenges
- Recent recall or FDA warning → compliance is top of mind RIGHT NOW
- Workforce reduction → need to do more with less → automation angle
- Recent M&A → integrating systems, standardizing processes

### Layer 5: Competitive Level (from research existing_solutions)
- No existing AI/ML solution → greenfield, education-focused messaging
- Has CMMS (Maximo, UpKeep) → "complement, don't replace" positioning
- Has IoT sensors → "you have the data, we add the intelligence" angle
- Has a competitor (Uptake, Augury) → DO NOT OUTREACH (suppressed)

### How Personalization Maps to Each Stage

| Stage | What's Personalized | Example |
|---|---|---|
| 1. Connection | Company fact + what you do (5 words) | "Noticed Daybreak Foods does egg products processing. I work on AI for food safety compliance." |
| 2. Question | Role-specific process question | VP Food Safety: "How does Daybreak handle CCP documentation across your processing lines? Still paper-based?" |
| 3. Value | Sub-sector data point | "67% of egg processors cite temperature monitoring gaps as their top 483 trigger. Curious if that matches your experience." |
| 4. Relevance | Similar company reference | "A dairy processor your size cut audit prep from 3 weeks to 2 days by automating their CCP logs. Different product, same documentation challenge." |
| 5. Ask | Specific to what you know | "Based on Daybreak's expansion into [new facility], you're probably scaling your HACCP plan. Would a 15-min walkthrough of automated CCP monitoring be useful?" |

---

## LinkedIn Costs & Recommendation

### Free LinkedIn
- ~100 connection requests/week (LinkedIn's rolling limit)
- Unlimited posting and commenting
- Can only message people you're connected with
- Limited search results
- **Verdict**: Workable for weeks 1-2 if you're strategic about connections

### LinkedIn Premium Business ($59.99/month)
- 15 InMail credits/month (message anyone, even non-connections)
- Unlimited search
- See who viewed your profile (buying signal!)
- Business insights on companies
- **Verdict**: Good starting point

### LinkedIn Sales Navigator Core ($99.99/month)
- 50 InMail credits/month
- Advanced lead filters (company size, industry, seniority, job changes)
- Lead recommendations ("similar to your saved leads")
- Real-time alerts on lead activity (job changes, posts, company news)
- See who viewed your profile (90 days vs. 5 on free)
- CRM sync capability
- **Verdict**: The right tool for what you're doing

### My Recommendation: Sales Navigator ($99.99/month)

Here's why the math works:
- 50 InMail credits = 50 messages to non-connections
- At 5% response rate = 2-3 conversations/month from InMail alone
- One pilot ($2,500-$5,000/month) pays for 25-50 months of Sales Navigator
- The "who viewed your profile" feature alone is a gold mine — it tells you who's interested before you even reach out
- Lead alerts tell you when a VP changes jobs → perfect timing for outreach
- Advanced search is better than Apollo for LinkedIn-specific prospecting

**Timing**: Start Sales Navigator when email warmup begins (now). Use weeks 1-2 to build your connection base. When emails start sending in week 3, you'll have 50+ LinkedIn connections providing social proof when prospects Google you.

### What You Get for $99.99/Month

| Capability | How You'll Use It |
|---|---|
| 50 InMails | High-priority targets who ignore connection requests |
| Advanced lead search | Find VP Food Safety at $50M-$200M food manufacturers (more precise than Apollo) |
| Lead alerts | Know when a target changes jobs, posts, or gets mentioned |
| Profile views | See which prospects viewed your profile after outreach (buying signal!) |
| Saved leads | Track your top 100 prospects with real-time activity updates |
| Company insights | Headcount growth, hiring trends, tech stack changes |

### The Profile View Hack

When someone views your LinkedIn profile after receiving your outreach, it's a STRONG buying signal. Sales Navigator shows you who viewed in the last 90 days. ProspectIQ should check this weekly and auto-escalate any prospect who viewed your profile to "warm" status.

This isn't something we can automate (no LinkedIn API for this), but the Daily Cockpit should remind you: "Check Sales Navigator profile views → log any prospects who viewed."

---

## Connection Request Limits

LinkedIn's actual limits (as of 2026):
- **Free**: ~100 connection requests/week (rolling, not hard wall)
- **Premium/Sales Navigator**: Same ~100/week limit (paying doesn't increase this)
- **With a note**: Counts as 1 request. Notes improve acceptance rate by 30-50%.
- **Without a note**: Counts as 1 request. Lower acceptance but faster to send.
- **Penalty for low acceptance**: If < 20% of your requests are accepted, LinkedIn may throttle you

**Best practice**: Send 10/day (50/week), all with personalized notes. This stays well under limits and maintains high acceptance rates.

### InMail vs. Connection Request

| Approach | When to Use |
|---|---|
| **Connection request + note** | Default for everyone. Free. 30-40% acceptance rate with good note. |
| **InMail** | VP/C-suite who ignore connection requests after 14 days. Or when you have a specific, time-sensitive reason. |
| **Group message** | If you're in the same LinkedIn Group. Shows up as a regular message, not InMail. Free. |

**InMail tip**: InMails with < 400 characters get 22% higher response rate than longer ones. Keep them short.

---

## Proposed Sequence Configuration

### Sequence 1: LinkedIn-First (for contacts with LinkedIn URL)

```yaml
linkedin_first:
  name: "LinkedIn-First Relationship Builder"
  description: "Start with LinkedIn, fall back to email only if LinkedIn fails"
  total_steps: 5
  channel_strategy: "linkedin_primary"

  steps:
    - step: 1
      stage: "recognition"
      channel: linkedin
      action: connection_request
      timing: immediate
      max_words: 50
      instructions:
        approach: >
          Reference ONE specific fact about their company.
          State what you work on in 5 words or less.
          No pitch, no ask, just connect.
        personalization: "company_fact + your_role"

    - step: 2
      stage: "curiosity"
      channel: linkedin
      action: direct_message
      timing: "3-5 days after connection accepted"
      timing_jitter_days: 2
      max_words: 80
      prerequisite: "connection_accepted"
      instructions:
        approach: >
          Ask a genuine question about their specific process.
          F&B: Ask about CCP monitoring, FSMA documentation, audit prep
          Mfg: Ask about maintenance approach, downtime tracking, monitoring
          DO NOT mention your product. Just ask.
        personalization: "role_specific_question + sub_sector_context"

    - step: 3
      stage: "value"
      channel: linkedin  # Stay on LinkedIn if they engaged
      channel_fallback: email  # Switch to email if LinkedIn went silent
      action: share_insight
      timing: "5-7 days after step 2"
      timing_jitter_days: 2
      max_words: 120
      instructions:
        approach: >
          Share a specific, valuable data point relevant to their sub-sector.
          Frame it as a peer sharing knowledge, not a vendor pitching.
          If they responded to step 2, reference their answer.
          If switching to email (LinkedIn failed): use a completely different
          angle than the LinkedIn messages. Don't reference LinkedIn.
        personalization: "sub_sector_data_point + timing_signals"

    - step: 4
      stage: "relevance"
      channel: same_as_step_3  # Stay on whatever channel worked
      action: social_proof
      timing: "5-7 days after step 3"
      timing_jitter_days: 2
      max_words: 130
      instructions:
        approach: >
          Reference how a similar company (same size, same sub-sector)
          handles the challenge. Don't fabricate case studies.
          Use training data results or industry benchmarks.
        personalization: "similar_company_reference + competitive_context"

    - step: 5
      stage: "ask"
      channel: same_as_step_3
      action: meeting_request
      timing: "5-7 days after step 4"
      timing_jitter_days: 2
      max_words: 100
      instructions:
        approach: >
          Direct, specific ask. "Would a 15-minute walkthrough be worth
          your time?" Reference something specific you've learned about
          their operation across the previous stages.
          Make it easy to say yes or no.
        personalization: "accumulated_context_from_stages_1_4"
```

### Sequence 2: Email-Only (for contacts without LinkedIn, or LinkedIn-failed)

```yaml
email_only:
  name: "Email-Only Outreach"
  description: "For contacts without LinkedIn, or after LinkedIn was ignored for 14+ days"
  total_steps: 4
  channel_strategy: "email_only"

  steps:
    - step: 1
      stage: "value_first"
      channel: email
      timing: immediate
      max_words: 150
      instructions:
        approach: >
          Lead with a data point or insight relevant to their operation.
          NOT "Hi, I'm Avi from Digitillis." Start with THEIR world.
          One mention of what you do. One low-friction CTA.

    - step: 2
      stage: "relevance"
      channel: email
      timing: "5-7 days after step 1"
      timing_jitter_days: 2
      max_words: 120
      instructions:
        approach: >
          Completely different angle from step 1.
          If step 1 was about their pain → step 2 is about industry data.
          If step 1 was about data → step 2 is about a similar company.

    - step: 3
      stage: "demo_value"
      channel: email
      timing: "5-7 days after step 2"
      timing_jitter_days: 2
      max_words: 130
      instructions:
        approach: >
          Include the Loom demo link (F&B or Mfg version).
          Frame as "90 seconds showing what this looks like in practice."
          Not "watch our demo" — more "I recorded this for shops like yours."

    - step: 4
      stage: "respectful_close"
      channel: email
      timing: "5-7 days after step 3"
      timing_jitter_days: 2
      max_words: 80
      instructions:
        approach: >
          Short. Respectful of their time.
          "I've reached out a few times. If the timing isn't right, no problem.
          If [specific pain point] is something you want to solve, happy to chat."
          Easy to decline gracefully.
```

---

## Summary of Recommendations

1. **LinkedIn first, always** (when LinkedIn URL available). Email is the fallback, not the primary.
2. **One channel at a time**. Never both in the same 14-day window.
3. **One thread per company**. Second contact only after first contact goes completely silent.
4. **Relationship stages, not calendar steps.** The stage determines the channel, not vice versa.
5. **Randomized timing** (jitter ±2 days). Breaks the pattern that exposes automation.
6. **Different angle per touch.** Recognition → Curiosity → Value → Relevance → Ask.
7. **48-hour activity check** before any send. If anything happened in the last 48h, delay.
8. **Invest in Sales Navigator ($99.99/month).** Profile views, InMails, and advanced search are worth 10x the cost.
9. **Start LinkedIn immediately.** Don't wait for email warmup. Build the connection base now.
10. **Every message personalized at 5 layers**: company, role, sub-sector, timing, competitive.
