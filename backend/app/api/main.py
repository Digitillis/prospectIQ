"""FastAPI application for ProspectIQ API.

Serves the Next.js CRM dashboard with endpoints for
companies, approvals, pipeline agents, analytics, and webhooks.
"""

import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from time import time

from fastapi import FastAPI

# Configure logging to DEBUG level for workspace isolation diagnostics
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ---------------------------------------------------------------------------
# Sentry — initialize early so all errors (including startup) are captured
# ---------------------------------------------------------------------------
try:
    from backend.app.core.config import get_settings as _get_settings
    _s = _get_settings()
    if _s.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        sentry_sdk.init(
            dsn=_s.sentry_dsn,
            environment=_s.sentry_environment,
            traces_sample_rate=_s.sentry_traces_sample_rate,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            # Don't capture 4xx errors as Sentry issues — those are user errors
            ignore_errors=[],
        )
        logging.getLogger(__name__).info(
            "Sentry initialized (env=%s, traces=%.0f%%)",
            _s.sentry_environment,
            _s.sentry_traces_sample_rate * 100,
        )
except Exception as _sentry_err:
    logging.getLogger(__name__).warning("Sentry init skipped: %s", _sentry_err)
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks, settings, actions, action_queue, contacts, today, content, events, sequences, monitoring, workspaces, invite, billing, signup, threads, intelligence, outreach_agent, hitl, personalization, auth as auth_routes, voice_of_prospect, multi_thread, ghostwriting, crm, meetings, deals, targeting, intent_signals, memory, llm_qualify, composer, onboarding
from backend.app.api.routes import quality_dashboard
from backend.app.webhooks import instantly as instantly_webhooks
from backend.app.core.workspace_middleware import WorkspaceMiddleware

logger = logging.getLogger(__name__)

# Module-level scheduler reference — set during lifespan startup.
# Used by _schedule_pipeline_advance() to queue one-shot reactive checks
# without requiring callers to hold a reference to the scheduler.
_scheduler = None


def _schedule_pipeline_advance(delay_seconds: int = 60) -> None:
    """Schedule a one-shot pipeline advance run, debounced by replace_existing.

    Calling this multiple times within the delay window collapses to a single
    run — the last call wins. This prevents stacking when multiple send batches
    or reply events fire in quick succession.
    """
    if _scheduler is None:
        return
    try:
        from datetime import datetime, timezone, timedelta
        _scheduler.add_job(
            _run_pipeline_advance,
            "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
            id="pipeline_advance_reactive",
            replace_existing=True,
        )
    except Exception as exc:
        logger.warning("_schedule_pipeline_advance failed: %s", exc)


def _pipeline_advance_workspace(ws: dict) -> None:
    from backend.app.core.pipeline_orchestrator import PipelineOrchestrator
    result = PipelineOrchestrator(workspace_id=ws["id"]).advance()
    status = result.get("pipeline_status", {})
    actions = result.get("actions", [])
    logger.info(
        "Pipeline advance [%s]: pending=%d in_flight=%d days_left=%.1f actions=%s",
        ws.get("name", ws["id"]),
        status.get("outreach_pending", 0),
        status.get("in_flight", 0),
        status.get("days_remaining", 0),
        actions or "none",
    )


def _run_pipeline_advance() -> None:
    """Heartbeat + reactive trigger: advance the pipeline for all active workspaces."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_pipeline_advance_workspace, "pipeline_advance")
    except Exception as exc:
        logger.error("Pipeline advance failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Rate limiting middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter. 100 requests per minute per IP."""

    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request, call_next):
        # Skip health checks
        if request.url.path in ("/health", "/healthz"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time()
        window = now - 60

        # Prune old entries
        self._hits[ip] = [t for t in self._hits[ip] if t > window]

        if len(self._hits[ip]) >= self.rpm:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in 60 seconds."},
            )

        self._hits[ip].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Background scheduler for engagement sequence processing
# ---------------------------------------------------------------------------

def _run_health_snapshot() -> None:
    """Every-15-min job: capture full system health snapshot."""
    try:
        from backend.app.agents.monitoring import HealthSnapshotAgent
        HealthSnapshotAgent().capture()
    except Exception as e:
        logger.error(f"Scheduled health_snapshot failed: {e}")


def _send_approved_workspace(ws: dict) -> None:
    from backend.app.core.workspace_scheduler import workspace_daily_sends_ok
    if not workspace_daily_sends_ok(ws, "send_approved"):
        return
    from backend.app.core.config import get_settings
    if not get_settings().send_enabled:
        return
    from backend.app.agents.engagement import EngagementAgent
    agent = EngagementAgent(workspace_id=ws["id"])
    result = agent.run(action="send_approved")
    logger.info("Send [%s]: processed=%d errors=%d", ws["name"], result.processed, result.errors)
    # Reactive: consumed pipeline capacity — check depth immediately
    if result.processed > 0:
        _schedule_pipeline_advance(delay_seconds=60)
        # Flywheel: schedule a 24-hour-out one-shot intent refresh for the
        # companies we just emailed. Prospects who just received outreach
        # often post relevant job openings within the next day.
        try:
            _schedule_post_send_intent_refresh(ws["id"], db, lookback_minutes=15)
        except Exception as exc:
            logger.debug("post-send intent refresh scheduling failed: %s", exc)


def _schedule_post_send_intent_refresh(
    workspace_id: str, db, lookback_minutes: int = 15,
) -> None:
    """Schedule a one-shot intent refresh in 24h for companies just emailed.

    Reads outreach_drafts sent in the last `lookback_minutes` for this
    workspace, dedupes the company set, and queues a one-shot job 24h out.
    """
    if _scheduler is None:
        return
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).isoformat()
    try:
        rows = (
            db.client.table("outreach_drafts")
            .select("company_id")
            .eq("workspace_id", workspace_id)
            .gte("sent_at", cutoff)
            .execute()
            .data or []
        )
    except Exception:
        return
    company_ids = list({r["company_id"] for r in rows if r.get("company_id")})
    if not company_ids:
        return
    run_at = datetime.now(timezone.utc) + timedelta(hours=24)
    try:
        _scheduler.add_job(
            _run_intent_refresh_for_companies,
            "date",
            run_date=run_at,
            args=[company_ids, workspace_id],
            id=f"intent_post_send_{workspace_id}_{int(run_at.timestamp())}",
            replace_existing=True,
        )
        logger.info(
            "Scheduled 24h post-send intent refresh for %d companies (ws=%s)",
            len(company_ids), workspace_id,
        )
    except Exception as exc:
        logger.debug("post-send intent refresh add_job failed: %s", exc)


def _run_send_approved() -> None:
    """Cron job: send approved drafts via Resend for all active workspaces.

    Scheduled Mon-Fri at :00 and :30 past each hour from 8 AM–11 AM Chicago time.
    """
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_send_approved_workspace, "send_approved")
    except Exception as e:
        logger.error(f"Scheduled send_approved failed: {e}")


def _run_process_due_sequences() -> None:
    """Hourly job: process engagement sequences with due follow-up actions."""
    try:
        from backend.app.agents.engagement import EngagementAgent
        agent = EngagementAgent()
        agent.run(action="process_due")
    except Exception as e:
        logger.error(f"Scheduled process_due failed: {e}")


def _run_poll_instantly() -> None:
    """Every-6-hour job: poll Instantly.ai for new email events (webhook fallback)."""
    try:
        from backend.app.core.config import get_settings
        if not get_settings().instantly_api_key:
            return
        from backend.app.agents.engagement import EngagementAgent
        agent = EngagementAgent()
        agent.run(action="poll_events")
    except Exception as e:
        logger.error(f"Scheduled poll_instantly failed: {e}")


def _run_process_hitl_snoozed() -> None:
    """Every-15-min job: move snoozed HITL items past their snooze_until back to pending."""
    try:
        from backend.app.core.database import Database
        db = Database()
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        result = (
            db.client.table("hitl_queue")
            .update({"status": "pending", "snoozed_until": None})
            .eq("status", "snoozed")
            .lte("snoozed_until", now)
            .execute()
        )
        count = len(result.data) if result.data else 0
        if count:
            logger.info(f"HITL: re-queued {count} snoozed item(s)")
    except Exception as e:
        logger.error(f"Scheduled process_hitl_snoozed failed: {e}")


def _run_personalization_refresh() -> None:
    """Every-24-hour job: refresh personalization for top 100 qualified companies."""
    try:
        from backend.app.core.personalization_batch import PersonalizationBatch
        runner = PersonalizationBatch()
        result = runner.run_batch(filters={"min_pqs": 50}, max_companies=100)
        logger.info(
            f"Personalization refresh: processed={result.processed}, "
            f"errors={result.errors}, cost=${result.total_cost_usd:.4f}"
        )
    except Exception as e:
        logger.error(f"Scheduled personalization_refresh failed: {e}")



