# Claude Code Generation Trigger — 001
## ProspectIQ — Research & Draft Generation Under the Subscription, Not the Metered API

**Author:** Avanish Mehrotra & Digitillis Architecture Team
**Status:** Accepted, in effect (2026-08-15)
**Related:** the 2026-08-15 send-path reconciliation (`STAGED_ACTIVATION_PROGRESSION_001.md`,
`DARK_LAUNCH_RUNTIME_OBSERVATION_004.md`); `CLAUDE.md`'s own operating note at the top of this
repo ("Email generation: ALWAYS via Claude Code workflow, NEVER the backend").

---

## 1. What this document is

CLAUDE.md already states the doctrine in one line. This document is the operational detail
that line didn't cover: how the trigger actually works, what it costs, what it does and does not
gate, and two real defects this session found and fixed in the mechanism.

## 2. The trigger

Generation is **human-invoked, batched, and explicit** — not a schedule, not a webhook.

| Workflow | Use | Model | Writer |
|---|---|---|---|
| `.claude/workflows/generate-outreach-emails.js` | Standard run: discover due threads, generate, write pending | Opus (generate), Sonnet (discover/write) | `scripts/piq_write_drafts.py` |
| `.claude/workflows/scale-generate.js` | Overnight batch, phase 1 (fresh + prior-thread continuation) | Opus | `scripts/piq_write_drafts.py` |
| `.claude/workflows/scale-generate-p2.js` | Overnight batch, phase 2 | Opus | `scripts/piq_write_drafts.py` |
| `.claude/workflows/repair-seq-gaps.js` | Backfill a sequence gap for specific contacts | Opus | `scripts/piq_write_drafts.py` |
| `.claude/workflows/generate-warm-outreach.js` | Warm/personal workspace | Opus | (own path, warm workspace only) |

Invoke via the Workflow tool (`/workflows`, or `Workflow({name: 'generate-outreach-emails', ...})`
in a Claude Code session). Each run is bounded — `limit` args on the standard workflow, fixed
`START`/`END` company ranges on the batch scripts — deliberately, not by omission. See §5.

## 3. Cost — subscription-covered, not free capacity

Verified against the official Claude Code documentation (not assumed):

- Runs on the Claude Code subscription (Pro/Max) consume the plan's existing usage allowance.
  There is no separate per-call charge the way the Anthropic API bills per token.
- If usage exceeds the plan's allowance, further runs are **rejected**, not queued or degraded,
  unless usage credits are explicitly enabled at `claude.ai/settings/usage` — which is metered
  overage billing, i.e. real additional spend. **Leave usage credits off.** With them off, the
  worst case of a large batch is a skipped run, never a surprise bill.
- This is genuinely different from "free": a large generation run competes with the same
  allowance used for engineering work in Claude Code that day. The trade-off is allowance, not
  dollars.

**Measured effect on tracked API spend** (`api_costs` table, `estimated_cost_usd`, read-only
verification 2026-08-15): **$246.27 in May 2026 → $3.28 in June → $7.82 in July** — a ~97% drop,
consistent with generation having moved to the subscription workflows above. The small residual
(June/July) traced to `batch_id="engagement_*"` — the scheduler still calling `OutreachAgent`
directly. Closed in this same change; see §6.

## 4. What generation still runs on the metered API — deliberately

Classification and reporting are **not** covered by this doctrine and are unaffected by anything
in this document: `title_classifier.py`, `reply_classifier.py` (Haiku, cheap, genuinely
runtime-reactive to an inbound event), `daily_report.py` (one Haiku call/day). The doctrine is
about *generating content* (research, draft copy, personalization hooks) — not about reacting to
an event with a cheap classification call.

CLI scripts (`run_research.py`, `run_instantly_research.py`, `run_sequence.py`, `weekend_run.py`,
`backend/scripts/run_outreach.py`) and the on-demand HTTP routes that reach the same generation
work (`POST /api/outreach/generate`, `/api/outreach/generate-batch`,
`/api/personalization/run/{company_id}`, `/api/personalization/run-batch`) are gated by the same
`LLM_GENERATION_ENABLED` flag as the scheduler (§6) — they are not a blessed alternate path. An
operator who wants metered generation from any of them sets `LLM_GENERATION_ENABLED=true`
explicitly, the same conscious-choice pattern `SEND_ENABLED` already establishes for sending.

**Correction (same-session, caught by independent adversarial review before merge):** the first
version of this section, and of `llm_generation_gate.py`'s own docstring, named
`POST /api/outreach/generate` and `/api/personalization/refresh` as covered examples. Both
citations were wrong: `/api/outreach/generate` resolves to a *different* class also named
`OutreachAgent` (`backend/app/agents/outreach_agent.py`, unrelated to the gated class in
`outreach.py`), which was still calling the Anthropic API directly; and
`/api/personalization/refresh` does not exist anywhere in this repo — the real single-company
route, `/api/personalization/run/{company_id}`, calls `PersonalizationEngine.run_full_pipeline()`
directly, a caller the gate on `PersonalizationBatch.run_batch()` did not cover. Both are now
gated (see `llm_generation_gate.py`'s docstring for the corrected, complete list of five entry
points). Recorded here per this session's own review discipline: a claim in an operations doc is
exactly as capable of being wrong as a claim in code.

