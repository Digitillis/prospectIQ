"""send_attempts.failure_code must distinguish a genuine assertion failure
from an expected, self-resolving scheduling deferral.

Before this fix, dispatch_scheduler.py collapsed company_locked,
hot_suppressed, prior_step_sent, and minimum_step_gap — none of which are
failures, they are deferrals that resolve on their own — into a single
"assertion_failed" failure_code alongside genuine gate failures. Combined
with minimum_step_gap re-logging on every 30-minute scheduler tick until the
gap clears, this is why send_attempts read as ~13.7k failures when the
majority were healthy deferrals. See backend/app/core/dispatch_scheduler.py.
"""

from __future__ import annotations

from backend.app.core.dispatch_scheduler import (
    _classify_assertion_failure_code,
    _is_permanent_assertion_failure,
)


def test_company_locked_classified_as_deferred_not_assertion_failed():
    reason = "company_locked: another contact reached 2d ago — retry after 5 business days"
    assert _classify_assertion_failure_code(reason) == "deferred_company_locked"
    assert _is_permanent_assertion_failure(reason) is False


def test_minimum_step_gap_classified_as_deferred_not_assertion_failed():
    reason = "minimum_step_gap: only 1d since step 3 was sent — minimum gap is 2d (step 4 blocked)"
    assert _classify_assertion_failure_code(reason) == "deferred_step_gap"
    assert _is_permanent_assertion_failure(reason) is False


def test_hot_suppressed_classified_as_deferred():
    reason = "hot_suppressed: company has active human engagement"
    assert _classify_assertion_failure_code(reason) == "deferred_hot_suppressed"
    assert _is_permanent_assertion_failure(reason) is False


def test_prior_step_sent_classified_as_deferred():
    reason = "prior_step_sent: step 2 not yet sent"
    assert _classify_assertion_failure_code(reason) == "deferred_prior_step"
    assert _is_permanent_assertion_failure(reason) is False


def test_cluster_routing_skip_still_classified_distinctly_and_permanent():
    """Retained from before this fix: cluster_routing_skip already had its
    own failure_code and is (independently of the routing-gate removal in
    the dispatch path) still a real permanent-failure classification for any
    caller that reaches this function directly.
    """
    reason = "cluster_routing_skip: cluster='other' requires manual review"
    assert _classify_assertion_failure_code(reason) == "cluster_routing_skip"
    assert _is_permanent_assertion_failure(reason) is True


def test_genuine_gate_failure_still_classified_as_assertion_failed():
    reason = "email_status_verified: email_status='unverified' for x@example.com"
    assert _classify_assertion_failure_code(reason) == "assertion_failed"


def test_bounce_rate_gate_is_transient_not_permanent():
    """bounce_rate_ok failures are not in the permanent list — the rolling
    7-day rate can drop back under threshold, so these should retry rather
    than dead-letter.
    """
    reason = "bounce_rate_ok: 7d contact-scoped: 6 bounced / 230 sent = 2.61% (threshold 2%)"
    assert _is_permanent_assertion_failure(reason) is False
    assert _classify_assertion_failure_code(reason) == "assertion_failed"


def test_suppressed_is_permanent():
    reason = "suppressed: company_status:not_interested"
    assert _is_permanent_assertion_failure(reason) is True
