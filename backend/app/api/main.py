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

from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks, settings, actions, action_queue, contacts, today, content, events, sequences, monitoring, workspaces, invite, billing, signup, threads, intelligence, outreach_agent, hitl, personalization, auth as auth_routes, voice_of_prospect, multi_thread, ghostwriting, crm, meetings, deals, targeting, intent_signals, memory, llm_qualify, composer
from backend.app.webhooks import instantly as instantly_webhooks
from backend.app.core.workspace_middleware import WorkspaceMiddleware

logger = logging.getLogger(__name__)


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


def _run_send_approved() -> None:
    """Cron job: push approved drafts to Instantly (gated by SEND_ENABLED).

    Scheduled Mon-Fri at :00 and :30 past each hour from 8 AM–11 AM Chicago time.
    Timing is enforced by the cron trigger; no additional window check needed here.
    """
    try:
        from backend.app.core.config import get_settings
        settings = get_settings()
        if not settings.send_enabled:
            return  # Silently skip — send not enabled
        from backend.app.agents.engagement import EngagementAgent
        agent = EngagementAgent()
        agent.run(action="send_approved")
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


def _run_gmail_intake() -> None:
    """Every-30-min job: poll Gmail IMAP for reply emails to avi@digitillis.io."""
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

                # Insert thread_message
                try:
                    db.client.table("thread_messages").insert({
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

                # Update campaign_threads if exists
                try:
                    db.client.table("campaign_threads").update({
                        "status": "replied",
                        "last_replied_at": received_at,
                    }).eq("contact_id", contact_id).execute()
                except Exception as e:
                    logger.warning(f"Gmail intake: campaign_threads update failed: {e}")

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
        logger.error(f"Scheduled gmail_intake failed: {e}", exc_info=True)


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
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="America/Chicago")
        scheduler.add_job(_run_health_snapshot, "interval", minutes=15, id="health_snapshot")
        # send_approved: cron at :00 and :30 of every hour Mon-Fri, 8am-11am Chicago
        # Ticks: 8:00, 8:30, 9:00, 9:30, 10:00, 10:30, 11:00 AM
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
        scheduler.add_job(_run_gmail_intake, "interval", minutes=30, id="gmail_intake")
        scheduler.start()
        logger.info(
            "APScheduler started — health_snapshot/hitl_snoozed every 15m, "
            "send_approved cron Mon-Fri 8:00-10:30 Chicago, gmail_intake every 30m, "
            "process_due/hitl_auto_archive every 1h, "
            "poll_instantly every 6h, personalization_refresh/jit_pregenerate every 24h"
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
app.include_router(composer.router)


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


@app.post("/api/admin/trigger-send")
async def trigger_send():
    """Manually trigger send_approved — useful when cron tick hasn't fired yet."""
    import threading
    threading.Thread(target=_run_send_approved, daemon=True).start()
    return {"status": "triggered", "message": "send_approved job started in background"}
