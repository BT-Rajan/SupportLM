"""Tests for Phase 2 WBS 1.0 — role hierarchy and require_role(),
exercised through real routes. Requires a reachable, migrated DB —
skips cleanly if one isn't configured, same pattern as
test_tenant_resolution.py.
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


def _login(client, email):
    resp = client.post(
        "/t/test-rbac-tenant/api/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 200, resp.text


def test_viewer_can_list_but_not_upload():
    tenant_id = _ensure_tenant("test-rbac-tenant")
    admin_id = _ensure_admin("rbac-viewer@example.com")
    _link(tenant_id, admin_id, "viewer")

    client = _client()
    _login(client, "rbac-viewer@example.com")

    assert client.get("/t/test-rbac-tenant/api/documents").status_code == 200

    resp = client.post(
        "/t/test-rbac-tenant/api/documents/upload",
        files={"file": ("t.md", b"# hi", "text/markdown")},
    )
    assert resp.status_code == 403
    assert "editor" in resp.json()["detail"]


def test_editor_can_upload_but_not_delete():
    tenant_id = _ensure_tenant("test-rbac-tenant")
    admin_id = _ensure_admin("rbac-editor@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "rbac-editor@example.com")

    upload = client.post(
        "/t/test-rbac-tenant/api/documents/upload",
        files={"file": ("t.md", b"# hi", "text/markdown")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["id"]

    resp = client.delete(f"/t/test-rbac-tenant/api/documents/{doc_id}")
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"]


def test_admin_can_delete():
    tenant_id = _ensure_tenant("test-rbac-tenant")
    admin_id = _ensure_admin("rbac-admin@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "rbac-admin@example.com")

    upload = client.post(
        "/t/test-rbac-tenant/api/documents/upload",
        files={"file": ("t.md", b"# hi", "text/markdown")},
    )
    doc_id = upload.json()["id"]

    resp = client.delete(f"/t/test-rbac-tenant/api/documents/{doc_id}")
    assert resp.status_code == 200


def test_owner_outranks_everyone():
    tenant_id = _ensure_tenant("test-rbac-tenant")
    admin_id = _ensure_admin("rbac-owner@example.com")
    _link(tenant_id, admin_id, "owner")

    client = _client()
    _login(client, "rbac-owner@example.com")

    upload = client.post(
        "/t/test-rbac-tenant/api/documents/upload",
        files={"file": ("t.md", b"# hi", "text/markdown")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["id"]
    assert client.delete(f"/t/test-rbac-tenant/api/documents/{doc_id}").status_code == 200


def test_role_rank_ordering():
    from app.core.rbac import ROLE_RANK

    assert ROLE_RANK["viewer"] < ROLE_RANK["editor"] < ROLE_RANK["admin"] < ROLE_RANK["owner"]
