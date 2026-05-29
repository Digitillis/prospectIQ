export const meta = {
  name: 'generate-outreach-emails',
  description: 'Generate cold outreach emails using Opus (Pro Max session). Writes pending drafts to Supabase. Requires explicit approval before sending.',
  whenToUse: 'Run this workflow to generate new outreach drafts. It uses Opus from the active Claude Code Pro Max session — no Anthropic API spend. Always requires human review and approval before emails are dispatched.',
  phases: [
    { title: 'Discover', detail: 'Find companies + contacts that need an email, load thread context' },
    { title: 'Generate', detail: 'Write emails with Opus — thread-aware, coherence-first, no templates' },
    { title: 'Write', detail: 'Persist drafts to Supabase as pending (approval required before send)' },
  ],
}

// ---------------------------------------------------------------------------
// args schema (passed when invoking):
//   mode: 'followup' | 'fresh'
//     followup — generate Step N+1 for playing-field companies (contacted, not bounced)
//     fresh    — generate Step 1 for qualified companies with research (no prior contact)
//   limit: integer (default 50) — max drafts to generate this run
//   company_ids: optional array of specific company UUIDs to target
// ---------------------------------------------------------------------------

const mode        = (args && args.mode)        || 'followup'
const limit       = (args && args.limit)       || 50
const company_ids = (args && args.company_ids) || null

log(`Mode: ${mode} | Limit: ${limit} | Company filter: ${company_ids ? company_ids.length + ' ids' : 'none'}`)

// ---------------------------------------------------------------------------
// Phase 1 — DISCOVER: query Supabase for companies + threads that need emails
// ---------------------------------------------------------------------------
phase('Discover')

const DISCOVER_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['threads', 'total_found', 'playing_field_size'],
  properties: {
    threads: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['company_id','company_name','contact_id','contact_name','contact_title','contact_email','pending_step','prior_emails','research'],
        properties: {
          company_id:     { type: 'string' },
          company_name:   { type: 'string' },
          contact_id:     { type: 'string' },
          contact_name:   { type: 'string' },
          contact_title:  { type: 'string' },
          contact_email:  { type: 'string' },
          pending_step:   { type: 'integer' },
          prior_emails:   {
            type: 'array',
            items: {
              type: 'object', additionalProperties: false,
              required: ['step','subject','body'],
              properties: { step: {type:'integer'}, subject: {type:'string'}, body: {type:'string'} }
            }
          },
          research: {
            type: 'object', additionalProperties: false,
            required: ['manufacturing_type','equipment_types','known_systems','pain_points','personalization_hooks','company_description'],
            properties: {
              manufacturing_type:  { type: 'string' },
              equipment_types:     { type: 'array', items: {type:'string'} },
              known_systems:       { type: 'array', items: {type:'string'} },
              pain_points:         { type: 'array', items: {type:'string'} },
              personalization_hooks: { type: 'array', items: {type:'string'} },
              company_description: { type: 'string' },
            }
          },
        }
      }
    },
    total_found:        { type: 'integer' },
    playing_field_size: { type: 'integer' },
  }
}