def _run_jit_pregenerate() -> None:
    """Every-24-hour job: pre-generate follow-up drafts due within the next 3 days."""
    try:
        from backend.app.agents.engagement import EngagementAgent
        agent = EngagementAgent()
        result = agent.run(action="jit_pregenerate")
        logger.info(f"JIT pre-generate: {result}")
    except Exception as e:
        logger.error(f"Scheduled jit_pregenerate failed: {e}")


def _gmail_intake_workspace(ws: dict) -> None:
    """Run Gmail IMAP intake for a single workspace.

    Loops over all active accounts in sender_pool so replies landing in any
    sending mailbox are captured, not just the primary account.
    """
    from backend.app.core.credential_store import CredentialStore
    from backend.app.core.database import Database
    from backend.app.integrations.gmail_imap import GmailImapClient, _classify_intent
    from datetime import datetime, timezone, timedelta

    ws_id = ws["id"]
    ws_settings = ws.get("settings") or {}
    creds = CredentialStore(ws_id)

    # Build list of (email, password) pairs to poll.
    # Primary account lives under the "gmail" credential key.
    # Additional sender_pool accounts are stored under "gmail_{safe_email}" key.
    accounts_to_poll: list[tuple[str, str]] = []

    primary_user = creds.get("gmail", "user")
    primary_password = creds.get("gmail", "app_password")
    if primary_user and primary_password:
        accounts_to_poll.append((primary_user, primary_password))

    sender_pool = ws_settings.get("sender_pool") or []
    for acct in sender_pool:
        if not acct.get("active", True):
            continue
        acct_email = acct.get("email", "")
        if not acct_email or acct_email == primary_user:
            continue
        safe_key = acct_email.replace("@", "_at_").replace(".", "_")
        acct_password = creds.get(f"gmail_{safe_key}", "app_password")
        if acct_password:
            accounts_to_poll.append((acct_email, acct_password))

    if not accounts_to_poll:
        return

    db = Database(workspace_id=ws_id)
    processed = 0
    skipped = 0

    for gmail_user, gmail_password in accounts_to_poll:
        try:
            with GmailImapClient(gmail_user, gmail_password) as gmail:
                replies = gmail.fetch_unseen_replies()
                if not replies:
                    continue

                for reply in replies:
                    from_email = reply["from_email"]
                    subject = reply["subject"]
                    body = reply["body"]
                    received_at = reply["received_at"]

                    clean_subject = subject.strip()
                    if clean_subject.lower().startswith("re:"):
                        clean_subject = clean_subject[3:].strip()

                    match = (
                        db.client.table("outreach_drafts")
                        .select("id, company_id, contact_id, sequence_name, sequence_step, workspace_id")
                        .ilike("subject", clean_subject)
                        .not_.is_("sent_at", "null")
                        .eq("workspace_id", ws_id)
                        .limit(1)
                        .execute()
                    ).data

                    if not match:
                        contact_row = (
                            db.client.table("contacts")
                            .select("id, company_id")
                            .eq("email", from_email)
                            .eq("workspace_id", ws_id)
                            .limit(1)
                            .execute()
                        ).data
                        if contact_row:
                            match = (
                                db.client.table("outreach_drafts")
                                .select("id, company_id, contact_id, sequence_name, sequence_step, workspace_id")
                                .eq("contact_id", contact_row[0]["id"])
                                .not_.is_("sent_at", "null")
                                .eq("workspace_id", ws_id)
                                .order("sent_at", desc=True)
                                .limit(1)
                                .execute()
                            ).data

                    if not match:
                        gmail.mark_as_read(reply["uid"])
                        skipped += 1
                        continue

                    draft = match[0]
                    company_id = draft["company_id"]
                    contact_id = draft["contact_id"]

                    existing = (
                        db.client.table("thread_messages")
                        .select("id")
                        .eq("contact_id", contact_id)
                        .eq("direction", "inbound")
                        .gte("created_at", (
                            datetime.fromisoformat(received_at.replace("Z", "+00:00"))
                            - timedelta(minutes=5)
                        ).isoformat())
                        .limit(1)
                        .execute()
                    ).data
                    if existing:
                        gmail.mark_as_read(reply["uid"])
                        skipped += 1
                        continue

                    intent = _classify_intent(body, subject)

                    thread_id = None
                    try:
                        existing_thread = (
                            db.client.table("campaign_threads")
                            .select("id")
                            .eq("contact_id", contact_id)
                            .limit(1)
                            .execute()
                        ).data
                        if existing_thread:
                            thread_id = existing_thread[0]["id"]
                            db.client.table("campaign_threads").update({
                                "status": "replied",
                                "last_replied_at": received_at,
                            }).eq("id", thread_id).execute()
                        else:
                            new_thread = db.client.table("campaign_threads").insert({
                                "company_id": company_id,
                                "contact_id": contact_id,
                                "status": "replied",
                                "last_replied_at": received_at,
                                "workspace_id": ws_id,
                                "sequence_name": draft.get("sequence_name", "email_value_first"),
                                "current_step": draft.get("sequence_step", 1),
                            }).execute()
                            if new_thread.data:
                                thread_id = new_thread.data[0]["id"]
                    except Exception as e:
                        logger.warning(f"Gmail intake [{ws['name']}]: campaign_threads upsert failed: {e}")

                    try:
                        db.client.table("thread_messages").insert({
                            "thread_id": thread_id,
                            "company_id": company_id,
                            "contact_id": contact_id,
                            "direction": "inbound",
                            "body": body[:4000],
                            "subject": subject,
                            "classification": intent,
                            "source": "gmail_imap",
                            "workspace_id": ws_id,
                        }).execute()
                    except Exception as e:
                        logger.warning(f"Gmail intake [{ws['name']}]: thread_message insert failed: {e}")

                    try:
                        db.client.table("interactions").insert({
                            "company_id": company_id,
                            "contact_id": contact_id,
                            "type": "email_replied",
                            "channel": "email",
                            "subject": subject,
                            "body": body[:4000],
                            "source": "gmail_imap",
                            "metadata": {"intent": intent, "from": from_email},
                            "workspace_id": ws_id,
                        }).execute()
                    except Exception as e:
                        logger.warning(f"Gmail intake [{ws['name']}]: interaction insert failed: {e}")

                    try:
                        if intent == "not_interested":
                            db.client.table("engagement_sequences").update({"status": "paused"}).eq(
                                "contact_id", contact_id).eq("status", "active").execute()
                        elif intent == "interested":
                            expedite_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                            db.client.table("engagement_sequences").update({"next_action_at": expedite_at}).eq(
                                "contact_id", contact_id).eq("status", "active").execute()
                        elif intent == "ooo":
                            delay_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                            db.client.table("engagement_sequences").update({"next_action_at": delay_at}).eq(
                                "contact_id", contact_id).eq("status", "active").execute()
                    except Exception as e:
                        logger.warning(f"Gmail intake [{ws['name']}]: sequence update failed: {e}")

                    # For reply-worthy intents, draft a response and queue for approval.
                    if intent in ("interested", "question", "objection", "referral"):
                        try:
                            draft_row = (
                                db.client.table("outreach_drafts")
                                .select("id")
                                .eq("contact_id", contact_id)
                                .not_.is_("sent_at", "null")
                                .eq("workspace_id", ws_id)
                                .order("sent_at", desc=True)
                                .limit(1)
                                .execute()
                            ).data
                            original_draft_id = draft_row[0]["id"] if draft_row else None
                            if original_draft_id:
                                from backend.app.agents.reply import ReplyAgent
                                reply_agent = ReplyAgent(workspace_id=ws_id)
                                reply_result = reply_agent.run(reply_data={
                                    "company_id": company_id,
                                    "contact_id": contact_id,
                                    "subject": subject,
                                    "body": body,
                                    "outreach_draft_id": original_draft_id,
                                })
                                if reply_result.success and thread_id:
                                    _push_reply_to_hitl(db, thread_id, ws_id, intent)
                                    logger.info(
                                        "Gmail intake [%s]: reply draft queued for %s (intent=%s)",
                                        ws["name"], from_email, intent,
                                    )
                        except Exception as e:
                            logger.warning(f"Gmail intake [{ws['name']}]: reply draft failed: {e}")

                    gmail.mark_as_read(reply["uid"])
                    processed += 1

        except Exception as e:
            logger.error(f"Gmail intake [{ws['name']}]: account {gmail_user} failed: {e}", exc_info=True)

    if processed or skipped:
        logger.info("Gmail intake [%s]: %d processed, %d skipped", ws["name"], processed, skipped)

    if processed > 0:
        _schedule_pipeline_advance(delay_seconds=30)


