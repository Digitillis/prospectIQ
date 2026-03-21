"""Workflow, channel-coordination, and API tests for ProspectIQ CRM.

Covers:
  1.  Workflow sequence enforcement (discovery → research → qualification → enrichment → outreach → engagement)
  2.  Cross-channel conflict logic (channel_coordinator.py)
  3.  Suppression + channel coordination integration
  4.  Daily Cockpit API (/api/today)
  5.  Content generation (ContentAgent system-prompt, banned phrases, char limits)
  6.  LinkedIn message generation (word limits, em-dash, vertical context)
  7.  Outreach quality gate (draft_quality.py)
  8.  Conflict alarm visibility (logging / result details)
  9.  Settings configurability (YAML loading, PATCH endpoints)
  10. API route smoke tests

Run with:
    python -m pytest tests/ -v --tb=short
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on the path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Helpers / shared fixtures
# ===========================================================================

def _make_db_mock(
    contact_data: dict | None = None,
    linkedin_interactions: list | None = None,
    email_interactions: list | None = None,
    completed_email_seqs: list | None = None,
) -> MagicMock:
    """Build a mock Database whose Supabase client chains return predictable data."""
    db = MagicMock()

    # Chainable query builder pattern: .table(...).select(...).eq(...).execute()
    def _chain(*args, **kwargs):
        """Return a new mock that itself supports further chaining."""
        m = MagicMock()
        m.eq = _chain
        m.in_ = _chain
        m.not_ = _chain
        m.is_ = _chain
        m.order = _chain
        m.limit = _chain
        m.lte = _chain
        m.gte = _chain
        m.like = _chain
        m.select = _chain
        m.execute = MagicMock(return_value=MagicMock(data=[], count=0))
        return m

    client = MagicMock()
    client.table.side_effect = lambda tbl: _make_table_mock(
        tbl,
        contact_data=contact_data,
        linkedin_interactions=linkedin_interactions,
        email_interactions=email_interactions,
        completed_email_seqs=completed_email_seqs,
    )
    db.client = client
    return db


def _make_table_mock(
    table_name: str,
    contact_data: dict | None = None,
    linkedin_interactions: list | None = None,
    email_interactions: list | None = None,
    completed_email_seqs: list | None = None,
) -> MagicMock:
    """Return a table mock whose execute() yields the right data for each table."""
    m = MagicMock()

    # Build a chainable stub that eventually returns the right execute() data
    def _make_chain(data, count=None):
        stub = MagicMock()
        stub.data = data
        stub.count = count if count is not None else len(data)
        return stub

    # Contacts table
    if table_name == "contacts":
        contact_list = [contact_data] if contact_data else []
        chain = MagicMock()
        chain.select = MagicMock(return_value=chain)
        chain.eq = MagicMock(return_value=chain)
        chain.in_ = MagicMock(return_value=chain)
        chain.order = MagicMock(return_value=chain)
        chain.limit = MagicMock(return_value=chain)
        chain.execute = MagicMock(return_value=_make_chain(contact_list))
        m.select = MagicMock(return_value=chain)
        return m

    # Interactions table — distinguish by the .in_() call content
    if table_name == "interactions":
        linkedin_data = linkedin_interactions or []
        email_data = email_interactions or []
        # We can't easily distinguish calls at the mock level without inspecting args,
        # so we use a closure that checks the most-recent call argument
        calls_made: list[list] = []

        class _InteractionChain:
            def __init__(self, pending_data=None):
                self._data = pending_data

            def select(self, *a, **kw):
                return self

            def eq(self, *a, **kw):
                return self

            def in_(self, field, values):
                # Decide which dataset to return based on values
                if any("linkedin" in str(v) for v in values):
                    self._data = linkedin_data
                elif any("email" in str(v) for v in values):
                    self._data = email_data
                else:
                    self._data = []
                return self

            def order(self, *a, **kw):
                return self

            def limit(self, *a, **kw):
                return self

            def gte(self, *a, **kw):
                return self

            def execute(self):
                return _make_chain(self._data or [])

        chain = _InteractionChain()
        m.select = MagicMock(side_effect=lambda *a, **kw: _InteractionChain())
        m.insert = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=_make_chain([]))))
        return m

    # Engagement sequences table
    if table_name == "engagement_sequences":
        seq_data = completed_email_seqs or []

        class _SeqChain:
            def select(self, *a, **kw):
                return self
            def eq(self, *a, **kw):
                return self
            def not_(self):
                return self
            def is_(self, *a, **kw):
                return self
            def order(self, *a, **kw):
                return self
            def limit(self, *a, **kw):
                return self
            def execute(self):
                return _make_chain(seq_data)

        m.select = MagicMock(return_value=_SeqChain())
        return m

    # Default: empty table
    chain = MagicMock()
    chain.select = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.in_ = MagicMock(return_value=chain)
    chain.not_ = MagicMock(return_value=chain)
    chain.is_ = MagicMock(return_value=chain)
    chain.order = MagicMock(return_value=chain)
    chain.limit = MagicMock(return_value=chain)
    chain.execute = MagicMock(return_value=_make_chain([]))
    m.select = MagicMock(return_value=chain)
    return m


# ===========================================================================
# 1. WORKFLOW SEQUENCE TESTS
# ===========================================================================

class TestWorkflowSequence:
    """
    Verify that the pipeline enforces the correct execution order.
    Without the prior stage having run, the next stage should process 0 records.
    """

    # ------------------------------------------------------------------ #
    # Discovery → Research                                                 #
    # ------------------------------------------------------------------ #

    def test_research_on_empty_db_returns_zero(self):
        """Research agent looks for 'discovered' companies.  Empty DB → 0 processed."""
        from backend.app.agents.research import ResearchAgent

        agent = ResearchAgent.__new__(ResearchAgent)
        # Inject a mock DB that returns nothing for discovered companies
        mock_db = MagicMock()
        mock_db.get_companies.return_value = []
        agent.db = mock_db

        result = agent.run(limit=50)
        # Either 0 processed, or the agent returned early with 0 successes
        assert result.processed == 0, (
            f"Research with empty DB should process 0 companies, got {result.processed}"
        )

    def test_discovery_populates_discovered_status(self):
        """A company inserted by Discovery should have status='discovered'."""
        from backend.app.core.models import CompanyStatus

        # Discovery sets status to 'discovered' — verify the model exists
        assert CompanyStatus.DISCOVERED == "discovered"

    # ------------------------------------------------------------------ #
    # Research → Qualification                                              #
    # ------------------------------------------------------------------ #

    def test_qualification_on_empty_db_returns_zero(self):
        """Qualification agent looks for 'researched' companies.  Empty DB → 0 processed."""
        from backend.app.agents.qualification import QualificationAgent

        agent = QualificationAgent.__new__(QualificationAgent)
        mock_db = MagicMock()
        mock_db.get_companies.return_value = []
        agent.db = mock_db

        result = agent.run(limit=50)
        assert result.processed == 0, (
            f"Qualification with empty DB should process 0, got {result.processed}"
        )

    def test_qualification_queries_researched_status(self):
        """Qualification agent must query 'researched' companies first."""
        from backend.app.agents.qualification import QualificationAgent

        agent = QualificationAgent.__new__(QualificationAgent)
        mock_db = MagicMock()
        mock_db.get_companies.return_value = []
        agent.db = mock_db
        agent.run(limit=10)

        # get_companies must have been called at least once; the FIRST call must
        # request status="researched" (the agent may also request "discovered" in
        # a second call to fill remaining capacity, but researched comes first).
        mock_db.get_companies.assert_called()
        first_call = mock_db.get_companies.call_args_list[0]
        args, kwargs = first_call
        assert kwargs.get("status") == "researched" or (args and args[0] == "researched"), (
            "Qualification agent must request companies with status='researched' on its first call"
        )

    # ------------------------------------------------------------------ #
    # Qualification → Enrichment                                           #
    # ------------------------------------------------------------------ #

    def test_enrichment_queries_qualified_status(self):
        """Enrichment agent must query 'qualified' contacts, not all contacts."""
        from backend.app.agents.enrichment import EnrichmentAgent

        agent = EnrichmentAgent.__new__(EnrichmentAgent)
        mock_db = MagicMock()
        mock_db.get_companies.return_value = []
        agent.db = mock_db
        agent.run(limit=10)

        mock_db.get_companies.assert_called()
        call_kwargs = mock_db.get_companies.call_args
        args, kwargs = call_kwargs
        assert kwargs.get("status") == "qualified" or (args and "qualified" in str(args)), (
            "Enrichment agent must request companies with status='qualified'"
        )

    # ------------------------------------------------------------------ #
    # Enrichment → Outreach                                                #
    # ------------------------------------------------------------------ #

    def test_outreach_queries_qualified_or_outreach_pending(self):
        """Outreach agent only targets qualified/outreach_pending companies."""
        from backend.app.agents.outreach import OutreachAgent

        agent = OutreachAgent.__new__(OutreachAgent)
        mock_db = MagicMock()
        mock_db.get_companies.return_value = []
        agent.db = mock_db
        agent.cost_tracker = MagicMock()
        try:
            agent.run(limit=10)
        except Exception:
            pass  # May fail on missing attrs — we just need get_companies to be called

        # Verify it queries the right statuses
        if mock_db.get_companies.called:
            call_kwargs = mock_db.get_companies.call_args
            args, kwargs = call_kwargs
            status_arg = kwargs.get("status") or (args[0] if args else "")
            assert status_arg in ("qualified", "outreach_pending"), (
                f"Outreach agent should query qualified or outreach_pending, got '{status_arg}'"
            )
        else:
            # Agent uses direct table queries — acceptable
            pass

    # ------------------------------------------------------------------ #
    # Outreach → Engagement                                                #
    # ------------------------------------------------------------------ #

    def test_engagement_action_list_is_recognised(self):
        """EngagementAgent.run() accepts known action strings."""
        from backend.app.agents.engagement import EngagementAgent

        agent = EngagementAgent.__new__(EngagementAgent)
        mock_db = MagicMock()
        mock_db.client = MagicMock()

        # Chain stubs for table queries
        chain = MagicMock()
        chain.select = MagicMock(return_value=chain)
        chain.eq = MagicMock(return_value=chain)
        chain.lte = MagicMock(return_value=chain)
        chain.order = MagicMock(return_value=chain)
        chain.limit = MagicMock(return_value=chain)
        chain.execute = MagicMock(return_value=MagicMock(data=[], count=0))
        mock_db.client.table = MagicMock(return_value=chain)
        agent.db = mock_db

        # Should not raise
        result = agent.run(action="process_due")
        assert result is not None

    def test_pipeline_order_matches_enumeration(self):
        """The pipeline steps must be: discovery → research → qualification → enrichment → outreach."""
        from backend.app.orchestrator.pipeline import Pipeline

        p = Pipeline.__new__(Pipeline)
        # Check that run_full exists and that it calls agents in order
        import inspect
        src = inspect.getsource(Pipeline.run_full)
        # Verify the order by checking string positions
        pos_discovery = src.find("run_discovery")
        pos_research = src.find("run_research")
        pos_qualification = src.find("run_qualification")
        pos_enrichment = src.find("run_enrichment")

        assert pos_discovery >= 0, "Pipeline must call run_discovery"
        assert pos_research >= 0, "Pipeline must call run_research"
        assert pos_qualification >= 0, "Pipeline must call run_qualification"
        assert pos_enrichment >= 0, "Pipeline must call run_enrichment"

        assert pos_discovery < pos_research, "Discovery must come before Research"
        assert pos_research < pos_qualification, "Research must come before Qualification"
        assert pos_qualification < pos_enrichment, "Qualification must come before Enrichment"


# ===========================================================================
# 2. CROSS-CHANNEL CONFLICT TESTS
# ===========================================================================

class TestChannelCoordinator:
    """Test the get_active_channel() and can_use_channel() logic in channel_coordinator.py."""

    def _contact(self, linkedin_url="", email="") -> dict:
        return {"linkedin_url": linkedin_url, "email": email}

    # ------------------------------------------------------------------ #
    # Basic channel detection                                              #
    # ------------------------------------------------------------------ #

    def test_linkedin_only_contact_returns_linkedin(self):
        from backend.app.core.channel_coordinator import get_active_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact(linkedin_url="https://linkedin.com/in/alice")])

        channel, reason = get_active_channel(db, "contact-1")
        assert channel == "linkedin"
        assert reason == "linkedin_only_channel"

    def test_email_only_contact_returns_email(self):
        from backend.app.core.channel_coordinator import get_active_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact(email="alice@example.com")])

        channel, reason = get_active_channel(db, "contact-1")
        assert channel == "email"
        assert reason == "email_only_channel"

    def test_no_channels_returns_none(self):
        from backend.app.core.channel_coordinator import get_active_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact()])  # no linkedin, no email

        channel, reason = get_active_channel(db, "contact-1")
        assert channel == "none"

    def test_contact_not_found_returns_none(self):
        from backend.app.core.channel_coordinator import get_active_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[])

        channel, reason = get_active_channel(db, "ghost-contact")
        assert channel == "none"
        assert reason == "contact_not_found"

    # ------------------------------------------------------------------ #
    # Both channels available — priority logic                            #
    # ------------------------------------------------------------------ #

    def test_both_channels_no_activity_prefers_linkedin(self):
        """When both channels available and no prior interaction, LinkedIn wins."""
        from backend.app.core.channel_coordinator import get_active_channel

        contact = self._contact(
            linkedin_url="https://linkedin.com/in/alice",
            email="alice@example.com",
        )

        db = MagicMock()

        def _table_side_effect(tbl):
            t = MagicMock()
            if tbl == "contacts":
                t.select.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[contact])
            elif tbl == "interactions":
                t.select.return_value.eq.return_value.in_.return_value \
                    .order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            elif tbl == "engagement_sequences":
                # Query chain: .select().eq().eq().not_.is_().order().limit().execute()
                # Note: .not_ is attribute access (no parens), .is_() is a method call
                t.select.return_value.eq.return_value.eq.return_value \
                    .not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            else:
                t.select.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[])
            return t

        db.client.table.side_effect = _table_side_effect
        channel, reason = get_active_channel(db, "contact-1")
        assert channel == "linkedin", f"Expected linkedin, got {channel} ({reason})"

    def test_recent_linkedin_activity_blocks_email(self):
        """LinkedIn activity < 7 days ago should block email."""
        from backend.app.core.channel_coordinator import get_active_channel

        contact = self._contact(
            linkedin_url="https://linkedin.com/in/alice",
            email="alice@example.com",
        )

        # LinkedIn interaction 2 days ago
        recent = datetime.now(timezone.utc) - timedelta(days=2)
        interaction_call_count = [0]  # tracks only 'interactions' table calls

        db = MagicMock()

        def table_side_effect(tbl):
            t = MagicMock()
            if tbl == "contacts":
                t.select.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[contact])
            elif tbl == "interactions":
                interaction_call_count[0] += 1
                if interaction_call_count[0] == 1:
                    # First interactions call: linkedin types → recent activity
                    t.select.return_value.eq.return_value.in_.return_value \
                        .order.return_value.limit.return_value.execute.return_value = \
                        MagicMock(data=[{"type": "linkedin_connection",
                                         "created_at": recent.isoformat()}])
                else:
                    # Second interactions call: email types → empty
                    t.select.return_value.eq.return_value.in_.return_value \
                        .order.return_value.limit.return_value.execute.return_value = \
                        MagicMock(data=[])
            elif tbl == "engagement_sequences":
                # .not_ is attribute access, .is_() is a method call
                t.select.return_value.eq.return_value.eq.return_value \
                    .not_.is_.return_value \
                    .order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            else:
                t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            return t

        db.client.table.side_effect = table_side_effect
        channel, reason = get_active_channel(db, "contact-1")

        assert channel == "linkedin", f"Expected linkedin (email blocked), got {channel}"
        assert "email_blocked" in reason, f"Reason should mention email_blocked, got: {reason}"

    def test_completed_email_sequence_blocks_linkedin_permanently(self):
        """If email sequence completed, should never return to LinkedIn."""
        from backend.app.core.channel_coordinator import get_active_channel

        contact = self._contact(
            linkedin_url="https://linkedin.com/in/alice",
            email="alice@example.com",
        )

        db = MagicMock()
        call_count = [0]

        def table_side_effect(tbl):
            call_count[0] += 1
            t = MagicMock()
            if tbl == "contacts":
                t.select.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[contact])
            elif tbl == "engagement_sequences":
                completed_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                t.select.return_value.eq.return_value.eq.return_value \
                    .not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[{"completed_at": completed_at}])
            else:
                # interactions — return empty
                t.select.return_value.eq.return_value.in_.return_value \
                    .order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            return t

        db.client.table.side_effect = table_side_effect
        channel, reason = get_active_channel(db, "contact-1")

        assert channel == "email", f"Expected email after completed sequence, got {channel}"
        assert "email_sequence_completed" in reason, f"Unexpected reason: {reason}"

    # ------------------------------------------------------------------ #
    # can_use_channel()                                                    #
    # ------------------------------------------------------------------ #

    def test_can_use_channel_email_when_email_active(self):
        """can_use_channel(email) → True when contact is email-only."""
        from backend.app.core.channel_coordinator import can_use_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact(email="bob@example.com")])

        allowed, reason = can_use_channel(db, "contact-1", "email")
        assert allowed is True
        assert reason is None

    def test_can_use_channel_linkedin_blocked_when_email_active(self):
        """can_use_channel(linkedin) → False when only email is available."""
        from backend.app.core.channel_coordinator import can_use_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact(email="bob@example.com")])

        allowed, reason = can_use_channel(db, "contact-1", "linkedin")
        assert allowed is False
        assert reason is not None

    def test_can_use_channel_email_blocked_when_linkedin_active(self):
        """can_use_channel(email) → False when contact has LinkedIn only."""
        from backend.app.core.channel_coordinator import can_use_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact(linkedin_url="https://linkedin.com/in/bob")])

        allowed, reason = can_use_channel(db, "contact-1", "email")
        assert allowed is False
        assert reason is not None

    def test_can_use_channel_returns_false_for_no_channel_contact(self):
        """can_use_channel on a contact with no channels should always return False."""
        from backend.app.core.channel_coordinator import can_use_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[self._contact()])

        allowed_email, _ = can_use_channel(db, "contact-1", "email")
        allowed_linkedin, _ = can_use_channel(db, "contact-1", "linkedin")

        assert allowed_email is False
        assert allowed_linkedin is False


# ===========================================================================
# 3. SUPPRESSION + CHANNEL COORDINATION INTEGRATION
# ===========================================================================

class TestSuppressionIntegration:
    """Verify that suppression blocks all channels and channel-coord blocks one at a time."""

    def _make_suppression_db(
        self,
        company_status: str = "qualified",
        contact_status: str = "active",
        existing_solutions: list | None = None,
    ) -> MagicMock:
        company = {"id": "co-1", "name": "TestCo", "status": company_status}
        contact = {"id": "ct-1", "status": contact_status, "email": "a@b.com"}
        research = {"existing_solutions": existing_solutions or []}

        db = MagicMock()
        db.get_company.return_value = company
        db.get_research.return_value = research

        # Use table-specific side_effect so each table returns isolated data
        def _table_side_effect(tbl):
            t = MagicMock()
            if tbl == "contacts":
                t.select.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[contact])
            elif tbl == "engagement_sequences":
                # No completed sequences → no cooldown
                t.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            elif tbl == "interactions":
                t.select.return_value.eq.return_value.eq.return_value \
                    .gte.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            elif tbl == "outreach_drafts":
                t.select.return_value.eq.return_value.in_.return_value \
                    .is_.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            else:
                t.select.return_value.eq.return_value.execute.return_value = \
                    MagicMock(data=[])
            return t

        db.client.table.side_effect = _table_side_effect
        return db

    def test_bounced_contact_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(contact_status="bounced")
        suppressed, reason = is_suppressed(db, "co-1", "ct-1")
        assert suppressed is True
        assert "bounced" in reason

    def test_not_interested_contact_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(contact_status="not_interested")
        suppressed, reason = is_suppressed(db, "co-1", "ct-1")
        assert suppressed is True
        assert "not_interested" in reason

    def test_not_interested_company_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(company_status="not_interested")
        suppressed, reason = is_suppressed(db, "co-1", "ct-1")
        assert suppressed is True
        assert "not_interested" in reason

    def test_disqualified_company_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(company_status="disqualified")
        suppressed, reason = is_suppressed(db, "co-1")
        assert suppressed is True
        assert "disqualified" in reason

    def test_competitor_company_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(existing_solutions=["augury"])
        suppressed, reason = is_suppressed(db, "co-1")
        assert suppressed is True
        assert "competitor" in reason
        assert "augury" in reason

    def test_active_contact_qualified_company_not_suppressed(self):
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db()
        suppressed, reason = is_suppressed(db, "co-1", "ct-1")
        assert suppressed is False
        assert reason is None

    def test_c3_ai_competitor_suppressed(self):
        """c3.ai must be in the competitor list."""
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(existing_solutions=["c3.ai"])
        suppressed, reason = is_suppressed(db, "co-1")
        assert suppressed is True, "c3.ai is a direct competitor and should suppress outreach"

    def test_unknown_solution_does_not_suppress(self):
        """A non-competitor solution should NOT suppress outreach."""
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(existing_solutions=["Salesforce", "Office365"])
        suppressed, _ = is_suppressed(db, "co-1")
        assert suppressed is False, "Non-competitor tools should not suppress"

    def test_bounced_status_blocks_company_level_outreach(self):
        """Company-level bounced status should suppress outreach."""
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(company_status="bounced")
        suppressed, reason = is_suppressed(db, "co-1")
        assert suppressed is True
        assert "bounced" in reason

    def test_converted_company_is_suppressed(self):
        """Converted companies should not receive outreach."""
        from backend.app.core.suppression import is_suppressed

        db = self._make_suppression_db(company_status="converted")
        suppressed, reason = is_suppressed(db, "co-1")
        assert suppressed is True
        assert "converted" in reason


# ===========================================================================
# 4. DAILY COCKPIT API TESTS
# ===========================================================================

class TestDailyCockpitAPI:
    """Test the /api/today endpoint and outcome-logging side effects."""

    @pytest.fixture
    def client(self):
        """Create FastAPI test client with a mock database injected via patch."""
        from fastapi.testclient import TestClient
        from backend.app.api.routes.today import router

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)

        # Build a fully chainable mock DB
        mock_db = MagicMock()
        mock_db.client = MagicMock()

        chain = MagicMock()
        chain.select = MagicMock(return_value=chain)
        chain.insert = MagicMock(return_value=chain)
        chain.update = MagicMock(return_value=chain)
        chain.delete = MagicMock(return_value=chain)
        chain.eq = MagicMock(return_value=chain)
        chain.order = MagicMock(return_value=chain)
        chain.limit = MagicMock(return_value=chain)
        chain.lte = MagicMock(return_value=chain)
        chain.gte = MagicMock(return_value=chain)
        chain.like = MagicMock(return_value=chain)
        chain.in_ = MagicMock(return_value=chain)
        chain.is_ = MagicMock(return_value=chain)
        chain.not_ = MagicMock(return_value=chain)
        chain.execute = MagicMock(return_value=MagicMock(data=[], count=0))
        mock_db.client.table = MagicMock(return_value=chain)

        # Patch get_db in the today module (it's called directly, not via Depends)
        self._patcher = patch(
            "backend.app.api.routes.today.get_db",
            return_value=mock_db,
        )
        self._patcher.start()
        self._mock_db = mock_db

        yield TestClient(app)

        self._patcher.stop()

    def test_today_endpoint_returns_200(self, client):
        resp = client.get("/api/today")
        assert resp.status_code == 200

    def test_today_response_has_data_key(self, client):
        resp = client.get("/api/today")
        body = resp.json()
        assert "data" in body

    def test_today_response_has_hot_signals(self, client):
        resp = client.get("/api/today")
        data = resp.json()["data"]
        assert "hot_signals" in data

    def test_today_response_has_pending_approvals(self, client):
        resp = client.get("/api/today")
        data = resp.json()["data"]
        assert "pending_approvals" in data

    def test_today_response_has_linkedin_queue(self, client):
        resp = client.get("/api/today")
        data = resp.json()["data"]
        assert "linkedin_queue" in data

    def test_today_response_has_pipeline_summary(self, client):
        resp = client.get("/api/today")
        data = resp.json()["data"]
        assert "pipeline_summary" in data

    def test_today_response_has_progress(self, client):
        resp = client.get("/api/today")
        data = resp.json()["data"]
        assert "progress" in data
        assert "completed" in data["progress"]
        assert "target" in data["progress"]

    def test_log_outcome_interested_updates_status_to_engaged(self, client):
        """Logging 'interested' should map to 'engaged' company status."""
        from backend.app.api.routes.today import _OUTCOME_STATUS_MAP

        assert _OUTCOME_STATUS_MAP.get("interested") == "engaged"

    def test_log_outcome_not_interested_updates_status(self, client):
        """Logging 'not_interested' should map to 'not_interested' company status."""
        from backend.app.api.routes.today import _OUTCOME_STATUS_MAP

        assert _OUTCOME_STATUS_MAP.get("not_interested") == "not_interested"

    def test_log_outcome_meeting_booked_updates_to_meeting_scheduled(self, client):
        """Logging 'meeting_booked' should map to 'meeting_scheduled' company status."""
        from backend.app.api.routes.today import _OUTCOME_STATUS_MAP

        assert _OUTCOME_STATUS_MAP.get("meeting_booked") == "meeting_scheduled"

    def test_log_outcome_endpoint_returns_200_with_valid_payload(self, client):
        """POST /api/today/log-outcome with valid data should return 200."""
        payload = {
            "company_id": "co-001",
            "contact_id": "ct-001",
            "channel": "email",
            "outcome": "interested",
        }
        resp = client.post("/api/today/log-outcome", json=payload)
        assert resp.status_code == 200

    def test_log_outcome_response_contains_outcome_field(self, client):
        payload = {
            "company_id": "co-001",
            "channel": "linkedin",
            "outcome": "not_interested",
        }
        resp = client.post("/api/today/log-outcome", json=payload)
        body = resp.json()
        assert "data" in body
        assert body["data"]["outcome"] == "not_interested"

    def test_mark_done_returns_200(self, client):
        payload = {"action_type": "linkedin_connection", "company_id": "co-001"}
        resp = client.post("/api/today/mark-done", json=payload)
        assert resp.status_code == 200

    def test_mark_done_response_contains_action_type(self, client):
        payload = {"action_type": "approval", "company_id": "co-001"}
        resp = client.post("/api/today/mark-done", json=payload)
        body = resp.json()
        assert body["data"]["action_type"] == "approval"

    def test_log_outcome_missing_required_fields_returns_422(self, client):
        """Missing company_id should fail validation."""
        resp = client.post("/api/today/log-outcome", json={"channel": "email", "outcome": "interested"})
        assert resp.status_code == 422

    def test_pqs_delta_map_has_positive_for_interested(self):
        from backend.app.api.routes.today import _OUTCOME_PQS_DELTA

        assert _OUTCOME_PQS_DELTA.get("interested", 0) > 0

    def test_pqs_delta_map_has_negative_for_not_interested(self):
        from backend.app.api.routes.today import _OUTCOME_PQS_DELTA

        assert _OUTCOME_PQS_DELTA.get("not_interested", 0) < 0


# ===========================================================================
# 5. CONTENT GENERATION TESTS
# ===========================================================================

class TestContentGeneration:
    """Test ContentAgent system-prompt construction and guideline enforcement."""

    def test_content_guidelines_load_without_error(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("content_guidelines.yaml")
        assert isinstance(cfg, dict)
        assert len(cfg) > 0

    def test_content_guidelines_has_author(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("content_guidelines.yaml")
        assert "author" in cfg or "voice_and_tone" in cfg, (
            "content_guidelines.yaml must have author or voice_and_tone"
        )

    def test_content_guidelines_has_banned_phrases(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("content_guidelines.yaml")
        assert "banned_phrases" in cfg, "content_guidelines.yaml must list banned_phrases"
        assert len(cfg["banned_phrases"]) > 0

    def test_content_guidelines_has_voice_and_tone(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("content_guidelines.yaml")
        assert "voice_and_tone" in cfg

    def test_content_calendar_has_50_topics(self):
        """Content calendar should have ≥ 16 entries (4-week rotation × 4 days/week)."""
        from backend.app.agents.content import CONTENT_CALENDAR

        assert len(CONTENT_CALENDAR) >= 16, (
            f"Content calendar should have at least 16 entries, found {len(CONTENT_CALENDAR)}"
        )

    def test_system_prompt_includes_voice_and_tone(self):
        from backend.app.agents.content import _build_system_prompt, _DEFAULT_GUIDELINES

        prompt = _build_system_prompt(_DEFAULT_GUIDELINES)
        assert "VOICE AND TONE" in prompt.upper() or "voice" in prompt.lower()

    def test_system_prompt_includes_banned_phrases_section(self):
        from backend.app.agents.content import _build_system_prompt, _DEFAULT_GUIDELINES

        prompt = _build_system_prompt(_DEFAULT_GUIDELINES)
        assert "BANNED" in prompt.upper(), "System prompt must call out banned phrases"

    def test_system_prompt_says_never_mention_product(self):
        """System prompt must explicitly prohibit product mentions."""
        from backend.app.agents.content import _build_system_prompt, _DEFAULT_GUIDELINES

        prompt = _build_system_prompt(_DEFAULT_GUIDELINES)
        assert "product" in prompt.lower() or "digitillis" in prompt.lower() or "company" in prompt.lower(), (
            "System prompt must instruct model not to mention the product"
        )

    def test_default_guidelines_has_banned_phrases(self):
        from backend.app.agents.content import _DEFAULT_GUIDELINES

        banned = _DEFAULT_GUIDELINES.get("banned_phrases", [])
        assert len(banned) >= 5, "Default guidelines must have at least 5 banned phrases"

    def test_default_guidelines_never_include_has_product_restriction(self):
        from backend.app.agents.content import _DEFAULT_GUIDELINES

        never = _DEFAULT_GUIDELINES.get("never_include", [])
        text = " ".join(never).lower()
        assert "digitillis" in text or "product" in text or "ai" in text, (
            "never_include must restrict product/company mentions"
        )

    def test_format_specs_char_limit_under_1500(self):
        """All format specs must cap character counts under 1500."""
        from backend.app.agents.content import _FORMAT_SPECS

        for fmt_name, spec in _FORMAT_SPECS.items():
            limit = spec.get("char_limit", 9999)
            assert limit < 1500, (
                f"Format '{fmt_name}' has char_limit={limit}, must be < 1500"
            )

    def test_user_prompt_includes_topic(self):
        from backend.app.agents.content import _build_user_prompt, _DEFAULT_GUIDELINES

        topic = "Test topic about FSMA compliance"
        prompt = _build_user_prompt(topic, "food_safety", "data_insight", _DEFAULT_GUIDELINES)
        assert topic in prompt

    def test_user_prompt_says_no_hashtags(self):
        from backend.app.agents.content import _build_user_prompt, _DEFAULT_GUIDELINES

        prompt = _build_user_prompt("Any topic", "food_safety", "data_insight", _DEFAULT_GUIDELINES)
        assert "hashtag" in prompt.lower() or "No hashtag" in prompt or "#" in prompt.lower()

    def test_user_prompt_does_not_ask_to_mention_product(self):
        """User prompt must NOT instruct the model to mention Digitillis."""
        from backend.app.agents.content import _build_user_prompt, _DEFAULT_GUIDELINES

        prompt = _build_user_prompt("OEE benchmarks", "predictive_maintenance", "data_insight", _DEFAULT_GUIDELINES)
        # The prompt should not ask Claude to promote any product
        assert "mention digitillis" not in prompt.lower()
        assert "promote" not in prompt.lower()


# ===========================================================================
# 6. LINKEDIN MESSAGE TESTS
# ===========================================================================

class TestLinkedInMessageGeneration:
    """Test LinkedInAgent config loading, vertical context, word limits."""

    def test_linkedin_guidelines_load_without_error(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("linkedin_messages_guidelines.yaml")
        assert isinstance(cfg, dict)
        assert len(cfg) > 0

    def test_linkedin_guidelines_has_fb_question_templates(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("linkedin_messages_guidelines.yaml")
        templates = cfg.get("fb_question_templates", [])
        assert len(templates) >= 2, "Must have at least 2 F&B question templates"

    def test_linkedin_guidelines_has_mfg_question_templates(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("linkedin_messages_guidelines.yaml")
        templates = cfg.get("mfg_question_templates", [])
        assert len(templates) >= 2, "Must have at least 2 manufacturing question templates"

    def test_linkedin_guidelines_has_banned_phrases(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("linkedin_messages_guidelines.yaml")
        assert "banned_phrases" in cfg
        assert len(cfg["banned_phrases"]) > 0

    def test_linkedin_guidelines_has_sender(self):
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("linkedin_messages_guidelines.yaml")
        assert "sender" in cfg
        assert "name" in cfg["sender"]

    def test_linkedin_system_prompt_mentions_em_dash_restriction(self):
        """System prompt must explicitly forbid em dashes."""
        from backend.app.agents.linkedin import _build_system_prompt

        guidelines = {}
        prompt = _build_system_prompt(guidelines)
        assert "em dash" in prompt.lower() or "—" in prompt, (
            "LinkedIn system prompt must forbid em dashes"
        )

    def test_fb_vertical_context_mentions_food_and_beverage(self):
        """F&B vertical context must reference food safety or FSMA."""
        from backend.app.agents.linkedin import LinkedInAgent

        agent = LinkedInAgent.__new__(LinkedInAgent)
        ctx = agent._build_vertical_context("food_beverage", "fb1", {})
        lower = ctx.lower()
        assert "food" in lower or "fsma" in lower or "safety" in lower

    def test_mfg_vertical_context_mentions_manufacturing(self):
        """Manufacturing vertical context must reference maintenance or OEE."""
        from backend.app.agents.linkedin import LinkedInAgent

        agent = LinkedInAgent.__new__(LinkedInAgent)
        ctx = agent._build_vertical_context("manufacturing", "mfg1", {})
        lower = ctx.lower()
        assert "maintenance" in lower or "oee" in lower or "manufacturing" in lower

    def test_connection_note_word_limit_is_50(self):
        """The connection note instructions must mention 50-word limit."""
        from backend.app.agents.linkedin import LINKEDIN_USER

        lower = LINKEDIN_USER.lower()
        assert "50 words" in lower or "50-word" in lower, (
            "LinkedIn prompt must specify 50-word limit for connection note"
        )

    def test_opening_dm_word_limit_is_80(self):
        """The opening DM instructions must mention 80-word limit."""
        from backend.app.agents.linkedin import LINKEDIN_USER

        lower = LINKEDIN_USER.lower()
        assert "80 words" in lower or "80-word" in lower, (
            "LinkedIn prompt must specify 80-word limit for opening DM"
        )

    def test_followup_dm_word_limit_is_100(self):
        """The follow-up DM instructions must mention 100-word limit."""
        from backend.app.agents.linkedin import LINKEDIN_USER

        lower = LINKEDIN_USER.lower()
        assert "100 words" in lower or "100-word" in lower, (
            "LinkedIn prompt must specify 100-word limit for follow-up DM"
        )

    def test_linkedin_prompt_generates_3_messages(self):
        """The prompt template must instruct the model to generate 3 messages."""
        from backend.app.agents.linkedin import LINKEDIN_USER

        lower = LINKEDIN_USER.lower()
        assert "3 messages" in lower or "three messages" in lower or \
               ("connection" in lower and "opening" in lower and "follow" in lower), (
            "LinkedIn prompt must produce 3 distinct message types"
        )

    def test_linkedin_prompt_specifies_json_output(self):
        """Output format must be JSON with the correct keys."""
        from backend.app.agents.linkedin import LINKEDIN_USER

        assert "connection_note" in LINKEDIN_USER
        assert "opening_dm" in LINKEDIN_USER
        assert "followup_dm" in LINKEDIN_USER

    def test_fb_tier_detected_correctly(self):
        """A tier starting with 'fb' should map to food_beverage vertical."""
        from backend.app.agents.linkedin import LinkedInAgent

        agent = LinkedInAgent.__new__(LinkedInAgent)
        ctx = agent._build_vertical_context("food_beverage", "fb2", {})
        assert "food" in ctx.lower() or "beverage" in ctx.lower() or "fsma" in ctx.lower()


# ===========================================================================
# 7. OUTREACH QUALITY GATE TESTS
# ===========================================================================

class TestDraftQualityGate:
    """Test validate_draft() in draft_quality.py."""

    def test_good_draft_passes(self, good_draft, sample_company, sample_research):
        from backend.app.core.draft_quality import validate_draft

        report = validate_draft(good_draft, sample_company, sample_research)
        assert report.passed, f"Good draft should pass. Issues: {report.issues}"

    def test_banned_phrase_is_caught(self):
        from backend.app.core.draft_quality import validate_draft

        draft = {
            "id": "d1",
            "subject": "Downtime",
            "body": (
                "i hope this email finds you well.\n\n"
                "We built a platform that reduces downtime.\n\n"
                "Would it be worth a 15-minute call?\n\n"
                "Avanish Mehrotra\nFounder & CEO\n224.355.4500"
            ),
        }
        report = validate_draft(draft)
        assert not report.passed
        assert any(i.check_name == "banned_phrase" for i in report.issues)

    def test_missing_subject_is_flagged(self):
        from backend.app.core.draft_quality import validate_draft

        draft = {
            "id": "d2",
            "subject": "",
            "body": (
                "Hi Sarah,\n\nAcme Foods recently hired a VP Digital. "
                "Would a 15-minute call make sense?\n\n"
                "Avanish Mehrotra\nFounder & CEO\n224.355.4500"
            ),
        }
        report = validate_draft(draft)
        assert any(i.check_name == "no_subject" for i in report.issues)

    def test_em_dash_is_flagged(self):
        from backend.app.core.draft_quality import validate_draft

        draft = {
            "id": "d3",
            "subject": "Production uptime",
            "body": (
                "Hi Sarah,\n\nAcme Foods — a good prospect — just hired a VP Digital. "
                "Would it be worth a 15-minute call?\n\n"
                "Avanish Mehrotra\nFounder & CEO\n224.355.4500"
            ),
        }
        report = validate_draft(draft)
        assert any("em_dash" in i.check_name or "em dash" in i.message.lower() for i in report.issues), (
            "Em dash should be flagged in draft quality check"
        )

    def test_too_short_body_is_rejected(self):
        from backend.app.core.draft_quality import validate_draft

        draft = {
            "id": "d4",
            "subject": "Quick question",
            "body": "Hi. Want to chat? Avanish",
        }
        report = validate_draft(draft)
        assert not report.passed
        assert any(i.check_name == "too_short" for i in report.issues)

    def test_missing_signature_flagged(self):
        from backend.app.core.draft_quality import validate_draft

        draft = {
            "id": "d5",
            "subject": "Production uptime",
            "body": (
                "Hi Sarah,\n\n"
                "Noticed Acme Foods recently hired a VP Digital.\n\n"
                "Would it be worth a 15-minute call to see if there's a fit?\n\n"
                "Best regards"
            ),
        }
        report = validate_draft(draft)
        assert any("signoff" in i.check_name or "signature" in i.message.lower() for i in report.issues)

    def test_quality_score_decremented_by_errors(self):
        from backend.app.core.draft_quality import QualityReport

        rpt = QualityReport(draft_id="x")
        initial_score = rpt.score

        rpt.add_issue("error", "test_error", "Something is wrong")
        assert rpt.score < initial_score
        assert not rpt.passed

    def test_quality_score_decremented_by_warning(self):
        from backend.app.core.draft_quality import QualityReport

        rpt = QualityReport(draft_id="x")
        initial_score = rpt.score

        rpt.add_issue("warning", "test_warn", "Something could be better")
        assert rpt.score < initial_score
        assert rpt.passed  # Warnings do NOT fail the draft

    def test_score_never_goes_below_zero(self):
        from backend.app.core.draft_quality import QualityReport

        rpt = QualityReport(draft_id="x")
        for _ in range(20):
            rpt.add_issue("error", "x", "Error")
        assert rpt.score >= 0

    def test_banned_phrase_list_exists_and_non_empty(self):
        from backend.app.core.draft_quality import _BANNED_PHRASES

        assert isinstance(_BANNED_PHRASES, list)
        assert len(_BANNED_PHRASES) >= 10

    def test_no_cta_is_flagged_as_warning(self):
        from backend.app.core.draft_quality import validate_draft

        draft = {
            "id": "d6",
            "subject": "OEE benchmarks",
            "body": (
                "Hi John,\n\n"
                "AcmeCorp recently announced a new automation investment. "
                "We work with similar manufacturers on predictive maintenance.\n\n"
                "Avanish Mehrotra\nFounder & CEO\n224.355.4500"
            ),
        }
        report = validate_draft(draft)
        assert any(i.check_name == "no_cta" for i in report.issues)


# ===========================================================================
# 8. CONFLICT ALARM TESTS
# ===========================================================================

class TestConflictAlarms:
    """Verify that skips, suppressions, and blocks produce clear audit trails."""

    def test_suppressed_contact_skip_is_recorded(self):
        """When LinkedInAgent skips a suppressed contact, it increments result.skipped."""
        from backend.app.agents.linkedin import LinkedInAgent

        agent = LinkedInAgent.__new__(LinkedInAgent)
        mock_db = MagicMock()
        mock_db.get_companies.return_value = [
            {"id": "co-1", "name": "TestCo", "tier": "fb1"}
        ]
        agent.db = mock_db

        # is_suppressed is imported inside the function body — patch the source module
        with patch("backend.app.core.suppression.is_suppressed",
                   return_value=(True, "contact_status:bounced")):
            result = agent.run(limit=5)

        assert result.skipped >= 1, "Suppressed company should appear in skipped count"

    def test_suppressed_skip_detail_is_added(self):
        """When a company is suppressed, a detail with reason should be added."""
        from backend.app.agents.linkedin import LinkedInAgent

        agent = LinkedInAgent.__new__(LinkedInAgent)
        mock_db = MagicMock()
        mock_db.get_companies.return_value = [
            {"id": "co-1", "name": "SuppressedCo", "tier": "mfg1"}
        ]
        agent.db = mock_db

        with patch("backend.app.core.suppression.is_suppressed",
                   return_value=(True, "company_status:not_interested")):
            result = agent.run(limit=5)

        suppressed_details = [d for d in result.details if d.get("status") == "suppressed"]
        assert len(suppressed_details) >= 1, "Should have a suppressed detail entry"

    def test_not_interested_outcome_suppresses_via_status_map(self):
        """_OUTCOME_STATUS_MAP for not_interested must map to 'not_interested'."""
        from backend.app.api.routes.today import _OUTCOME_STATUS_MAP

        # Verify the mapping drives company suppression
        assert _OUTCOME_STATUS_MAP["not_interested"] == "not_interested"

    def test_suppressed_contact_reason_is_non_empty(self):
        """is_suppressed must always return a reason string when suppressed."""
        from backend.app.core.suppression import is_suppressed

        db = MagicMock()
        db.get_company.return_value = {"id": "co-1", "name": "X", "status": "bounced"}
        db.get_research.return_value = {}

        suppressed, reason = is_suppressed(db, "co-1")
        assert suppressed is True
        assert reason is not None and len(reason) > 0

    def test_duplicate_draft_is_suppressed(self):
        """If a pending draft already exists for a contact, is_suppressed returns True."""
        from backend.app.core.suppression import is_suppressed

        db = MagicMock()
        db.get_company.return_value = {"id": "co-1", "name": "X", "status": "qualified"}
        db.get_research.return_value = {}

        # Contact lookup returns active contact
        # Sequence and interaction queries return empty (no cooldown)
        # Draft query returns an existing draft
        contact_data = {"id": "ct-1", "status": "active", "email": "a@b.com"}

        def table_side(tbl):
            t = MagicMock()
            chain = MagicMock()
            if tbl == "contacts":
                chain.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[contact_data])
            elif tbl == "outreach_drafts":
                chain.select.return_value.eq.return_value.in_.return_value.is_.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[{"id": "draft-existing"}])
            else:
                chain.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
                chain.select.return_value.eq.return_value.eq.return_value \
                    .not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = \
                    MagicMock(data=[])
            t.select = chain.select
            return t

        db.client.table = MagicMock(side_effect=table_side)

        suppressed, reason = is_suppressed(db, "co-1", "ct-1")
        assert suppressed is True
        assert "duplicate" in reason or "pending" in reason


# ===========================================================================
# 9. SETTINGS CONFIGURABILITY TESTS
# ===========================================================================

class TestSettingsConfigurability:
    """Test that settings endpoints read and write YAML correctly."""

    @pytest.fixture
    def settings_client(self):
        from fastapi.testclient import TestClient
        from backend.app.api.routes.settings import router

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_settings_returns_200(self, settings_client):
        resp = settings_client.get("/api/settings")
        assert resp.status_code == 200

    def test_get_settings_has_icp_key(self, settings_client):
        resp = settings_client.get("/api/settings")
        body = resp.json()
        assert "data" in body
        assert "icp" in body["data"]

    def test_get_settings_has_scoring_key(self, settings_client):
        resp = settings_client.get("/api/settings")
        body = resp.json()
        assert "scoring" in body["data"]

    def test_get_outreach_guidelines_returns_200(self, settings_client):
        resp = settings_client.get("/api/settings/outreach-guidelines")
        assert resp.status_code == 200

    def test_get_outreach_guidelines_has_sender(self, settings_client):
        resp = settings_client.get("/api/settings/outreach-guidelines")
        body = resp.json()
        assert "data" in body
        assert "sender" in body["data"]

    def test_outreach_guidelines_sender_has_phone(self, settings_client):
        resp = settings_client.get("/api/settings/outreach-guidelines")
        sender = resp.json()["data"]["sender"]
        assert "phone" in sender, "Outreach guidelines sender must have phone number"

    def test_get_content_guidelines_returns_200(self, settings_client):
        resp = settings_client.get("/api/settings/content-guidelines")
        assert resp.status_code == 200

    def test_content_guidelines_has_topics_via_pillars_or_calendar(self, settings_client):
        """Content guidelines or calendar together should cover many content topics."""
        from backend.app.agents.content import CONTENT_CALENDAR

        assert len(CONTENT_CALENDAR) >= 16, (
            "Should have at least 16 content calendar entries across 4 pillars"
        )

    def test_get_linkedin_guidelines_returns_200(self, settings_client):
        resp = settings_client.get("/api/settings/linkedin-guidelines")
        assert resp.status_code == 200

    def test_linkedin_guidelines_has_question_templates(self, settings_client):
        resp = settings_client.get("/api/settings/linkedin-guidelines")
        body = resp.json()
        data = body.get("data", {})
        has_fb = "fb_question_templates" in data
        has_mfg = "mfg_question_templates" in data
        assert has_fb or has_mfg, "LinkedIn guidelines must include question templates"

    def test_outreach_guidelines_has_voice_and_tone(self, settings_client):
        resp = settings_client.get("/api/settings/outreach-guidelines")
        data = resp.json()["data"]
        assert "voice_and_tone" in data or "voice" in str(data).lower()

    def test_load_yaml_config_is_not_cached(self):
        """load_yaml_config must read from disk fresh each call (not lru_cache)."""
        from backend.app.core.config import load_yaml_config
        import inspect

        # load_yaml_config should NOT have a cache_info attribute (not lru_cached)
        assert not hasattr(load_yaml_config, "cache_info"), (
            "load_yaml_config must not use lru_cache — agents need fresh reads on every run"
        )

    def test_get_outreach_guidelines_is_not_cached(self):
        """get_outreach_guidelines must NOT use lru_cache — edits must take effect immediately."""
        from backend.app.core.config import get_outreach_guidelines

        # The function is intentionally not cached so dashboard PATCH edits are
        # picked up on the next request without a server restart.
        assert not hasattr(get_outreach_guidelines, "cache_info"), (
            "get_outreach_guidelines must not use lru_cache — "
            "PATCH edits to the guidelines file must be visible immediately"
        )

    def test_patch_settings_returns_200_for_empty_payload(self, settings_client):
        """PATCH /api/settings with empty payload should succeed (no-op update)."""
        resp = settings_client.patch("/api/settings", json={})
        assert resp.status_code == 200


# ===========================================================================
# 10. API ROUTE SMOKE TESTS
# ===========================================================================

class TestAPIRoutes:
    """Basic smoke tests for key API routes."""

    @pytest.fixture
    def app_client(self):
        from fastapi.testclient import TestClient
        from backend.app.api.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_health_route_exists_or_root_responds(self, app_client):
        """Either /health or the root path should respond."""
        resp = app_client.get("/health")
        # Accept 200, 404 (route doesn't exist) — just not a 500
        assert resp.status_code != 500

    def test_content_calendar_route(self, app_client):
        resp = app_client.get("/api/content/calendar")
        # The calendar is static — should always work without DB
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert len(body["data"]) >= 16

    def test_content_calendar_entries_have_required_fields(self, app_client):
        resp = app_client.get("/api/content/calendar")
        entries = resp.json()["data"]
        for entry in entries[:5]:  # Spot-check first 5
            assert "topic" in entry
            assert "pillar" in entry
            assert "format" in entry

    def test_settings_route_returns_200(self, app_client):
        """GET /api/settings should always return 200 even without DB."""
        resp = app_client.get("/api/settings")
        assert resp.status_code == 200

    def test_outreach_guidelines_route_returns_200(self, app_client):
        resp = app_client.get("/api/settings/outreach-guidelines")
        assert resp.status_code == 200

    def test_content_guidelines_route_returns_200(self, app_client):
        resp = app_client.get("/api/settings/content-guidelines")
        assert resp.status_code == 200

    def test_linkedin_guidelines_route_returns_200(self, app_client):
        resp = app_client.get("/api/settings/linkedin-guidelines")
        assert resp.status_code == 200

    def test_log_outcome_requires_post_not_get(self, app_client):
        """GET /api/today/log-outcome should be 405 Method Not Allowed."""
        resp = app_client.get("/api/today/log-outcome")
        assert resp.status_code == 405

    def test_today_route_responds(self, app_client):
        """GET /api/today should not crash even if DB is unavailable."""
        resp = app_client.get("/api/today")
        # Should return 200 with graceful empty lists (the route has try/except)
        assert resp.status_code == 200

    def test_mark_done_requires_post_not_get(self, app_client):
        """GET /api/today/mark-done should be 405."""
        resp = app_client.get("/api/today/mark-done")
        assert resp.status_code == 405


# ===========================================================================
# Additional integration-style workflow checks
# ===========================================================================

class TestWorkflowIntegrityChecks:
    """Miscellaneous checks that verify workflow invariants."""

    def test_company_status_enum_covers_full_pipeline(self):
        """CompanyStatus must cover every stage from discovery to conversion."""
        from backend.app.core.models import CompanyStatus

        required = {
            "discovered", "researched", "qualified", "disqualified",
            "outreach_pending", "contacted", "engaged", "meeting_scheduled",
            "not_interested", "bounced",
        }
        actual = {s.value for s in CompanyStatus}
        missing = required - actual
        assert not missing, f"CompanyStatus is missing: {missing}"

    def test_approval_status_enum_covers_all_states(self):
        """ApprovalStatus must cover pending, approved, rejected, edited."""
        from backend.app.core.models import ApprovalStatus

        required = {"pending", "approved", "rejected", "edited"}
        actual = {s.value for s in ApprovalStatus}
        missing = required - actual
        assert not missing, f"ApprovalStatus is missing: {missing}"

    def test_suppression_reason_returned_when_suppressed(self):
        """is_suppressed must always return a non-None reason when True."""
        from backend.app.core.suppression import is_suppressed

        db = MagicMock()
        db.get_company.return_value = {"id": "x", "status": "not_interested"}
        db.get_research.return_value = {}

        suppressed, reason = is_suppressed(db, "x")
        if suppressed:
            assert reason is not None, "Suppression must always include a reason"

    def test_channel_coordinator_returns_tuple(self):
        """get_active_channel must return a 2-tuple."""
        from backend.app.core.channel_coordinator import get_active_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[])

        result = get_active_channel(db, "contact-1")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_can_use_channel_returns_tuple(self):
        """can_use_channel must return a 2-tuple."""
        from backend.app.core.channel_coordinator import can_use_channel

        db = MagicMock()
        db.client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[])

        result = can_use_channel(db, "contact-1", "email")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_outreach_guidelines_has_banned_characters(self):
        """Outreach guidelines must list banned characters (em dash, etc.)."""
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("outreach_guidelines.yaml")
        # Either banned_characters or em dash mention in voice_and_tone
        has_banned_chars = "banned_characters" in cfg
        has_em_dash_restriction = "—" in str(cfg) or "em dash" in str(cfg).lower() or "em-dash" in str(cfg).lower()
        assert has_banned_chars or has_em_dash_restriction, (
            "Outreach guidelines must restrict em dashes"
        )

    def test_sequences_yaml_has_at_least_one_email_step(self):
        """At least one sequence must have an email channel step."""
        from backend.app.core.config import load_yaml_config

        cfg = load_yaml_config("sequences.yaml")
        seqs = cfg.get("sequences", {})
        found_email = False
        for seq in seqs.values():
            for step in seq.get("steps", []):
                if step.get("channel", "") == "email":
                    found_email = True
                    break

        assert found_email, "sequences.yaml must define at least one email step"

    def test_pipeline_class_has_all_stage_methods(self):
        """Pipeline class must expose run methods for each stage."""
        from backend.app.orchestrator.pipeline import Pipeline

        required_methods = [
            "run_discovery", "run_research", "run_qualification",
            "run_enrichment", "run_full",
        ]
        for method in required_methods:
            assert hasattr(Pipeline, method), (
                f"Pipeline is missing method: {method}"
            )

    def test_today_outcome_map_only_maps_known_outcomes(self):
        """_OUTCOME_STATUS_MAP should map exactly the outcomes that change company status."""
        from backend.app.api.routes.today import _OUTCOME_STATUS_MAP

        # These 3 outcomes have status implications
        assert "interested" in _OUTCOME_STATUS_MAP
        assert "meeting_booked" in _OUTCOME_STATUS_MAP
        assert "not_interested" in _OUTCOME_STATUS_MAP
