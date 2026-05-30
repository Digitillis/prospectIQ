# ProspectIQ — Sample Outreach (Arms A & C, corrected)

*Generated 2026-05-29 via Opus (Pro Max). Corrected: no overclaim, no em dashes/ellipses, "Hi {First}," / "Best regards, Avanish". For review, nothing sent.*

Cadence: Day 0 / +4 / +9 / +16 / +30 (breakup).


---

## Arm A — Operational pain
**Martin Sprocket & Gear** · Justin Holmes
**Source:** https://geaps2024.smallworldlabs.com/exhibitors/exhibitor/223


### Mail 1 — Day 0
**Subject:** Hob spindle bearing wear on your gear hobbing line

Hi Justin,

On a high-mix gear floor, the asset I would watch first is your gear hobbing machine. When the hob spindle bearings start to degrade, the early signal is rarely a hard fault. It shows up as a slow rise in radial runout that walks the tooth profile and lead out of tolerance before anything trips an alarm.

The operational ripple is what makes it expensive. By the time the lead error is caught at inspection, you have already cut a batch, and on agriculture and mining drive components the rework or scrap lands on parts that took real machine hours to rough and finish. Worse, the drift is gradual, so an operator running to a calendar PM has no reason to pull the spindle until the bearing is already marginal.

Digitillis predicts that kind of bearing degradation days ahead using the vibration, spindle load, and historian data a plant already has, no new sensors bolted on. The point is to move the hob spindle from a fixed PM interval to a condition-based call.

When a hob starts producing profile drift, are your operators catching it from in-process inspection, or does it usually surface at final gauging?

Best regards,
Avanish

### Mail 2 — Day 4
**Subject:** Re: Hob spindle bearing wear on your gear hobbing line

Hi Justin,

Following up on my note about hob spindle bearing wear, there is a second consequence that tends to compound it, and it sits one operation downstream in your carburizing furnaces.

When case depth drifts on a carburizing cycle, the usual cause is not the gear geometry at all. It is the furnace itself, a sagging carbon potential from a tired oxygen probe, or temperature uniformity creeping outside the qualified window across the load. The frustrating part is that the parts look fine coming out, and the case-depth shortfall only shows up later at metallurgical check or, in the field, as premature tooth fatigue on a drive component under load.

So you can have a perfectly hobbed gear go to scrap because the heat treat that followed it was quietly out of spec. Both failure modes share the same fix in approach, which is reading the early drift in existing process data rather than waiting for the inspection that confirms the loss.

Do you track carbon potential and load uniformity trend over time, or is case depth mostly verified piece by piece after the fact?

Best regards,
Avanish

### Mail 3 — Day 9
**Subject:** Re: Hob spindle bearing wear on your gear hobbing line

Hi Justin,

Staying inside the same precision domain, the third asset worth a look is your grinding machines, because they are where the cost of upstream drift becomes permanent.

Grinding is the last chance to hold tolerance, so when a grinding spindle loses balance or the wheel dressing interval slips, the symptoms read as surface finish chatter and dimensional wander on the finish dimension. On hardened gear teeth and shafts, that is also where you risk grinding burn, a thermal injury to the case you cannot see without etch testing, which is brutal on parts that just survived hobbing and heat treat.

The pattern across all three of these assets is the same. The machine signals its drift well before the part fails inspection, and that signal is already sitting in spindle vibration, current draw, and cycle data. Reading it ahead of time is the difference between a planned wheel or bearing service and a scrapped finished gear.

Would it be worth a short call to walk through how this would map onto your specific hobbing and grinding lines? Twenty minutes, no slides.

Best regards,
Avanish

### Mail 4 — Day 16
**Subject:** Re: Hob spindle bearing wear on your gear hobbing line

Hi Justin,

I want to address the practical question that usually sits behind all of this, which is whether predicting these failures means another sensor rollout and another integration project on a floor that already runs hot on a high-mix schedule.

It does not. Your broaching machines are a good example. The early warning for a broach is in the hydraulic pull-force trend and pressure signature, and on most floors that data already exists in the machine control or the historian. A rising pull force or a shifting pressure curve flags a dulling broach or a hydraulic issue before it pulls an out-of-spec spline or stalls mid-cut and damages an expensive tool.

Digitillis works on the data a plant already produces, sensors, historian, and CMMS records, with no new hardware on the equipment. That keeps it out of your maintenance and IT queue and lets the prediction run against the assets you already trust.

Could we put thirty minutes on the calendar in the next week or two? I would rather tailor this to your actual hobbing, grinding, broaching, and heat-treat lines than talk in generalities.

Best regards,
Avanish

### Mail 5 — Day 30
**Subject:** Re: Hob spindle bearing wear on your gear hobbing line

Hi Justin,

I have reached out a few times about the failure modes on your precision line, and I do not want to keep landing in your inbox if the timing is not right. This is my last note for now.

Before I go, one parting thought on your CNC machining centers, since they feed everything upstream. A failure mode that quietly costs high-mix shops is ballscrew and linear guide wear. As preload is lost, positioning accuracy degrades, and on a floor running constant job changes it shows up first as creeping positional error and a rise in servo following error. The data is already in the controller, so it is one of the cleaner things to catch early before it turns into a feature you cannot hold and a part you cannot ship.

