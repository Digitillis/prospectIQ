"""_run_dispatch_heartbeat_check must not fire a false "scheduler died" alert
when the reason zero send_attempts exist is that sending is intentionally
disabled -- not that the dispatcher silently died.

Found by adversarial review of PR #174 (re-enabling schedule_recompute,
2026-08-17): this check had no SEND_ENABLED awareness at all. Once real due
rows exist in outbound_queue (which schedule_recompute + the already-live
enqueue_schedule job would produce) and SEND_ENABLED correctly keeps
dispatch_workspace() from sending, this check's own logic ("eligible items
exist, zero send_attempts today, therefore the scheduler died") would have
been triggered every business day -- a foreseeable false alarm, not a
hypothetical one.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
OTHER_WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


def _mock_db(queue_rows: list[dict], attempt_count: int = 0) -> MagicMock:
    db = MagicMock()

    def _table(name):
        t = MagicMock()
        if name == "outbound_queue":
            t.select.return_value.is_.return_value.execute.return_value = MagicMock(data=queue_rows)
        elif name == "send_attempts":
            t.select.return_value.gte.return_value.limit.return_value.execute.return_value = (
                MagicMock(count=attempt_count)
            )
        return t

    db.table.side_effect = _table
    return db


class TestSuppressesFalseAlarmWhenSendDisabled:
    def test_no_alert_when_every_eligible_workspace_has_sending_disabled(self):
        queue_rows = [
            {"id": "q1", "workspace_id": WORKSPACE_ID, "next_retry_at": None, "locked_by": None}
        ]
        db = _mock_db(queue_rows, attempt_count=0)

        with (
            patch("backend.app.core.database.get_supabase_client", return_value=db),
            patch(
                "backend.app.core.dispatch_scheduler._send_disabled_reason",
                return_value="env_send_enabled=false",
            ),
            patch("backend.app.utils.notifications.notify_slack") as mock_slack,
        ):
            from backend.app.api.main import _run_dispatch_heartbeat_check

            _run_dispatch_heartbeat_check()

        mock_slack.assert_not_called()

    def test_alert_still_fires_when_sending_is_enabled_and_silent(self):
        """The fix must not suppress a genuine dead-scheduler signal -- a
        workspace where sending IS enabled but still has zero send_attempts
        is exactly the case this check exists to catch."""
        queue_rows = [
            {"id": "q1", "workspace_id": WORKSPACE_ID, "next_retry_at": None, "locked_by": None}
        ]
        db = _mock_db(queue_rows, attempt_count=0)

        with (
            patch("backend.app.core.database.get_supabase_client", return_value=db),
            patch(
                "backend.app.core.dispatch_scheduler._send_disabled_reason",
                return_value=None,  # sending is enabled for this workspace
            ),
            patch("backend.app.utils.notifications.notify_slack") as mock_slack,
        ):
            from backend.app.api.main import _run_dispatch_heartbeat_check

            _run_dispatch_heartbeat_check()

        mock_slack.assert_called_once()

    def test_alert_fires_if_any_eligible_workspace_has_sending_enabled(self):
        """Mixed case: one workspace disabled, one enabled. Must still alert,
        scoped correctly rather than an all-or-nothing check."""
        queue_rows = [
            {"id": "q1", "workspace_id": WORKSPACE_ID, "next_retry_at": None, "locked_by": None},
            {
                "id": "q2",
                "workspace_id": OTHER_WORKSPACE_ID,
                "next_retry_at": None,
                "locked_by": None,
            },
        ]
        db = _mock_db(queue_rows, attempt_count=0)

        def _reason(db_client, ws_id):
            return "env_send_enabled=false" if ws_id == WORKSPACE_ID else None

        with (
            patch("backend.app.core.database.get_supabase_client", return_value=db),
            patch(
                "backend.app.core.dispatch_scheduler._send_disabled_reason",
                side_effect=_reason,
            ),
            patch("backend.app.utils.notifications.notify_slack") as mock_slack,
        ):
            from backend.app.api.main import _run_dispatch_heartbeat_check

            _run_dispatch_heartbeat_check()

        mock_slack.assert_called_once()

    def test_no_alert_when_send_attempts_exist_regardless_of_send_enabled(self):
        """Sanity: the original, unrelated success path must be unaffected --
        real send_attempts today means no alert, independent of this fix."""
        queue_rows = [
            {"id": "q1", "workspace_id": WORKSPACE_ID, "next_retry_at": None, "locked_by": None}
        ]
        db = _mock_db(queue_rows, attempt_count=3)

        with (
            patch("backend.app.core.database.get_supabase_client", return_value=db),
            patch(
                "backend.app.core.dispatch_scheduler._send_disabled_reason",
                return_value=None,
            ),
            patch("backend.app.utils.notifications.notify_slack") as mock_slack,
        ):
            from backend.app.api.main import _run_dispatch_heartbeat_check

            _run_dispatch_heartbeat_check()

        mock_slack.assert_not_called()
