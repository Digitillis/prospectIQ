# F&B FSMA 204 Outreach Templates
# Campaign: fsma204-fb
# Author: Avanish Mehrotra
# Version: v1 — 2026-04-30
#
# Usage:
#   - Variables in [BRACKETS] must be filled from discovery/enrichment data before sending
#   - Variables marked (verify) require manual confirmation — do not send with placeholders
#   - One template per role per sub-segment where the wedge differs materially
#   - No AI generation of per-company variants. Fill the brackets. Send.
#
# Sub-segments with dedicated templates:
#   DAIRY     — fb_dairy (HTST pasteurizer + CIP + soft cheese FTL)
#   SEAFOOD   — fb_seafood (first land-based receiving CTE + cold chain)
#   PRODUCE   — fb_produce (leafy greens FTL + paper-based CTE gap)
#   MEAT      — fb_meat (HACCP + cold chain + FTL finfish/crustacean)
#   BEVERAGE  — fb_bev (aseptic filler + OEE angle, FSMA secondary)
#   BAKERY    — fb_bakery (allergen changeover primary wedge)
#
# ============================================================
# PERSONAS: 3 primary cold-outreach targets
# ============================================================
#
# C1: VP of Operations / COO / Director of Operations
#     — Economic buyer. Cares about OEE, downtime cost, labor. FSMA is secondary.
#     — Goal of first touch: get 20-minute discovery call on downtime cost.
#
# C2: VP / Director of Quality or Food Safety / Regulatory Affairs Director
#     — Key influencer. Owns FSMA compliance, audit liability, FDA relationship.
#     — Goal of first touch: get 20-minute discovery call on traceability readiness.
#     — NOTE: Hold C2 send until FSMA Traceability module is demo-ready.
#
# C3: Plant Manager / Director of Manufacturing
#     — Day-to-day champion. Cares about throughput, maintenance burden, shift issues.
#     — Typically reached after C1 or C2 responds. Can be sent simultaneously.


---
---
## DAIRY (fb_dairy)
---

### DAIRY — C1: VP of Operations

Subject: [COMPANY] filling line downtime — the numbers

[FIRST_NAME],

[COMPANY] runs [PLANT_COUNT] production facilit[y/ies] (verify). Industry data for mid-market dairy shows $18,000–$40,000 per hour of unplanned downtime on HTST lines — and 2–4 preventable events per year is typical for facilities our size without predictive monitoring.

At 3 events averaging 45 minutes each, that is roughly $[CALC: PLANT_COUNT x 40000 x 2.25] annually — before accounting for batch loss and quality audit costs.

ARIA connects to your existing OPC-UA signals and gives 72-hour early warning on developing failure patterns on your pasteurizers, CIP skids, and filling lines. No new sensors required.

Worth 20 minutes to see whether the numbers hold at [COMPANY]?

Avanish Mehrotra
Digitillis
[PHONE]

---
### DAIRY — C2: VP of Quality / Food Safety (HOLD — needs FSMA module demo-ready)

Subject: FSMA 204 — dairy traceability at [COMPANY]

[FIRST_NAME],

The July 2028 deadline gives you time to close the FSMA 204 gap properly. Most dairy processors we talk to have lot trace in their ERP — but FSMA traceability is not ERP lot trace. The gap is at the plant floor: linking your HTST pasteurization events, CIP cycle records, and transformation events (especially when raw milk lots are blended or re-split) to the CTEs that FDA will request.

Soft cheeses and fluid milk on the Food Traceability List mean [COMPANY] needs every CTE documented and producible in 24 hours — not 3 days.

Digitillis closes that gap from the same data stream that runs your predictive maintenance. I'd like to understand where [COMPANY] stands today. 20 minutes?

Avanish Mehrotra
Digitillis
[PHONE]

---
### DAIRY — C3: Plant Manager

Subject: 72-hour warning on pasteurizer failures — no new sensors

