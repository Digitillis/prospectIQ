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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Exponential backoff schedule indexed by (new_retry_count - 1).
# retry 0→1: +5min, 1→2: +15min, 2→3: +1h, 3→4: +4h
_BACKOFF_SECONDS: list[int] = [300, 900, 3600, 14400]

STALE_LOCK_MINUTES: int = 5


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
        rows = db_client.table("send_attempts").insert({
            "draft_id": draft_id,
            "workspace_id": workspace_id,
            "attempt_number": attempt_number,
            "idempotency_key": idempotency_key,
            "status": "DISPATCHED",
            "dispatched_at": _now_iso(),
        }).execute().data
        if rows:
            return rows[0]["id"]
    except Exception as exc:
        logger.error(
            "dispatch.insert_send_attempt FAILED draft_id=%s attempt=%d: %s",
            draft_id, attempt_number, exc,
        )
    return None


def _update_send_attempt(db_client, attempt_id: str, **fields) -> None:
    try:
        db_client.table("send_attempts").update(fields).eq("id", attempt_id).execute()
    except Exception as exc:
        logger.error(
            "dispatch.update_send_attempt id=%s fields=%s error=%s",
            attempt_id, list(fields.keys()), exc,
        )


def _release_queue_lock(db_client, queue_row_id: str) -> None:
    try:
        db_client.table("outbound_queue").update({
            "locked_by": None,
            "locked_at": None,
        }).eq("id", queue_row_id).execute()
    except Exception as exc:
        logger.error("dispatch.release_queue_lock id=%s error=%s", queue_row_id, exc)


def _delete_queue_row(db_client, queue_row_id: str) -> None:
    try:
        db_client.table("outbound_queue").delete().eq("id", queue_row_id).execute()
    except Exception as exc:
        logger.error("dispatch.delete_queue_row id=%s error=%s", queue_row_id, exc)


def _schedule_retry(db_client, queue_row: dict, new_retry_count: int) -> None:
    delay = _backoff_for(new_retry_count - 1)
    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    try:
        db_client.table("outbound_queue").update({
            "retry_count": new_retry_count,
            "next_retry_at": retry_at,
            "locked_by": None,
            "locked_at": None,
        }).eq("id", queue_row["id"]).execute()
        logger.info(
            "dispatch.retry_scheduled draft_id=%s retry_count=%d retry_at=%s",
            queue_row["draft_id"], new_retry_count, retry_at,
        )
    except Exception as exc:
        logger.error(
            "dispatch.schedule_retry FAILED id=%s new_retry_count=%d error=%s",
            queue_row["id"], new_retry_count, exc,
        )


def _mark_draft_dispatch_failed(db_client, draft_id: str) -> None:
    try:
        db_client.table("outreach_drafts").update({
            "approval_status": "dispatch_failed",
        }).eq("id", draft_id).execute()
    except Exception as exc:
        logger.error(
            "dispatch.mark_draft_dispatch_failed draft_id=%s error=%s", draft_id, exc,
        )


# ---------------------------------------------------------------------------
# Public: stale lock reclaim
# ---------------------------------------------------------------------------

