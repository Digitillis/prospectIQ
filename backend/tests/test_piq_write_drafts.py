"""Tests for scripts/piq_write_drafts.py — the single, tracked writer for
Claude Code workflow-generated outreach drafts.

Regression coverage for two findings from the 2026-08-15 subscription-
migration work:

  - Finding 10 (silent draft-discard): the untracked writer this script
    replaces set `model="opus-via-claude-code"` correctly, but
    generate-outreach-emails.js's separate, prose-driven write path did
    not — its field list never mentioned `model`, so its drafts had
    model=NULL and were silently filtered out of the send schedule by
    send_scheduler.py's `if d.get("model")` check. Routing both workflows
    through this one script makes that structurally impossible: `model`
    is set in code (test_build_row_always_sets_model_provenance), not
    left to an agent's discretion each run.
  - Finding 11 (untracked writer): this script is the tracked replacement
    for /Users/avanish/prospectIQ/.pipeline-queues/piq_write_drafts.py,
    which existed only on one local machine, in no repository.

Also covers finding 12 (quality gates bypassed on the Claude Code write
path): this script now runs the same _check_draft_integrity /
is_step_1_url_violation checks OutreachAgent applies to its own
API-generated drafts, and routes inserts through
Database.insert_outreach_draft() (the previous untracked script called
.table().insert() directly, bypassing insert_outreach_draft()'s dedup
guards).

scripts/ has no __init__.py and is not reliably importable as a package
in this repo's test environment (confirmed: even a script that DOES
exist, scripts/warm_reply_reconcile.py, fails an `import
scripts.warm_reply_reconcile` — a pre-existing, unrelated issue). These
tests load the module by file path instead.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "piq_write_drafts.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("piq_write_drafts_under_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["piq_write_drafts_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def m():
    return _load_module()


WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


class TestBuildRow:
    def test_always_sets_model_provenance(self, m):
        """The core regression check: model must be set unconditionally,
        not something the caller can omit.
        """
        row = m._build_row(
            {
                "company_id": "c1",
                "contact_id": "ct1",
                "sequence_step": 2,
                "subject": "Following up",
                "body": "...",
            },
            WORKSPACE_ID,
        )
        assert row["model"] == "opus-via-claude-code"

    def test_maps_all_required_columns(self, m):
        row = m._build_row(
            {
                "company_id": "c1",
                "contact_id": "ct1",
                "sequence_step": "3",
                "subject": "Re: your plant",
                "body": "body text",
                "personalization_notes": "https://example.com/press-release",
            },
            WORKSPACE_ID,
        )
        assert row["company_id"] == "c1"
        assert row["contact_id"] == "ct1"
        assert row["sequence_step"] == 3  # coerced to int
        assert row["subject"] == "Re: your plant"
        assert row["body"] == "body text"
        assert row["personalization_notes"] == "https://example.com/press-release"
        assert row["approval_status"] == "pending"
        assert row["sequence_name"] == "email_value_first"
        assert row["channel"] == "email"
        assert row["workspace_id"] == WORKSPACE_ID


class TestMainQualityGating:
    def _run_main(self, m, tmp_path, drafts, monkeypatch):
        inserted = []
        db = MagicMock()
        db.workspace_id = WORKSPACE_ID

        def _fake_insert(row):
            inserted.append(row)
            return {"id": f"draft-{len(inserted)}", **row}

        db.insert_outreach_draft.side_effect = _fake_insert
        monkeypatch.setattr(m, "Database", MagicMock(return_value=db))
        monkeypatch.setattr(
            m, "get_settings", MagicMock(return_value=MagicMock(default_workspace_id=WORKSPACE_ID))
        )

        draft_file = tmp_path / "drafts.json"
        draft_file.write_text(json.dumps(drafts))

        m.main(str(draft_file))
        return inserted

    def test_clean_draft_inserted_as_pending(self, m, tmp_path, monkeypatch, capsys):
        drafts = [
            {
                "company_id": "c1",
                "contact_id": "ct1",
                "sequence_step": 2,
                "subject": "Following up on your line 3 downtime",
                "body": (
                    "Hi Jane, following up on my last note about your line 3 "
                    "downtime. Worth a quick call this week?"
                ),
                "personalization_notes": "https://example.com/press-release — plant expansion",
            }
        ]
        inserted = self._run_main(m, tmp_path, drafts, monkeypatch)

        assert len(inserted) == 1
        assert inserted[0]["approval_status"] == "pending"
        assert "rejection_reason" not in inserted[0]

        out = json.loads(capsys.readouterr().out)
        assert out["written"] == 1
        assert out["rejected"] == 0
        assert out["failed"] == 0

    def test_step_1_url_violation_inserted_as_rejected_not_dropped(
        self, m, tmp_path, monkeypatch, capsys
    ):
        """Findings-12 regression: a bad draft must still be visible and
        auditable (inserted as rejected), not silently skipped — matching
        OutreachAgent's own auto-reject convention.
        """
        drafts = [
            {
                "company_id": "c1",
                "contact_id": "ct1",
                "sequence_step": 1,
                "subject": "Quick question",
                "body": "Check this out: https://example.com/demo — worth 10 minutes?",
                "personalization_notes": "https://example.com/press-release",
            }
        ]
        inserted = self._run_main(m, tmp_path, drafts, monkeypatch)

        assert len(inserted) == 1
        assert inserted[0]["approval_status"] == "rejected"
        assert "step1_url_violation" in inserted[0]["rejection_reason"]

        out = json.loads(capsys.readouterr().out)
        assert out["written"] == 0
        assert out["rejected"] == 1

    def test_missing_hook_source_inserted_as_rejected(self, m, tmp_path, monkeypatch, capsys):
        drafts = [
            {
                "company_id": "c1",
                "contact_id": "ct1",
                "sequence_step": 2,
                "subject": "Following up",
                "body": "Hi Jane, wanted to follow up on my last note. Worth a call?",
                "personalization_notes": "",  # no source URL
            }
        ]
        inserted = self._run_main(m, tmp_path, drafts, monkeypatch)

        assert inserted[0]["approval_status"] == "rejected"
        assert "missing_hook_source" in inserted[0]["rejection_reason"]

    def test_insert_exception_counted_as_failed_not_raised(self, m, tmp_path, monkeypatch, capsys):
        db = MagicMock()
        db.workspace_id = WORKSPACE_ID
        db.insert_outreach_draft.side_effect = RuntimeError("db down")
        monkeypatch.setattr(m, "Database", MagicMock(return_value=db))
        monkeypatch.setattr(
            m, "get_settings", MagicMock(return_value=MagicMock(default_workspace_id=WORKSPACE_ID))
        )

        draft_file = tmp_path / "drafts.json"
        draft_file.write_text(
            json.dumps(
                [
                    {
                        "company_id": "c1",
                        "contact_id": "ct1",
                        "sequence_step": 2,
                        "subject": "s",
                        "body": "b",
                        "personalization_notes": "https://example.com/x",
                    }
                ]
            )
        )

        m.main(str(draft_file))  # must not raise

        out = json.loads(capsys.readouterr().out)
        assert out["failed"] == 1
        assert out["written"] == 0
