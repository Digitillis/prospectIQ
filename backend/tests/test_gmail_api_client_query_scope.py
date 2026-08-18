"""fetch_recent_replies() must not scope its search to in:inbox.

A reply quoting our own outbound email inherits its unsubscribe URL text
(which contains "prospectiq" as a substring of the Railway deploy URL).
Any user-side Gmail filter matching that text and archiving the message
(removing the INBOX label) makes the reply permanently invisible to an
in:inbox-scoped search — observed directly 2026-08-18 against a real
reply that Gmail had accepted and stored, but which this query never
found. Dropping in:inbox widens the search to All Mail, which still
excludes Spam/Trash by default (messages.list without
includeSpamTrash=True).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_fetch_recent_replies_query_is_not_scoped_to_inbox():
    from backend.app.integrations import gmail_api_client

    fake_service = MagicMock()
    fake_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": []
    }

    with patch.object(gmail_api_client, "_build_service", return_value=fake_service):
        gmail_api_client.fetch_recent_replies("avi@digitillis.io")

    list_call = fake_service.users.return_value.messages.return_value.list
    assert list_call.called, "expected messages.list to be called"
    query = list_call.call_args.kwargs.get("q", "")

    assert "in:inbox" not in query, (
        "query must not require in:inbox — a locally-archived reply "
        f"(INBOX label removed by an unrelated filter) would never match. Got: {query!r}"
    )
    assert "-from:avi@digitillis.io" in query, "must still exclude mail we sent ourselves"
