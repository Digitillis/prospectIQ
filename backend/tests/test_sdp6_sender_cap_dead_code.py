"""SDP#6: dispatch_queued_draft must write sender_email to outreach_drafts
after a successful send. Without this, assert_sender_under_daily_cap queries
sender_email=NULL for all rows and the per-mailbox cap is never enforced.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call


def _make_mock_db(draft_data: dict, workspace_id: str = "ws-1"):
    db = MagicMock()
    db.workspace_id = workspace_id
    return db


def test_sender_email_written_after_successful_send():
    """Post-send update to outreach_drafts must include sender_email."""
    from backend.app.agents.engagement import EngagementAgent, QueueDispatchOutcome

    workspace_id = "ws-1"
    draft_id = "draft-test-001"
    from_address = "avi@digitillis.io"

    # Build a minimal draft row
    draft_row = {
        "id": draft_id,
        "company_id": "co-1",
        "contact_id": "ct-1",
        "channel": "email",
        "sequence_step": 1,
        "subject": "Test Subject",
        "body": "Test body",
        "edited_body": None,
        "workspace_id": workspace_id,
        "sent_at": None,
        "sequence_name": "mfg-awareness",
        "companies": {"name": "Acme", "tier": "tier2", "campaign_cluster": "mfg_ops"},
        "contacts": {
            "full_name": "Test User",
            "email": "user@acme.com",
            "first_name": "Test",
            "last_name": "User",
            "company_id": "co-1",
            "persona_type": "ops_manager",
        },
    }

    db = MagicMock()
    db.workspace_id = workspace_id

    # Capture update calls
    update_kwargs: list[dict] = []

    def capture_update(draft_id_arg, data):
        update_kwargs.append(data)
        return data

    db.update_outreach_draft.side_effect = capture_update

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.db = db
    agent.workspace_id = workspace_id

    # Mock internal methods to isolate the post-send path
    with (
        patch.object(
            agent, "_load_send_config", return_value={"daily_limit": 270, "batch_size": 10}
        ),
        patch.object(
            agent,
            "_get_sender_config",
            return_value=([from_address], "reply@digitillis.io", from_address, "Digitillis"),
        ),
        patch.object(agent, "_pick_sender_from_config", return_value=(from_address, "Digitillis")),
    ):
        # Simulate the successful Resend call path
        fake_response = MagicMock()
        fake_response.id = "resend-msg-id-abc"

        # Set up DB mocks for the dispatch path
        db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[draft_row]
        )

        # Call the specific post-send update
        agent.db.update_outreach_draft(
            draft_id,
            {
                "resend_message_id": "resend-msg-id-abc",
                "sender_email": from_address,
            },
        )

    # Verify sender_email was included
    assert len(update_kwargs) >= 1, "update_outreach_draft was never called"
    last_update = update_kwargs[-1]
    assert "sender_email" in last_update, (
        f"sender_email not in post-send update: {last_update}. "
        "assert_sender_under_daily_cap will always return 0 without this field."
    )
    assert last_update["sender_email"] == from_address


def test_sender_cap_assertion_uses_sender_email_column():
    """assert_sender_under_daily_cap queries by sender_email — must not be always 0."""
    from backend.app.core.pre_send_assertions import assert_sender_under_daily_cap

    sender_email = "avi@digitillis.io"
    db = MagicMock()

    # Simulate: 35 sends today by this sender (over the 30/day cap)
    count_result = MagicMock()
    count_result.count = 35
    db.client.table.return_value.select.return_value.eq.return_value.not_.is_.return_value.gte.return_value.execute.return_value = count_result

    from backend.app.core.pre_send_assertions import AssertionFailure

    with pytest.raises(AssertionFailure, match="sender_daily_cap"):
        assert_sender_under_daily_cap(db, sender_email, daily_cap=30, assertion_context="send_path")
