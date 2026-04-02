"""FastAPI application for ProspectIQ API.

Serves the Next.js CRM dashboard with endpoints for
companies, approvals, pipeline agents, analytics, and webhooks.
"""

import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from time import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

<<<<<<< Updated upstream
<<<<<<< Updated upstream
from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks, settings, actions, action_queue, contacts, today, content, events, sequences, monitoring, workspaces, invite, billing, signup, threads, intelligence, outreach_agent, hitl, personalization
=======
from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks, settings, actions, action_queue, contacts, today, content, events, sequences, monitoring, workspaces, invite, billing, signup, threads, intelligence, outreach_agent, hitl, personalization, lookalike, auth as auth_routes
>>>>>>> Stashed changes
=======
from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks, settings, actions, action_queue, contacts, today, content, events, sequences, monitoring, workspaces, invite, billing, signup, threads, intelligence, outreach_agent, hitl, personalization, multi_thread, ghostwriting
>>>>>>> Stashed changes
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
    """Every-30-min job: push approved drafts to Instantly (gated by SEND_ENABLED)."""
    try:
        from backend.app.core.config import get_settings
        if not get_settings().send_enabled:
            return  # Silently skip — warm-up not complete yet
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
        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_health_snapshot, "interval", minutes=15, id="health_snapshot")
        scheduler.add_job(_run_send_approved, "interval", minutes=30, id="send_approved")
        scheduler.add_job(_run_process_due_sequences, "interval", hours=1, id="process_due")
        scheduler.add_job(_run_poll_instantly, "interval", hours=6, id="poll_instantly")
        scheduler.add_job(_run_process_hitl_snoozed, "interval", minutes=15, id="hitl_snoozed")
        scheduler.add_job(_run_auto_action_low_priority, "interval", hours=1, id="hitl_auto_archive")
        scheduler.add_job(_run_personalization_refresh, "interval", hours=24, id="personalization_refresh")
        scheduler.start()
        logger.info(
            "APScheduler started — health_snapshot/hitl_snoozed every 15m, "
            "send_approved every 30m, process_due/hitl_auto_archive every 1h, "
            "poll_instantly every 6h, personalization_refresh every 24h"
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
<<<<<<< Updated upstream
<<<<<<< Updated upstream
=======
app.include_router(lookalike.router)
app.include_router(auth_routes.router)
>>>>>>> Stashed changes
=======
app.include_router(multi_thread.router)
app.include_router(ghostwriting.router)
>>>>>>> Stashed changes


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok", "service": "prospectiq-api"}
