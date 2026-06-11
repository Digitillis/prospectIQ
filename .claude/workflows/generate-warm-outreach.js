export const meta = {
  name: 'generate-warm-outreach',
  description: 'Generate WARM / personal 1-3 touch outreach (e.g. symposium attendees) with Opus, into the ISOLATED warm workspace. Hand-sent by the founder — never on the automated pipeline.',
  whenToUse: 'Run for a warm, hand-sent list (symposium attendees, intros, referrals). Reads an attendee CSV, drafts a 1-3 touch personal sequence in Avanish\'s voice, and writes pending drafts to the warm workspace for review. Avanish sends each personally from his own Gmail. Uses Opus on the Pro Max session — no API spend.',
  phases: [
    { title: 'Prepare', detail: 'Ingest attendee CSV into the warm workspace; build threads + next touch' },
    { title: 'Generate', detail: 'Write warm, context-led emails with Opus (peer-to-peer, no templates, no fabrication)' },
    { title: 'Write', detail: 'Persist drafts to the warm workspace as pending (hand-sent; never auto-dispatched)' },
  ],
}

// ---------------------------------------------------------------------------
// args:
//   csv:        path to the attendee CSV (name,email,title,company,note) — REQUIRED
//   event:      symposium / shared-context label, e.g. "the 2026 Reliability Symposium" — REQUIRED
//   event_note: optional one-liner of shared context/theme to ground the opener
//   max_touches:1..3 (default 3)
//   limit:      max attendees to draft this run (default 50)
// ---------------------------------------------------------------------------

const csv         = (args && args.csv)         || null
const event       = (args && args.event)       || 'the symposium'
const event_note  = (args && args.event_note)  || ''
const max_touches = Math.min((args && args.max_touches) || 3, 3)
const limit       = (args && args.limit)       || 50

if (!csv) {
  return { error: 'Pass { csv: "<path-to-attendees.csv>", event: "<symposium name>" }. Aborting — nothing generated.' }
}

// Slug for sequence_name so this list is queryable + reusable for future events.
const eventSlug = ('warm_' + String(event).toLowerCase().replace(/[^a-z0-9]+/g, '_')).replace(/_+$/,'').slice(0, 60)
log(`Warm list: ${csv} | Event: ${event} | max_touches: ${max_touches} | sequence_name: ${eventSlug}`)

// ---------------------------------------------------------------------------
// Phase 1 — PREPARE: ingest attendees into the warm workspace, get threads
// ---------------------------------------------------------------------------
phase('Prepare')

const PREP_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['threads', 'created_companies', 'created_contacts', 'skipped_complete', 'collisions', 'cold_contacted_skipped', 'cold_flagged', 'workspace_id'],
  properties: {
    threads: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['company_id','company_name','contact_id','contact_name','contact_title','contact_email','domain','note','cold_collision','pending_step','prior_emails'],
        properties: {
          company_id:    { type: 'string' },
          company_name:  { type: 'string' },
          contact_id:    { type: 'string' },
          contact_name:  { type: 'string' },
          contact_title: { type: 'string' },
          contact_email: { type: 'string' },
          domain:        { type: 'string' },
          note:          { type: 'string' },
          cold_collision:{ type: ['object','null'] },
          pending_step:  { type: 'integer' },
          prior_emails:  {
            type: 'array',
            items: {
              type: 'object', additionalProperties: false,
              required: ['step','subject','body'],
              properties: { step: {type:'integer'}, subject: {type:'string'}, body: {type:'string'} }
            }
          },
        }
      }
    },
    created_companies: { type: 'integer' },
    created_contacts:  { type: 'integer' },
    skipped_complete:  { type: 'integer' },
    collisions:        { type: 'array' },
    cold_contacted_skipped: { type: 'integer' },
    cold_flagged:      { type: 'integer' },
    workspace_id:      { type: 'string' },
  }
}

