"""Tests for ClickClassifier (P4.2 — GTM rebuild)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.core.click_classifier import ClickClassifier


def _ts(seconds_offset: int) -> str:
    """Return an ISO timestamp at base + seconds_offset for deterministic tests."""
    base = datetime(2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=seconds_offset)).isoformat()


def test_85_second_click_is_bot() -> None:
    """85 seconds < 90s floor → bot."""
    event = {"latency_seconds": 85}
    assert ClickClassifier().classify(event) == "bot"


def test_proofpoint_user_agent_is_bot() -> None:
    event = {
        "latency_seconds": 600,  # well past the latency floor
        "user_agent": "Mozilla/5.0 (Proofpoint URL Defense) ...",
    }
    assert ClickClassifier().classify(event) == "bot"


def test_three_rapid_clicks_is_bot() -> None:
    """3 clicks across distinct links within 120s → bot."""
    event = {
        "latency_seconds": 600,
        "recent_clicks": [
            {"click_timestamp": _ts(0),   "link": "https://a.com/1"},
            {"click_timestamp": _ts(20),  "link": "https://b.com/2"},
            {"click_timestamp": _ts(40),  "link": "https://c.com/3"},
        ],
    }
    assert ClickClassifier().classify(event) == "bot"


def test_open_then_click_45s_later_is_human() -> None:
    """Open + click with 45s dwell (well above 30s floor) → human."""
    event = {
        "latency_seconds": 600,
        "open_timestamp":  _ts(0),
        "click_timestamp": _ts(45),
    }
    assert ClickClassifier().classify(event) == "human"


def test_ametek_pattern_day_2_open_and_click() -> None:
    """AMETEK historical pattern: open on day 2, click on day 2 ~minutes after.
    Realistic legitimate engagement that must come back as 'human'."""
    base = datetime(2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc)
    open_ts = base + timedelta(days=2, minutes=0)
    click_ts = base + timedelta(days=2, minutes=4)  # 240 seconds dwell
    event = {
        "latency_seconds": (click_ts - base).total_seconds(),  # ~172800s
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124",
        "open_timestamp": open_ts.isoformat(),
        "click_timestamp": click_ts.isoformat(),
    }
    assert ClickClassifier().classify(event) == "human"


def test_tsubaki_pattern_open_then_click_with_dwell() -> None:
    """Tsubaki pattern — open immediately, click 2 minutes later. Human."""
    event = {
        "latency_seconds": 360,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/124",
        "open_timestamp":  _ts(0),
        "click_timestamp": _ts(125),  # 125s dwell, well above 30s floor
    }
    assert ClickClassifier().classify(event) == "human"


def test_default_unclear_when_no_signals() -> None:
    """No latency, no user-agent, no open dwell → unclear."""
    event = {}
    assert ClickClassifier().classify(event) == "unclear"


def test_microsoft_atp_safelinks_is_bot() -> None:
    event = {
        "latency_seconds": 800,
        "user_agent": "Mozilla/5.0 (compatible; ATP SafeLinks/1.0)",
    }
    assert ClickClassifier().classify(event) == "bot"


def test_open_to_click_dwell_too_short_is_unclear() -> None:
    """Open then click 5s later → not enough dwell for human, falls to unclear."""
    event = {
        "latency_seconds": 600,
        "open_timestamp":  _ts(0),
        "click_timestamp": _ts(5),
    }
    assert ClickClassifier().classify(event) == "unclear"