def reclaim_stale_locks(db_client, workspace_id: str) -> int:
    """Clear distributed locks held longer than STALE_LOCK_MINUTES.

    Returns the number of rows reclaimed. Logs a warning for every reclaim
    so the count is visible in structured logs.
    """
    stale_cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=STALE_LOCK_MINUTES)
    ).isoformat()
    try:
        rows = (
            db_client.table("outbound_queue")
            .update({"locked_by": None, "locked_at": None})
            .eq("workspace_id", workspace_id)
            .not_.is_("locked_at", "null")
            .lt("locked_at", stale_cutoff)
            .execute()
            .data or []
        )
        count = len(rows)
        if count:
            logger.warning(
                "dispatch.stale_lock_reclaim workspace_id=%s reclaimed=%d "
                "(locked_at < %s)",
                workspace_id, count, stale_cutoff,
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
            workspace_id, exc,
        )
        return 0


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
    from backend.app.agents.engagement import EngagementAgent

    result = BatchResult()
    instance_id = str(uuid.uuid4())

    try:
        claimed = db_client.rpc("claim_outbound_queue_batch", {
            "p_workspace_id": workspace_id,
            "p_instance_id": instance_id,
            "p_batch_size": batch_size,
        }).execute().data or []
    except Exception as exc:
        logger.error(
            "dispatch.claim_batch FAILED workspace_id=%s error=%s",
            workspace_id, exc,
        )
        result.errors += 1
        return result

    if not claimed:
        logger.debug(
            "dispatch.claim_batch workspace_id=%s instance=%s no eligible rows",
            workspace_id, instance_id,
        )
        return result

    logger.info(
        "dispatch.claim_batch workspace_id=%s instance=%s claimed=%d",
        workspace_id, instance_id, len(claimed),
    )

    agent = EngagementAgent(workspace_id=workspace_id)

    for queue_row in claimed:
        draft_id = queue_row["draft_id"]
        queue_row_id = queue_row["id"]
        retry_count = queue_row.get("retry_count", 0)
        attempt_number = retry_count + 1
        idempotency_key = f"{draft_id}:{attempt_number}"

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
                draft_id, exc, exc_info=True,
            )
            new_retry_count = retry_count + 1
            if new_retry_count >= max_retries:
                _update_send_attempt(
                    db_client, attempt_id,
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
                    db_client, attempt_id,
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
                db_client, attempt_id,
                status="DELIVERED",
                provider_message_id=outcome.provider_message_id,
                resolved_at=_now_iso(),
            )
            _delete_queue_row(db_client, queue_row_id)
            result.delivered += 1

        elif outcome.status == "ASSERTION_FAILED":
            _update_send_attempt(
                db_client, attempt_id,
                status="FAILED",
                failure_code="assertion_failed",
                failure_reason=(outcome.failure_reason or "pre-send assertion blocked")[:500],
                resolved_at=_now_iso(),
            )
            _release_queue_lock(db_client, queue_row_id)
            result.assertion_skipped += 1

        elif outcome.status == "TRANSIENT_FAILED":
            new_retry_count = retry_count + 1
            if new_retry_count >= max_retries:
                _update_send_attempt(
                    db_client, attempt_id,
                    status="PERMANENTLY_FAILED",
                    failure_code=outcome.failure_code,
                    failure_reason=f"max_retries_exceeded: {outcome.failure_reason}",
                    resolved_at=_now_iso(),
                )
                _mark_draft_dispatch_failed(db_client, draft_id)
                _delete_queue_row(db_client, queue_row_id)
                logger.warning(
                    "dispatch.max_retries_exceeded draft_id=%s retry_count=%d",
                    draft_id, new_retry_count,
                )
                result.permanently_failed += 1
            else:
                _update_send_attempt(
                    db_client, attempt_id,
                    status="FAILED",
                    failure_code=outcome.failure_code,
                    failure_reason=outcome.failure_reason,
                    resolved_at=_now_iso(),
                )
                _schedule_retry(db_client, queue_row, new_retry_count)
                result.transient_failed += 1

        elif outcome.status == "PERMANENTLY_FAILED":
            _update_send_attempt(
                db_client, attempt_id,
                status="PERMANENTLY_FAILED",
                failure_code=outcome.failure_code,
                failure_reason=outcome.failure_reason,
                resolved_at=_now_iso(),
            )
            _mark_draft_dispatch_failed(db_client, draft_id)
            _delete_queue_row(db_client, queue_row_id)
            result.permanently_failed += 1

        elif outcome.status == "ALREADY_DELIVERED":
            # Pre-send claim found sent_at already set: prior attempt crashed after the
            # claim was persisted but before the queue row was deleted. The email was
            # sent (or at minimum claimed). Mark the send_attempt DELIVERED and drain
            # the stuck queue row. D6 adds webhook reconciliation to verify the provider.
            logger.warning(
                "dispatch.already_delivered_drain draft_id=%s queue_row=%s reason=%s",
                draft_id, queue_row_id, outcome.failure_reason,
            )
            _update_send_attempt(
                db_client, attempt_id,
                status="DELIVERED",
                failure_reason=f"already_delivered_drain: {outcome.failure_reason}",
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
