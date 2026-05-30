export const meta = {
  name: 'icp-validate',
  description: 'Classify not-yet-generated companies as ICP-fit (manufacturer) vs NOT, from existing data. Haiku, no web search. Writes verdict files.',
  phases: [ { title: 'Classify', detail: 'Each agent classifies a slice of companies from name/industry/research' } ],
}

const TOTAL = 2449
const SLICE = 35
const slices = []
for (let s = 0; s < TOTAL; s += SLICE) slices.push([s, Math.min(s + SLICE, TOTAL)])

const ICP = `DIGITILLIS ICP = a company that PHYSICALLY MANUFACTURES or PROCESSES goods using production equipment (CNC, furnaces, presses, extruders, mixers, packaging/filling lines, kilns, reactors, etc.) where unplanned EQUIPMENT downtime hurts output. Discrete or process manufacturing, contract manufacturers, food/beverage processors, metal/plastics/chemicals/aerospace/automotive-parts producers all qualify.

NOT ICP (exclude): software/SaaS/tech platforms, fintech/banking/lending/insurance/crypto, car/equipment DEALERSHIPS, pure DISTRIBUTORS/WHOLESALERS (no production of their own), logistics/freight/trucking, staffing/recruiting, consulting/advisory/professional services, trade associations & marketing/promotion orgs (e.g. a dairy marketing board is NOT a dairy processor), universities/colleges, certification/standards/testing bodies, real estate/realty, oil & gas land/lease services, pure engineering-services firms with no production floor.

Note: research labels on file are unreliable (a lender may be mislabeled "discrete manufacturing") — judge from the NAME + DESCRIPTION + EQUIPMENT, not the mfg_type label. If a company both distributes AND manufactures, it is ICP_FIT.`

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['icp_fit','not_icp','unsure','verdicts'],
  properties: {
    icp_fit: { type: 'integer' }, not_icp: { type: 'integer' }, unsure: { type: 'integer' },
    verdicts: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['company_id','verdict','reason'],
      properties: {
        company_id: { type: 'string' },
        verdict: { type: 'string', enum: ['ICP_FIT','NOT_ICP','UNSURE'] },
        reason: { type: 'string' },
      } } },
  }
}

phase('Classify')
const results = await parallel(slices.map(([a,b], si) => () => agent(
  `${ICP}

Load your slice of companies (indices ${a} to ${b}):
  cd /Users/avanish/prospectIQ && python3 -c "import json;d=json.load(open('.pipeline-queues/icp_validate_input.json'));print(__import__('json').dumps(d[${a}:${b}]))"

Each record has: company_id, name, industry, mfg_type (UNRELIABLE), equipment, desc.
Classify EVERY company in the slice as ICP_FIT, NOT_ICP, or UNSURE per the definition above, judging from name + desc + equipment. Use UNSURE only when the data genuinely doesn't reveal whether they run a production floor. Do NOT web search — classify from the provided data only.

Return the counts and the full verdicts array (one entry per company_id in your slice).`,
  { label: `icp:${a}-${b}`, phase: 'Classify', model: 'haiku', schema: SCHEMA }
)))

const all = []
for (const r of results.filter(Boolean)) for (const v of (r.verdicts||[])) all.push(v)
const fit = all.filter(v=>v.verdict==='ICP_FIT').length
const not = all.filter(v=>v.verdict==='NOT_ICP').length
const uns = all.filter(v=>v.verdict==='UNSURE').length
log(`Classified ${all.length}: ICP_FIT=${fit} NOT_ICP=${not} UNSURE=${uns}`)
return { classified: all.length, icp_fit: fit, not_icp: not, unsure: uns, verdicts: all }
