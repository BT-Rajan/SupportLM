"""Tests for Phase 8 — 3.0 Agent/Bot Configuration UI. Requires a
reachable, migrated DB (027 applied) — skips cleanly if one isn't
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


def _clear_branding(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        cur.close()


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


def test_tone_instruction_helper():
    from app.services.chat import _tone_instruction

    assert _tone_instruction(None) == ""
    text = _tone_instruction("warm and concise")
    assert "warm and concise" in text


def test_resolve_theme_includes_tone_when_set():
    from app.core.theme import resolve_theme

    tenant_id = _ensure_tenant("test-agentcfg-theme")
    _clear_branding(tenant_id)

    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tenant_branding (tenant_id, tone) VALUES (%s, %s)",
            (tenant_id, "cheerful and brief"),
        )
        cur.close()

    theme = resolve_theme(tenant_id)
    assert theme["tone"] == "cheerful and brief"


def test_resolve_theme_tone_defaults_to_none():
    from app.core.theme import resolve_theme

    tenant_id = _ensure_tenant("test-agentcfg-theme-none")
    _clear_branding(tenant_id)

    theme = resolve_theme(tenant_id)
    assert theme["tone"] is None


def test_ask_merges_tone_into_system_prompt():
    from app.services.chat import ask

    tenant_id = _ensure_tenant("test-agentcfg-merge")
    captured = {}

    class _CapturingProvider:
        PROVIDER_NAME = "stub"
        model = "stub-model"

        def chat_completion(self, system_prompt, history, user_message):
            captured["system_prompt"] = system_prompt
            return {"content": "an answer", "input_tokens": 5, "output_tokens": 5}

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_CapturingProvider()
    ):
        ask(tenant_id, "hi", None, tone="playful and full of puns")

    assert "playful and full of puns" in captured["system_prompt"]


def test_agent_config_requires_admin():
    tenant_id = _ensure_tenant("test-agentcfg-viewer")
    admin_id = _ensure_admin("agentcfg-viewer@example.com")
    _link(tenant_id, admin_id, "viewer")

    client = _client()
    _login(client, "test-agentcfg-viewer", "agentcfg-viewer@example.com")

    assert client.get("/t/test-agentcfg-viewer/api/tenant/agent-config").status_code == 403
    assert (
        client.post(
            "/t/test-agentcfg-viewer/api/tenant/agent-config", json={"agent_name": "Ava"}
        ).status_code
        == 403
    )


def test_agent_config_get_set_roundtrip():
    tenant_id = _ensure_tenant("test-agentcfg-roundtrip")
    admin_id = _ensure_admin("agentcfg-roundtrip@example.com")
    _link(tenant_id, admin_id, "admin")
    _clear_branding(tenant_id)

    client = _client()
    _login(client, "test-agentcfg-roundtrip", "agentcfg-roundtrip@example.com")

    empty = client.get("/t/test-agentcfg-roundtrip/api/tenant/agent-config").json()
    assert empty["agent_name"] is None
    assert empty["tone"] is None

    set_resp = client.post(
        "/t/test-agentcfg-roundtrip/api/tenant/agent-config",
        json={"agent_name": "Ava", "tone": "warm and to the point"},
    )
    assert set_resp.status_code == 200

    fetched = client.get("/t/test-agentcfg-roundtrip/api/tenant/agent-config").json()
    assert fetched["agent_name"] == "Ava"
    assert fetched["tone"] == "warm and to the point"


def test_agent_config_end_to_end_via_chat_endpoint():
    """The full path: admin sets tone via the endpoint, a subsequent
    real /api/chat call actually uses it."""
    tenant_id = _ensure_tenant("test-agentcfg-e2e")
    admin_id = _ensure_admin("agentcfg-e2e@example.com")
    _link(tenant_id, admin_id, "admin")
    _clear_branding(tenant_id)

    client = _client()
    _login(client, "test-agentcfg-e2e", "agentcfg-e2e@example.com")
    client.post(
        "/t/test-agentcfg-e2e/api/tenant/agent-config",
        json={"agent_name": "Buddy", "tone": "extremely formal and old-fashioned"},
    )

    captured = {}

    class _CapturingProvider:
        PROVIDER_NAME = "stub"
        model = "stub-model"

        def chat_completion(self, system_prompt, history, user_message):
            captured["system_prompt"] = system_prompt
            return {"content": "Good day to you.", "input_tokens": 5, "output_tokens": 5}

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_CapturingProvider()
    ):
        resp = client.post("/t/test-agentcfg-e2e/api/chat", json={"question": "hello"})

    assert resp.status_code == 200
    assert "extremely formal and old-fashioned" in captured["system_prompt"]
    assert "Buddy" in captured["system_prompt"]
