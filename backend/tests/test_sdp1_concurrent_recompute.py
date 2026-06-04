"""SDP#1: recompute_and_persist and enqueue_todays_schedule must acquire a
Postgres advisory lock before mutating the schedule. A process that cannot
acquire the lock must skip and log — not corrupt the schedule.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call


def test_recompute_skips_when_lock_unavailable():
    """When pg_try_advisory_lock returns False, recompute must skip and return skipped=True."""
    from backend.app.core.send_scheduler import recompute_and_persist

    db = MagicMock()
    db.workspace_id = "ws-1"

    with patch("backend.app.core.send_scheduler._try_acquire_advisory_lock", return_value=False):
        result = recompute_and_persist(db, "ws-1")

    assert result.get("persisted") is False, "Lock-skip must not persist"
    assert result.get("skipped") is True, "Result must signal skipped=True"
    assert result.get("reason") == "advisory_lock_held"

    # Must not have touched any DB tables
    db.client.table.assert_not_called()


def test_recompute_proceeds_when_lock_acquired():
    """When pg_try_advisory_lock returns True, recompute must proceed normally."""
    from backend.app.core.send_scheduler import recompute_and_persist, _load_state, compute_schedule

    db = MagicMock()
    db.workspace_id = "ws-1"

    # Mock _load_state to return empty state (no contacts)
    with patch("backend.app.core.send_scheduler._try_acquire_advisory_lock", return_value=True), \
         patch("backend.app.core.send_scheduler._release_advisory_lock"), \
         patch("backend.app.core.send_scheduler._load_state", return_value=([], {}, ["avi@digitillis.io"], 270)):

        db.client.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        result = recompute_and_persist(db, "ws-1")

    # Should have proceeded (not skipped)
    assert result.get("skipped") is not True, "Should not be skipped when lock acquired"
    assert "persisted" in result


def test_recompute_releases_lock_after_completion():
    """Advisory lock must be released even if recompute aborts due to violations."""
    from backend.app.core.send_scheduler import recompute_and_persist

    db = MagicMock()
    db.workspace_id = "ws-1"

    release_called = []

    def mock_release(db_arg, key):
        release_called.append(key)

    with patch("backend.app.core.send_scheduler._try_acquire_advisory_lock", return_value=True), \
         patch("backend.app.core.send_scheduler._release_advisory_lock", side_effect=mock_release), \
         patch("backend.app.core.send_scheduler._load_state", return_value=([], {}, ["avi@digitillis.io"], 270)):

        db.client.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        recompute_and_persist(db, "ws-1")

    assert len(release_called) >= 1, "Advisory lock must be released after recompute"


def test_enqueue_skips_when_lock_unavailable():
    """When pg_try_advisory_lock returns False for enqueue, it must skip and return skipped=True."""
    from backend.app.core.send_scheduler import enqueue_todays_schedule
    from datetime import date

    db = MagicMock()
    db.workspace_id = "ws-1"

    with patch("backend.app.core.send_scheduler._try_acquire_advisory_lock", return_value=False):
        result = enqueue_todays_schedule(db, "ws-1", today=date.today())

    assert result.get("skipped") is True
    assert result.get("enqueued") == 0
    db.client.table.assert_not_called()


def test_enqueue_releases_lock_after_completion():
    """Advisory lock for enqueue must be released after the function completes."""
    from backend.app.core.send_scheduler import enqueue_todays_schedule
    from datetime import date

    db = MagicMock()
    db.workspace_id = "ws-1"
    today = date.today()

    release_called = []

    def mock_release(db_arg, key):
        release_called.append(key)

    # Return empty schedule rows
    db.client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
    db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{}])

    with patch("backend.app.core.send_scheduler._try_acquire_advisory_lock", return_value=True), \
         patch("backend.app.core.send_scheduler._release_advisory_lock", side_effect=mock_release):

        enqueue_todays_schedule(db, "ws-1", today=today)

    assert len(release_called) >= 1, "Advisory lock must be released after enqueue"
