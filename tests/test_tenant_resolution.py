"""Tests for WBS 3.1/3.2's request-scoping dependencies
(app/core/tenant_scope.py), exercised through real routes — not just
the unit-level enforce_active checks in test_tenant_access.py. Requires
a reachable, migrated DB — skips cleanly if one isn't configured, since
this repo has no DB test fixture/CI setup yet."""
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


def _ensure_tenant(slug: str, status: str) -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE tenant SET status = %s WHERE id = %s", (status, row["id"]))
            tenant_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, %s)",
                (slug, slug, status),
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


def _ensure_admin(email: str, password_hash: str) -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM admin_user WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            admin_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'owner')",
                (email, password_hash),
            )
            admin_id = cur.lastrowid
        cur.close()
    return admin_id


def _link(tenant_id: int, admin_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT IGNORE INTO tenant_user (tenant_id, admin_id, role) VALUES (%s, %s, 'owner')",
            (tenant_id, admin_id),
        )
        cur.close()


def _client():
    from app.main import app

    return TestClient(app)


def test_unscoped_root_points_at_tenant_shape():
    resp = _client().get("/")
    assert resp.status_code == 404
    assert "/t/" in resp.json()["detail"]


def test_unknown_tenant_slug_404s():
    resp = _client().get("/t/definitely-not-a-real-tenant-slug/")
    assert resp.status_code == 404


def test_suspended_tenant_blocked_on_anonymous_routes():
    _ensure_tenant("test-suspended-tenant", "suspended")
    client = _client()
    assert client.get("/t/test-suspended-tenant/").status_code == 403
    assert client.get("/t/test-suspended-tenant/admin").status_code == 403
    assert client.get("/t/test-suspended-tenant/api/categories").status_code == 403


def test_active_tenant_page_renders_with_slug():
    _ensure_tenant("test-active-tenant", "active")
    resp = _client().get("/t/test-active-tenant/")
    assert resp.status_code == 200
    assert "window.__SUPPORTLM_CONFIG__" in resp.text
    assert 'tenant_slug: "test-active-tenant"' in resp.text


def test_trial_tenant_allowed_through():
    _ensure_tenant("test-trial-tenant", "trial")
    resp = _client().get("/t/test-trial-tenant/")
    assert resp.status_code == 200


def test_admin_routes_require_session():
    _ensure_tenant("test-admin-tenant", "active")
    client = _client()
    assert client.get("/t/test-admin-tenant/api/documents").status_code == 401


def test_admin_blocked_from_tenant_they_dont_own():
    """The specific gap the reconciled 3.1 exists to close: a valid
    session for tenant A must not grant access to tenant B."""
    from app.core.security import hash_password

    tenant_a = _ensure_tenant("test-cross-tenant-a", "active")
    tenant_b = _ensure_tenant("test-cross-tenant-b", "active")
    admin_id = _ensure_admin("cross-tenant-test@example.com", hash_password("testpass123"))
    _link(tenant_a, admin_id)  # deliberately NOT linked to tenant_b

    client = _client()
    login = client.post(
        "/t/test-cross-tenant-a/api/auth/login",
        json={"email": "cross-tenant-test@example.com", "password": "testpass123"},
    )
    assert login.status_code == 200

    assert client.get("/t/test-cross-tenant-a/api/documents").status_code == 200
    resp = client.get("/t/test-cross-tenant-b/api/documents")
    assert resp.status_code == 403
    assert "access" in resp.json()["detail"].lower()


def test_suspended_tenant_blocks_even_a_linked_admin():
    from app.core.security import hash_password

    tenant_id = _ensure_tenant("test-suspended-but-linked", "active")
    admin_id = _ensure_admin("suspended-linked-test@example.com", hash_password("testpass123"))
    _link(tenant_id, admin_id)

    client = _client()
    client.post(
        "/t/test-suspended-but-linked/api/auth/login",
        json={"email": "suspended-linked-test@example.com", "password": "testpass123"},
    )
    assert client.get("/t/test-suspended-but-linked/api/documents").status_code == 200

    _ensure_tenant("test-suspended-but-linked", "suspended")
    assert client.get("/t/test-suspended-but-linked/api/documents").status_code == 403
