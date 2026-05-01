"""ICP Manager — versioned ICP definitions stored in DB, with YAML fallback.

ICP definitions move from config/icp.yaml to the icp_definitions table so that
every send records which ICP version was active. This makes it possible to
compare reply rates across ICP versions — without it, you cannot know whether
tightening or loosening targeting actually worked.

Usage:
    from backend.app.core.icp_manager import ICPManager
    mgr = ICPManager(db)
    version_id = mgr.active_version_id()
    definition = mgr.active_definition()
    mgr.create_version(payload_dict, label="Q2 tightened")
    mgr.activate(version_id)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ICPManager:
    def __init__(self, db: Any):
        self._db = db

    def active_version_id(self) -> str | None:
        """Return the UUID of the currently active ICP definition, or None."""
        try:
            rows = (
                self._db.client.table("icp_definitions")
                .select("id")
                .eq("is_active", True)
                .limit(1)
                .execute()
                .data or []
            )
            return rows[0]["id"] if rows else None
        except Exception as e:
            logger.warning("Could not fetch active ICP version: %s", e)
            return None

    def active_definition(self) -> dict:
        """Return the active ICP payload dict. Falls back to icp.yaml if no DB version."""
        try:
            rows = (
                self._db.client.table("icp_definitions")
                .select("id,version,label,payload")
                .eq("is_active", True)
                .limit(1)
                .execute()
                .data or []
            )
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("Could not fetch active ICP from DB, falling back to YAML: %s", e)

        # YAML fallback — always available
        try:
            from backend.app.core.config import get_icp_config
            payload = get_icp_config()
            return {"id": None, "version": 0, "label": "yaml_default", "payload": payload}
        except Exception:
            return {"id": None, "version": 0, "label": "empty", "payload": {}}

    def create_version(self, payload: dict, label: str = "", activate: bool = False) -> str:
        """Create a new ICP version. Returns the new version UUID.

        Args:
            payload: Full ICP definition dict (same structure as icp.yaml).
            label: Human-readable label (e.g., "Q2 tight — food & bev only").
            activate: If True, immediately activate this version (deactivates current).
        """
        try:
            # Get next version number for this workspace
            workspace_id = getattr(self._db, "workspace_id", None)
            existing = (
                self._db.client.table("icp_definitions")
                .select("version")
                .order("version", desc=True)
                .limit(1)
                .execute()
                .data or []
            )
            next_version = (existing[0]["version"] + 1) if existing else 1

            row = {
                "version": next_version,
                "label": label,
                "payload": payload,
                "is_active": False,
            }
            if workspace_id:
                row["workspace_id"] = workspace_id

            result = self._db.client.table("icp_definitions").insert(row).execute()
            new_id = result.data[0]["id"]

            if activate:
                self.activate(new_id)

            logger.info("Created ICP version %s (id=%s, activate=%s)", next_version, new_id, activate)
            return new_id
        except Exception as e:
            logger.error("Failed to create ICP version: %s", e)
            raise

    def activate(self, version_id: str) -> None:
        """Activate a specific ICP version and deactivate all others."""
        try:
            workspace_id = getattr(self._db, "workspace_id", None)
            # Deactivate current
            q = self._db.client.table("icp_definitions").update({"is_active": False})
            if workspace_id:
                q = q.eq("workspace_id", workspace_id)
            q.execute()
            # Activate target
            from datetime import datetime, timezone
            self._db.client.table("icp_definitions").update({
                "is_active": True,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", version_id).execute()
            logger.info("Activated ICP version %s", version_id)
        except Exception as e:
            logger.error("Failed to activate ICP version %s: %s", version_id, e)
            raise

    def is_company_excluded(self, company_id: str) -> tuple[bool, str | None]:
        """Check if a company is in the ICP exclusions list.

        Returns (is_excluded, reason).
        """
        try:
            workspace_id = getattr(self._db, "workspace_id", None)
            q = (
                self._db.client.table("icp_exclusions")
                .select("reason,detail")
                .eq("company_id", company_id)
                .limit(1)
            )
            if workspace_id:
                q = q.eq("workspace_id", workspace_id)
            rows = q.execute().data or []
            if rows:
                r = rows[0]
                return True, r.get("reason") or r.get("detail") or "excluded"
            return False, None
        except Exception as e:
            logger.warning("Could not check ICP exclusion for %s: %s", company_id, e)
            return False, None

    def exclude_company(self, company_id: str, reason: str, detail: str = "",
                        excluded_by: str = "system") -> None:
        """Add a company to the ICP exclusions list."""
        try:
            workspace_id = getattr(self._db, "workspace_id", None)
            row: dict = {
                "company_id": company_id,
                "reason": reason,
                "detail": detail,
                "excluded_by": excluded_by,
            }
            if workspace_id:
                row["workspace_id"] = workspace_id
            self._db.client.table("icp_exclusions").upsert(row, on_conflict="workspace_id,company_id").execute()
            logger.info("Excluded company %s from ICP (reason=%s)", company_id, reason)
        except Exception as e:
            logger.error("Failed to exclude company %s: %s", company_id, e)