def _push_reply_to_hitl(db, thread_id: str, workspace_id: str, intent: str) -> None:
    """Push a reply needing approval into the HITL queue."""
    priority_map = {"interested": 1, "referral": 2, "objection": 3, "question": 3}
    try:
        db.client.table("hitl_queue").insert({
            "thread_id": thread_id,
            "workspace_id": workspace_id,
            "classification": intent,
            "classification_confidence": 0.85,
            "priority": priority_map.get(intent, 3),
            "status": "pending",
        }).execute()
    except Exception as e:
        logger.warning("_push_reply_to_hitl failed: %s", e)


def _run_gmail_intake() -> None:
    """Every-15-min job: poll Gmail IMAP for replies across all active workspaces."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_gmail_intake_workspace, "gmail_intake")
    except Exception as e:
        logger.error(f"Scheduled gmail_intake failed: {e}", exc_info=True)


def _run_gmail_intake_LEGACY() -> None:
    """LEGACY — kept for reference only. Replaced by workspace-aware version above."""
    try:
        from backend.app.core.config import get_settings
        from backend.app.core.database import Database
        from backend.app.integrations.gmail_imap import GmailImapClient, _classify_intent
        from datetime import datetime, timezone, timedelta

        settings = get_settings()
        if not settings.gmail_user or not settings.gmail_app_password:
            return  # Not configured — skip silently

        db = Database()
        processed = 0
        skipped = 0

        with GmailImapClient(settings.gmail_user, settings.gmail_app_password) as gmail:
            replies = gmail.fetch_unseen_replies()
            if not replies:
                return

            for reply in replies:
                from_email = reply["from_email"]
                subject = reply["subject"]
                body = reply["body"]
                received_at = reply["received_at"]

                # Match to outreach_draft by stripping "Re: " prefix and looking up subject
                clean_subject = subject.strip()
                if clean_subject.lower().startswith("re:"):
                    clean_subject = clean_subject[3:].strip()

                # Try to find matching draft by subject + sender email
                match = (
                    db.client.table("outreach_drafts")
                    .select("id, company_id, contact_id, sequence_name, sequence_step, workspace_id")
                    .ilike("subject", clean_subject)
                    .not_.is_("sent_at", "null")
                    .limit(1)
                    .execute()
                ).data

                # Fallback: match by contact email
                if not match:
                    contact_row = (
                        db.client.table("contacts")
                        .select("id, company_id")
                        .eq("email", from_email)
                        .limit(1)
                        .execute()
                    ).data
                    if contact_row:
                        match = (
                            db.client.table("outreach_drafts")
                            .select("id, company_id, contact_id, sequence_name, sequence_step, workspace_id")
                            .eq("contact_id", contact_row[0]["id"])
                            .not_.is_("sent_at", "null")
                            .order("sent_at", desc=True)
                            .limit(1)
                            .execute()
                        ).data

                if not match:
                    logger.debug(f"Gmail intake: no draft match for reply from {from_email} re: {subject!r}")
                    gmail.mark_as_read(reply["uid"])
                    skipped += 1
                    continue

                draft = match[0]
                company_id = draft["company_id"]
                contact_id = draft["contact_id"]
                workspace_id = draft.get("workspace_id", "00000000-0000-0000-0000-000000000001")

                # Dedup: skip if already logged this message (same from_email + received_at)
                existing = (
                    db.client.table("thread_messages")
                    .select("id")
                    .eq("contact_id", contact_id)
                    .eq("direction", "inbound")
                    .gte("created_at", (
                        datetime.fromisoformat(received_at.replace("Z", "+00:00")) - timedelta(minutes=5)
                    ).isoformat())
                    .limit(1)
                    .execute()
                ).data
                if existing:
                    gmail.mark_as_read(reply["uid"])
                    skipped += 1
                    continue

                intent = _classify_intent(body, subject)

                # Ensure a campaign_thread row exists — upsert so replies always
                # have a thread to attach to, even for contacts that started before
                # the threads table was introduced.
                thread_id = None
                try:
                    existing_thread = (
                        db.client.table("campaign_threads")
                        .select("id")
                        .eq("contact_id", contact_id)
                        .limit(1)
                        .execute()
                    ).data
                    if existing_thread:
                        thread_id = existing_thread[0]["id"]
                        db.client.table("campaign_threads").update({
                            "status": "replied",
                            "last_replied_at": received_at,
                        }).eq("id", thread_id).execute()
                    else:
                        new_thread = db.client.table("campaign_threads").insert({
                            "company_id": company_id,
                            "contact_id": contact_id,
                            "status": "replied",
                            "last_replied_at": received_at,
                            "workspace_id": workspace_id,
                            "sequence_name": draft.get("sequence_name", "email_value_first"),
                            "current_step": draft.get("sequence_step", 1),
                        }).execute()
                        if new_thread.data:
                            thread_id = new_thread.data[0]["id"]
                except Exception as e:
                    logger.warning(f"Gmail intake: campaign_threads upsert failed: {e}")

                # Insert thread_message — includes thread_id so it surfaces in the triage UI
                try:
                    db.client.table("thread_messages").insert({
                        "thread_id": thread_id,
                        "company_id": company_id,
                        "contact_id": contact_id,
                        "direction": "inbound",
                        "body": body[:4000],
                        "subject": subject,
                        "classification": intent,
                        "source": "gmail_imap",
                        "workspace_id": workspace_id,
                    }).execute()
                except Exception as e:
                    logger.warning(f"Gmail intake: thread_message insert failed: {e}")

                # Insert interaction
                try:
                    db.client.table("interactions").insert({
                        "company_id": company_id,
                        "contact_id": contact_id,
                        "type": "email_replied",
                        "channel": "email",
                        "subject": subject,
                        "body": body[:4000],
                        "source": "gmail_imap",
                        "metadata": {"intent": intent, "from": from_email},
                        "workspace_id": workspace_id,
                    }).execute()
                except Exception as e:
                    logger.warning(f"Gmail intake: interaction insert failed: {e}")

                # Update engagement_sequence based on intent
                try:
                    if intent == "not_interested":
                        db.client.table("engagement_sequences").update({
                            "status": "paused",
                        }).eq("contact_id", contact_id).eq("status", "active").execute()
                    elif intent == "interested":
                        from datetime import timedelta
                        expedite_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                        db.client.table("engagement_sequences").update({
                            "next_action_at": expedite_at,
                        }).eq("contact_id", contact_id).eq("status", "active").execute()
                    elif intent == "ooo":
                        # Delay next step by 7 days
                        delay_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                        db.client.table("engagement_sequences").update({
                            "next_action_at": delay_at,
                        }).eq("contact_id", contact_id).eq("status", "active").execute()
                except Exception as e:
                    logger.warning(f"Gmail intake: sequence update failed: {e}")

                gmail.mark_as_read(reply["uid"])
                processed += 1
                logger.info(f"Gmail intake: processed reply from {from_email} (intent={intent})")

        if processed or skipped:
            logger.info(f"Gmail intake: {processed} processed, {skipped} skipped/unmatched")

    except Exception as e:
        logger.error(f"Scheduled gmail_intake_legacy failed: {e}", exc_info=True)


MONTHLY_API_BUDGET_USD = 200.0  # Hard stop for automated research/enrichment
BUDGET_WARN_THRESHOLD_USD = 150.0  # Alert email at this level (~75% of cap)


def _get_monthly_api_spend() -> float:
    """Return total estimated API spend in the current calendar month (USD)."""
    try:
        from backend.app.core.database import get_supabase_client
        from datetime import datetime, timezone
        client = get_supabase_client()
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        result = (
            client.table("api_costs")
            .select("estimated_cost_usd")
            .gte("created_at", month_start)
            .execute()
        )
        return sum(float(r.get("estimated_cost_usd") or 0) for r in (result.data or []))
    except Exception as e:
        logger.warning(f"Could not fetch monthly API spend: {e}")
        return 0.0


def _check_budget(job_name: str) -> bool:
    """Return True if budget allows running. Emails Avi at warning threshold; hard-stops at cap."""
    spend = _get_monthly_api_spend()

    if spend >= MONTHLY_API_BUDGET_USD:
        logger.warning(
            f"BUDGET GATE: {job_name} skipped — monthly API spend ${spend:.2f} "
            f">= ${MONTHLY_API_BUDGET_USD:.2f} limit."
        )
        return False

    # One-per-day warning email when spend crosses the alert threshold
    if spend >= BUDGET_WARN_THRESHOLD_USD:
        try:
            from backend.app.core.database import get_supabase_client
            from datetime import date
            client = get_supabase_client()
            today = str(date.today())
            already_warned = (
                client.table("api_costs")
                .select("id", count="exact")
                .eq("provider", "__budget_warn__")
                .gte("created_at", f"{today}T00:00:00")
                .execute()
            ).count or 0
            if not already_warned:
                import asyncio
                from backend.app.core.notifications import send_email
                asyncio.run(send_email(
                    to="avanish.mehrotra@gmail.com",
                    subject=f"[ProspectIQ] Budget alert: ${spend:.0f} of ${MONTHLY_API_BUDGET_USD:.0f} used this month — hold or increase?",
                    html_body=(
                        f"<html><body style='font-family:-apple-system,sans-serif;max-width:520px;margin:0 auto;color:#111;padding:20px'>"
                        f"<h2 style='color:#b45309;margin-bottom:4px'>API Budget Alert</h2>"
                        f"<p style='color:#6b7280;font-size:13px;margin-top:0'>Monthly spend has crossed the 75% warning threshold.</p>"
                        f"<table style='width:100%;border-collapse:collapse;font-size:14px;margin:14px 0'>"
                        f"<tr style='background:#fef3c7'><td style='padding:8px 12px;font-weight:600'>Spent this month</td><td style='text-align:right;padding:8px 12px'><strong>${spend:.2f}</strong></td></tr>"
                        f"<tr><td style='padding:8px 12px;border-top:1px solid #e5e7eb'>Monthly cap</td><td style='text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb'>${MONTHLY_API_BUDGET_USD:.2f}</td></tr>"
                        f"<tr><td style='padding:8px 12px;border-top:1px solid #e5e7eb'>Remaining</td><td style='text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb;color:#16a34a'><strong>${MONTHLY_API_BUDGET_USD - spend:.2f}</strong></td></tr>"
                        f"<tr><td style='padding:8px 12px;border-top:1px solid #e5e7eb'>Usage</td><td style='text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb'>{spend / MONTHLY_API_BUDGET_USD * 100:.0f}%</td></tr>"
                        f"</table>"
                        f"<div style='background:#fef9c3;border:1px solid #fde047;padding:12px 16px;border-radius:6px;font-size:14px;margin:16px 0'>"
                        f"<strong>Action required:</strong> All automated jobs (research, enrichment, outreach drafting) will hard-stop at ${MONTHLY_API_BUDGET_USD:.0f}. "
                        f"Reply to this email or update <code>workspace.settings.monthly_api_budget_usd</code> to increase the cap. "
                        f"Otherwise jobs will pause automatically when the limit is reached."
                        f"</div>"
                        f"<p style='font-size:13px'>Should we <strong>hold at ${MONTHLY_API_BUDGET_USD:.0f}</strong> and let it stop, or <strong>increase the cap</strong> to keep the pipeline running?</p>"
                        f"<p style='font-size:11px;color:#9ca3af'>This alert fires once per day while spend remains above the threshold.</p>"
                        f"</body></html>"
                    ),
                ))
                client.table("api_costs").insert({
                    "provider": "__budget_warn__",
                    "model": "alert",
                    "estimated_cost_usd": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }).execute()
        except Exception as e:
            logger.debug(f"Budget warning email skipped: {e}")

    remaining = MONTHLY_API_BUDGET_USD - spend
    logger.info(f"Budget check ({job_name}): ${spend:.2f} spent, ${remaining:.2f} remaining this month")
    return True


def _qualify_workspace(ws: dict) -> None:
    from backend.app.agents.qualification import QualificationAgent
    agent = QualificationAgent(workspace_id=ws["id"])
    result = agent.run(limit=300)
    logger.info("Qualification [%s]: processed=%d errors=%d", ws["name"], result.processed, result.errors)


def _run_qualification() -> None:
    """Every-15-min job: score researched companies and promote to qualified/disqualified."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_qualify_workspace, "qualification")
        # Flywheel fast-path: newly qualified companies should generate drafts
        # immediately rather than waiting up to 30 min for the next draft cron.
        try:
            _run_draft_generation()
        except Exception as exc:
            logger.warning("qualification → draft fast-path failed: %s", exc)
    except Exception as e:
        logger.error(f"Scheduled qualification failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Draft generation — closes the gap between enriched contacts and outreach
# ---------------------------------------------------------------------------

def _draft_workspace(ws: dict) -> None:
    """Generate initial outreach drafts for qualified companies with enriched contacts.

    OutreachAgent.run() with no company_ids defaults to status='qualified'.
    After drafting, companies move to 'outreach_pending' so they aren't picked
    up again on the next tick.
    """
    from backend.app.core.workspace_scheduler import workspace_budget_ok
    if not workspace_budget_ok(ws, "drafting"):
        return
    from backend.app.agents.outreach import OutreachAgent
    agent = OutreachAgent(workspace_id=ws["id"])
    result = agent.run(limit=50)
    logger.info(
        "Draft generation [%s]: drafted=%d skipped=%d errors=%d",
        ws["name"], result.processed, result.skipped, result.errors,
    )


def _run_draft_generation() -> None:
    """Every-30-min job: generate initial outreach drafts for qualified-but-undrafted companies."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_draft_workspace, "drafting")
    except Exception as e:
        logger.error(f"Draft generation failed: {e}", exc_info=True)


def _research_workspace(ws: dict) -> None:
    from backend.app.core.workspace_scheduler import workspace_budget_ok, research_budget_ok
    if not workspace_budget_ok(ws, "research"):
        return
    if not research_budget_ok(ws):
        return
    from backend.app.agents.research import ResearchAgent
    agent = ResearchAgent(workspace_id=ws["id"])
    result = agent.run(batch_size=150)
    logger.info("Research [%s]: processed=%d errors=%d", ws["name"], result.processed, result.errors)


def _run_research() -> None:
    """Runs every 20 min 24/7 — 150 companies per run, budget-gated.

    Flywheel: immediately fires qualification at the end so research output
    is qualified within ~2 minutes instead of waiting up to 15 min for the
    qualification cron tick.
    """
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_research_workspace, "research")
        # Fast-path: research → qualify, closes 35-min gap to ~2 min
        try:
            _run_qualification()
        except Exception as exc:
            logger.warning("research → qualify fast-path failed: %s", exc)
    except Exception as e:
        logger.error(f"Scheduled research failed: {e}", exc_info=True)


def _auto_approve_workspace(ws: dict) -> None:
    from backend.app.core.database import get_supabase_client
    client = get_supabase_client()
    ws_id = ws["id"]
    ws_settings = ws.get("settings") or {}
    pqs_threshold = int(ws_settings.get("auto_approve_pqs_threshold", 70))

    rows = (
        client.table("outreach_drafts")
        .select("id, company_id, companies(pqs_total)")
        .eq("approval_status", "pending")
        .is_("sent_at", "null")
        .eq("workspace_id", ws_id)
        .limit(200)
        .execute()
        .data or []
    )

    approved = 0
    for r in rows:
        pqs = (r.get("companies") or {}).get("pqs_total") or 0
        if pqs >= pqs_threshold:
            client.table("outreach_drafts").update({"approval_status": "approved"}).eq("id", r["id"]).execute()
            approved += 1

    if approved:
        logger.info("Auto-approve [%s]: approved %d drafts (PQS >= %d)", ws["name"], approved, pqs_threshold)


def _run_auto_approve() -> None:
    """Auto-approve high-PQS pending drafts across all active workspaces."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_auto_approve_workspace, "auto_approve")
    except Exception as e:
        logger.error(f"Auto-approve failed: {e}", exc_info=True)


def _run_limit_ramp() -> None:
    """One-time job 2026-05-07: ramp to 150/day (30/account × 5 senders)."""
    try:
        from backend.app.core.database import get_supabase_client
        from backend.app.core.config import get_settings
        client = get_supabase_client()
        ws = get_settings().default_workspace_id
        client.table("outreach_send_config").update({
            "daily_limit": 150,
            "batch_size": 25,
        }).eq("workspace_id", ws).execute()
        logger.info("Limit ramp: daily_limit bumped to 150 (30/account/day × 5 senders)")
    except Exception as e:
        logger.error(f"Limit ramp failed: {e}", exc_info=True)


def _run_daily_report() -> None:
    """Daily job at 5pm Chicago: generate and email the GTM brief."""
    try:
        from backend.app.agents.daily_report import run_daily_report
        run_daily_report()
    except Exception as e:
        logger.error(f"Daily report failed: {e}", exc_info=True)


def _run_intent_refresh() -> None:
    """Daily job: recompute intent scores from Apollo job postings for all pipeline companies."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace

        def _intent_refresh_workspace(ws: dict) -> None:
            from backend.app.core.workspace_scheduler import workspace_budget_ok
            if not workspace_budget_ok(ws, "intent_refresh"):
                return
            from backend.app.core.database import Database
            from backend.app.core.intent_engine import IntentEngine
            db = Database(workspace_id=ws["id"])
            engine = IntentEngine(db)
            result = engine.recompute_all_intent_scores()
            logger.info("Intent refresh [%s]: %s", ws["name"], result)

        for_each_workspace(_intent_refresh_workspace, "intent_refresh")
    except Exception as e:
        logger.error(f"Intent refresh failed: {e}", exc_info=True)


def _run_intent_refresh_for_companies(company_ids: list[str], workspace_id: str) -> None:
    """One-shot intent refresh for a specific set of companies.

    Called from the post-send fast-path: prospects who just received an email
    might post relevant job openings within the next day, so we re-check
    those companies specifically rather than waiting for the daily cron.
    """
    try:
        from backend.app.core.database import Database
        from backend.app.core.intent_engine import IntentEngine
        db = Database(workspace_id=workspace_id)
        engine = IntentEngine(db)
        refreshed = 0
        for cid in company_ids:
            try:
                company = db.get_company(cid)
                if not company:
                    continue
                engine.compute_company_intent_score(cid, company_tier=company.get("tier") or "")
                refreshed += 1
            except Exception as exc:
                logger.debug("intent rescore for %s failed: %s", cid, exc)
        logger.info("Intent post-send refresh: %d companies rescored", refreshed)
    except Exception as e:
        logger.error("Intent post-send refresh failed: %s", e, exc_info=True)


def _run_pipeline_monitor_email() -> None:
    """Every-6-hour job: email pipeline stats to Avanish."""
    try:
        from backend.app.core.database import get_supabase_client
        from backend.app.core.workspace_scheduler import apollo_credits_ok
        from backend.app.core.notifications import send_email
        from backend.app.integrations.apollo import ApolloClient
        from datetime import datetime, timezone
        import asyncio

        client = get_supabase_client()
        workspace_id = "00000000-0000-0000-0000-000000000001"
        now_str = datetime.now(timezone.utc).strftime("%b %-d, %Y at %-I:%M %p UTC")

        # Pipeline counts
        def count(status):
            r = client.table("companies").select("id", count="exact").eq("workspace_id", workspace_id).eq("status", status).execute()
            return r.count or 0

        def count_contacts(status):
            r = client.table("contacts").select("id", count="exact").eq("workspace_id", workspace_id).eq("enrichment_status", status).execute()
            return r.count or 0

        discovered   = count("discovered")
        researched   = count("researched")
        qualified    = count("qualified")
        disqualified = count("disqualified")
        outreach     = count("outreach_pending")

        contacts_enriched = count_contacts("enriched")
        contacts_pending  = count_contacts("pending")

        # Apollo credits
        credits_remaining = "—"
        try:
            with ApolloClient(workspace_id=workspace_id) as apollo:
                info = apollo.get_credits()
                used = info.get("credits_used", 0)
                limit = info.get("credit_limit", 0)
                credits_remaining = f"{limit - used:,} of {limit:,} remaining"
        except Exception:
            pass

        # Enrichment cap progress
        ws_row = client.table("workspaces").select("settings").eq("id", workspace_id).single().execute()
        ws_settings = (ws_row.data or {}).get("settings") or {}
        cap = ws_settings.get("enrichment_company_cap")
        processed = ws_settings.get("enrichment_companies_processed", 0)
        cap_line = f"{processed} / {cap} companies (cap)" if cap else f"{processed} companies (no cap)"

        html = f"""
<html><body style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#222">
<h2 style="color:#1a56db;margin-bottom:4px">ProspectIQ Pipeline Report</h2>
<p style="color:#666;margin-top:0">{now_str}</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0">
  <tr style="background:#f3f4f6">
    <th style="text-align:left;padding:8px 12px">Stage</th>
    <th style="text-align:right;padding:8px 12px">Count</th>
  </tr>
  <tr><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Discovered (queue)</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb"><strong>{discovered:,}</strong></td></tr>
  <tr style="background:#f9fafb"><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Researched</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb"><strong>{researched:,}</strong></td></tr>
  <tr><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Qualified</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb"><strong>{qualified:,}</strong></td></tr>
  <tr style="background:#f9fafb"><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Outreach Pending</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb"><strong style="color:#1a56db">{outreach:,}</strong></td></tr>
  <tr><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Disqualified</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb;color:#9ca3af">{disqualified:,}</td></tr>
</table>
<table style="width:100%;border-collapse:collapse;margin:16px 0">
  <tr style="background:#f3f4f6">
    <th style="text-align:left;padding:8px 12px">Contacts</th>
    <th style="text-align:right;padding:8px 12px">Count</th>
  </tr>
  <tr><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Enriched (have email)</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb"><strong>{contacts_enriched:,}</strong></td></tr>
  <tr style="background:#f9fafb"><td style="padding:8px 12px;border-top:1px solid #e5e7eb">Pending enrichment</td>
      <td style="text-align:right;padding:8px 12px;border-top:1px solid #e5e7eb">{contacts_pending:,}</td></tr>
</table>
<p style="background:#fef3c7;padding:10px 14px;border-radius:6px;margin:16px 0">
  <strong>Apollo credits:</strong> {credits_remaining}<br>
  <strong>Enrichment cap:</strong> {cap_line}
</p>
</body></html>"""

        asyncio.run(send_email(
            to="avanish.mehrotra@gmail.com",
            subject=f"ProspectIQ pipeline: {outreach:,} outreach-ready | {qualified:,} qualified | {discovered:,} in queue",
            html_body=html,
        ))
        logger.info("Pipeline monitor email sent.")
    except Exception as e:
        logger.error("Pipeline monitor email failed: %s", e, exc_info=True)


def _enrich_workspace(ws: dict) -> None:
    from backend.app.core.workspace_scheduler import workspace_budget_ok
    if not workspace_budget_ok(ws, "enrichment"):
        return

    settings = ws.get("settings") or {}
    cap = settings.get("enrichment_company_cap")  # None = unlimited
    count_so_far = int(settings.get("enrichment_companies_processed", 0))

    if cap is not None and count_so_far >= cap:
        logger.info(
            "Enrichment [%s]: cap of %d companies reached (%d processed) — paused. "
            "Reset enrichment_companies_processed in workspace settings to resume.",
            ws["name"], cap, count_so_far,
        )
        return

    # Compute how many companies this run may process
    if cap is not None:
        run_limit = min(200, cap - count_so_far)
    else:
        run_limit = 200

    from backend.app.agents.enrichment import EnrichmentAgent
    agent = EnrichmentAgent(workspace_id=ws["id"])
    result = agent.run(limit=run_limit)
    logger.info(
        "Enrichment [%s]: processed=%d errors=%d (cap=%s used=%d)",
        ws["name"], result.processed, result.errors,
        cap, count_so_far + result.processed,
    )

    # Persist running total back to workspace settings
    if result.processed > 0:
        try:
            from backend.app.core.database import get_supabase_client
            client = get_supabase_client()
            new_count = count_so_far + result.processed
            updated_settings = dict(settings)
            updated_settings["enrichment_companies_processed"] = new_count
            client.table("workspaces").update({"settings": updated_settings}).eq("id", ws["id"]).execute()

            # Alert when cap is hit
            if cap is not None and new_count >= cap:
                import asyncio
                from backend.app.core.notifications import send_email
                asyncio.run(send_email(
                    to="avanish.mehrotra@gmail.com",
                    subject=f"ProspectIQ: enrichment cap of {cap} companies reached",
                    html_body=(
                        f"<p>The enrichment run has processed <strong>{new_count}</strong> companies "
                        f"(cap: {cap}).</p>"
                        f"<p>Enrichment is now <strong>paused</strong>. Review the results, then "
                        f"reset <code>enrichment_companies_processed</code> to 0 (or raise "
                        f"<code>enrichment_company_cap</code>) in workspace settings to resume.</p>"
                    ),
                ))
        except Exception as exc:
            logger.warning("Could not update enrichment counter: %s", exc)


def _run_enrichment() -> None:
    """Every-45-min job: enrich up to enrichment_company_cap companies via Apollo (1 credit/contact).

    Controlled by workspace settings:
      enrichment_company_cap (int): pause after this many companies (None = unlimited)
      enrichment_companies_processed (int): running total; reset to 0 to start a new batch
    """
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_enrich_workspace, "enrichment")
    except Exception as e:
        logger.error(f"Scheduled enrichment failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Discovery jobs — scheduled weekly to keep the pipeline full
# ---------------------------------------------------------------------------

def _fb_discovery_workspace(ws: dict) -> None:
    from backend.app.core.workspace_scheduler import workspace_budget_ok
    if not workspace_budget_ok(ws, "fb_discovery"):
        return
    from backend.app.agents.discovery import DiscoveryAgent
    agent = DiscoveryAgent(workspace_id=ws["id"])
    result = agent.run(
        campaign_name="fsma204-fb",
        tiers=["fb_dairy", "fb_bev", "fb_seafood", "fb_meat", "fb_produce", "fb_bakery"],
        max_pages=3,
    )
    logger.info(
        "F&B discovery [%s]: processed=%d skipped=%d errors=%d",
        ws["name"], result.processed, result.skipped, result.errors,
    )


def _run_fb_discovery() -> None:
    """Monday 7am: discover new F&B FSMA 204 companies across all sub-segments."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_fb_discovery_workspace, "fb_discovery")
    except Exception as e:
        logger.error("Scheduled F&B discovery failed: %s", e, exc_info=True)


def _mfg_discovery_workspace(ws: dict) -> None:
    from backend.app.core.workspace_scheduler import workspace_budget_ok
    if not workspace_budget_ok(ws, "mfg_discovery"):
        return
    from backend.app.agents.discovery import DiscoveryAgent
    agent = DiscoveryAgent(workspace_id=ws["id"])
    result = agent.run(
        campaign_name="mfg-fsma",
        tiers=["mfg1", "mfg2", "mfg3", "pmfg1"],
        max_pages=3,
    )
    logger.info(
        "Mfg discovery [%s]: processed=%d skipped=%d errors=%d",
        ws["name"], result.processed, result.skipped, result.errors,
    )


def _run_mfg_discovery() -> None:
    """Wednesday 7am: discover new discrete/process manufacturing companies."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_mfg_discovery_workspace, "mfg_discovery")
    except Exception as e:
        logger.error("Scheduled mfg discovery failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Learning job — weekly self-improvement loop
# ---------------------------------------------------------------------------

def _learning_workspace(ws: dict) -> None:
    from backend.app.core.workspace_scheduler import workspace_budget_ok
    if not workspace_budget_ok(ws, "weekly_learning"):
        return
    from backend.app.agents.learning import LearningAgent
    from backend.app.core.database import Database
    from backend.app.core.pipeline_orchestrator import _resolve_auto_apply
    # Graduated rollout: env var explicit override wins; otherwise auto-apply
    # turns on once cumulative outcomes for this workspace cross the threshold
    # (LEARNING_AUTO_APPLY_OUTCOME_THRESHOLD = 50).
    from backend.app.core.database import Database
    _db = Database(workspace_id=ws["id"])
    auto_apply = _resolve_auto_apply(_db, ws["id"])
    agent = LearningAgent(workspace_id=ws["id"])
    result = agent.run(period_days=30, auto_apply=auto_apply)
    logger.info(
        "Weekly learning [%s]: processed=%d errors=%d (auto_apply=%s)",
        ws["name"], result.processed, result.errors, auto_apply,
    )


def _run_weekly_learning() -> None:
    """Sunday 8am: analyse 30 days of outreach outcomes and surface insights.

    Runs after post_send_audit (7am). auto_apply is env-var gated so scoring
    changes are opt-in until the signal is trusted.
    """
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace
        for_each_workspace(_learning_workspace, "weekly_learning")
    except Exception as e:
        logger.error("Scheduled weekly learning failed: %s", e, exc_info=True)


def _run_weekly_post_send_audit() -> None:
    """Sunday 7am job: audit sends from the past 7 days for data quality issues."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace

        def _audit_workspace(ws: dict) -> None:
            from backend.app.agents.post_send_audit import PostSendAuditAgent
            PostSendAuditAgent(workspace_id=ws["id"]).run(days=7)

        for_each_workspace(_audit_workspace, "post_send_audit")
    except Exception as e:
        logger.error(f"Scheduled post-send audit failed: {e}", exc_info=True)


def _run_weekly_contact_backup() -> None:
    """Saturday 5am job: export all contact profiles to local JSON backup."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace

        def _backup_workspace(ws: dict) -> None:
            from backend.app.agents.contact_backup import ContactBackupAgent
            ContactBackupAgent(workspace_id=ws["id"]).run()

        for_each_workspace(_backup_workspace, "contact_backup")
    except Exception as e:
        logger.error(f"Scheduled contact backup failed: {e}", exc_info=True)


def _run_signal_monitor() -> None:
    """Weekly job: re-research qualified/outreach companies for new buying signals."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace

        def _signal_monitor_workspace(ws: dict) -> None:
            from backend.app.core.workspace_scheduler import workspace_budget_ok
            if not workspace_budget_ok(ws, "signal_monitor"):
                return
            from backend.app.agents.signal_monitor import SignalMonitorAgent
            agent = SignalMonitorAgent(workspace_id=ws["id"])
            result = agent.run(limit=50, min_pqs=30)
            logger.info(
                "Signal monitor [%s]: refreshed=%d skipped=%d errors=%d",
                ws["name"], result.processed, result.skipped, result.errors,
            )

        for_each_workspace(_signal_monitor_workspace, "signal_monitor")
    except Exception as e:
        logger.error(f"Signal monitor failed: {e}", exc_info=True)


def _run_reengagement() -> None:
    """Weekly job: re-queue contacts whose sequence completed with no reply (90-day cooldown)."""
    try:
        from backend.app.core.workspace_scheduler import for_each_workspace

        def _reengagement_workspace(ws: dict) -> None:
            from backend.app.agents.reengagement import ReengagementAgent
            agent = ReengagementAgent(workspace_id=ws["id"])
            result = agent.run(limit=50)
            logger.info(
                "Reengagement [%s]: requeued=%d errors=%d",
                ws["name"], result.processed, result.errors,
            )

        for_each_workspace(_reengagement_workspace, "reengagement")
    except Exception as e:
        logger.error(f"Reengagement failed: {e}", exc_info=True)


def _run_weekly_signal_scrapers() -> None:
    """Saturday 6am job: refresh manufacturing-specific targeting signals (FDA, OSHA, MEP)."""
    try:
        from backend.app.core.database import get_supabase_client
        from backend.app.core.database import Database

        db = Database()  # workspace-agnostic — scrapers match by company name across all workspaces

        from backend.app.agents.signal_scrapers.fda_scraper import FDARecallScraper
        from backend.app.agents.signal_scrapers.osha_scraper import OSHACitationScraper
        from backend.app.agents.signal_scrapers.mep_scraper import MEPGrantScraper

        fda_result = FDARecallScraper(db).run(days_back=90)
        logger.info("FDA scraper: %s", fda_result)

        osha_result = OSHACitationScraper(db).run(days_back=60)
        logger.info("OSHA scraper: %s", osha_result)

        # MEP runs quarterly — only run when NIST publishes new data (annual release)
        # Skipped in weekly run; trigger manually with: MEPGrantScraper(db).run()

        try:
            from backend.app.utils.notifications import notify_slack
            notify_slack(
                f"*Signal scrapers complete:* "
                f"FDA {fda_result.get('matched', 0)} matched | "
                f"OSHA {osha_result.get('matched', 0)} matched",
                emoji=":satellite:",
            )
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Scheduled signal scrapers failed: {e}", exc_info=True)


def _run_weekly_cost_summary() -> None:
    """Monday 8am job: log a weekly API cost summary."""
    try:
        from backend.app.core.database import get_supabase_client
        from datetime import datetime, timezone, timedelta
        client = get_supabase_client()
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).isoformat()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        week_result = (
            client.table("api_costs")
            .select("provider,model,estimated_cost_usd,input_tokens,output_tokens")
            .gte("created_at", week_start)
            .execute()
        )
        month_result = (
            client.table("api_costs")
            .select("estimated_cost_usd")
            .gte("created_at", month_start)
            .execute()
        )

        week_rows = week_result.data or []
        month_total = sum(float(r.get("estimated_cost_usd") or 0) for r in (month_result.data or []))
        week_total = sum(float(r.get("estimated_cost_usd") or 0) for r in week_rows)

        by_provider: dict[str, float] = {}
        for r in week_rows:
            key = f"{r.get('provider','?')}/{r.get('model','?')}"
            by_provider[key] = by_provider.get(key, 0) + float(r.get("estimated_cost_usd") or 0)

        breakdown = " | ".join(f"{k}: ${v:.2f}" for k, v in sorted(by_provider.items(), key=lambda x: -x[1])[:5])
        logger.info(
            f"WEEKLY COST SUMMARY — past 7 days: ${week_total:.2f} | "
            f"month-to-date: ${month_total:.2f} / ${MONTHLY_API_BUDGET_USD:.2f} budget | "
            f"top models: {breakdown}"
        )
    except Exception as e:
        logger.error(f"Weekly cost summary failed: {e}")


