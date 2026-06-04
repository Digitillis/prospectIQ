"""Tenant isolation tests.

Verifies that Database._filter_ws() fails closed (raises) when workspace_id
is absent, that workspace_id is applied to every scoped query, and that
cross-tenant IDOR attacks are rejected at the database helper layer.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from backend.app.core.database import Database, WorkspaceRequiredError


# ---------------------------------------------------------------------------
# Minimal query stub that records .eq() calls
# ---------------------------------------------------------------------------


class _Q:
    """Minimal query stub recording .eq() filter calls."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def eq(self, col: str, val: object) -> "_Q":
        self.calls.append((col, val))
        return self


# ---------------------------------------------------------------------------
# Move 1 — fail-closed _filter_ws
# ---------------------------------------------------------------------------


def test_filter_ws_raises_without_workspace_id():
    """`_filter_ws` must raise WorkspaceRequiredError when workspace_id is None."""
    db = Database.__new__(Database)
    db.workspace_id = None
    with pytest.raises(WorkspaceRequiredError):
        db._filter_ws(_Q())


def test_filter_ws_raises_with_empty_string_workspace_id():
    """`_filter_ws` must also raise for empty-string workspace_id."""
    db = Database.__new__(Database)
    db.workspace_id = ""
    with pytest.raises(WorkspaceRequiredError):
        db._filter_ws(_Q())


def test_filter_ws_applies_workspace_filter():
    """`_filter_ws` applies workspace_id as an .eq() filter."""
    db = Database.__new__(Database)
    db.workspace_id = "ws-test"
    q = _Q()
    result = db._filter_ws(q)
    assert ("workspace_id", "ws-test") in result.calls


def test_ws_property_raises_without_workspace_id():
    """`_ws` property raises WorkspaceRequiredError when workspace_id is None."""
    db = Database.__new__(Database)
    db.workspace_id = None
    with pytest.raises(WorkspaceRequiredError):
        _ = db._ws


def test_ws_property_returns_workspace_id():
    """`_ws` property returns the workspace_id string when set."""
    db = Database.__new__(Database)
    db.workspace_id = "ws-123"
    assert db._ws == "ws-123"


# ---------------------------------------------------------------------------
# Move 2 — IDOR scoping on individual methods
# ---------------------------------------------------------------------------


def _mock_db(workspace_id: str = "ws-a") -> Database:
    """Return a Database instance with a mocked Supabase client."""
    db = Database.__new__(Database)
    db.workspace_id = workspace_id
    db.client = MagicMock()
    # Default chain: table().select/update/etc().eq().eq().execute() returns empty
    chain = MagicMock()
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.is_.return_value = chain
    chain.not_.is_.return_value = chain
    chain.limit.return_value = chain
    chain.order.return_value = chain
    chain.lte.return_value = chain
    chain.lt.return_value = chain
    chain.execute.return_value = MagicMock(data=[], count=0)
    db.client.table.return_value.select.return_value = chain
    db.client.table.return_value.update.return_value = chain
    db.client.table.return_value.insert.return_value = chain
    db.client.table.return_value.delete.return_value = chain
    return db


def _eq_calls(mock_db: Database, method_name: str = "update") -> list[tuple]:
    """Return the .eq() call args from the most recent table chain method."""
    table_mock = mock_db.client.table.return_value
    chain = getattr(table_mock, method_name).return_value
    return [call.args for call in chain.eq.call_args_list]


def test_get_company_scoped_to_workspace():
    """get_company must filter by workspace_id, rejecting cross-tenant UUIDs."""
    db = _mock_db("ws-a")
    db.get_company("company-uuid-xyz")
    select_chain = db.client.table.return_value.select.return_value
    eq_args = [call.args for call in select_chain.eq.call_args_list]
    assert ("workspace_id", "ws-a") in eq_args, f"workspace_id not in eq() calls: {eq_args}"


def test_update_company_scoped_to_workspace():
    """update_company must filter by workspace_id to prevent cross-tenant mutation."""
    db = _mock_db("ws-a")
    db.update_company("company-uuid-xyz", {"status": "engaged"})
    update_chain = db.client.table.return_value.update.return_value
    eq_args = [call.args for call in update_chain.eq.call_args_list]
    assert ("workspace_id", "ws-a") in eq_args, f"workspace_id not in update eq() calls: {eq_args}"


def test_update_contact_scoped_to_workspace():
    """update_contact must filter by workspace_id."""
    db = _mock_db("ws-a")
    db.update_contact("contact-uuid-xyz", {"outreach_state": "replied"})
    update_chain = db.client.table.return_value.update.return_value
    eq_args = [call.args for call in update_chain.eq.call_args_list]
    assert ("workspace_id", "ws-a") in eq_args


