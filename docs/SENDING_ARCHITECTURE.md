# ProspectIQ — Sending Architecture

> **Last updated:** 2026-05-01
> **Source of truth for:** how emails are sent, how replies are captured, and what Instantly actually does.

---

## The three-layer model

```
SEND LAYER         →  Resend API (resend.Emails.send)
REPLY LAYER        →  Gmail IMAP polling (every 15 min, all sender mailboxes)
WARMUP LAYER       →  Instantly (account warming only — never sends real outreach)
```

These three layers are independent. Instantly does NOT touch real outreach. Resend does NOT capture replies. Gmail IMAP is the only path that surfaces replies to the application.

---

## Send layer — Resend

**File:** `backend/app/agents/engagement.py` → `_send_approved_drafts()`

All cold outreach is sent via `resend.Emails.send()` called directly in the engagement agent. The `ResendClient` class in `backend/app/integrations/resend_client.py` is **dead code** — it is not imported or used anywhere. Do not use it.

**Sender selection:**
```python
sender_index = int(md5(contact_email.encode()).hexdigest(), 16) % len(sender_pool)
sender = sender_pool[sender_index]
```

This is deterministic — the same contact always gets the same sending address. Sender pool is read from:
1. `workspaces.settings.sender_pool` JSONB (primary, set in DB)
2. `config/outreach_guidelines.yaml` (fallback)
3. Hardcoded `avi@digitillis.io` (last resort fallback)

**Reply-To:** Always set to `avi@digitillis.io` regardless of which sending account is used.

**Confirmed live:** 192 emails sent as of 2026-05-01, all `source=resend`, all with `resend_message_id`.

**Tracking:** Resend fires webhooks at `POST /api/webhooks/resend` for `delivered`, `opened`, `clicked`, `bounced`, `complained`. Configure `RESEND_WEBHOOK_SECRET` in the Resend dashboard for HMAC authentication (not yet set).

---

## Reply layer — Gmail IMAP

**File:** `backend/app/api/main.py` → `_gmail_intake_workspace()`
**Schedule:** Every 15 minutes via APScheduler.

Since Resend sends from the 9 sender mailboxes, replies land directly in those Gmail inboxes. IMAP polling is the **only** way the application sees replies. There is no other path.

### How multi-mailbox polling works

For each workspace, the intake builds a list of `(email, app_password)` pairs:

1. **Primary account** — env vars `GMAIL_USER` + `GMAIL_APP_PASSWORD` (fallback when no cred in DB)
2. **Additional accounts** — for each entry in `workspace.settings.sender_pool`, looks up app password from `workspace_credentials` table using:
   - `provider = "gmail_{email_safe}"` where safe = email with `@` → `_at_`, `.` → `_`
   - `key_name = "app_password"`

### Required DB tables and env vars

| Requirement | Status |
|---|---|
| `workspace_credentials` table (migration 030) | Must be applied to production |
| `CREDENTIAL_ENCRYPTION_KEY` env var (Fernet base64 key) | Must be set before credentials can be stored |
| App password for `avi@digitillis.io` | Set via `GMAIL_APP_PASSWORD` env var |
| App passwords for the other 8 sender accounts | Must be stored via `CredentialStore.set()` |

### How to add IMAP credentials for a sender account

Prerequisites per account:
1. Enable IMAP in Gmail: Settings → Forwarding and POP/IMAP → Enable IMAP
2. Generate app password: `myaccount.google.com/apppasswords` (requires 2FA)

Then run:
```python
from backend.app.core.credential_store import CredentialStore
store = CredentialStore("00000000-0000-0000-0000-000000000001")
email = "avanish@trydigitillis.com"
safe_key = email.replace("@", "_at_").replace(".", "_")
store.set(f"gmail_{safe_key}", "app_password", "xxxx xxxx xxxx xxxx")
```

### Reply handling after capture

For each reply, the intake:
1. Matches to an `outreach_drafts` row by subject or contact email
2. Classifies intent via keyword heuristics (`_classify_intent`)
3. Writes to `thread_messages`, `interactions`, `campaign_threads`
4. For `interested` / `question` / `objection` / `referral`: calls `ReplyAgent` to generate a response draft (`approval_status=pending`) and pushes to `hitl_queue` for your review
5. Triggers a pipeline advance check 30 seconds later

---

## Warmup layer — Instantly

**Instantly is connected to all 9 sender mailboxes for inbox warming only.**

Warmup keeps sender reputation healthy. Instantly sends automated warmup emails between seeded accounts and marks them as read. This has nothing to do with prospect outreach.

