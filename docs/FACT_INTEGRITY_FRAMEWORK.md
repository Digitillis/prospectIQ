# ProspectIQ — Fact Integrity & Recommendation Validation Framework

> **Status:** Governance infrastructure — permanent, not version-dated.
> **Author:** Avanish Mehrotra & Digitillis Architecture Team
> **Created:** 2026-05-13
> **Purpose:** Ensure no strategic recommendation, KPI, operational assessment, or architectural conclusion enters doctrine documents without explicit evidence validation.

This framework is a direct response to factual errors embedded in ProspectIQ doctrine during the 2026-05-12 GTM assessment — specifically: incorrect sender domain attribution, an unsupported bounce rate figure, conflation of distinct failure modes, and a strategic conclusion drawn from statistically insufficient Touch-1-only data. See `STRATEGIC_INTELLIGENCE.md` INVALIDATED ASSUMPTIONS for the full record.

---

## Part 1 — Evidence Hierarchy

Every claim in ProspectIQ doctrine must trace to a level in this hierarchy. The level determines what can be stated as fact versus what must be labeled.

### Level 1 — Direct System Evidence
*Highest authority. Can be stated as fact.*

- Database records (queried directly, with table/column cited)
- Application logs (with timestamp and log level)
- Code paths (with file path and line number)
- API responses (with endpoint, request, and response cited)
- Scheduler state (with job name and last-run timestamp)
- Send telemetry (with source table and aggregation method)
- Configuration files (with file path and key name)

**Required citation format:** `[source: table.column, queried YYYY-MM-DD]` or `[source: file/path.py:line_number]`

### Level 2 — Derived Calculations
*Computed from Level 1 data. Can be presented as derived fact with formula cited.*

- Metrics computed from raw DB records (with SQL or pseudocode)
- Cohort analysis results (with filter criteria stated)
- Rate calculations (with numerator, denominator, and source for each)
- Bounce decomposition (with breakdown method cited)
- Progression rates (with time window and population stated)

**Required citation format:** Formula must be stated. Example: `4.15% = 45 bounced / 1,084 sent [source: outreach_drafts, queried 2026-05-12]`

**Critical rule:** A rate that combines distinct populations (e.g., verified and unverified contacts) must be decomposed, not presented as a single metric. Conflation of distinct failure modes into a single figure is a validation failure.

### Level 3 — Strategic Inference
*Derived from Level 1 and Level 2. Must cite supporting evidence. Cannot be presented as fact without evidence.*

- GTM interpretations
- Operational hypotheses
- Strategic recommendations
- Doctrine conclusions
- Architecture decisions

**Rule:** Every Level 3 claim must cite at least one Level 1 or Level 2 item as its basis. Level 3 claims without traceable evidence must be labeled `HYPOTHESIS` or `SPECULATION` (see Part 3).

---

## Part 2 — Mandatory Recommendation Validation Checklist

Before any recommendation is added to a doctrine document, the author must be able to answer YES or N/A to all applicable questions.

### Metric validation
- [ ] Was the underlying metric verified by a direct DB query, not recalled from memory or copied from a summary?
- [ ] Is the formula stated explicitly (numerator / denominator / source table)?
- [ ] Are distinct failure modes separated rather than aggregated?
- [ ] Is the sample size stated, and is it sufficient to support the conclusion drawn?

### Domain and configuration validation
- [ ] Was the sender domain confirmed from `config/outreach_guidelines.yaml` or the `outreach_send_config.sender_pool` DB record — not assumed?
- [ ] Was the infrastructure state (send_enabled, daily_limit, scheduler jobs) confirmed from live config, not from memory?

