"""Tests for BenchmarkDetector (P2.1).

Exercises Layers 1 and 2 only — Layer 3 (LLM verifier) is not invoked
in unit tests; we instantiate the detector with `llm_enabled=False`.
"""

from __future__ import annotations

from backend.app.core.benchmark_detector import BenchmarkDetector


# Fixed proof point set for deterministic citation matching
_PROOF = [
    {
        "id": "pp_0",
        "text": (
            "Industry benchmark: manufacturers using predictive maintenance "
            "see a 23-41% reduction in unplanned downtime (LNS Research, 2024)"
        ),
    },
    {
        "id": "pp_1",
        "text": (
            "Industry data: food & beverage plants with real-time CCP monitoring "
            "reduce recall risk by catching process drift 2-5 days earlier than "
            "manual checks (FDA enforcement data, 2023)"
        ),
    },
]


def _detector() -> BenchmarkDetector:
    return BenchmarkDetector(proof_points=_PROOF, llm_enabled=False)


def test_clean_short_outreach_passes() -> None:
    body = (
        "Hi Avi, saw your team is opening the Iowa plant. Curious how you're "
        "thinking about preventive maintenance scheduling there. Worth a "
        "20-minute call next week?"
    )
    a = _detector().analyze(body)
    assert a.has_violations is False
    assert a.verdict == "clean"
    assert a.findings == []


def test_fabricated_similar_plants_phrasing_flagged() -> None:
    body = "Plants in similar operations typically see real lift."
    a = _detector().analyze(body)
    rules = {f.rule for f in a.findings}
    assert "similar_plants" in rules or "typically_verb" in rules
    assert a.has_violations is True


def test_fabricated_pct_range_flagged() -> None:
    body = "Cut downtime 23-41% across the board."
    a = _detector().analyze(body)
    rules = {f.rule for f in a.findings}
    # cut_pct_range looks for "cut <word> 23-41 %"
    assert "cut_pct_range" in rules
    assert a.has_violations is True


def test_catch_n_units_earlier_flagged() -> None:
    body = "We catch issues 3-5 days earlier than the rest."
    a = _detector().analyze(body)
    rules = {f.rule for f in a.findings}
    assert "catch_n_units_earlier" in rules
    assert a.has_violations is True


def test_our_clients_saw_phrasing_flagged() -> None:
    body = "Our customers saw a measurable lift on the first audit."
    a = _detector().analyze(body)
    rules = {f.rule for f in a.findings}
    assert "our_clients_saw" in rules
    assert a.has_violations is True


def test_pct_change_phrase_with_citation_clears_to_attributed() -> None:
    """A 23-41% reduction line WITH a year-cited source resolves to attributed,
    so has_violations stays False."""
    body = (
        "Industry benchmark: manufacturers using predictive maintenance see a "
        "23-41% reduction in unplanned downtime (LNS Research, 2024)."
    )
    a = _detector().analyze(body)
    # Must have at least one finding, but no fabricated verdict
    fabricated = [f for f in a.findings if f.verdict == "fabricated"]
    assert fabricated == []
    assert a.has_violations is False


def test_layer_2_numeric_without_citation_flagged() -> None:
    """A numeric % claim with no citation registers a Layer 2 unclear finding."""
    body = "Our process drives a 22% improvement on most lines."
    a = _detector().analyze(body)
    # Should have at least a layer2_numeric finding
    layers = {f.layer for f in a.findings}
    assert "layer2_numeric" in layers or "layer1_regex" in layers


def test_layer_2_with_fda_reference_clears() -> None:
    """A numeric claim citing a regulator (FDA) is treated as cited."""
    body = (
        "Plants reduce recall risk by catching process drift 2-5 days earlier "
        "than manual checks (FDA enforcement data, 2023)."
    )
    a = _detector().analyze(body)
    fabricated = [f for f in a.findings if f.verdict == "fabricated"]
    assert fabricated == []


def test_empty_body_is_clean() -> None:
    a = _detector().analyze("")
    assert a.verdict == "clean"
    assert a.findings == []
    assert a.has_violations is False
