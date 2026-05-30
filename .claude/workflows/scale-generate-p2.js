export const meta = {
  name: 'scale-generate-p2',
  description: 'Overnight batch outreach generation: web-ground + Opus full/remaining arc per company, write pending drafts. args:{phase,file,count}',
  phases: [ { title: 'Generate', detail: 'One agent per company: ground, generate, write pending drafts' } ],
}

// BATCH CONFIG — edit these per run (args global is not populated for scriptPath invocations).
const PHASE = '2'
const FILE  = '/tmp/piq_p2_enriched.json'
const START = 0
const END   = 40

const STEP_DAYS = '{1:0, 2:4, 3:9, 4:16, 5:30}'

const RULES = `VOICE & FORMAT (founder Avanish Mehrotra's personal style, conform exactly):
- Greeting on its own line: "Hi {FirstName}," then a blank line. Short paragraphs (2-4 sentences), blank line between. No bullet lists.
- Close with "Best regards," then "Avanish".
ABSOLUTE BANS (a single violation fails the email): NO em dashes (— –) and NO ellipses (...). NO customer-base/traction claim (we are PRE-CUSTOMER; never "I run a company that works with...", "we work with plants like yours", "our customers", named/implied clients). NO recycled stats ("15-20%","40-65%","SMRP","18 days"), NO "time-based maintenance schedules", NO canned openers ("Curious,","Quick question:"), NO fabricated anecdotes/replies, NO generic hooks ("manufacturers like yours").
CAPABILITY TRUTH: Digitillis reads the data a plant ALREADY produces (historian, CMMS/work orders, PLC/SCADA tags, ERP), learns each asset's normal behavior, and surfaces drift toward failure early, before it trips an alarm or reaches inspection. No new sensors, no rip-and-replace. Use SOFT lead-time only ("days ahead", "before it forces a stop") — never a specific day-count. Refer to integrations generically ("your existing historian, CMMS, and ERP"); name no vendors. Do NOT mention vibration at all (not even conditionally) in this run; use motor/drive current, spindle/drive load, temperature, cycle time, pressure, and work-order history instead. Do NOT guarantee an outcome or claim we already model their specific asset.
HARD URL REQUIREMENT: every email's personalization_notes MUST contain a real https:// URL you actually found. If you cannot find ANY real source URL for this company (no event, no reachable company website), skip its contacts (count them as skipped) — never write an email with an empty or invented source URL.
VOICE: first-person, peer-to-peer, founder-to-operator. Open on the single highest-risk NAMED asset, name the specific failure mode in correct trade vocabulary, connect to the operational ripple. 150-220 words each.
SEQUENCE ARC (one coherent thread; each mail builds explicitly on the prior, never re-introduces; never reference internal labels like "step 2"):
  Step 1 (day 0): cold open, asset + failure mode + operational ripple + one soft answerable question. No link.
  Step 2 (day 4): explicit callback to step 1, add ONE new consequence or sub-asset, soft probe.
  Step 3 (day 9): deepen with a different sub-asset within the same domain, light meeting probe.
  Step 4 (day 16): substantiate (works on existing data, no new hardware), clearer low-pressure meeting ask.
  Step 5 (day 30): breakup + a genuine technical insight as a parting gift, low-friction door, NO hard ask.
ARM SELECTION: if your web search finds a STRONG, specific, recent (last ~18 months) company event (capex, plant/expansion, leadership hire, certification, recall, acquisition), use ARM C: lead each email's framing from that event, cite its real URL. Otherwise use ARM A: lead with the asset failure mode and operational consequence, and use the company website as the source URL. Either way, personalization_notes carries the real source URL.`

const STATUS = {
  type:'object', additionalProperties:false,
  required:['company_id','company','arm','emails_written','contacts_done','skipped','note'],
  properties:{
    company_id:{type:'string'}, company:{type:'string'}, arm:{type:'string'},
    emails_written:{type:'integer'}, contacts_done:{type:'integer'},
    skipped:{type:'integer'}, note:{type:'string'},
  }
}

phase('Generate')

const idx = Array.from({length: END - START}, (_, k) => START + k)
let done = 0
const results = await parallel(idx.map(i => () => agent(
  `${RULES}

You are generating outreach for ONE manufacturing company (Phase ${PHASE}). Steps map to send-days: ${STEP_DAYS}.

1. Load the company record at index ${i}:
   cd /Users/avanish/prospectIQ && python3 -c "import json;d=json.load(open('${FILE}'));print(__import__('json').dumps(d[${i}]))"
   The record has: company, website, mfg_type, equipment, pain_points, company_description, and contacts[] (each with contact_id, name, title, email, remaining[] = the step numbers to generate${PHASE === '1' ? ', and prior[] = emails already SENT to this contact with step/subject/body — your new emails MUST continue that thread, never re-introduce' : ''}).

2. Decide the arm and get a real source URL. IF the record already has equipment/pain_points (prior research exists), web search is OPTIONAL: do AT MOST ONE quick WebSearch for a recent event; if it does not return a clear event promptly, immediately use ARM A with the company website as the source URL. Do not retry searches. (This keeps search load low.) Decide ARM C (event-led, cite the real event URL) or ARM A (operational-pain-led, company website URL).
   DEEP-RESEARCH MODE: if the record's equipment and pain_points are empty/null (no prior research on file), you MUST first research this company from the web — their website, recent news, the nature of their products and processes — to identify their likely highest-risk production assets and the failure modes that matter. Ground every asset detail in what you actually find; never invent equipment they do not run. If after searching you cannot establish any specific asset or credible hook for this company, skip its contacts (count them in "skipped") rather than send something generic.

3. For EACH contact, generate its "remaining" steps as one coherent arc, honoring every rule above. Use the company's equipment and pain_points for asset specificity. ${PHASE === '1' ? 'IMPORTANT: read each contact\'s prior[] sent emails and continue the thread (callback, no re-introduction). The remaining steps may start at 2, 3, or 5.' : 'Write the full arc for the steps listed (normally 1-5).'} Each contact greets "Hi {their first name},".

4. Write ALL generated emails for this company to a JSON file, then insert them:
   - Build a JSON array; each item: {company_id, contact_id, sequence_step, subject, body, personalization_notes, arm}. personalization_notes = the real source URL + the specific fact used.
   - Use the Write tool to save it to /tmp/piq_gen_p${PHASE}_${i}.json
   - Then run: cd /Users/avanish/prospectIQ && python3 /tmp/piq_write_drafts.py /tmp/piq_gen_p${PHASE}_${i}.json
   - Confirm the printed {"inserted": N} count.

5. Return the status: company_id, company, arm ("A" or "C"), emails_written (the inserted count), contacts_done, skipped, and a short note (e.g. the event used, or "no event, used asset hook").

Do not invent a source URL. Do not violate any ban. If WebSearch is rate-limited or fails, fall back to ARM A with the company website.`,
  { label:`p${PHASE}:${i}`, phase:'Generate', model:'opus', schema:STATUS }
)))

const ok = results.filter(Boolean)
const totalEmails = ok.reduce((s,r)=>s+(r.emails_written||0),0)
const totalSkipped = ok.reduce((s,r)=>s+(r.skipped||0),0)
const armC = ok.filter(r=>r.arm==='C').length
log(`Phase ${PHASE}: ${ok.length}/${idx.length} companies done, ${totalEmails} emails written, ${armC} used Arm C, ${totalSkipped} contacts skipped`)
return { phase: PHASE, companies_done: ok.length, companies_total: idx.length, emails_written: totalEmails, arm_c: armC, skipped: totalSkipped, failures: idx.length - ok.length }
