"""Honesty-pass regression guards for the targeting endpoint.

The four strategies WARM_LEADS, DECISION_MAKERS, MEETING_READY, DEAL_FOCUSED
have no real query — they must report status='not_implemented' and return zero
prospects, never the old undifferentiated 'pqs_total >= 50' list.
"""

from __future__ import annotations

import pytest

from backend.app.api.routes.targeting import (
    TargetingStrategy,
    _NOT_IMPLEMENTED_STRATEGIES,
    _calculate_icp_fit_score,
)


def test_four_strategies_are_marked_not_implemented():
    assert _NOT_IMPLEMENTED_STRATEGIES == frozenset(
        {
            TargetingStrategy.WARM_LEADS,
            TargetingStrategy.DECISION_MAKERS,
            TargetingStrategy.MEETING_READY,
            TargetingStrategy.DEAL_FOCUSED,
        }
    )


def test_implemented_strategies_not_flagged():
    for s in (
        TargetingStrategy.HIGH_PQS,
        TargetingStrategy.QUICK_WINS,
        TargetingStrategy.RECENT_ACTIVITY,
    ):
        assert s not in _NOT_IMPLEMENTED_STRATEGIES


def test_icp_fit_score_is_heuristic_clamped_0_100():
    # No deal, no meeting, pqs=100 → 40 points
    assert _calculate_icp_fit_score({"pqs_total": 100}, None, None) == 40.0
    # pqs=0, won deal (100*0.5=50), meeting (+15) → 65
    assert _calculate_icp_fit_score({"pqs_total": 0}, {"stage": "won"}, True) == 65.0
    # Clamp: pqs=100 (40) + won (50) + meeting (15) = 105 → clamped to 100
    assert _calculate_icp_fit_score({"pqs_total": 100}, {"stage": "won"}, True) == 100.0


def test_conversion_probability_name_is_gone():
    """The misleading 'conversion_probability' name must not reappear."""
    import backend.app.api.routes.targeting as mod

    src = open(mod.__file__).read()
    assert "conversion_probability" not in src
    assert "icp_fit_score" in src
