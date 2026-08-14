"""_gmail_intake_workspace() must actually persist inbound replies.

Two independent schema-mismatch bugs previously made thread_messages hold
2,727 rows — all outbound, zero inbound — despite the poller running every
15 minutes and matching replies to drafts correctly:

  1. The dedup query filtered thread_messages on `contact_id`, a column that
     does not exist on that table, and was NOT wrapped in try/except — so it
     raised on the first matched reply and aborted every subsequent reply in
     that mailbox's poll for the entire tick.
  2. The inbound insert omitted `sent_at` (NOT NULL, no column default) and
     wrote source='gmail_imap' (CHECK-constrained to
     'manual'|'instantly_webhook'|'gmail_webhook') — both violate the schema
     and the insert was wrapped in a narrow try/except that logged and
     silently dropped every reply, forever.

See backend/app/api/main.py, _gmail_intake_workspace().
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class _RoutedFakeTable:
    """A chainable Supabase-query-builder stand-in for ONE table.

    Supports both call-chain forms the real client uses:
      .select(...).eq(...).limit(...)   — attribute access immediately called
      .not_.is_(...)                    — attribute access returns a
                                           chainable object BEFORE being
                                           called (`.not_` is a bare
                                           property, not a method)

    __getattr__ always returns self (so `.not_` alone is valid and
    chainable); __call__ records the *most recently accessed* attribute
    name against its call args. `.execute()` is a real method, so normal
    attribute lookup finds it directly without going through __getattr__.
    """

    def __init__(self, data=None):
        self._data = data if data is not None else []
        self.calls: list[tuple[str, tuple, dict]] = []
        self.insert_payloads: list[dict] = []
        self._pending_name: str | None = None

    def __getattr__(self, name):
        self._pending_name = name
        return self

    def __call__(self, *args, **kwargs):
        name = self._pending_name
        self.calls.append((name, args, kwargs))
        if name == "insert" and args:
            self.insert_payloads.append(args[0])
        return self

    def execute(self):
        result = MagicMock()
        result.data = self._data
        return result


def _make_routed_db(tables: dict[str, _RoutedFakeTable]) -> MagicMock:
    db = MagicMock()

    def _table(name):
        return tables.setdefault(name, _RoutedFakeTable())

    db.client.table.side_effect = _table
    return db


def test_inbound_reply_insert_has_required_sent_at_and_valid_source():
    """The insert payload for an inbound reply must include sent_at and use
    a source value the CHECK constraint actually allows.
    """
    from backend.app.api import main as main_mod

    draft = {
        "id": "draft-1",
        "company_id": "co-1",
        "contact_id": "ct-1",
        "sequence_name": "email_value_first",
        "sequence_step": 1,
        "workspace_id": "ws-1",
    }
    received_at = datetime.now(timezone.utc).isoformat()

    tables = {
        "outreach_drafts": _RoutedFakeTable(data=[draft]),
        "campaign_threads": _RoutedFakeTable(data=[]),  # no existing thread -> create
        "thread_messages": _RoutedFakeTable(data=[]),  # no existing dedup match
        "interactions": _RoutedFakeTable(data=[]),
        "scheduler_state": _RoutedFakeTable(data=[]),
        "contacts": _RoutedFakeTable(data=[]),
    }
    db = _make_routed_db(tables)

    # campaign_threads insert must return a new thread id for thread_id
    # resolution to succeed.
    orig_table = tables["campaign_threads"]

    def _ct_execute():
        result = MagicMock()
        if orig_table.calls and orig_table.calls[-1][0] == "insert":
            result.data = [{"id": "thread-new-1"}]
        else:
            result.data = []
        return result

    tables["campaign_threads"].execute = _ct_execute

    fake_reply = {
        "from_email": "prospect@example.com",
        "subject": "Re: quick question about your maintenance program",
        "body": "Not the right department, please reach out to our ops director instead.",
        "received_at": received_at,
        "uid": "uid-1",
    }

    fake_gmail_client = MagicMock()
    fake_gmail_client.__enter__.return_value = fake_gmail_client
    fake_gmail_client.__exit__.return_value = False
    fake_gmail_client.fetch_since_replies.return_value = [fake_reply]

    ws = {
        "id": "ws-1",
        "name": "Test WS",
        "settings": {"sender_pool": []},
    }

    with (
        patch("backend.app.core.credential_store.CredentialStore") as mock_creds_cls,
        patch("backend.app.core.database.Database", return_value=db),
        patch("backend.app.integrations.gmail_imap.GmailImapClient", return_value=fake_gmail_client),
        patch("backend.app.integrations.gmail_imap._classify_intent", return_value="other"),
        patch.dict("os.environ", {}, clear=False),
    ):
        mock_creds = mock_creds_cls.return_value
        mock_creds.get.side_effect = lambda provider, key: {
            ("gmail", "user"): "sender@example.com",
            ("gmail", "app_password"): "app-password-value",
        }.get((provider, key))

        # Force IMAP path, not Gmail API path.
        for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
            import os

            os.environ.pop(var, None)

        main_mod._gmail_intake_workspace(ws)

    tm_table = tables["thread_messages"]
    assert tm_table.insert_payloads, "Expected an insert on thread_messages for the inbound reply"
    payload = tm_table.insert_payloads[0]

    assert payload.get("sent_at"), "sent_at is NOT NULL with no default — must be set on every insert"
    assert payload.get("source") == "gmail_webhook", (
        f"source must be a value the CHECK constraint allows "
        f"('manual'|'instantly_webhook'|'gmail_webhook'), got {payload.get('source')!r}"
    )
    assert payload.get("direction") == "inbound"


def test_dedup_query_does_not_filter_thread_messages_by_contact_id():
    """thread_messages has no contact_id column. The dedup query must not
    reference it, or it raises PGRST204 and (previously, unguarded) aborted
    every subsequent reply in the same poll.
    """
    from backend.app.api import main as main_mod

    draft = {
        "id": "draft-1",
        "company_id": "co-1",
        "contact_id": "ct-1",
        "sequence_name": "email_value_first",
        "sequence_step": 1,
        "workspace_id": "ws-1",
    }
    received_at = datetime.now(timezone.utc).isoformat()

    tables = {
        "outreach_drafts": _RoutedFakeTable(data=[draft]),
        "campaign_threads": _RoutedFakeTable(data=[{"id": "thread-existing-1"}]),
        "thread_messages": _RoutedFakeTable(data=[]),
        "interactions": _RoutedFakeTable(data=[]),
        "scheduler_state": _RoutedFakeTable(data=[]),
        "contacts": _RoutedFakeTable(data=[]),
    }
    db = _make_routed_db(tables)

    fake_reply = {
        "from_email": "prospect@example.com",
        "subject": "Re: quick question",
        "body": "Thanks, not relevant to my role.",
        "received_at": received_at,
        "uid": "uid-2",
    }
    fake_gmail_client = MagicMock()
    fake_gmail_client.__enter__.return_value = fake_gmail_client
    fake_gmail_client.__exit__.return_value = False
    fake_gmail_client.fetch_since_replies.return_value = [fake_reply]

    ws = {"id": "ws-1", "name": "Test WS", "settings": {"sender_pool": []}}

    with (
        patch("backend.app.core.credential_store.CredentialStore") as mock_creds_cls,
        patch("backend.app.core.database.Database", return_value=db),
        patch("backend.app.integrations.gmail_imap.GmailImapClient", return_value=fake_gmail_client),
        patch("backend.app.integrations.gmail_imap._classify_intent", return_value="other"),
    ):
        mock_creds = mock_creds_cls.return_value
        mock_creds.get.side_effect = lambda provider, key: {
            ("gmail", "user"): "sender@example.com",
            ("gmail", "app_password"): "app-password-value",
        }.get((provider, key))

        import os

        for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
            os.environ.pop(var, None)

        main_mod._gmail_intake_workspace(ws)

    tm_table = tables["thread_messages"]
    filter_calls = [c for c in tm_table.calls if c[0] in ("eq", "gte", "not_", "is_")]
    referenced_columns = {c[1][0] for c in filter_calls if c[1]}
    assert "contact_id" not in referenced_columns, (
        "Dedup query must not filter thread_messages by contact_id — that "
        "column does not exist on the table"
    )
