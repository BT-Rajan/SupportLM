"""Tests for Phase 4 — 3.3: /api/tenant/prompt-versions endpoints.
Requires a reachable, migrated DB — skips cleanly if one isn't
configured, same pattern as test_llm_config.py.
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


def _reset_prompt_versions(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE tenant SET active_prompt_version_id = NULL WHERE id = %s", (tenant_id,))
        cur.execute("DELETE FROM tenant_prompt_version WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


def test_viewer_can_list_but_not_create_or_activate():
    tenant_id = _ensure_tenant("test-pv-tenant")
    admin_id = _ensure_admin("pv-viewer@example.com")
    _link(tenant_id, admin_id, "viewer")
    _reset_prompt_versions(tenant_id)

    client = _client()
    _login(client, "test-pv-tenant", "pv-viewer@example.com")

    assert client.get("/t/test-pv-tenant/api/tenant/prompt-versions").status_code == 200
    assert (
        client.post(
            "/t/test-pv-tenant/api/tenant/prompt-versions", json={"prompt_text": "x {context}"}
        ).status_code
        == 403
    )
    assert client.post("/t/test-pv-tenant/api/tenant/prompt-versions/1/activate").status_code == 403


def test_editor_can_create_but_not_activate():
    tenant_id = _ensure_tenant("test-pv-editor")
    admin_id = _ensure_admin("pv-editor@example.com")
    _link(tenant_id, admin_id, "editor")
    _reset_prompt_versions(tenant_id)

    client = _client()
    _login(client, "test-pv-editor", "pv-editor@example.com")

    create = client.post(
        "/t/test-pv-editor/api/tenant/prompt-versions", json={"prompt_text": "Draft one. {context}"}
    )
    assert create.status_code == 200, create.text
    version_id = create.json()["id"]

    activate = client.post(f"/t/test-pv-editor/api/tenant/prompt-versions/{version_id}/activate")
    assert activate.status_code == 403


def test_create_does_not_auto_activate_via_endpoint():
    tenant_id = _ensure_tenant("test-pv-noauto")
    admin_id = _ensure_admin("pv-admin-noauto@example.com")
    _link(tenant_id, admin_id, "admin")
    _reset_prompt_versions(tenant_id)

    client = _client()
    _login(client, "test-pv-noauto", "pv-admin-noauto@example.com")

    create = client.post(
        "/t/test-pv-noauto/api/tenant/prompt-versions", json={"prompt_text": "Not live yet. {context}"}
    )
    assert create.status_code == 200

    listed = client.get("/t/test-pv-noauto/api/tenant/prompt-versions").json()
    assert len(listed) == 1
    assert listed[0]["is_active"] is False


def test_admin_activate_lifecycle_and_rollback():
    tenant_id = _ensure_tenant("test-pv-lifecycle")
    admin_id = _ensure_admin("pv-admin-lifecycle@example.com")
    _link(tenant_id, admin_id, "admin")
    _reset_prompt_versions(tenant_id)

    client = _client()
    _login(client, "test-pv-lifecycle", "pv-admin-lifecycle@example.com")

    v1 = client.post(
        "/t/test-pv-lifecycle/api/tenant/prompt-versions", json={"prompt_text": "Version one. {context}"}
    ).json()
    v2 = client.post(
        "/t/test-pv-lifecycle/api/tenant/prompt-versions", json={"prompt_text": "Version two. {context}"}
    ).json()

    activate_v2 = client.post(f"/t/test-pv-lifecycle/api/tenant/prompt-versions/{v2['id']}/activate")
    assert activate_v2.status_code == 200

    listed = {row["id"]: row["is_active"] for row in client.get(
        "/t/test-pv-lifecycle/api/tenant/prompt-versions"
    ).json()}
    assert listed[v2["id"]] is True
    assert listed[v1["id"]] is False

    # Rollback: re-activate v1.
    rollback = client.post(f"/t/test-pv-lifecycle/api/tenant/prompt-versions/{v1['id']}/activate")
    assert rollback.status_code == 200

    listed_after = {row["id"]: row["is_active"] for row in client.get(
        "/t/test-pv-lifecycle/api/tenant/prompt-versions"
    ).json()}
    assert listed_after[v1["id"]] is True
    assert listed_after[v2["id"]] is False


def test_activate_unknown_version_id_returns_404():
    tenant_id = _ensure_tenant("test-pv-404")
    admin_id = _ensure_admin("pv-admin-404@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-pv-404", "pv-admin-404@example.com")

    resp = client.post("/t/test-pv-404/api/tenant/prompt-versions/999999/activate")
    assert resp.status_code == 404


def test_cannot_activate_another_tenants_version_via_endpoint():
    tenant_a = _ensure_tenant("test-pv-iso-a")
    tenant_b = _ensure_tenant("test-pv-iso-b")
    admin_a = _ensure_admin("pv-admin-iso-a@example.com")
    admin_b = _ensure_admin("pv-admin-iso-b@example.com")
    _link(tenant_a, admin_a, "admin")
    _link(tenant_b, admin_b, "admin")
    _reset_prompt_versions(tenant_a)
    _reset_prompt_versions(tenant_b)

    client_a = _client()
    _login(client_a, "test-pv-iso-a", "pv-admin-iso-a@example.com")
    v_a = client_a.post(
        "/t/test-pv-iso-a/api/tenant/prompt-versions", json={"prompt_text": "Tenant A prompt. {context}"}
    ).json()

    client_b = _client()
    _login(client_b, "test-pv-iso-b", "pv-admin-iso-b@example.com")

    # Tenant B's admin cannot activate tenant A's version_id through
    # tenant B's own URL.
    resp = client_b.post(f"/t/test-pv-iso-b/api/tenant/prompt-versions/{v_a['id']}/activate")
    assert resp.status_code == 404
