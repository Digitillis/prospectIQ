"""_withdraw_stale_invites must not abort the whole batch when one
withdrawal fails. Before this fix, a network exception from one
unipile.withdraw_invitation() call (its own 200/204 check catches HTTP
error codes, but the underlying httpx call can still raise on a timeout or
connection reset) propagated out of the per-invite loop and was caught only
by the outer try/except spanning the whole method -- silently dropping
every remaining invite in that batch and skipping the result.add_detail()
call entirely. Same whole-batch-abort pattern already found and fixed for
_send_connection_requests/_send_opening_dms (see test_linkedin_suppression.py's
TestBatchIsolation). See backend/app/agents/linkedin_sender.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from backend.app.agents.base import AgentResult
from backend.app.agents.linkedin_sender import LinkedInSenderAgent


def _make_agent() -> LinkedInSenderAgent:
    agent = object.__new__(LinkedInSenderAgent)
    agent.db = MagicMock()
    agent.workspace_id = "ws-1"
    return agent


def _stale_invite(invite_id: str) -> dict:
    sent_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    return {"id": invite_id, "sent_at": sent_at}


class TestStaleInviteWithdrawalIsolation:
    def test_one_failing_withdrawal_does_not_abort_the_rest(self):
        agent = _make_agent()
        unipile = MagicMock()
        unipile.list_pending_invitations.return_value = [
            _stale_invite("inv-bad"),
            _stale_invite("inv-good-1"),
            _stale_invite("inv-good-2"),
        ]

        def _withdraw_side_effect(invite_id):
            if invite_id == "inv-bad":
                raise ConnectionError("transient network failure")
            return True

        unipile.withdraw_invitation.side_effect = _withdraw_side_effect
        result = AgentResult()

        agent._withdraw_stale_invites(unipile, dry_run=False, result=result)

        # All three invitations must have been attempted, not just the first.
        assert unipile.withdraw_invitation.call_count == 3
        # The two good ones succeeded; the bad one's exception didn't stop them.
        detail = next(d for d in result.details if d["company"] == "stale_invites")
        assert detail["message"] == "2/3"

    def test_all_succeed_reports_full_count(self):
        agent = _make_agent()
        unipile = MagicMock()
        unipile.list_pending_invitations.return_value = [
            _stale_invite("inv-1"),
            _stale_invite("inv-2"),
        ]
        unipile.withdraw_invitation.return_value = True
        result = AgentResult()

        agent._withdraw_stale_invites(unipile, dry_run=False, result=result)

        detail = next(d for d in result.details if d["company"] == "stale_invites")
        assert detail["message"] == "2/2"

    def test_no_stale_invites_is_a_noop(self):
        agent = _make_agent()
        unipile = MagicMock()
        unipile.list_pending_invitations.return_value = []
        result = AgentResult()

        agent._withdraw_stale_invites(unipile, dry_run=False, result=result)

        unipile.withdraw_invitation.assert_not_called()
        assert result.details == []
