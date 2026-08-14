"""is_suppressed() must actually consult do_not_contact and contact-scope
suppression_log — previously it only checked contacts.status and
suppression_log at scope='company', so a DNC entry (e.g. written by
backend/app/core/unsubscribe.py's record_unsubscribe()) blocked nothing at
send time. See backend/app/core/suppression.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _FakeQuery:
    """Chainable stand-in for a Supabase query builder. Every method that
    doesn't terminate the chain returns self; .execute() returns the
    pre-configured result for whichever call this is.
    """

    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        result = MagicMock()
        result.data = self._data
        return result


def _make_db(
    *,
    company: dict,
    company_suppression: list | None = None,
    contact: dict | None = None,
    dnc: list | None = None,
    contact_suppression: list | None = None,
    research: dict | None = None,
) -> MagicMock:
    """Build a Database mock whose .client.table(name) routes to the right
    canned response based on table name and (for `contacts` vs
    `do_not_contact` vs `suppression_log`, which are all queried in
    sequence) call order isn't relied upon — routing is purely by name.
    """
    db = MagicMock()
    db.workspace_id = "ws-1"
    db.get_company.return_value = company
    db.get_research.return_value = research or {}

    tables = {
        "suppression_log": iter(
            [_FakeQuery(company_suppression or []), _FakeQuery(contact_suppression or [])]
        ),
        "contacts": _FakeQuery([contact] if contact else []),
        "do_not_contact": _FakeQuery(dnc or []),
    }

    def _table(name):
        if name == "suppression_log":
            return next(tables["suppression_log"])
        return tables[name]

    db.client.table.side_effect = _table
    return db


def test_dnc_email_match_suppresses():
    from backend.app.core.suppression import is_suppressed

    db = _make_db(
        company={"status": "active"},
        contact={"id": "ct-1", "email": "person@example.com", "status": "active"},
        dnc=[{"id": "d-1", "reason": "unsubscribed", "email": "person@example.com", "domain": None}],
    )

    suppressed, reason = is_suppressed(db, "co-1", contact_id="ct-1")

    assert suppressed is True
    assert "do_not_contact" in reason
    assert "unsubscribed" in reason


def test_dnc_domain_match_suppresses():
    from backend.app.core.suppression import is_suppressed

    db = _make_db(
        company={"status": "active"},
        contact={"id": "ct-1", "email": "person@blocked-domain.com", "status": "active"},
        dnc=[{"id": "d-1", "reason": "legal_hold", "email": None, "domain": "blocked-domain.com"}],
    )

    suppressed, reason = is_suppressed(db, "co-1", contact_id="ct-1")

    assert suppressed is True
    assert "do_not_contact" in reason
    assert "legal_hold" in reason


def test_contact_scope_suppression_log_suppresses():
    """A scope='contact' suppression_log row (e.g. written by a manual
    unsubscribe or the one-click unsubscribe flow) must block — previously
    is_suppressed() only ever queried scope='company'.
    """
    from backend.app.core.suppression import is_suppressed

    db = _make_db(
        company={"status": "active"},
        contact={"id": "ct-1", "email": "person@example.com", "status": "active"},
        contact_suppression=[{"reason": "unsubscribe"}],
    )

    suppressed, reason = is_suppressed(db, "co-1", contact_id="ct-1")

    assert suppressed is True
    assert "unsubscribe" in reason


def test_no_dnc_or_suppression_entry_is_not_suppressed_on_those_grounds():
    """Sanity check: a clean contact with no DNC/suppression rows isn't
    blocked by the new checks (other steps in is_suppressed may still apply,
    but none of those are configured to fire in this fixture).
    """
    from backend.app.core.suppression import is_suppressed

    db = _make_db(
        company={"status": "active"},
        contact={"id": "ct-1", "email": "person@example.com", "status": "active"},
    )
    db.get_sequence_state = MagicMock(return_value=None)

    suppressed, reason = is_suppressed(db, "co-1", contact_id="ct-1", skip_duplicate_check=True)

    # Whatever the final verdict, it must not be attributed to do_not_contact
    # or a contact-scope suppression_log row, since none exist in this fixture.
    if suppressed:
        assert "do_not_contact" not in (reason or "")
        assert not (reason or "").startswith("suppression_log:unsubscribe")