### Sequence and sample validity
- [ ] Was sequence completeness considered? (A Touch-1-only reply rate is not a valid measure of a multi-touch sequence's effectiveness.)
- [ ] Is the time window stated? (Rolling 7-day, all-time, a specific burst period?)
- [ ] Are quality-failure periods separated from normal-operation periods in the analysis?

### Inference validity
- [ ] Is the recommendation confined to what the evidence supports, or does it extrapolate beyond the data?
- [ ] Is the recommendation architecture-biased (preferring a technically interesting solution over the simplest fix)?
- [ ] Does the recommendation distinguish between "this is broken" and "we have not yet measured whether this works"?

### Contradiction check
- [ ] Does this recommendation conflict with any statement in any other current doctrine document?
- [ ] Does this recommendation conflict with observed code behavior?
- [ ] If there is a conflict, has it been explicitly resolved rather than silently overwritten?

---

## Part 3 — Assumption Labeling System

All claims in doctrine documents must carry one of the following labels where the claim is not self-evidently factual. Labels appear inline in the text or as a suffix in parentheses.

| Label | Meaning | When to use |
|---|---|---|
| `VERIFIED` | Confirmed from Level 1 direct system evidence | DB queries, code reads, log inspection |
| `DERIVED` | Computed from verified data with stated formula | Rate calculations, cohort analyses |
| `HYPOTHESIS` | Plausible inference from evidence but not yet confirmed | Strategic inferences, architectural predictions |
| `SPECULATION` | No supporting evidence; asserted without traceable basis | Claims that cannot be traced to any data source |
| `INVALIDATED_ASSUMPTION` | Previously embedded assumption disproven by evidence | See INVALIDATED ASSUMPTIONS in `STRATEGIC_INTELLIGENCE.md` |

### Usage rules

- `VERIFIED` and `DERIVED` require citation. If a citation cannot be provided, downgrade to `HYPOTHESIS`.
- `SPECULATION` must be explicitly labeled. Speculation presented as fact without a label is a governance violation.
- `INVALIDATED_ASSUMPTION` entries must be logged in `STRATEGIC_INTELLIGENCE.md` INVALIDATED ASSUMPTIONS with full provenance.
- Labels do not need to appear on every sentence in a narrative section. They are required on: KPI definitions, operational thresholds, strategic conclusions, architectural recommendations, and any claim that could affect send behavior, domain management, or GTM doctrine.

### Examples

**Correct:**
> "True deliverability bounce rate is estimated at ~1.3% `DERIVED [45 bounces × 32% verified-but-bounced / 1,084 sends; source: outreach_drafts + failure analysis, 2026-05-12]`."

**Incorrect (presented as fact without citation):**
> "The domain reputation has been compromised by a 6.6% bounce rate."

**Correct after correction:**
> "The 6.6% bounce rate claim is `INVALIDATED_ASSUMPTION IA-002`. Measured combined failure rate: 4.15% `DERIVED`. No data produces 6.6%."

---

## Part 4 — Contradiction Detection Process

### When to apply
- Before adding any new claim to a doctrine document
- When two documents are updated in the same session
- Whenever a recommendation conflicts with an observation from direct code or DB inspection
- As part of any strategic review or retrospective

### Detection steps

1. **Identify the claim** — state it precisely in one sentence.
2. **Search existing doctrine** — grep the claim's key terms across all docs in `docs/`. Note any conflicting statements.
3. **Search code and config** — confirm the claim against the live system state, not against prior summaries.
4. **Resolve explicitly** — if a conflict exists, it must be resolved in one of three ways:
   - **Correction:** the old claim was wrong; update it and log in INVALIDATED ASSUMPTIONS.
   - **Context:** both claims are correct in different contexts; add context labels to disambiguate.
   - **Pending:** the conflict cannot be resolved without more data; label both claims `HYPOTHESIS` and add to Open Questions.
5. **No silent overwrites** — deleting or overwriting a prior claim without explanation is not permitted. The reason for the change must be stated.

### Common contradiction patterns to check

| Pattern | Check |
|---|---|
| Domain name claim | Confirm from `outreach_guidelines.yaml` sender_pool and `SENDING_ARCHITECTURE.md` |
| Bounce or failure rate | Confirm numerator and denominator from `outreach_drafts` table |
| Send count | Confirm from `outreach_drafts WHERE sent_at IS NOT NULL` |
| Reply count | Confirm from `interactions WHERE type = 'reply'` |
| Scheduler state | Confirm from `main.py` lifespan scheduler registration — not from memory |
| Account cap | Confirm whether it is a measured constraint or a workflow estimate |
| Sequence completion | Confirm from `outreach_drafts` grouped by contact_id and sequence_step |

---

## Part 5 — Doctrine Review Protocol

### When a doctrine document is updated

1. Identify every claim in the updated section.
2. Label each claim with its evidence level (VERIFIED / DERIVED / HYPOTHESIS / SPECULATION).
3. Check the Contradiction Detection checklist.
4. If any claim is SPECULATION, either provide a citation to upgrade it or remove it.
5. If any claim was previously embedded as fact and is now known to be wrong, create an INVALIDATED_ASSUMPTION entry.

### Frequency

| Trigger | Review scope |
|---|---|
| Any doctrine document updated | The updated section only |
| Any strategic retrospective | All doctrine documents |
| Any new pipeline metric added | Metric definition, formula, and source table |
| Any send pause or resume decision | The pause/resume rationale — must be verifiable |
| Any architecture decision | The stated reason — must cite evidence level |

### Who is responsible

The author of any doctrine update is responsible for applying the checklist before the content is added. Claude Code must apply this framework before adding any claim to a ProspectIQ doctrine document. If a claim cannot be validated at the time of writing, it must be labeled `HYPOTHESIS` and added to Open Questions.

---

## Appendix — Invalidated Assumptions Quick Reference

For the full record, see `STRATEGIC_INTELLIGENCE.md` § Invalidated Assumptions.

| ID | Assumption | Status | Correction |
|---|---|---|---|
| IA-001 | digitillis.com was the cold sending domain | INVALIDATED | Sending domains: digitillis.io + 4 verb-prefix .com variants |
| IA-002 | 6.6% bounce rate | INVALIDATED | No data source produces 6.6%; measured combined rate is 4.15% |
| IA-003 | 4.15% = domain reputation risk | INVALIDATED | 4.15% is a combined metric; true deliverability rate ~1.3%, below threshold |
| IA-004 | 0.09% reply rate invalidates the outbound model | INVALIDATED | Touch-1-only, quality-failure-era data; sequence completion ~0%; statistically insufficient |
| IA-005 | Subdomain migration is a send-resume prerequisite | INVALIDATED | Verification gate (PR #76) is the actual fix; subdomain migration is good practice |
