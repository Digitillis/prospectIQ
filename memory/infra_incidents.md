---
name: Infrastructure Incidents
description: Anthropic cap incident April 1; batching fix applied; cap resets May 1
type: project
---

## April 1, 2026 — Anthropic Monthly Cap Kill

**What happened:** Research pipeline hit monthly usage cap mid-run. 1,730 jobs failed, 384 partial. $33.01 in API credits consumed with no recoverable output.

**Root cause:** All jobs ran in a single `execute()` context. Cost committed only at `monitor.finish()` at end of run. Cap kill prevented finish() from running → cost never committed.

**Fix applied:** Restructured to 50 companies per `execute()` call, each with its own `pipeline_runs` row. Max exposure per kill is now ~$1.25.

**Current state:** Cap hit again today ($2.34 committed successfully, no money lost — batching worked). **Cap resets May 1, 2026.** Consider pre-paying Anthropic credits before then.

**Cost per company:** ~$0.0253 (claude-sonnet-4-6, 1,400 input tokens, 800 output tokens)

## Key Scripts
- `run_instantly_research.py` — batched runner (50/batch, best PQS first)
- `run_pipeline_loop.sh` — orchestrates all 5 pipeline loops in parallel

## api_costs Table Note
`api_costs` table does NOT have a `workspace_id` column. `log_api_cost()` in `database.py` must NOT call `_inject_ws()`. Fixed 2026-04-01.
