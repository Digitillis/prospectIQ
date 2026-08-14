"""PATCH/GET /api/settings/outreach-guidelines's sender_physical_address must
persist in the database (outreach_send_config.sender_physical_address,
migration 065), not config/outreach_guidelines.yaml.

The YAML file lives on the Railway container's local filesystem, which has
no attached persistent volume (Railpack build, no Dockerfile/railway.toml
declaring one — confirmed directly against the live Railway service
config). A value written there via this PATCH endpoint was silently lost on
the next redeploy, for any reason, even one unrelated to this field —
meaning a routine deploy could silently re-block all outbound sending right
after someone thought they'd fixed it. See backend/app/core/unsubscribe.py's
compliance_footer_text() and supabase_migrations/migrations/
065_outreach_send_config_physical_address.sql.

Route functions are called directly (bypassing FastAPI's dependency
injection / require_role auth chain, which is untested infrastructure this
fix doesn't touch) so these tests exercise the real route logic without
needing to stand up the full auth stack.
"""

from __future__ import annotations

import yaml
from unittest.mock import MagicMock, patch

import pytest


_MINIMAL_GUIDELINES_YAML = """
version: "1.0"
sender:
  name: "Test Sender"
  company: "Acme"
"""


@pytest.fixture
def guidelines_file(tmp_path):
    path = tmp_path / "outreach_guidelines.yaml"
    path.write_text(_MINIMAL_GUIDELINES_YAML)
    return path


class _FakeConfigTable:
    """Models outreach_send_config for a single workspace's
    sender_physical_address column — enough to test both the read path
    (get_guidelines) and the write path (patch_guidelines).
    """

    def __init__(self, existing_row: bool = True):
        self.updates: list[dict] = []
        self._value = None
        self._existing_row = existing_row
        self._filtered_workspace_id = None

    def select(self, *a, **k):
        return self

    def update(self, payload: dict):
        self.updates.append(payload)
        if self._existing_row:
            self._value = payload.get("sender_physical_address")
        return self

    def eq(self, field, value, *a, **k):
        if field == "workspace_id":
            self._filtered_workspace_id = value
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        result = MagicMock()
        if not self._existing_row:
            result.data = []
        else:
            result.data = [{"sender_physical_address": self._value}]
        return result


class _FakeSupabaseClient:
    def __init__(self, config_table: _FakeConfigTable):
        self._config_table = config_table

    def table(self, name):
        if name == "outreach_send_config":
            return self._config_table
        raise AssertionError(f"unexpected table access: {name}")


class TestPatchGuidelinesPhysicalAddress:
    def test_writes_to_database_not_yaml(self, guidelines_file):
        from backend.app.api.routes.settings import patch_guidelines, GuidelinesPatch

        config_table = _FakeConfigTable(existing_row=True)
        fake_client = _FakeSupabaseClient(config_table)

        with (
            patch("backend.app.api.routes.settings.CONFIG_DIR", guidelines_file.parent),
            patch(
                "backend.app.core.database.get_supabase_client",
                return_value=fake_client,
            ),
        ):
            payload = GuidelinesPatch(sender_physical_address="123 Main St, Chicago, IL")
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                patch_guidelines(payload, _role=None)
            )

        # The DB was written.
        assert config_table.updates == [{"sender_physical_address": "123 Main St, Chicago, IL"}]
        # The YAML file was NOT touched with this field.
        on_disk = yaml.safe_load(guidelines_file.read_text())
        assert "physical_address" not in on_disk.get("sender", {})
        # The response surfaces the new value even though it's not in the YAML.
        assert result["data"]["sender"]["physical_address"] == "123 Main St, Chicago, IL"

    def test_raises_if_no_matching_workspace_row(self, guidelines_file):
        """update().eq() on a workspace_id with no row returns an empty data
        list rather than raising — silently reporting success on a PATCH
        that changed nothing would be exactly the class of bug this repo's
        review discipline exists to catch.
        """
        from backend.app.api.routes.settings import patch_guidelines, GuidelinesPatch
        from fastapi import HTTPException

        config_table = _FakeConfigTable(existing_row=False)
        fake_client = _FakeSupabaseClient(config_table)

        with (
            patch("backend.app.api.routes.settings.CONFIG_DIR", guidelines_file.parent),
            patch(
                "backend.app.core.database.get_supabase_client",
                return_value=fake_client,
            ),
        ):
            payload = GuidelinesPatch(sender_physical_address="123 Main St")
            import asyncio

            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(patch_guidelines(payload, _role=None))
        assert exc_info.value.status_code == 500

    def test_omitting_field_does_not_touch_database(self, guidelines_file):
        from backend.app.api.routes.settings import patch_guidelines, GuidelinesPatch

        config_table = _FakeConfigTable(existing_row=True)
        fake_client = _FakeSupabaseClient(config_table)

        with (
            patch("backend.app.api.routes.settings.CONFIG_DIR", guidelines_file.parent),
            patch(
                "backend.app.core.database.get_supabase_client",
                return_value=fake_client,
            ),
        ):
            payload = GuidelinesPatch(sender_name="New Name")  # physical_address omitted
            import asyncio

            asyncio.get_event_loop().run_until_complete(patch_guidelines(payload, _role=None))

        assert config_table.updates == []


class TestGetGuidelinesPhysicalAddress:
    def test_reads_physical_address_from_database(self, guidelines_file):
        from backend.app.api.routes.settings import get_guidelines

        config_table = _FakeConfigTable(existing_row=True)
        config_table._value = "999 Existing Address Ave"
        fake_client = _FakeSupabaseClient(config_table)

        with patch(
            "backend.app.core.database.get_supabase_client",
            return_value=fake_client,
        ):
            import asyncio

            with patch("backend.app.core.config.CONFIG_DIR", guidelines_file.parent):
                result = asyncio.get_event_loop().run_until_complete(get_guidelines())

        assert result["data"]["sender"]["physical_address"] == "999 Existing Address Ave"