[FIRST_NAME],

If your HTST pasteurizer developed a temperature deviation pattern today, how soon would your team know? Most plant managers say: when the alarm fires. By then, the batch may be at risk and the CIP cycle that follows is reactive, not planned.

ARIA reads your existing OPC-UA signals and gives 72+ hours of early warning — enough time to schedule the repair during a planned sanitation window rather than an emergency stop. No new sensors. No rip-and-replace of your existing CMMS.

We have worked with dairy facilities running Alfa Laval and APV systems. 15 minutes to show you what the early warning pattern looks like on a pasteurizer failure?

Avanish Mehrotra
Digitillis
[PHONE]

---
---
## SEAFOOD (fb_seafood)
---

### SEAFOOD — C1: VP of Operations

Subject: [COMPANY] — cold chain downtime cost

[FIRST_NAME],

Refrigeration and blast-freeze system failures at seafood processing facilities average $25,000–$60,000 per hour when you account for product loss, hold status, and regulatory notification costs. [COMPANY] processes [SPECIES/PRODUCT if known] (verify), which puts you in the highest-risk category for both product value loss and FSMA 204 exposure.

ARIA monitors your cold chain, CIP skids, and processing equipment in real time using your existing OPC-UA signals — no new sensors. Typical result: 2–3 prevented shutdowns per year, 8–12 week time to first value.

20 minutes to run the numbers for your facility?

Avanish Mehrotra
Digitillis
[PHONE]

---
### SEAFOOD — C2: VP of Quality / Food Safety (HOLD — needs FSMA module demo-ready)

Subject: FSMA 204 and first land-based receiving at [COMPANY]

[FIRST_NAME],

Finfish and crustaceans are directly on the FDA Food Traceability List. FSMA 204 requires [COMPANY] to document the first land-based receiving CTE — with Traceability Lot Code, quantity, and location identifier — for every covered seafood product, and to produce those records to FDA within 24 hours.

Most seafood processors have lot codes in their ERP or WMS. The gap is the link between receiving records, cold chain events, and transformation points (when a single raw lot becomes multiple processed lots at filleting or packaging). That link does not exist in most ERP systems today.

Digitillis closes it from your existing plant data. I'd like to understand your current state. 20 minutes?

Avanish Mehrotra
Digitillis
[PHONE]

---
### SEAFOOD — C3: Plant Manager

Subject: Cold chain monitoring at [COMPANY] — no new hardware

[FIRST_NAME],

A blast freezer going out of range at 2am is not caught until the morning shift walks in. By then, you may have a hold decision, a HACCP deviation record, and a 4-hour recovery that your team is handling manually.

ARIA monitors your cold chain and refrigeration systems continuously, uses your existing OPC-UA or BACnet signals, and pages the right person before the deviation becomes a hold situation. No new sensors. No changes to your existing CMMS or ERP.

15 minutes to show you what the alert cadence looks like for a facility your size?

Avanish Mehrotra
Digitillis
[PHONE]

---
---
## PRODUCE / FRESH-CUT (fb_produce)
---

### PRODUCE — C1: VP of Operations

Subject: [COMPANY] — traceability and line downtime, quantified

[FIRST_NAME],

Fresh-cut produce operations run on thin margins and tight production windows. A conveyor or cooling system failure at [COMPANY] during peak line time costs [ESTIMATE: $8,000–$20,000/hour depending on line] — and the follow-on quality hold can cost 3x the mechanical repair.

ARIA monitors your cooling, cutting, and packaging lines using existing plant signals. Typical customers see 2–3 prevented events in the first year. At 30 minutes each at $15,000/hour, that is approximately $22,000 recovered — before accounting for reduced waste.

20 minutes to walk through the numbers for [COMPANY]'s operation?

Avanish Mehrotra
Digitillis
[PHONE]

---
### PRODUCE — C2: VP of Quality / Food Safety (HOLD — needs FSMA module demo-ready)

