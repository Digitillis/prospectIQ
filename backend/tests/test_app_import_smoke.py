# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: Avanish Mehrotra & Digitillis Technical Team
"""Import smoke test for the FastAPI application entrypoint.

Catches syntax errors and broken imports in route modules before they reach
production. Added after a pre-existing SyntaxError in multi_thread.py
caused a crash-loop on Railway because the error was only caught at uvicorn
import time during deployment — not in CI.

This test does NOT start the server, connect to external services, or
execute any send path. The scheduler only starts inside the lifespan
context manager, which is never entered here.
"""

from __future__ import annotations


def test_app_entrypoint_imports_cleanly():
    """backend.app.api.main must import without errors.

    A failure here means a syntax error, a circular import, or a broken
    module-level expression exists somewhere in the route tree. Fix the
    import error before landing any code change.
    """
    # Import side-effect: registers all routes. Does NOT start the server,
    # scheduler, or any background tasks.
    from backend.app.api.main import app  # noqa: F401

    # A non-None app object is the only assertion needed — if the import
    # raised, pytest would have already failed above.
    assert app is not None