def test_update_outreach_draft_scoped_to_workspace():
    """update_outreach_draft must filter by workspace_id."""
    db = _mock_db("ws-a")
    db.update_outreach_draft("draft-uuid-xyz", {"approval_status": "approved"})
    update_chain = db.client.table.return_value.update.return_value
    eq_args = [call.args for call in update_chain.eq.call_args_list]
    assert ("workspace_id", "ws-a") in eq_args


def test_update_engagement_sequence_scoped_to_workspace():
    """update_engagement_sequence must filter by workspace_id."""
    db = _mock_db("ws-a")
    db.update_engagement_sequence("seq-uuid-xyz", {"status": "cancelled"})
    update_chain = db.client.table.return_value.update.return_value
    eq_args = [call.args for call in update_chain.eq.call_args_list]
    assert ("workspace_id", "ws-a") in eq_args


def test_get_company_wrong_workspace_returns_none():
    """get_company with a UUID from a different workspace must return None.

    Simulates: db = Database(workspace_id="ws-a") trying to read a company
    that belongs to "ws-b". The workspace filter causes 0 rows returned.
    """
    db = _mock_db("ws-a")
    # The mock returns empty data by default (simulating no row found because
    # the workspace_id filter excludes it)
    result = db.get_company("uuid-from-ws-b")
    assert result is None


def test_update_company_wrong_workspace_returns_empty():
    """update_company with a UUID from a different workspace must return {} (no rows updated)."""
    db = _mock_db("ws-a")
    result = db.update_company("uuid-from-ws-b", {"status": "not_interested"})
    assert result == {}


# ---------------------------------------------------------------------------
# Two-workspace isolation
# ---------------------------------------------------------------------------


def test_two_workspace_filter_isolation():
    """Database(workspace_id=A)._filter_ws produces a filter distinct from ws-B.

    Verifies the filter value matches the constructor argument, so two Database
    instances with different workspace_ids produce disjoint queries.
    """
    q_a = _Q()
    q_b = _Q()

    db_a = Database.__new__(Database)
    db_a.workspace_id = "ws-a"

    db_b = Database.__new__(Database)
    db_b.workspace_id = "ws-b"

    db_a._filter_ws(q_a)
    db_b._filter_ws(q_b)

    assert ("workspace_id", "ws-a") in q_a.calls
    assert ("workspace_id", "ws-b") in q_b.calls
    # The two filters use different values
    assert ("workspace_id", "ws-b") not in q_a.calls
    assert ("workspace_id", "ws-a") not in q_b.calls


# ---------------------------------------------------------------------------
# Move 4 — BaseAgent workspace requirement
# ---------------------------------------------------------------------------


def test_base_agent_requires_workspace_id():
    """BaseAgent must raise WorkspaceRequiredError when no workspace_id is provided."""
    import os
    from backend.app.agents.base import BaseAgent

    class _ConcreteAgent(BaseAgent):
        agent_name = "test"

        def run(self, **kwargs):
            pass

    # No WORKSPACE_ID env var, no explicit workspace_id
    old_env = os.environ.pop("WORKSPACE_ID", None)
    try:
        with pytest.raises(WorkspaceRequiredError):
            _ConcreteAgent()
    finally:
        if old_env is not None:
            os.environ["WORKSPACE_ID"] = old_env


def test_base_agent_accepts_explicit_workspace_id():
    """BaseAgent must succeed when workspace_id is passed explicitly."""
    from backend.app.agents.base import BaseAgent
    from unittest.mock import patch

    class _ConcreteAgent(BaseAgent):
        agent_name = "test"

        def run(self, **kwargs):
            pass

    with patch("backend.app.core.database.get_supabase_client"):
        agent = _ConcreteAgent(workspace_id="ws-explicit")
    assert agent.workspace_id == "ws-explicit"


def test_base_agent_accepts_env_workspace_id():
    """BaseAgent must succeed when WORKSPACE_ID env var is set."""
    import os
    from backend.app.agents.base import BaseAgent
    from unittest.mock import patch

    class _ConcreteAgent(BaseAgent):
        agent_name = "test"

        def run(self, **kwargs):
            pass

    with (
        patch("backend.app.core.database.get_supabase_client"),
        patch.dict(os.environ, {"WORKSPACE_ID": "ws-from-env"}),
    ):
        agent = _ConcreteAgent()
    assert agent.workspace_id == "ws-from-env"


def test_default_workspace_id_constant_removed():
    """The hardcoded _DEFAULT_WORKSPACE_ID must not exist in base.py."""
    import backend.app.agents.base as base_mod

    assert not hasattr(base_mod, "_DEFAULT_WORKSPACE_ID"), (
        "_DEFAULT_WORKSPACE_ID still present in base.py — hardcoded fallback not removed"
    )
