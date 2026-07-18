"""Tests for Phase 3 WBS 2.0 — website content sync. DB-dependent
tests skip cleanly without a reachable DB. `httpx.get` and
`ingest_document` are both monkeypatched rather than hitting a real
network/embedding model — same "isolate the one I/O boundary" pattern
already used for `_send_email` in transcript_email.py and the direct
SQL fixtures in test_review_workflow.py.
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


def _ensure_admin(email: str, role: str = "admin") -> int:
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
                "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, %s)",
                (email, hash_password("testpass123"), role),
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


def _clear_sync_sources(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_sync_source WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# --- extract_text() ---

def test_extract_text_strips_tags_and_captures_title():
    from app.services.website_sync import extract_text

    html = """
    <html><head><title>Billing FAQ</title><style>.x{color:red}</style></head>
    <body><script>alert(1)</script><h1>Billing</h1><p>How do I update my card?</p></body></html>
    """
    text, title = extract_text(html)
    assert title == "Billing FAQ"
    assert "How do I update my card?" in text
    assert "alert(1)" not in text
    assert "color:red" not in text


# --- sync_source() lifecycle, with httpx and ingest_document mocked ---

def test_sync_source_creates_document_on_first_sync(monkeypatch):
    from app.db.pool import get_conn
    from app.services import website_sync

    ingested_ids = []
    monkeypatch.setattr(website_sync, "ingest_document", lambda doc_id: ingested_ids.append(doc_id))
    monkeypatch.setattr(
        website_sync.httpx, "get",
        lambda url, timeout=None, follow_redirects=None: _FakeResponse("<title>Doc A</title><p>pytest sync content v1</p>"),
    )

    tenant_id = _ensure_tenant("test-sync-tenant")
    _clear_sync_sources(tenant_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, %s)", (tenant_id, "https://example.com/a"))
        source_id = cur.lastrowid
        cur.close()

    status = website_sync.sync_source(tenant_id, source_id)
    assert status == "ingested"
    assert len(ingested_ids) == 1

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT document_id, last_content_hash FROM tenant_sync_source WHERE id = %s", (source_id,))
        row = cur.fetchone()
        cur.execute("SELECT title, review_state FROM document WHERE id = %s", (row["document_id"],))
        doc = cur.fetchone()
        cur.close()
    assert row["document_id"] is not None
    assert row["last_content_hash"] is not None
    assert doc["title"] == "Doc A"
    assert doc["review_state"] == "draft"


def test_sync_source_unchanged_content_is_noop(monkeypatch):
    from app.db.pool import get_conn
    from app.services import website_sync

    ingested_ids = []
    monkeypatch.setattr(website_sync, "ingest_document", lambda doc_id: ingested_ids.append(doc_id))
    monkeypatch.setattr(
        website_sync.httpx, "get",
        lambda url, timeout=None, follow_redirects=None: _FakeResponse("<title>Doc B</title><p>pytest sync content stable</p>"),
    )

    tenant_id = _ensure_tenant("test-sync-tenant")
    _clear_sync_sources(tenant_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, %s)", (tenant_id, "https://example.com/b"))
        source_id = cur.lastrowid
        cur.close()

    first = website_sync.sync_source(tenant_id, source_id)
    second = website_sync.sync_source(tenant_id, source_id)

    assert first == "ingested"
    assert second == "unchanged"
    assert len(ingested_ids) == 1  # not re-ingested the second time


def test_sync_source_changed_content_updates_same_document_and_resets_to_draft(monkeypatch):
    """A content change on an already-published synced document must
    reset it to 'draft' — live content silently changing without
    re-review would defeat 1.0's review workflow."""
    from app.db.pool import get_conn
    from app.services import website_sync

    monkeypatch.setattr(website_sync, "ingest_document", lambda doc_id: None)

    tenant_id = _ensure_tenant("test-sync-tenant")
    _clear_sync_sources(tenant_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, %s)", (tenant_id, "https://example.com/c"))
        source_id = cur.lastrowid
        cur.close()

    monkeypatch.setattr(
        website_sync.httpx, "get",
        lambda url, timeout=None, follow_redirects=None: _FakeResponse("<title>Doc C</title><p>version one</p>"),
    )
    website_sync.sync_source(tenant_id, source_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT document_id FROM tenant_sync_source WHERE id = %s", (source_id,))
        first_doc_id = cur.fetchone()["document_id"]
        cur.execute("UPDATE document SET review_state = 'published' WHERE id = %s", (first_doc_id,))
        cur.close()

    monkeypatch.setattr(
        website_sync.httpx, "get",
        lambda url, timeout=None, follow_redirects=None: _FakeResponse("<title>Doc C</title><p>version two, changed</p>"),
    )
    status = website_sync.sync_source(tenant_id, source_id)
    assert status == "ingested"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT document_id FROM tenant_sync_source WHERE id = %s", (source_id,))
        second_doc_id = cur.fetchone()["document_id"]
        cur.execute("SELECT raw_markdown, review_state FROM document WHERE id = %s", (second_doc_id,))
        doc = cur.fetchone()
        cur.close()

    assert second_doc_id == first_doc_id  # same document, updated in place — not a duplicate
    assert "version two" in doc["raw_markdown"]
    assert doc["review_state"] == "draft"  # reset, even though it had been published


def test_sync_all_sources_continues_past_one_failure(monkeypatch):
    from app.db.pool import get_conn
    from app.services import website_sync

    monkeypatch.setattr(website_sync, "ingest_document", lambda doc_id: None)

    def fake_get(url, timeout=None, follow_redirects=None):
        if "broken" in url:
            raise Exception("connection refused")
        return _FakeResponse("<title>OK</title><p>pytest batch sync content</p>")

    monkeypatch.setattr(website_sync.httpx, "get", fake_get)

    tenant_id = _ensure_tenant("test-sync-tenant")
    _clear_sync_sources(tenant_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, 'https://example.com/broken')", (tenant_id,))
        cur.execute("INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, 'https://example.com/fine')", (tenant_id,))
        cur.close()

    results = website_sync.sync_all_sources(tenant_id)
    statuses = {r["url"]: r["status"] for r in results}
    assert statuses["https://example.com/broken"].startswith("error")
    assert statuses["https://example.com/fine"] == "ingested"


# --- Admin endpoints ---

def test_add_sync_source_rejects_non_http_url():
    tenant_id = _ensure_tenant("test-sync-tenant")
    admin_id = _ensure_admin("sync-editor@example.com", "admin")
    _link(tenant_id, admin_id, "editor")

    client = _client()
    _login(client, "test-sync-tenant", "sync-editor@example.com")
    resp = client.post("/t/test-sync-tenant/api/documents/sync-sources", json={"url": "ftp://example.com"})
    assert resp.status_code == 400


def test_add_sync_source_rejects_duplicate_url():
    tenant_id = _ensure_tenant("test-sync-tenant")
    admin_id = _ensure_admin("sync-editor2@example.com", "admin")
    _link(tenant_id, admin_id, "editor")
    _clear_sync_sources(tenant_id)

    client = _client()
    _login(client, "test-sync-tenant", "sync-editor2@example.com")
    first = client.post("/t/test-sync-tenant/api/documents/sync-sources", json={"url": "https://example.com/dup"})
    assert first.status_code == 200
    second = client.post("/t/test-sync-tenant/api/documents/sync-sources", json={"url": "https://example.com/dup"})
    assert second.status_code == 400


def test_viewer_cannot_add_source_but_can_list():
    tenant_id = _ensure_tenant("test-sync-tenant")
    viewer_id = _ensure_admin("sync-viewer@example.com", "admin")
    _link(tenant_id, viewer_id, "viewer")

    client = _client()
    _login(client, "test-sync-tenant", "sync-viewer@example.com")
    add_resp = client.post("/t/test-sync-tenant/api/documents/sync-sources", json={"url": "https://example.com/x"})
    assert add_resp.status_code == 403
    list_resp = client.get("/t/test-sync-tenant/api/documents/sync-sources")
    assert list_resp.status_code == 200


def test_sync_now_requires_admin_not_just_editor():
    tenant_id = _ensure_tenant("test-sync-tenant")
    editor_id = _ensure_admin("sync-editor3@example.com", "admin")
    _link(tenant_id, editor_id, "editor")

    client = _client()
    _login(client, "test-sync-tenant", "sync-editor3@example.com")
    resp = client.post("/t/test-sync-tenant/api/documents/sync-sources/sync-now")
    assert resp.status_code == 403


def test_delete_sync_source_does_not_delete_its_document(monkeypatch):
    from app.db.pool import get_conn
    from app.services import website_sync

    monkeypatch.setattr(website_sync, "ingest_document", lambda doc_id: None)
    monkeypatch.setattr(
        website_sync.httpx, "get",
        lambda url, timeout=None, follow_redirects=None: _FakeResponse("<title>Keep me</title><p>pytest content</p>"),
    )

    tenant_id = _ensure_tenant("test-sync-tenant")
    admin_id = _ensure_admin("sync-admin@example.com", "admin")
    _link(tenant_id, admin_id, "admin")
    _clear_sync_sources(tenant_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, 'https://example.com/keep')", (tenant_id,))
        source_id = cur.lastrowid
        cur.close()
    website_sync.sync_source(tenant_id, source_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT document_id FROM tenant_sync_source WHERE id = %s", (source_id,))
        document_id = cur.fetchone()["document_id"]
        cur.close()

    client = _client()
    _login(client, "test-sync-tenant", "sync-admin@example.com")
    resp = client.delete(f"/t/test-sync-tenant/api/documents/sync-sources/{source_id}")
    assert resp.status_code == 200

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM document WHERE id = %s", (document_id,))
        still_there = cur.fetchone()
        cur.close()
    assert still_there is not None
