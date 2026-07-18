"""Tests for Phase 2 WBS 3.0 — server-side session invalidation,
logout-everywhere, and the cookie secure-flag audit. The DB-dependent
tests skip cleanly without a reachable DB, same pattern as
test_rbac.py / test_api_keys.py. The secure-flag wiring test doesn't
need a DB at all, so it isn't gated by pytestmark.
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


def test_cookie_secure_flag_follows_app_env():
    """3.3: `secure` must track app_env, not be hardcoded either way —
    hardcoded True would break the cookie on plain-HTTP XAMPP dev,
    hardcoded False would ship an insecure cookie in production."""
    from app.api.auth import _COOKIE_SECURE
    from app.core.config import settings

    assert _COOKIE_SECURE == (settings.app_env == "production")


db_only = pytest.mark.skipif(
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
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, 'active')",
                (slug, slug),
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


def _client():
    from app.main import app

    return TestClient(app)


@db_only
def test_logout_all_invalidates_the_calling_session_too():
    tenant_id = _ensure_tenant("test-session-tenant")
    admin_id = _ensure_admin("session-admin1@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    login = client.post(
        "/t/test-session-tenant/api/auth/login",
        json={"email": "session-admin1@example.com", "password": "testpass123"},
    )
    assert login.status_code == 200

    # Works before logout-all.
    assert client.get("/t/test-session-tenant/api/documents").status_code == 200

    revoke = client.post("/t/test-session-tenant/api/auth/logout-all")
    assert revoke.status_code == 200

    # The same client (same cookie jar) is now logged out — logout-all
    # invalidates the very session that called it, not just others.
    assert client.get("/t/test-session-tenant/api/documents").status_code == 401


@db_only
def test_logout_all_invalidates_other_sessions_too():
    tenant_id = _ensure_tenant("test-session-tenant")
    admin_id = _ensure_admin("session-admin2@example.com")
    _link(tenant_id, admin_id, "admin")

    client_a = _client()
    client_a.post(
        "/t/test-session-tenant/api/auth/login",
        json={"email": "session-admin2@example.com", "password": "testpass123"},
    )
    client_b = _client()
    client_b.post(
        "/t/test-session-tenant/api/auth/login",
        json={"email": "session-admin2@example.com", "password": "testpass123"},
    )

    # Both sessions work independently before either logs out.
    assert client_a.get("/t/test-session-tenant/api/documents").status_code == 200
    assert client_b.get("/t/test-session-tenant/api/documents").status_code == 200

    client_a.post("/t/test-session-tenant/api/auth/logout-all")

    # client_b's session was issued to the same admin, so it's
    # invalidated too, even though it never called logout-all itself.
    assert client_b.get("/t/test-session-tenant/api/documents").status_code == 401

    # A fresh login for the same admin works fine — it's issued
    # against the new, current session_version.
    client_c = _client()
    client_c.post(
        "/t/test-session-tenant/api/auth/login",
        json={"email": "session-admin2@example.com", "password": "testpass123"},
    )
    assert client_c.get("/t/test-session-tenant/api/documents").status_code == 200


@db_only
def test_pre_hardening_token_shape_is_rejected():
    """A token minted before 010_session_hardening.sql existed carries
    no `session_version` claim at all — simulated here by signing one
    the old way directly, bypassing login(). Must be rejected, not
    silently accepted (see migrations/010_session_hardening.sql's
    reasoning: a security-hardening change shouldn't grandfather in
    tokens minted under the weaker, unrevocable model)."""
    from itsdangerous import URLSafeTimedSerializer

    from app.core.config import settings

    tenant_id = _ensure_tenant("test-session-tenant")
    admin_id = _ensure_admin("session-admin3@example.com")
    _link(tenant_id, admin_id, "admin")

    old_shape_serializer = URLSafeTimedSerializer(settings.app_secret_key, salt="admin-session")
    old_token = old_shape_serializer.dumps({"admin_id": admin_id})  # no session_version

    client = _client()
    client.cookies.set("session", old_token)
    resp = client.get("/t/test-session-tenant/api/documents")
    assert resp.status_code == 401
