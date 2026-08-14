"""LinkedIn connection requests and DMs must respect suppression/DNC — same
as the email send path (engagement.py). Before this fix, linkedin_sender.py
never called is_suppressed() at all: a contact who unsubscribed from email,
or who was otherwise added to do_not_contact or suppression_log, could
still receive a LinkedIn connection request or DM, because those checks
only ever ran on the email dispatch path. See backend/app/agents/linkedin_sender.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.app.agents.base import AgentResult
from backend.app.agents.linkedin_sender import LinkedInSenderAgent


def _make_agent() -> LinkedInSenderAgent:
    """Construct a LinkedInSenderAgent without hitting BaseAgent.__init__ (which
    would build a real Database() / Supabase client). Tests set db/workspace_id
    directly, mirroring how the agent is actually wired at runtime.
    """
    agent = object.__new__(LinkedInSenderAgent)
    agent.db = MagicMock()
    agent.workspace_id = "ws-1"
    return agent


_DRAFT = {
    "id": "draft-1",
    "company_id": "company-1",
    "contact_id": "contact-1",
    "body": "Hi there",
    "edited_body": None,
    "companies": {"name": "Acme Corp"},
}

_CONTACT = {
    "id": "contact-1",
    "full_name": "Jane Doe",
    "first_name": "Jane",
    "linkedin_url": "https://linkedin.com/in/janedoe",
}


class TestConnectionRequestSuppression:
    def test_suppressed_contact_never_reaches_unipile(self):
        agent = _make_agent()
        agent._get_contact = MagicMock(return_value=_CONTACT)
        unipile = MagicMock()
        result = AgentResult()

        with patch(
            "backend.app.core.suppression.is_suppressed",
            return_value=(True, "do_not_contact:email:unsubscribe"),
        ):
            agent._send_connection_draft(unipile, _DRAFT, dry_run=False, result=result)

        unipile.send_connection_request.assert_not_called()
        assert result.skipped == 1
        assert result.processed == 0
        assert any(d["status"] == "suppressed" for d in result.details)

    def test_non_suppressed_contact_still_sends_normally(self):
        agent = _make_agent()
        agent._get_contact = MagicMock(return_value=_CONTACT)
        unipile = MagicMock()
        result = AgentResult()

        with (
            patch(
                "backend.app.core.suppression.is_suppressed",
                return_value=(False, None),
            ),
            patch("backend.app.core.outbound_validator.OutboundValidator") as mock_validator_cls,
            patch("backend.app.core.linkedin_rate_limiter.LinkedInRateLimiter") as mock_limiter_cls,
        ):
            mock_validator_cls.return_value.validate_linkedin_connect.return_value = None
            mock_limiter_cls.return_value.consume.return_value = True
            agent._send_connection_draft(unipile, _DRAFT, dry_run=False, result=result)

        unipile.send_connection_request.assert_called_once()
        assert result.processed == 1
        assert result.skipped == 0


class TestDMSuppression:
    def test_suppressed_contact_never_receives_dm(self):
        agent = _make_agent()
        agent._get_contact = MagicMock(return_value=_CONTACT)
        unipile = MagicMock()
        result = AgentResult()

        with patch(
            "backend.app.core.suppression.is_suppressed",
            return_value=(True, "contact_status:unsubscribed"),
        ):
            agent._send_dm_draft(unipile, _DRAFT, "opening_dm", dry_run=False, result=result)

        unipile.send_message.assert_not_called()
        assert result.skipped == 1
        assert any(d["status"] == "suppressed" for d in result.details)

    def test_non_suppressed_contact_dm_still_sends_normally(self):
        agent = _make_agent()
        agent._get_contact = MagicMock(return_value=_CONTACT)
        unipile = MagicMock()
        result = AgentResult()

        with (
            patch(
                "backend.app.core.suppression.is_suppressed",
                return_value=(False, None),
            ),
            patch("backend.app.core.outbound_validator.OutboundValidator") as mock_validator_cls,
            patch("backend.app.core.linkedin_rate_limiter.LinkedInRateLimiter") as mock_limiter_cls,
        ):
            mock_validator_cls.return_value.validate_linkedin_dm.return_value = None
            mock_limiter_cls.return_value.consume.return_value = True
            agent._send_dm_draft(unipile, _DRAFT, "opening_dm", dry_run=False, result=result)

        unipile.send_message.assert_called_once()
        assert result.processed == 1
        assert result.skipped == 0

    def test_suppression_checked_before_linkedin_url_lookup(self):
        """A suppressed contact with no linkedin_url should still be classified
        as 'suppressed', not 'no linkedin_url' — suppression must be checked
        first so the real skip reason is recorded, not masked by a data gap.
        """
        agent = _make_agent()
        contact_no_url = dict(_CONTACT, linkedin_url="")
        agent._get_contact = MagicMock(return_value=contact_no_url)
        unipile = MagicMock()
        result = AgentResult()

        with patch(
            "backend.app.core.suppression.is_suppressed",
            return_value=(True, "do_not_contact:email:unsubscribe"),
        ):
            agent._send_dm_draft(unipile, _DRAFT, "opening_dm", dry_run=False, result=result)

        unipile.send_message.assert_not_called()
        assert any(d["status"] == "suppressed" for d in result.details)