def _run_auto_action_low_priority() -> None:
    """Hourly job: auto-archive soft_no items pending for >72 hours."""
    try:
        from backend.app.core.database import Database
        from datetime import datetime, timezone, timedelta
        db = Database()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        result = (
            db.client.table("hitl_queue")
            .update({"status": "actioned", "actioned_at": datetime.now(timezone.utc).isoformat()})
            .eq("status", "pending")
            .eq("classification", "soft_no")
            .lte("created_at", cutoff)
            .execute()
        )
        count = len(result.data) if result.data else 0
        if count:
            logger.info(f"HITL: auto-archived {count} stale soft_no item(s)")
    except Exception as e:
        logger.error(f"Scheduled auto_action_low_priority failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background scheduler on startup, shut down gracefully."""
    try:
        global _scheduler
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="America/Chicago")
        _scheduler = scheduler
        scheduler.add_job(_run_health_snapshot, "interval", minutes=15, id="health_snapshot")
        # send_approved: Tue/Wed/Thu only, 8am-11am Chicago at :00 and :30
        # Ticks: 8:00, 8:30, 9:00, 9:30, 10:00, 10:30, 11:00 (7 per day)
        # With batch_size=20 and daily_limit=100, first 5 ticks fill the quota
        # so effectively all 100 emails go out by 10am — front-loaded as intended.
        # send_approved: Mon-Fri, 8am-11am Chicago at :00 and :30 (7 ticks/day)
        # 7 ticks × batch_size=20 = 140 capacity; daily_limit=125 caps it at 125
        scheduler.add_job(
            _run_send_approved, "cron",
            day_of_week="mon-fri", hour="8-11", minute="0,30",
            timezone="America/Chicago",
            id="send_approved",
        )
        scheduler.add_job(_run_process_due_sequences, "interval", hours=1, id="process_due")
        scheduler.add_job(_run_poll_instantly, "interval", hours=6, id="poll_instantly")
        scheduler.add_job(_run_process_hitl_snoozed, "interval", minutes=15, id="hitl_snoozed")
        scheduler.add_job(_run_auto_action_low_priority, "interval", hours=1, id="hitl_auto_archive")
        scheduler.add_job(_run_personalization_refresh, "interval", hours=24, id="personalization_refresh")
        scheduler.add_job(_run_jit_pregenerate, "interval", hours=24, id="jit_pregenerate")
        # Gmail intake: every 15 min so replies surface quickly for triage
        scheduler.add_job(_run_gmail_intake, "interval", minutes=15, id="gmail_intake")
        # Research: every 20 min 24/7 — 150 companies per run, budget-gated
        # Aggressive cadence to clear 7K+ reclaimed + 1.5K discovered backlog fast
        scheduler.add_job(_run_research, "interval", minutes=20, id="research")
        # Qualification: every 15 min 24/7 — stays ahead of research output
        scheduler.add_job(_run_qualification, "interval", minutes=15, id="qualification")
        # Draft generation: every 30 min — drains qualified-but-undrafted companies
        # (closes the gap where enriched contacts had no scheduled path to a sent email)
        scheduler.add_job(_run_draft_generation, "interval", minutes=30, id="draft_generation")
        # Enrichment: every 45 min 24/7 — Apollo credit-gated (1 credit/contact)
        # 45-min spacing keeps rate limits comfortable; credit guard halts if < 200 remaining
        scheduler.add_job(_run_enrichment, "interval", minutes=45, id="enrichment")
        # Pipeline monitor: email pipeline stats every hour (researched/qualified/enriched/credits/outreach)
        scheduler.add_job(_run_pipeline_monitor_email, "interval", hours=1, id="pipeline_monitor")
        # Auto-approve: high-PQS pending drafts (PQS >= 70) approved without manual review
        # Runs hourly Mon-Fri during business hours so drafts are ready for morning send
        scheduler.add_job(
            _run_auto_approve, "cron",
            day_of_week="mon-fri", hour="7-18", minute=0,
            timezone="America/Chicago",
            id="auto_approve",
        )
        # Limit ramp: bump daily_limit to 150 on 2026-05-07 (one week out, 30/account/day × 5)
        scheduler.add_job(
            _run_limit_ramp, "date",
            run_date="2026-05-07 08:00:00",
            timezone="America/Chicago",
            id="limit_ramp",
        )
        # Pipeline advance heartbeat: every 4 hours.
        # The orchestrator checks pipeline depth vs. capacity-aware watermark and fires
        # discovery + learning only when needed. Reactive triggers (post-send, post-reply)
        # schedule one-shot advances via _schedule_pipeline_advance(); this is the backstop.
        scheduler.add_job(
            _run_pipeline_advance, "interval", hours=4, id="pipeline_advance_heartbeat",
        )
        # Fire one advance immediately at startup to catch any pipeline gaps.
        scheduler.add_job(
            _run_pipeline_advance, "date",
            run_date=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(seconds=90),
            id="pipeline_advance_startup",
        )
        # Weekly post-send audit: Sunday 7am Chicago
        scheduler.add_job(
            _run_weekly_post_send_audit, "cron",
            day_of_week="sun", hour=7, minute=0,
            timezone="America/Chicago",
            id="weekly_post_send_audit",
        )
        # Weekly contact backup: Saturday 5am Chicago → /Volumes/Digitillis/Data/prospectiq_backups/
        scheduler.add_job(
            _run_weekly_contact_backup, "cron",
            day_of_week="sat", hour=5, minute=0,
            timezone="America/Chicago",
            id="weekly_contact_backup",
        )
        # Weekly signal scrapers: Saturday 6am Chicago (FDA + OSHA)
        scheduler.add_job(
            _run_weekly_signal_scrapers, "cron",
            day_of_week="sat", hour=6, minute=0,
            timezone="America/Chicago",
            id="weekly_signal_scrapers",
        )
        # Weekly signal monitor: Sunday 6am Chicago — re-research tracked
        # companies for new buying signals (leadership changes, capex, etc.)
        scheduler.add_job(
            _run_signal_monitor, "cron",
            day_of_week="sun", hour=6, minute=0,
            timezone="America/Chicago",
            id="signal_monitor",
        )
        # Weekly re-engagement: Sunday 8am Chicago — find sequences that
        # completed without a reply past the cooldown window and re-queue
        # them with fresh messaging instead of letting them fall off pipeline.
        # Slot one hour after post_send_audit to avoid contention.
        scheduler.add_job(
            _run_reengagement, "cron",
            day_of_week="sun", hour=8, minute=0,
            timezone="America/Chicago",
            id="reengagement",
        )
        # Weekly cost summary: Monday 8am Chicago
        scheduler.add_job(
            _run_weekly_cost_summary, "cron",
            day_of_week="mon", hour=8, minute=0,
            timezone="America/Chicago",
            id="weekly_cost_summary",
        )
        # Daily GTM brief: 6am Chicago Mon-Fri — Claude-written analysis + email to Avi
        scheduler.add_job(
            _run_daily_report, "cron",
            day_of_week="mon-fri", hour=6, minute=0,
            timezone="America/Chicago",
            id="daily_report",
        )
        # Daily intent refresh: 5am Chicago — recompute intent scores from
        # Apollo job postings + fresh signals so any overnight buying signal
        # is reflected in PQS before the morning send window opens.
        scheduler.add_job(
            _run_intent_refresh, "cron",
            hour=5, minute=0,
            timezone="America/Chicago",
            id="intent_refresh",
        )
        scheduler.start()
        logger.info(
            "APScheduler started — "
            "pipeline_advance every 4h (event-driven: capacity-aware discovery + learning trigger), "
            "send_approved cron Mon-Fri 8:00-11:00 Chicago (reactive advance after each batch), "
            "gmail_intake every 15m across all sender_pool mailboxes (reply draft + HITL on interested/question/objection), "
            "research 9/12/3/6pm → qualification +30m → enrichment 9:45am+2:45pm Mon-Fri (Apollo credit-gated), "
            "process_due/hitl_auto_archive every 1h, poll_instantly every 6h, "
            "personalization_refresh/jit_pregenerate every 24h, "
            "daily_report 6am Mon-Fri, "
            "weekly_post_send_audit Sun 7am, weekly_contact_backup Sat 5am, "
            "weekly_cost_summary Mon 8am, weekly_signal_scrapers Sat 6am"
        )
    except ImportError:
        logger.warning("APScheduler not installed — background jobs disabled")
        scheduler = None

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ProspectIQ API",
    version="1.0.0",
    description="AI-powered manufacturing sales prospecting backend",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server, Vercel, and Netlify domains
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://localhost(:\d+)?$|^https://.*\.vercel\.app$|^https://.*\.netlify\.app$|^https://.*\.digitillis\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Workspace context — enriches requests with workspace identity when auth present
app.add_middleware(WorkspaceMiddleware)

