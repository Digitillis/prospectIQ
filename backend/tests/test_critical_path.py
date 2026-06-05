"""Critical-path canary suite — one test per pipeline stage.

Each test covers a single stage of contact → schedule → send → reply → funnel
and is designed to FAIL if that stage regresses. No real DB or network: pure
functions are exercised directly; DB-dependent stages use minimal mocks.

Stages:
  1. Contact eligibility gate     (_load_state filters)
  2. Schedule minimum-gap         (compute_schedule)
  3. Dispatch idempotency         (dispatch_workspace → stable key)
  4. Opt-out cancels sequences    (ReplyAgent._cancel_active_sequences — D1)
  5. Funnel honours days param    (get_funnel_counts — D5)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Stage 1 — Contact eligibility gate
# ---------------------------------------------------------------------------


def test_eligible_contact_passes_load_state_filters():
    """A verified, eligible contact with a model-tagged pending draft and a
    sendable cluster must survive _load_state filtering and appear as a Contact."""
    from backend.app.core.send_scheduler import _load_state

    eligible_contact = {
        "id": "c1",
        "email": "alice@acme.com",
        "company_id": "co1",
        "title": "VP Operations",
        "is_outreach_eligible": True,
        "email_status": "verified",
        "outreach_state": "active",
    }
    company = {"id": "co1", "campaign_cluster": "machinery", "status": "qualified"}
    pending_draft = {
        "id": "d1",
        "contact_id": "c1",
        "company_id": "co1",
        "sequence_step": 1,
        "body": "Hi Alice, saw your work at https://acme.com and had a quick question.",
        "personalization_notes": "Referenced https://linkedin.com/in/alice ops post.",
        "approval_status": "pending",
        "sent_at": None,
        "model": "claude-sonnet-4-6",
    }

    pages = {
        "contacts": [eligible_contact],
        "companies": [company],
        "suppression_log": [],
        "outreach_drafts": [pending_draft],
        "outreach_send_config": [
            {"sender_pool": [{"email": "avi@digitillis.io"}], "daily_limit": 270}
        ],
    }

    class _Chain:
        """Every query method returns self; execute() yields the table's rows."""

        def __init__(self, rows):
            self._rows = rows

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def range(self, *a, **k):
            return self

        def execute(self):
            return MagicMock(data=list(self._rows))

    db = MagicMock()
    db.workspace_id = "ws-1"
    db.client.table.side_effect = lambda name: _Chain(pages.get(name, []))

    contacts, sent_hist, sender_pool, full_cap = _load_state(db, "ws-1")

    assert any(c.contact_id == "c1" for c in contacts), (
        "Eligible contact with a model-tagged pending draft was filtered out of _load_state"
    )


# ---------------------------------------------------------------------------
# Stage 2 — Schedule minimum-gap (the June 3 regression)
# ---------------------------------------------------------------------------


def test_step4_not_scheduled_sooner_than_2_calendar_days_after_step3():
    """Step 4 must never be scheduled fewer than 2 calendar days after step 3,
    regardless of time-of-day."""
    from backend.app.core.send_scheduler import compute_schedule, Contact

    c = Contact(
        contact_id="c1",
        company_id="co1",
        email="x@example.com",
        remaining={4: "draft-4"},
        sent={3: date(2026, 6, 1)},  # step 3 sent Monday June 1
    )
    slots, _ = compute_schedule(
        [c], sender_pool=["avi@test.com"], start_date=date(2026, 6, 1), full_cap=270
    )
    assert slots, "Step 4 should be schedulable"
    gap = (slots[0].scheduled_date - date(2026, 6, 1)).days
    assert gap >= 2, f"Step 4 scheduled only {gap} days after step 3 (floor is 2)"


# ---------------------------------------------------------------------------
# Stage 2b — Assertion step-gap uses calendar dates, not timedelta.days
#
# Regression test for the June 3 2026 incident: step-3 sent at 2:49 PM UTC
# June 1; step-4 dispatched at 8:53 AM UTC June 3. timedelta.days = 1 (18h
# short of a full 2 days), so the assertion wrongly blocked 429 sends.
# The fix: compare .date() values so time-of-day drift can't cause a false fail.
# ---------------------------------------------------------------------------


