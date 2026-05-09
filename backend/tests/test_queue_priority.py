"""Tests for backend.app.core.queue_manager.compute_priority_score().

The send queue ranks contacts by priority_score so the pace limiter ships
the highest-value targets first each day. These tests pin the relative
ordering between persona types, between companies with/without signals,
and the [0, 100] clamp.
"""

from __future__ import annotations

from backend.app.core.queue_manager import compute_priority_score


# Baseline contact dict — kept minimal so tests isolate the variable
# under test. Completeness is zero and last_contacted_at is recent so
# persona and signal deltas move the score visibly without saturating
# the 0-100 clamp (live ICP weights make persona points alone hit 100).
def _contact(**overrides) -> dict:
    base = {
        "completeness_score": 0,
        "persona_type": None,
        "open_count": 0,
        "click_count": 0,
        "last_contacted_at": "2026-05-07T00:00:00+00:00",  # recent — applies -10 penalty
        "updated_at": None,
    }
    base.update(overrides)
    return base


def _company(**overrides) -> dict:
    base = {
        "tier": "unknown_tier",  # default tier points (3) — keeps headroom
        "intent_score": 0,
        "active_signals": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Persona ordering
# ---------------------------------------------------------------------------

def test_vp_ops_scores_higher_than_plant_manager() -> None:
    """vp_ops carries more persona points than plant_manager."""
    company = _company()
    vp = _contact(persona_type="vp_ops")
    pm = _contact(persona_type="plant_manager")

    assert compute_priority_score(vp, company) > compute_priority_score(pm, company)


def test_known_persona_scores_higher_than_unknown_persona() -> None:
    """An unmapped persona falls back to the default; vp_ops dominates it."""
    company = _company()
    vp = _contact(persona_type="vp_ops")
    unknown = _contact(persona_type="random_role")

    assert compute_priority_score(vp, company) > compute_priority_score(unknown, company)


# ---------------------------------------------------------------------------
# Signal-driven intent boost
# ---------------------------------------------------------------------------

def test_company_with_no_signals_scores_lower_than_with_fda_signals() -> None:
    """Intent score from active signals is added (capped at 15)."""
    contact = _contact(persona_type="vp_ops")

    no_signals = _company(intent_score=0, active_signals=[])
    fda_signals = _company(
        intent_score=12,
        active_signals=[{"signal_type": "fda_warning_letter"}],
    )

    assert compute_priority_score(contact, fda_signals) > compute_priority_score(
        contact, no_signals
    )


def test_fb_company_with_fsma_signal_outscores_same_company_without() -> None:
    """F&B tiers get a 1.5x multiplier when an FSMA-class signal is present."""
    contact = _contact(persona_type="vp_quality_food_safety")

    fb_no_fsma = _company(tier="fb_dairy", intent_score=8, active_signals=[])
    fb_with_fsma = _company(
        tier="fb_dairy",
        intent_score=8,
        active_signals=[{"signal_type": "fda_warning_letter_fsma"}],
    )

    assert compute_priority_score(contact, fb_with_fsma) > compute_priority_score(
        contact, fb_no_fsma
    )


# ---------------------------------------------------------------------------
# Score range
# ---------------------------------------------------------------------------

def test_score_clamped_to_zero_minimum() -> None:
    """Negative components (heavy recency penalty) cannot push score below 0."""
    contact = _contact(
        completeness_score=0,
        persona_type=None,
        last_contacted_at="2099-01-01T00:00:00+00:00",  # future date — large penalty
    )
    company = _company(tier="unknown_tier")
    score = compute_priority_score(contact, company)
    assert 0 <= score <= 100


def test_score_clamped_to_one_hundred_maximum() -> None:
    """Maxed-out positive components must not exceed 100."""
    contact = _contact(
        completeness_score=100,
        persona_type="vp_ops",
        click_count=5,  # +20 engagement
    )
    company = _company(tier="mfg1", intent_score=99)
    score = compute_priority_score(contact, company)
    assert 0 <= score <= 100


def test_baseline_score_within_range() -> None:
    """A typical contact stays inside [0, 100]."""
    contact = _contact(persona_type="vp_ops")
    company = _company()
    score = compute_priority_score(contact, company)
    assert 0 <= score <= 100