# Rate limiting — added after CORS so preflight requests are not rate-limited
app.add_middleware(RateLimitMiddleware, requests_per_minute=100)

# Mount route modules
app.include_router(companies.router)
app.include_router(approvals.router)
app.include_router(pipeline.router)
app.include_router(analytics.router)
app.include_router(webhooks.router)
app.include_router(settings.router)
app.include_router(actions.router)
app.include_router(action_queue.router)
app.include_router(contacts.router)
app.include_router(today.router)
app.include_router(content.router)
app.include_router(events.router)
app.include_router(instantly_webhooks.router)
app.include_router(sequences.router)
app.include_router(sequences.v2_router)
app.include_router(monitoring.router)
app.include_router(workspaces.router)
app.include_router(invite.router)
app.include_router(billing.router)
app.include_router(signup.router)
app.include_router(threads.router)
app.include_router(intelligence.router)
app.include_router(outreach_agent.router)
app.include_router(hitl.router)
app.include_router(personalization.router)
app.include_router(auth_routes.router)
app.include_router(voice_of_prospect.router)
app.include_router(multi_thread.router)
app.include_router(ghostwriting.router)
app.include_router(crm.router)
app.include_router(meetings.router)
app.include_router(deals.router)
app.include_router(targeting.router)
app.include_router(intent_signals.router)
app.include_router(memory.router)
app.include_router(llm_qualify.router)
app.include_router(onboarding.router)
app.include_router(composer.router)
app.include_router(quality_dashboard.router)


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    from backend.app.core.config import get_settings
    s = get_settings()
    secret = s.resend_webhook_secret or ""
    return {
        "status": "ok",
        "service": "prospectiq-api",
        "resend_webhook_secret_set": bool(secret),
        "resend_webhook_secret_preview": secret[:8] + "..." if len(secret) > 8 else secret,
    }


