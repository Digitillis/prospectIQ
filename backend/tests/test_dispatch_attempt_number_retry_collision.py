"""attempt_number must not collide on retry after a 'timed' assertion outcome.

Four assertion-failure types (company_locked, hot_suppressed, prior_step_sent,
minimum_step_gap) park the queue row via _set_queue_next_retry, which
deliberately does NOT bump retry_count (see its docstring: an external,
temporary block shouldn't burn max_retries budget). attempt_number used to
be derived as retry_count + 1, so the next claim of the same row recomputed
the identical attempt_number and _insert_send_attempt collided on
send_attempts' (draft_id, attempt_number) unique constraint — a real crash,
observed directly 2026-08-17/18 during a live dispatch test where 16 of 20
queued drafts got stuck this way after hitting hot_suppressed once.

send_attempts is an explicit audit-immutability table (ADR-002/SEC-013) —
rows are never deleted, so the fix cannot free the old attempt_number slot.
Instead attempt_number is now derived from the actual max attempt_number
already on record for the draft, independent of retry_count.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.core.dispatch_scheduler import _next_attempt_number


def _mock_db_with_attempts(existing_attempt_numbers: list[int]) -> MagicMock:
    db = MagicMock()
    rows = [{"attempt_number": max(existing_attempt_numbers)}] if existing_attempt_numbers else []
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = rows
    return db


def test_first_attempt_with_no_prior_rows_returns_1():
    db = _mock_db_with_attempts([])
    assert _next_attempt_number(db, "draft-1") == 1


def test_second_attempt_after_one_existing_row_returns_2_even_with_unbumped_retry_count():
    """This is the exact collision scenario: a 'timed' assertion outcome left
    attempt_number=1 on record without bumping retry_count. The next claim
    must NOT recompute attempt_number=1 again."""
    db = _mock_db_with_attempts([1])
    assert _next_attempt_number(db, "draft-1") == 2


def test_derives_from_max_not_count_in_case_of_any_gap():
    db = _mock_db_with_attempts([1, 2, 5])
    assert _next_attempt_number(db, "draft-1") == 6


def test_lookup_failure_defaults_to_1_rather_than_raising():
    db = MagicMock()
    db.table.side_effect = Exception("connection error")
    assert _next_attempt_number(db, "draft-1") == 1
