"""Tests for Phase 3 WBS 1.0 — content review workflow. DB-dependent,
skips cleanly without a reachable DB, same pattern as the Phase 2
suite. Retrieval-gating tests insert a fake embedding directly rather
than going through app.services.ingestion's real embedding model, the
same "avoid the network-dependent boundary" choice
test_transcript_email.py already made for ask()/the LLM provider.
"""
import json
import uuid

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


def _clear_documents(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def _make_document(tenant_id: int, status: str, review_state: str, with_embedding: bool = False) -> int:
    """Inserts a document (+ optionally one chunk with a fake unit
    vector embedding) directly via SQL — bypasses
    app.services.ingestion, which calls out to a real embedding model
    not reachable/desired in a unit test."""
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO document (tenant_id, title, filename, raw_markdown, status, review_state)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (tenant_id, f"doc-{uuid.uuid4()}", "t.md", "# hi", status, review_state),
        )
        document_id = cur.lastrowid

        if with_embedding:
            cur.execute(
                "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, content) VALUES (%s, %s, 0, 'hello world')",
                (tenant_id, document_id),
            )
            chunk_id = cur.lastrowid
            cur.execute(
                """INSERT INTO embedding (tenant_id, chunk_id, model, dims, embedding_vector)
                   VALUES (%s, %s, 'test-model', 3, %s)""",
                (tenant_id, chunk_id, json.dumps([1.0, 0.0, 0.0])),
            )
        cur.close()
    return document_id


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


def test_upload_defaults_to_draft():
    tenant_id = _ensure_tenant("test-review-tenant")
    admin_id = _ensure_admin("review-editor@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-review-tenant", "review-editor@example.com")

    resp = client.post(
        "/t/test-review-tenant/api/documents/upload",
        files={"file": ("t.md", b"# hi", "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_state"] == "draft"


def test_retrieval_excludes_unpublished_documents():
    """The actual point of 1.0: a 'ready' but 'draft' document must not
    be retrievable, only 'ready' + 'published' is."""
    from app.services.vector_store import MySQLVectorStore

    tenant_id = _ensure_tenant("test-review-tenant")
    _clear_documents(tenant_id)
    _make_document(tenant_id, status="ready", review_state="draft", with_embedding=True)
    _make_document(tenant_id, status="ready", review_state="review", with_embedding=True)
    published_id = _make_document(tenant_id, status="ready", review_state="published", with_embedding=True)
    _make_document(tenant_id, status="pending", review_state="published", with_embedding=True)  # not ingested yet

    store = MySQLVectorStore()
    results = store.search(tenant_id, query_vector=[1.0, 0.0, 0.0], top_k=10)

    result_doc_ids = {r.document_id for r in results}
    assert result_doc_ids == {published_id}


def test_editor_can_set_review_state_viewer_cannot():
    tenant_id = _ensure_tenant("test-review-tenant")
    editor_id = _ensure_admin("review-editor2@example.com")
    viewer_id = _ensure_admin("review-viewer@example.com")
    _link(tenant_id, editor_id, "editor")
    _link(tenant_id, viewer_id, "viewer")
    doc_id = _make_document(tenant_id, status="ready", review_state="draft")

    viewer_client = _client()
    _login(viewer_client, "test-review-tenant", "review-viewer@example.com")
    resp = viewer_client.post(
        f"/t/test-review-tenant/api/documents/{doc_id}/review-state", json={"state": "published"}
    )
    assert resp.status_code == 403

    editor_client = _client()
    _login(editor_client, "test-review-tenant", "review-editor2@example.com")
    resp = editor_client.post(
        f"/t/test-review-tenant/api/documents/{doc_id}/review-state", json={"state": "published"}
    )
    assert resp.status_code == 200
    assert resp.json()["review_state"] == "published"

    # Editor can also move it straight back to draft — no forced
    # forward-only ordering, per the owner's explicit decision.
    resp = editor_client.post(
        f"/t/test-review-tenant/api/documents/{doc_id}/review-state", json={"state": "draft"}
    )
    assert resp.status_code == 200
    assert resp.json()["review_state"] == "draft"


def test_setting_same_review_state_does_not_404():
    """Regression test: pymysql's UPDATE rowcount reflects rows
    *changed*, not rows *matched* (db/pool.py doesn't set
    CLIENT_FOUND_ROWS). Setting review_state to the value it already
    has updates 0 rows — must still return 200, not a false 404."""
    tenant_id = _ensure_tenant("test-review-tenant")
    admin_id = _ensure_admin("review-editor3@example.com")
    _link(tenant_id, admin_id, "editor")
    doc_id = _make_document(tenant_id, status="ready", review_state="draft")

    client = _client()
    _login(client, "test-review-tenant", "review-editor3@example.com")
    resp = client.post(f"/t/test-review-tenant/api/documents/{doc_id}/review-state", json={"state": "draft"})
    assert resp.status_code == 200
    assert resp.json()["review_state"] == "draft"


def test_invalid_review_state_rejected():
    tenant_id = _ensure_tenant("test-review-tenant")
    admin_id = _ensure_admin("review-editor4@example.com")
    _link(tenant_id, admin_id, "editor")
    doc_id = _make_document(tenant_id, status="ready", review_state="draft")

    client = _client()
    _login(client, "test-review-tenant", "review-editor4@example.com")
    resp = client.post(f"/t/test-review-tenant/api/documents/{doc_id}/review-state", json={"state": "banana"})
    assert resp.status_code == 400


def test_unknown_document_404s():
    tenant_id = _ensure_tenant("test-review-tenant")
    admin_id = _ensure_admin("review-editor5@example.com")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-review-tenant", "review-editor5@example.com")
    resp = client.post("/t/test-review-tenant/api/documents/999999/review-state", json={"state": "published"})
    assert resp.status_code == 404