@app.get("/api/admin/send-config")
async def send_config_check():
    """Diagnostic: show send-relevant config flags (no secret values)."""
    from backend.app.core.config import get_settings
    from backend.app.core.database import get_supabase_client
    from datetime import date
    s = get_settings()
    client = get_supabase_client()
    today = date.today().isoformat()
    try:
        sent_today = (
            client.table("outreach_drafts")
            .select("id", count="exact")
            .gte("sent_at", f"{today}T00:00:00")
            .execute()
        ).count or 0
    except Exception:
        sent_today = -1
    try:
        cfg_row = (
            client.table("outreach_send_config")
            .select("daily_limit,batch_size,min_gap_minutes,send_enabled")
            .limit(1).execute().data or [{}]
        )[0]
    except Exception:
        cfg_row = {}
    try:
        pending = (
            client.table("outreach_drafts")
            .select("id", count="exact")
            .eq("approval_status", "approved")
            .is_("sent_at", "null")
            .execute()
        ).count or 0
    except Exception:
        pending = -1
    # Test if the service key can actually UPDATE (not just SELECT)
    # Uses a no-op update on a known config row
    update_test = "untested"
    try:
        test_r = (
            client.table("outreach_send_config")
            .update({"notes": None})
            .eq("workspace_id", "00000000-0000-0000-0000-000000000001")
            .execute()
        )
        update_test = "ok" if test_r.data else "blocked_empty_return"
    except Exception as e:
        update_test = f"error:{e}"

    # Fetch the first pending draft to verify the claim step would work
    claim_test = "untested"
    try:
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        drafts_sample = (
            client.table("outreach_drafts")
            .select("id,sent_at")
            .eq("approval_status", "approved")
            .is_("sent_at", "null")
            .limit(1)
            .execute()
            .data
        )
        if drafts_sample:
            d = drafts_sample[0]
            claim_test = f"draft_found:{d['id'][:8]}..._sent_at_is_null={d['sent_at'] is None}"
        else:
            claim_test = "no_pending_drafts_found"
    except Exception as e:
        claim_test = f"error:{e}"

    return {
        "env_send_enabled": s.send_enabled,
        "env_resend_api_key_set": bool(s.resend_api_key),
        "env_resend_api_key_prefix": s.resend_api_key[:8] + "..." if s.resend_api_key else "",
        "env_supabase_service_key_set": bool(s.supabase_service_key),
        "env_supabase_service_key_role": "service_role" if "service_role" in (s.supabase_service_key or "") else "anon_or_other",
        "env_send_window_start": s.send_window_start,
        "env_send_window_end": s.send_window_end,
        "db_send_config": cfg_row,
        "sent_today": sent_today,
        "approved_unsent": pending,
        "update_permission_test": update_test,
        "draft_claim_test": claim_test,
    }


