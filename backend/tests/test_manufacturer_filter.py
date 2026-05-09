"""Tests for the manufacturer-only structural filter (P3.2).

Covers:
  - Pure helper: is_manufacturer_company(company)
  - Database.get_companies() applies the filter via a fake supabase-like
    query chain. We seed a non-manufacturer company (tier='non_mfg'), a
    null-tier company, and a manufacturer (tier='mfg1'), then assert the
    orchestrator pull only returns the manufacturer.
"""

from __future__ import annotations

import pytest

from backend.app.core.contact_filter import is_manufacturer_company


# -----------------------------
# is_manufacturer_company helper
# -----------------------------

@pytest.mark.parametrize("tier", ["mfg1", "mfg3", "fb_dairy", "pmfg1", "1", "2"])
def test_manufacturer_tiers_pass(tier: str) -> None:
    assert is_manufacturer_company({"tier": tier}) is True


@pytest.mark.parametrize("tier", ["non_mfg", "Non_MFG", "NON_MFG"])
def test_non_mfg_blocked(tier: str) -> None:
    assert is_manufacturer_company({"tier": tier}) is False


def test_null_tier_blocked() -> None:
    assert is_manufacturer_company({"tier": None}) is False
    assert is_manufacturer_company({"tier": ""}) is False
    assert is_manufacturer_company({}) is False
    assert is_manufacturer_company(None) is False


# ----------------------------------------------------------
# Fake supabase-like client to exercise Database.get_companies
# ----------------------------------------------------------

class _FakeQuery:
    """Records filter calls and returns rows matching the predicates.

    Supports the small subset of supabase-py methods used by get_companies():
    .select, .eq, .in_, .neq, .is_ via .not_.is_(...), .gte, .ilike, .order,
    .range, .execute. The chain returns self so it's chainable.
    """

    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self._eq: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._neq: list[tuple[str, object]] = []
        self._is_null: list[str] = []
        self._not_is_null: list[str] = []
        self.not_ = self._NotChain(self)

    class _NotChain:
        def __init__(self, parent: "_FakeQuery") -> None:
            self._parent = parent

        def is_(self, col: str, val):
            # supabase syntax: not_.is_(col, "null") = "WHERE col IS NOT NULL"
            assert val == "null", f"unsupported not_.is_ value: {val}"
            self._parent._not_is_null.append(col)
            return self._parent

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, col, val):
        self._eq.append((col, val))
        return self

    def in_(self, col, vals):
        self._in.append((col, list(vals)))
        return self

    def neq(self, col, val):
        self._neq.append((col, val))
        return self

    def is_(self, col, val):
        # Used directly: query.is_(col, "null")
        assert val == "null"
        self._is_null.append(col)
        return self

    def gte(self, col, val):
        return self  # not exercised in this test

    def ilike(self, col, pattern):
        return self  # not exercised

    def order(self, col, desc=False):
        return self

    def range(self, start, end):
        # No real paging — the in-memory data is small
        return self

    def limit(self, n):
        return self

    def offset(self, n):
        return self

    def execute(self):
        rows = list(self.rows)
        for col, val in self._eq:
            rows = [r for r in rows if r.get(col) == val]
        for col, vals in self._in:
            rows = [r for r in rows if r.get(col) in vals]
        for col, val in self._neq:
            rows = [r for r in rows if r.get(col) != val]
        for col in self._is_null:
            rows = [r for r in rows if r.get(col) is None]
        for col in self._not_is_null:
            rows = [r for r in rows if r.get(col) is not None]

        class _R:
            def __init__(self, data):
                self.data = data
                self.count = len(data)
        return _R(rows)


class _FakeClient:
    def __init__(self, rows_by_table: dict[str, list[dict]]) -> None:
        self._rows_by_table = rows_by_table

    def table(self, name: str):
        return _FakeQuery(self._rows_by_table.get(name, []))


def test_orchestrator_pull_excludes_non_manufacturer(monkeypatch) -> None:
    """A non-manufacturer (tier='non_mfg') must not appear in the
    orchestrator pull, even with an OK status and PQS.
    """
    from backend.app.core.database import Database

    seeded = [
        {"id": "co-mfg",   "name": "Big Mfg",   "tier": "mfg1",     "status": "qualified", "pqs_total": 50, "workspace_id": "ws"},
        {"id": "co-fb",    "name": "Dairy Co",  "tier": "fb_dairy", "status": "qualified", "pqs_total": 60, "workspace_id": "ws"},
        {"id": "co-non",   "name": "Health Co", "tier": "non_mfg",  "status": "qualified", "pqs_total": 80, "workspace_id": "ws"},
        {"id": "co-null",  "name": "Unknown",   "tier": None,       "status": "qualified", "pqs_total": 70, "workspace_id": "ws"},
    ]

    fake = _FakeClient({"companies": seeded})

    db = Database.__new__(Database)
    db.client = fake
    db.workspace_id = "ws"
    db._workspace_id = "ws"

    # Patch _filter_ws to be a no-op pass-through (it normally uses workspace_id)
    db._filter_ws = lambda q: q

    rows = db.get_companies(status="qualified", limit=10, oec_only=False)

    ids = sorted(r["id"] for r in rows)
    assert "co-non" not in ids, "Non-manufacturer must be excluded"
    assert "co-null" not in ids, "Null-tier company must be excluded"
    assert "co-mfg" in ids
    assert "co-fb"  in ids
