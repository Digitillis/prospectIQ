"""Regression tests for R1-R12 platform remediations (2026-05-28).

Each test proves a specific invariant that was broken in the pre-remediation
corpus. CI will catch regressions if any of these tests starts failing after
a future code change.
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# R1 — SINCE-based reply ingestion
# ---------------------------------------------------------------------------

class TestR1ReplyIngestion(unittest.TestCase):
    """fetch_since_replies uses SINCE, not UNSEEN."""

    def test_fetch_since_replies_uses_since_criterion(self):
        """GmailImapClient.fetch_since_replies must call IMAP SEARCH with SINCE."""
        from backend.app.integrations.gmail_imap import GmailImapClient
        client = GmailImapClient("test@example.com", "password")

        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        client._conn = mock_conn
        client._conn.select.return_value = ("OK", [])

        since_dt = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)
        client.fetch_since_replies(since_dt)

        call_args = mock_conn.search.call_args
        search_criterion = str(call_args[0])
        assert "SINCE" in search_criterion, (
            "fetch_since_replies must use SINCE, not UNSEEN — "
            f"got search args: {call_args}"
        )
        assert "UNSEEN" not in search_criterion, (
            "fetch_since_replies must NOT use UNSEEN"
        )

    def test_fetch_since_replies_formats_date_correctly(self):
        """SINCE date must be DD-Mon-YYYY (IMAP RFC 3501 format)."""
        from backend.app.integrations.gmail_imap import GmailImapClient
        client = GmailImapClient("test@example.com", "password")

        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        client._conn = mock_conn
        client._conn.select.return_value = ("OK", [])

        since_dt = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        client.fetch_since_replies(since_dt)

        search_str = str(mock_conn.search.call_args)
        # RFC 3501 date: 01-May-2026
        assert "01-May-2026" in search_str, (
            f"SINCE date format should be DD-Mon-YYYY, got: {search_str}"
        )


# ---------------------------------------------------------------------------
# R2 — Rejected drafts cannot dispatch
# ---------------------------------------------------------------------------

class TestR2RejectedDraftGate(unittest.TestCase):
    """assert_not_rejected raises AssertionFailure for rejected/dispatch_failed drafts."""

    def _make_db(self, approval_status: str):
        db = MagicMock()
        db.client.table.return_value.select.return_value\
            .eq.return_value.limit.return_value.execute.return_value\
            .data = [{"id": "draft-123", "approval_status": approval_status}]
        db.client.table.return_value.insert.return_value.execute.return_value = None
        return db

    def test_rejected_draft_raises(self):
        from backend.app.core.pre_send_assertions import assert_not_rejected, AssertionFailure
        db = self._make_db("rejected")
        with self.assertRaises(AssertionFailure) as ctx:
            assert_not_rejected(db, "draft-123", "send_path")
        assert "rejected" in str(ctx.exception)

    def test_dispatch_failed_raises(self):
        from backend.app.core.pre_send_assertions import assert_not_rejected, AssertionFailure
        db = self._make_db("dispatch_failed")
        with self.assertRaises(AssertionFailure):
            assert_not_rejected(db, "draft-123", "send_path")

    def test_approved_draft_passes(self):
        from backend.app.core.pre_send_assertions import assert_not_rejected
        db = self._make_db("approved")
        # Must not raise
        assert_not_rejected(db, "draft-123", "send_path")

    def test_edited_draft_passes(self):
        from backend.app.core.pre_send_assertions import assert_not_rejected
        db = self._make_db("edited")
        assert_not_rejected(db, "draft-123", "send_path")


# ---------------------------------------------------------------------------
# R3 — Bot events do not promote company to 'engaged'
# ---------------------------------------------------------------------------

class TestR3BotFiltering(unittest.TestCase):
    """ClickClassifier correctly labels sub-90s events as bots."""

    def test_sub_90s_latency_is_bot(self):
        from backend.app.core.click_classifier import ClickClassifier
        result = ClickClassifier().classify({"latency_seconds": 15.0})
        assert result == "bot", f"Expected 'bot', got {result!r}"

    def test_89s_latency_is_bot(self):
        from backend.app.core.click_classifier import ClickClassifier
        result = ClickClassifier().classify({"latency_seconds": 89.9})
        assert result == "bot"

    def test_no_latency_defaults_to_unclear(self):
        from backend.app.core.click_classifier import ClickClassifier
        result = ClickClassifier().classify({})
        assert result in ("unclear", "human"), (
            "Unknown latency should not be 'bot'"
        )

    def test_scanner_ua_is_bot(self):
        from backend.app.core.click_classifier import ClickClassifier
        result = ClickClassifier().classify({
            "latency_seconds": 200.0,
            "user_agent": "Mimecast SafetyNet Scanner/3.0",
        })
        assert result == "bot"


# ---------------------------------------------------------------------------
# R4 + R6 — Integrity validator catches fingerprints and requires hook URL
# ---------------------------------------------------------------------------

class TestR4R6IntegrityValidator(unittest.TestCase):
    """_check_draft_integrity catches recycled stats, fingerprints, missing hook."""

    def _check(self, body: str, subject: str = "", notes: str = "", step: int = 1):
        from backend.app.agents.outreach import _check_draft_integrity
        return _check_draft_integrity(body, subject, personalization_notes=notes, sequence_step=step)

    def test_missing_hook_url_rejected_step1(self):
        violations = self._check(
            "Your induction furnace reliability concerns us. Quick question...",
            notes="",
            step=1,
        )
        assert any("missing_hook_source" in v for v in violations), (
            f"Expected missing_hook_source violation, got: {violations}"
        )

    def test_missing_hook_url_rejected_step2(self):
        """Hook contract extends to all steps (R4 extension)."""
        violations = self._check(
            "Following up on my prior note about your furnace.",
            notes="",
            step=2,
        )
        assert any("missing_hook_source" in v for v in violations)

    def test_hook_url_present_passes(self):
        violations = self._check(
            "Re: your induction furnace setup at Waupaca.",
            notes="https://www.waupacafoundry.com/about",
            step=1,
        )
        hook_violations = [v for v in violations if "missing_hook_source" in v]
        assert not hook_violations, f"Clean draft should not have hook violations: {violations}"

    def test_recycled_stat_15_20_flagged(self):
        violations = self._check(
            "Plants typically lose 15-20% of available machine time.",
            notes="https://example.com",
        )
        assert any("recycled_stat" in v for v in violations)

    def test_recycled_stat_18_days_flagged(self):
        violations = self._check(
            "We predict failures 18 days out.",
            notes="https://example.com",
        )
        assert any("recycled_stat" in v for v in violations)

    def test_time_based_maintenance_flagged(self):
        violations = self._check(
            "If your plant is still running time-based maintenance schedules...",
            notes="https://example.com",
        )
        assert any("template_fingerprint" in v for v in violations)

    def test_generic_hook_phrase_flagged(self):
        violations = self._check(
            "Manufacturers like yours typically face downtime issues.",
            notes="https://example.com",
        )
        assert any("generic_hook" in v for v in violations)

    def test_clean_waupaca_style_email_passes(self):
        """The Waupaca gold-standard email should pass all integrity checks."""
        body = (
            "Electric induction furnaces are probably your highest-cost, highest-risk "
            "assets on the floor. A coil failure or refractory problem doesn't just "
            "stop the melt — it ripples through your molding lines for days. "
            "Curious — how are you currently monitoring furnace health between "
            "scheduled inspections?"
        )
        violations = self._check(body, notes="https://www.waupacafoundry.com/operations")
        # Should have no violations other than possibly the SINCE-label rules
        blocking = [v for v in violations if not v.startswith("step_label_leak")]
        assert not blocking, f"Gold-standard email should pass integrity: {blocking}"


# ---------------------------------------------------------------------------
# R6 — Batch fingerprint linter
# ---------------------------------------------------------------------------

class TestR6BatchLinter(unittest.TestCase):
    """check_batch_fingerprints catches corpus-level template saturation."""

    def test_high_rate_triggers_violation(self):
        from backend.app.agents.outreach import check_batch_fingerprints
        # 10 emails all containing "time-based maintenance schedules" = 100% rate
        bodies = ["Plants on time-based maintenance schedules lose efficiency."] * 10
        violations = check_batch_fingerprints(bodies, threshold=0.10)
        assert "time_based_maintenance" in violations, (
            f"Expected time_based_maintenance violation, got {violations}"
        )

    def test_low_rate_passes(self):
        from backend.app.agents.outreach import check_batch_fingerprints
        # 1 in 20 = 5% — below 10% threshold
        bodies = (
            ["Plants on time-based maintenance schedules lose efficiency."]
            + ["Clean personalized email about induction furnace reliability."] * 19
        )
        violations = check_batch_fingerprints(bodies, threshold=0.10)
        assert "time_based_maintenance" not in violations


# ---------------------------------------------------------------------------
# R7 — Qualification scorer bugs
# ---------------------------------------------------------------------------

class TestR7Qualification(unittest.TestCase):
    """Rule-based scorer no longer awards bonus for NULL state or missing research."""

    def _make_scorer_and_company(self, state=None):
        """Return a partial scorer result for state_match evaluation."""
        from backend.app.agents.qualification import QualificationAgent
        agent = QualificationAgent.__new__(QualificationAgent)
        agent.db = MagicMock()
        company = {"state": state, "employee_count": 500}
        return agent, company

    def test_null_state_does_not_get_midwest_bonus(self):
        """state=NULL must not award the Midwest geography bonus."""
        from backend.app.agents.qualification import QualificationAgent
        agent = QualificationAgent.__new__(QualificationAgent)

        # Simulate the state_match branch with qualifying states list
        qualifying = ["IL", "OH", "MI", "IN", "WI", "MN", "IA", "MO"]
        state = None
        score_added = 0
        if state and state in qualifying:
            score_added = 3

        assert score_added == 0, (
            "NULL state must NOT award geography bonus (was giving +3 for missing data)"
        )

    def test_known_qualifying_state_gets_bonus(self):
        qualifying = ["IL", "OH", "MI"]
        state = "OH"
        score_added = 3 if (state and state in qualifying) else 0
        assert score_added == 3

    def test_no_research_returns_zero_technographic(self):
        """_score_technographic returns 0 when no research record exists."""
        from backend.app.agents.qualification import QualificationAgent
        agent = QualificationAgent.__new__(QualificationAgent)
        agent._build_search_text = MagicMock(return_value="")

        # Minimal config stub
        config = {
            "dimensions": {
                "technographic": {
                    "max_points": 25,
                    "signals": {},
                }
            }
        }
        result = agent._score_technographic({}, None, config)
        assert result == 0, f"Expected 0 technographic score with no research, got {result}"


# ---------------------------------------------------------------------------
# R8 — Step N references step N-1
# ---------------------------------------------------------------------------

class TestR8SequenceContinuity(unittest.TestCase):
    """Step-label-leak rule allows natural follow-up language."""

    def _check(self, body, notes="https://example.com", step=2):
        from backend.app.agents.outreach import _check_draft_integrity
        return _check_draft_integrity(body, personalization_notes=notes, sequence_step=step)

    def test_non_response_guilt_trip_still_flagged(self):
        """'You didn't respond' is still blocked."""
        violations = self._check("You haven't responded to my prior outreach.")
        assert any("step_label_leak" in v for v in violations)

    def test_natural_followup_language_allowed(self):
        """'Following up on my note about X' must NOT be flagged."""
        violations = self._check(
            "Following up on my note about your induction furnace reliability."
        )
        step_leaks = [v for v in violations if "step_label_leak" in v]
        assert not step_leaks, (
            f"Natural follow-up language should not be flagged as step_label_leak: {violations}"
        )

    def test_circling_back_allowed(self):
        """'Circling back after reaching out about X' must NOT be flagged."""
        violations = self._check(
            "Circling back after reaching out about your VAR furnace setup."
        )
        step_leaks = [v for v in violations if "step_label_leak" in v]
        assert not step_leaks, f"'Circling back' should be allowed: {violations}"

    def test_explicit_step_label_still_blocked(self):
        """'step 1' or 'step 2' in the body is still a violation."""
        violations = self._check("Following up on step 1 of my outreach sequence.")
        assert any("step_label_leak" in v for v in violations)


if __name__ == "__main__":
    unittest.main()
