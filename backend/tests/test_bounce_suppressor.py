"""Tests for bounce suppression hygiene.

Exercises ``run_bounce_suppression`` against a fake supabase-like client so
we can verify the contact updates, DNC inserts, and per-domain threshold
without hitting the live database.
"""

from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake supabase client
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, data: list[dict[str, Any]] | None = None, count: int | None = None):
        self.data = data or []
        self.count = count


class _Query:
    """Records the chain of select/filter calls then returns the seeded rows."""

    def __init__(self, table: "_Table", op: str = "select"):
        self.table = table
        self.op = op
        self._filters: list[tuple[str, Any]] = []
        self._payload: dict | list | None = None

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

    def upsert(self, payload, **_kwargs):
        self.op = "upsert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def ilike(self, col, val):
        self._filters.append(("ilike", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    @property
    def not_(self):
        # Allow .not_.is_(col, "null") chains to no-op as "non null"
        return _NotProxy(self)

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def range(self, start, _end):
        self._range = (start, _end)
        return self

    def execute(self) -> _Result:
        return self.table._dispatch(self)


class _NotProxy:
    def __init__(self, q: _Query):
        self.q = q

    def is_(self, col, _val):
        self.q._filters.append(("not_null", col, None))
        return self.q


class _Table:
    def __init__(self, db: "_FakeClient", name: str):
        self.db = db
        self.name = name

    def select(self, *args, **kwargs):
        q = _Query(self, "select")
        return q.select(*args, **kwargs)

    def insert(self, payload):
        return _Query(self, "insert").insert(payload)

    def update(self, payload):
        return _Query(self, "update").update(payload)

    def upsert(self, payload, **kwargs):
        return _Query(self, "upsert").upsert(payload, **kwargs)

    def _dispatch(self, q: _Query) -> _Result:
        rows = self.db._tables.get(self.name, [])
        if q.op == "select":
            filtered = list(rows)
            for f in q._filters:
                if f[0] == "not_null":
                    filtered = [r for r in filtered if r.get(f[1]) is not None]
                elif f[0] == "eq":
                    filtered = [r for r in filtered if r.get(f[1]) == f[2]]
                elif f[0] == "in":
                    filtered = [r for r in filtered if r.get(f[1]) in f[2]]
                elif f[0] == "ilike":
                    needle = (f[2] or "").lower()
                    filtered = [r for r in filtered if (r.get(f[1]) or "").lower() == needle]

            # Hydrate the contacts(...) join used by the SUT
            if self.name == "outreach_drafts":
                contacts = {c["id"]: c for c in self.db._tables.get("contacts", [])}
                for r in filtered:
                    if r.get("contact_id"):
                        r = dict(r)
                        r["contacts"] = contacts.get(r["contact_id"])
                # Mutate filtered with hydrated copies
                filtered = [
                    {**r, "contacts": contacts.get(r.get("contact_id"))}
                    for r in filtered
                ]
            return _Result(filtered)

        if q.op == "insert":
            payload = q._payload
            payload_list = payload if isinstance(payload, list) else [payload]
            self.db._inserts.setdefault(self.name, []).extend(payload_list)
            self.db._tables.setdefault(self.name, []).extend(payload_list)
            return _Result(payload_list)

        if q.op == "update":
            payload = q._payload or {}
            updated: list[dict] = []
            for r in self.db._tables.get(self.name, []):
                ok = True
                for f in q._filters:
                    if f[0] == "eq" and r.get(f[1]) != f[2]:
                        ok = False
                        break
                if ok:
                    r.update(payload)
                    updated.append(r)
            self.db._updates.setdefault(self.name, []).append({"payload": payload, "filters": q._filters})
            return _Result(updated)

        if q.op == "upsert":
            payload = q._payload
            payload_list = payload if isinstance(payload, list) else [payload]
            self.db._tables.setdefault(self.name, []).extend(payload_list)
            return _Result(payload_list)

        return _Result([])


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self._inserts: dict[str, list[dict]] = {}
        self._updates: dict[str, list[dict]] = {}

    def table(self, name: str) -> _Table:
        return _Table(self, name)


class _FakeDatabase:
    """Stand-in for backend.app.core.database.Database used by the SUT."""

    def __init__(self, client: _FakeClient, workspace_id: str):
        self.client = client
        self.workspace_id = workspace_id

    def _filter_ws(self, query):
        return query.eq("workspace_id", self.workspace_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


WS = "00000000-0000-0000-0000-000000000001"


def _make_db(contacts: list[dict], drafts: list[dict], dnc: list[dict] | None = None):
    client = _FakeClient({
        "contacts": contacts,
        "outreach_drafts": drafts,
        "do_not_contact": dnc or [],
    })
    return _FakeDatabase(client, WS), client


def test_no_bounced_drafts_returns_empty_summary():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    db, _ = _make_db([], [])
    summary = run_bounce_suppression(db)
    assert summary["contacts_suppressed"] == 0
    assert summary["domains_suppressed"] == 0
    assert summary["already_suppressed"] == 0
    assert summary["errors"] == []


def test_single_bounce_suppresses_contact_and_inserts_dnc():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    contacts = [{
        "id": "c1",
        "email": "vp.ops@acme.com",
        "status": "active",
        "is_outreach_eligible": True,
    }]
    drafts = [{
        "id": "d1",
        "contact_id": "c1",
        "workspace_id": WS,
        "bounced_at": "2026-05-08T10:00:00+00:00",
    }]

    db, client = _make_db(contacts, drafts)
    summary = run_bounce_suppression(db)

    assert summary["contacts_suppressed"] == 1
    assert summary["domains_suppressed"] == 0
    assert summary["already_suppressed"] == 0
    assert client._tables["contacts"][0]["status"] == "bounced"
    assert client._tables["contacts"][0]["is_outreach_eligible"] is False
    inserts = client._inserts.get("do_not_contact", [])
    assert len(inserts) == 1
    assert inserts[0]["email"] == "vp.ops@acme.com"
    assert inserts[0]["reason"] == "bounced"
    assert inserts[0]["workspace_id"] == WS


def test_already_suppressed_is_skipped():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    contacts = [{
        "id": "c1",
        "email": "vp.ops@acme.com",
        "status": "bounced",
        "is_outreach_eligible": False,
    }]
    drafts = [{
        "id": "d1",
        "contact_id": "c1",
        "workspace_id": WS,
        "bounced_at": "2026-05-08T10:00:00+00:00",
    }]
    dnc = [{"email": "vp.ops@acme.com", "reason": "bounced"}]

    db, client = _make_db(contacts, drafts, dnc=dnc)
    summary = run_bounce_suppression(db)
    assert summary["contacts_suppressed"] == 0
    assert summary["already_suppressed"] == 1
    assert client._inserts.get("do_not_contact", []) == []


def test_three_bounces_in_same_domain_blocks_domain():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    contacts = [
        {"id": f"c{i}", "email": f"u{i}@badmx.com", "status": "active", "is_outreach_eligible": True}
        for i in range(3)
    ]
    drafts = [
        {"id": f"d{i}", "contact_id": f"c{i}", "workspace_id": WS, "bounced_at": "2026-05-08T10:00:00+00:00"}
        for i in range(3)
    ]

    db, client = _make_db(contacts, drafts)
    summary = run_bounce_suppression(db)

    assert summary["contacts_suppressed"] == 3
    assert summary["domains_suppressed"] == 1
    inserts = client._inserts.get("do_not_contact", [])
    domain_inserts = [i for i in inserts if i.get("domain")]
    assert len(domain_inserts) == 1
    assert domain_inserts[0]["domain"] == "badmx.com"
    assert domain_inserts[0]["reason"] == "bounced_domain"
    assert domain_inserts[0]["workspace_id"] == WS


def test_two_bounces_in_same_domain_does_not_block_domain():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    contacts = [
        {"id": f"c{i}", "email": f"u{i}@borderline.com", "status": "active", "is_outreach_eligible": True}
        for i in range(2)
    ]
    drafts = [
        {"id": f"d{i}", "contact_id": f"c{i}", "workspace_id": WS, "bounced_at": "2026-05-08T10:00:00+00:00"}
        for i in range(2)
    ]

    db, client = _make_db(contacts, drafts)
    summary = run_bounce_suppression(db)
    assert summary["contacts_suppressed"] == 2
    assert summary["domains_suppressed"] == 0


def test_missing_workspace_id_returns_error():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    db, _ = _make_db([], [])
    db.workspace_id = None
    summary = run_bounce_suppression(db)
    assert summary["errors"] == ["missing_workspace_id"]


def test_drafts_without_contact_email_are_skipped():
    from backend.app.core.bounce_suppressor import run_bounce_suppression

    contacts = [{"id": "c1", "email": None, "status": "active", "is_outreach_eligible": True}]
    drafts = [{"id": "d1", "contact_id": "c1", "workspace_id": WS, "bounced_at": "2026-05-08T10:00:00+00:00"}]

    db, client = _make_db(contacts, drafts)
    summary = run_bounce_suppression(db)
    assert summary["contacts_suppressed"] == 0
    assert client._inserts.get("do_not_contact", []) == []
