"""Tests for the quality-gate parity fix on backend/app/agents/outreach_agent.py's
OutreachAgent.generate_draft() — a class distinct from outreach.py's OutreachAgent
of the same name (see test_llm_generation_gate.py's TestOutreachAgentSecondClassGate).

Adversarial review (2026-08-17) found this class, reachable via
POST /api/outreach/generate and a live dashboard button, had neither of the two
safeguards outreach.py's writer already had: no fabrication-detection gate
(_check_draft_integrity) and no abstention when a company has no research
grounding. With empty research data its own prompt still instructed the model
to name "a specific, verifiable fact" as the first sentence — a built-in
hallucination pressure with nothing downstream to catch it. It also never set
the `model` field on inserted drafts, so even a fixed draft would have been
silently filtered out of the send schedule by send_scheduler.py's model-tag
filter (the same bug class PR #170 fixed for the Claude Code workflow path).

These tests prove:
  1. Abstention fires before any Anthropic call when a company has no grounding.
  2. The fabrication gate rejects a draft matching _check_draft_integrity's rules.
  3. require_hook_source=False is actually wired: a grounded, non-fabricated
     draft with no source URL in personalization_notes is NOT rejected for
     missing_hook_source — that check would otherwise fire on 100% of this
     class's drafts (verified against 200+ real personalization_hooks rows,
     none contain a URL).
  4. The model field is now always set on inserted drafts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _base_settings():
    return MagicMock(anthropic_api_key="test-key")


def _company(**overrides):
    base = {
        "id": "co1",
        "name": "Acme Manufacturing",
        "tier": "mfg3",
        "research_summary": None,
        "personalization_hooks": [],
        "pain_signals": [],
        "campaign_cluster": "mfg",
        "manufacturing_profile": {},
        "city": "Chicago",
        "state": "IL",
    }
    base.update(overrides)
    return base


def _contact(**overrides):
    base = {
        "id": "ct1",
        "full_name": "Jane Doe",
        "first_name": "Jane",
        "title": "VP Operations",
        "persona_type": "vp_ops",
        "seniority": "vp",
    }
    base.update(overrides)
    return base


def _llm_output(subject: str, body: str, notes: str) -> str:
    """Build raw model output matching _parse_draft_output's expected format:
    marker lines (SUBJECT:/BODY:/PERSONALIZATION_NOTES:) with content on
    SEPARATE following lines -- content on the same line as BODY:/
    PERSONALIZATION_NOTES: is silently discarded by the real parser."""
    return f"SUBJECT: {subject}\nBODY:\n{body}\nPERSONALIZATION_NOTES:\n{notes}"


def _make_agent(company: dict, contact: dict, resend_text: str) -> tuple[MagicMock, MagicMock]:
    """Build an OutreachAgent with db mocked and Anthropic mocked to return
    resend_text as the model output. Returns (agent, mock_anthropic_client)."""
    from backend.app.agents.outreach_agent import OutreachAgent

    agent = OutreachAgent(workspace_id=WORKSPACE_ID)
    agent.db = MagicMock()
    agent.db.get_company.return_value = company
    agent.db.get_contacts_for_company.return_value = [contact]
    agent.db.client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.limit.return_value.execute.return_value.data = []
    agent.db.insert_outreach_draft.side_effect = lambda d: d
    agent.track_cost = MagicMock()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=resend_text)]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return agent, mock_client


class TestAbstentionWithoutGrounding:
    def test_raises_before_any_anthropic_call_when_ungrounded(self):
        company = _company()  # no research_summary, no hooks, no pains
        contact = _contact()
        agent, mock_client = _make_agent(company, contact, resend_text="unused")

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            try:
                agent.generate_draft(company_id="co1", contact_id="ct1", sequence_step="touch_1")
                assert False, "expected ValueError for ungrounded company"
            except ValueError as e:
                assert "research" in str(e).lower() or "grounding" in str(e).lower()

        mock_client.messages.create.assert_not_called()

    def test_proceeds_when_research_summary_is_prose_not_json(self):
        """Second independent review (2026-08-17) found the original abstention
        check gated on the post-json.loads() research_summary dict, but
        company.research_summary is always real prose in production (its only
        writers never emit JSON) -- so json.loads() always raises and the dict
        always collapses to {}, regardless of how much genuine research text
        exists. That would make a company with real research prose but empty
        hooks/pains incorrectly abstain. Must ground on the raw string instead."""
        company = _company(research_summary="A real manufacturer of aerospace fasteners.")
        contact = _contact()
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Hi", "Hi Jane, real body text grounded in research prose.", "internal notes"
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            agent.generate_draft(company_id="co1", contact_id="ct1", sequence_step="touch_1")

        mock_client.messages.create.assert_called_once()

    def test_raises_when_hooks_are_present_but_empty_strings(self):
        """Second independent review (2026-08-17): a list of empty/whitespace
        strings is truthy in Python, so the original check would not abstain
        even though there is no usable content -- reaching the prompt as
        ungrounded filler, exactly the hallucination pressure this gate exists
        to stop."""
        company = _company(personalization_hooks=["", "   "], pain_signals=["  "])
        contact = _contact()
        agent, mock_client = _make_agent(company, contact, resend_text="unused")

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            try:
                agent.generate_draft(company_id="co1", contact_id="ct1", sequence_step="touch_1")
                assert False, "expected ValueError for whitespace-only hooks/pains"
            except ValueError:
                pass

        mock_client.messages.create.assert_not_called()

    def test_raises_when_research_summary_is_whitespace_only(self):
        """Third independent review (2026-08-17): bool(raw_research) didn't
        strip whitespace, so a whitespace-only research_summary would bypass
        abstention the same way empty-string hooks originally did."""
        company = _company(research_summary="   \n  ")
        contact = _contact()
        agent, mock_client = _make_agent(company, contact, resend_text="unused")

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            try:
                agent.generate_draft(company_id="co1", contact_id="ct1", sequence_step="touch_1")
                assert False, "expected ValueError for whitespace-only research_summary"
            except ValueError:
                pass

        mock_client.messages.create.assert_not_called()

    def test_non_string_hook_element_does_not_crash(self):
        """Third independent review (2026-08-17): personalization_hooks is
        written from unvalidated LLM JSON with no per-element type
        enforcement -- a non-string element (e.g. a malformed row) must not
        crash generate_draft() with an unhandled AttributeError."""
        company = _company(personalization_hooks=["", 5, None], pain_signals=[])
        contact = _contact()
        agent, mock_client = _make_agent(company, contact, resend_text="unused")

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            try:
                agent.generate_draft(company_id="co1", contact_id="ct1", sequence_step="touch_1")
                assert False, "expected a clean ValueError, not a crash"
            except ValueError:
                pass  # correct: no real string content -> abstain cleanly
            except AttributeError:
                assert False, "non-string list element must not crash .strip()"

    def test_proceeds_when_pain_signals_alone_provide_grounding(self):
        """Grounding check is OR across research_summary/hooks/pains — pain_signals
        alone must be enough, matching how the method actually reads company data."""
        company = _company(pain_signals=["Unplanned downtime on line 3"])
        contact = _contact()
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Hi", "Hi Jane, real body text here.", "internal notes, no url"
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            agent.generate_draft(company_id="co1", contact_id="ct1", sequence_step="touch_1")

        mock_client.messages.create.assert_called_once()


class TestFabricationGate:
    def test_rejects_draft_matching_integrity_rule(self):
        company = _company(pain_signals=["Unplanned downtime on line 3"])
        contact = _contact()
        # "step 1" in the body matches _INTEGRITY_RULES' step_label_leak pattern.
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Following up",
                "Hi Jane, following up on step 1 of our conversation.",
                "internal notes, no url",
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            result = agent.generate_draft(
                company_id="co1", contact_id="ct1", sequence_step="touch_1"
            )

        assert result["approval_status"] == "rejected"
        assert result["rejection_reason"].startswith("auto_rejected|")
        assert "step_label_leak" in result["rejection_reason"]

    def test_reason_preserves_both_violations_when_draft_trips_two_checks(self):
        """Second independent review (2026-08-17): the integrity check and the
        step-1 URL check used to each unconditionally overwrite
        rejection_reason in separate if-blocks, so a draft tripping both lost
        the integrity violation's detail (which fabrication rule fired) --
        approval_status stayed 'rejected' either way, so nothing was silently
        accepted, but the diagnostic detail was clobbered. Both must survive."""
        company = _company(pain_signals=["Unplanned downtime on line 3"])
        contact = _contact()
        # step 1 (default sequence_step="touch_1") + a URL -> url_in_step_1;
        # "one plant identified" -> fabricated_anecdote. Both should fire.
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Quick question",
                "Check this out: https://example.com/demo — one plant identified this last year.",
                "internal notes, no url here",
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            result = agent.generate_draft(
                company_id="co1", contact_id="ct1", sequence_step="touch_1"
            )

        assert result["approval_status"] == "rejected"
        assert "fabricated_anecdote" in result["rejection_reason"]
        assert "url_in_step_1" in result["rejection_reason"]

    def test_url_in_step_1_survives_truncation_with_four_other_violations(self):
        """Third independent review (2026-08-17): the [:4] truncation could
        still silently drop url_in_step_1 if 4+ integrity violations fired
        first and it was only ever appended last. Four distinct, independently
        firing tags (step_label_leak, fabricated_anecdote, past_customer_claim,
        recycled_stat) plus a step-1 URL must all be representable -- at
        minimum url_in_step_1 must survive regardless of ordering."""
        company = _company(pain_signals=["Unplanned downtime on line 3"])
        contact = _contact()
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Quick question",
                "Check this out: https://example.com/demo — following up on step 1. "
                "Here's what we found: one plant identified 15-20% of available "
                "machine time lost to downtime.",
                "internal notes, no url here",
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            result = agent.generate_draft(
                company_id="co1", contact_id="ct1", sequence_step="touch_1"
            )

        assert result["approval_status"] == "rejected"
        assert "url_in_step_1" in result["rejection_reason"]

    def test_require_hook_source_false_does_not_reject_clean_grounded_draft(self):
        """The URL-source requirement must NOT fire for this class -- its hooks
        have no URL-provenance mechanism (see outreach.py's _check_draft_integrity
        docstring). A clean, grounded, non-fabricated draft with no URL in notes
        must pass, or every real draft from this path would auto-reject."""
        company = _company(pain_signals=["Unplanned downtime on line 3"])
        contact = _contact()
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Quick question",
                "Hi Jane, noticed your team runs a lot of unplanned downtime "
                "on line 3. Worth a conversation?",
                "internal notes, no url here",
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            result = agent.generate_draft(
                company_id="co1", contact_id="ct1", sequence_step="touch_1"
            )

        assert result["approval_status"] == "pending"
        assert "rejection_reason" not in result or result.get("rejection_reason") is None


class TestModelTagAlwaysSet:
    def test_inserted_draft_carries_model_field(self):
        company = _company(pain_signals=["Unplanned downtime on line 3"])
        contact = _contact()
        agent, mock_client = _make_agent(
            company,
            contact,
            resend_text=_llm_output(
                "Quick question", "Hi Jane, real grounded body text about line 3.", "internal notes"
            ),
        )

        with (
            patch(
                "backend.app.core.llm_generation_gate.generation_enabled",
                return_value=True,
            ),
            patch("backend.app.agents.outreach_agent.get_settings", return_value=_base_settings()),
            patch("anthropic.Anthropic", return_value=mock_client),
        ):
            result = agent.generate_draft(
                company_id="co1", contact_id="ct1", sequence_step="touch_1"
            )

        assert result.get("model"), "model field must be set or the draft is silently unschedulable"
