# ProspectIQ — Production-Standard Sample (Arms A & C, capability-truth pass)

*Generated 2026-05-29 via Opus (Pro Max). APPROVED production standard. Vibration softened to existing-historian signals; soft lead-time; generic integrations; no overclaim; no em dashes/ellipses. Nothing sent.*

Cadence: Day 0 / +4 / +9 / +16 / +30 (breakup close).


---

## Arm A — Operational pain
**Martin Sprocket & Gear** · Justin Holmes
**Source:** https://geaps2024.smallworldlabs.com/exhibitors/exhibitor/223


### Mail 1 — Day 0
**Subject:** Hob spindle drift before the gear quality slips

Hi Justin,

The failure mode I keep coming back to on a high-mix gear shop is the hob spindle on a hobbing machine drifting long before anyone calls it a problem. Bearing preload relaxes, the spindle load and motor current creep up cut over cut, and the first visible symptom is profile or lead error showing up at gear inspection rather than on the floor. By then you have already cut a batch.

What makes it costly at a plant running agriculture and mining drive components is the ripple. A hob that is quietly degrading does not just scrap its own parts, it pushes rework onto your grinders and stretches an already tight high-mix schedule, so one drifting spindle becomes a throughput problem two operations downstream.

The signals that show it early are usually already streaming from the PLC, spindle load and drive current trended against cycle time, not anything new you would have to install.

When a hob spindle starts going on you, what tells you first, the part at inspection or something an operator notices at the machine?

Best regards,
Avanish

### Mail 2 — Day 4
**Subject:** Re: Hob spindle drift before the gear quality slips

Hi Justin,

Following up on my note about hob spindle drift on your hobbing line. There is a second place the same early-drift problem hides that tends to hurt more on gear work, the carburizing furnace.

Case-depth variability rarely announces itself. A carbon-potential or oxygen probe slowly reading off, or one heat zone's thermocouples wandering a few degrees across a campaign, and the gears come out within spec on paper but soft or inconsistent in the case where it matters for fatigue. For agriculture and mining components that see shock load, that is the kind of escape you find in the field, not at final inspection.

The reason I raise it alongside hobbing is that both are the same pattern, a slow drift in data you already log, surfaced while you can still correct the recipe instead of quarantining a load. Furnace zone thermocouples and carbon-potential readings already sit in the historian for exactly this.

On the heat-treat side, is case-depth consistency something you watch lot to lot, or mostly trust to the recipe and periodic checks?

Best regards,
Avanish

### Mail 3 — Day 9
**Subject:** Re: Hob spindle drift before the gear quality slips

Hi Justin,

Two notes back I raised the hob spindle, last week the carburizing furnace. There is a third asset in the same chain that fails quietly in a different way, the broaching machine.

With broaches the early tell is usually hydraulic. Pull pressure starts climbing for the same part as the broach edges wear or the hydraulics lose efficiency, and the cycle time stretches a little before you see torn or undersized splines. On internal-spline gear parts that drift sends rework straight back through the same grinders that are already absorbing any hobbing variance, so the broach and the hob end up competing for the same recovery capacity.

The grinder itself shows the same story from a third angle, spindle load creeping as a wheel loads up or dressing falls behind, which is the last place you want surprise variation on a precision gear.

None of this needs new instrumentation, the hydraulic pressure and spindle load are already on the PLC. If it is useful, I would happily walk through how this would map onto one of your lines on a short call, no obligation.

Best regards,
Avanish

### Mail 4 — Day 16
**Subject:** Re: Hob spindle drift before the gear quality slips

Hi Justin,

I have written about the hobbing spindle, the carburizing furnace, and the broach and grinders. The fair question is whether catching any of this actually requires a project, and it does not.

What we do reads the data your plant already produces, the PLC and SCADA tags, the historian, your CMMS work-order history and ERP. From that it learns what normal looks like for each specific asset and flags when one starts drifting toward trouble, before it trips an alarm or shows up at inspection. No new sensors, no rip and replace, no change to how your operators run the machine. It sits on top of what is already there.

The reason this fits a high-mix gear shop is precisely the mix. Fixed thresholds struggle when the same machine runs twenty different parts a week, whereas learning each asset's own normal handles that variation instead of fighting it.

Across 33 facilities you have a lot of this data already sitting in logs. Would a thirty minute call make sense to see whether one of your CNC or hobbing lines is a sensible first place to point it?

Best regards,
Avanish

### Mail 5 — Day 30
**Subject:** Re: Hob spindle drift before the gear quality slips

Hi Justin,

I have come at your gear line from a few angles now, the hob spindle, the heat-treat case depth, the broach and grinders, so I will leave it here and not keep crowding your inbox.

