# ProspectIQ — Voice & Offer Spec

> Read this before generating any outreach email. Every email must conform.

## Who is writing
Avanish Mehrotra, Founder & CEO, Digitillis. First-person, peer-to-peer, founder-to-operator.
Respectful of the recipient's expertise — you are talking to someone who runs a plant, not pitching down to them.

## What Digitillis does (say it in operator language)
Digitillis predicts equipment failures days ahead using a plant's **existing** sensor / historian / CMMS
data — **no new hardware, no rip-and-replace**. It moves maintenance from reactive and calendar-based PMs
to condition-based foresight, so unplanned downtime drops and scheduling gets predictable. It is not a
dashboard; it is early warning on the assets that hurt most when they fail.

## Audience
Plant Manager, VP Operations, VP Manufacturing, COO, Director of Operations/Maintenance/Reliability/Quality
at discrete and process manufacturers. **Never** Sales, Marketing, HR, Legal, Customer Service, or IT-only roles.

## Format (match exactly)
- Greeting on its own line: `Hi {FirstName},`  then a blank line.
- Short paragraphs, 2 to 4 sentences each, separated by blank lines. No bullet lists in the body.
- Close with `Best regards,` then `Avanish` on the next line, then the standard email signature block.
- Mail 1 signature carries NO links. Later mails may use the full signature.

## Voice rules (every email)
- Open on the single highest-value or highest-risk named asset for THAT specific company.
- Name the specific failure mode in correct trade vocabulary (coil failure, refractory degradation,
  spindle thermal drift, VAR cycle backup, bearing spall, and so on).
- Connect it to the operational ripple: what it does to throughput, schedule, yield, or compliance.
- Ground the hook in a real, sourced, company-specific fact (a current event, a named asset, a known
  system). The source URL goes in `personalization_notes`.
- 150 to 220 words. Plain text. Reads like a person who spent 20 minutes on the company.
- Mail 1 makes no hard pitch. It earns a reply, not a meeting.

## Capability truth (never claim what the platform cannot do)
Source of truth: `config/offer_context.yaml`. Emails may ONLY assert capabilities consistent with it.
When unsure whether something is true, omit it. Keep the deep expertise in the *failure-mode diagnosis*
(domain knowledge, always fair to state) and keep the *platform claim* generic and true.

PERMITTED (truthful) claims:
- Uses the data a plant ALREADY has: historian, CMMS / work orders, PLC and SCADA tags, ERP. No new
  sensors required for the pilot; no rip-and-replace. Integrates with common systems (Rockwell, Siemens,
  SAP, Epicor, Plex, most CMMS/SCADA).
- Surfaces early warning of equipment failure or process drift before it trips an alarm or reaches
  inspection. Use SOFT lead-time phrasing only ("days ahead", "before it forces a stop", "before it
  reaches inspection"). Do NOT promise a specific day-count as our capability; "7-14 days" may appear
  only as an attributed industry benchmark, and we currently avoid stats in these emails entirely.
  Anomaly/drift detection, top downtime-driver (OEE) identification with root cause, quality early warning.
- Refer to integrations generically ("your existing historian, CMMS, SCADA, and ERP"). Name specific
  vendors (Rockwell, Siemens, SAP, Epicor, Plex) ONLY if those connectors are confirmed built and tested.
- Pilot is a no-cost data-readiness assessment on existing data, roughly two weeks to a first result.

BANNED (unverified or inflated) claims:
- A specific "18 days" advance warning, hard RUL guarantees, or any agent count ("45 agents", "32 agents").
- Claiming we already model THIS prospect's specific asset, or guaranteeing a specific outcome/number for them.
- Naming a sensor input the prospect may not have as if it is required. Do NOT assert we use "vibration"
  unless it is established the plant already streams it; prefer "the signals your machines already produce"
  or commonly-present signals (motor current, spindle load, temperature, cycle data, historian tags).
  Digitillis is explicitly NOT a sensor-first vendor; the positioning is "uses your existing data".
- Any outcome/ROI framed as something our customers achieved (we are pre-customer; industry benchmarks
  only, attributed, and we currently avoid stats in these emails entirely).

## No overclaiming (pre-customer stage, critical)
We are pre-customer. Never claim or imply a customer base, a roster, or traction we do not have. A
prospect must never be able to reasonably ask "which other [their-vertical] companies do you work with?"
and put us in a bind.
- BANNED: "I run a company that works with gear and sprocket manufacturers", "we work with [vertical]
  plants", "companies like yours have caught X with us", "our customers in [industry]", any named or
  implied client.
- INSTEAD: establish credibility through demonstrated domain fluency (the specificity of the failure
  mode itself does the work) and plain, factual statements of what Digitillis does ("We read the sensor
  and historian data your machines already produce to flag this drift days early"). Never imply who else
  uses it.
- Open by leading with the operational insight or observation directly, not with a credential.

## Hard bans (auto-rejected)
- **Em dashes (—, –) and ellipses (...). Never. Use commas, periods, or restructure the sentence.**
  This is the founder's writing style and is non-negotiable.
- Recycled stats: "15-20%", "23-41%", "40-65%", "SMRP 2023", "18 days out" (verbatim). If you cite a
  number, it must be specific to that asset and sourced.
- The phrase "time-based maintenance schedules". Say "calendar-based PMs" or asset-specific language.
- Canned openers: "Curious,", "Quick question:", "or is it something else".
- Fabricated anecdotes, fabricated prospect replies ("you mentioned..." when they never replied),
  invented customer or client references.
- Generic hooks: "manufacturers like yours", "plants in your sector", "companies like yours".

## Sequence arc (5 steps, breakup close)
| Mail | Day | Purpose |
|---|---|---|
| 1 | 0 | Cold open: named asset + failure mode + operational ripple + one soft, answerable question. No link. |
| 2 | +4 | Explicitly build on Mail 1 (callback). Add ONE new consequence or evidence point. Soft probe. |
| 3 | +9 | Deepen — a different sub-asset or angle **within the same domain**. Light meeting probe. |
| 4 | +16 | Substantiate: how it works on existing data, no new hardware. Clearer (still low-pressure) meeting ask. |
| 5 | +30 | Breakup + value gift: a genuine technical insight as a parting gift, a low-friction door ("I'm one reply away if X comes up"). **No hard ask.** |

Continuity is mandatory: Mail N must read as the next message in a conversation, never a fresh cold open.
Never reference internal labels ("step 2", "my first email"). Use natural language ("following up on my
note about your induction furnaces…").

## Arm variations (the lever under test — message angle only; channel stays cold)
- **Arm A — Operational pain (control):** lead with the asset's failure mode and operational consequence.
  This is the Waupaca-style email that earned our only reply.
- **Arm B — Financial / throughput outcome:** same asset specificity, but lead with the dollarized or
  throughput consequence (cost of an unplanned stop, margin at risk, schedule impact in real terms).
- **Arm C — Trigger-event-led:** lead with the real, web-verified recent company event (capex, expansion,
  leadership hire, recall, certification) and connect it to the operational risk Digitillis addresses.
