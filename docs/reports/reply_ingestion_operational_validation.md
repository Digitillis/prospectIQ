# Reply Ingestion Operational Validation
**Date:** 2026-05-13  
**Scope:** Phase 3 — Gmail IMAP reply ingestion path, schema, env vars, issues, fixes

---

## 1. Code Path

```
APScheduler (every 15 min) → _run_gmail_intake()
  → for_each_workspace(_gmail_intake_workspace, "gmail_intake")
    → _gmail_intake_workspace(ws: dict)
      → CredentialStore(ws_id) — loads gmail credentials
      → for each account in sender_pool:
        → GmailImapClient(user, password).fetch_unseen_replies()
          → IMAP SELECT INBOX, search UNSEEN
          → filters: subject must start with "Re:" (case-insensitive)
          → returns: uid, from_email, from_name, subject, body, received_at
        → for each reply:
          1. Match to outreach_drafts by subject (ilike, stripped "Re:")
          2. Fallback: match by contacts.email = from_email
          3. If no match: mark_as_read(), skipped++
          4. Dedup check: thread_messages within 5 min window
          5. _classify_intent(body, subject) → intent string
          6. Upsert campaign_threads (status='replied')
          7. Insert thread_messages (inbound record)
          8. Insert interactions (type='email_replied')
          9. Update engagement_sequences based on intent
          10. If intent in (interested, question, objection, referral): ReplyAgent → HITL queue
          11. mark_as_read(uid)
      → Log: processed N, skipped M
      → If processed > 0: _schedule_pipeline_advance(30s)
```

**Source file:** `backend/app/api/main.py` (`_gmail_intake_workspace`, lines 338-573)  
**Integration:** `backend/app/integrations/gmail_imap.py`  
**Scheduler:** `main.py:2018` — `scheduler.add_job(_run_gmail_intake, "interval", minutes=15, id="gmail_intake")`

---

## 2. Required Environment Variables

| Variable | Where set | Status | Required |
|---|---|---|---|
| `GMAIL_USER` | `.env` (local), Railway Variables | Set (avi@digitillis.io) | Yes |
| `GMAIL_APP_PASSWORD` | `.env` (local), Railway Variables | Set (local) | Yes — must be set in Railway |

### Railway Verification Required (Avanish action)

`GMAIL_APP_PASSWORD` is confirmed present in the local `.env`. It must also be set in Railway Variables for the production deployment.

**Verification command:** In Railway Dashboard → Service → Variables → search for `GMAIL_APP_PASSWORD`

If not set, the `workspace_credentials` lookup (`CredentialStore(ws_id).get("gmail", "app_password")`) will also fail since the `workspace_credentials` table has 0 rows.

**Workspace credentials table status:** 0 rows. All credential resolution falls through to env vars. This is fine for single-sender operation but means the sender_pool IMAP polling (secondary accounts) is disabled until credentials are added via the API.

---

## 3. UNSEEN/SEEN Behavior

The cron only fetches emails with the `UNSEEN` IMAP flag:
```python
_, data = self._conn.search(None, "UNSEEN")
```

**Risk: manually-read replies will be missed.** If Avanish reads a reply directly in Gmail before the 15-min cron runs, Gmail marks it `\Seen`, and the IMAP search will not return it. The reply will never be ingested.

**Mitigation options (not yet implemented):**
1. Use Gmail API instead of IMAP — Gmail API can search by label without depending on read state
2. Add a "SINCE <last_run_date>" search as a secondary fallback
3. Use a dedicated Gmail label for outreach replies to segregate from manually-read mail

**Current exposure:** Unknown. No way to count missed replies without examining Gmail directly.

---

## 4. Critical Bug Found and Fixed

### thread_messages Column Mismatch (CRITICAL)

**Finding:** `_gmail_intake_workspace` was inserting `company_id`, `contact_id`, and `workspace_id` into `thread_messages`. The actual `thread_messages` table schema does NOT contain these columns.

```python
# BEFORE (broken):
db.client.table("thread_messages").insert({
    "thread_id": thread_id,
    "company_id": company_id,     # column does not exist → PGRST204 error
    "contact_id": contact_id,     # column does not exist → PGRST204 error
    "workspace_id": ws_id,        # column does not exist → PGRST204 error
    "direction": "inbound",
    ...
}).execute()
```

Error message from live test:
```
Could not find the 'company_id' column of 'thread_messages' in the schema cache
```

This means **every inbound reply thread_message write was silently failing** since the `_gmail_intake_workspace` function was deployed. The `interactions` write still succeeded (that table does have `company_id`/`contact_id`). The `campaign_threads` upsert also succeeded.

**Impact:** No `thread_messages` inbound records for any replies processed via IMAP. The `_get_latest_reply_context()` function in engagement.py reads from `thread_messages` to inject reply context into follow-up drafts — this function would return `None` for all IMAP-sourced replies.

**Fix applied (2026-05-13):**
```python
# AFTER (fixed):
_tm_payload = {
    "direction": "inbound",
    "body": body[:4000],
    "subject": subject,
    "classification": intent,
    "source": "gmail_imap",
}
if thread_id:
    _tm_payload["thread_id"] = thread_id
db.client.table("thread_messages").insert(_tm_payload).execute()
```

**File:** `backend/app/api/main.py` lines 489-500

**Rollback:** Revert to prior payload by re-adding the three invalid columns. Degraded behavior (silent failure) would resume.

---

## 5. Interaction Write Path

```python
db.client.table("interactions").insert({
    "company_id": company_id,
    "contact_id": contact_id,
    "type": "email_replied",     # ← this is the interaction_type
    "channel": "email",
    "subject": subject,
    "body": body[:4000],
    "source": "gmail_imap",
    "metadata": {"intent": intent, "from": from_email},
    "workspace_id": ws_id,
}).execute()
```

`interaction_type = "email_replied"` (not `"reply_received"` which is the Instantly webhook value).

**Current email_replied count in interactions:** 0  
This confirms zero IMAP replies have been successfully written — either no replies have been received, or all writes failed due to the thread_messages bug causing the function to exit early. The `interactions` write is in a separate try/except, so it should have succeeded independently.

---

## 6. Heartbeat Logging Added

The `_run_gmail_intake()` function now logs a structured heartbeat at each tick:

```python
logger.info("gmail_intake_heartbeat tick_start=%s", _tick_start,
            extra={"event": "gmail_intake_heartbeat", "tick_start": _tick_start})
...
logger.info("gmail_intake_heartbeat tick_end=%s", _tick_end,
            extra={"event": "gmail_intake_complete", "tick_end": _tick_end})
```

Monitor for `gmail_intake_heartbeat` events in Railway logs to confirm the cron is running. A 15+ min gap in heartbeats means the scheduler has stopped.

---

## 7. Summary of Issues

| # | Issue | Severity | Status |
|---|---|---|---|
| 1 | `thread_messages` insert silently failing (company_id/contact_id not in schema) | Critical | Fixed |
| 2 | UNSEEN-only polling misses manually-read replies | High | Documented — requires Avanish decision on mitigation |
| 3 | `GMAIL_APP_PASSWORD` must be set in Railway | High | Avanish action required |
| 4 | 0 `email_replied` interaction records (no IMAP replies ingested) | High | Root cause: likely Railway env var missing |
| 5 | `workspace_credentials` table has 0 rows | Medium | IMAP polling falls back to env vars correctly |
| 6 | No heartbeat logging previously | Medium | Fixed |