const prep = await agent(
  `Ingest a warm attendee list into the ISOLATED warm workspace and return the threads to draft.
Repo: /Users/avanish/prospectIQ. Run Python from that directory.

Run exactly this and return its JSON output verbatim (it scopes everything to the warm workspace):

\`\`\`bash
cd /Users/avanish/prospectIQ && python3 scripts/warm_ingest_attendees.py ${JSON.stringify(csv)} --max-touches ${max_touches}
\`\`\`

Then return the parsed JSON. Cap the returned threads to the first ${limit}. Do not modify anything else.`,
  { label: 'prepare', phase: 'Prepare', schema: PREP_SCHEMA, model: 'sonnet' }
)

const threads = ((prep && prep.threads) || []).slice(0, limit)
const warmWs = prep && prep.workspace_id
log(`Prepared ${threads.length} threads (new companies: ${prep?.created_companies||0}, new contacts: ${prep?.created_contacts||0}, already-complete: ${prep?.skipped_complete||0}) in workspace ${warmWs}`)
if (prep?.cold_contacted_skipped) log(`Cross-channel: SKIPPED ${prep.cold_contacted_skipped} attendee(s) already cold-contacted (avoid double-touch). ${prep?.cold_flagged||0} in cold list but not yet contacted were included + flagged.`)
else if (prep?.cold_flagged) log(`Cross-channel: ${prep.cold_flagged} attendee(s) are in the cold list (not yet contacted) — included + flagged.`)

if (!warmWs) {
  return { error: 'Ingest did not return a warm workspace_id. Run scripts/seed_warm_workspace.py first and set WARM_WORKSPACE_ID. Aborting.' }
}
if (threads.length === 0) {
  return { generated: 0, message: 'No attendees needed a draft (all complete or empty CSV).' }
}

// ---------------------------------------------------------------------------
// Phase 2 — GENERATE: warm, context-led, peer-to-peer. No templates, no fabrication.
// ---------------------------------------------------------------------------
phase('Generate')

const DRAFT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['company_id','contact_id','pending_step','subject','body','personalization_notes','generation_notes'],
  properties: {
    company_id:            { type: 'string' },
    contact_id:            { type: 'string' },
    pending_step:          { type: 'integer' },
    subject:               { type: 'string' },
    body:                  { type: 'string', description: 'plain text, 120-200 words' },
    personalization_notes: { type: 'string', description: 'the verifiable shared-context hook used (symposium / their talk / role)' },
    generation_notes:      { type: 'string', description: 'how this continues the prior touch' },
  }
}

const WARM_SYSTEM_PROMPT = `You are writing a PERSONAL, hand-sent note that Avanish Mehrotra (Founder & CEO of Digitillis)
will send HIMSELF, from his own inbox, to someone who attended ${event}. The honest shared context is ONLY that
they both attended ${event} — Avanish most likely did NOT meet or speak with this person.
${event_note ? `Shared context: ${event_note}` : ''}
Digitillis builds AI-native manufacturing intelligence (predicting equipment failures, reducing unplanned downtime).
This is NOT a bulk blast and NOT a sequence machine — it is a genuine, individual note from one operator to another.

ABSOLUTE RULES (any violation = bad draft):
1. LEAD with the genuine shared context — that you both attended ${event} — plus the person's own talk/role/work
   ONLY when the note provides it. Keep it natural and specific, never forced or flattering.
2. NO FABRICATION. Use ONLY these as facts: attendance at ${event}, the provided note (if any), their title, and their
   company NAME. Do NOT invent plant details, equipment, metrics, initiatives, a prior conversation, or "I noticed your
   facility…" claims. With no note, keep it about the event and their role — genuine, never specific-sounding-but-made-up.
3. Do NOT claim or imply you met, spoke with, or remember this person unless the note explicitly says so. Co-attending
   ${event} is the only relationship you may assume.
4. Sound like one operator writing to another — warm, brief, low-pressure, first person, Avanish's voice. Not marketing copy.
5. CTA by step: Step 1 = introduce yourself genuinely off the shared event + one specific, relevant question (soft or no ask);
   Step 2 = a short relevant thought or resource, gentle "worth a quick chat?"; Step 3 = one clear soft ask (a 15-min call).
6. Step 2+ MUST open with a specific callback to the prior note; never re-introduce yourself or the premise.
7. No recycled stats, no "time-based maintenance", no "Curious —"/"Quick question:" openers, no hype.
8. Body 120-200 words, plain text. Signature exactly: "Best,\\nAvanish".
9. personalization_notes states the verifiable hook you used (the event, and the talk/role if a note gave one) — never a fabricated fact.`

