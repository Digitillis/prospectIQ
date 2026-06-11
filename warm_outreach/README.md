# Warm / Personal Outreach

A separate, hand-sent channel for people you share real context with (symposium attendees,
intros, referrals). Drafts are written by Opus with a warm, peer-to-peer prompt and a 1-3 touch
cap. **You send each one personally from your own Gmail.** Nothing here is ever auto-dispatched.

## Why it can't mix with cold prospects

Warm lives in its **own `workspace_id`** (`WARM_WORKSPACE_ID`, default `…0002`), separate from the
cold workspace (`…0001`). The whole cold pipeline is workspace-scoped and fail-closed
(`database._filter_ws` raises if no workspace is set), so cold code cannot see warm data even if a
filter is ever forgotten. On top of that boundary:

- The warm workspace's `subscription_status = 'internal'` → it is **excluded from
  `get_active_workspaces()`**, so no scheduler job (recompute, enqueue, dispatch, gmail_intake,
  process_due, jit_pregenerate) ever touches it.
- Its `outreach_send_config` has `send_enabled=false`, `daily_limit=0`, `sender_pool=[]` → a second,
  independent gate: it has no sending identity even if dispatch were invoked by hand.
- Global suppression (`do_not_contact`) stays shared — anyone who unsubscribes anywhere is honored.
- Keep your personal sending mailbox OUT of the cold `sender_pool` so cold reply-intake never sees
  your warm replies — they stay in your inbox.

`tests/test_warm_isolation.py` asserts these guarantees and fails loudly if any regress.

## One-time setup

```bash
python3 scripts/seed_warm_workspace.py        # creates the inert warm workspace + send-off config
pytest tests/test_warm_isolation.py -q        # confirm isolation
```

(The warm id defaults to `…0002` via config; set `WARM_WORKSPACE_ID` in `.env` to override.)

## Each campaign

1. Make a CSV like `attendees.example.csv` — columns: `name,email,title,company,note`.
   The `note` (their talk / how you met) is the strongest, always-verifiable hook.
2. Generate drafts (Opus, Pro Max session — no API spend):
   ```
   invoke generate-warm-outreach { csv: "warm_outreach/attendees.csv",
                                   event: "the 2026 Reliability Symposium",
                                   event_note: "two days on plant reliability",
                                   max_touches: 3 }
   ```
   This ingests the list into the warm workspace and writes pending drafts there.
3. Review + send by hand:
   ```
   python3 scripts/warm_review.py                 # read drafts, copy into Gmail, send personally
   python3 scripts/warm_mark.py sent <draft_id>   # record the send
   python3 scripts/warm_mark.py replied <email>   # track a reply
   python3 scripts/warm_mark.py meeting <email>   # track a meeting
   ```
   Re-running `generate-warm-outreach` on the same list produces the next touch (Step 2, then 3)
   for contacts you've already sent — capped at `max_touches`.

## Deferred (may grow)

Reviewing warm drafts in the **web dashboard** (instead of the CLI) needs a membership-verified
workspace switcher: the dashboard binds workspace from the Supabase JWT with no per-request switch.
The clean follow-up is an `X-Workspace-Id` override in `WorkspaceMiddleware` honored only when the
authenticated user is a verified `workspace_members` row, plus a sidebar selector. You are already
seeded as a member of the warm workspace, so that work is unblocked when wanted.