Subject: FSMA 204 — leafy greens traceability at [COMPANY]

[FIRST_NAME],

[COMPANY]'s products are almost certainly on the FDA Food Traceability List — leafy greens, tomatoes, cucumbers, peppers, and fresh-cut fruits and vegetables are all covered. That means FSMA 204 requires complete CTE records producible within 24 hours of an FDA request.

The gap we see most often in fresh-cut operations: the transformation CTE (when whole-head lettuce becomes shredded salad mix and a new Traceability Lot Code must be assigned) is tracked on paper or in the ERP with batch-level granularity, not at the equipment event level. If FDA asks for the records associated with a specific finished lot, linking it back through the transformation point to the incoming supplier lot takes days, not hours.

I'd like to understand how [COMPANY] handles that today. 20 minutes?

Avanish Mehrotra
Digitillis
[PHONE]

---
---
## MEAT / POULTRY (fb_meat)
---

### MEAT — C1: VP of Operations

Subject: [COMPANY] line downtime — the arithmetic

[FIRST_NAME],

A processing line failure at a meat facility costs $15,000–$50,000 per hour when you include product on the line, sanitation restart requirements, and regulatory notification costs if a HACCP deviation is involved.

ARIA monitors your processing and packaging equipment using existing OPC-UA or PLC signals — no new sensors, no rip-and-replace. Typical results: 2–4 prevented events per year. At $25,000/event and 60 minutes average recovery, that is $50,000–$100,000 per year, conservatively.

20 minutes to see whether those numbers hold at [COMPANY]'s facilities?

Avanish Mehrotra
Digitillis
[PHONE]

---
### MEAT — C2: VP of Quality / Food Safety (HOLD — needs FSMA module demo-ready)

Subject: FSMA 204 at [COMPANY] — what 24-hour production actually means

[FIRST_NAME],

Finfish and crustaceans are directly on the FSMA Food Traceability List. For [COMPANY], that means every receiving, transformation, and shipping event for covered products must be documented at the CTE level — with Traceability Lot Codes — and producible to FDA in 24 hours.

The gap at most mid-market meat and seafood processors: HACCP records, lot trace, and sanitation records are in three different systems, and linking them for a specific production lot takes 2–3 days manually. The FDA's standard is 24 hours, not 24 hours to start looking.

Digitillis links those three data streams from your existing plant data. Worth 20 minutes to see the gap analysis for your operation?

Avanish Mehrotra
Digitillis
[PHONE]

---
---
## BEVERAGE (fb_bev)
---

### BEVERAGE — C1: VP of Operations

Subject: [COMPANY] filler downtime — the math is straightforward

[FIRST_NAME],

An aseptic filling line at typical production value runs $100,000–$200,000 per hour. A filler stoppage at [COMPANY] during peak SKU production does not just lose fill time — it triggers a sterile requalification cycle that adds 4–8 hours before the next run.

ARIA monitors your fillers, homogenizers, and CIP skids using existing OPC-UA signals. It gives 72-hour early warning on developing failure patterns — enough time to schedule the repair during a planned changeover, not an emergency stop.

No new sensors. No changes to your existing CMMS. 20 minutes to walk through the numbers?

Avanish Mehrotra
Digitillis
[PHONE]

---
### BEVERAGE — C3: Plant Manager

Subject: Filler and CIP failure prediction at [COMPANY]

[FIRST_NAME],

How far in advance do you typically know about a developing CIP failure on your aseptic line? Most plant managers say: the conductivity alarm. By then, you are already running a cleanup cycle against an already-compromised result.

ARIA reads your existing OPC-UA signals and identifies the deviation trend in your CIP conductivity, temperature, and flow readings 48–72 hours before the alarm fires. Same for filling line mechanical deviations.

Worth 15 minutes to see what that looks like on a beverage line?

Avanish Mehrotra
Digitillis
[PHONE]

