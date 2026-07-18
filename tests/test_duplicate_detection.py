"""Tests for Phase 3 WBS 3.0 — duplicate/conflict detection. DB-
dependent, skips cleanly without a reachable DB, same pattern as the
rest of the Phase 3 suite.
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


def _reset_tenant_content(tenant_id: int):
    """Clears documents (cascades to chunks/flags) so each test starts
    from a clean slate — same pattern test_hybrid_search.py's
    _reset_tenant_content() established for exactly this reason."""
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def _make_document(tenant_id: int, title: str, headings: list[str] | None = None) -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO document (tenant_id, title, filename, raw_markdown, status, review_state) "
            "VALUES (%s, %s, 't.md', '# x', 'ready', 'published')",
            (tenant_id, title),
        )
        document_id = cur.lastrowid
        for i, heading in enumerate(headings or []):
            cur.execute(
                "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, heading_path, content) "
                "VALUES (%s, %s, %s, %s, 'content')",
                (tenant_id, document_id, i, heading),
            )
        cur.close()
    return document_id


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


# --- scan_for_duplicates() ---

def test_scan_flags_near_duplicate_titles():
    from app.services.duplicate_detection import scan_for_duplicates

    tenant_id = _ensure_tenant("test-dup-tenant")
    _reset_tenant_content(tenant_id)
    doc_a = _make_document(tenant_id, "Refund Policy")
    doc_b = _make_document(tenant_id, "Refunds Policy")

    flags = scan_for_duplicates(tenant_id)
    title_flags = [f for f in flags if f["source"] == "title"]
    assert len(title_flags) == 1
    assert {title_flags[0]["document_id_a"], title_flags[0]["document_id_b"]} == {doc_a, doc_b}


def test_scan_does_not_flag_distinct_titles():
    from app.services.duplicate_detection import scan_for_duplicates

    tenant_id = _ensure_tenant("test-dup-tenant")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Shipping Policy")
    _make_document(tenant_id, "Return Policy")

    flags = scan_for_duplicates(tenant_id)
    assert flags == []


def test_scan_does_not_flag_headings_within_the_same_document():
    from app.services.duplicate_detection import scan_for_duplicates

    tenant_id = _ensure_tenant("test-dup-tenant")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Doc With Repeats", headings=["Setup Instructions", "Setup Instructions"])

    flags = scan_for_duplicates(tenant_id)
    assert [f for f in flags if f["source"] == "heading"] == []


def test_scan_flags_near_duplicate_headings_across_documents():
    from app.services.duplicate_detection import scan_for_duplicates

    tenant_id = _ensure_tenant("test-dup-tenant")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Doc A", headings=["Cancellation Policy"])
    _make_document(tenant_id, "Doc B", headings=["Cancelation Policy"])

    flags = scan_for_duplicates(tenant_id)
    heading_flags = [f for f in flags if f["source"] == "heading"]
    assert len(heading_flags) == 1


def test_rescanning_does_not_duplicate_an_unresolved_flag():
    from app.services.duplicate_detection import scan_for_duplicates

    tenant_id = _ensure_tenant("test-dup-tenant")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Refund Policy")
    _make_document(tenant_id, "Refunds Policy")

    first = scan_for_duplicates(tenant_id)
    second = scan_for_duplicates(tenant_id)
    assert len(first) == 1
    assert second == []  # already flagged and still unresolved — not recreated


def test_resolved_flag_is_not_recreated_by_a_later_scan():
    from app.db.pool import get_conn
    from app.services.duplicate_detection import scan_for_duplicates

    tenant_id = _ensure_tenant("test-dup-tenant")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Refund Policy")
    _make_document(tenant_id, "Refunds Policy")

    flags = scan_for_duplicates(tenant_id)
    flag_id = flags[0]["id"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE duplicate_flag SET resolved_at = NOW() WHERE id = %s", (flag_id,))
        cur.close()

    rescanned = scan_for_duplicates(tenant_id)
    assert rescanned == []  # dismissed pair doesn't come back


# --- Admin endpoints ---

def test_scan_duplicates_requires_admin_not_just_editor():
    tenant_id = _ensure_tenant("test-dup-tenant")
    editor_id = _ensure_admin("dup-editor@example.com")
    _link(tenant_id, editor_id, "editor")

    client = _client()
    _login(client, "test-dup-tenant", "dup-editor@example.com")
    resp = client.post("/t/test-dup-tenant/api/documents/scan-duplicates")
    assert resp.status_code == 403


def test_full_flow_scan_list_resolve():
    tenant_id = _ensure_tenant("test-dup-tenant")
    admin_id = _ensure_admin("dup-admin@example.com")
    _link(tenant_id, admin_id, "admin")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Cancellation Policy")
    _make_document(tenant_id, "Cancelation Policy")

    client = _client()
    _login(client, "test-dup-tenant", "dup-admin@example.com")

    scan_resp = client.post("/t/test-dup-tenant/api/documents/scan-duplicates")
    assert scan_resp.status_code == 200
    new_flags = scan_resp.json()
    assert len(new_flags) == 1
    flag_id = new_flags[0]["id"]

    list_resp = client.get("/t/test-dup-tenant/api/documents/duplicate-flags")
    assert list_resp.status_code == 200
    assert any(f["id"] == flag_id for f in list_resp.json())

    resolve_resp = client.post(f"/t/test-dup-tenant/api/documents/duplicate-flags/{flag_id}/resolve")
    assert resolve_resp.status_code == 200

    after_resolve = client.get("/t/test-dup-tenant/api/documents/duplicate-flags")
    assert all(f["id"] != flag_id for f in after_resolve.json())


def test_resolve_unknown_flag_404s():
    tenant_id = _ensure_tenant("test-dup-tenant")
    admin_id = _ensure_admin("dup-admin2@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-dup-tenant", "dup-admin2@example.com")
    resp = client.post("/t/test-dup-tenant/api/documents/duplicate-flags/999999/resolve")
    assert resp.status_code == 404


def test_viewer_can_list_but_not_resolve():
    tenant_id = _ensure_tenant("test-dup-tenant")
    viewer_id = _ensure_admin("dup-viewer@example.com")
    _link(tenant_id, viewer_id, "viewer")
    _reset_tenant_content(tenant_id)
    _make_document(tenant_id, "Refund Policy")
    _make_document(tenant_id, "Refunds Policy")

    admin_id = _ensure_admin("dup-admin3@example.com")
    _link(tenant_id, admin_id, "admin")
    admin_client = _client()
    _login(admin_client, "test-dup-tenant", "dup-admin3@example.com")
    admin_client.post("/t/test-dup-tenant/api/documents/scan-duplicates")

    viewer_client = _client()
    _login(viewer_client, "test-dup-tenant", "dup-viewer@example.com")
    list_resp = viewer_client.get("/t/test-dup-tenant/api/documents/duplicate-flags")
    assert list_resp.status_code == 200
    flag_id = list_resp.json()[0]["id"]

    resolve_resp = viewer_client.post(f"/t/test-dup-tenant/api/documents/duplicate-flags/{flag_id}/resolve")
    assert resolve_resp.status_code == 403
