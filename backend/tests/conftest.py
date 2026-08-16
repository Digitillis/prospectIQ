"""Shared pytest fixtures for backend/tests.

No conftest.py existed here before this file. It exists to reconcile two
things that were previously independent and are now coupled:

  1. CI sets SEND_ENABLED=false for the entire pytest run
     (.github/workflows/ci.yml) as a safety net so no real send path can
     execute during tests, even if some individual test's mocking is
     imperfect.
  2. dispatch_workspace() (backend/app/core/dispatch_scheduler.py) now
     checks send_enabled — env AND DB — as its first action, so that
     POST /api/admin/trigger-dispatch (which calls dispatch_workspace()
     directly, bypassing main.py's separate env check) can no longer send
     while disabled either. See _send_disabled_reason().

Most existing dispatch-scheduler unit tests exercise queue-claim, retry,
and outcome-classification logic with EngagementAgent (and therefore Resend)
already mocked out — they were written before the send_disabled gate
existed and don't set up outreach_send_config mock data. Under (1), those
tests would now abort at the gate before reaching the logic under test.

This fixture defaults the gate to "enabled" for every test, so existing
tests keep exercising the logic they were written for. Tests that
specifically verify the disabled path (e.g. the send_disabled tests added
alongside the gate itself) override this within the test body by
re-entering `patch(".. ._send_disabled_reason", ...)`, which takes
precedence for the duration of the `with` block.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _dispatch_send_enabled_by_default():
    with patch(
        "backend.app.core.dispatch_scheduler._send_disabled_reason",
        return_value=None,
    ):
        yield
