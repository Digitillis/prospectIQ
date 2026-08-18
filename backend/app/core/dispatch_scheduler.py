"""Dispatch scheduler — queue claim, Resend dispatch, retry lifecycle (PR G).

Invariants:
  1. send_attempts with status=DISPATCHED is inserted before every Resend call.
  2. No Resend call may occur without a send_attempts record.
  3. On assertion failure: release lock without setting next_retry_at (retry next tick).
  4. On transient failure (5xx/429): schedule next_retry_at via exponential backoff.
  5. On permanent failure (4xx except 429, or max_retries exhausted): delete queue
     row + set outreach_drafts.approval_status='dispatch_failed'.
  6. Stale lock reclaim: rows with locked_at older than STALE_LOCK_MINUTES have
     their lock cleared. Count and log every reclaim.

No time.sleep() in this module. Stagger between sends comes from multiple
cron ticks 30 minutes apart during the send window, not within-batch sleep.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Exponential backoff schedule indexed by (new_retry_count - 1).
# retry 0→1: +5min, 1→2: +15min, 2→3: +1h, 3→4: +4h
_BACKOFF_SECONDS: list[int] = [300, 900, 3600, 14400]

STALE_LOCK_MINUTES: int = 5

# Cap simultaneous Supabase operations across APScheduler BackgroundScheduler
# threads. At 5+ concurrent jobs the connection pool saturates, producing
# "Server disconnected" / RemoteProtocolError in production logs.
# threading.Semaphore is used (not asyncio) because dispatch_workspace is sync
# and called from BackgroundScheduler thread-pool workers.
# Stagger between sends still comes from cron ticks — no time.sleep() here.
_DISPATCH_CONCURRENCY: threading.Semaphore = threading.Semaphore(3)

# Debounce for the compliance-config-missing Slack alert below — every
# affected draft in a batch (up to batch_size=45) hits this on the same
# tick, and the tick repeats every 30 minutes while the misconfiguration
# persists. Without a cooldown this would post dozens of duplicate Slack
# messages per tick, every tick. One alert per hour is enough to make the
# outage known without becoming noise that gets muted.
#
# _last_compliance_alert_at is a check-then-act on a shared global, and this
# module is genuinely multi-threaded: _DISPATCH_CONCURRENCY caps concurrent
# dispatch_workspace() calls at 3, and a manual admin trigger
# (backend/app/api/main.py's trigger-dispatch endpoint) can also spawn a
# raw thread that reaches this same function concurrently with the
# scheduled job. compliance_config_missing is global by construction — it
# blocks every workspace at once — so "multiple dispatch threads hit this
# right when the misconfiguration first appears" is the normal case this
# debounce exists for, not an edge case. The lock bounds it to exactly one
# alert per cooldown window instead of one per concurrent thread.
_COMPLIANCE_ALERT_COOLDOWN: timedelta = timedelta(hours=1)
_last_compliance_alert_at: Optional[datetime] = None
_compliance_alert_lock: threading.Lock = threading.Lock()


@dataclass
class BatchResult:
    dispatched: int = 0
    delivered: int = 0
    transient_failed: int = 0
    permanently_failed: int = 0
    assertion_skipped: int = 0
    already_delivered_drained: int = 0
    errors: int = 0
    # Set when dispatch_workspace() aborted before claiming anything because
    # sending is disabled (env var, DB config, or both) — see
    # _send_disabled_reason(). Distinct from an empty claim (dispatched=0
    # with send_disabled=False means "ran normally, nothing was due").
    send_disabled: bool = False
    send_disabled_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_for(retry_count: int) -> int:
    """Return backoff seconds for transitioning from retry_count to retry_count+1."""
    idx = min(retry_count, len(_BACKOFF_SECONDS) - 1)
    return _BACKOFF_SECONDS[idx]


def _is_permanent_assertion_failure(failure_reason: str) -> bool:
    """True when an ASSERTION_FAILED outcome will never self-resolve and
    should be dead-lettered immediately rather than retried.
    """
    return any(
        failure_reason.startswith(p)
        for p in (
            "cluster_routing_skip:",
            "outreach_eligible:",  # tier/eligibility flag — won't flip automatically
            "suppressed:",  # suppression list — manual removal only
            "contact_has_no_email",
            "contact_fetch_failed",
        )
    )


def _classify_assertion_failure_code(failure_reason: str) -> str:
    """Map an ASSERTION_FAILED failure_reason to a send_attempts.failure_code.

    Distinguishes a genuine assertion failure from an expected, self-resolving
    scheduling deferral (company cooldown, hot-lead re-check window, prior
    step in flight, minimum step gap). `send_attempts.status` stays
    FAILED/PERMANENTLY_FAILED for all of these — the column is CHECK-
    constrained to DISPATCHED|DELIVERED|FAILED|PERMANENTLY_FAILED, so there
    is no DEFERRED value without a migration — but failure_code now records
    which case this was.

    Before this fix, all five collapsed into a single "assertion_failed"
    bucket, which is why aggregate dashboards read as ~13.7k failures when
    the majority were company-lock and step-gap deferrals re-evaluated (and
    re-logged as a new "failure") on the next scheduler tick.

    compliance_config_error: (added post-review) is a SIXTH case, and it is
    neither a genuine gate failure nor a per-contact deferral — it is a
    GLOBAL, temporary misconfiguration (missing physical_address or
    backend_public_url, see backend/app/core/unsubscribe.py) that blocks
    every draft in every workspace simultaneously until a human fixes
    config. Without its own code, it fell into the same generic
    "assertion_failed" bucket this function exists to disambiguate from —
    the exact bug this function was written to fix, reintroduced by the fix
    itself. See the dedicated retry-delay branch in
    _dispatch_workspace_inner() for why it is also NOT routed through
    _is_permanent_assertion_failure(): dead-lettering every blocked draft
    would lose them once the config is fixed, since nothing re-enqueues a
    deleted queue row automatically.
    """
    if failure_reason.startswith("cluster_routing_skip:"):
        return "cluster_routing_skip"
    if failure_reason.startswith("company_locked:"):
        return "deferred_company_locked"
    if failure_reason.startswith("hot_suppressed:"):
        return "deferred_hot_suppressed"
    if failure_reason.startswith("prior_step_sent:"):
        return "deferred_prior_step"
    if failure_reason.startswith("minimum_step_gap:"):
        return "deferred_step_gap"
    if failure_reason.startswith("compliance_config_error:"):
        return "compliance_config_missing"
    return "assertion_failed"


def _maybe_alert_compliance_config_missing(failure_reason: str) -> None:
    """Fire a rate-limited Slack alert for a compliance_config_missing block.

    The boot-log warning in main.py's lifespan() is the primary discovery
    mechanism for this misconfiguration (see _classify_assertion_failure_code
    above), but it only fires once, at startup, and is easy to miss in
    Railway's log stream. This is the fallback for the case that motivated
    that comment: whoever doesn't read boot logs. Fire-and-forget — never
    raises, never blocks dispatch (notify_slack already fails soft if no
    webhook is configured).
    """
    global _last_compliance_alert_at
    with _compliance_alert_lock:
        now = datetime.now(timezone.utc)
        if (
            _last_compliance_alert_at is not None
            and now - _last_compliance_alert_at < _COMPLIANCE_ALERT_COOLDOWN
        ):
            return
        _last_compliance_alert_at = now
    try:
        from backend.app.utils.notifications import notify_slack

        notify_slack(
            f"ProspectIQ dispatch blocked: compliance_config_missing "
            f"({failure_reason[:200]}). All outbound sends are held until "
            f"physical_address / backend_public_url are set. "
            f"See /api/admin/send-trace for a live check.",
            emoji=":warning:",
        )
    except Exception as exc:
        logger.warning("compliance_config_missing Slack alert failed (non-fatal): %s", exc)


def _resolve_provider_message_id(db_client, draft_id: str) -> Optional[str]:
    """Return resend_message_id from outreach_drafts for ALREADY_DELIVERED reconciliation.

    If non-None: Resend API call completed — email was dispatched (Scenario C).
    If None: Resend was never called — draft was pre-claimed but process crashed
             before the API call (Scenario E). Email was NOT delivered.
    """
    try:
        rows = (
            db_client.table("outreach_drafts")
            .select("resend_message_id")
            .eq("id", draft_id)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            return rows[0].get("resend_message_id") or None
    except Exception as exc:
        logger.error("dispatch.resolve_provider_id FAILED draft_id=%s error=%s", draft_id, exc)
    return None


def _next_attempt_number(db_client, draft_id: str) -> int:
    """Return the next attempt_number for draft_id, derived from actual
    send_attempts rows rather than queue_row.retry_count.

    retry_count and attempt_number used to be the same counter
    (attempt_number = retry_count + 1), but they track different things:
    retry_count is a budget spent only on genuine failed-send attempts
    (deliberately NOT bumped for the four "timed" assertion outcomes —
    company_locked/hot_suppressed/prior_step_sent/minimum_step_gap — see
    _set_queue_next_retry's docstring, so a temporary external block
    doesn't count toward max_retries dead-lettering). Since a "timed"
    outcome still inserts a send_attempts row (the invariant at the top
    of this module: a row must exist before any Resend call is even
    considered) without bumping retry_count, the next claim recomputed
    the same attempt_number and collided with (draft_id, attempt_number)'s
    unique constraint on send_attempts — a duplicate-key crash on retry,
    observed directly 2026-08-17/18 during a real dispatch test. Deriving
    attempt_number from the real row count keeps retry_count's budget
    semantics intact while making every insert land on a fresh slot.

    This does NOT delete or renumber existing rows — send_attempts rows
    are append-only by convention here, matching _run_orphan_attempt_cleanup
    (backend/app/api/main.py) which already deletes stale FAILED
    attempt_number=1 rows as a workaround for this exact collision. That
    cron becomes redundant for the case this fix addresses (it can likely
    be retired once this has run in production for a while) but is left
    running for now since it may still catch orphaned rows this fix
    doesn't reach — a separate cleanup, not bundled here.
    (Note: _ALLOWED_TRANSITIONS/_guard_status_transition below governs
    illegal UPDATE status transitions on this table, not deletes — it
    does not itself prevent a delete-based fix; append-only was a
    deliberate choice for this fix, not something the guard forced.)

    Known residual gap: on a lookup failure this falls back to 1
    unconditionally, which could still collide if a prior attempt exists
    and the SELECT fails transiently while a later INSERT succeeds. Bounded:
    _insert_send_attempt's own try/except catches that INSERT failure,
    logs it, and returns None; the caller then releases the queue lock
    without bumping retry_count and retries on the next tick rather than
    crashing the dispatch loop.
    """
    try:
        rows = (
            db_client.table("send_attempts")
            .select("attempt_number")
            .eq("draft_id", draft_id)
            .order("attempt_number", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            return rows[0]["attempt_number"] + 1
    except Exception as exc:
        logger.warning(
            "dispatch.next_attempt_number_lookup_failed draft_id=%s error=%s — defaulting to 1",
            draft_id,
            exc,
        )
    return 1


def _insert_send_attempt(
    db_client,
    draft_id: str,
    workspace_id: str,
    attempt_number: int,
    idempotency_key: str,
) -> Optional[str]:
    """Insert a DISPATCHED send_attempts row before the Resend call.

    Returns the row id on success, or None if the insert fails.
    Failure means the Resend call MUST NOT proceed.
    """
    try:
        rows = (
            db_client.table("send_attempts")
            .insert(
                {
                    "draft_id": draft_id,
                    "workspace_id": workspace_id,
                    "attempt_number": attempt_number,
                    "idempotency_key": idempotency_key,
                    "status": "DISPATCHED",
                    "dispatched_at": _now_iso(),
                }
            )
            .execute()
            .data
        )
        if rows:
            return rows[0]["id"]
    except Exception as exc:
        logger.error(
            "dispatch.insert_send_attempt FAILED draft_id=%s attempt=%d: %s",
            draft_id,
            attempt_number,
            exc,
        )
    return None


# ---------------------------------------------------------------------------
# Audit-record immutability — app-layer status-transition guard (SEC-013 / ADR-002)
# ---------------------------------------------------------------------------

# Legal forward transitions. DELIVERED→PERMANENTLY_FAILED is the only backward-looking
# allowed path (bounce reconciliation: provider confirmed delivery then later bounced).
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISPATCHED": frozenset({"DELIVERED", "FAILED", "PERMANENTLY_FAILED"}),
    "FAILED": frozenset(
        {"DISPATCHED", "PERMANENTLY_FAILED"}
    ),  # retry = new DISPATCHED row; explicit terminal
    "DELIVERED": frozenset({"PERMANENTLY_FAILED"}),  # bounce reconciliation only
    "PERMANENTLY_FAILED": frozenset(),  # terminal — no further writes
}


def _guard_status_transition(db_client, attempt_id: str, new_status: str) -> bool:
    """Verify the status transition is legal. Returns True if allowed, logs ERROR and returns False if not.

    Called before every _update_send_attempt that includes a 'status' field.
    Never raises — the caller proceeds or skips based on the return value.
    See ADR-002 for the transition table and rationale.
    """
    try:
        rows = (
            db_client.table("send_attempts")
            .select("status")
            .eq("id", attempt_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            return True  # row not found — let insert/update proceed; caller handles missing row
        current = rows[0].get("status", "") or ""
        if current not in _ALLOWED_TRANSITIONS:
            # Unrecognized current status (e.g. freshly inserted row, empty string, or
            # future status not yet in this table). Allow the transition — unknown is not terminal.
            return True
        allowed = _ALLOWED_TRANSITIONS[current]
        if new_status not in allowed:
            logger.error(
                "dispatch.illegal_status_transition attempt_id=%s current=%s new=%s allowed=%s — write blocked (ADR-002)",
                attempt_id,
                current,
                new_status,
                sorted(allowed),
            )
            return False
    except Exception as exc:
        logger.warning(
            "dispatch.status_guard_check_failed attempt_id=%s new_status=%s error=%s — allowing (non-blocking guard)",
            attempt_id,
            new_status,
            exc,
        )
    return True


def _update_send_attempt(db_client, attempt_id: str, **fields) -> None:
    new_status = fields.get("status")
    if new_status and not _guard_status_transition(db_client, attempt_id, new_status):
        return  # illegal transition — blocked, already logged at ERROR
    try:
        db_client.table("send_attempts").update(fields).eq("id", attempt_id).execute()
    except Exception as exc:
        logger.error(
            "dispatch.update_send_attempt id=%s fields=%s error=%s",
            attempt_id,
            list(fields.keys()),
            exc,
        )


def _release_queue_lock(db_client, queue_row_id: str) -> None:
    try:
        db_client.table("outbound_queue").update(
            {
                "locked_by": None,
                "locked_at": None,
            }
        ).eq("id", queue_row_id).execute()
    except Exception as exc:
        logger.error("dispatch.release_queue_lock id=%s error=%s", queue_row_id, exc)


def _release_queue_lock_bump_retry(db_client, queue_row_id: str, current_retry_count: int) -> None:
    """Release lock and increment retry_count after an assertion failure.

    attempt_number is derived as retry_count + 1. Without bumping retry_count,
    every re-attempt collides on the same attempt_number in send_attempts
    (unique constraint on draft_id + attempt_number). Assertion failures are not
    transient errors — no backoff, no max_retries — so next_retry_at stays NULL
    and the row is picked up on the next scheduler tick.
    """
    try:
        db_client.table("outbound_queue").update(
            {
                "locked_by": None,
                "locked_at": None,
                "retry_count": current_retry_count + 1,
            }
        ).eq("id", queue_row_id).execute()
    except Exception as exc:
        logger.error("dispatch.release_lock_bump_retry id=%s error=%s", queue_row_id, exc)


def _set_queue_next_retry(db_client, queue_row_id: str, delay_seconds: int) -> None:
    """Park a queue row until delay_seconds from now without bumping retry_count.

    Used for timed assertion failures (company_locked, hot_suppressed, prior_step_not_sent)
    where the row is valid but temporarily blocked. Preserves retry_count so the row
    is not dead-lettered before the block resolves.
    """
    from datetime import datetime, timezone, timedelta
    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
    try:
        db_client.table("outbound_queue").update(
            {"locked_by": None, "locked_at": None, "next_retry_at": retry_at}
        ).eq("id", queue_row_id).execute()
    except Exception as exc:
        logger.error("dispatch.set_queue_next_retry id=%s error=%s", queue_row_id, exc)


def _delete_queue_row(db_client, queue_row_id: str) -> None:
    try:
        db_client.table("outbound_queue").delete().eq("id", queue_row_id).execute()
    except Exception as exc:
        logger.error("dispatch.delete_queue_row id=%s error=%s", queue_row_id, exc)


def _schedule_retry(db_client, queue_row: dict, new_retry_count: int) -> None:
    delay = _backoff_for(new_retry_count - 1)
    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    try:
        db_client.table("outbound_queue").update(
            {
                "retry_count": new_retry_count,
                "next_retry_at": retry_at,
                "locked_by": None,
                "locked_at": None,
            }
        ).eq("id", queue_row["id"]).execute()
        logger.info(
            "dispatch.retry_scheduled draft_id=%s retry_count=%d retry_at=%s",
            queue_row["draft_id"],
            new_retry_count,
            retry_at,
        )
    except Exception as exc:
        logger.error(
            "dispatch.schedule_retry FAILED id=%s new_retry_count=%d error=%s",
            queue_row["id"],
            new_retry_count,
            exc,
        )


def _mark_draft_dispatch_failed(db_client, draft_id: str) -> None:
    try:
        db_client.table("outreach_drafts").update(
            {
                "approval_status": "dispatch_failed",
            }
        ).eq("id", draft_id).execute()
    except Exception as exc:
        logger.error(
            "dispatch.mark_draft_dispatch_failed draft_id=%s error=%s",
            draft_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Public: stale lock reclaim
# ---------------------------------------------------------------------------


def reclaim_stale_locks(db_client, workspace_id: str) -> int:
    """Clear distributed locks held longer than STALE_LOCK_MINUTES.

    Returns the number of rows reclaimed. Logs a warning for every reclaim
    so the count is visible in structured logs.
    """
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_LOCK_MINUTES)).isoformat()
    try:
        rows = (
            db_client.table("outbound_queue")
            .update({"locked_by": None, "locked_at": None})
            .eq("workspace_id", workspace_id)
            .not_.is_("locked_at", "null")
            .lt("locked_at", stale_cutoff)
            .execute()
            .data
            or []
        )
        count = len(rows)
        if count:
            logger.warning(
                "dispatch.stale_lock_reclaim workspace_id=%s reclaimed=%d (locked_at < %s)",
                workspace_id,
                count,
                stale_cutoff,
            )
        else:
            logger.debug(
                "dispatch.stale_lock_reclaim workspace_id=%s no stale locks",
                workspace_id,
            )
        return count
    except Exception as exc:
        logger.error(
            "dispatch.stale_lock_reclaim ERROR workspace_id=%s error=%s",
            workspace_id,
            exc,
        )
        return 0


# ---------------------------------------------------------------------------
# Public: pre-dispatch eligibility screen
# ---------------------------------------------------------------------------


def screen_dispatch_queue(db_client, workspace_id: str, batch_size: int = 100) -> dict:
    """Pre-dispatch eligibility check — call before any manual trigger.

    Counts how many of the top `batch_size` claimable rows in outbound_queue
    would actually reach Resend after passing the key assertions checked in
    dispatch_queued_draft:
      - contact.is_outreach_eligible = true
      - contact not in suppression_log (hard_bounce / manual_block / unsubscribed)
      - company.campaign_cluster not in ('other', 'watchlist')
      - prior sequence step has been sent (for steps 2–5)

    Returns a dict with eligible_count, blocked_breakdown, and total_claimable
    so callers can decide whether to proceed and with what batch_size.
    """
    try:
        result = (
            db_client.rpc(
                "claim_outbound_queue_batch",
                {
                    "p_workspace_id": workspace_id,
                    "p_instance_id": "pre_screen_dry_run",
                    "p_batch_size": batch_size,
                },
            )
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.error("screen_dispatch_queue: claim failed: %s", exc)
        return {"error": str(exc)}

    # Immediately release all locks — this is a read-only screen, not a real dispatch
    if result:
        ids = [r["id"] for r in result]
        try:
            db_client.table("outbound_queue").update(
                {"locked_by": None, "locked_at": None}
            ).in_("id", ids).execute()
        except Exception as exc:
            logger.warning("screen_dispatch_queue: lock release failed: %s", exc)

    total_claimable = len(result)
    if total_claimable == 0:
        return {"eligible_count": 0, "total_claimable": 0, "blocked": {}}

    draft_ids = [r["draft_id"] for r in result]

    # Fetch drafts with contact/company data needed for assertion checks
    try:
        drafts = (
            db_client.table("outreach_drafts")
            .select(
                "id, contact_id, company_id, sequence_step, "
                "contact:contacts(is_outreach_eligible, contact_tier, email), "
                "company:companies(campaign_cluster)"
            )
            .in_("id", draft_ids)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.error("screen_dispatch_queue: draft fetch failed: %s", exc)
        return {"error": str(exc), "total_claimable": total_claimable}

    # Suppressed emails
    try:
        all_emails = [
            (d.get("contact") or {}).get("email") for d in drafts if d.get("contact")
        ]
        suppressed_emails: set[str] = set()
        if all_emails:
            sup_rows = (
                db_client.table("suppression_log")
                .select("email")
                .in_("email", [e for e in all_emails if e])
                .in_("reason", ["hard_bounce_contact", "manual_block", "unsubscribed", "spam_complaint"])
                .execute()
                .data
                or []
            )
            suppressed_emails = {r["email"] for r in sup_rows}
    except Exception:
        suppressed_emails = set()

    # Prior-step sent check: for each step>1, verify prior step is sent
    try:
        contact_ids = list({d["contact_id"] for d in drafts if d.get("contact_id")})
        sent_steps: dict[str, set[int]] = {}
        if contact_ids:
            sent_rows = (
                db_client.table("outreach_drafts")
                .select("contact_id, sequence_step")
                .in_("contact_id", contact_ids)
                .not_.is_("sent_at", "null")
                .execute()
                .data
                or []
            )
            for row in sent_rows:
                sent_steps.setdefault(row["contact_id"], set()).add(row["sequence_step"])
    except Exception:
        sent_steps = {}

    # Company-locked check: step-1 rows where company was touched within 8 days
    from datetime import datetime, timezone, timedelta
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    company_ids_step1 = {
        d["company_id"] for d in drafts
        if d.get("company_id") and int(d.get("sequence_step") or 1) == 1
    }
    locked_company_ids: set[str] = set()
    if company_ids_step1:
        try:
            lock_rows = (
                db_client.table("interactions")
                .select("contact_id, company_id:contacts(company_id)")
                .in_("type", ["email_sent", "email_replied", "linkedin_connection", "linkedin_message"])
                .gte("created_at", cutoff_iso)
                .execute()
                .data
                or []
            )
            for row in lock_rows:
                cid = (row.get("company_id") or {}).get("company_id")
                if cid in company_ids_step1:
                    locked_company_ids.add(cid)
        except Exception:
            pass

    # Hot-suppressed check: companies with recent human reply/click (last 7 days)
    all_company_ids = {d["company_id"] for d in drafts if d.get("company_id")}
    hot_company_ids: set[str] = set()
    hot_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    if all_company_ids:
        try:
            hot_rows = (
                db_client.table("interactions")
                .select("contact_id, company_id:contacts(company_id)")
                .in_("type", ["email_replied", "email_clicked"])
                .gte("created_at", hot_cutoff)
                .execute()
                .data
                or []
            )
            for row in hot_rows:
                cid = (row.get("company_id") or {}).get("company_id")
                if cid in all_company_ids:
                    hot_company_ids.add(cid)
        except Exception:
            pass

    blocked: dict[str, int] = {}
    eligible = 0

    for d in drafts:
        contact = d.get("contact") or {}
        company = d.get("company") or {}
        email = contact.get("email", "")
        step = int(d.get("sequence_step") or 1)
        cluster = company.get("campaign_cluster") or "other"
        contact_id = d.get("contact_id", "")
        company_id = d.get("company_id", "")

        if not contact.get("is_outreach_eligible"):
            blocked["not_eligible"] = blocked.get("not_eligible", 0) + 1
        elif email in suppressed_emails:
            blocked["suppressed"] = blocked.get("suppressed", 0) + 1
        elif cluster in ("other", "watchlist"):
            blocked["bad_cluster"] = blocked.get("bad_cluster", 0) + 1
        elif step == 1 and company_id in locked_company_ids:
            blocked["company_locked"] = blocked.get("company_locked", 0) + 1
        elif company_id in hot_company_ids:
            blocked["hot_suppressed"] = blocked.get("hot_suppressed", 0) + 1
        elif step > 1 and (step - 1) not in sent_steps.get(contact_id, set()):
            blocked["prior_step_not_sent"] = blocked.get("prior_step_not_sent", 0) + 1
        else:
            eligible += 1

    return {
        "total_claimable": total_claimable,
        "eligible_count": eligible,
        "will_assert_fail": total_claimable - eligible,
        "blocked": blocked,
    }


# ---------------------------------------------------------------------------
# Public: dispatch loop
# ---------------------------------------------------------------------------


def _send_disabled_reason(db_client, workspace_id: str) -> Optional[str]:
    """Returns a reason string if sending is disabled for this workspace,
    or None if it is enabled.

    This is the single enforced boundary for send_enabled — every caller of
    dispatch_workspace() (the scheduled dispatch_loop tick AND the
    POST /api/admin/trigger-dispatch endpoint, which previously bypassed the
    check entirely) goes through this. Two independent switches are
    required, and either one being off disables sending:

      1. settings.send_enabled (the SEND_ENABLED env var). This was
         previously the only thing checked, and only by one caller
         (main.py's _dispatch_workspace), not by dispatch_workspace() itself.
      2. outreach_send_config.send_enabled (the DB column). Previously read
         nowhere on this path — the staged-activation doctrine's Emergency
         Freeze step (UPDATE outreach_send_config SET send_enabled=false)
         was a no-op prior to this change.

    Fails CLOSED: a missing row, or a row that errors on read, disables
    sending rather than defaulting to enabled. test_warm_isolation.py
    documents exactly this danger for a workspace with no config row at
    all ("send_enabled would DEFAULT TO TRUE") — fail-closed here is what
    makes seeding an explicit row the correct fix rather than a convention
    nothing enforces.
    """
    from backend.app.core.config import get_settings

    if not get_settings().send_enabled:
        return "env_send_enabled=false"

    try:
        rows = (
            db_client.table("outreach_send_config")
            .select("send_enabled")
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:
        return f"db_send_config_unreadable:{exc}"

    if not rows:
        return "db_send_config_missing"

    if not rows[0].get("send_enabled"):
        return "db_send_enabled=false"

    return None


def dispatch_workspace(
    db_client,
    workspace_id: str,
    *,
    batch_size: int = 10,
    max_retries: int = 4,
) -> BatchResult:
    """Claim and dispatch one batch of outbound_queue rows for a workspace.

    Calls claim_outbound_queue_batch() via Supabase RPC (PostgreSQL FOR UPDATE
    SKIP LOCKED), then dispatches each claimed row via
    EngagementAgent.dispatch_queued_draft().

    Returns BatchResult with per-outcome counts.
    """
    result = BatchResult()

    disabled_reason = _send_disabled_reason(db_client, workspace_id)
    if disabled_reason is not None:
        logger.info(
            "dispatch.aborted_send_disabled workspace_id=%s reason=%s",
            workspace_id,
            disabled_reason,
        )
        result.send_disabled = True
        result.send_disabled_reason = disabled_reason
        return result

    instance_id = str(uuid.uuid4())

    # Acquire the concurrency slot before making any Supabase calls.
    # Logs at DEBUG when another thread is already holding slots so pool
    # pressure is visible without being noisy in normal operation.
    if not _DISPATCH_CONCURRENCY.acquire(blocking=False):
        logger.debug(
            "dispatch.concurrency_limit_hit workspace_id=%s instance=%s — "
            "waiting for slot (max 3 simultaneous Supabase operations)",
            workspace_id,
            instance_id,
        )
        _DISPATCH_CONCURRENCY.acquire(blocking=True)

    try:
        return _dispatch_workspace_inner(
            db_client=db_client,
            workspace_id=workspace_id,
            batch_size=batch_size,
            max_retries=max_retries,
            result=result,
            instance_id=instance_id,
        )
    finally:
        _DISPATCH_CONCURRENCY.release()


def _dispatch_workspace_inner(
    db_client,
    workspace_id: str,
    batch_size: int,
    max_retries: int,
    result: BatchResult,
    instance_id: str,
) -> BatchResult:
    """Inner dispatch logic — runs with _DISPATCH_CONCURRENCY slot held."""
    from backend.app.agents.engagement import EngagementAgent

    try:
        claimed = (
            db_client.rpc(
                "claim_outbound_queue_batch",
                {
                    "p_workspace_id": workspace_id,
                    "p_instance_id": instance_id,
                    "p_batch_size": batch_size,
                },
            )
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.error(
            "dispatch.claim_batch FAILED workspace_id=%s error=%s",
            workspace_id,
            exc,
        )
        result.errors += 1
        return result

    if not claimed:
        logger.debug(
            "dispatch.claim_batch workspace_id=%s instance=%s no eligible rows",
            workspace_id,
            instance_id,
        )
        return result

    logger.info(
        "dispatch.claim_batch workspace_id=%s instance=%s claimed=%d",
        workspace_id,
        instance_id,
        len(claimed),
    )

    agent = EngagementAgent(workspace_id=workspace_id)

    for queue_row in claimed:
        draft_id = queue_row["draft_id"]
        queue_row_id = queue_row["id"]
        retry_count = queue_row.get("retry_count", 0)
        attempt_number = _next_attempt_number(db_client, draft_id)
        # Stable idempotency key: keyed on draft_id only (not attempt_number) so
        # Resend's 24-hour dedup window covers all retry attempts for the same draft.
        # A per-attempt key would generate a new key on every retry, defeating dedup
        # and emailing the prospect twice when a send times out then retries.
        idempotency_key = draft_id

        result.dispatched += 1

        # Invariant: send_attempts row MUST exist before Resend is called.
        attempt_id = _insert_send_attempt(
            db_client,
            draft_id=draft_id,
            workspace_id=workspace_id,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
        )
        if attempt_id is None:
            # Can't record the attempt — release lock and skip without incrementing
            # retry_count. This row will be picked up on the next scheduler tick.
            logger.error(
                "dispatch.send_attempt_insert_failed draft_id=%s — "
                "releasing lock, will retry on next tick",
                draft_id,
            )
            _release_queue_lock(db_client, queue_row_id)
            result.errors += 1
            result.dispatched -= 1
            continue

        try:
            outcome = agent.dispatch_queued_draft(
                queue_row=queue_row,
                attempt_number=attempt_number,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            logger.error(
                "dispatch.dispatch_queued_draft EXCEPTION draft_id=%s error=%s",
                draft_id,
                exc,
                exc_info=True,
            )
            new_retry_count = retry_count + 1
            if new_retry_count >= max_retries:
                _update_send_attempt(
                    db_client,
                    attempt_id,
                    status="PERMANENTLY_FAILED",
                    failure_code="exception",
                    failure_reason=f"max_retries_exceeded: {str(exc)[:300]}",
                    resolved_at=_now_iso(),
                )
                _mark_draft_dispatch_failed(db_client, draft_id)
                _delete_queue_row(db_client, queue_row_id)
                result.permanently_failed += 1
            else:
                _update_send_attempt(
                    db_client,
                    attempt_id,
                    status="FAILED",
                    failure_code="exception",
                    failure_reason=str(exc)[:500],
                    resolved_at=_now_iso(),
                )
                _schedule_retry(db_client, queue_row, new_retry_count)
                result.transient_failed += 1
            continue

        if outcome.status == "DELIVERED":
            _update_send_attempt(
                db_client,
                attempt_id,
                status="DELIVERED",
                provider_message_id=outcome.provider_message_id,
                resolved_at=_now_iso(),
            )
            _delete_queue_row(db_client, queue_row_id)
            result.delivered += 1

        elif outcome.status == "ASSERTION_FAILED":
            _failure_reason = (outcome.failure_reason or "pre-send assertion blocked")[:500]
            _is_permanent = _is_permanent_assertion_failure(_failure_reason)
            _is_company_locked = _failure_reason.startswith("company_locked:")
            _is_hot_suppressed = _failure_reason.startswith("hot_suppressed:")
            _is_prior_step = _failure_reason.startswith("prior_step_sent:")
            _is_step_gap = _failure_reason.startswith("minimum_step_gap:")
            _is_compliance_config_error = _failure_reason.startswith("compliance_config_error:")

            _update_send_attempt(
                db_client,
                attempt_id,
                status="PERMANENTLY_FAILED" if _is_permanent else "FAILED",
                failure_code=_classify_assertion_failure_code(_failure_reason),
                failure_reason=_failure_reason,
                resolved_at=_now_iso(),
            )

            if _is_permanent:
                _mark_draft_dispatch_failed(db_client, draft_id)
                _delete_queue_row(db_client, queue_row_id)
                result.permanently_failed += 1
                logger.warning(
                    "dispatch.assertion_permanent draft_id=%s reason=%s — dead-lettered",
                    draft_id, _failure_reason[:80],
                )
            elif _is_company_locked:
                # Park for 8 days — past the 5-business-day company lock window.
                # Do NOT bump retry_count; the row is valid, just temporarily blocked.
                _set_queue_next_retry(db_client, queue_row_id, delay_seconds=8 * 86400)
                result.assertion_skipped += 1
            elif _is_hot_suppressed:
                # Re-check after 24 h — engagement signal may clear.
                _set_queue_next_retry(db_client, queue_row_id, delay_seconds=86400)
                result.assertion_skipped += 1
            elif _is_prior_step:
                # Prior step may be in-flight; retry in 6 h.
                _set_queue_next_retry(db_client, queue_row_id, delay_seconds=6 * 3600)
                result.assertion_skipped += 1
            elif _is_step_gap:
                # Post-review fix: minimum_step_gap previously fell to the
                # generic `else` below — no delay, re-claimed on the very
                # next 30-minute dispatch tick, writing a fresh send_attempts
                # row each time. Observed gaps are 2-5 days
                # ("minimum gap is 2d"/"5d" in the failure_reason text); a
                # flat 24h re-check (matching hot_suppressed's cadence) cuts
                # re-fire frequency by ~48x for a typical 2-day gap, without
                # parsing the gap duration out of a log-style string.
                _set_queue_next_retry(db_client, queue_row_id, delay_seconds=86400)
                result.assertion_skipped += 1
            elif _is_compliance_config_error:
                # Post-review fix: a missing physical_address or
                # backend_public_url (see unsubscribe.py) is a GLOBAL,
                # temporary misconfiguration — every draft in every workspace
                # hits this simultaneously. It must NOT be routed through
                # _is_permanent_assertion_failure() / dead-lettered: deleting
                # every blocked queue row would lose them all once the config
                # is fixed, since nothing re-enqueues a deleted row
                # automatically. 1h re-check balances "resume quickly once
                # fixed" against not hammering every workspace's full queue
                # every 30 minutes while broken. The startup warning in
                # main.py's lifespan() is the primary discovery mechanism;
                # this is the fallback for whoever doesn't read boot logs.
                _set_queue_next_retry(db_client, queue_row_id, delay_seconds=3600)
                _maybe_alert_compliance_config_missing(_failure_reason)
                result.assertion_skipped += 1
            else:
                _release_queue_lock_bump_retry(db_client, queue_row_id, retry_count)
                result.assertion_skipped += 1

        elif outcome.status == "TRANSIENT_FAILED":
            new_retry_count = retry_count + 1
            if new_retry_count >= max_retries:
                _update_send_attempt(
                    db_client,
                    attempt_id,
                    status="PERMANENTLY_FAILED",
                    failure_code=outcome.failure_code,
                    failure_reason=f"max_retries_exceeded: {outcome.failure_reason}",
                    resolved_at=_now_iso(),
                )
                _mark_draft_dispatch_failed(db_client, draft_id)
                _delete_queue_row(db_client, queue_row_id)
                logger.warning(
                    "dispatch.max_retries_exceeded draft_id=%s retry_count=%d",
                    draft_id,
                    new_retry_count,
                )
                result.permanently_failed += 1
            else:
                _update_send_attempt(
                    db_client,
                    attempt_id,
                    status="FAILED",
                    failure_code=outcome.failure_code,
                    failure_reason=outcome.failure_reason,
                    resolved_at=_now_iso(),
                )
                _schedule_retry(db_client, queue_row, new_retry_count)
                result.transient_failed += 1

        elif outcome.status == "PERMANENTLY_FAILED":
            _update_send_attempt(
                db_client,
                attempt_id,
                status="PERMANENTLY_FAILED",
                failure_code=outcome.failure_code,
                failure_reason=outcome.failure_reason,
                resolved_at=_now_iso(),
            )
            _mark_draft_dispatch_failed(db_client, draft_id)
            _delete_queue_row(db_client, queue_row_id)
            result.permanently_failed += 1

        elif outcome.status == "ALREADY_DELIVERED":
            # Pre-send claim found sent_at already set — prior attempt set the claim
            # then crashed before deleting the queue row.
            # Reconcile via resend_message_id on outreach_drafts:
            #   - Non-None:  Resend was called and accepted (Scenario C). Email delivered.
            #                Mark send_attempt DELIVERED with provider_message_id.
            #   - None:      Resend was never called (Scenario E — crash between pre-send
            #                claim and Resend call). Email NOT delivered.
            #                Mark send_attempt FAILED with code "lost_send_pre_claim_crash".
            _provider_id = _resolve_provider_message_id(db_client, draft_id)
            if _provider_id:
                logger.warning(
                    "dispatch.already_delivered_drain draft_id=%s queue_row=%s "
                    "provider_id=%s reason=%s — email was sent; draining stuck queue row",
                    draft_id,
                    queue_row_id,
                    _provider_id,
                    outcome.failure_reason,
                )
                _update_send_attempt(
                    db_client,
                    attempt_id,
                    status="DELIVERED",
                    provider_message_id=_provider_id,
                    failure_reason=f"already_delivered_drain: {outcome.failure_reason}",
                    reconciled_at=_now_iso(),
                    resolved_at=_now_iso(),
                )
            else:
                # Email was NOT sent — pre-claim survived the crash, Resend never called.
                # Mark FAILED for manual review. Do not set dispatch_failed on the draft
                # (the draft is not permanently failed — it could be re-queued if needed).
                logger.error(
                    "dispatch.lost_send draft_id=%s queue_row=%s reason=%s — "
                    "sent_at set but resend_message_id is NULL; email was never dispatched",
                    draft_id,
                    queue_row_id,
                    outcome.failure_reason,
                )
                _update_send_attempt(
                    db_client,
                    attempt_id,
                    status="FAILED",
                    failure_code="lost_send_pre_claim_crash",
                    failure_reason="sent_at_set_but_resend_never_called",
                    resolved_at=_now_iso(),
                )
            _delete_queue_row(db_client, queue_row_id)
            result.already_delivered_drained += 1

    logger.info(
        "dispatch.workspace_complete workspace_id=%s dispatched=%d delivered=%d "
        "transient_failed=%d permanently_failed=%d assertion_skipped=%d "
        "already_delivered_drained=%d errors=%d",
        workspace_id,
        result.dispatched,
        result.delivered,
        result.transient_failed,
        result.permanently_failed,
        result.assertion_skipped,
        result.already_delivered_drained,
        result.errors,
    )
    return result
