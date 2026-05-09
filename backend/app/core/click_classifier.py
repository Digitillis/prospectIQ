"""Bot-vs-human click classifier (P4.2 — GTM rebuild 2026-05-08).

Email security gateways (Mimecast, Proofpoint, Microsoft ATP, etc.) silently
visit every URL in an email to scan it for malicious content. Those visits
register as `email_clicked` interactions but should NEVER count as buyer
engagement — they pollute the engagement-tier state machine and lead to
spurious HOT classifications.

This module exposes ClickClassifier.classify(event) which returns:
    "bot"     — provably automated visit
    "human"   — high-confidence real human interaction
    "unclear" — could be either; we do not count these as engagement

Rules are evaluated in priority order. The first matching rule wins.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Below this many seconds between message delivery and the click, the
# interaction is almost certainly an email security scanner — humans don't
# read and click within the first minute.
_BOT_LATENCY_FLOOR_SECONDS = 90

# Substrings (case-insensitive) on user-agent that mark known scanners.
_BOT_USER_AGENT_TOKENS: tuple[str, ...] = (
    "Mimecast",
    "Proofpoint",
    "Barracuda",
    "Microsoft ATP",
    "ATP SafeLinks",
    "Cisco IronPort",
    "Symantec",
    "url_rewriter",
    "safelinks.protection.outlook.com",
)

# 3+ clicks across distinct links within this many seconds → bot.
_RAPID_CLICK_WINDOW_SECONDS = 120
_RAPID_CLICK_MIN_COUNT = 3

# Minimum dwell between an open and a click for the click to count as human.
# Below this, the open + click look automated.
_HUMAN_OPEN_CLICK_MIN_DWELL_SECONDS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_datetime(value) -> datetime | None:
    """Coerce a timestamp-shaped value to a tz-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _seconds_between(a, b) -> float | None:
    """Return abs(b - a) in seconds, or None if either side is missing."""
    da, db = _to_datetime(a), _to_datetime(b)
    if da is None or db is None:
        return None
    return abs((db - da).total_seconds())


def _user_agent_is_scanner(ua: str | None) -> bool:
    if not ua:
        return False
    ua_lower = ua.lower()
    for token in _BOT_USER_AGENT_TOKENS:
        if token.lower() in ua_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class ClickClassifier:
    """Stateless click-event classifier."""

    def classify(self, click_event: dict) -> str:
        """Return 'bot', 'human', or 'unclear' for a single click event.

        Expected fields on `click_event` (all optional except where noted):
          latency_seconds      — seconds between send delivery and click
          user_agent           — UA string
          recent_clicks        — list of dicts each with at least
                                 'click_timestamp' and 'link' (or 'url')
                                 used for the rapid-click rule
          open_timestamp       — when the same recipient opened the email
          click_timestamp      — when the click happened (for dwell calc)
        """
        # 1) Latency floor — if the click is suspiciously fast, it's a scanner
        latency = click_event.get("latency_seconds")
        if isinstance(latency, (int, float)) and latency < _BOT_LATENCY_FLOOR_SECONDS:
            return "bot"

        # 2) User-agent denylist
        if _user_agent_is_scanner(click_event.get("user_agent")):
            return "bot"

        # 3) Rapid-click pattern — 3+ clicks on different links within 120s
        if self._rapid_click_pattern(click_event):
            return "bot"

        # 4) Open before click with reasonable dwell — strong human signal
        open_ts = click_event.get("open_timestamp")
        click_ts = click_event.get("click_timestamp")
        if open_ts is not None and click_ts is not None:
            open_dt = _to_datetime(open_ts)
            click_dt = _to_datetime(click_ts)
            if open_dt and click_dt and click_dt >= open_dt:
                dwell = (click_dt - open_dt).total_seconds()
                if dwell >= _HUMAN_OPEN_CLICK_MIN_DWELL_SECONDS:
                    return "human"

        # Default — cannot confidently say either way
        return "unclear"

    # -- Internal helpers ----------------------------------------------------

    def _rapid_click_pattern(self, click_event: dict) -> bool:
        """Return True when `recent_clicks` contains 3+ clicks across
        distinct links within 120 seconds.
        """
        recent: Iterable[dict] = click_event.get("recent_clicks") or []
        if not recent:
            return False
        # Add the current click to the set so a single payload showing 3 fast
        # hits fires the rule even when the caller didn't include "self".
        cur_click_ts = click_event.get("click_timestamp")
        cur_link = click_event.get("link") or click_event.get("url")
        items: list[dict] = []
        for r in recent:
            items.append({
                "click_timestamp": r.get("click_timestamp") or r.get("timestamp"),
                "link": r.get("link") or r.get("url"),
            })
        if cur_click_ts is not None or cur_link:
            items.append({"click_timestamp": cur_click_ts, "link": cur_link})

        # Convert and sort
        timed: list[tuple[datetime, str | None]] = []
        for it in items:
            dt = _to_datetime(it.get("click_timestamp"))
            if dt is None:
                continue
            timed.append((dt, it.get("link")))
        if len(timed) < _RAPID_CLICK_MIN_COUNT:
            return False
        timed.sort(key=lambda t: t[0])

        # Sliding window — find any window of size MIN_COUNT whose span
        # is within the 120s threshold AND whose links are distinct.
        n = len(timed)
        for i in range(n - _RAPID_CLICK_MIN_COUNT + 1):
            window = timed[i : i + _RAPID_CLICK_MIN_COUNT]
            span = (window[-1][0] - window[0][0]).total_seconds()
            if span <= _RAPID_CLICK_WINDOW_SECONDS:
                links = {w[1] for w in window if w[1]}
                if len(links) >= _RAPID_CLICK_MIN_COUNT or (
                    len(links) >= 2 and len(window) >= _RAPID_CLICK_MIN_COUNT
                ):
                    return True
        return False
