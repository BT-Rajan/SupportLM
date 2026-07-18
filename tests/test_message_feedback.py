"""Tests for Phase 5 — 3.0 Thumbs Up/Down Feedback: POST
/api/chat/{message_id}/feedback. Requires a reachable, migrated DB (019
applied) — skips cleanly if one isn't configured.
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


class _StubProvider:
    PROVIDER_NAME = "stub"
    model = "stub-model"
    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "stub answer", "input_tokens": 10, "output_tokens": 10}


def _client():
    from app.main import app

    return TestClient(app)


def _ask_and_get_message_id(tenant_slug: str, tenant_id: int) -> tuple:
    """Uses the real /api/chat endpoint (mocking only the provider/
    embedder) so the message_id under test is a real row created the
    same way production traffic creates one."""
    client = _client()
    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_StubProvider()
    ):
        resp = client.post(f"/t/{tenant_slug}/api/chat", json={"question": "test question"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return client, body["message_id"]


def test_up_vote_succeeds():
    tenant_id = _ensure_tenant("test-fb-up")
    client, message_id = _ask_and_get_message_id("test-fb-up", tenant_id)

    resp = client.post(f"/t/test-fb-up/api/chat/{message_id}/feedback", json={"rating": "up"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_down_vote_succeeds():
    tenant_id = _ensure_tenant("test-fb-down")
    client, message_id = _ask_and_get_message_id("test-fb-down", tenant_id)

    resp = client.post(f"/t/test-fb-down/api/chat/{message_id}/feedback", json={"rating": "down"})
    assert resp.status_code == 200


def test_invalid_rating_rejected():
    tenant_id = _ensure_tenant("test-fb-invalid")
    client, message_id = _ask_and_get_message_id("test-fb-invalid", tenant_id)

    resp = client.post(f"/t/test-fb-invalid/api/chat/{message_id}/feedback", json={"rating": "sideways"})
    assert resp.status_code == 400


def test_second_vote_on_same_message_rejected_with_409():
    """The core kickoff decision: no re-voting after the first
    submission."""
    tenant_id = _ensure_tenant("test-fb-revote")
    client, message_id = _ask_and_get_message_id("test-fb-revote", tenant_id)

    first = client.post(f"/t/test-fb-revote/api/chat/{message_id}/feedback", json={"rating": "up"})
    assert first.status_code == 200

    second = client.post(f"/t/test-fb-revote/api/chat/{message_id}/feedback", json={"rating": "down"})
    assert second.status_code == 409


def test_unknown_message_id_returns_404():
    _ensure_tenant("test-fb-404")
    client = _client()

    resp = client.post("/t/test-fb-404/api/chat/999999/feedback", json={"rating": "up"})
    assert resp.status_code == 404


def test_cannot_rate_a_user_message():
    """A visitor can rate the assistant's answer, not their own
    question."""
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("test-fb-usermsg")
    client, _assistant_message_id = _ask_and_get_message_id("test-fb-usermsg", tenant_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM message WHERE tenant_id = %s AND role = 'user' ORDER BY id DESC LIMIT 1",
            (tenant_id,),
        )
        user_message_id = cur.fetchone()["id"]
        cur.close()

    resp = client.post(f"/t/test-fb-usermsg/api/chat/{user_message_id}/feedback", json={"rating": "up"})
    assert resp.status_code == 400


def test_cannot_rate_another_tenants_message():
    """Cross-tenant isolation: tenant B cannot submit feedback on
    tenant A's message_id through tenant B's own URL."""
    tenant_a = _ensure_tenant("test-fb-iso-a")
    _ensure_tenant("test-fb-iso-b")

    client_a, message_id_a = _ask_and_get_message_id("test-fb-iso-a", tenant_a)
    client_b = _client()

    resp = client_b.post(f"/t/test-fb-iso-b/api/chat/{message_id_a}/feedback", json={"rating": "up"})
    assert resp.status_code == 404


def test_ask_response_includes_message_id():
    """Integration: ask()'s returned message_id is a real, usable id —
    the widget needs this to submit feedback at all."""
    from app.services.chat import ask

    tenant_id = _ensure_tenant("test-fb-msgid")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_StubProvider()
    ):
        result = ask(tenant_id, "does this return a message_id?", None)

    assert isinstance(result["message_id"], int)
    assert result["message_id"] > 0