---
---
## BAKERY / SNACK (fb_bakery)
---

### BAKERY — C1: VP of Operations

Subject: Allergen changeover time at [COMPANY]

[FIRST_NAME],

In bakery and snack manufacturing, allergen changeovers are the highest-risk, highest-cost production transition you run. A missed validation step triggers a hold, a potential recall, and an FDA correctable action — and changeover time directly limits your line utilization.

ARIA validates each changeover in sequence: CIP completion, first-off-line sample hold, operator sign-off, and production record linkage. It blocks a production start if any step is missing — and the full changeover record becomes a FSMA-compliant CTE event.

At [COMPANY] with [SKU COUNT if known] (verify) active SKUs and [CHANGEOVER FREQUENCY if known] changeovers per week, the efficiency and compliance case is direct. 20 minutes?

Avanish Mehrotra
Digitillis
[PHONE]

---
### BAKERY — C2: VP of Quality / Food Safety (HOLD — needs FSMA module demo-ready)

Subject: Allergen changeover records and FSMA 204 at [COMPANY]

[FIRST_NAME],

Allergen changeover records are increasingly an FSMA 204 CTE for bakery operations with FTL-adjacent ingredients. Beyond FSMA, they are the single highest-risk compliance document you produce — an incomplete changeover record is the root cause of most allergen-related recalls in the $50M-$300M bakery segment.

Most bakeries manage changeover validation on paper sign-off sheets or a spreadsheet that gets reconciled weekly. When a recall investigation starts, the question is: was the changeover for lot [X] fully validated before production started? The answer takes hours to reconstruct manually.

Digitillis makes that question answer itself in 45 seconds. Worth 20 minutes to see how it works for [COMPANY]'s line configuration?

Avanish Mehrotra
Digitillis
[PHONE]


---
---
# SEND RULES (apply before every send)
---

1. VERIFY [VARIABLES] — never send with a placeholder unfilled or wrong.
   Required minimum per company before sending:
   - Correct first name and current title (check LinkedIn — Apollo titles go stale)
   - Company name spelled correctly (check their website)
   - Plant count confirmed (1 plant vs. 5 plants changes the message)
   - Email address validated (CCS >= 2 sources or manually confirmed)

2. DAIRY and SEAFOOD first. Run these sub-segments before meat, produce, and bakery.
   fb_dairy and fb_seafood have the strongest FTL exposure and the clearest ROI stories.

3. C1 (VP Ops) and C3 (Plant Manager) can send now — ARIA is built.
   C2 (VP Quality/Food Safety) waits until FSMA Traceability module is demo-ready.

4. Simultaneous dual-persona: send C1 and C3 in the same week per company,
   not sequentially. ThreadingCoordinator handles this via assign_fb_simultaneous_contacts().

5. 20-minute ask only. Do not pitch the product in the first message.
   Goal of the first touch is one outcome: a 20-minute discovery call.

6. Maximum 5 sends per day to F&B contacts. This is a relationship vertical.
   Quality of follow-up matters more than send volume.

7. Subject lines are final — do not modify them. They have been calibrated
   for specificity without false premises.


---
# DISQUALIFICATION CRITERIA (remove from send queue before outreach)
---

Remove any company that meets any of these criteria:

| Criterion                          | Action             |
|------------------------------------|--------------------|
| Revenue > $500M                    | icp_exclusion: wrong_vertical (enterprise motion) |
| Revenue < $50M confirmed           | icp_exclusion: wrong_vertical (too small) |
| Already has Sight Machine contract | icp_exclusion: already_compliant |
| FDA warning letter resolved >2 yrs | Lower priority — remove from wave 1 |
| Public company, no divisional buy  | Move to manual outreach; longer cycle |
| Domain bounce on email validation  | icp_exclusion: hard_bounce |
| No verifiable plant-floor ops      | icp_exclusion: wrong_vertical |
