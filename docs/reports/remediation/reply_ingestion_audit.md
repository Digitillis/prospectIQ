# Phase 2 — Reply Ingestion Audit

**Date:** 2026-05-13  
**Confidence Level:** HIGH for credential diagnosis; MEDIUM for runtime state  
**Operational Impact:** Critical — zero reply tracking means no engagement funnel visibility  
**Risk Level:** Medium (requires credential provisioning action by Avanish)

---

## Finding Summary

**Zero `email_replied` interactions** exist in production. Zero inbound `thread_messages`. Zero `campaign_threads` with status=replied. Reply tracking has never produced a single event.

The gmail_intake cron is **scheduled** (every 15 minutes, line 2018 in `main.py`) and the code logic is correct. The failure point is credential resolution for the sender_pool accounts.

---

## Architecture Walkthrough

### The scheduled job

```python
scheduler.add_job(_run_gmail_intake, "interval", minutes=15, id="gmail_intake")
```

This calls `_run_gmail_intake()` → `for_each_workspace(_gmail_intake_workspace, "gmail_intake")`.

`for_each_workspace` fetches workspaces with `subscription_status IN ('active', 'trialing')`. There is exactly **1 active workspace**: `id=00000000-0000-0000-0000-000000000001` (Digitillis).

### Credential resolution for `_gmail_intake_workspace`

The function builds `accounts_to_poll` as follows:

1. **Primary account:** `creds.get("gmail", "user")` and `creds.get("gmail", "app_password")`
   - `CredentialStore` first looks in `workspace_credentials` table → **0 rows stored there**
   - Falls back to env var `GMAIL_USER` → present in `.env` as `avi@digitillis.io`
   - Falls back to env var `GMAIL_APP_PASSWORD` → present in `.env` as `uoto laih khpf cvib`
   - **Result:** Primary credentials ARE available via env var fallback

2. **Sender pool accounts (9 accounts):**
   ```
   avi@digitillis.io, avanish@trydigitillis.com, avi@trydigitillis.com,
   avanish@meetdigitillis.com, avi@meetdigitillis.com, avanish@usedigitillis.com,
   avi@usedigitillis.com, avanish@getdigitillis.com, avi@getdigitillis.com
   ```
   - Each is looked up via `creds.get(f"gmail_{safe_key}", "app_password")`
   - Example for `avanish@trydigitillis.com`: key = `"gmail_avanish_at_trydigitillis_com"` → no env var, no DB entry
   - **Result:** Only `avi@digitillis.io` (primary) has credentials. The other 8 are silently skipped.

### Conclusion: Primary credential path should work

The primary account (`avi@digitillis.io`) is resolvable. The intake should be polling that inbox. There are two possible reasons for zero reply events:

---

## Root Cause Candidates (Ranked by Probability)

### Candidate A: No replies have actually arrived in the inbox (HIGH probability)

The 1,090 step-1 sends have a 0% reply rate at the `email_replied` interaction level. If replies truly have not come in, the intake is working correctly (no new UNSEEN "Re:" emails to process). The intake fetches UNSEEN emails with `Re:` subjects — if the inbox is empty or all emails are already marked READ, it processes nothing.

**Evidence for:** The open rate (8.7%) and click rate (14.4%) are non-trivial, but reply rates for cold B2B outbound are typically 0.5-3%. 1,090 sends at 1% = ~11 expected replies. These may have come in but been marked READ by the sender before the intake ran.

**Evidence against:** The intake only processes UNSEEN emails. If Avanish reads replies manually before the cron fires, those emails are marked READ and the cron skips them. This is the most likely explanation for zero events.

### Candidate B: Railway environment does not have GMAIL_APP_PASSWORD set (MEDIUM probability)

The `.env` file contains `GMAIL_APP_PASSWORD` and `GMAIL_USER`, but these are local credentials. If Railway's production environment variables do not include `GMAIL_APP_PASSWORD`, then on Railway the `CredentialStore` DB lookup fails (0 rows) and the env fallback returns `None`, causing `accounts_to_poll = []` → the function returns immediately with no processing.

