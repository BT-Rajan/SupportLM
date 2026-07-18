"""Tests for Phase 4 — 2.4: /api/tenant/llm-config endpoints. Requires
a reachable, migrated DB — skips cleanly if one isn't configured, same
pattern as test_api_keys.py.
"""
import pytest
from fastapi.testclient import TestClient

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


def _ensure_admin(email: str) -> int:
    from app.core.security import hash_password
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM admin_user WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            admin_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'admin')",
                (email, hash_password("testpass123")),
            )
            admin_id = cur.lastrowid
        cur.close()
    return admin_id


def _link(tenant_id: int, admin_id: int, role: str):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_user (tenant_id, admin_id, role) VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE role = VALUES(role)""",
            (tenant_id, admin_id, role),
        )
        cur.close()


def _clear_config(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_llm_config WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


def test_editor_cannot_read_or_write_llm_config():
    tenant_id = _ensure_tenant("test-llm-config-tenant")
    admin_id = _ensure_admin("llmcfg-editor@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-llm-config-tenant", "llmcfg-editor@example.com")

    assert client.get("/t/test-llm-config-tenant/api/tenant/llm-config").status_code == 403
    assert (
        client.post(
            "/t/test-llm-config-tenant/api/tenant/llm-config",
            json={"provider": "openai", "model": "gpt-4o-mini"},
        ).status_code
        == 403
    )


def test_get_returns_null_when_unconfigured():
    tenant_id = _ensure_tenant("test-llm-config-null")
    admin_id = _ensure_admin("llmcfg-admin-null@example.com")
    _link(tenant_id, admin_id, "admin")
    _clear_config(tenant_id)

    client = _client()
    _login(client, "test-llm-config-null", "llmcfg-admin-null@example.com")

    resp = client.get("/t/test-llm-config-null/api/tenant/llm-config")
    assert resp.status_code == 200
    assert resp.json() is None


def test_set_config_never_echoes_raw_key_and_reports_has_custom_key():
    tenant_id = _ensure_tenant("test-llm-config-set")
    admin_id = _ensure_admin("llmcfg-admin-set@example.com")
    _link(tenant_id, admin_id, "admin")
    _clear_config(tenant_id)

    client = _client()
    _login(client, "test-llm-config-set", "llmcfg-admin-set@example.com")

    resp = client.post(
        "/t/test-llm-config-set/api/tenant/llm-config",
        json={"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "api_key": "sk-secret-123"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "anthropic"
    assert body["has_custom_api_key"] is True
    assert "api_key" not in body
    assert "sk-secret-123" not in resp.text

    fetched = client.get("/t/test-llm-config-set/api/tenant/llm-config").json()
    assert fetched["has_custom_api_key"] is True
    assert "sk-secret-123" not in client.get("/t/test-llm-config-set/api/tenant/llm-config").text


def test_reject_unknown_provider():
    tenant_id = _ensure_tenant("test-llm-config-badprovider")
    admin_id = _ensure_admin("llmcfg-admin-bad@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-llm-config-badprovider", "llmcfg-admin-bad@example.com")

    resp = client.post(
        "/t/test-llm-config-badprovider/api/tenant/llm-config",
        json={"provider": "not-a-real-provider", "model": "x"},
    )
    assert resp.status_code == 400


def test_reset_clears_config_back_to_null():
    tenant_id = _ensure_tenant("test-llm-config-reset")
    admin_id = _ensure_admin("llmcfg-admin-reset@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-llm-config-reset", "llmcfg-admin-reset@example.com")

    client.post(
        "/t/test-llm-config-reset/api/tenant/llm-config",
        json={"provider": "openai", "model": "gpt-4o-mini", "api_key": "k"},
    )
    assert client.get("/t/test-llm-config-reset/api/tenant/llm-config").json() is not None

    reset = client.post("/t/test-llm-config-reset/api/tenant/llm-config/reset")
    assert reset.status_code == 200

    assert client.get("/t/test-llm-config-reset/api/tenant/llm-config").json() is None


def test_config_is_tenant_isolated():
    tenant_a = _ensure_tenant("test-llm-config-iso-a")
    tenant_b = _ensure_tenant("test-llm-config-iso-b")
    admin_a = _ensure_admin("llmcfg-admin-iso-a@example.com")
    admin_b = _ensure_admin("llmcfg-admin-iso-b@example.com")
    _link(tenant_a, admin_a, "admin")
    _link(tenant_b, admin_b, "admin")
    _clear_config(tenant_a)
    _clear_config(tenant_b)

    client_a = _client()
    _login(client_a, "test-llm-config-iso-a", "llmcfg-admin-iso-a@example.com")
    client_a.post(
        "/t/test-llm-config-iso-a/api/tenant/llm-config",
        json={"provider": "openai", "model": "gpt-4o-mini", "api_key": "a-key"},
    )

    client_b = _client()
    _login(client_b, "test-llm-config-iso-b", "llmcfg-admin-iso-b@example.com")

    # Tenant B, even as its own admin, sees no config — A's write never
    # crossed over.
    assert client_b.get("/t/test-llm-config-iso-b/api/tenant/llm-config").json() is None
