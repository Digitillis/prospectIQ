"""fabricated_anecdote's "(one|a|an) + noun + verb" rule must require a real
verb suffix, not match any word.

The trailing (ed|ing|s)? quantifier was optional, so \\w+ alone already
satisfied it regardless of what followed the noun -- the rule matched any
"(a/an/one) + [0-3 words] + noun-from-list + any word" sentence, not just
genuine third-party-anecdote claims. Confirmed false-positiving on real,
non-fabricated content across a live draft batch, 2026-08-17/18:
"a facility that size", "a customer complaint", "a customer scorecard flags".

See backend/app/agents/outreach.py's _INTEGRITY_RULES for the corrected
pattern and full rationale for excluding the "s" suffix.
"""

from __future__ import annotations

from backend.app.agents.outreach import _check_draft_integrity

_STEP2_NOTES = "internal notes, no url needed for this test"


def _has_fabricated_anecdote(body: str) -> bool:
    violations = _check_draft_integrity(
        body,
        subject="Test subject",
        personalization_notes=_STEP2_NOTES,
        sequence_step=2,
        require_hook_source=False,
    )
    return any(v.startswith("fabricated_anecdote:") for v in violations)


def test_ordinary_noun_phrase_a_facility_that_size_does_not_trigger():
    body = "Bringing new converting equipment into a facility that size is exactly when unplanned downtime patterns get set for years."
    assert not _has_fabricated_anecdote(body)


def test_ordinary_noun_phrase_a_customer_complaint_does_not_trigger():
    body = "That's usually where quality drift shows up first, not in QA testing, but in a customer complaint from a private label account weeks later."
    assert not _has_fabricated_anecdote(body)


def test_ordinary_noun_phrase_a_customer_scorecard_does_not_trigger():
    body = "When one line underperforms, it's often invisible until a customer scorecard flags it, and by then the OEM has already seen it before your team did."
    assert not _has_fabricated_anecdote(body)


def test_genuine_anecdote_past_tense_still_triggers():
    body = "One aerospace shop identified the exact failure mode a week before it happened."
    assert _has_fabricated_anecdote(body)


def test_genuine_anecdote_gerund_still_triggers():
    body = "A process manufacturer using this exact approach caught the drift early."
    assert _has_fabricated_anecdote(body)
