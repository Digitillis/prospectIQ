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


@dataclass
class BatchResult:
    dispatched: int = 0
    delivered: int = 0
    transient_failed: int = 0
    permanently_failed: int = 0
    assertion_skipped: int = 0
    already_delivered_drained: int = 0
    errors: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_for(retry_count: int) -> int:
    """Return backoff seconds for transitioning from retry_count to retry_count+1."""
    idx = min(retry_count, len(_BACKOFF_SECONDS) - 1)
    return _BACKOFF_SECONDS[idx]


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
        attempt_number = retry_count + 1
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

            # Classify assertion by self-resolution potential:
            #   permanent  — will never resolve; dead-letter immediately
            #   timed      — resolves after a known delay; set next_retry_at, don't burn retry_count
            #   transient  — resolves soon (prior step in-flight); short backoff
            _is_permanent = any(_failure_reason.startswith(p) for p in (
                "cluster_routing_skip:",
                "outreach_eligible:",   # tier/eligibility flag — won't flip automatically
                "suppressed:",          # suppression list — manual removal only
                "contact_has_no_email",
                "contact_fetch_failed",
            ))
            _is_company_locked = _failure_reason.startswith("company_locked:")
            _is_hot_suppressed = _failure_reason.startswith("hot_suppressed:")
            _is_prior_step = _failure_reason.startswith("prior_step_sent:")

            _update_send_attempt(
                db_client,
                attempt_id,
                status="PERMANENTLY_FAILED" if _is_permanent else "FAILED",
                failure_code=(
                    "cluster_routing_skip" if _failure_reason.startswith("cluster_routing_skip:")
                    else "assertion_failed"
                ),
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