## 5. Batch sizing — generate to a horizon, not to exhaust the corpus

Direct evidence for this rule, not a guess: the send-path reconciliation found `outbound_queue`
holding 579 rows, all sequence steps 2–5, 554 drafted in May 2026, 55% no longer dispatchable
because their prior step was never sent. Generating far ahead of the actual send cadence produces
drafts that are stale before they can be used — the recommendation there was to purge that queue
and regenerate fresh, rather than keep sending 2-month-old personalization.

Keep batch sizes bounded to what the send cadence can actually clear in the near term. The
existing `limit`/`START`/`END` args on every workflow above already enforce this — do not remove
them "to save a run."

## 6. Two defects this session found and fixed in the mechanism itself

These are not doctrine changes — the doctrine ("generate via Claude Code, not the backend") was
already correct. These are bugs in how it was implemented.

1. **Three scheduler jobs contradicted the doctrine.** `_run_process_due_sequences`,
   `_run_jit_pregenerate`, and `_run_personalization_refresh` (`backend/app/api/main.py`) were
   still active and reached `OutreachAgent`/`ResearchAgent`/`PersonalizationBatch` directly,
   spending API tokens the doctrine says should not be spent by the deployed service. This is
   the source of the residual June/July spend in §3. **Fixed**: `LLM_GENERATION_ENABLED`
   (`backend/app/core/config.py`, default `false`), enforced in
   `backend/app/core/llm_generation_gate.py`, checked at the entry of all three generation
   classes. Sequence advancement in `_run_process_due_sequences` is unaffected — it still runs;
   it just stops generating new content while the flag is off.

2. **A silent draft-discard bug in the write path.** `send_scheduler.py`'s model filter
   (`drafts = [d for d in all_pending_drafts if d.get("model")]`) exists specifically because an
   earlier version of this filter caused a documented "silent send blackout (D2)". Despite that,
   `generate-outreach-emails.js`'s Write phase asked a sub-agent to write its own insert code from
   a prose field list that never mentioned `model` — so every draft it wrote had `model=NULL`
   and was silently dropped from the send schedule, the exact failure mode the filter's own
   comment warns about. **Fixed**: replaced the freehand insert instruction in every workflow
   above with a call to `scripts/piq_write_drafts.py`, a single tracked writer that sets
   `model="opus-via-claude-code"` in code — not left to an agent's per-run discretion — and
   applies the same `_check_draft_integrity()` / `is_step_1_url_violation()` quality gates
   `OutreachAgent` applies to its own drafts (previously bypassed entirely on the Claude Code
   write path). It also routes through `Database.insert_outreach_draft()`'s dedup guards, which
   the previous untracked writer (`/Users/avanish/prospectIQ/.pipeline-queues/piq_write_drafts.py`
   — a local file in no repository, and `scale-generate-p2.js` pointed at an even more ephemeral
   `/tmp/piq_write_drafts.py`) bypassed by inserting directly.

## 7. Research provenance — deliberately not built yet

`research_intelligence` has no `model`/provenance column, and none is added by this change. Every
current workflow's research grounding (WebSearch results, the "DEEP-RESEARCH MODE" step in
`scale-generate.js`) feeds directly into that run's email generation — none of them write findings
back to `research_intelligence` or `companies.research_summary` for reuse. There is currently no
live caller that would use a research-provenance marker.

**If a future workflow is built that does persist research findings** (mirroring
`piq_write_drafts.py` for research rather than drafts), record provenance in
`companies.custom_tags` — already a JSONB field carrying `research_path` (see `research.py`'s
`"research_path": "haiku_only"` for the cheap-triage case) — rather than adding a schema column or
repurposing `research_intelligence.perplexity_response`, which is dead (always `""`) and would be
a misleading name for the purpose. Building the write path itself, before a workflow needs it, was
deliberately deferred — it would be exactly the dormant, caller-less path this reconciliation's
other findings warn against.

## 8. Recurring/unattended generation — not enabled by this change

Everything above remains **human-triggered**. A recurring unattended trigger (Claude Code
scheduled cloud agents / "routines") was considered and is documented as a deliberate later step,
gated on: `LLM_GENERATION_ENABLED`'s scheduler-side leaks being closed (done, §6), a credential
decision (a routine's cloud VM has no dedicated secrets store — the Supabase service-role key
should not go into plaintext environment config without a scoped-down key or an external secret
manager), and one measured manual run to size actual usage-allowance consumption before
automating it. Not part of this change.
