"""Engagement state machine — defines valid status transitions.

Ensures company/contact status changes follow the expected lifecycle.
"""

from backend.app.core.models import CompanyStatus

# Valid transitions: current_status → set of allowed next statuses
VALID_TRANSITIONS: dict[str, set[str]] = {
    CompanyStatus.DISCOVERED: {
        CompanyStatus.RESEARCHED,
        CompanyStatus.DISQUALIFIED,
    },
    CompanyStatus.RESEARCHED: {
        CompanyStatus.QUALIFIED,
        CompanyStatus.DISQUALIFIED,
    },
    CompanyStatus.QUALIFIED: {
        CompanyStatus.OUTREACH_PENDING,
        CompanyStatus.DISQUALIFIED,
        CompanyStatus.PAUSED,
    },
    CompanyStatus.OUTREACH_PENDING: {
        CompanyStatus.CONTACTED,
        CompanyStatus.PAUSED,
    },
    CompanyStatus.CONTACTED: {
        CompanyStatus.ENGAGED,
        CompanyStatus.NOT_INTERESTED,
        CompanyStatus.BOUNCED,
        CompanyStatus.PAUSED,
    },
    CompanyStatus.ENGAGED: {
        CompanyStatus.MEETING_SCHEDULED,
        CompanyStatus.NOT_INTERESTED,
        CompanyStatus.PAUSED,
    },
    CompanyStatus.MEETING_SCHEDULED: {
        CompanyStatus.PILOT_DISCUSSION,
        CompanyStatus.NOT_INTERESTED,
        CompanyStatus.PAUSED,
    },
    CompanyStatus.PILOT_DISCUSSION: {
        CompanyStatus.PILOT_SIGNED,
        CompanyStatus.NOT_INTERESTED,
        CompanyStatus.PAUSED,
    },
    CompanyStatus.PILOT_SIGNED: {
        CompanyStatus.ACTIVE_PILOT,
        CompanyStatus.NOT_INTERESTED,
    },
    CompanyStatus.ACTIVE_PILOT: {
        CompanyStatus.CONVERTED,
        CompanyStatus.NOT_INTERESTED,
    },
    # Terminal states can only move to paused (for reactivation)
    CompanyStatus.NOT_INTERESTED: {
        CompanyStatus.PAUSED,
    },
    CompanyStatus.BOUNCED: {
        CompanyStatus.DISCOVERED,  # Re-enter pipeline with new contact
    },
    CompanyStatus.PAUSED: {
        # Can return to any active state
        CompanyStatus.DISCOVERED,
        CompanyStatus.RESEARCHED,
        CompanyStatus.QUALIFIED,
        CompanyStatus.CONTACTED,
        CompanyStatus.ENGAGED,
    },
}


def can_transition(current_status: str, new_status: str) -> bool:
    """Check if a status transition is valid.

    Args:
        current_status: Current company status.
        new_status: Proposed new status.

    Returns:
        True if the transition is allowed.
    """
    allowed = VALID_TRANSITIONS.get(current_status, set())
    return new_status in allowed


def get_valid_transitions(current_status: str) -> list[str]:
    """Get all valid next statuses from the current status.

    Args:
        current_status: Current company status.

    Returns:
        List of valid next status strings.
    """
    return sorted(VALID_TRANSITIONS.get(current_status, set()))
