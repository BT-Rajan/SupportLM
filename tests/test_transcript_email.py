"""Tests for Phase 2 WBS 4.0 — anonymous chat transcript email.
DB-dependent tests skip cleanly without a reachable DB, same pattern
as the rest of the Phase 2 suite. SMTP is never actually contacted:
`_send_email` is monkeypatched to capture the call instead, since no
mail relay is reachable from the test environment.
"""
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


def _make_conversation(tenant_id: int, messages: list[tuple[str, str]]) -> str:
    """messages: list of (role, content). Inserted directly rather
    than via app.services.chat.ask() — ask() calls out to the
    embedding model and the LLM provider, neither reachable/desired in
    a unit test that's only exercising the transcript-email path."""
    from app.db.pool import get_conn

    conversation_id = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conversation (id, tenant_id) VALUES (%s, %s)",
            (conversation_id, tenant_id),
        )
        for role, content in messages:
            cur.execute(
                "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, %s, %s)",
                (tenant_id, conversation_id, role, content),
            )
        cur.close()
    return conversation_id


def test_build_transcript_formats_messages_in_order():
    from app.services.transcript_email import build_transcript

    tenant_id = _ensure_tenant("test-transcript-tenant")
    conv_id = _make_conversation(
        tenant_id, [("user", "How do I reset my password?"), ("assistant", "Click 'forgot password'.")]
    )

    text = build_transcript(tenant_id, conv_id)
    assert "You" in text
    assert "How do I reset my password?" in text
    assert "Assistant" in text
    assert "Click 'forgot password'." in text
    assert text.index("How do I reset my password?") < text.index("Click 'forgot password'.")


def test_build_transcript_rejects_wrong_tenant():
    from app.services.transcript_email import TranscriptEmailError, build_transcript

    tenant_a = _ensure_tenant("test-transcript-tenant-a")
    tenant_b = _ensure_tenant("test-transcript-tenant-b")
    conv_id = _make_conversation(tenant_a, [("user", "hi")])

    with pytest.raises(TranscriptEmailError):
        build_transcript(tenant_b, conv_id)


def test_build_transcript_rejects_empty_conversation():
    from app.db.pool import get_conn
    from app.services.transcript_email import TranscriptEmailError, build_transcript

    tenant_id = _ensure_tenant("test-transcript-tenant")
    conv_id = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO conversation (id, tenant_id) VALUES (%s, %s)", (conv_id, tenant_id))
        cur.close()

    with pytest.raises(TranscriptEmailError):
        build_transcript(tenant_id, conv_id)


def test_send_rejects_invalid_email(monkeypatch):
    from app.core.config import settings
    from app.services.transcript_email import TranscriptEmailError, send_transcript_email

    monkeypatch.setattr(settings, "smtp_host", "localhost")  # configured, so email format is what fails
    tenant_id = _ensure_tenant("test-transcript-tenant")
    conv_id = _make_conversation(tenant_id, [("user", "hi")])

    with pytest.raises(TranscriptEmailError):
        send_transcript_email(tenant_id, conv_id, "not-an-email")


def test_send_fails_loudly_when_smtp_not_configured(monkeypatch):
    from app.core.config import settings
    from app.services.transcript_email import TranscriptEmailError, send_transcript_email

    monkeypatch.setattr(settings, "smtp_host", "")
    tenant_id = _ensure_tenant("test-transcript-tenant")
    conv_id = _make_conversation(tenant_id, [("user", "hi")])

    with pytest.raises(TranscriptEmailError, match="not configured"):
        send_transcript_email(tenant_id, conv_id, "visitor@example.com")


def test_send_success_calls_smtp_and_persists_opt_in(monkeypatch):
    from app.core.config import settings
    from app.db.pool import get_conn
    from app.services import transcript_email

    sent = {}

    def fake_send_email(to_addr, subject, body):
        sent["to"] = to_addr
        sent["subject"] = subject
        sent["body"] = body

    monkeypatch.setattr(transcript_email, "_send_email", fake_send_email)
    monkeypatch.setattr(settings, "smtp_host", "localhost")

    tenant_id = _ensure_tenant("test-transcript-tenant")
    conv_id = _make_conversation(tenant_id, [("user", "hi"), ("assistant", "hello!")])

    transcript_email.send_transcript_email(tenant_id, conv_id, "visitor@example.com", agent_name="TestBot")

    assert sent["to"] == "visitor@example.com"
    assert "TestBot" in sent["subject"]
    assert "hi" in sent["body"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT visitor_email FROM conversation WHERE id = %s", (conv_id,))
        row = cur.fetchone()
    assert row["visitor_email"] == "visitor@example.com"


def test_endpoint_end_to_end(monkeypatch):
    from app.core.config import settings
    from app.main import app
    from app.services import transcript_email

    sent = {}
    monkeypatch.setattr(transcript_email, "_send_email", lambda to, subj, body: sent.update(to=to))
    monkeypatch.setattr(settings, "smtp_host", "localhost")

    tenant_id = _ensure_tenant("test-transcript-tenant")
    conv_id = _make_conversation(tenant_id, [("user", "hi"), ("assistant", "hello!")])

    client = TestClient(app)
    resp = client.post(
        "/t/test-transcript-tenant/api/chat/transcript",
        json={"conversation_id": conv_id, "email": "visitor@example.com"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
    assert sent["to"] == "visitor@example.com"


def test_endpoint_rejects_unknown_conversation(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "localhost")
    _ensure_tenant("test-transcript-tenant")

    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/t/test-transcript-tenant/api/chat/transcript",
        json={"conversation_id": str(uuid.uuid4()), "email": "visitor@example.com"},
    )
    assert resp.status_code == 400