const drafts = await parallel(
  threads.map(thread => () => agent(
    `${WARM_SYSTEM_PROMPT}

PERSON: ${thread.contact_name}${thread.contact_title ? `, ${thread.contact_title}` : ''}
COMPANY: ${thread.company_name}
SHARED CONTEXT NOTE: ${thread.note || '(no per-person note — anchor ONLY on co-attending ' + event + ' and their role; do NOT imply you met them; invent nothing)'}
STEP TO WRITE: Step ${thread.pending_step} of up to ${max_touches}

${thread.prior_emails.length > 0 ? `PRIOR TOUCHES ALREADY SENT (read before writing; open with a specific callback):
${thread.prior_emails.map(p => `--- Step ${p.step} ---\nSubject: ${p.subject}\n${(p.body||'').slice(0,500)}`).join('\n\n')}` : 'This is the first, warm touch.'}

Write Step ${thread.pending_step} now. Return company_id="${thread.company_id}", contact_id="${thread.contact_id}", pending_step=${thread.pending_step}.`,
    { label: `warm:${thread.contact_name?.slice(0,18)}:s${thread.pending_step}`, phase: 'Generate', schema: DRAFT_SCHEMA, model: 'opus' }
  ))
)

const validDrafts = drafts.filter(Boolean)
log(`Generated ${validDrafts.length} warm drafts`)

if (validDrafts.length === 0) {
  return { generated: 0, message: 'Generation produced no drafts.' }
}

// ---------------------------------------------------------------------------
// Phase 3 — WRITE: persist to the WARM workspace as pending (never auto-sent)
// ---------------------------------------------------------------------------
phase('Write')

const WRITE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['written', 'failed', 'draft_ids'],
  properties: {
    written:   { type: 'integer' },
    failed:    { type: 'integer' },
    draft_ids: { type: 'array', items: { type: 'string' } },
  }
}

const writeResult = await agent(
  `Write these ${validDrafts.length} WARM drafts to Supabase as pending drafts in the WARM workspace.
Repo: /Users/avanish/prospectIQ. Run Python from that directory.

CRITICAL: every insert MUST set workspace_id to the warm workspace id (get_settings().warm_workspace_id),
NOT the default/cold workspace. sequence_name = '${eventSlug}'. approval_status = 'pending'. Do NOT set sent_at.

Insert each into outreach_drafts with: workspace_id (warm), company_id, contact_id,
sequence_step = pending_step, subject, body, personalization_notes, channel = 'email',
approval_status = 'pending', sequence_name = '${eventSlug}'.

Use this pattern and assert the warm id before writing:
\`\`\`python
from backend.app.core.database import get_supabase_client
from backend.app.core.config import get_settings
ws = get_settings().warm_workspace_id
assert ws and ws != get_settings().default_workspace_id, "warm workspace not configured / equals cold"
client = get_supabase_client()
# insert each draft with workspace_id=ws ...
\`\`\`

DRAFTS TO WRITE:
${JSON.stringify(validDrafts, null, 1)}

Return count written, failed, and the list of inserted draft IDs.`,
  { label: 'write-warm', phase: 'Write', schema: WRITE_SCHEMA, model: 'sonnet' }
)

log(`Written: ${writeResult?.written || 0} | Failed: ${writeResult?.failed || 0}`)

return {
  event,
  sequence_name: eventSlug,
  workspace_id: warmWs,
  generated: validDrafts.length,
  written: writeResult?.written || 0,
  failed: writeResult?.failed || 0,
  draft_ids: writeResult?.draft_ids || [],
  message: `${validDrafts.length} warm drafts generated with Opus and written to the WARM workspace as pending. Review them, then send each personally from your own Gmail. Nothing is auto-dispatched.`
}
