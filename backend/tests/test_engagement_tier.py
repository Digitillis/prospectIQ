"""Tests for the three-tier engagement state machine (P4.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.agents.engagement import (
    COLD,
    WARMING,
    HOT,
    classify_engagement_tier,
)


_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)


def _ev(ev_type: str, days_ago: float, **extra) -> dict:
    return {
        "type": ev_type,
        "created_at": (_NOW - timedelta(days=days_ago)).isoformat(),
        **extra,
    }


def _human_classifier(_event: dict) -> str:
    return "human"


def _bot_classifier(_event: dict) -> str:
    return "bot"


def test_no_interactions_is_cold() -> None:
    assert classify_engagement_tier("co", [], now=_NOW) == COLD


def test_open_in_window_is_warming() -> None:
    """A single open within the 14-day window → WARMING."""
    events = [_ev("email_opened", days_ago=10)]
    assert classify_engagement_tier("co", events, now=_NOW) == WARMING


def test_old_open_outside_window_is_cold() -> None:
    """Open older than 14 days does not warm the prospect."""
    events = [_ev("email_opened", days_ago=20)]
    assert classify_engagement_tier("co", events, now=_NOW) == COLD


def test_human_click_in_window_is_warming() -> None:
    events = [_ev("email_clicked", days_ago=10)]
    out = classify_engagement_tier("co", events, click_classifier=_human_classifier, now=_NOW)
    assert out == WARMING


def test_bot_click_is_ignored() -> None:
    """A click classified as bot must not warm or heat the prospect."""
    events = [_ev("email_clicked", days_ago=2)]
    out = classify_engagement_tier("co", events, click_classifier=_bot_classifier, now=_NOW)
    assert out == COLD


def test_two_human_clicks_in_seven_days_is_hot() -> None:
    """2+ distinct human-class engagements within 7 days → HOT."""
    events = [
        _ev("email_clicked", days_ago=2),
        _ev("email_clicked", days_ago=4),
    ]
    out = classify_engagement_tier("co", events, click_classifier=_human_classifier, now=_NOW)
    assert out == HOT


def test_open_plus_human_click_in_seven_days_is_hot() -> None:
    """Open + human click within HOT window → HOT (2 distinct human signals)."""
    events = [
        _ev("email_opened", days_ago=1),
        _ev("email_clicked", days_ago=3),
    ]
    out = classify_engagement_tier("co", events, click_classifier=_human_classifier, now=_NOW)
    assert out == HOT


def test_any_reply_is_hot() -> None:
    """A reply unconditionally bumps the prospect to HOT, even outside windows."""
    events = [_ev("email_replied", days_ago=30)]  # 30 days ago — still HOT
    out = classify_engagement_tier("co", events, now=_NOW)
    assert out == HOT
