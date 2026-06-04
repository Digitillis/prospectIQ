"""SEC-006: Contacts search must strip PostgREST .or_() injection characters.

The _safe_search() helper must remove '(', ')', and ',' so a caller cannot
inject arbitrary PostgREST filter predicates via the search parameter.
"""

from __future__ import annotations

import pytest
from backend.app.api.routes.contacts import _safe_search


@pytest.mark.parametrize(
    "input_val,expected",
    [
        # Injection attempt: close-paren followed by a new predicate
        ("alice),workspace_id.neq.other_tenant", "aliceworkspace_id.neq.other_tenant"),
        # Multiple injection chars
        ("a(b,c)d", "abcd"),
        # Normal search — must pass through unchanged
        ("alice smith", "alice smith"),
        # Empty string
        ("", ""),
        # Injection at start
        ("(SELECT 1)", "SELECT 1"),
        # Comma-only
        (",,,", ""),
    ],
)
def test_safe_search_strips_injection_chars(input_val, expected):
    assert _safe_search(input_val) == expected


def test_safe_search_fails_on_current_code():
    """Verify that WITHOUT _safe_search the injection chars would survive.

    The injection payload '),(workspace_id.neq.other' contains ')' and ',' which
    PostgREST interprets as structural operators. _safe_search must remove them.
    """
    malicious = "alice),workspace_id.neq.other_tenant"
    result = _safe_search(malicious)
    # Result must not contain any of the injection chars
    for bad_char in (")", "(", ","):
        assert bad_char not in result, f"Injection char {bad_char!r} survived _safe_search"
