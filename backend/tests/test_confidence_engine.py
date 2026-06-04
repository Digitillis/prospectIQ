"""Tests for backend.app.core.confidence_engine helpers.

Covers the signal evidence policy helpers used by the intent engine when
summing signal scores: classify_evidence_url() (URL → evidence type) and
apply_evidence_cap() (cap unevidenced signals above the threshold).
"""

from __future__ import annotations

import pytest

from backend.app.core.confidence_engine import (
    apply_evidence_cap,
    classify_evidence_url,
)


# ---------------------------------------------------------------------------
# classify_evidence_url
# ---------------------------------------------------------------------------


def test_classify_sec_url() -> None:
    assert classify_evidence_url("https://www.sec.gov/cgi-bin/browse-edgar") == "sec_filing"


def test_classify_job_posting_url() -> None:
    assert classify_evidence_url("https://company.greenhouse.io/jobs/123") == "job_posting"


def test_classify_press_release_url() -> None:
    assert classify_evidence_url("https://www.prnewswire.com/news/abc") == "press_release"


def test_classify_unknown_url_returns_none() -> None:
    assert classify_evidence_url("https://example.com") is None


def test_classify_none_url_returns_none() -> None:
    assert classify_evidence_url(None) is None


def test_classify_empty_url_returns_none() -> None:
    assert classify_evidence_url("") is None


# ---------------------------------------------------------------------------
# apply_evidence_cap
# ---------------------------------------------------------------------------


def test_apply_evidence_cap_with_evidence_passes_through() -> None:
    """Score above threshold WITH evidence — should not be capped."""
    result = apply_evidence_cap(0.80, evidence_url="https://sec.gov/filing/abc")
    assert result == pytest.approx(0.80, abs=0.01)


def test_apply_evidence_cap_without_evidence_is_capped() -> None:
    """Score above threshold WITHOUT evidence — should be capped at unevidenced_cap."""
    result = apply_evidence_cap(0.80, evidence_url=None)
    assert result <= 0.30 + 0.01  # default unevidenced_cap


def test_apply_evidence_cap_below_threshold_passes_through() -> None:
    """Score below required_above_score — cap doesn't apply regardless of evidence."""
    result = apply_evidence_cap(0.40, evidence_url=None)
    assert result == pytest.approx(0.40, abs=0.01)


def test_apply_evidence_cap_at_threshold_passes_through() -> None:
    """Score at the required_above_score boundary — left alone (cap is strict >)."""
    # Default required_above_score is 0.50; >0.50 is required for capping.
    result = apply_evidence_cap(0.50, evidence_url=None)
    assert result == pytest.approx(0.50, abs=0.01)


def test_apply_evidence_cap_unrecognised_url_treated_as_unevidenced() -> None:
    """A URL that doesn't match any evidence type is unevidenced — caps apply."""
    result = apply_evidence_cap(0.90, evidence_url="https://example.com/random")
    assert result <= 0.30 + 0.01


def test_apply_evidence_cap_explicit_evidence_type_overrides_url() -> None:
    """Caller-supplied evidence_type takes precedence over URL classification."""
    # No URL but explicit acceptable type — should not be capped.
    result = apply_evidence_cap(
        0.80,
        evidence_url="https://sec.gov/filing/abc",
        evidence_type="sec_filing",
    )
    assert result == pytest.approx(0.80, abs=0.01)
