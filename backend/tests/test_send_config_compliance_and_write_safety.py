"""Tests for GET /api/admin/send-config (backend/app/api/main.py:
send_config_check), covering two 2026-08-15 send-path reconciliation
findings:

  - Finding 6: the endpoint's write-permission probe did
    `.update({"notes": None})`, permanently clobbering
    outreach_send_config.notes on every call — including the audit trail
    of the 2026-08-14 daily_limit/batch_size reset recorded there. A
    read-only diagnostic must not destroy state.
  - Findings 2 + the general readiness gap: BACKEND_PUBLIC_URL and
    sender_physical_address are both unset in production, and there was
    no single queryable signal for "can this workspace send a compliant
    email right now" — only three separate startup log WARNINGs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _authed_client():
    from backend.app.api.main import app
    from backend.app.core.auth import get_current_user

    async def _stub(request=None):
        return {
            "user_id": "u1",
            "email": "a@b.com",
            "workspace_id": WORKSPACE_ID,
            "auth_method": "bearer",
        }

    app.dependency_overrides[get_current_user] = _stub
    return app, TestClient(app, raise_server_exceptions=False)


def _mock_supabase_client(cfg_row: dict | None):
    """Build a client whose outreach_send_config .select().eq().limit()
    .execute().data returns [cfg_row] (or [] if cfg_row is None), and
    whose outreach_drafts queries return empty/zero results. Records
    every .update() call on outreach_send_config so a test can assert
    exactly what was written.
    """
    client = MagicMock()
    update_calls: list[dict] = []

    def table(name):
        t = MagicMock()
        if name == "outreach_send_config":
            select_chain = MagicMock()
            select_chain.eq.return_value = select_chain
            select_chain.limit.return_value = select_chain
            select_chain.execute.return_value.data = [cfg_row] if cfg_row else []
            t.select.return_value = select_chain

            update_chain = MagicMock()
            update_chain.eq.return_value = update_chain

            def _record_update(payload):
                update_calls.append(payload)
                return update_chain

            t.update.side_effect = _record_update
            update_chain.execute.return_value.data = [{"workspace_id": WORKSPACE_ID}]
        elif name == "outreach_drafts":
            drafts_chain = MagicMock()
            for attr in ("select", "eq", "gte", "is_", "limit"):
                getattr(drafts_chain, attr).return_value = drafts_chain
            drafts_chain.execute.return_value.count = 0
            drafts_chain.execute.return_value.data = []
            t.select.return_value = drafts_chain
        else:
            t.select.return_value.execute.return_value.data = []
        return t

    client.table.side_effect = table
    return client, update_calls


class TestWritePermissionProbeIsNonDestructive:
    def test_writes_back_the_same_notes_value_read(self):
        client, update_calls = _mock_supabase_client(
            cfg_row={
                "daily_limit": 1,
                "batch_size": 1,
                "min_gap_minutes": 0,
                "send_enabled": False,
                "notes": "RESET 2026-08-14 (session reconciliation, Avanish-authorized)",
                "sender_physical_address": None,
            }
        )
        app, tc = _authed_client()
        try:
            with patch("backend.app.core.database.get_supabase_client", return_value=client):
                r = tc.get("/api/admin/send-config")
            assert r.status_code == 200
            body = r.json()
            assert body["update_permission_test"] == "ok"
        finally:
            app.dependency_overrides.clear()

        assert update_calls == [
            {"notes": "RESET 2026-08-14 (session reconciliation, Avanish-authorized)"}
        ]
        # The bug this replaces would have produced {"notes": None} here.
        assert update_calls[0]["notes"] is not None

    def test_skips_write_probe_when_no_row_for_workspace(self):
        client, update_calls = _mock_supabase_client(cfg_row=None)
        app, tc = _authed_client()
        try:
            with patch("backend.app.core.database.get_supabase_client", return_value=client):
                r = tc.get("/api/admin/send-config")
            assert r.status_code == 200
            assert r.json()["update_permission_test"] == "skipped_no_row_for_workspace"
        finally:
            app.dependency_overrides.clear()

        assert update_calls == []


class TestComplianceReadiness:
    def test_all_three_missing_reports_not_ready(self):
        client, _ = _mock_supabase_client(cfg_row={"notes": "x", "sender_physical_address": None})
        settings = MagicMock(
            send_enabled=False,
            resend_api_key="",
            supabase_service_key="",
            send_window_start=8,
            send_window_end=11,
            backend_public_url="",
            webhook_secret="",
        )
        app, tc = _authed_client()
        try:
            with (
                patch("backend.app.core.database.get_supabase_client", return_value=client),
                patch("backend.app.core.config.get_settings", return_value=settings),
            ):
                r = tc.get("/api/admin/send-config")
            body = r.json()
        finally:
            app.dependency_overrides.clear()

        assert body["compliance_ready"] is False
        assert set(body["compliance_missing"]) == {
            "sender_physical_address",
            "backend_public_url",
            "webhook_secret",
        }

    def test_all_three_present_reports_ready(self):
        client, _ = _mock_supabase_client(
            cfg_row={"notes": "x", "sender_physical_address": "123 Main St, Austin, TX"}
        )
        settings = MagicMock(
            send_enabled=False,
            resend_api_key="",
            supabase_service_key="",
            send_window_start=8,
            send_window_end=11,
            backend_public_url="https://prospectiq-production-4848.up.railway.app",
            webhook_secret="whsec_abc123",
        )
        app, tc = _authed_client()
        try:
            with (
                patch("backend.app.core.database.get_supabase_client", return_value=client),
                patch("backend.app.core.config.get_settings", return_value=settings),
            ):
                r = tc.get("/api/admin/send-config")
            body = r.json()
        finally:
            app.dependency_overrides.clear()

        assert body["compliance_ready"] is True
        assert body["compliance_missing"] == []
