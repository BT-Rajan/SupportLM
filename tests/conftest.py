"""Shared pytest fixtures.

Phase 8 — 2.0 added real rate limiting to POST /api/chat. Without
this fixture, every existing test that calls the real endpoint via
TestClient (feedback, escalation, analytics tests, etc.) would share
one fixed test-client IP bucket and could start tripping 429s purely
from test-suite volume — especially across this project's own "3
consecutive full-suite runs" validation habit, which would otherwise
accumulate against the same real-world-minute bucket. Bypassed by
default; tests that actually need to exercise real enforcement mark
themselves `@pytest.mark.real_rate_limit` to opt back in.
"""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _bypass_rate_limit_by_default(request):
    if request.node.get_closest_marker("real_rate_limit"):
        yield
        return
    with patch("app.api.chat.enforce_rate_limit"):
        yield


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_rate_limit: exercise real rate-limit enforcement instead of the autouse bypass"
    )
