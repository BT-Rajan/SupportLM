"""Tests for WBS 3.2: every existing query retrofitted to filter by
tenant_id. Complements test_tenant_resolution.py, which only tests the
*gate* (can a request reach a handler at all) — these tests confirm
that once past the gate, queries actually return/affect only the
resolved tenant's rows. Requires a reachable, migrated DB — skips
cleanly if one isn't configured."""
import json
from unittest.mock import patch

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


def _ensure_tenant(slug: str, status: str = "active") -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, %s)", (slug, slug, status)
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


def _ensure_admin_linked(email: str, password: str, tenant_id: int) -> int:
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
                "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'owner')",
                (email, hash_password(password)),
            )
            admin_id = cur.lastrowid
        cur.execute(
            "INSERT IGNORE INTO tenant_user (tenant_id, admin_id, role) VALUES (%s, %s, 'owner')",
            (tenant_id, admin_id),
        )
        cur.close()
    return admin_id


def test_vector_store_search_only_returns_own_tenant_chunks():
    """The core bug this round exists to fix: identical-content chunks
    in two tenants must never cross over in search results."""
    from app.db.pool import get_conn
    from app.services.vector_store import MySQLVectorStore

    tenant_a = _ensure_tenant("pytest-iso-a")
    tenant_b = _ensure_tenant("pytest-iso-b")

    with get_conn() as conn:
        cur = conn.cursor()
        for tenant_id, label in [(tenant_a, "A"), (tenant_b, "B")]:
            cur.execute(
                "INSERT INTO document (tenant_id, title, filename, raw_markdown, status) "
                "VALUES (%s, %s, %s, %s, 'ready')",
                (tenant_id, f"Doc {label}", f"{label.lower()}.md", "# x"),
            )
            doc_id = cur.lastrowid
            cur.execute(
                "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, heading_path, "
                "content, token_count) VALUES (%s, %s, 0, %s, %s, 10)",
                (tenant_id, doc_id, f"Section {label}", f"pytest secret content tenant {label}"),
            )
            chunk_id = cur.lastrowid
            cur.execute(
                "INSERT INTO embedding (tenant_id, chunk_id, model, dims, embedding_vector) "
                "VALUES (%s, %s, 'test', 3, %s)",
                (tenant_id, chunk_id, json.dumps([1.0, 0.0, 0.0])),
            )
        cur.close()

    store = MySQLVectorStore()
    results_a = store.search(tenant_a, [1.0, 0.0, 0.0], top_k=5)
    results_b = store.search(tenant_b, [1.0, 0.0, 0.0], top_k=5)

    assert all("tenant A" in r.content for r in results_a)
    assert all("tenant B" in r.content for r in results_b)
    assert not any("tenant B" in r.content for r in results_a)
    assert not any("tenant A" in r.content for r in results_b)


