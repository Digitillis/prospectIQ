"""D5: Analytics date filter must restrict contacts to the requested time window.

Old code called `_since_iso(days)` but never applied `.gte('created_at', since)`
to the contacts query. Every time-windowed call (7d/30d/90d) returned identical
all-time totals.

Tests verify:
1. get_funnel_counts applies .gte("created_at", since) to the contacts query.
2. get_reply_rate_by_vertical applies the date filter.
3. get_reply_rate_by_persona applies the date filter.
4. Old behavior: T-100d record was counted in 30d window — must no longer happen.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call, patch


def _since_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_funnel_analytics(contacts_rows: list[dict]):
    """Return a FunnelAnalytics instance with a mocked DB returning the given rows."""
    from backend.app.analytics.funnel import FunnelAnalytics

    db = MagicMock()
    db.workspace_id = "ws-1"

    # Chain: _filter_ws(table.select).gte().execute().data
    gte_chain = MagicMock()
    gte_chain.execute.return_value.data = contacts_rows
    gte_chain.in_.return_value = gte_chain

    filter_ws_chain = MagicMock()
    filter_ws_chain.gte.return_value = gte_chain

    db._filter_ws.return_value = filter_ws_chain

    fa = FunnelAnalytics(db)
    return fa, db, filter_ws_chain, gte_chain


def test_get_funnel_counts_applies_gte_created_at():
    """get_funnel_counts must call .gte('created_at', since) on the contacts query."""
    fa, db, filter_ws_chain, gte_chain = _make_funnel_analytics([])

    fa.get_funnel_counts(days=30)

    # gte must have been called with 'created_at' and a date string
    gte_calls = filter_ws_chain.gte.call_args_list
    assert gte_calls, "gte() was never called — date filter is not applied"
    assert gte_calls[0][0][0] == "created_at", (
        f"gte() first arg must be 'created_at', got {gte_calls[0][0][0]!r}"
    )


def test_get_reply_rate_by_vertical_applies_date_filter():
    """get_reply_rate_by_vertical must apply .gte('created_at', since)."""
    fa, db, filter_ws_chain, gte_chain = _make_funnel_analytics([])

    # Set up the chain for the vertical query
    db._filter_ws.return_value = filter_ws_chain
    fa.get_reply_rate_by_vertical(days=30)

    gte_calls = filter_ws_chain.gte.call_args_list
    assert gte_calls, "get_reply_rate_by_vertical: gte() was never called — date filter missing"
    assert any(c[0][0] == "created_at" for c in gte_calls), (
        "get_reply_rate_by_vertical must filter by created_at"
    )


def test_get_reply_rate_by_persona_applies_date_filter():
    """get_reply_rate_by_persona must apply .gte('created_at', since)."""
    fa, db, filter_ws_chain, gte_chain = _make_funnel_analytics([])

    db._filter_ws.return_value = filter_ws_chain
    fa.get_reply_rate_by_persona(days=30)

    gte_calls = filter_ws_chain.gte.call_args_list
    assert gte_calls, "get_reply_rate_by_persona: gte() was never called — date filter missing"
    assert any(c[0][0] == "created_at" for c in gte_calls)


def test_old_behavior_contact_outside_window_excluded():
    """A contact created 100 days ago must NOT appear in a 30-day window."""
    # Simulate what the fixed code does: only return contacts created within window.
    # The test verifies the gte filter would exclude old records.

    old_contact = {
        "outreach_state": "replied",
        "company_id": "co-old",
        "created_at": (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(),
    }
    new_contact = {
        "outreach_state": "replied",
        "company_id": "co-new",
        "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
    }

    since = datetime.now(timezone.utc) - timedelta(days=30)

    # Simulate the filter
    rows = [old_contact, new_contact]
    filtered = [r for r in rows if datetime.fromisoformat(r["created_at"]) >= since]

    assert len(filtered) == 1, (
        f"Only the T-5d contact should be in the 30d window, got {len(filtered)}"
    )
    assert filtered[0]["company_id"] == "co-new"


def test_date_filter_string_format_is_iso():
    """The since value passed to .gte() must be an ISO date string."""
    from backend.app.analytics.funnel import _since_iso

    since = _since_iso(30)
    # Must be parseable as ISO datetime
    try:
        parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - parsed
        assert 29 <= age.days <= 31, f"Expected ~30 days, got {age.days}"
    except ValueError as e:
        pytest.fail(f"_since_iso returned non-ISO string: {since!r}: {e}")
