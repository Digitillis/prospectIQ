# ProspectIQ — Claude Code Operating Notes

## Email generation: ALWAYS via Claude Code workflow, NEVER the backend

All outreach email generation runs through the **`generate-outreach-emails`** Claude Code
workflow (`.claude/workflows/generate-outreach-emails.js`). It uses **Opus on the active
Pro Max session — no Anthropic API spend**, and it is coherence-first (thread-aware,
escalating CTA, no recycled templates).

The backend's old `_run_draft_generation` scheduler job and its qualification/enrichment
fast-path triggers are **disabled** (`backend/app/api/main.py`). Do NOT re-enable them —
they produced Haiku-quality, template-heavy drafts with no thread continuity. If asked to
"generate emails / drafts / follow-ups," run the workflow; never call the backend OutreachAgent.

## Plain-English trigger convention

When Avanish asks to generate emails in plain language, map the request to the workflow and run it.
No JSON required from him.

| He says (examples) | Run |
|---|---|
| "generate follow-ups", "generate 50 follow-ups", "generate the next emails" | `generate-outreach-emails` with `{mode:"followup", limit:<N or 50>}` |
| "generate follow-ups for these companies <names/ids>" | `{mode:"followup", company_ids:[...]}` (resolve names → ids first) |
| "generate fresh emails / new Step 1s", "open up N new companies" | `{mode:"fresh", limit:<N>}` |
| "regenerate the broken ones" | `{mode:"followup", company_ids:[...the broken set...]}` |

Defaults: `mode="followup"`, `limit=50`. `followup` = playing-field companies (contacted,
not bounced) whose next sequence step has no pending draft. `fresh` = qualified companies
with research and no prior contact.

## Hard rules

- **Approval required before send.** The workflow writes drafts as `approval_status='pending'`.
  Nothing dispatches without human approval in the dashboard. Never auto-approve or send.
- **Playing field = contacted AND not bounced.** "Clean" (never-contacted) companies are left
  untouched unless explicitly told otherwise.
- **No new company discovery** unless explicitly requested (discovery scheduler stays paused).