One parting thought that costs you nothing to use. On most of these assets the earliest honest leading indicator is not a temperature or a pressure limit, it is cycle time drifting for an unchanged part program. When a hob, a broach, or a grinder quietly takes a few percent longer to make the same part it has been making, the machine is usually telling you something mechanical or thermal has moved, often before any single tag crosses a threshold. If you only watch one trend per asset with what you already log, watch cycle time against the part number and let the rest hang off it.

If the timing is ever better, my door is open and a short call is easy to set up. Either way, I hope the gear lines run clean through your busy season.

Best regards,
Avanish

---

## Arm C — Trigger-event-led
**Redwood Materials** · Ivor Bull
**Source:** https://scbiz.com/redwood-materials-battery-recycling-plant-south-carolina/


### Mail 1 — Day 0
**Subject:** Camp Hall ramp and your kiln refractory

Hi Ivor,

I saw the first phase of the Camp Hall campus came online in December and is already recovering critical minerals. Ramping a black-mass calcination line on a brand-new site is the part I keep thinking about, because the rotary kilns are carrying the most risk before anyone has a local wear baseline to trust.

The failure mode I would watch first is refractory degradation on mixed-chemistry feedstock. As lining condition drifts, the shell-temperature tags start showing hot spots and the drive pulls more torque to turn the same charge, often well before a cool-down forces the issue. On a new line those early signatures look like noise until you have weeks of normal behavior to compare against.

The trouble is that the first months are exactly when you have the least history and the most feedstock variation, so the baseline you most need is the one you do not have yet.

How are you establishing what normal looks like for the kilns during this ramp, when every batch of incoming packs is a little different?

Best regards,
Avanish

### Mail 2 — Day 4
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

Following up on my note about refractory wear on the calcination kilns during the Camp Hall ramp. There is a second consequence worth naming, because it tends to hide behind the kiln itself.

When a kiln runs hotter or works harder to hold temperature, the offgas recirculation fans inherit the load. The signal that usually moves first is fan bearing temperature creeping up alongside drive current, and on recirculation duty the dust and condensate make those bearings unforgiving. A fan that trips during a ramp can drag a kiln into an unplanned cool-down, and the thermal cycle is rough on the very lining you are trying to protect.

So the kiln and the fan are really one risk surface, not two. The early drift on each shows up in tags you are already collecting.

Are the offgas fans on the same condition watch as the kilns right now, or are they still treated as run-to-trip support equipment?

Best regards,
Avanish

### Mail 3 — Day 9
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

Staying in the same plant but moving downstream from the kilns and fans. The hydromet side carries its own slow failure mode that is easy to miss while attention is on the thermal end.

In the leaching and solvent-extraction lines, a small drift in pH or temperature is where purity escapes start. The instrument trends rarely fall off a cliff. They wander, and a reagent dosing pump that is losing flow or holding the wrong pressure will nudge pH out of band gradually, so the off-spec batch looks like a one-off rather than a trend. Reading the dosing-pump flow and pressure together with the pH and temperature tags is usually enough to catch the drift before it costs you a batch.

Given how tight cathode-grade purity has to be, that early wander matters more here than almost anywhere on the site.

Would a short call be useful to compare how you are watching the leaching trends today? Twenty minutes, no deck.

Best regards,
Avanish

### Mail 4 — Day 16
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

One thing I should have said earlier about the kiln, fan, and leaching signals I have been describing. None of it asks you to add hardware to a plant you just stood up.

Digitillis reads the data your lines already produce, your existing historian, CMMS work orders, and the PLC and SCADA tags, then learns what normal looks like for each asset and flags drift toward failure early, before it trips an alarm or forces a stop. So the shell-temperature hot spots, the fan bearing creep, and the pH wander I mentioned are all things it learns from streams you are already capturing at Camp Hall. No new sensors, no rip-and-replace, and the baseline builds itself as the ramp generates history.

That last part is the point for a new site. The faster you accumulate normal behavior, the sooner the early warnings become trustworthy.

If it is worth thirty minutes, I would walk you through how this would sit on top of your current tags for one kiln line. Happy to work around your schedule.

Best regards,
Avanish

### Mail 5 — Day 30
**Subject:** Re: Camp Hall ramp and your kiln refractory

Hi Ivor,

I will stop landing in your inbox after this one, since you are clearly heads-down getting Camp Hall to rate.

Before I go, one genuinely useful thing on the kilns. During early ramp on mixed feedstock, the most reliable lining-wear tell is not the shell temperature on its own, it is the relationship between shell temperature and drive torque over time. A rising hot spot at the same torque usually means a thinning section of refractory, while rising torque at steady temperature points more to ring or buildup forming inside. Tracking the two together separates wear from fouling, and it is a comparison you can build today from tags you already log, no extra instrumentation required.

That alone has saved a few thermal cycles for teams who watch it deliberately during a new-line ramp.

If the timing is ever right, the door is open and a short call is easy to set up. Either way, congratulations on getting the first phase recovering minerals, and good luck with the ramp.

Best regards,
Avanish