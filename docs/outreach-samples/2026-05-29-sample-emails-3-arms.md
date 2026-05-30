# ProspectIQ — Sample Outreach (3 arms x 1 prospect x 5 steps)

*Generated 2026-05-29 via Opus (Pro Max session), web-grounded. For review — nothing sent.*

Cadence: Mail 1 Day 0, Mail 2 +4, Mail 3 +9, Mail 4 +16, Mail 5 +30 (breakup).


---

## Arm A — Operational pain (control)
**Martin Sprocket & Gear** · Justin Holmes

**Grounding (event):** Martin Sprocket & Gear exhibited its Material Handling Division at GEAPS Exchange 2024 (February 24-27, Kansas City), showcasing bulk conveying and elevator equipment to grain-handling customers — underscoring the company's active investment in expanding its agricultural and material handling market presence across its 33 North American facilities.
**Source:** https://geaps2024.smallworldlabs.com/exhibitors/exhibitor/223


### Mail 1 — Day 0
**Subject:** The hob spindle bearings on your gear line

Justin,

I run a company that works with gear and sprocket manufacturers, and the failure mode I keep coming back to on a high-mix floor like yours is the hob spindle and the worktable index worm on the hobbing machines. When the spindle bearing preload starts to relax or the index worm picks up backlash, you rarely get a clean breakdown. What you get is profile drift and lead error that walks slowly out of tolerance, and the gears keep cutting and shipping until QC or a customer catches it downstream.

That is the part that hurts at Martin specifically. You are feeding agriculture, mining, and construction customers who have no tolerance for a late drive component, so a scrapped batch on a hobber is not just lost spindle hours, it is a resequenced schedule and a delivery commitment you now have to defend.

When a hobber does eventually act up, are your people usually reacting to a finished-gear quality flag, or do they catch the spindle or index worm starting to wander before it reaches the part?

Best,
Avanish

### Mail 2 — Day 4
**Subject:** Re: The hob spindle bearings on your gear line

Justin,

Following up on my note about the hob spindle and index worm drifting before anything actually breaks. There is a second place that same problem shows up, and it is the one that tends to slip past inspection: the grinding spindles on your finishing operations.

A gear can leave the hobber inside tolerance, get carburized and hardened, and then the grind step is supposed to be the last word on geometry. But as a grinding spindle warms across a long run, the bearings and the thermal growth of the headstock shift the wheel position by microns. On a hardened gear that is the difference between a clean tooth flank and a dimensional escape that you cannot rework, only scrap, after you have already paid for the steel, the cut, and the heat treat.

So the cost of missing it on the grinder is much higher than missing it on the hobber, because all of the upstream value is already sunk into the part.

Are your grinding spindles on fixed inspection intervals right now, or is anyone watching how their condition changes across a shift?

Best,
Avanish

### Mail 3 — Day 9
**Subject:** The furnace upstream of your scrap problem

Justin,

I have been talking about the hobbing and grinding spindles, but the asset that most often quietly sets up scrap on a gear line sits upstream of both: the carburizing furnace.

Case-depth scrap is rarely a sudden event. It builds when temperature uniformity inside the furnace starts to slip, usually because a recirculation fan bearing is degrading or a heating element is drifting in resistance, so the load no longer sees an even carbon potential across every tray. The gears come out looking fine. The case depth or surface hardness fails on a destructive check days later, by which point you have run more of the same heat through the same drifting furnace.

For a manufacturer expanding its presence in agriculture and material handling, that is a direct threat to the parts you are putting in front of those customers, since heat treat is what actually carries the load rating you are selling on.

Would a short call be useful, just to compare how you are currently catching furnace drift versus what an earlier signal would change? I am glad to keep it to fifteen minutes.

Best,
Avanish

### Mail 4 — Day 16
**Subject:** No sensors to add, Justin

Justin,

One thing I should have made clear earlier in this thread, because it changes how much friction any of this carries for you.

Everything I described, the hob spindle wandering, the grinding-spindle drift across a run, the furnace uniformity slipping, is already visible in data your plant produces today. The PLCs on the hobbers, the spindle load and temperature signals, the furnace zone thermocouples and fan motor draw, the work-order history in your CMMS. We read what is already there and learn each asset's normal signature, then flag the change days before it reaches a finished gear. No new hardware on the machines, no rip-and-replace, no controls project. That matters for a privately held shop that has to be deliberate about capital.

