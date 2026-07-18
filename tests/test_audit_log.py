"""Tests for Phase 8 — 1.0 Audit Log. Requires a reachable, migrated
DB (024 applied) — skips cleanly if one isn't configured.
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


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


def test_login_creates_audit_entry():
    tenant_id = _ensure_tenant("test-audit-login")
    admin_id = _ensure_admin("audit-login@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-audit-login", "audit-login@example.com")

    from app.services.audit import get_audit_log

    entries = get_audit_log(tenant_id, days=1)
    login_entries = [e for e in entries if e["action"] == "login" and e["admin_email"] == "audit-login@example.com"]
    assert len(login_entries) >= 1


def test_upload_creates_audit_entry():
    tenant_id = _ensure_tenant("test-audit-upload")
    admin_id = _ensure_admin("audit-upload@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-audit-upload", "audit-upload@example.com")

    resp = client.post(
        "/t/test-audit-upload/api/documents/upload",
        files={"file": ("t.md", b"# hello", "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    document_id = resp.json()["id"]

    from app.services.audit import get_audit_log

    entries = get_audit_log(tenant_id, days=1)
    matching = [e for e in entries if e["action"] == "upload" and e["entity_id"] == document_id]
    assert len(matching) == 1
    assert matching[0]["entity_type"] == "document"
    assert matching[0]["admin_email"] == "audit-upload@example.com"


def test_review_state_change_creates_audit_entry():
    tenant_id = _ensure_tenant("test-audit-edit")
    admin_id = _ensure_admin("audit-edit@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-audit-edit", "audit-edit@example.com")

    upload = client.post(
        "/t/test-audit-edit/api/documents/upload",
        files={"file": ("t.md", b"# hello", "text/markdown")},
    )
    document_id = upload.json()["id"]

    resp = client.post(
        f"/t/test-audit-edit/api/documents/{document_id}/review-state", json={"state": "review"}
    )
    assert resp.status_code == 200, resp.text

    from app.services.audit import get_audit_log

    entries = get_audit_log(tenant_id, days=1)
    matching = [e for e in entries if e["action"] == "edit" and e["entity_id"] == document_id]
    assert len(matching) == 1
    assert "review" in matching[0]["detail"]


def test_delete_creates_audit_entry():
    tenant_id = _ensure_tenant("test-audit-delete")
    admin_id = _ensure_admin("audit-delete@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-audit-delete", "audit-delete@example.com")

    upload = client.post(
        "/t/test-audit-delete/api/documents/upload",
        files={"file": ("t.md", b"# hello", "text/markdown")},
    )
    document_id = upload.json()["id"]

    resp = client.delete(f"/t/test-audit-delete/api/documents/{document_id}")
    assert resp.status_code == 200

    from app.services.audit import get_audit_log

    entries = get_audit_log(tenant_id, days=1)
    matching = [e for e in entries if e["action"] == "delete" and e["entity_id"] == document_id]
    assert len(matching) == 1


def test_audit_log_endpoint_requires_admin():
    tenant_id = _ensure_tenant("test-audit-endpoint-viewer")
    admin_id = _ensure_admin("audit-endpoint-viewer@example.com")
    _link(tenant_id, admin_id, "viewer")

    client = _client()
    _login(client, "test-audit-endpoint-viewer", "audit-endpoint-viewer@example.com")

    resp = client.get("/t/test-audit-endpoint-viewer/api/tenant/audit-log")
    assert resp.status_code == 403


def test_audit_log_endpoint_tenant_isolated():
    tenant_a = _ensure_tenant("test-audit-iso-a")
    tenant_b = _ensure_tenant("test-audit-iso-b")
    admin_a = _ensure_admin("audit-iso-a@example.com")
    admin_b = _ensure_admin("audit-iso-b@example.com")
    _link(tenant_a, admin_a, "editor")
    _link(tenant_b, admin_b, "admin")

    client_a = _client()
    _login(client_a, "test-audit-iso-a", "audit-iso-a@example.com")
    client_a.post(
        "/t/test-audit-iso-a/api/documents/upload",
        files={"file": ("t.md", b"# hello", "text/markdown")},
    )

    client_b = _client()
    _login(client_b, "test-audit-iso-b", "audit-iso-b@example.com")
    resp = client_b.get("/t/test-audit-iso-b/api/tenant/audit-log")
    assert resp.status_code == 200
    uploads_from_a_visible_to_b = [e for e in resp.json() if e["action"] == "upload"]
    assert uploads_from_a_visible_to_b == []


def test_audit_entry_survives_admin_deletion():
    """admin_id is ON DELETE SET NULL — deleting the admin must not
    delete the audit record of what they did."""
    from app.db.pool import get_conn
    from app.services.audit import get_audit_log, log_audit_event

    tenant_id = _ensure_tenant("test-audit-admindel")
    admin_id = _ensure_admin("audit-admindel@example.com")

    # Idempotency: a prior run of this test deleted the admin it
    # created, so _ensure_admin() above just made a NEW one — without
    # clearing old rows first, reruns against the same DB accumulate
    # multiple matching audit_log entries and the len(...) == 1
    # assertion below breaks, same non-idempotency pitfall earlier
    # rounds hit (e.g. Round 9's category-isolation test).
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM audit_log WHERE tenant_id = %s AND detail = %s",
            (tenant_id, "survives deletion test"),
        )
        cur.close()

    log_audit_event(tenant_id, admin_id, "upload", "document", 1, detail="survives deletion test")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM admin_user WHERE id = %s", (admin_id,))
        cur.close()

    entries = get_audit_log(tenant_id, days=1)
    matching = [e for e in entries if e["detail"] == "survives deletion test"]
    assert len(matching) == 1
    assert matching[0]["admin_email"] is None
