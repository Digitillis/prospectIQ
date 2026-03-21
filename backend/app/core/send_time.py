"""Send-time optimization for outreach emails.

Manufacturing executives have predictable email reading patterns:
- VP/Director: 6:00-7:30am local time (before the floor starts)
- Plant Manager: 5:30-6:30am (earliest risers)
- C-suite: 7:00-8:30am (after morning routine)

This module calculates the optimal send time based on:
1. Prospect's timezone (derived from state)
2. Persona type (different roles read email at different times)
3. Day of week (Tue-Thu > Mon > Fri; never weekends)
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# State → timezone mapping (US manufacturing hubs)
_STATE_TIMEZONE: dict[str, str] = {
    # Eastern
    "CT": "US/Eastern", "DE": "US/Eastern", "FL": "US/Eastern",
    "GA": "US/Eastern", "IN": "US/Eastern", "KY": "US/Eastern",
    "MA": "US/Eastern", "MD": "US/Eastern", "ME": "US/Eastern",
    "MI": "US/Eastern", "NC": "US/Eastern", "NH": "US/Eastern",
    "NJ": "US/Eastern", "NY": "US/Eastern", "OH": "US/Eastern",
    "PA": "US/Eastern", "RI": "US/Eastern", "SC": "US/Eastern",
    "TN": "US/Eastern", "VA": "US/Eastern", "VT": "US/Eastern",
    "WV": "US/Eastern",
    # Central
    "AL": "US/Central", "AR": "US/Central", "IA": "US/Central",
    "IL": "US/Central", "KS": "US/Central", "LA": "US/Central",
    "MN": "US/Central", "MO": "US/Central", "MS": "US/Central",
    "NE": "US/Central", "ND": "US/Central", "OK": "US/Central",
    "SD": "US/Central", "TX": "US/Central", "WI": "US/Central",
    # Mountain
    "AZ": "US/Mountain", "CO": "US/Mountain", "ID": "US/Mountain",
    "MT": "US/Mountain", "NM": "US/Mountain", "UT": "US/Mountain",
    "WY": "US/Mountain",
    # Pacific
    "CA": "US/Pacific", "NV": "US/Pacific", "OR": "US/Pacific",
    "WA": "US/Pacific",
    # Other
    "AK": "US/Alaska", "HI": "US/Hawaii",
}

# Optimal local send times by persona type
_PERSONA_WINDOWS: dict[str, tuple[time, time]] = {
    # Plant managers read email earliest — before shift starts
    "plant_manager": (time(5, 30), time(6, 30)),
    # VP/Director ops — before the floor gets busy
    "vp_ops": (time(6, 0), time(7, 30)),
    "director_ops": (time(6, 0), time(7, 30)),
    "maintenance_leader": (time(6, 0), time(7, 0)),
    # Food safety — similar to ops
    "vp_quality_food_safety": (time(6, 30), time(7, 30)),
    "director_quality_food_safety": (time(6, 30), time(7, 30)),
    # C-suite — slightly later
    "coo": (time(7, 0), time(8, 30)),
    "cio": (time(7, 0), time(8, 30)),
    # Digital transformation — tech-oriented, read email a bit later
    "digital_transformation": (time(7, 30), time(9, 0)),
    # Supply chain
    "vp_supply_chain": (time(6, 30), time(8, 0)),
}

# Default window if persona not mapped
_DEFAULT_WINDOW = (time(6, 30), time(7, 30))

# Best days to send (1=Mon, 5=Fri): Tue-Thu preferred, Mon acceptable, Fri worst
_DAY_PREFERENCE = {
    1: 2,  # Monday — acceptable (inbox flooded from weekend)
    2: 3,  # Tuesday — great
    3: 3,  # Wednesday — great
    4: 3,  # Thursday — great
    5: 1,  # Friday — poor (weekend mindset)
    6: 0,  # Saturday — never
    7: 0,  # Sunday — never
}


def get_optimal_send_time(
    state: str | None = None,
    persona_type: str | None = None,
    from_time: datetime | None = None,
) -> datetime:
    """Calculate the optimal send time for a prospect.

    Args:
        state: Two-letter US state code (for timezone).
        persona_type: Prospect's persona type (for reading window).
        from_time: Calculate from this time (default: now UTC).

    Returns:
        Optimal send time as a UTC datetime.
    """
    now = from_time or datetime.now(timezone.utc)

    # Determine prospect's timezone
    tz_name = _STATE_TIMEZONE.get((state or "").upper(), "US/Eastern")
    prospect_tz = ZoneInfo(tz_name)

    # Determine optimal local time window
    window_start, window_end = _PERSONA_WINDOWS.get(
        persona_type or "", _DEFAULT_WINDOW
    )

    # Convert now to prospect's local time
    local_now = now.astimezone(prospect_tz)

    # Find the next good send slot
    candidate = local_now.replace(
        hour=window_start.hour,
        minute=window_start.minute,
        second=0,
        microsecond=0,
    )

    # If we're past today's window, start from tomorrow
    if local_now.time() >= window_end:
        candidate += timedelta(days=1)

    # Skip weekends and find the next best day
    for _ in range(7):
        day_pref = _DAY_PREFERENCE.get(candidate.isoweekday(), 0)
        if day_pref >= 2:  # Acceptable or great
            break
        candidate += timedelta(days=1)

    # Convert back to UTC
    return candidate.astimezone(timezone.utc)


def get_send_time_explanation(
    state: str | None = None,
    persona_type: str | None = None,
) -> str:
    """Get a human-readable explanation of the send time logic.

    Returns:
        String like "6:30am ET (Tue-Thu) — VP Ops reading window"
    """
    tz_name = _STATE_TIMEZONE.get((state or "").upper(), "US/Eastern")
    tz_label = tz_name.replace("US/", "").replace("ern", "")  # "Eastern" → "East"

    window_start, window_end = _PERSONA_WINDOWS.get(
        persona_type or "", _DEFAULT_WINDOW
    )

    return (
        f"{window_start.strftime('%I:%M%p').lstrip('0')}-"
        f"{window_end.strftime('%I:%M%p').lstrip('0')} {tz_label} "
        f"(Tue-Thu preferred) — {persona_type or 'default'} reading window"
    )