The outcome is simple. Your machinists stop getting pulled into reactive firefighting on a hobber that failed mid-run, and start getting a heads-up while it is still a planned intervention between jobs.

Could we put thirty minutes on the calendar in the next week or two? I will walk through exactly which of your existing signals we would use, against your actual asset list, so you can judge it on your floor and not mine.

Best,
Avanish

### Mail 5 — Day 30
**Subject:** Closing the loop, with one thing worth keeping

Justin,

I have not heard back, which I take to mean a downtime tool is not where your attention is right now. That is fair, and I will stop landing in your inbox.

Before I go, here is something genuinely useful that needs nothing from me. If you want the earliest honest warning on a hobber or grinder, do not start with vibration. Start with the spindle motor's load signature at a fixed point in the cycle, an air cut or a known reference pass. When bearing preload relaxes or an index worm picks up backlash, the load to hold position and finish quality changes measurably before vibration crosses any alarm threshold and well before the part fails inspection. Logging that one reference-pass load value per spindle, per shift, and watching the trend rather than the instant reading, will surface a wandering machine earlier than almost anything else you can do without buying gear. The same logic, watching the trend instead of the snapshot, applies to your furnace fan motor draw.

That is worth having whether or not we ever talk. If undetected drift in hobbing, grinding, or heat treat ever turns into a scrap or delivery problem you want a second set of eyes on, I am one reply away.

Best,
Avanish

---

## Arm B — Financial / throughput
**Pepsi Bottling Ventures** · James Darnell

**Grounding (event):** Pepsi Bottling Ventures completed a $35 million investment to bring a new high-speed bottling line online at its Winston-Salem, NC facility by end of 2024, capable of running 100% recycled-material PET bottles for Aquafina, Lipton Tea, and Nature's Twist.
**Source:** https://pepsibottlingventures.com/2022/07/11/pepsi-bottling-ventures-llc-invests-35-million-to-expand-operating-capacity/


### Mail 1 — Day 0
**Subject:** Your Winston-Salem line and the cost of an hour down

James,

Your new high-speed line in Winston-Salem is built to move serious volume, and that is exactly where an unplanned stop costs the most. When a rotary filler running PET goes down mid-run, it is rarely the obvious failure. It starts with a filling valve seal hardening or a worn lift cylinder seal letting fill levels drift, then a few rejects, then a fault that drops the whole line while everything upstream keeps feeding into a stalled accumulator.

On a line spec'd to run flat out through a summer demand spike, an hour of that is not an hour of lost output. It is the cases you were already behind on, plus the changeover and CIP time to recover, plus the carbonation and product you scrap clearing the line. The math gets ugly faster than the maintenance log suggests.

I work with manufacturing leaders on catching exactly this kind of valve and seal degradation days before it pulls a line, using the sensor and historian data the line already produces.

When a filler line drops unexpectedly today, how much of the lost throughput do you actually recover by end of week, versus losing for good?

Best,
Avanish

### Mail 2 — Day 4
**Subject:** The recycled-resin cost on that same line

James,

Following up on my note about filler valve and seal wear quietly eating throughput on the Winston-Salem line. There is a second cost on that line worth naming, and it lands harder now that it runs 100% recycled PET.

Recycled resin is less forgiving in the blow molder. As heater bands drift or a stretch rod and preform mandrel start to wear, you get inconsistent wall thickness and weak base clearance, which shows up as bottles that fail at the filler or burst under carbonation pressure. With rPET that drift window is narrower, so the same machine condition that virgin resin tolerated now turns into scrapped preforms, rejected bottles, and resin you paid a premium for going into the regrind bin instead of a pallet.

That is real margin leaving the building before a single case ships, and it rarely trips an alarm until the reject rate is already high.

The pattern is readable early in the machine's own process data, before yield falls off.

Roughly, when blow molder reject rate climbs on a run, how long does it usually take your team to trace it back to the actual cause?

Best,
Avanish

