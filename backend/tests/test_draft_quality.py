"""Tests for draft_quality URL hard-block at sequence step 1.

Step 1 cold opens must never contain a URL. The validator rejects those
drafts with check_name='url_in_step_1' and severity='error'. Step 2+ may
contain URLs without triggering this specific rule.
"""

from __future__ import annotations

from backend.app.core.draft_quality import (
    contains_url,
    is_step_1_url_violation,
    validate_draft,
)


def _draft(step: int, body: str, subject: str = "Quick question on your line") -> dict:
    return {
        "id": f"draft-{step}",
        "sequence_step": step,
        "subject": subject,
        "body": body,
    }


def test_contains_url_detects_http_and_https() -> None:
    assert contains_url("see https://example.com/x for details")
    assert contains_url("HTTP://Example.com")
    assert contains_url("link: http://docs.foo.io/abc")
    assert not contains_url("just plain text — no link here")
    assert not contains_url("")
    assert not contains_url(None)


def test_step_1_blocks_urls() -> None:
    """Three step-1 drafts each carrying a URL must all be flagged as violations."""
    body_a = (
        "Hey Avi,\n\nI noticed your team is scaling up the Iowa plant. "
        "Wanted to share https://digitillis.com/predictive-mx for context.\n\n"
        "Worth a 15-minute call?\n\nAvanish"
    )
    body_b = (
        "Hi there — context: http://lns-research.com/pdm-benchmarks\n\n"
        "Curious whether your maintenance team is reactive or condition-based.\n\nAvanish"
    )
    body_c = (
        "Quick note. We see manufacturers cut downtime 23-41%. "
        "Details: HTTPS://example.org/whitepaper\n\nWorth a chat?"
    )

    for body in (body_a, body_b, body_c):
        draft = _draft(step=1, body=body)
        assert is_step_1_url_violation(draft), f"Should flag URL in step-1 body: {body[:60]}"

        report = validate_draft(draft)
        codes = [i.check_name for i in report.issues]
        assert "url_in_step_1" in codes, f"validate_draft must add url_in_step_1 issue. Got {codes}"
        # And block the draft
        assert not report.passed, "Step-1 URL must fail the report (passed=False)"


def test_step_2_url_passes_url_rule() -> None:
    """A step-2 draft with a URL is allowed by the url_in_step_1 rule."""
    body = (
        "Following up on last week's note. The asset reliability deck is here: "
        "https://digitillis.com/asset-reliability-overview\n\n"
        "Open to 20 minutes next Tuesday?\n\nAvanish"
    )
    draft = _draft(step=2, body=body)

    assert not is_step_1_url_violation(draft)

    report = validate_draft(draft)
    codes = [i.check_name for i in report.issues]
    # url_in_step_1 specifically must NOT be present
    assert "url_in_step_1" not in codes


def test_step_1_no_url_passes_url_rule() -> None:
    body = (
        "Hi Avi — saw your team just opened the Indiana facility. Curious how "
        "you're handling preventive maintenance scheduling there. Worth a quick "
        "20-minute call?\n\nAvanish"
    )
    draft = _draft(step=1, body=body)
    assert not is_step_1_url_violation(draft)

    report = validate_draft(draft)
    codes = [i.check_name for i in report.issues]
    assert "url_in_step_1" not in codes


def test_step_1_violation_handles_string_step() -> None:
    """sequence_step may arrive as 'touch_1' (string). Must still detect step 1."""
    draft = {
        "id": "d-x",
        "sequence_step": "touch_1",
        "subject": "Hi",
        "body": "Visit https://example.com for details",
    }
    assert is_step_1_url_violation(draft)
