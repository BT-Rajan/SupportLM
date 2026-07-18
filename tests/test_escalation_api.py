"""Tests for Phase 6 — 3.3/3.4: /api/chat/{message_id}/escalate and
/api/tenant/support-config. Requires a reachable, migrated DB — skips
cleanly if one isn't configured.
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


def _set_support_email(tenant_id: int, email: str | None):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        if email is None:
            cur.execute("DELETE FROM tenant_support_config WHERE tenant_id = %s", (tenant_id,))
        else:
            cur.execute(
                """INSERT INTO tenant_support_config (tenant_id, support_email) VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE support_email = VALUES(support_email)""",
                (tenant_id, email),
            )
        cur.close()


def _client():
    from app.main import app

    return TestClient(app)


def _login(client, slug, email):
    resp = client.post(f"/t/{slug}/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text


class _EscalatingProvider:
    PROVIDER_NAME = "stub"
    model = "stub-model"
    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "I don't know that.\n\n[ESCALATE]", "input_tokens": 10, "output_tokens": 10}


def _ask_and_get_escalating_message(tenant_slug: str) -> tuple:
    client = _client()
    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_EscalatingProvider()
    ):
        resp = client.post(f"/t/{tenant_slug}/api/chat", json={"question": "out of scope"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_escalation"] is True
    return client, body["message_id"]


def test_escalate_endpoint_happy_path():
    tenant_id = _ensure_tenant("test-esc-api-happy")
    _set_support_email(tenant_id, "support@acme.example")
    client, message_id = _ask_and_get_escalating_message("test-esc-api-happy")

    with patch("app.services.escalation._send_email"):
        resp = client.post(
            f"/t/test-esc-api-happy/api/chat/{message_id}/escalate", json={"email": "v@example.com"}
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["sr_number"].startswith("SR-")


def test_escalate_endpoint_unknown_message_404():
    _ensure_tenant("test-esc-api-404")
    client = _client()

    resp = client.post("/t/test-esc-api-404/api/chat/9999999/escalate", json={"email": "v@example.com"})
    assert resp.status_code == 404


def test_escalate_endpoint_duplicate_409():
    tenant_id = _ensure_tenant("test-esc-api-409")
    _set_support_email(tenant_id, "support@acme.example")
    client, message_id = _ask_and_get_escalating_message("test-esc-api-409")

    with patch("app.services.escalation._send_email"):
        first = client.post(
            f"/t/test-esc-api-409/api/chat/{message_id}/escalate", json={"email": "v@example.com"}
        )
        assert first.status_code == 200

        second = client.post(
            f"/t/test-esc-api-409/api/chat/{message_id}/escalate", json={"email": "v2@example.com"}
        )
    assert second.status_code == 409


def test_escalate_endpoint_no_config_400():
    tenant_id = _ensure_tenant("test-esc-api-noconfig")
    _set_support_email(tenant_id, None)
    client, message_id = _ask_and_get_escalating_message("test-esc-api-noconfig")

    resp = client.post(
        f"/t/test-esc-api-noconfig/api/chat/{message_id}/escalate", json={"email": "v@example.com"}
    )
    assert resp.status_code == 400


def test_support_config_requires_admin():
    tenant_id = _ensure_tenant("test-esc-cfg-viewer")
    admin_id = _ensure_admin("esc-cfg-viewer@example.com")
    _link(tenant_id, admin_id, "viewer")

    client = _client()
    _login(client, "test-esc-cfg-viewer", "esc-cfg-viewer@example.com")

    assert client.get("/t/test-esc-cfg-viewer/api/tenant/support-config").status_code == 403
    assert (
        client.post(
            "/t/test-esc-cfg-viewer/api/tenant/support-config", json={"support_email": "x@example.com"}
        ).status_code
        == 403
    )


def test_support_config_rejects_invalid_email():
    tenant_id = _ensure_tenant("test-esc-cfg-invalid")
    admin_id = _ensure_admin("esc-cfg-invalid@example.com")
    _link(tenant_id, admin_id, "admin")

    client = _client()
    _login(client, "test-esc-cfg-invalid", "esc-cfg-invalid@example.com")

    resp = client.post(
        "/t/test-esc-cfg-invalid/api/tenant/support-config", json={"support_email": "not-an-email"}
    )
    assert resp.status_code == 400


def test_support_config_get_set_roundtrip():
    tenant_id = _ensure_tenant("test-esc-cfg-roundtrip")
    admin_id = _ensure_admin("esc-cfg-roundtrip@example.com")
    _link(tenant_id, admin_id, "admin")
    _set_support_email(tenant_id, None)

    client = _client()
    _login(client, "test-esc-cfg-roundtrip", "esc-cfg-roundtrip@example.com")

    assert client.get("/t/test-esc-cfg-roundtrip/api/tenant/support-config").json() is None

    set_resp = client.post(
        "/t/test-esc-cfg-roundtrip/api/tenant/support-config", json={"support_email": "support@acme.example"}
    )
    assert set_resp.status_code == 200

    get_resp = client.get("/t/test-esc-cfg-roundtrip/api/tenant/support-config").json()
    assert get_resp["support_email"] == "support@acme.example"
