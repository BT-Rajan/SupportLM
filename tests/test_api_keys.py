"""Tests for Phase 2 WBS 2.0 — API key minting, role cap, X-API-Key
auth path, revocation, and tenant isolation. Requires a reachable,
migrated DB — skips cleanly if one isn't configured, same pattern as
test_rbac.py.
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


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


def test_editor_cannot_mint_keys():
    tenant_id = _ensure_tenant("test-api-keys-tenant")
    admin_id = _ensure_admin("apikey-editor@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-api-keys-tenant", "apikey-editor@example.com")

    resp = client.post("/t/test-api-keys-tenant/api/api-keys", json={"name": "ci", "role": "viewer"})
    assert resp.status_code == 403


def test_admin_cannot_mint_owner_key():
    tenant_id = _ensure_tenant("test-api-keys-tenant")
    admin_id = _ensure_admin("apikey-admin@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-api-keys-tenant", "apikey-admin@example.com")

    resp = client.post("/t/test-api-keys-tenant/api/api-keys", json={"name": "ci", "role": "owner"})
    assert resp.status_code == 400
    assert "higher than your own" in resp.json()["detail"]


def test_key_lifecycle_create_use_revoke():
    tenant_id = _ensure_tenant("test-api-keys-tenant")
    admin_id = _ensure_admin("apikey-admin2@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-api-keys-tenant", "apikey-admin2@example.com")

    create = client.post("/t/test-api-keys-tenant/api/api-keys", json={"name": "ci", "role": "editor"})
    assert create.status_code == 200, create.text
    body = create.json()
    raw_key = body["api_key"]
    assert raw_key.startswith("sk_live_")
    key_id = body["id"]

    # List never returns the raw key or hash — only the prefix.
    listed = client.get("/t/test-api-keys-tenant/api/api-keys")
    assert listed.status_code == 200
    assert all("api_key" not in row and "key_hash" not in row for row in listed.json())

    # The minted key authenticates as its own role (editor): can
    # upload, can't delete — same as a session-authenticated editor.
    anon_client = _client()
    upload = anon_client.post(
        "/t/test-api-keys-tenant/api/documents/upload",
        headers={"X-API-Key": raw_key},
        files={"file": ("t.md", b"# hi", "text/markdown")},
    )
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["id"]

    delete = anon_client.delete(
        f"/t/test-api-keys-tenant/api/documents/{doc_id}",
        headers={"X-API-Key": raw_key},
    )
    assert delete.status_code == 403

    # Revoke, then confirm the same key no longer authenticates.
    revoke = client.post(f"/t/test-api-keys-tenant/api/api-keys/{key_id}/revoke")
    assert revoke.status_code == 200

    after_revoke = anon_client.get(
        "/t/test-api-keys-tenant/api/documents",
        headers={"X-API-Key": raw_key},
    )
    assert after_revoke.status_code == 401


def test_key_rejected_on_wrong_tenant():
    tenant_a = _ensure_tenant("test-api-keys-tenant-a")
    _ensure_tenant("test-api-keys-tenant-b")
    admin_id = _ensure_admin("apikey-crosstenant@example.com")
    _link(tenant_a, admin_id, "admin")

    client = _client()
    _login(client, "test-api-keys-tenant-a", "apikey-crosstenant@example.com")
    create = client.post("/t/test-api-keys-tenant-a/api/api-keys", json={"name": "ci", "role": "viewer"})
    raw_key = create.json()["api_key"]

    anon_client = _client()
    resp = anon_client.get("/t/test-api-keys-tenant-b/api/documents", headers={"X-API-Key": raw_key})
    assert resp.status_code == 401


def test_invalid_key_rejected():
    _ensure_tenant("test-api-keys-tenant")
    client = _client()
    resp = client.get(
        "/t/test-api-keys-tenant/api/documents",
        headers={"X-API-Key": "sk_live_not_a_real_key"},
    )
    assert resp.status_code == 401
