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
        logger.error(f"Scheduled gmail_intake failed: {e}", exc_info=True)


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
                    subject=f"ProspectIQ spend alert: ${spend:.0f} of ${MONTHLY_API_BUDGET_USD:.0f} used this month",
                    html_body=(
                        f"<p>Monthly API spend is at <strong>${spend:.2f}</strong> "
                        f"({spend / MONTHLY_API_BUDGET_USD * 100:.0f}% of the ${MONTHLY_API_BUDGET_USD:.0f} cap).</p>"
                        f"<p>Hard stop activates at ${MONTHLY_API_BUDGET_USD:.0f}. "
                        f"Remaining budget: <strong>${MONTHLY_API_BUDGET_USD - spend:.2f}</strong>.</p>"
                        f"<p>Research and enrichment continue until the cap is hit. "
                        f"Reply to this email or update the cap in Railway if you want to raise it.</p>"
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


def _run_qualification() -> None:
    """Daily job: score researched companies and promote to qualified/disqualified."""
    try:
        from backend.app.agents.qualification import QualificationAgent
        agent = QualificationAgent()
        result = agent.run(batch_size=100)
        logger.info(f"Scheduled qualification: processed={result.processed} errors={result.errors}")
    except Exception as e:
        logger.error(f"Scheduled qualification failed: {e}", exc_info=True)


def _run_research() -> None:
    """Runs 4× daily (9am / 12pm / 3pm / 6pm Mon-Fri) — 50 companies per run, budget-gated."""
    if not _check_budget("research"):
        return
    try:
        from backend.app.agents.research import ResearchAgent
        agent = ResearchAgent()
        result = agent.run(batch_size=50)
        logger.info(f"Scheduled research: processed={result.processed} errors={result.errors}")
    except Exception as e:
        logger.error(f"Scheduled research failed: {e}", exc_info=True)


def _run_auto_approve() -> None:
    """Auto-approve high-PQS pending drafts (PQS >= 70) to reduce manual bottleneck."""
    try:
        from backend.app.core.database import get_supabase_client
        from backend.app.core.config import get_settings
        client = get_supabase_client()
        ws = get_settings().default_workspace_id

        rows = (
            client.table("outreach_drafts")
            .select("id, company_id, companies(pqs_total)")
            .eq("approval_status", "pending")
            .is_("sent_at", "null")
            .eq("workspace_id", ws)
            .limit(200)
            .execute()
            .data or []
        )

        approved = 0
        for r in rows:
            pqs = (r.get("companies") or {}).get("pqs_total") or 0
            if pqs >= 70:
                client.table("outreach_drafts").update(
                    {"approval_status": "approved"}
                ).eq("id", r["id"]).execute()
                approved += 1

        if approved:
            logger.info(f"Auto-approve: approved {approved} high-PQS drafts (PQS >= 70)")
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


def _run_enrichment() -> None:
    """2× daily job: enrich up to 100 contacts per run via Apollo (burns Apollo credits)."""
    if not _check_budget("enrichment"):
        return
    try:
        from backend.app.agents.enrichment import EnrichmentAgent
        agent = EnrichmentAgent()
        result = agent.run(batch_size=100)
        logger.info(f"Scheduled enrichment: processed={result.processed} errors={result.errors}")
    except Exception as e:
        logger.error(f"Scheduled enrichment failed: {e}", exc_info=True)


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
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="America/Chicago")
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
        # Research: 4× daily Mon-Fri (9am / 12pm / 3pm / 6pm) — 50 companies per run
        # 200 companies/day max; budget gate stops early if monthly limit hit
        scheduler.add_job(
            _run_research, "cron",
            day_of_week="mon-fri", hour="9,12,15,18", minute=0,
            timezone="America/Chicago",
            id="research",
        )
        # Qualification: runs 30 min after each research wave
        scheduler.add_job(
            _run_qualification, "cron",
            day_of_week="mon-fri", hour="9,12,15,18", minute=30,
            timezone="America/Chicago",
            id="qualification",
        )
        # Enrichment: 2× daily Mon-Fri (9:45am + 2:45pm) — 100 contacts per run via Apollo
        scheduler.add_job(
            _run_enrichment, "cron",
            day_of_week="mon-fri", hour="9,14", minute=45,
            timezone="America/Chicago",
            id="enrichment",
        )
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
        scheduler.start()
        logger.info(
            "APScheduler started — health_snapshot/hitl_snoozed every 15m, "
            "send_approved cron Tue-Thu 8:00-11:00 Chicago, gmail_intake every 30m, "
            "process_due/hitl_auto_archive every 1h, "
            "poll_instantly every 6h, personalization_refresh/jit_pregenerate every 24h, "
            "research 9/12/3pm → qualification 9:30/12:30/3:30pm → enrichment 9:45am Mon-Fri Chicago (budget-gated), "
            "daily_report 6am Chicago Mon-Fri, "
            "weekly_cost_summary Mon 8am Chicago"
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
