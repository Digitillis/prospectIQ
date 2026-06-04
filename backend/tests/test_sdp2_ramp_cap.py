"""SDP#2: ramp_cap must be keyed on business days since CAMPAIGN_START,
not on the loop day_idx (which resets to 0 on every recompute).

Post-2026-06-15 (week 3+) daily slot counts must equal full_cap, not be
throttled back to week-1 limits because the loop index restarts at 0.
"""

from __future__ import annotations

import pytest
from datetime import date, timedelta

from backend.app.core.send_scheduler import (
    CAMPAIGN_START,
    RAMP_SCHEDULE,
    ramp_cap,
    compute_schedule,
    Contact,
)


def _business_days_between(start: date, end: date) -> int:
    """Count business days from start (exclusive) to end (inclusive)."""
    count = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            count += 1
    return count


def test_ramp_cap_week1():
    """Week 1 (bday 0-4): cap should be RAMP_SCHEDULE[0]."""
    full_cap = 270
    assert ramp_cap(0, full_cap) == RAMP_SCHEDULE[0]
    assert ramp_cap(4, full_cap) == RAMP_SCHEDULE[0]


def test_ramp_cap_week2():
    """Week 2 (bday 5-9): cap should be RAMP_SCHEDULE[1]."""
    full_cap = 270
    assert ramp_cap(5, full_cap) == RAMP_SCHEDULE[1]
    assert ramp_cap(9, full_cap) == RAMP_SCHEDULE[1]


def test_ramp_cap_week3_plus_equals_full_cap():
    """Week 3+ (bday >= 10): cap should equal full_cap."""
    full_cap = 270
    assert ramp_cap(10, full_cap) == full_cap
    assert ramp_cap(20, full_cap) == full_cap
    assert ramp_cap(100, full_cap) == full_cap


def test_post_campaign_start_daily_slots_not_throttled():
    """After week 2, ramp_cap must return full_cap, not week-1 caps.

    This catches the bug where day_idx (loop counter, restarts at 0 each recompute)
    was passed to ramp_cap instead of business days since CAMPAIGN_START.

    We test via follow-up contacts (step 2 ready) since Phase A (follow-ups) is only
    gated by ramp_cap, not new_start_soft_cap. If ramp_cap returns the old week-1
    value (100) instead of full_cap (270), Phase A would stop placing at 100.
    """
    full_cap = 270
    sent_step1_on = date(2026, 6, 2)  # step 1 sent in week 1

    # Create 270+ contacts that all have step 2 ready (step 1 already sent)
    contacts = [
        Contact(
            contact_id=f"c{i:04d}",
            company_id=f"co{i:04d}",
            email=f"c{i:04d}@example.com",
            remaining={2: f"draft2-{i:04d}"},
            sent={1: sent_step1_on},  # step 1 sent — step 2 is a follow-up
        )
        for i in range(full_cap + 50)
    ]

    # Start scheduling in week 3 (well past ramp up)
    # CAMPAIGN_START = 2026-06-01, week 3 starts ~2026-06-15 (10 business days in)
    start_date = date(2026, 6, 18)  # Thursday of week 3
    sender_pool = [f"sender{i}@digitillis.io" for i in range(10)]

    slots, warnings = compute_schedule(
        contacts,
        sender_pool=sender_pool,
        start_date=start_date,
        full_cap=full_cap,
    )

    # Count slots for the first business day scheduled
    from collections import Counter
    day_counts = Counter(s.scheduled_date for s in slots)
    if day_counts:
        first_day = min(day_counts)
        first_day_count = day_counts[first_day]
        # With ramp_cap bug (day_idx=0 → RAMP_SCHEDULE[0]=100), only 100 placed
        # With fix (real bday since start → week 3 → full_cap=270), full cap placed
        assert first_day_count == full_cap, (
            f"Expected {full_cap} slots on first day (week 3+ should be full_cap), "
            f"got {first_day_count}. Ramp cap bug: recompute may be throttling to week-1/2 cap."
        )
