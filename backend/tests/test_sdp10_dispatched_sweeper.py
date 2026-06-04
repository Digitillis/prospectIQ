"""SDP#10: _run_dispatched_sweeper must mark DISPATCHED send_attempts older
than 30 minutes as PERMANENTLY_FAILED to prevent accounting drift.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_sweeper_marks_old_dispatched_as_permanently_failed():
    """DISPATCHED rows older than 30 min must be updated to PERMANENTLY_FAILED."""
    from backend.app.api.main import _run_dispatched_sweeper

    db_client = MagicMock()
    update_chain = MagicMock()
    db_client.table.return_value.update.return_value = update_chain
    update_chain.eq.return_value = update_chain
    update_chain.lt.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[{"id": "attempt-1"}, {"id": "attempt-2"}])

    with patch("backend.app.core.database.get_supabase_client", return_value=db_client):
        _run_dispatched_sweeper()

    # Must have called update on send_attempts
    db_client.table.assert_any_call("send_attempts")
    update_args = db_client.table.return_value.update.call_args
    assert update_args is not None, "update() was never called on send_attempts"

    update_data = update_args[0][0]
    assert update_data["status"] == "PERMANENTLY_FAILED", (
        f"Expected PERMANENTLY_FAILED, got {update_data.get('status')}"
    )
    assert update_data.get("failure_code") == "orphan_dispatched"


def test_sweeper_queries_only_dispatched_status():
    """Sweeper must only touch DISPATCHED rows, not DELIVERED or FAILED."""
    from backend.app.api.main import _run_dispatched_sweeper

    db_client = MagicMock()
    update_chain = MagicMock()
    db_client.table.return_value.update.return_value = update_chain
    update_chain.eq.return_value = update_chain
    update_chain.lt.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[])

    eq_calls: list = []

    def capture_eq(*args, **kwargs):
        eq_calls.append(args)
        return update_chain

    update_chain.eq.side_effect = capture_eq

    with patch("backend.app.core.database.get_supabase_client", return_value=db_client):
        _run_dispatched_sweeper()

    status_filters = [c[1] for c in eq_calls if c[0] == "status"]
    assert "DISPATCHED" in status_filters, "Sweeper must filter on status='DISPATCHED'"


def test_sweeper_logs_warning_when_rows_found(caplog):
    """When orphan rows are found, a warning must be logged."""
    import logging
    from backend.app.api.main import _run_dispatched_sweeper

    db_client = MagicMock()
    update_chain = MagicMock()
    db_client.table.return_value.update.return_value = update_chain
    update_chain.eq.return_value = update_chain
    update_chain.lt.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[{"id": "a1"}, {"id": "a2"}])

    with (
        patch("backend.app.core.database.get_supabase_client", return_value=db_client),
        caplog.at_level(logging.WARNING, logger="backend.app.api.main"),
    ):
        _run_dispatched_sweeper()

    assert any(
        "orphan" in r.message.lower() or "DISPATCHED" in r.message for r in caplog.records
    ), "Expected a warning log when orphan DISPATCHED rows are found"
