"""Tests for Phase 8 — 2.0 Rate Limiting & Abuse Protection. Requires
a reachable, migrated DB (025 applied) — skips cleanly if one isn't
configured.

Tests marked `real_rate_limit` opt out of conftest.py's autouse bypass
(see that file's docstring) — every other test in this suite calls
`/api/chat` with rate limiting silently disabled, by design, so this
is the one file that actually exercises it.
"""
import pytest

try:
    from app.db.pool import get_conn

    with get_conn() as _conn:
        pass
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DB_AVAILABLE, reason="requires a configured, reachable DB (see .env.example)"
)


def _ensure_tenant(slug: str) -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, 'active')", (slug, slug)
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


def _clear_buckets():
    """Idempotency across reruns — a real fixed-window bucket accrues
    real counts against the current minute, so a rerun within the same
    minute must start from a clean slate, same non-idempotency lesson
    as every other stateful test in this project."""
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM rate_limit_bucket")
        cur.close()


def test_increment_and_check_allows_under_limit():
    from app.core.rate_limit import _increment_and_check

    _clear_buckets()
    for _ in range(5):
        allowed = _increment_and_check("ip", "1.2.3.4", limit=10)
        assert allowed is True


def test_increment_and_check_rejects_over_limit():
    from app.core.rate_limit import _increment_and_check

    _clear_buckets()
    for _ in range(3):
        assert _increment_and_check("ip", "1.2.3.4", limit=3) is True
    # 4th call in the same window exceeds the limit of 3.
    assert _increment_and_check("ip", "1.2.3.4", limit=3) is False


def test_different_scope_keys_have_independent_buckets():
    from app.core.rate_limit import _increment_and_check

    _clear_buckets()
    for _ in range(3):
        assert _increment_and_check("ip", "1.1.1.1", limit=3) is True
    # A different IP's bucket is completely independent.
    assert _increment_and_check("ip", "2.2.2.2", limit=3) is True


def test_ip_and_tenant_scopes_are_independent():
    from app.core.rate_limit import _increment_and_check

    _clear_buckets()
    for _ in range(3):
        assert _increment_and_check("ip", "9.9.9.9", limit=3) is True
    # Same scope_key value ("9.9.9.9") but a different scope_type is a
    # completely separate bucket.
    assert _increment_and_check("tenant", "9.9.9.9", limit=3) is True


def test_client_ip_prefers_x_forwarded_for():
    from unittest.mock import MagicMock

    from app.core.rate_limit import _client_ip

    request = MagicMock()
    request.headers = {"x-forwarded-for": "5.5.5.5, 6.6.6.6"}
    assert _client_ip(request) == "5.5.5.5"


def test_client_ip_falls_back_to_client_host():
    from unittest.mock import MagicMock

    from app.core.rate_limit import _client_ip

    request = MagicMock()
    request.headers = {}
    request.client.host = "7.7.7.7"
    assert _client_ip(request) == "7.7.7.7"


@pytest.mark.real_rate_limit
def test_endpoint_returns_429_after_ip_limit_exceeded():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    _ensure_tenant("test-ratelimit-ip")
    _clear_buckets()

    client = TestClient(app)

    class _NormalProvider:
        PROVIDER_NAME = "deepseek"
        model = "deepseek-chat"

        def chat_completion(self, system_prompt, history, user_message):
            return {"content": "an answer", "input_tokens": 10, "output_tokens": 10}

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_NormalProvider()
    ), patch("app.core.rate_limit.IP_LIMIT_PER_MINUTE", 3):
        statuses = []
        for _ in range(5):
            resp = client.post("/t/test-ratelimit-ip/api/chat", json={"question": "hi"})
            statuses.append(resp.status_code)

    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]


@pytest.mark.real_rate_limit
def test_endpoint_returns_429_after_tenant_limit_exceeded():
    """Same test but at the tenant scope — TestClient's fixed IP means
    this also exercises the IP bucket, so the IP limit is raised well
    above the tenant limit under test to isolate which one actually
    triggers the 429."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    _ensure_tenant("test-ratelimit-tenant")
    _clear_buckets()

    client = TestClient(app)

    class _NormalProvider:
        PROVIDER_NAME = "deepseek"
        model = "deepseek-chat"

        def chat_completion(self, system_prompt, history, user_message):
            return {"content": "an answer", "input_tokens": 10, "output_tokens": 10}

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_NormalProvider()
    ), patch("app.core.rate_limit.IP_LIMIT_PER_MINUTE", 1000), patch(
        "app.core.rate_limit.TENANT_LIMIT_PER_MINUTE", 3
    ):
        statuses = []
        for _ in range(5):
            resp = client.post("/t/test-ratelimit-tenant/api/chat", json={"question": "hi"})
            statuses.append(resp.status_code)

    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]
