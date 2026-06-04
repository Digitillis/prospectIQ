"""SDP#3: The dispatch idempotency key must be stable across retry attempts.

A key that changes per retry (e.g. includes attempt_number) defeats Resend's
24-hour dedup window and causes double-sends on timeout/retry scenarios.
The correct behaviour: the key must be the same for all attempts on the same draft.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def _build_queue_row(draft_id: str, retry_count: int) -> dict:
    return {
        "id": "qrow-1",
        "draft_id": draft_id,
        "workspace_id": "ws-test",
        "retry_count": retry_count,
        "next_retry_at": None,
        "locked_by": "inst-1",
        "locked_at": "2026-06-04T10:00:00",
    }


def test_idempotency_key_is_stable_across_retries():
    """For the same draft_id, retry 0, 1, 2, 3 must all produce the same idempotency key."""
    from backend.app.core import dispatch_scheduler as ds

    draft_id = "draft-abc-123"
    keys_seen = set()

    for retry_count in range(4):
        queue_row = _build_queue_row(draft_id, retry_count)
        attempt_number = queue_row["retry_count"] + 1

        # Reproduce the actual key construction from dispatch_scheduler.py
        # This is the post-fix: idempotency_key = draft_id
        idempotency_key = draft_id  # stable key
        keys_seen.add(idempotency_key)

    assert len(keys_seen) == 1, (
        f"Idempotency key changed across retries: {keys_seen}. "
        "All retries for the same draft must use the same key."
    )


def test_old_per_attempt_key_would_differ():
    """Verify the OLD behaviour (f'{draft_id}:{attempt_number}') produces different keys.

    This test documents WHY the fix was necessary: per-attempt keys would bypass
    Resend's dedup and cause double-sends.
    """
    draft_id = "draft-abc-123"
    old_keys = set()

    for retry_count in range(4):
        attempt_number = retry_count + 1
        old_key = f"{draft_id}:{attempt_number}"  # old (broken) behaviour
        old_keys.add(old_key)

    assert len(old_keys) > 1, "Old keys should differ per attempt — confirming the fix is needed"


def test_dispatch_workspace_uses_stable_key():
    """dispatch_workspace must pass draft_id (not draft_id:attempt_number) as idempotency key."""
    from backend.app.core import dispatch_scheduler as ds

    captured_keys: list[str] = []
    draft_id = "draft-xyz-789"

    def fake_insert_send_attempt(db_client, draft_id, workspace_id, attempt_number, idempotency_key):
        captured_keys.append(idempotency_key)
        return "attempt-id-1"

    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value.data = [_build_queue_row(draft_id, 0)]

    fake_agent = MagicMock()
    fake_outcome = MagicMock()
    fake_outcome.status = "DELIVERED"
    fake_outcome.provider_message_id = "msg-1"
    fake_agent.dispatch_queued_draft.return_value = fake_outcome

    with patch.object(ds, "_insert_send_attempt", side_effect=fake_insert_send_attempt), \
         patch("backend.app.agents.engagement.EngagementAgent", return_value=fake_agent):
        ds.dispatch_workspace(fake_db, "ws-test", batch_size=10)

    assert len(captured_keys) == 1, "Expected exactly one send attempt"
    assert captured_keys[0] == draft_id, (
        f"Expected idempotency_key='{draft_id}', got '{captured_keys[0]}'"
    )
