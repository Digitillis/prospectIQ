export const meta = {
  name: 'repair-seq-gaps',
  description: 'Sequence-gap repair: regenerate missing steps for 12 contacts whose pending arc had a hole. Phase-1 path (reads prior sent emails, continues thread). 10 companies, 44 emails.',
  phases: [ { title: 'Repair', detail: 'One agent per company: continue existing thread, generate missing + remaining steps, write pending drafts' } ],
}

// Repair run — 10 companies, 12 contacts, 44 emails
const FILE  = '/Users/avanish/prospectIQ/.pipeline-queues/piq_repair_remaining.json'
const START = 0
const END   = 10

const STEP_DAYS = '{1:0, 2:4, 3:9, 4:16, 5:30}'

const RULES = `VOICE & FORMAT (founder Avanish Mehrotra's personal style, conform exactly):
- Greeting on its own line: "Hi {FirstName}," then a blank line. Short paragraphs (2-4 sentences), blank line between. No bullet lists.
- Close with "Best regards," then "Avanish".
ABSOLUTE BANS (a single violation fails the email): NO em dashes (— –) and NO ellipses (...). NO customer-base/traction claim (we are PRE-CUSTOMER; never "I run a company that works with...", "we work with plants like yours", "our customers", named/implied clients). NO recycled stats ("15-20%","40-65%","SMRP","18 days"), NO "time-based maintenance schedules", NO canned openers ("Curious,","Quick question:"), NO fabricated anecdotes/replies, NO generic hooks ("manufacturers like yours").
CAPABILITY TRUTH: Digitillis reads the data a plant ALREADY produces (historian, CMMS/work orders, PLC/SCADA tags, ERP), learns each asset's normal behavior, and surfaces drift toward failure early, before it trips an alarm or reaches inspection. No new sensors, no rip-and-replace. Use SOFT lead-time only ("days ahead", "before it forces a stop") — never a specific day-count. Refer to integrations generically ("your existing historian, CMMS, and ERP"); name no vendors. Do NOT mention vibration at all; use motor/drive current, spindle/drive load, temperature, cycle time, pressure, and work-order history instead. Do NOT guarantee an outcome or claim we already model their specific asset.
HARD URL REQUIREMENT: every email's personalization_notes MUST contain a real https:// URL you actually found. If you cannot find ANY real source URL for this company (no event, no reachable company website), skip its contacts — never write an email with an empty or invented source URL.
VOICE: first-person, peer-to-peer, founder-to-operator. Open on the single highest-risk NAMED asset, name the specific failure mode in correct trade vocabulary, connect to the operational ripple. 150-220 words each.
SEQUENCE ARC (one coherent thread; each mail builds explicitly on the prior, never re-introduces; never reference internal labels like "step 2" or "step 3"):
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

phase('Repair')

const idx = Array.from({length: END - START}, (_, k) => START + k)
let done = 0
const results = await parallel(idx.map(i => () => agent(
  `${RULES}

You are doing a SEQUENCE REPAIR for ONE manufacturing company. Steps map to send-days: ${STEP_DAYS}.

This company already has emails SENT to contacts. Your job is to generate the MISSING and REMAINING steps as a coherent continuation of each contact's existing thread. The contact's prior[] array contains the emails already sent (step/subject/body truncated to ~450 chars) — you MUST read each one carefully and write continuations that explicitly build on them.

1. Load the company record at index ${i}:
   cd /Users/avanish/prospectIQ && python3 -c "import json;d=json.load(open('${FILE}'));print(__import__('json').dumps(d[${i}]))"
   The record has: company, website, mfg_type, equipment, pain_points, company_description, and contacts[] (each with contact_id, name, title, email, remaining[] = step numbers to generate, and prior[] = emails already SENT to this contact with step/subject/body).

2. Decide the arm and get a real source URL:
   a. If "website" is present, that is your Arm A fallback source URL.
   b. If "website" is empty/null, do ONE WebSearch for the company name to find its real official website/domain. Use that real URL as the source.
   c. Optionally (one quick search) look for a recent event -> ARM C (event-led, cite the real event URL). Else ARM A.
   ONLY skip a company if, after the search, it has NO findable web presence OR is clearly NOT a manufacturer.

3. For EACH contact, generate its "remaining" steps as a coherent continuation:
   CRITICAL: Read each contact's prior[] sent emails and EXPLICITLY CONTINUE that thread.
   - The new Step 2 (if in remaining) must explicitly reference the topic of Step 1 that was sent (callback — "following up on my note about...", referencing the specific asset or failure mode you raised).
   - The new Step 3 (if in remaining) must deepen within the same domain (a different sub-asset or angle), not re-open fresh.
   - Do NOT re-introduce Digitillis or the contact's company as if you have never spoken. The thread is already warm.
   - Never reference internal labels ("step 2", "step 3", "my second email").
   - Treat the prior[] body as the email that was sent — you may reference its specific wording, asset, or question.
   Each contact greets "Hi {their first name},".

4. Write ALL generated emails for this company to a JSON file, then insert them:
   - Build a JSON array; each item: {company_id, contact_id, sequence_step, subject, body, personalization_notes, arm}.
   - personalization_notes = the real source URL + the specific fact used.
   - Use the Write tool to save it to /Users/avanish/prospectIQ/.pipeline-queues/gen_repair_${i}.json
   - Then run: cd /Users/avanish/prospectIQ && python3 .pipeline-queues/piq_write_drafts.py .pipeline-queues/gen_repair_${i}.json
   - Confirm the printed {"inserted": N} count.

5. Return the status: company_id, company, arm ("A" or "C"), emails_written (the inserted count), contacts_done, skipped, and a short note (e.g. the event used, what the prior thread was about).

Do not invent a source URL. Do not violate any ban. If WebSearch is rate-limited, fall back to ARM A with the company website.`,
  { label:`repair:${i}`, phase:'Repair', model:'opus', schema:STATUS }
)))

const ok = results.filter(Boolean)
const totalEmails = ok.reduce((s,r)=>s+(r.emails_written||0),0)
const totalSkipped = ok.reduce((s,r)=>s+(r.skipped||0),0)
const armC = ok.filter(r=>r.arm==='C').length
log(`Repair: ${ok.length}/${idx.length} companies done, ${totalEmails} emails written, ${armC} used Arm C, ${totalSkipped} contacts skipped`)
return { companies_done: ok.length, companies_total: idx.length, emails_written: totalEmails, arm_c: armC, skipped: totalSkipped, failures: idx.length - ok.length }
