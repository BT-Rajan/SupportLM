"""Tests for Phase 8 — 4.0 Health/Status Page. Requires a reachable
DB for the "healthy" path tests — skips those cleanly if unreachable
(the degraded-path tests mock the DB call and don't need a real one).
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

try:
    from app.db.pool import get_conn

    with get_conn() as _conn:
        pass
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False


def _client():
    from app.main import app

    return TestClient(app)


@pytest.mark.skipif(not _DB_AVAILABLE, reason="requires a configured, reachable DB")
def test_health_returns_ok_when_db_reachable():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


@pytest.mark.skipif(not _DB_AVAILABLE, reason="requires a configured, reachable DB")
def test_status_page_shows_operational_when_healthy():
    resp = _client().get("/status")
    assert resp.status_code == 200
    assert "All systems operational" in resp.text
    assert "Degraded" not in resp.text


def test_health_returns_503_when_db_unreachable():
    with patch("app.db.pool.get_conn", side_effect=Exception("DB down")):
        resp = _client().get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "database": "unreachable"}


def test_status_page_shows_degraded_when_db_unreachable():
    with patch("app.db.pool.get_conn", side_effect=Exception("DB down")):
        resp = _client().get("/status")
    # The status page itself must stay up (200) even when the
    # underlying database is down — that's the whole point of it
    # being checkable independently of the app's own data layer state.
    assert resp.status_code == 200
    assert "Degraded" in resp.text


def test_status_page_requires_no_auth_or_tenant_scope():
    """A status page's entire purpose is being checkable without
    credentials — no session cookie, no /t/{slug} prefix."""
    resp = _client().get("/status")
    assert resp.status_code == 200
