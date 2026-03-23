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

from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks, settings, actions, action_queue, contacts, today, content, events

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background scheduler on startup, shut down gracefully."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_process_due_sequences, "interval", hours=1, id="process_due")
        scheduler.add_job(_run_poll_instantly, "interval", hours=6, id="poll_instantly")
        scheduler.start()
        logger.info("APScheduler started — process_due every 1h, poll_instantly every 6h")
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


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok", "service": "prospectiq-api"}
