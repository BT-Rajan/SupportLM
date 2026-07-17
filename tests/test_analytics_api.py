"""Tests for Phase 7 — 1.2/2.3/5.1: /api/tenant/analytics/* endpoints.
Requires a reachable, migrated DB — skips cleanly if one isn't
configured.
"""
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


class _NormalProvider:
    PROVIDER_NAME = "deepseek"
    model = "deepseek-chat"

    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "an answer", "input_tokens": 100, "output_tokens": 50}


def _seed_one_message(tenant_slug):
    client = _client()
    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_NormalProvider()
    ):
        resp = client.post(f"/t/{tenant_slug}/api/chat", json={"question": "hello"})
    assert resp.status_code == 200


def test_dashboard_requires_at_least_viewer():
    _ensure_tenant("test-analytics-noauth")
    client = _client()

    resp = client.get("/t/test-analytics-noauth/api/tenant/analytics/dashboard")
    assert resp.status_code in (401, 403)


def test_viewer_can_read_dashboard_and_flagged_questions():
    tenant_id = _ensure_tenant("test-analytics-viewer")
    admin_id = _ensure_admin("analytics-viewer@example.com")
    _link(tenant_id, admin_id, "viewer")
    _seed_one_message("test-analytics-viewer")

    client = _client()
    _login(client, "test-analytics-viewer", "analytics-viewer@example.com")

    dash = client.get("/t/test-analytics-viewer/api/tenant/analytics/dashboard")
    assert dash.status_code == 200
    assert dash.json()["answer_count"] >= 1

    flagged = client.get("/t/test-analytics-viewer/api/tenant/analytics/flagged-questions")
    assert flagged.status_code == 200
    assert isinstance(flagged.json(), list)


def test_viewer_cannot_export_csv():
    tenant_id = _ensure_tenant("test-analytics-viewer-csv")
    admin_id = _ensure_admin("analytics-viewer-csv@example.com")
    _link(tenant_id, admin_id, "viewer")

    client = _client()
    _login(client, "test-analytics-viewer-csv", "analytics-viewer-csv@example.com")

    resp = client.get("/t/test-analytics-viewer-csv/api/tenant/analytics/export.csv")
    assert resp.status_code == 403


def test_admin_can_export_csv_with_correct_header_row():
    tenant_id = _ensure_tenant("test-analytics-csv")
    admin_id = _ensure_admin("analytics-csv-admin@example.com")
    _link(tenant_id, admin_id, "admin")
    _seed_one_message("test-analytics-csv")

    client = _client()
    _login(client, "test-analytics-csv", "analytics-csv-admin@example.com")

    resp = client.get("/t/test-analytics-csv/api/tenant/analytics/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    lines = resp.text.strip().split("\n")
    header = lines[0]
    assert "conversation_id" in header
    assert "estimated_cost_usd" in header
    assert "feedback_rating" in header
    # At least the header + one seeded message row.
    assert len(lines) >= 2


def test_analytics_data_is_tenant_isolated_via_endpoint():
    tenant_a = _ensure_tenant("test-analytics-iso-a")
    tenant_b = _ensure_tenant("test-analytics-iso-b")
    admin_a = _ensure_admin("analytics-iso-a@example.com")
    admin_b = _ensure_admin("analytics-iso-b@example.com")
    _link(tenant_a, admin_a, "viewer")
    _link(tenant_b, admin_b, "viewer")

    _seed_one_message("test-analytics-iso-a")
    _seed_one_message("test-analytics-iso-a")

    client_b = _client()
    _login(client_b, "test-analytics-iso-b", "analytics-iso-b@example.com")
    dash_b = client_b.get("/t/test-analytics-iso-b/api/tenant/analytics/dashboard").json()

    # Tenant B's own dashboard must not include tenant A's messages.
    assert dash_b["answer_count"] == 0
