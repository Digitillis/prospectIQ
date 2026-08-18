"""unsourced_company_event's "since you (recently|just) [verb]ed" rule must
require the real "-ed" past-tense ending, not match any word ending in "d".

(ed|d) is functionally equivalent to "any word ending in the letter d" --
every "-ed" word already ends in "d", so the "d" alternative alone matched
everything "ed" would and far more: "since you recently expand", "since
you just rebrand", "since you recently attend" all matched despite none
of those words being past tense. Found during independent review of a
related fix to a different _INTEGRITY_RULES pattern with the same shape
(fabricated_anecdote's optional-suffix bug) -- confirmed by direct testing
against the live regex, not part of the original three bugs from the live
dispatch test, but the same defect class in the same rule list.
"""

from __future__ import annotations

from backend.app.agents.outreach import _check_draft_integrity

_STEP2_NOTES = "internal notes, no url needed for this test"


def _has_unsourced_company_event(body: str) -> bool:
    violations = _check_draft_integrity(
        body,
        subject="Test subject",
        personalization_notes=_STEP2_NOTES,
        sequence_step=2,
        require_hook_source=False,
    )
    return any(v.startswith("unsourced_company_event:") for v in violations)


def test_present_tense_expand_does_not_trigger():
    body = "Since you recently expand into new markets, keeping quality consistent across lines gets harder."
    assert not _has_unsourced_company_event(body)


def test_present_tense_rebrand_does_not_trigger():
    body = "Since you just rebrand the product line, customer questions about the change are probably still coming in."
    assert not _has_unsourced_company_event(body)


def test_present_tense_attend_does_not_trigger():
    body = "Since you recently attend more industry conferences, your team's visibility into new tooling has probably grown."
    assert not _has_unsourced_company_event(body)


def test_genuine_past_tense_acquired_still_triggers():
    body = "Since you recently acquired the new facility, integration is probably keeping your ops team busy."
    assert _has_unsourced_company_event(body)


def test_genuine_past_tense_launched_still_triggers():
    body = (
        "Since you just launched the new product line, quality consistency is probably top of mind."
    )
    assert _has_unsourced_company_event(body)