const discovered = await agent(
  `You are discovering which companies need outreach emails generated.
Repo: /Users/avanish/prospectIQ. Run Python from that directory.

MODE: ${mode}
LIMIT: ${limit}
COMPANY_IDS_FILTER: ${company_ids ? JSON.stringify(company_ids) : 'null (no filter)'}

Run this Python script to pull the data:

\`\`\`python
cd /Users/avanish/prospectIQ && python3 -c "
import json
from backend.app.core.database import Database
from collections import defaultdict

db = Database()

# Playing field: contacted + not bounced
sent_rows = db.client.table('outreach_drafts').select('company_id,contact_id,sequence_step,subject,body,edited_body,sent_at').not_.is_('sent_at','null').limit(5000).execute().data or []
contacted_ids = set(r['company_id'] for r in sent_rows)
bounced_d = db.client.table('outreach_drafts').select('company_id').not_.is_('bounced_at','null').limit(5000).execute().data or []
bounced_c = db.client.table('contacts').select('company_id').eq('outreach_state','bounced').limit(5000).execute().data or []
bounced = set(r['company_id'] for r in bounced_d) | set(r['company_id'] for r in bounced_c)
playing_field = contacted_ids - bounced

mode = '${mode}'
limit = ${limit}
company_filter = ${company_ids ? JSON.stringify(company_ids) : 'None'}

if mode == 'followup':
    # Find playing-field companies whose next step has no pending/approved draft
    sent_by_contact = defaultdict(list)
    for r in sent_rows:
        sent_by_contact[r['contact_id']].append(r)

    pending_rows = db.client.table('outreach_drafts').select('contact_id,sequence_step').eq('approval_status','pending').is_('sent_at','null').limit(5000).execute().data or []
    approved_rows = db.client.table('outreach_drafts').select('contact_id,sequence_step').in_('approval_status',['approved','edited']).is_('sent_at','null').limit(5000).execute().data or []
    has_pending_step = defaultdict(set)
    for r in pending_rows + approved_rows:
        has_pending_step[r['contact_id']].add(r['sequence_step'])

    candidates = []
    for cid in playing_field:
        if company_filter and cid not in company_filter:
            continue
        contacts_sent = [r for r in sent_rows if r['company_id'] == cid]
        if not contacts_sent:
            continue
        # Group by contact
        by_contact = defaultdict(list)
        for r in contacts_sent:
            by_contact[r['contact_id']].append(r)
        for contact_id, steps in by_contact.items():
            steps_sent = sorted(set(r['sequence_step'] for r in steps))
            max_step = max(steps_sent)
            next_step = max_step + 1
            if next_step > 4:
                continue  # 4-step sequence max
            if next_step in has_pending_step.get(contact_id, set()):
                continue  # already has a pending draft for next step
            candidates.append({'company_id': cid, 'contact_id': contact_id, 'next_step': next_step, 'prior_steps': steps})
    candidates = candidates[:limit]
elif mode == 'fresh':
    # Qualified companies with research, no prior contact
    fresh_cos = [cid for cid in (company_filter or []) if cid not in contacted_ids] if company_filter else []
    if not fresh_cos:
        qual_cos = db.client.table('companies').select('id').eq('status','qualified').limit(500).execute().data or []
        fresh_cos = [r['id'] for r in qual_cos if r['id'] not in contacted_ids][:limit]
    candidates = [{'company_id': cid, 'contact_id': None, 'next_step': 1, 'prior_steps': []} for cid in fresh_cos]

print(json.dumps({'candidates': candidates, 'playing_field_size': len(playing_field)}))
"
\`\`\`

Then for each candidate, enrich with:
- company record (name, research_summary, manufacturing_profile, personalization_hooks, pain_signals, technology_stack)
- contact record (full_name, title, email)
- research_intelligence row (manufacturing_type, equipment_types, known_systems, pain_points, personalization_hooks, company_description)
- prior sent emails (subject + body/edited_body, sorted by sequence_step)

Cap enrichment at the first ${limit} candidates. Return all data in the schema.`,
  { label: 'discover', phase: 'Discover', schema: DISCOVER_SCHEMA, model: 'sonnet' }
)

const threads = (discovered && discovered.threads) || []
log(`Found ${threads.length} threads to generate (playing field: ${discovered?.playing_field_size || 0})`)

if (threads.length === 0) {
  log('Nothing to generate. Exiting.')
  return { generated: 0, message: 'No eligible threads found for the requested mode and limit.' }
}

// ---------------------------------------------------------------------------
// Phase 2 — GENERATE: Opus writes each email, thread-aware, coherence-first
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
    body:                  { type: 'string', description: 'plain text email body, 150-250 words' },
    personalization_notes: { type: 'string', description: 'source URL(s) and grounding facts used in this email' },
    generation_notes:      { type: 'string', description: 'brief note on how this continues the prior thread' },
  }
}

