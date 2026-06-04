"""Tests for PR E: ContextPacket assembly via ContextPacketBuilder.

Ten invariants:

1. test_full_packet_builds_from_contact_company_and_draft_data
   Happy path — contact + company + one prior sent draft. contact_snapshot,
   company_snapshot, and prior_messages populated; is_first_touch=False;
   packet.id assigned after persist.

2. test_missing_contact_produces_degraded_packet
   _load_contact returns None. contact_snapshot is empty; build does not crash.

3. test_missing_company_produces_degraded_packet
   _load_company returns None. company_snapshot is empty; build does not crash.

4. test_missing_workspace_id_logs_warning
   Contact row has no workspace_id and none passed to build(). A WARNING
   containing 'workspace_id=NULL' is logged; packet.workspace_id = ''.

5. test_prior_messages_are_populated
   Two sent drafts exist. prior_messages has 2 entries; is_first_touch=False;
   days_since_last_touch is non-None and non-negative.

6. test_suppression_status_is_reflected
   Suppression loader sets packet.suppression_status = 'company'. The built
   packet reflects that status and reason.

7. test_company_lock_and_traction_are_reflected
   is_company_locked returns (True, 'reply_in_progress') and
   get_company_traction has_traction=True. packet.company_locked=True and
   traction_signal='warm' (no active_conversation to override it).

8. test_prohibited_prior_angle_added_for_step_two_and_beyond
   Sequence step=2; _get_prior_angle returns a prior angle string. The angle
   appears in packet.prohibited_claims.

9. test_active_conversation_detected
   Reply history contains a reply with sentiment='interested'.
   packet.active_conversation=True; traction_signal='active_reply'.

10. test_malformed_uuid_does_not_enter_suppression_filter
    _load_suppression called directly with invalid UUID strings for both
    contact_id and company_id. suppression_log table is never accessed;
    errors list records both invalids.
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

CONTACT_ID = "a1b2c3d4-1111-1111-1111-111111111111"
COMPANY_ID = "b2c3d4e5-2222-2222-2222-222222222222"
WS_ID = "c3d4e5f6-3333-3333-3333-333333333333"

CONTACT = {
    "id": CONTACT_ID,
    "workspace_id": WS_ID,
    "full_name": "Jane Doe",
    "email": "jane@acme.com",
    "linkedin_url": "https://linkedin.com/in/janedoe",
    "seniority": "director",
    "title": "Director of Operations",
    "department": "Operations",
    "reply_sentiment": None,
    "linkedin_status": "connected",
    "company_id": COMPANY_ID,
}

COMPANY = {
    "id": COMPANY_ID,
    "name": "Acme Corp",
    "domain": "acme.com",
    "employee_count": 500,
    "headcount_growth_6m": 5.2,
    "industry": "Manufacturing",
    "tier": "A",
    "status": "active",
    "intent_score": 72,
    "assigned_persona": "ops_director",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_db(persist_id: str = "pkt-uuid-001") -> MagicMock:
    """DB mock with context_packets insert wired for persist step."""
    db = MagicMock()
    db.workspace_id = WS_ID
    cp_table = MagicMock()
    cp_table.insert.return_value.execute.return_value.data = [{"id": persist_id}]

    def _dispatch(name: str) -> MagicMock:
        if name == "context_packets":
            return cp_table
        return MagicMock()

    db.client.table.side_effect = _dispatch
    return db


def _channel_mock(
    locked: bool = False,
    lock_reason: str | None = None,
    has_traction: bool = False,
) -> MagicMock:
    """channel_coordinator module mock injected via patch.dict(sys.modules)."""
    m = MagicMock()
    m.get_active_channel.return_value = ("email", "default")
    m.is_company_locked.return_value = (locked, lock_reason)
    m.get_company_traction.return_value = {"has_traction": has_traction}
    return m


def _load_builder():
    from backend.app.core.context_intelligence import ContextPacketBuilder

    return ContextPacketBuilder


# ---------------------------------------------------------------------------
# Test 1: happy path
# ---------------------------------------------------------------------------


def test_full_packet_builds_from_contact_company_and_draft_data():
    """Full packet: contact + company found; one prior sent draft."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)
    prior = [
        {
            "draft_id": "d-001",
            "step": 1,
            "channel": "email",
            "subject": "Intro",
            "sent_at": "2026-05-01T10:00:00Z",
            "primary_angle": "ops_efficiency",
        }
    ]

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=prior),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert packet.contact_snapshot["full_name"] == "Jane Doe"
    assert packet.contact_snapshot["has_email"] is True
    assert packet.contact_snapshot["has_linkedin"] is True
    assert packet.company_snapshot["name"] == "Acme Corp"
    assert packet.company_snapshot["tier"] == "A"
    assert len(packet.prior_messages) == 1
    assert packet.is_first_touch is False
    assert packet.workspace_id == WS_ID
    assert packet.id == "pkt-uuid-001"
    assert packet.content_hash