def test_ingest_document_threads_tenant_id_onto_chunks_and_embeddings():
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-ingest")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO document (tenant_id, title, filename, raw_markdown, status) "
            "VALUES (%s, 'Ingest Test', 'ingest.md', '# Setup\\n\\nContent.', 'pending')",
            (tenant_id,),
        )
        doc_id = cur.lastrowid
        cur.close()

    with patch("app.services.ingestion.embed_text", return_value=[0.1, 0.2, 0.3]):
        from app.services.ingestion import ingest_document

        ingest_document(doc_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status FROM document WHERE id = %s", (doc_id,))
        assert cur.fetchone()["status"] == "ready"
        cur.execute("SELECT tenant_id FROM document_chunk WHERE document_id = %s", (doc_id,))
        chunk_rows = cur.fetchall()
        assert chunk_rows and all(r["tenant_id"] == tenant_id for r in chunk_rows)
        cur.execute(
            "SELECT e.tenant_id FROM embedding e JOIN document_chunk dc ON dc.id = e.chunk_id "
            "WHERE dc.document_id = %s",
            (doc_id,),
        )
        embedding_rows = cur.fetchall()
        assert embedding_rows and all(r["tenant_id"] == tenant_id for r in embedding_rows)
        cur.close()


def test_document_and_category_routes_are_cross_tenant_isolated():
    from app.db.pool import get_conn
    from app.main import app

    tenant_x = _ensure_tenant("pytest-query-x")
    tenant_y = _ensure_tenant("pytest-query-y")
    _ensure_admin_linked("pytest-query-x@test.com", "pass123", tenant_x)
    _ensure_admin_linked("pytest-query-y@test.com", "pass123", tenant_y)

    # Clean up this test's own fixture rows from any previous run so
    # re-running against the same DB doesn't collide with the
    # per-tenant unique slug constraint added in 1.4.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM category WHERE tenant_id = %s AND slug = 'pytest-x-only'", (tenant_x,))
        cur.execute("DELETE FROM document WHERE tenant_id = %s AND filename = 'secret.md'", (tenant_x,))
        cur.close()

    client_x = TestClient(app)
    client_y = TestClient(app)
    client_x.post("/t/pytest-query-x/api/auth/login", json={"email": "pytest-query-x@test.com", "password": "pass123"})
    client_y.post("/t/pytest-query-y/api/auth/login", json={"email": "pytest-query-y@test.com", "password": "pass123"})

    # Categories: created in X, invisible to Y, undeletable by Y via id-guessing.
    cat = client_x.post("/t/pytest-query-x/api/categories", json={"name": "Pytest X Only"})
    assert cat.status_code == 200
    cat_id = cat.json()["id"]

    assert any(c["id"] == cat_id for c in client_x.get("/t/pytest-query-x/api/categories").json())
    assert not any(c["id"] == cat_id for c in client_y.get("/t/pytest-query-y/api/categories").json())
    assert client_y.delete(f"/t/pytest-query-y/api/categories/{cat_id}").status_code == 404
    assert any(c["id"] == cat_id for c in client_x.get("/t/pytest-query-x/api/categories").json())

    # Documents: uploaded in X, invisible to Y, un-reindexable/undeletable by Y.
    with patch("app.services.ingestion.embed_text", return_value=[0.1, 0.2, 0.3]):
        upload = client_x.post(
            "/t/pytest-query-x/api/documents/upload",
            files={"file": ("secret.md", b"# Secret\n\nX only.", "text/markdown")},
        )
    assert upload.status_code == 200
    doc_id = upload.json()["id"]

    assert any(d["id"] == doc_id for d in client_x.get("/t/pytest-query-x/api/documents").json())
    assert not any(d["id"] == doc_id for d in client_y.get("/t/pytest-query-y/api/documents").json())
    assert client_y.post(f"/t/pytest-query-y/api/documents/{doc_id}/reindex").status_code == 404
    assert client_y.delete(f"/t/pytest-query-y/api/documents/{doc_id}").status_code == 404
    assert any(d["id"] == doc_id for d in client_x.get("/t/pytest-query-x/api/documents").json())

    # Uploading against another tenant's category_id is rejected outright.
    with patch("app.services.ingestion.embed_text", return_value=[0.1, 0.2, 0.3]):
        bad = client_y.post(
            f"/t/pytest-query-y/api/documents/upload?category_id={cat_id}",
            files={"file": ("bad.md", b"# Bad", "text/markdown")},
        )
    assert bad.status_code == 400


def test_ask_rejects_cross_tenant_conversation_id_reuse():
    from app.services.chat import ask

    tenant_p = _ensure_tenant("pytest-chat-p")
    tenant_q = _ensure_tenant("pytest-chat-q")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.chat_completion", return_value="mocked"
    ):
        result_p = ask(tenant_p, "hello from P", None)
        conv_id_p = result_p["conversation_id"]

        result_q = ask(tenant_q, "hello from Q, reusing P's conversation_id", conv_id_p)
        conv_id_q = result_q["conversation_id"]

    assert conv_id_q != conv_id_p

    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT tenant_id FROM conversation WHERE id = %s", (conv_id_p,))
        assert cur.fetchone()["tenant_id"] == tenant_p
        cur.execute("SELECT tenant_id FROM conversation WHERE id = %s", (conv_id_q,))
        assert cur.fetchone()["tenant_id"] == tenant_q
        cur.execute(
            "SELECT COUNT(*) AS n FROM message WHERE conversation_id = %s AND tenant_id != %s",
            (conv_id_p, tenant_p),
        )
        assert cur.fetchone()["n"] == 0
        cur.close()

    # Same-tenant continuation must still work.
    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.chat_completion", return_value="mocked follow-up"
    ):
        result_p2 = ask(tenant_p, "follow-up from P", conv_id_p)
    assert result_p2["conversation_id"] == conv_id_p
