"""Tests for Phase 6 — 3.0 Dual Email Notification: complete_escalation()
service logic. Requires a reachable, migrated DB (020/021/022 applied)
— skips cleanly if one isn't configured.
"""
from unittest.mock import patch

import pytest

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


def _make_escalating_message(tenant_id: int) -> tuple:
    """Real conversation + escalating assistant message, via ask()
    with an escalating stub provider — the same real path production
    traffic uses."""
    from app.services.chat import ask

    class _EscalatingProvider:
        def chat_completion(self, system_prompt, history, user_message):
            return "I don't have information on that.\n\n[ESCALATE]"

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_EscalatingProvider()
    ):
        result = ask(tenant_id, "something out of scope", None)
    assert result["needs_escalation"] is True
    return result["conversation_id"], result["message_id"]


def _make_normal_message(tenant_id: int) -> tuple:
    from app.services.chat import ask

    class _NormalProvider:
        def chat_completion(self, system_prompt, history, user_message):
            return "Here's a normal answer."

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_NormalProvider()
    ):
        result = ask(tenant_id, "a normal question", None)
    assert result["needs_escalation"] is False
    return result["conversation_id"], result["message_id"]


def test_invalid_email_rejected():
    from app.services.escalation import EscalationError, complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-bademail")
    _set_support_email(tenant_id, "support@acme.example")
    _, message_id = _make_escalating_message(tenant_id)

    with pytest.raises(EscalationError, match="valid email"):
        complete_escalation(tenant_id, message_id, "not-an-email")


def test_unknown_message_id_rejected():
    from app.services.escalation import EscalationError, complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-unknown")
    _set_support_email(tenant_id, "support@acme.example")

    with pytest.raises(EscalationError, match="not found"):
        complete_escalation(tenant_id, 9999999, "visitor@example.com")


def test_message_that_never_signaled_escalation_rejected():
    from app.services.escalation import EscalationError, complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-normal-msg")
    _set_support_email(tenant_id, "support@acme.example")
    _, message_id = _make_normal_message(tenant_id)

    with pytest.raises(EscalationError, match="did not trigger"):
        complete_escalation(tenant_id, message_id, "visitor@example.com")


def test_no_support_config_rejected_without_creating_sr():
    from app.db.pool import get_conn
    from app.services.escalation import EscalationError, complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-noconfig")
    _set_support_email(tenant_id, None)
    _, message_id = _make_escalating_message(tenant_id)

    with pytest.raises(EscalationError, match="isn't available"):
        complete_escalation(tenant_id, message_id, "visitor@example.com")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM service_request WHERE message_id = %s", (message_id,))
        assert cur.fetchone() is None


def test_successful_escalation_sends_both_emails_and_persists_sr():
    from app.db.pool import get_conn
    from app.services.escalation import complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-success")
    _set_support_email(tenant_id, "support@acme.example")
    _, message_id = _make_escalating_message(tenant_id)

    sent_emails = []

    def _fake_send(to_addr, subject, body):
        sent_emails.append({"to": to_addr, "subject": subject, "body": body})

    with patch("app.services.escalation._send_email", side_effect=_fake_send):
        result = complete_escalation(tenant_id, message_id, "visitor@example.com")

    assert result["sr_number"].startswith("SR-")
    recipients = {e["to"] for e in sent_emails}
    assert recipients == {"support@acme.example", "visitor@example.com"}
    for e in sent_emails:
        assert result["sr_number"] in e["subject"]
        assert result["sr_number"] in e["body"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT sr_number, visitor_email, tenant_id FROM service_request WHERE message_id = %s",
            (message_id,),
        )
        row = cur.fetchone()
    assert row["sr_number"] == result["sr_number"]
    assert row["visitor_email"] == "visitor@example.com"
    assert row["tenant_id"] == tenant_id


def test_second_escalation_attempt_on_same_message_rejected():
    from app.services.escalation import EscalationError, complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-duplicate")
    _set_support_email(tenant_id, "support@acme.example")
    _, message_id = _make_escalating_message(tenant_id)

    with patch("app.services.escalation._send_email"):
        complete_escalation(tenant_id, message_id, "visitor@example.com")

    with pytest.raises(EscalationError, match="already been created|already created"):
        complete_escalation(tenant_id, message_id, "visitor2@example.com")


def test_failed_email_send_does_not_persist_sr_allowing_retry():
    """The documented tradeoff in escalation.py: a failed send must not
    leave a stale row blocking every future attempt for this
    message_id."""
    from app.db.pool import get_conn
    from app.services.escalation import complete_escalation

    tenant_id = _ensure_tenant("pytest-esc-retry")
    _set_support_email(tenant_id, "support@acme.example")
    _, message_id = _make_escalating_message(tenant_id)

    with patch("app.services.escalation._send_email", side_effect=RuntimeError("SMTP down")):
        with pytest.raises(RuntimeError):
            complete_escalation(tenant_id, message_id, "visitor@example.com")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM service_request WHERE message_id = %s", (message_id,))
        assert cur.fetchone() is None

    # Retry with SMTP "recovered" now succeeds — not blocked by the
    # earlier failed attempt.
    with patch("app.services.escalation._send_email"):
        result = complete_escalation(tenant_id, message_id, "visitor@example.com")
    assert result["sr_number"].startswith("SR-")


def test_cross_tenant_message_id_rejected():
    from app.services.escalation import EscalationError, complete_escalation

    tenant_a = _ensure_tenant("pytest-esc-iso-a")
    tenant_b = _ensure_tenant("pytest-esc-iso-b")
    _set_support_email(tenant_a, "support-a@acme.example")
    _set_support_email(tenant_b, "support-b@acme.example")
    _, message_id_a = _make_escalating_message(tenant_a)

    with pytest.raises(EscalationError, match="not found"):
        complete_escalation(tenant_b, message_id_a, "visitor@example.com")
