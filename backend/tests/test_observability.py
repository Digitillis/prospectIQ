"""Observability foundation tests.

Verifies the pipeline_run_log instrumentation in send_scheduler writes a
best-effort audit row at the two filter/transform points, and that a failure
to write the log row never breaks the pipeline.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.app.core.send_scheduler import enqueue_todays_schedule
import backend.app.core.send_scheduler as ss


def test_enqueue_writes_pipeline_run_log_row(monkeypatch):
    """enqueue_todays_schedule must record a pipeline_run_log row with due/enqueued counts."""
    captured: list[dict] = []

    db = MagicMock()

    # Acquire lock succeeds
    monkeypatch.setattr(ss, "_try_acquire_advisory_lock", lambda *a, **k: True)
    monkeypatch.setattr(ss, "_release_advisory_lock", lambda *a, **k: None)

    # send_schedule "due" query returns two rows
    due_rows = [
        {"id": "ss1", "draft_id": "d1", "sequence_step": 1, "slot_order": 0},
        {"id": "ss2", "draft_id": "d2", "sequence_step": 2, "slot_order": 1},
    ]

    def table_router(name: str):
        tbl = MagicMock()
        if name == "pipeline_run_log":

            def capture_insert(payload):
                captured.append(payload)
                m = MagicMock()
                m.execute.return_value = MagicMock(data=[payload])
                return m

            tbl.insert.side_effect = capture_insert
        elif name == "send_schedule":
            # select(...).eq().eq().eq().order().execute().data -> due_rows
            chain = MagicMock()
            chain.eq.return_value = chain
            chain.order.return_value = chain
            chain.execute.return_value = MagicMock(data=due_rows)
            tbl.select.return_value = chain
            # update(...).eq().execute()
            upd = MagicMock()
            upd.eq.return_value = upd
            upd.execute.return_value = MagicMock(data=[])
            tbl.update.return_value = upd
        elif name == "outreach_send_config":
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=[{"default_reviewer_id": "rev-1"}])
            tbl.select.return_value = chain
        return tbl

    db.client.table.side_effect = table_router
    # RPC for approve_draft_and_enqueue succeeds for both
    db.client.rpc.return_value.execute.return_value = MagicMock(data=[{"id": "d1"}])

    result = enqueue_todays_schedule(db, "ws-1", today=date(2026, 6, 4))

    assert result["due"] == 2
    assert result["enqueued"] == 2

    log_rows = [c for c in captured if c.get("stage") == "enqueue_todays_schedule"]
    assert log_rows, "no pipeline_run_log row written for enqueue stage"
    row = log_rows[0]
    assert row["input_count"] == 2
    assert row["output_count"] == 2
    assert row["filtered_count"] == 0
    assert row["workspace_id"] == "ws-1"


def test_pipeline_run_log_failure_does_not_break_enqueue(monkeypatch):
    """A pipeline_run_log insert failure must never break the pipeline."""
    db = MagicMock()
    monkeypatch.setattr(ss, "_try_acquire_advisory_lock", lambda *a, **k: True)
    monkeypatch.setattr(ss, "_release_advisory_lock", lambda *a, **k: None)

    due_rows = [{"id": "ss1", "draft_id": "d1", "sequence_step": 1, "slot_order": 0}]

    def table_router(name: str):
        tbl = MagicMock()
        if name == "pipeline_run_log":
            # Insert raises — must be swallowed
            tbl.insert.side_effect = RuntimeError("log table unavailable")
        elif name == "send_schedule":
            chain = MagicMock()
            chain.eq.return_value = chain
            chain.order.return_value = chain
            chain.execute.return_value = MagicMock(data=due_rows)
            tbl.select.return_value = chain
            upd = MagicMock()
            upd.eq.return_value = upd
            upd.execute.return_value = MagicMock(data=[])
            tbl.update.return_value = upd
        elif name == "outreach_send_config":
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=[{}])
            tbl.select.return_value = chain
        return tbl

    db.client.table.side_effect = table_router
    db.client.rpc.return_value.execute.return_value = MagicMock(data=[{"id": "d1"}])

    # Must not raise despite the log insert failing
    result = enqueue_todays_schedule(db, "ws-1", today=date(2026, 6, 4))
    assert result["enqueued"] == 1