If foresight on any of these assets, hobbing, grinding, broaching, heat treat, or the CNCs, becomes worth a closer look down the road, my door is open and a short conversation is easy to set up.

Thanks for reading, and I genuinely respect the work it takes to keep a 33-facility operation running clean.

Best regards,
Avanish

---

## Arm C — Trigger-event-led
**Redwood Materials** · Ivor Bull
**Source:** https://scbiz.com/redwood-materials-battery-recycling-plant-south-carolina/


### Mail 1 — Day 0
**Subject:** Camp Hall ramp and your kiln refractory

Hi Ivor,

I saw that the first phase of the Camp Hall campus came online in December and started recovering critical minerals. Bringing a black-mass processing line up from cold at that scale is a different problem than running a seasoned plant, and the first asset I would worry about is the rotary kiln.

During early ramp on mixed-chemistry feedstock, refractory lining wear rarely shows up evenly. You get localized hot-face spalling and thinning where the charge geometry concentrates heat, and the first real signal is often a drifting shell temperature rather than anything on a PM checklist. By the time it reads on a handheld scan, you are usually already planning an unscheduled cool-down.

The part that compounds is the cool-down itself. Every unplanned thermal cycle on a young lining accelerates the next failure, so one event during ramp tends to pull the whole campaign window forward.

At a brand-new plant you do not yet have a local wear baseline to lean on, which is exactly when shell-temperature and drive-current trends are most useful and least trusted.

How are you watching for that early lining wear right now, before it forces a stop?

Best regards,
Avanish

### Mail 2 — Day 4
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

Following up on my note about early refractory wear on the kiln at Camp Hall. There is a second-order effect I left out that tends to bite during ramp.

The recirculation fans on the kiln offgas side take a beating once you are running varied black-mass feed. Particulate loading and condensable carryover build deposits unevenly on the impeller, and that mass imbalance shows up as a rising 1x vibration peak long before anyone hears it on the floor. Left alone, it works the bearings and the shaft, and a fan trip during a campaign forces the same cool-down you were trying to avoid on the lining.

So the kiln and the fan are really one risk, not two. A thermal event on the lining and a vibration trip on the fan both land as unplanned downtime in the same window, and during a first ramp those windows are the most expensive ones you have.

Most of this is already visible in the historian if the fan vibration and the kiln shell temperatures are read together rather than on separate rounds.

Are your offgas fans on continuous vibration monitoring yet, or still on periodic routes?

Best regards,
Avanish

### Mail 3 — Day 9
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

One more piece of the same picture, this time downstream of the kiln on the hydromet side.

Your leaching and solvent-extraction lines live or die on pH and temperature control, and the failure that worries me there is slow drift rather than a hard fault. A reagent dosing pump that is gradually losing volumetric efficiency, or a heat exchanger fouling on the leach circuit, will nudge pH and temperature off setpoint by amounts too small to trip an alarm. The cost does not show up as downtime. It shows up as a purity escape in the nickel or cobalt stream, which on recovered critical minerals is a quality and yield hit that is hard to claw back.

What makes this tricky during ramp is that the drift looks like normal process noise until you have enough history to separate a trend from variation, and a new line does not have that history yet.

If any of this maps to what your team is seeing, I would be glad to compare notes for twenty minutes on where the earliest signals tend to appear. No pitch, just operator to operator.

Best regards,
Avanish

### Mail 4 — Day 16
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

I have walked through three risks on your line now, the kiln lining, the offgas fans, and pH and temperature drift on the leach and extraction circuits. I want to be clear about how Digitillis would actually touch any of them, because the answer is less invasive than it sounds.

We work from the data your plant already produces. The shell-temperature tags, the fan vibration, the dosing-pump and exchanger readings, the CMMS work-order history, all of it already lives in your historian and control system. Digitillis reads those existing streams and learns the normal behavior of each asset, then flags the drift toward failure days ahead instead of at the point of trip. There is no new hardware to install, no sensors to add, and nothing that interrupts a running campaign to get started.

That matters most at a young plant, because the value is in turning the limited history you do have into an early-warning baseline faster than waiting for failures to teach you.

Would a half-hour call next week be worth it to map which of your existing tags would give the earliest warning on the kiln? I am happy to work around the ramp schedule.

Best regards,
Avanish

### Mail 5 — Day 30
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

I will stop landing in your inbox after this, since I know a ramp at Camp Hall leaves little room for cold email. Before I go, here is the one insight I would actually want in your operators' hands.

On a kiln during early life, the most reliable predictor of refractory trouble is usually not the absolute shell temperature, it is the rate of change of the hot-to-cold-face gradient at a fixed point. A lining that is thinning will let the shell temperature climb faster after each restart even when the peak still looks normal, and that acceleration tends to lead a spall by a couple of weeks. If your team trends the slope rather than the value, on the same thermocouples you already have, you can often see the lining failing before the lining tells you.

The same logic carries to the fans and the leach circuit. The early signal is almost always in the rate of change, not the reading itself.

If that is useful and you ever want a second set of eyes on it, my door stays open with no agenda. Either way, congratulations on getting first phase running, and good luck with the ramp.

Best regards,
Avanish