const SYSTEM_PROMPT = `You are writing cold outreach emails for Avanish Mehrotra, Founder & CEO of Digitillis.
Digitillis sells AI-native manufacturing intelligence: predicting equipment failures, reducing unplanned downtime,
and replacing reactive maintenance with condition-based foresight. Target buyers: plant managers, VP Operations,
COOs, Directors of Maintenance/Reliability at discrete manufacturing companies.

ABSOLUTE RULES (any violation = bad draft):
1. NEVER re-introduce the product or the problem premise if a prior email already did. Treat it as known.
2. ALWAYS open Step 2+ with an explicit, specific callback to something from the prior email — not "circling back" generically.
3. NEVER fabricate a reply from the prospect. They have not responded.
4. STAY in the same asset/equipment domain across all steps unless a one-sentence bridge explains the shift.
5. CTA must ESCALATE each step: Step 1 = diagnostic question | Step 2 = deepen/substantiate + softer meeting probe | Step 3 = specific ask (15-min call, named deliverable, pilot framing).
6. NO recycled stats without asset-specific grounding (no "15-20%", "18 days out", "SMRP 2023" without qualification).
7. NO "time-based maintenance schedules" — use "calendar-based PMs" or asset-specific language.
8. NO "Curious —" or "Quick question:" openers — vary the CTA form.
9. Body: 150-250 words. Plain text. Signature: "Best,\\nAvanish".
10. personalization_notes MUST include at least one source URL for the hook.`

const drafts = await parallel(
  threads.map(thread => () => agent(
    `${SYSTEM_PROMPT}

COMPANY: ${thread.company_name}
CONTACT: ${thread.contact_name}, ${thread.contact_title}
STEP TO WRITE: Step ${thread.pending_step}

RESEARCH INTELLIGENCE:
- Manufacturing type: ${thread.research.manufacturing_type}
- Key equipment: ${(thread.research.equipment_types || []).join(', ')}
- Known systems: ${(thread.research.known_systems || []).join(', ') || 'unknown'}
- Pain points: ${(thread.research.pain_points || []).slice(0,3).join('; ')}
- Personalization hooks: ${(thread.research.personalization_hooks || []).slice(0,3).join('; ')}
- Company description: ${thread.research.company_description?.slice(0, 300)}

${thread.prior_emails.length > 0 ? `PRIOR EMAILS SENT (read carefully before writing):
${thread.prior_emails.map(p => `--- Step ${p.step} (already sent) ---\nSubject: ${p.subject}\n${p.body?.slice(0,500)}`).join('\n\n')}

CONTINUITY REQUIREMENT: Your email must open with a specific callback to Step ${thread.prior_emails[thread.prior_emails.length-1].step}'s content.
Do not re-introduce the product. The prospect already received those emails.` : 'This is the first email to this contact.'}

Write Step ${thread.pending_step} now. Return company_id="${thread.company_id}", contact_id="${thread.contact_id}", pending_step=${thread.pending_step}.`,
    { label: `gen:${thread.company_name?.slice(0,20)}:s${thread.pending_step}`, phase: 'Generate', schema: DRAFT_SCHEMA, model: 'opus' }
  ))
)

const validDrafts = drafts.filter(Boolean)
log(`Generated ${validDrafts.length} drafts`)

// ---------------------------------------------------------------------------
// Phase 3 — WRITE: persist to Supabase as pending (no auto-send)
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
  `Write these ${validDrafts.length} outreach drafts to Supabase as pending drafts (approval_status='pending', sent_at=NULL).
Repo: /Users/avanish/prospectIQ. Run from that directory.

Each draft must be inserted into outreach_drafts with:
  - company_id, contact_id (from the draft)
  - sequence_step = pending_step
  - subject, body
  - personalization_notes (the source URL + grounding facts)
  - approval_status = 'pending'
  - sequence_name = 'email_value_first'
  - workspace_id = the default workspace id from config

Do NOT set sent_at. These are pending approval only.

DRAFTS TO WRITE:
${JSON.stringify(validDrafts, null, 1)}

Use this Python pattern:
\`\`\`python
from backend.app.core.database import Database
from backend.app.core.config import get_settings
db = Database()
ws_id = get_settings().default_workspace_id
# insert each draft...
\`\`\`

Return count of written, failed, and list of inserted draft IDs.`,
  { label: 'write-to-db', phase: 'Write', schema: WRITE_SCHEMA, model: 'sonnet' }
)

log(`Written: ${writeResult?.written || 0} | Failed: ${writeResult?.failed || 0}`)

return {
  mode,
  generated: validDrafts.length,
  written: writeResult?.written || 0,
  failed: writeResult?.failed || 0,
  draft_ids: writeResult?.draft_ids || [],
  message: `${validDrafts.length} drafts generated with Opus (Pro Max session) and written to Supabase as pending. Review and approve in the dashboard before any email is sent.`
}