@app.get("/api/admin/send-trace")
async def send_trace():
    """Step-by-step dry-run of the send path — identifies exactly where it stops."""
    from backend.app.core.config import get_settings
    from backend.app.core.database import get_supabase_client, Database
    from backend.app.core.suppression import is_suppressed
    from backend.app.core.channel_coordinator import is_company_locked
    from datetime import date

    trace = []
    s = get_settings()

    # Step 1: gate checks
    if not s.send_enabled:
        return {"abort_at": "send_enabled=false", "trace": trace}
    trace.append("send_enabled=true")

    if not s.resend_api_key:
        return {"abort_at": "resend_api_key missing", "trace": trace}
    trace.append("resend_api_key=set")

    client = get_supabase_client()
    db = Database()

    # Step 2: daily count
    today = date.today().isoformat()
    try:
        sent_today = (
            client.table("outreach_drafts").select("id", count="exact")
            .gte("sent_at", f"{today}T00:00:00").execute()
        ).count or 0
    except Exception as e:
        return {"abort_at": f"count_sent_today error: {e}", "trace": trace}

    cfg = {"daily_limit": 30, "batch_size": 10}
    try:
        row = client.table("outreach_send_config").select("daily_limit,batch_size").limit(1).execute().data
        if row:
            cfg.update(row[0])
    except Exception:
        pass

    remaining = cfg["daily_limit"] - sent_today
    trace.append(f"sent_today={sent_today} daily_limit={cfg['daily_limit']} remaining={remaining}")

    if remaining <= 0:
        return {"abort_at": "daily_limit_reached", "trace": trace}

    # Step 3: fetch drafts
    fetch_limit = min(cfg["batch_size"], remaining)
    try:
        drafts = (
            client.table("outreach_drafts")
            .select("id,company_id,contact_id,subject,channel,companies(name),contacts(full_name,email)")
            .eq("approval_status", "approved")
            .is_("sent_at", "null")
            .eq("channel", "email")
            .not_.is_("subject", "null")
            .neq("subject", "")
            .order("created_at")
            .limit(fetch_limit)
            .execute()
            .data
        ) or []
    except Exception as e:
        return {"abort_at": f"fetch_drafts error: {e}", "trace": trace}

    trace.append(f"drafts_fetched={len(drafts)}")
    if not drafts:
        return {"abort_at": "no_drafts_returned", "trace": trace}

    # Step 4: trace first 3 drafts through all checks
    per_draft = []
    for draft in drafts[:3]:
        info = {"id": draft["id"][:8]}
        contact = draft.get("contacts") or {}
        company = draft.get("companies") or {}
        info["company"] = company.get("name", "null")
        info["contact_email"] = contact.get("email") or None

        if not info["contact_email"]:
            info["skip_reason"] = "no_email"
            per_draft.append(info)
            continue

        try:
            suppressed, sup_reason = is_suppressed(
                db, draft["company_id"], contact_id=draft.get("contact_id"), skip_duplicate_check=True
            )
            info["suppressed"] = suppressed
            info["sup_reason"] = sup_reason
        except Exception as e:
            info["suppressed"] = f"error:{e}"

        if info.get("suppressed") is True:
            info["skip_reason"] = f"suppressed:{sup_reason}"
            per_draft.append(info)
            continue

        try:
            locked, lock_reason = is_company_locked(db, draft["company_id"], exclude_contact_id=draft.get("contact_id"))
            info["locked"] = locked
            info["lock_reason"] = lock_reason
        except Exception as e:
            info["locked"] = f"error:{e}"

        if info.get("locked") is True:
            info["skip_reason"] = f"locked:{lock_reason}"
            per_draft.append(info)
            continue

        info["would_send"] = True
        per_draft.append(info)

    trace.append(f"first_3_drafts_checked")
    return {"abort_at": None, "trace": trace, "per_draft": per_draft}


@app.post("/api/admin/trigger-send")
async def trigger_send():
    """Manually trigger send_approved — useful when cron tick hasn't fired yet."""
    import threading
    threading.Thread(target=_run_send_approved, daemon=True).start()
    return {"status": "triggered", "message": "send_approved job started in background"}