### Mail 3 — Day 9
**Subject:** Capping is the quiet throughput leak

James,

One more piece of the same line, since seal integrity is where throughput and quality collide. Capping is the quiet one. As capper chuck springs fatigue or the torque head bearings wear, application torque drifts out of spec gradually. You do not get a clean failure. You get rising low-torque and high-torque rejects, a slow bleed of seal-integrity holds, and eventually a line stop to swap heads, usually mid-shift and never on schedule.

On a high-speed line, a capper that needs a head rebuild does not announce it. It shows up as a creeping reject rate the line operators learn to live with, until QA flags a carbonation-retention or leaker issue and the whole run is in question.

Across the filler, the blow molder, and the capper, the common thread is that the wear is mechanical, gradual, and visible in the data days before it costs you a run. We read torque, vibration, and process trends to flag the asset that is drifting, not the whole plant.

Would a short call make sense to walk through how this would look on the Winston-Salem line specifically? Even 20 minutes.

Best,
Avanish

### Mail 4 — Day 16
**Subject:** What it takes to stand this up (less than you'd think)

James,

I have walked through three failure modes on your high-speed line: filler valve and seal wear, blow molder drift on recycled resin, and capper torque degradation. A fair question at this point is what it would actually take to stand this up on your floor.

The honest answer is very little, and that is the part most operators do not expect. Beverage lines like yours already produce the signal. The Allen-Bradley PLCs are logging fault codes, cycle times, fill and torque data. Your historian is already trending it, and your CMMS already holds the work-order history. We read what is already there. No new sensors bolted onto the filler, no rewiring the line, no production interruption to install anything.

What changes is that instead of a tech noticing a reject trend after it has cost a run, the asset that is drifting surfaces days ahead, while there is still a quiet window to act.

If it is worth 25 minutes, I would map this against your actual line layout and show where the early-warning windows sit. I can work around the production schedule. What week looks least underwater for you?

Best,
Avanish

### Mail 5 — Day 30
**Subject:** A parting CIP signal worth trending

James,

I will stop landing in your inbox after this, but I want to leave you something useful either way.

If you ever want a no-cost leading indicator on that Winston-Salem line, watch your CIP cycles on the filler and mixer. Trend the conductivity return curve and the time it takes each circuit to reach setpoint temperature, cycle over cycle. When a circuit starts taking longer to come up to temp or the conductivity tail drags, that is often a fouling supply pump or a heat-exchanger losing efficiency well before it becomes a sanitation hold or an unplanned stop. It is one of the earliest, cheapest signals of pump and exchanger degradation hiding in data you already log nightly, and most teams never trend it.

That alone can buy you a few days of warning on equipment you would otherwise only notice when it fails.

If unplanned line stoppages on the new line ever start costing more than they should, or recycled resin keeps testing your blow molders, I am one reply away. No pitch. Happy to be a sounding board.

Best,
Avanish

---

## Arm C — Trigger-event-led
**Redwood Materials** · Ivor Bull

**Grounding (event):** Redwood Materials opened the first phase of its $3.5 billion, 600-acre Camp Hall campus in South Carolina in December 2025, beginning critical-mineral recovery operations at what is the largest economic development project in state history.
**Source:** https://scbiz.com/redwood-materials-battery-recycling-plant-south-carolina/


### Mail 1 — Day 0
**Subject:** Camp Hall kilns and the first 90 days of mixed feedstock

Ivor,

I saw Camp Hall started critical-mineral recovery in December, and I keep coming back to the rotary kilns and calcination furnaces, because the first months of a brand-new line running mixed-chemistry black mass are where refractory wear behaves least predictably. When the feedstock blend shifts batch to batch, the thermal profile across the kiln drifts in ways that grab samples and a campaign-based reline schedule rarely catch early. The first place you usually see it is your nickel and cobalt recovery numbers softening, and by then the refractory has already moved.

What makes Camp Hall harder than Carson City is that you have no local wear baseline yet. The kiln is teaching you its degradation curve in real time, while you are also trying to hit recovery and purity targets to make the cost-parity case against Asian cathode suppliers.

I run a company focused on exactly that gap, so I am genuinely curious rather than pitching: in those first months at Camp Hall, are you reading kiln health mostly from shell temperature and periodic inspection, or do you already have a way to tie thermal-profile drift back to a feedstock blend before it shows up in recovery?

Best,
Avanish

### Mail 2 — Day 4
**Subject:** Re: Camp Hall kilns and the first 90 days of mixed feedstock

Ivor,

Following up on my note about the Camp Hall kilns and refractory wear, with one consequence I left out that tends to matter more than the reline cost itself.

When a refractory hot spot develops on a rotary kiln running variable black mass, the real exposure is not just the lining. It is the unplanned cool-down. Bringing a high-temperature kiln down off-cycle and back up cleanly is slow, and during a facility ramp every one of those forced stops competes directly with the throughput you need to prove Camp Hall's economics. A single unplanned thermal event can cost you more schedule than a planned reline you saw coming weeks out.

The reason I keep raising it is that the signal is usually already in your data. The drift shows up as a slow divergence between shell-temperature zones and feed rate before any alarm trips, but it is hard to see batch to batch when the chemistry keeps moving underneath you.

At your stage of ramp, are forced kiln cool-downs something you are actively trying to engineer out, or is the line still stable enough that it has not bitten yet?

Best,
Avanish

### Mail 3 — Day 9
**Subject:** Re: Camp Hall kilns and the first 90 days of mixed feedstock

Ivor,

I have been talking about the kilns, but the same Camp Hall ramp problem lives one step downstream in the hydromet leaching and solvent extraction lines, and that is where it gets expensive quietly.

In leaching, a 0.2% drift in pH or temperature across a stage can push pCAM toward the edge of spec before a grab sample ever catches it. With feedstock chemistry changing between an EV pack, a laptop cell, and production scrap in the same shift, the set points that held last week are not the right set points this week. The corrosive environment compounds it, because the same chemistry that attacks your materials of construction also degrades the very instruments you are trusting to tell you the line is in control.

So you can have a quality escape that is not a sensor failure or an operator error, just slow drift the system was never watching for. At tight battery-material purity specs, those escapes are not cheap.

If you are open to it, I would value 20 minutes to compare how you are thinking about real-time process correction across leaching versus how we approach drift detection. Worth a short call?

Best,
Avanish

### Mail 4 — Day 16
**Subject:** Re: Camp Hall kilns and the first 90 days of mixed feedstock

Ivor,

One thing I should have made clear earlier, because it changes whether any of this is worth your time during a ramp.

Everything I have described about the Camp Hall kilns and leaching lines works on the data you already generate. No new hardware on the line, no instrumentation project competing with your ramp schedule. We read your existing process historian, sensor streams, and maintenance records, and we learn the normal relationship between feedstock blend, thermal profile, and chemistry. Then we flag the drift days before it reaches your recovery or purity numbers, which is exactly the lead time you do not have when the kiln is still teaching you its own wear curve.

The reason that matters at a new plant is that the value shows up while you are still building your wear and process baselines, not a year later once you have lived through the failures the hard way.

Would a 30-minute call in the next week or two make sense? I am not asking you to change anything you are running. I would just walk through how this would sit on top of your Camp Hall data and where the first useful warning would likely come from. Happy to work around your schedule.

Best,
Avanish

### Mail 5 — Day 30
**Subject:** Re: Camp Hall kilns and the first 90 days of mixed feedstock

Ivor,

I will stop landing in your inbox after this, since a December plant start means your attention is rightly on the floor, not on email.

Before I go, one genuine parting thought from watching mixed-feedstock thermal processing. The most useful early predictor of refractory trouble on a black-mass kiln is usually not absolute shell temperature. It is the rate of change in the temperature spread between adjacent kiln zones, normalized to feed rate. Operators often watch peak temperature and miss that the zones are diverging at a feed rate that used to hold them together. If you have someone trend that ratio per feedstock campaign at Camp Hall, you will likely catch hot-spot formation a good stretch before it forces a cool-down, with nothing new installed. It is a free win regardless of whether we ever talk.

I think Redwood is building one of the few genuinely hard things in this industry, and I would rather be useful than persistent. If kiln wear, leaching drift, or quality escapes during the ramp ever turn into a real headache, I am one reply away.

Best,
Avanish