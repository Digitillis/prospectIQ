"""Tests for assert_workspace_under_daily_cap and its wiring into
run_pre_send_assertions (backend/app/core/pre_send_assertions.py).

Regression coverage for finding 3 of the 2026-08-15 send-path
reconciliation: outreach_send_config.daily_limit was loaded at the
send-path call site (engagement.py) but never passed into the assertion
battery, so it had zero effect on dispatch. The live ceiling was whatever
batch_size times cron ticks produced (~8/day with batch_size=1), not the
configured daily_limit (which was reset to 1 on 2026-08-14 believing it
would cap sends at 1/day).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.core.pre_send_assertions import (
    AssertionFailure,
    assert_workspace_under_daily_cap,
    run_pre_send_assertions,
)

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _db_with_sent_count(count: int, raise_exc: Exception | None = None):
    db = MagicMock()
    chain = db.client.table.return_value
    for attr in ("select", "eq", "gte"):
        getattr(chain, attr).return_value = chain
    chain.not_.is_.return_value = chain
    if raise_exc is not None:
        chain.execute.side_effect = raise_exc
    else:
        chain.execute.return_value = MagicMock(count=count)
    return db


class TestAssertWorkspaceUnderDailyCap:
    def test_under_cap_passes(self):
        db = _db_with_sent_count(count=0)
        assert_workspace_under_daily_cap(db, WORKSPACE_ID, daily_cap=1)  # no raise

    def test_at_cap_raises(self):
        db = _db_with_sent_count(count=1)
        try:
            assert_workspace_under_daily_cap(db, WORKSPACE_ID, daily_cap=1)
            assert False, "expected AssertionFailure"
        except AssertionFailure as af:
            assert af.assertion == "workspace_daily_cap"
            assert "1/1" in af.detail

    def test_over_cap_raises(self):
        db = _db_with_sent_count(count=5)
        try:
            assert_workspace_under_daily_cap(db, WORKSPACE_ID, daily_cap=1)
            assert False, "expected AssertionFailure"
        except AssertionFailure:
            pass

    def test_query_scoped_to_workspace_and_sent_today(self):
        db = _db_with_sent_count(count=0)
        assert_workspace_under_daily_cap(db, WORKSPACE_ID, daily_cap=1)
        db.client.table.assert_any_call("outreach_drafts")
        db.client.table.return_value.eq.assert_any_call("workspace_id", WORKSPACE_ID)

    def test_read_failure_fails_open_not_closed(self):
        """Matches assert_sender_under_daily_cap's behavior directly above
        it: a query exception logs and passes rather than blocking every
        send whenever the count query has a transient issue.
        """
        db = _db_with_sent_count(count=0, raise_exc=RuntimeError("db down"))
        assert_workspace_under_daily_cap(db, WORKSPACE_ID, daily_cap=1)  # no raise


class TestRunPreSendAssertionsWorkspaceCapWiring:
    """Isolates the workspace-cap wiring from the rest of the battery by
    no-opping every sibling assertion — those are covered by
    test_send_path_governance.py and friends. This class only asks: given
    assertion_context and the two new params, does
    assert_workspace_under_daily_cap get called, and does its failure
    propagate?
    """

    def _passthrough_kwargs(self):
        return dict(
            contact={"id": "c1", "email": "a@b.com"},
            company={"id": "co1"},
            sender_email="sender@digitillis.io",
        )

    def _noop_siblings(self, monkeypatch):
        for name in (
            "assert_not_rejected",
            "assert_bounce_rate_ok",
            "assert_email_deliverable",
            "assert_email_status_verified",
            "assert_email_name_consistent",
            "assert_outreach_eligible",
            "assert_persona_target",
            "assert_no_recent_company_send",
            "assert_sender_under_daily_cap",
            "assert_prior_step_sent",
            "assert_minimum_step_gap",
        ):
            monkeypatch.setattr(
                f"backend.app.core.pre_send_assertions.{name}",
                lambda *a, **k: None,
            )

    def test_not_invoked_when_workspace_params_absent(self, monkeypatch):
        """Existing send_path callers that don't pass workspace_id /
        workspace_daily_cap must be unaffected — this is what the prior
        engagement.py call site looked like before this fix.
        """
        self._noop_siblings(monkeypatch)
        called = []
        monkeypatch.setattr(
            "backend.app.core.pre_send_assertions.assert_workspace_under_daily_cap",
            lambda *a, **k: called.append((a, k)),
        )
        run_pre_send_assertions(
            db=MagicMock(),
            assertion_context="send_path",
            **self._passthrough_kwargs(),
        )
        assert called == []

    def test_not_invoked_in_draft_gen_context_even_with_params(self, monkeypatch):
        self._noop_siblings(monkeypatch)
        called = []
        monkeypatch.setattr(
            "backend.app.core.pre_send_assertions.assert_workspace_under_daily_cap",
            lambda *a, **k: called.append((a, k)),
        )
        run_pre_send_assertions(
            db=MagicMock(),
            assertion_context="draft_gen",
            workspace_id=WORKSPACE_ID,
            workspace_daily_cap=1,
            **self._passthrough_kwargs(),
        )
        assert called == []

    def test_invoked_in_send_path_when_both_params_given(self, monkeypatch):
        self._noop_siblings(monkeypatch)
        called = []
        monkeypatch.setattr(
            "backend.app.core.pre_send_assertions.assert_workspace_under_daily_cap",
            lambda *a, **k: called.append((a, k)),
        )
        run_pre_send_assertions(
            db=MagicMock(),
            assertion_context="send_path",
            workspace_id=WORKSPACE_ID,
            workspace_daily_cap=1,
            **self._passthrough_kwargs(),
        )
        assert len(called) == 1
        args, _ = called[0]
        assert args[1] == WORKSPACE_ID
        assert args[2] == 1

    def test_workspace_cap_failure_blocks_the_whole_batch(self, monkeypatch):
        """The real regression check: with the workspace already at its
        daily_limit, run_pre_send_assertions in send_path context must
        raise before per-contact checks run — this is what makes
        daily_limit=1 actually mean 1/day rather than the ~8/day the
        batch_size*cron-ticks ceiling previously allowed.
        """
        self._noop_siblings(monkeypatch)
        db = _db_with_sent_count(count=1)
        try:
            run_pre_send_assertions(
                db=db,
                assertion_context="send_path",
                workspace_id=WORKSPACE_ID,
                workspace_daily_cap=1,
                **self._passthrough_kwargs(),
            )
            assert False, "expected AssertionFailure"
        except AssertionFailure as af:
            assert af.assertion == "workspace_daily_cap"
