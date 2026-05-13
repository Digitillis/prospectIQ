"""Send-path governance tests.

Exercises the two critical properties of the send-time assertion gate:

1. Stale-state prevention: a draft generated while a contact is eligible is
   blocked at send time if the contact's verification status deteriorated
   between generation and delivery — and sent_at is rolled back.

2. Rollback failure visibility: if the rollback DB call itself fails, a
   CRITICAL log fires with all required fields; the exception is not swallowed.

These tests use a fake DB client identical in shape to the one used in
test_bounce_suppressor.py — no real database connection required.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.app.core.pre_send_assertions import (
    AssertionFailure,
    assert_email_deliverable,
    assert_email_status_verified,
    run_pre_send_assertions,
    SENDABLE_EMAIL_STATUSES,
)
from backend.app.agents.engagement import _rollback_sent_at


# ---------------------------------------------------------------------------
# Fake DB infrastructure (mirrors test_bounce_suppressor.py pattern)
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, data: list[dict[str, Any]] | None = None, count: int | None = None):
        self.data = data or []
        self.count = count


class _Query:
    def __init__(self, table: "_Table", op: str = "select"):
        self.table = table
        self.op = op
        self._filters: list = []
        self._payload: dict | list | None = None
        self._raise: Exception | None = None

    def select(self, *_args, **_kwargs):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self._payload = payload
        return self

    def eq(self, *_args): return self
    def neq(self, *_args): return self
    def is_(self, *_args): return self
    def not_(self): return self
    def gte(self, *_args): return self
    def in_(self, *_args): return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_args): return self
    def range(self, *_args): return self

    # Support chained .not_.is_(...)
    def __getattr__(self, name):
        return self

    def execute(self) -> _Result:
        if self._raise:
            raise self._raise
        return self.table._result_for(self.op, self._payload)


class _Table:
    def __init__(self, name: str, rows: list[dict] | None = None,
                 raise_on_update: Exception | None = None,
                 raise_on_insert: Exception | None = None):
        self.name = name
        self._rows = rows or []
        self._raise_on_update = raise_on_update
        self._raise_on_insert = raise_on_insert
        self.updates: list[dict] = []
        self.inserts: list[dict] = []

    def _result_for(self, op: str, payload) -> _Result:
        if op == "update":
            if self._raise_on_update:
                raise self._raise_on_update
            self.updates.append(payload or {})
            return _Result(data=[payload] if payload else [])
        if op == "insert":
            if self._raise_on_insert:
                raise self._raise_on_insert
            self.inserts.append(payload or {})
            return _Result(data=[payload] if payload else [])
        # select
        return _Result(data=list(self._rows))

    def select(self, *_args, **_kwargs):
        q = _Query(self, "select")
        return q

    def update(self, payload):
        q = _Query(self, "update")
        q._payload = payload
        if self._raise_on_update:
            q._raise = self._raise_on_update
        return q

    def insert(self, payload):
        q = _Query(self, "insert")
        q._payload = payload
        if self._raise_on_insert:
            q._raise = self._raise_on_insert
        return q


class _FakeClient:
    def __init__(self, tables: dict[str, _Table]):
        self._tables = tables

    def table(self, name: str) -> _Table:
        if name not in self._tables:
            self._tables[name] = _Table(name)
        return self._tables[name]


class _FakeDb:
    def __init__(self, tables: dict[str, _Table]):
        self.client = _FakeClient(tables)
        self.workspace_id = "ws-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contact(email_status: str | None, **extra) -> dict:
    return {
        "id": "contact-001",
        "email": "target@example.com",
        "email_status": email_status,
        "email_name_verified": True,
        "is_outreach_eligible": True,
        "contact_tier": "tier_1",
        "company_id": "company-001",
        "full_name": "Test Target",
        **extra,
    }


def _company() -> dict:
    return {"id": "company-001"}


# ---------------------------------------------------------------------------
# Test 1 — Stale-state prevention
#
# Scenario: draft generated while contact.email_status='verified' (eligible).
# Between generation and send, email_status deteriorates to 'invalid'.
# Send-path assertion must block delivery and sent_at must roll back.
# ---------------------------------------------------------------------------


def test_stale_contact_status_blocks_send_and_rolls_back():
    """assert_email_deliverable blocks a contact whose status went invalid after draft gen."""
    send_assertions_table = _Table("send_assertions")
    outreach_drafts_table = _Table("outreach_drafts")
    db = _FakeDb({
        "send_assertions": send_assertions_table,
        "outreach_drafts": outreach_drafts_table,
    })

    # Simulate: contact status is now 'invalid' at send time
    stale_contact = _contact(email_status="invalid")

    with pytest.raises(AssertionFailure) as exc_info:
        assert_email_deliverable(db, stale_contact, assertion_context="send_path")

    failure = exc_info.value
    assert failure.assertion == "email_deliverable"
    assert "invalid" in failure.detail

    # Assertion logged with send_path context
    assert len(send_assertions_table.inserts) == 1
    logged = send_assertions_table.inserts[0]
    assert logged["passed"] is False
    assert logged["assertion_context"] == "send_path"

    # Simulate rollback: sent_at is NULL'd on the draft
    _rollback_sent_at(db, "draft-001", "contact-001", "company-001",
                      failure.assertion, failure)

    assert len(outreach_drafts_table.updates) == 1
    assert outreach_drafts_table.updates[0] == {"sent_at": None}


def test_null_email_status_blocks_send_at_send_path():
    """assert_email_status_verified blocks NULL status at send time."""
    send_assertions_table = _Table("send_assertions")
    db = _FakeDb({"send_assertions": send_assertions_table})

    null_contact = _contact(email_status=None)

    with pytest.raises(AssertionFailure) as exc_info:
        assert_email_status_verified(db, null_contact, assertion_context="send_path")

    failure = exc_info.value
    assert failure.assertion == "email_status_verified"
    assert "None" in failure.detail

    logged = send_assertions_table.inserts[0]
    assert logged["passed"] is False
    assert logged["assertion_context"] == "send_path"


def test_verified_status_passes_send_path_assertion():
    """assert_email_status_verified passes for 'verified' and 'catch_all' statuses."""
    for status in SENDABLE_EMAIL_STATUSES:
        send_assertions_table = _Table("send_assertions")
        db = _FakeDb({"send_assertions": send_assertions_table})

        contact = _contact(email_status=status)
        # Should not raise
        assert_email_status_verified(db, contact, assertion_context="send_path")

        logged = send_assertions_table.inserts[0]
        assert logged["passed"] is True
        assert logged["assertion_context"] == "send_path"


def test_draft_gen_context_preserved_when_not_send_path():
    """Default assertion_context='draft_gen' is preserved for outreach.py call sites."""
    send_assertions_table = _Table("send_assertions")
    db = _FakeDb({"send_assertions": send_assertions_table})

    contact = _contact(email_status="verified")
    assert_email_status_verified(db, contact)  # no assertion_context kwarg

    logged = send_assertions_table.inserts[0]
    assert logged["assertion_context"] == "draft_gen"


# ---------------------------------------------------------------------------
# Test 2 — Rollback failure visibility
#
# Scenario: assertion fails, rollback DB call raises an exception.
# System must emit a CRITICAL log with all required fields.
# Exception must NOT propagate — caller decides control flow.
# ---------------------------------------------------------------------------


def test_rollback_failure_emits_critical_log_with_all_fields(caplog):
    """_rollback_sent_at logs CRITICAL with draft_id/contact_id/company_id/assertion on DB failure."""
    rollback_exc = RuntimeError("DB timeout")
    outreach_drafts_table = _Table(
        "outreach_drafts",
        raise_on_update=rollback_exc,
    )
    db = _FakeDb({"outreach_drafts": outreach_drafts_table})

    original_assertion_exc = AssertionFailure("email_deliverable", "status=invalid")

    with caplog.at_level(logging.CRITICAL, logger="backend.app.agents.engagement"):
        _rollback_sent_at(
            db,
            draft_id="draft-xyz",
            contact_id="contact-abc",
            company_id="company-def",
            assertion="email_deliverable",
            original_exc=original_assertion_exc,
        )

    # CRITICAL was emitted — orphan state is visible
    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical_records) == 1

    msg = critical_records[0].getMessage()
    assert "draft-xyz" in msg
    assert "contact-abc" in msg
    assert "company-def" in msg
    assert "email_deliverable" in msg
    assert "rollback_failure" in msg or "rollback_failure" in str(critical_records[0].__dict__)


def test_rollback_success_does_not_raise(caplog):
    """_rollback_sent_at completes silently when DB update succeeds."""
    outreach_drafts_table = _Table("outreach_drafts")
    db = _FakeDb({"outreach_drafts": outreach_drafts_table})

    original_exc = AssertionFailure("email_status_verified", "status=None")

    with caplog.at_level(logging.WARNING, logger="backend.app.agents.engagement"):
        _rollback_sent_at(
            db,
            draft_id="draft-001",
            contact_id="contact-001",
            company_id="company-001",
            assertion="email_status_verified",
            original_exc=original_exc,
        )

    # sent_at was set to NULL
    assert outreach_drafts_table.updates == [{"sent_at": None}]

    # No CRITICAL
    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical_records) == 0

    # rollback_success logged at WARNING
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("rollback_success" in r.getMessage() for r in warning_records)


def test_rollback_failure_does_not_propagate_exception():
    """_rollback_sent_at must never raise — caller owns control flow."""
    outreach_drafts_table = _Table(
        "outreach_drafts",
        raise_on_update=RuntimeError("catastrophic DB failure"),
    )
    db = _FakeDb({"outreach_drafts": outreach_drafts_table})

    # Must complete without raising
    _rollback_sent_at(
        db,
        draft_id="draft-001",
        contact_id="contact-001",
        company_id="company-001",
        assertion="email_deliverable",
        original_exc=AssertionFailure("email_deliverable", "status=invalid"),
    )


# ---------------------------------------------------------------------------
# Test 3 — run_pre_send_assertions with assertion_context propagation
# ---------------------------------------------------------------------------


def test_run_pre_send_assertions_propagates_send_path_context():
    """run_pre_send_assertions passes assertion_context='send_path' to every assertion."""
    send_assertions_table = _Table("send_assertions")
    outreach_drafts_table = _Table("outreach_drafts", rows=[])  # no recent sends

    db = _FakeDb({
        "send_assertions": send_assertions_table,
        "outreach_drafts": outreach_drafts_table,
    })

    contact = _contact(email_status="verified")
    company = _company()

    run_pre_send_assertions(
        db=db,
        contact=contact,
        company=company,
        sender_email="avi@trydigitillis.com",
        daily_cap=500,
        cooldown_days=0,
        sequence_step=1,
        assertion_context="send_path",
    )

    # Every logged assertion carries send_path context
    for row in send_assertions_table.inserts:
        assert row.get("assertion_context") == "send_path", (
            f"Assertion '{row.get('assertion')}' logged context "
            f"'{row.get('assertion_context')}' instead of 'send_path'"
        )
