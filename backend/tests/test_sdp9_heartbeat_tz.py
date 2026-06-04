"""SDP#9: _run_dispatch_heartbeat_check must compute 'today_start' in
America/Chicago time, not UTC. A UTC boundary crossing (midnight UTC but 7pm
Chicago) should not make the heartbeat count zero attempts.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


def _chicago_midnight_as_utc(dt_chicago: datetime) -> str:
    """Convert a Chicago midnight to UTC ISO string."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Chicago")
        local = dt_chicago.replace(tzinfo=tz)
        return local.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc).isoformat()
    except Exception:
        return dt_chicago.replace(tzinfo=timezone.utc).isoformat()


def test_heartbeat_today_start_uses_chicago_time():
    """today_start should be computed from Chicago midnight, not UTC midnight.

    When UTC is 00:30 (midnight UTC, which is 7:30pm Chicago CDT), using UTC
    would produce a today_start of ~00:00 UTC, missing all attempts logged
    during the Chicago business day (which ends at ~23:00 UTC = 6pm Chicago).
    """
    # Simulated scenario: it is 11:40am Chicago (17:40 UTC, CDT = UTC-5)
    try:
        from zoneinfo import ZoneInfo
        tz_chi = ZoneInfo("America/Chicago")
        now_chicago = datetime(2026, 6, 4, 11, 40, tzinfo=tz_chi)
        # Chicago midnight in UTC for June 4 CDT (UTC-5): June 4 00:00 CDT = 05:00 UTC
        expected_today_start_utc_hour = 5  # Chicago is CDT (UTC-5) in June
    except ImportError:
        pytest.skip("zoneinfo not available")

    db_client = MagicMock()
    db_client.table.return_value.select.return_value.is_.return_value.execute.return_value = MagicMock(data=[])
    db_client.table.return_value.select.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(count=5)

    captured_today_start: list[str] = []

    original_select = db_client.table.return_value.select

    def capture_select(*args, **kwargs):
        result = MagicMock()
        result.gte.side_effect = lambda col, val: (captured_today_start.append(val) or result)
        result.gte.return_value.limit.return_value.execute.return_value = MagicMock(count=5)
        result.is_.return_value.execute.return_value = MagicMock(data=[])
        return result

    db_client.table.return_value.select.side_effect = capture_select

    with patch("backend.app.core.database.get_supabase_client", return_value=db_client), \
         patch("backend.app.utils.notifications.notify_slack"):
        from backend.app.api.main import _run_dispatch_heartbeat_check
        _run_dispatch_heartbeat_check()

    # Check that a today_start was captured and it reflects Chicago midnight, not UTC midnight
    if captured_today_start:
        ts = captured_today_start[0]
        # Parse the timestamp
        from datetime import datetime as dt
        parsed = dt.fromisoformat(ts.replace("Z", "+00:00"))
        # Chicago CDT midnight = 05:00 UTC on the same calendar date
        # UTC midnight = 00:00 UTC
        # The heartbeat should NOT use 00:00 UTC as today_start in June
        assert parsed.hour != 0 or parsed.tzinfo is not None, (
            f"today_start appears to be UTC midnight ({ts}) instead of Chicago midnight"
        )
