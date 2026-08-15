"""Tests for the send_enabled gate in dispatch_workspace() /
_send_disabled_reason() (backend/app/core/dispatch_scheduler.py).

Regression coverage for two findings from the 2026-08-15 send-path
reconciliation:

  - POST /api/admin/trigger-dispatch called dispatch_workspace() directly,
    bypassing main.py's env-only send_enabled check entirely (finding 5).
    A batch_size=100 call to that endpoint would send real email even with
    SEND_ENABLED=false, because nothing downstream checked it.
  - outreach_send_config.send_enabled (the DB column) was read nowhere on
    the live dispatch path, making the staged-activation doctrine's
    Emergency Freeze step (UPDATE outreach_send_config SET
    send_enabled=false) a no-op (finding 4).

These tests call dispatch_workspace() directly — the same entry point
trigger-dispatch uses — with no env-level wrapper, so a regression of
either finding shows up here even if main.py's own check is untouched.

Each test disables backend/tests/conftest.py's autouse
_dispatch_send_enabled_by_default fixture by re-patching
_send_disabled_reason back to the real implementation, then drives the
real gate via get_settings + a mocked outreach_send_config row.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _make_chain():
    """MagicMock where common filter methods return self (chainable)."""
    m = MagicMock()
    for attr in ("select", "eq", "limit"):
        getattr(m, attr).return_value = m
    return m


def _db_client_with_config_row(row=None, raise_on_select: Exception | None = None):
    """Build a Supabase client mock whose outreach_send_config select
    returns `row` (a single dict, or None for an empty/missing result), or
    raises `raise_on_select` if given. client.rpc is also wired so a test
    can assert whether the claim RPC was reached at all.
    """
    client = MagicMock()

    if raise_on_select is not None:
        client.table.return_value.select.side_effect = raise_on_select
    else:
        chain = _make_chain()
        chain.execute.return_value.data = [row] if row is not None else []
        client.table.return_value = chain

    rpc_result = MagicMock()
    rpc_result.data = []
    client.rpc.return_value.execute.return_value = rpc_result
    return client


# Capture the real implementation once, at collection time, before any
# test's autouse fixture (conftest.py's _dispatch_send_enabled_by_default)
# has a chance to monkeypatch the module attribute. The autouse fixture
# replaces the *module-level name*, not this already-bound function object,
# so this reference stays the true implementation for the whole file.
import backend.app.core.dispatch_scheduler as dispatch_scheduler_module  # noqa: E402

_TRUE_SEND_DISABLED_REASON = dispatch_scheduler_module._send_disabled_reason


def _with_real_gate():
    """Override conftest's autouse patch for one `with` block, restoring
    the real _send_disabled_reason so these tests exercise actual gate
    logic instead of the file-wide "always enabled" default.
    """
    return patch(
        "backend.app.core.dispatch_scheduler._send_disabled_reason",
        side_effect=_TRUE_SEND_DISABLED_REASON,
    )


class TestEnvDisabled:
    def test_env_send_enabled_false_blocks_dispatch(self):
        """SEND_ENABLED=false must block dispatch_workspace() called
        directly — the trigger-dispatch endpoint's own call path — not
        only the higher-level wrapper in main.py.
        """
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _db_client_with_config_row(row={"send_enabled": True})
        settings = MagicMock(send_enabled=False)

        with (
            _with_real_gate(),
            patch("backend.app.core.config.get_settings", return_value=settings),
        ):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.send_disabled is True
        assert result.send_disabled_reason == "env_send_enabled=false"
        assert result.dispatched == 0
        client.rpc.assert_not_called()


class TestDbDisabled:
    def test_db_send_enabled_false_blocks_even_when_env_true(self):
        """The DB column must be enforced too — this is what makes the
        staged-activation doctrine's Emergency Freeze
        (UPDATE outreach_send_config SET send_enabled=false) real instead
        of a no-op.
        """
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _db_client_with_config_row(row={"send_enabled": False})
        settings = MagicMock(send_enabled=True)

        with (
            _with_real_gate(),
            patch("backend.app.core.config.get_settings", return_value=settings),
        ):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.send_disabled is True
        assert result.send_disabled_reason == "db_send_enabled=false"
        client.rpc.assert_not_called()

    def test_missing_config_row_blocks_fail_closed(self):
        """A workspace with no outreach_send_config row at all must NOT
        default to enabled. test_warm_isolation.py documents this exact
        danger for the warm workspace; this is the enforcement that makes
        seeding an explicit row meaningful.
        """
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _db_client_with_config_row(row=None)
        settings = MagicMock(send_enabled=True)

        with (
            _with_real_gate(),
            patch("backend.app.core.config.get_settings", return_value=settings),
        ):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.send_disabled is True
        assert result.send_disabled_reason == "db_send_config_missing"
        client.rpc.assert_not_called()

    def test_config_read_error_blocks_fail_closed(self):
        """An exception reading outreach_send_config must also disable
        sending, not raise past the gate or default to enabled.
        """
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _db_client_with_config_row(raise_on_select=RuntimeError("boom"))
        settings = MagicMock(send_enabled=True)

        with (
            _with_real_gate(),
            patch("backend.app.core.config.get_settings", return_value=settings),
        ):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.send_disabled is True
        assert "db_send_config_unreadable" in result.send_disabled_reason
        client.rpc.assert_not_called()


class TestBothEnabled:
    def test_env_and_db_both_true_proceeds_to_claim(self):
        """Both switches on is the only state that reaches the claim RPC —
        the actual regression check for finding 5 (trigger-dispatch could
        previously send with SEND_ENABLED=false; now it cannot reach the
        RPC unless both gates pass).
        """
        from backend.app.core.dispatch_scheduler import dispatch_workspace

        client = _db_client_with_config_row(row={"send_enabled": True})
        settings = MagicMock(send_enabled=True)

        with (
            _with_real_gate(),
            patch("backend.app.core.config.get_settings", return_value=settings),
            patch("backend.app.agents.engagement.EngagementAgent"),
        ):
            result = dispatch_workspace(client, WORKSPACE_ID)

        assert result.send_disabled is False
        assert result.send_disabled_reason is None
        client.rpc.assert_called_once()