**What the code uses Instantly for:**
- `EngagementAgent._poll_instantly_events()` — polls warmup analytics every 6 hours for account health monitoring. Read-only, no side effects.
- `EngagementAgent._check_campaign_status()` — checks if a campaign is active for analytics purposes. Read-only.
- Instantly webhook at `POST /webhooks/instantly` — accepts events from Instantly. Because no real prospects are enrolled, all incoming events resolve to `contact_not_found` and are dropped silently.

**What the code does NOT use Instantly for:**
- Sending outreach emails (Resend does this)
- Capturing replies (IMAP does this)

---

## Active sender accounts (as of 2026-05-01)

| Account | Daily limit | Warmup score | IMAP configured |
|---|---|---|---|
| avi@digitillis.io | 30 | 100% | Yes (env var) |
| avanish@trydigitillis.com | 30 | 100% | Pending |
| hello@trydigitillis.com | 30 | 100% | Pending |
| avanish@meetdigitillis.com | 30 | 100% | Pending |
| hello@meetdigitillis.com | 30 | 100% | Pending |
| avanish@usedigitillis.com | 30 | 100% | Pending |
| hello@usedigitillis.com | 30 | 100% | Pending |
| avanish@getdigitillis.com | 30 | 100% | Pending |
| hello@getdigitillis.com | 30 | 100% | Pending |
| **Total** | **270/day** | — | 1 of 9 |

---

## Required env vars

| Var | Required for | Status |
|---|---|---|
| `RESEND_API_KEY` | Sending outreach | Set |
| `GMAIL_USER` | Primary IMAP inbox | Set (`avi@digitillis.io`) |
| `GMAIL_APP_PASSWORD` | Primary IMAP inbox | Set |
| `CREDENTIAL_ENCRYPTION_KEY` | Storing per-account IMAP passwords in DB | **NOT SET** |
| `RESEND_WEBHOOK_SECRET` | Authenticated Resend tracking webhooks | **NOT SET** |
| `INSTANTLY_API_KEY` | Warmup analytics polling | Set |
| `INSTANTLY_WEBHOOK_SECRET` | Warmup webhook HMAC verification | Set |
| `INSTANTLY_SEQ_*` (11 vars) | **OBSOLETE — unused by any automated path** | Remove |

---

## Required DB migrations (unapplied as of 2026-05-01)

| Migration | Creates | Blocking what |
|---|---|---|
| `019_campaign_threads_hitl.sql` | `campaign_threads`, `thread_messages`, `hitl_queue` | HITL queue is never populated; reply thread tracking silently fails |
| `020_sequence_builder_v2.sql` | `campaign_sequence_definitions_v2` | V2 sequence processing falls back to V1 |
| `030_workspace_credentials.sql` | `workspace_credentials` table, `sender_pool`/`reply_to`/`gmail_user` columns on `outreach_send_config` | IMAP credentials can't be stored; 8 of 9 mailboxes not polled |

Apply in order: 019 → 020 → 030.

---

## Dangerous code paths — do not invoke

These files/functions still exist in the codebase but must not be called from automated paths. They would enroll real prospects into Instantly campaigns and cause double-contact:

| Path | Risk | Status |
|---|---|---|
| `backend/scripts/push_to_sequences.py` | Bulk-enrolls contacts into Instantly campaigns | **Remove or add `sys.exit("DEPRECATED")` guard** |
| `backend/scripts/daily_outreach.py` step 5 (`_run_sequence_push`) | Calls `push_to_sequences` | **Remove step 5** |
| `backend/scripts/manage_thread.py` `send` subcommand | Sends replies via Instantly instead of Resend | **Replace with Resend path or remove** |
| `InstantlyClient.add_lead_to_campaign()` | Enrolls contact in Instantly campaign | **Never call from automated code** |
| `InstantlyClient.add_leads_to_campaign()` | Same, bulk | **Never call from automated code** |
| `sequence_router.get_campaign_id*()` | Maps personas to Instantly campaigns | Dead in automated path; only called by above scripts |

---

## Mental model for future contributors

> "If your task involves **sending** an email: edit `engagement.py`. It calls Resend.
> If your task involves **capturing replies**: edit `gmail_imap.py` and `_gmail_intake_workspace()` in `main.py`.
> If you find yourself adding code to `push_to_sequences.py` or calling `InstantlyClient.add_lead_to_campaign`, stop — you are heading in the wrong direction.
> Instantly is a warmup utility. It does not touch prospect communication."
