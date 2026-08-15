"""Tests for the LLM_GENERATION_ENABLED gate (backend/app/core/
llm_generation_gate.py) and its wiring into the three call sites that
were reaching the metered Anthropic API despite CLAUDE.md's own doctrine
("Email generation: ALWAYS via Claude Code workflow, NEVER the backend").

Regression coverage for finding 9 of the 2026-08-15 send-path
reconciliation / subscription-migration follow-up: three still-active
scheduler jobs (_run_process_due_sequences, _run_jit_pregenerate,
_run_personalization_refresh) reached OutreachAgent.run(),
ResearchAgent.run(), and PersonalizationBatch.run_batch() directly,
spending real API tokens on content generation the doctrine says should
happen only in a Claude Code subscription session.

Each test proves the gate is checked BEFORE any DB read or Anthropic
client construction — not just that the method returns early for some
other reason — by asserting the underlying company-fetch call was never
made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


class TestGenerationEnabledHelper:
    def test_reads_settings_flag_true(self):
        from backend.app.core.llm_generation_gate import generation_enabled

        settings = MagicMock(llm_generation_enabled=True)
        with patch("backend.app.core.config.get_settings", return_value=settings):
            assert generation_enabled() is True

    def test_reads_settings_flag_false(self):
        from backend.app.core.llm_generation_gate import generation_enabled

        settings = MagicMock(llm_generation_enabled=False)
        with patch("backend.app.core.config.get_settings", return_value=settings):
            assert generation_enabled() is False


class TestOutreachAgentGate:
    def test_disabled_skips_before_any_db_call(self):
        from backend.app.agents.outreach import OutreachAgent

        agent = OutreachAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=False,
        ):
            result = agent.run(company_ids=["c1"])

        assert result.success is True
        assert result.processed == 0
        agent.db.get_company.assert_not_called()
        agent.db.get_companies.assert_not_called()

    def test_enabled_proceeds_past_the_gate(self):
        """Doesn't exercise the full pipeline (that needs a much larger
        DB/config mock) — just proves the gate itself doesn't block when
        enabled, by confirming execution reaches the next DB call.
        """
        from backend.app.agents.outreach import OutreachAgent

        agent = OutreachAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()
        agent.db.get_company.return_value = (
            None  # so companies ends up empty and run() exits cleanly
        )

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=True,
        ):
            agent.run(company_ids=["c1"])

        agent.db.get_company.assert_called_once_with("c1")


class TestResearchAgentGate:
    def test_disabled_skips_before_any_db_call(self):
        from backend.app.agents.research import ResearchAgent

        agent = ResearchAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=False,
        ):
            result = agent.run(company_ids=["c1"])

        assert result.success is True
        assert result.processed == 0
        agent.db.get_company.assert_not_called()
        agent.db.get_companies.assert_not_called()

    def test_enabled_proceeds_past_the_gate(self):
        from backend.app.agents.research import ResearchAgent

        agent = ResearchAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()
        agent.db.get_company.return_value = None

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=True,
        ):
            agent.run(company_ids=["c1"])

        agent.db.get_company.assert_called_once_with("c1")


class TestPersonalizationBatchGate:
    def test_disabled_skips_before_fetching_companies(self):
        from backend.app.core.personalization_batch import PersonalizationBatch

        runner = PersonalizationBatch(workspace_id=WORKSPACE_ID)
        runner._fetch_eligible_companies = MagicMock(return_value=[{"id": "c1"}])

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=False,
        ):
            result = runner.run_batch(max_companies=10)

        assert result.processed == 0
        assert result.errors == 0
        runner._fetch_eligible_companies.assert_not_called()

    def test_enabled_proceeds_past_the_gate(self):
        from backend.app.core.personalization_batch import PersonalizationBatch

        runner = PersonalizationBatch(workspace_id=WORKSPACE_ID)
        runner._fetch_eligible_companies = MagicMock(return_value=[])

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=True,
        ):
            result = runner.run_batch(max_companies=10)

        runner._fetch_eligible_companies.assert_called_once()
        assert result.processed == 0  # no companies returned, nothing to process
