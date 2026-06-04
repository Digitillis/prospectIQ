"""SDP#7: _dispatch_workspace in main.py must use db_client, not the undefined 'db'.

The NameError was introduced when _schedule_post_send_intent_refresh was called with
'db' (undefined in the function scope) instead of 'db_client'.
This test verifies the function no longer raises NameError when result.delivered > 0.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_dispatch_workspace_no_nameerror_on_delivered():
    """_dispatch_workspace must not raise NameError when result.delivered > 0."""
    from backend.app.api.main import _dispatch_workspace

    ws = {"id": "ws-1", "name": "Test Workspace"}

    # Mock all dependencies
    mock_settings = MagicMock()
    mock_settings.send_enabled = True

    mock_result = MagicMock()
    mock_result.dispatched = 1
    mock_result.delivered = 1  # triggers the post-send path with db/db_client
    mock_result.transient_failed = 0
    mock_result.permanently_failed = 0
    mock_result.assertion_skipped = 0
    mock_result.already_delivered_drained = 0
    mock_result.errors = 0

    with patch("backend.app.core.config.get_settings", return_value=mock_settings), \
         patch("backend.app.core.dispatch_scheduler.dispatch_workspace", return_value=mock_result), \
         patch("backend.app.core.database.get_supabase_client", return_value=MagicMock()), \
         patch("backend.app.api.main._schedule_pipeline_advance"), \
         patch("backend.app.api.main._schedule_post_send_intent_refresh") as mock_refresh:

        # Must not raise NameError
        try:
            _dispatch_workspace(ws)
        except NameError as e:
            pytest.fail(f"_dispatch_workspace raised NameError: {e}")

        # _schedule_post_send_intent_refresh should be called with db_client, not undefined 'db'
        # (If it was called with `db` it would have raised NameError above)
        mock_refresh.assert_called_once()
        call_args = mock_refresh.call_args
        # First positional arg is workspace_id, second is the db client
        assert call_args[0][0] == "ws-1", "First arg must be workspace_id"
        # Second arg must not be None (would be if 'db' was undefined and swallowed)
        assert call_args[0][1] is not None, "db_client arg must not be None"