# ---------------------------------------------------------------------------
# Test 2: missing contact
# ---------------------------------------------------------------------------


def test_missing_contact_produces_degraded_packet():
    """Contact not found → contact_snapshot empty; packet still built."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)

    with (
        patch.object(builder, "_load_contact", return_value=None),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=[]),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert packet.contact_snapshot == {}
    assert packet.company_snapshot["name"] == "Acme Corp"
    assert packet.is_first_touch is True
    assert packet.content_hash


# ---------------------------------------------------------------------------
# Test 3: missing company
# ---------------------------------------------------------------------------


def test_missing_company_produces_degraded_packet():
    """Company not found → company_snapshot empty; build does not crash."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=None),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=[]),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert packet.company_snapshot == {}
    assert packet.contact_snapshot["full_name"] == "Jane Doe"
    assert packet.workspace_id == WS_ID


# ---------------------------------------------------------------------------
# Test 4: missing workspace_id logs warning
# ---------------------------------------------------------------------------


def test_missing_workspace_id_logs_warning(caplog):
    """Contact has no workspace_id; none passed to build() → WARNING with 'workspace_id=NULL'."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)
    contact_no_ws = {**CONTACT, "workspace_id": None}

    with (
        patch.object(builder, "_load_contact", return_value=contact_no_ws),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=[]),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
        caplog.at_level(logging.WARNING, logger="backend.app.core.context_intelligence"),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
            # workspace_id intentionally omitted
        )

    assert packet.workspace_id == ""
    assert any(
        "workspace_id=NULL" in r.message for r in caplog.records if r.levelno == logging.WARNING
    ), f"Expected workspace_id=NULL warning. Records: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Test 5: prior messages populated
# ---------------------------------------------------------------------------


def test_prior_messages_are_populated():
    """Two sent drafts → prior_messages has 2 entries; is_first_touch=False; days_since_last_touch set."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)
    prior = [
        {
            "draft_id": "d-001",
            "step": 1,
            "channel": "email",
            "subject": "Intro",
            "sent_at": "2026-04-20T10:00:00+00:00",
            "primary_angle": "ops_efficiency",
        },
        {
            "draft_id": "d-002",
            "step": 2,
            "channel": "email",
            "subject": "Follow-up",
            "sent_at": "2026-04-27T10:00:00+00:00",
            "primary_angle": "cost_reduction",
        },
    ]

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=prior),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert len(packet.prior_messages) == 2
    assert packet.is_first_touch is False
    assert packet.days_since_last_touch is not None
    assert packet.days_since_last_touch >= 0


# ---------------------------------------------------------------------------
# Test 6: suppression status reflected
# ---------------------------------------------------------------------------


def test_suppression_status_is_reflected():
    """Active company suppression → packet.suppression_status='company'."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)

    def _set_suppressed(contact_id, contact, company_id, packet, errors):
        packet.suppression_status = "company"
        packet.suppression_reason = "dnc_list"

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression", side_effect=_set_suppressed),
        patch.object(builder, "_load_prior_messages", return_value=[]),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert packet.suppression_status == "company"
    assert packet.suppression_reason == "dnc_list"


# ---------------------------------------------------------------------------
# Test 7: company lock and traction reflected
# ---------------------------------------------------------------------------


def test_company_lock_and_traction_are_reflected():
    """is_company_locked=True + has_traction=True → company_locked=True; traction_signal='warm'."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)
    ch = _channel_mock(locked=True, lock_reason="reply_in_progress", has_traction=True)

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=[]),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": ch}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert packet.company_locked is True
    assert packet.company_lock_reason == "reply_in_progress"
    # active_conversation=False (no replies), so traction_signal stays 'warm'
    assert packet.traction_signal == "warm"


