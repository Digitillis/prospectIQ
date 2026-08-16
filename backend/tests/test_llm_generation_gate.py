"""Tests for the LLM_GENERATION_ENABLED gate (backend/app/core/
llm_generation_gate.py) and its wiring into the five call sites that
were reaching the metered Anthropic API despite CLAUDE.md's own doctrine
("Email generation: ALWAYS via Claude Code workflow, NEVER the backend").

Regression coverage for finding 9 of the 2026-08-15 send-path
reconciliation / subscription-migration follow-up: three still-active
scheduler jobs (_run_process_due_sequences, _run_jit_pregenerate,
_run_personalization_refresh) reached OutreachAgent.run() (outreach.py),
ResearchAgent.run(), and PersonalizationBatch.run_batch() directly,
spending real API tokens on content generation the doctrine says should
happen only in a Claude Code subscription session.

TestOutreachAgentGate / TestResearchAgentGate / TestPersonalizationBatchGate
cover those three. TestOutreachAgentSecondClassGate and
TestPersonalizationEngineDirectGate cover two MORE entry points an
independent adversarial review found still ungated in the first version
of this fix: POST /api/outreach/generate resolves to a DIFFERENT class
also named OutreachAgent (backend/app/agents/outreach_agent.py, unrelated
to outreach.py's class), and POST /api/personalization/run/{company_id}
calls PersonalizationEngine.run_full_pipeline() directly — a caller
PersonalizationBatch.run_batch()'s gate does not cover, since it doesn't
go through the batch runner at all.

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


class TestOutreachAgentSecondClassGate:
    """POST /api/outreach/generate resolves to backend/app/agents/
    outreach_agent.py's OutreachAgent — a different class from
    outreach.py's, unrelated except sharing a name. Missed by the first
    version of this gate; found by adversarial review.
    """

    def test_generate_draft_disabled_raises_before_any_db_call(self):
        from backend.app.agents.outreach_agent import OutreachAgent

        agent = OutreachAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=False,
        ):
            try:
                agent.generate_draft(company_id="c1", contact_id="ct1", sequence_step="touch_1")
                assert False, "expected RuntimeError"
            except RuntimeError as e:
                assert "LLM_GENERATION_ENABLED" in str(e)

        agent.db.get_company.assert_not_called()

    def test_generate_draft_enabled_proceeds_past_the_gate(self):
        from backend.app.agents.outreach_agent import OutreachAgent

        agent = OutreachAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()
        agent.db.get_company.return_value = None  # -> raises ValueError next, fine for this test

        settings = MagicMock(anthropic_api_key="test-key")
        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=settings),
        ):
            try:
                agent.generate_draft(company_id="c1", contact_id="ct1", sequence_step="touch_1")
            except ValueError:
                pass  # expected — company_id doesn't resolve to a real company

        agent.db.get_company.assert_called_once_with("c1")

    def test_generate_batch_disabled_returns_empty_without_looping(self):
        from backend.app.agents.outreach_agent import OutreachAgent

        agent = OutreachAgent(workspace_id=WORKSPACE_ID)
        agent.db = MagicMock()
        agent.generate_draft = MagicMock()

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=False,
        ):
            result = agent.generate_batch(company_ids=["c1", "c2", "c3"], sequence_step="touch_1")

        assert result == []
        agent.generate_draft.assert_not_called()
        agent.db.get_contacts_for_company.assert_not_called()


class TestPersonalizationEngineDirectGate:
    """POST /api/personalization/run/{company_id} calls
    PersonalizationEngine.run_full_pipeline() directly — NOT through
    PersonalizationBatch.run_batch(), so that gate does not cover it.
    Missed by the first version of this gate; found by adversarial review.
    """

    def test_disabled_raises_before_any_db_call(self):
        from backend.app.core.personalization_engine import PersonalizationEngine

        engine = PersonalizationEngine(workspace_id=WORKSPACE_ID)
        engine.db = MagicMock()

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=False,
        ):
            try:
                engine.run_full_pipeline(company_id="c1")
                assert False, "expected RuntimeError"
            except RuntimeError as e:
                assert "LLM_GENERATION_ENABLED" in str(e)

        engine.db.get_company.assert_not_called()

    def test_enabled_proceeds_past_the_gate(self):
        from backend.app.core.personalization_engine import PersonalizationEngine

        engine = PersonalizationEngine(workspace_id=WORKSPACE_ID)
        engine.db = MagicMock()
        engine.db.get_company.return_value = None  # -> raises ValueError next, fine for this test

        with patch(
            "backend.app.core.llm_generation_gate.generation_enabled",
            return_value=True,
        ):
            try:
                engine.run_full_pipeline(company_id="c1")
            except ValueError:
                pass  # expected — company_id doesn't resolve to a real company

        engine.db.get_company.assert_called_once_with("c1")