def test_step_gap_assertion_uses_calendar_dates_not_timedelta_days():
    """assert_minimum_step_gap must pass when 2 calendar days have elapsed,
    even if the datetime difference is < 2.0 days due to time-of-day offset."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone
    from backend.app.core.pre_send_assertions import assert_minimum_step_gap, AssertionFailure

    # Step 3 sent late afternoon UTC June 1; step 4 dispatched early morning June 3
    step3_sent = "2026-06-01T14:49:16.583551+00:00"
    dispatch_time = datetime(2026, 6, 3, 8, 53, 0, tzinfo=timezone.utc)
    # timedelta.days = 1 (broken); date diff = 2 (correct)

    class _R:
        data = [{"sent_at": step3_sent}]

    class _Q:
        def select(self, *a): return self
        def eq(self, *a): return self
        def order(self, *a, **k): return self
        def limit(self, *a): return self
        def execute(self): return _R()
        def __getattr__(self, name): return self
        def __call__(self, *a, **k): return self

    class _Client:
        def table(self, _): return _Q()

    class _Db:
        client = _Client()

    contact = {"id": "c-001", "contact_id": "c-001", "company_id": "co-001", "full_name": "T"}

    with patch("backend.app.core.pre_send_assertions.datetime") as mock_dt:
        mock_dt.now.return_value = dispatch_time
        mock_dt.fromisoformat = datetime.fromisoformat
        # Must NOT raise — 2 calendar days >= 2 day minimum for step 4
        assert_minimum_step_gap(_Db(), contact, sequence_step=4)


def test_step_gap_assertion_blocks_when_only_one_calendar_day_has_passed():
    """assert_minimum_step_gap must FAIL when only 1 calendar day has elapsed."""
    from unittest.mock import patch
    from datetime import datetime, timezone
    from backend.app.core.pre_send_assertions import assert_minimum_step_gap, AssertionFailure

    step3_sent = "2026-06-02T08:00:00.000000+00:00"
    dispatch_time = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)  # 1 calendar day

    class _R:
        data = [{"sent_at": step3_sent}]

    class _Q:
        def select(self, *a): return self
        def eq(self, *a): return self
        def order(self, *a, **k): return self
        def limit(self, *a): return self
        def execute(self): return _R()
        def __getattr__(self, name): return self
        def __call__(self, *a, **k): return self

    class _Client:
        def table(self, _): return _Q()

    class _Db:
        client = _Client()

    contact = {"id": "c-002", "contact_id": "c-002", "company_id": "co-002", "full_name": "T"}

    with patch("backend.app.core.pre_send_assertions.datetime") as mock_dt:
        mock_dt.now.return_value = dispatch_time
        mock_dt.fromisoformat = datetime.fromisoformat
        import pytest
        with pytest.raises(AssertionFailure, match="minimum_step_gap"):
            assert_minimum_step_gap(_Db(), contact, sequence_step=4)


# ---------------------------------------------------------------------------
# Stage 3 — Dispatch idempotency (stable key across retries — SDP#3)
# ---------------------------------------------------------------------------


def test_idempotency_key_is_stable_draft_id_on_retry():
    """The idempotency key passed to dispatch_queued_draft must equal draft_id
    (not draft_id:attempt_number), so Resend's 24h dedup catches retries."""
    from backend.app.core.dispatch_scheduler import dispatch_workspace
    from backend.app.agents.engagement import QueueDispatchOutcome

    DRAFT_ID = "draft-abc"
    # retry_count=1 → this is the second attempt; the key must still be just draft_id.
    queue_row = {"id": "q1", "draft_id": DRAFT_ID, "workspace_id": "ws-1", "retry_count": 1}

    db_client = MagicMock()
    db_client.rpc.return_value.execute.return_value = MagicMock(data=[queue_row])
    # send_attempts insert returns an id so dispatch proceeds
    db_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "attempt-1"}]
    )
    db_client.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    db_client.table.return_value.delete.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    captured = {}

    agent = MagicMock()

    def _dispatch(queue_row, attempt_number, idempotency_key):
        captured["key"] = idempotency_key
        captured["attempt"] = attempt_number
        return QueueDispatchOutcome(status="DELIVERED", provider_message_id="m1")

    agent.dispatch_queued_draft.side_effect = _dispatch

    from unittest.mock import patch

    with patch("backend.app.agents.engagement.EngagementAgent", return_value=agent):
        dispatch_workspace(db_client, "ws-1")

    assert captured.get("key") == DRAFT_ID, (
        f"Idempotency key was {captured.get('key')!r}, expected stable draft_id {DRAFT_ID!r}"
    )
    assert captured.get("attempt") == 2, "attempt_number should still increment for the DB row"


# ---------------------------------------------------------------------------
# Stage 4 — Opt-out reply cancels active sequences (D1 regression)
# ---------------------------------------------------------------------------


def test_unsubscribe_reply_cancels_active_sequences():
    """An opt-out must cancel all active engagement sequences for the contact's
    company. Regression guard for the D1 AttributeError (method was module-scope)."""
    from backend.app.agents.reply import ReplyAgent

    agent = ReplyAgent.__new__(ReplyAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.get_active_sequences.return_value = [
        {"id": "seq-1", "company_id": "co1"},
        {"id": "seq-2", "company_id": "co1"},
        {"id": "seq-3", "company_id": "OTHER"},  # different company — must be left alone
    ]

    cancelled = agent._cancel_active_sequences("co1")

    assert cancelled == 2, f"Expected 2 sequences cancelled for co1, got {cancelled}"
    # The two co1 sequences were updated to cancelled; the OTHER one was not.
    updated_ids = [c.args[0] for c in agent.db.update_engagement_sequence.call_args_list]
    assert set(updated_ids) == {"seq-1", "seq-2"}


# ---------------------------------------------------------------------------
# Stage 5 — Funnel honours the days parameter (D5 regression)
# ---------------------------------------------------------------------------


def test_funnel_applies_days_date_filter():
    """get_funnel_counts(days=7) must apply .gte('created_at', since) so a
    contact created 100 days ago is excluded from the 7-day window."""
    from backend.app.analytics.funnel import FunnelAnalytics

    db = MagicMock()
    db.workspace_id = "ws-1"

    gte_calls: list = []

    # _filter_ws returns a chain; .gte records its args then returns a terminal chain
    filtered_chain = MagicMock()

    def _gte(col, val):
        gte_calls.append((col, val))
        terminal = MagicMock()
        terminal.execute.return_value = MagicMock(data=[])
        terminal.in_.return_value = terminal
        return terminal

    filtered_chain.gte.side_effect = _gte
    db._filter_ws.return_value = filtered_chain

    fa = FunnelAnalytics(db)
    fa.get_funnel_counts(days=7)

    assert gte_calls, "get_funnel_counts did not apply any .gte() date filter (D5 regression)"
    col, val = gte_calls[0]
    assert col == "created_at", f"date filter applied to {col!r}, expected 'created_at'"
    # The 'since' value must be ~7 days in the past, not all-time.
    parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - parsed).days
    assert 6 <= age_days <= 8, f"days=7 produced a since value {age_days}d old, expected ~7"


# guard against accidental import-time collisions with timedelta used above
assert timedelta is not None
