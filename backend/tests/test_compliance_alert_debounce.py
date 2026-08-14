"""compliance_config_missing must alert (fallback for whoever doesn't read
boot logs — see dispatch_scheduler.py's comment on the retry-delay branch),
but must not spam: every affected draft in a batch of up to 45 hits this on
the same tick, and the tick repeats every 30 minutes while the
misconfiguration persists. _maybe_alert_compliance_config_missing debounces
to one Slack post per hour. See backend/app/core/dispatch_scheduler.py.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import backend.app.core.dispatch_scheduler as dispatch_scheduler


def setup_function(_fn):
    # Module-level debounce state — reset between tests so they don't leak.
    dispatch_scheduler._last_compliance_alert_at = None


def test_first_call_fires_alert():
    with patch("backend.app.utils.notifications.notify_slack") as mock_notify:
        dispatch_scheduler._maybe_alert_compliance_config_missing(
            "compliance_config_error: backend_public_url is not set"
        )
    mock_notify.assert_called_once()
    assert "compliance_config_missing" in mock_notify.call_args.args[0]


def test_second_call_within_cooldown_is_suppressed():
    with patch("backend.app.utils.notifications.notify_slack") as mock_notify:
        dispatch_scheduler._maybe_alert_compliance_config_missing("compliance_config_error: x")
        dispatch_scheduler._maybe_alert_compliance_config_missing("compliance_config_error: x")
        dispatch_scheduler._maybe_alert_compliance_config_missing("compliance_config_error: x")
    assert mock_notify.call_count == 1


def test_call_after_cooldown_expires_fires_again():
    with patch("backend.app.utils.notifications.notify_slack") as mock_notify:
        dispatch_scheduler._maybe_alert_compliance_config_missing("compliance_config_error: x")
        # Simulate an hour having passed by moving the recorded timestamp back.
        dispatch_scheduler._last_compliance_alert_at = datetime.now(timezone.utc) - timedelta(
            hours=2
        )
        dispatch_scheduler._maybe_alert_compliance_config_missing("compliance_config_error: x")
    assert mock_notify.call_count == 2


def test_notify_slack_exception_does_not_propagate():
    """Fire-and-forget: a Slack webhook failure must never break dispatch."""
    with patch("backend.app.utils.notifications.notify_slack", side_effect=RuntimeError("boom")):
        dispatch_scheduler._maybe_alert_compliance_config_missing("compliance_config_error: x")
    # No exception raised = pass.


def test_concurrent_calls_fire_exactly_one_alert():
    """dispatch_workspace() is called from multiple threads at once (see the
    module docstring on _compliance_alert_lock: _DISPATCH_CONCURRENCY caps at
    3, and a manual admin trigger can add a 4th). compliance_config_missing
    is global by construction, so many threads hitting this simultaneously —
    right when the misconfiguration first appears — is the normal case this
    debounce exists for, not a rare edge case. Without the lock, concurrent
    threads can all read the stale timestamp before any of them writes the
    update, each passing the cooldown check and each firing its own alert.
    """
    with patch("backend.app.utils.notifications.notify_slack") as mock_notify:
        threads = [
            threading.Thread(
                target=dispatch_scheduler._maybe_alert_compliance_config_missing,
                args=("compliance_config_error: x",),
            )
            for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert mock_notify.call_count == 1
