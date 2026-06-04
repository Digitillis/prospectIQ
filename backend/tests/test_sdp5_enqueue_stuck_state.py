"""SDP#5: enqueue_todays_schedule must use an atomic approve+enqueue operation.
The old 3-step non-transactional path left drafts approved-but-unqueued when
the queue insert failed. The fix uses the approve_draft_and_enqueue RPC.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call, patch


def _mock_db_with_schedule(draft_ids: list[str], workspace_id: str = "ws-1"):
    """Return a mock Database with pre-loaded send_schedule rows for today."""
    from datetime import date

    today_str = date.today().isoformat()

    db = MagicMock()
    db.workspace_id = workspace_id

    schedule_rows = [
        {"id": f"ss-{i}", "draft_id": d, "sequence_step": 1, "slot_order": i}
        for i, d in enumerate(draft_ids)
    ]
    # Chain: db.client.table("send_schedule").select(...).eq(...).eq(...).eq(...).order(...).execute().data
    mock_select = MagicMock()
    mock_select.eq.return_value = mock_select
    mock_select.order.return_value = mock_select
    mock_select.execute.return_value = MagicMock(data=schedule_rows)

    db.client.table.return_value.select.return_value = mock_select

    # Config lookup
    db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"default_reviewer_id": "rev-123"}]
    )

    return db


def test_enqueue_uses_rpc_not_3_step():
    """enqueue_todays_schedule must call approve_draft_and_enqueue RPC, not 3 separate writes."""
    from backend.app.core.send_scheduler import enqueue_todays_schedule
    from datetime import date

    today = date.today()
    db = MagicMock()
    db.workspace_id = "ws-1"

    # send_schedule lookup
    schedule_rows = [{"id": "ss-1", "draft_id": "draft-1", "sequence_step": 1, "slot_order": 0}]

    # Make all table() calls go through a single chain mock to track calls
    rpc_calls: list[dict] = []

    def mock_rpc(name, params):
        rpc_calls.append({"name": name, "params": params})
        mock = MagicMock()
        mock.execute.return_value = MagicMock(data=[{"id": "draft-1"}])
        return mock

    db.client.rpc.side_effect = mock_rpc

    # Build a chain that returns schedule_rows for the send_schedule query
    mock_table_chain = MagicMock()
    mock_table_chain.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=schedule_rows)
    # For the outreach_send_config query
    mock_table_chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{}])
    # For send_schedule status update
    mock_table_chain.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    db.client.table.return_value = mock_table_chain

    enqueue_todays_schedule(db, "ws-1", today=today)

    # The RPC must have been called
    rpc_names = [c["name"] for c in rpc_calls]
    assert "approve_draft_and_enqueue" in rpc_names, (
        f"Expected approve_draft_and_enqueue RPC call, got: {rpc_names}"
    )

    # The RPC call must include the correct params
    rpc_call = next(c for c in rpc_calls if c["name"] == "approve_draft_and_enqueue")
    assert rpc_call["params"]["p_draft_id"] == "draft-1"
    assert rpc_call["params"]["p_status"] == "approved"


def test_enqueue_does_not_use_3_step_inserts():
    """Ensure the old 3-step pattern (update → insert → update) is not used."""
    from backend.app.core.send_scheduler import enqueue_todays_schedule
    from datetime import date

    today = date.today()
    db = MagicMock()
    db.workspace_id = "ws-1"

    schedule_rows = [{"id": "ss-1", "draft_id": "draft-1", "sequence_step": 1, "slot_order": 0}]

    update_calls: list[str] = []
    insert_calls: list[str] = []

    def mock_table(name):
        mock = MagicMock()
        if name == "outreach_drafts":
            # Track update calls to outreach_drafts
            def track_update(*a, **kw):
                update_calls.append("outreach_drafts.update")
                return MagicMock()
            mock.update.side_effect = track_update
        elif name == "outbound_queue":
            def track_insert(*a, **kw):
                insert_calls.append("outbound_queue.insert")
                return MagicMock()
            mock.insert.side_effect = track_insert
        elif name == "send_schedule":
            mock.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=schedule_rows)
            mock.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        elif name == "outreach_send_config":
            mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{}])
        return mock

    db.client.table.side_effect = mock_table
    db.client.rpc.return_value.execute.return_value = MagicMock(data=[{"id": "draft-1"}])

    enqueue_todays_schedule(db, "ws-1", today=today)

    # Old 3-step: separate outreach_drafts.update + outbound_queue.insert
    # New: single RPC call — outreach_drafts.update must NOT be called directly
    assert "outreach_drafts.update" not in update_calls, (
        "outreach_drafts was updated directly — still using old 3-step pattern instead of RPC"
    )
    assert "outbound_queue.insert" not in insert_calls, (
        "outbound_queue was inserted directly — still using old 3-step pattern instead of RPC"
    )