# ---------------------------------------------------------------------------
# Test 8: prohibited prior angle for step 2+
# ---------------------------------------------------------------------------


def test_prohibited_prior_angle_added_for_step_two_and_beyond():
    """Step 2 build: prior step-1 angle appears in packet.prohibited_claims."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)
    prior_angle = "ops_efficiency_angle"

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(
            builder,
            "_load_prior_messages",
            return_value=[
                {
                    "draft_id": "d-001",
                    "step": 1,
                    "channel": "email",
                    "subject": "Intro",
                    "sent_at": "2026-05-01T10:00:00Z",
                    "primary_angle": prior_angle,
                },
            ],
        ),
        patch.object(builder, "_get_prior_angle", return_value=prior_angle),
        patch.object(builder, "_load_reply_history", return_value=[]),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
            sequence_name="mfg_ops_sequence",
            sequence_step=2,
        )

    assert packet.prior_step_angle == prior_angle
    assert any("ops_efficiency_angle" in claim for claim in packet.prohibited_claims), (
        f"Expected prior angle in prohibited_claims. Got: {packet.prohibited_claims}"
    )


# ---------------------------------------------------------------------------
# Test 9: active conversation detection
# ---------------------------------------------------------------------------


def test_active_conversation_detected():
    """Reply with 'interested' sentiment → active_conversation=True; traction_signal='active_reply'."""
    ContextPacketBuilder = _load_builder()
    db = _make_db()
    builder = ContextPacketBuilder(db)
    reply_history = [
        {
            "contact_id": CONTACT_ID,
            "sentiment": "interested",
            "replied_at": "2026-05-10T09:00:00Z",
            "body_excerpt": "Yes, let's set up a call.",
        }
    ]

    with (
        patch.object(builder, "_load_contact", return_value=CONTACT),
        patch.object(builder, "_load_company", return_value=COMPANY),
        patch.object(builder, "_load_suppression"),
        patch.object(builder, "_load_prior_messages", return_value=[]),
        patch.object(builder, "_load_reply_history", return_value=reply_history),
        patch.object(builder, "_load_sibling_history", return_value=[]),
        patch.dict(sys.modules, {"backend.app.core.channel_coordinator": _channel_mock()}),
    ):
        packet = builder.build(
            contact_id=CONTACT_ID,
            company_id=COMPANY_ID,
            purpose="draft_generation",
        )

    assert packet.active_conversation is True
    # active_reply supersedes warm traction (step 10 logic)
    assert packet.traction_signal == "active_reply"


# ---------------------------------------------------------------------------
# Test 10: malformed UUID does not enter .or_() filter
# ---------------------------------------------------------------------------


def test_malformed_uuid_does_not_enter_suppression_filter():
    """Invalid UUID for both contact and company → suppression_log never accessed; errors recorded."""
    from backend.app.core.context_intelligence import ContextPacketBuilder

    db = _make_db()
    builder = ContextPacketBuilder(db)
    errors: list[str] = []
    packet_stub = MagicMock()

    builder._load_suppression(
        "not-a-valid-uuid",
        None,
        "also-not-valid",
        packet_stub,
        errors,
    )

    # Both UUIDs invalid → filter_parts empty → early return; table never reached
    accessed_tables = [c.args[0] for c in db.client.table.call_args_list]
    assert "suppression_log" not in accessed_tables, (
        f"suppression_log was queried despite malformed UUIDs: {accessed_tables}"
    )

    # Both invalid inputs must be recorded in errors
    assert any("invalid_contact_uuid" in e for e in errors), f"errors={errors}"
    assert any("invalid_company_uuid" in e for e in errors), f"errors={errors}"