**Evidence for:** The `.env` confirms the credentials exist locally. Railway env vars are configured separately in the Railway dashboard and are not automatically synced from `.env`. The MEMORY.md notes that Railway env setup has been an ongoing issue.

**Action required by Avanish:** Verify that `GMAIL_USER` and `GMAIL_APP_PASSWORD` are set in Railway → ProspectIQ → Variables.

### Candidate C: Gmail App Password expired or IMAP disabled (LOW-MEDIUM probability)

Gmail App Passwords can be revoked (e.g., after a Google account security event or 2FA change). IMAP can also be disabled by Google for the account. If either is true, the IMAP connection fails with an authentication error, which is caught by the `except Exception as e:` block and logged as an error but does not crash the app.

**Evidence for:** The `uoto laih khpf cvib` App Password format is correct (16-char groups). But it may have been regenerated or revoked since configuration.

**Action required by Avanish:** Log into `myaccount.google.com/apppasswords` and confirm the app password is still valid for `avi@digitillis.io`.

### Candidate D: Subject matching fails (LOW probability)

The intake matches replies by stripping `"Re: "` from the subject and doing a case-insensitive `ilike` lookup in `outreach_drafts`. If subjects contain special characters or were truncated, the match could fail. Failed matches are silently skipped (`gmail.mark_as_read(reply["uid"])` is called regardless).

**Evidence against:** The fallback path also matches by `contact.email = from_email`, which would work if the reply's From header matches the contact's stored email. Two independent matching paths both failing is less likely.

---

## Interaction Type Evidence

Live DB query result:
```
email_sent:    1,097
email_clicked:   158
email_bounced:    45
email_opened:     95
email_replied:     0  ← absolute zero
```

The presence of `email_clicked` and `email_bounced` events confirms that the interaction insertion pipeline is functional. Events are being written for other types. The zero for `email_replied` is specific to the reply intake path.

---

## Recommended Fix (In Priority Order)

1. **Verify Railway env vars** — Confirm `GMAIL_USER=avi@digitillis.io` and `GMAIL_APP_PASSWORD=uoto laih khpf cvib` are set in Railway production environment. This is the most likely cause if the intake is not running at all on production.

2. **Verify IMAP is enabled** — Log into Gmail as `avi@digitillis.io` → Settings → See all settings → Forwarding and POP/IMAP → confirm IMAP is enabled.

3. **Test App Password** — Use `backend/scripts/test_gmail_imap.py` to attempt IMAP connection manually:
   ```bash
   railway run python3 backend/scripts/test_gmail_imap.py
   ```

4. **Check inbox for existing replies** — If replies have come in and been manually read, they will be SEEN (not UNSEEN) and the cron will skip them. Consider: if any replies are in the inbox marked READ, manually mark them UNREAD to test the intake path.

5. **Add logging to intake** — Currently the intake only logs at INFO level on success. Add a log line at the start of each IMAP poll to confirm it is running: `"gmail_intake: polling {gmail_user}..."`. This makes it visible in Railway logs.

---

## Data Impact

- Zero reply events means `SEQUENCE_COOLDOWN_DAYS=90` will activate for all contacts that complete the sequence with no reply recorded. This is technically correct behavior but incorrect in practice if replies are happening and not being logged.
- The sequence cooldown check in `suppression.py` (`is_suppressed` step 5) looks for `email_replied` interactions. If none exist, no contacts will exit cooldown early via reply, even if they replied.
- A/B tracking (in `ReplyAgent`) never fires — reply variants have zero data.

---

## Risk Assessment

| Risk                          | Level  |
|-------------------------------|--------|
| Operational impact of current state | HIGH (engagement loop broken) |
| Risk of proposed fix (env var) | LOW (no code change required) |
| Risk of fix breaking something | VERY LOW (read-only IMAP poll) |
| Rollback | N/A (env var can be cleared; no code change) |
