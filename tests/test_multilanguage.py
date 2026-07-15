"""Tests for Phase 5 — 2.0 Multi-language Support: language resolution,
system-prompt enforcement, persistence on `conversation.language`, and
mid-conversation switching. Requires a reachable, migrated DB (018
applied) — skips cleanly if one isn't configured.
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


class _StubProvider:
    def __init__(self):
        self.calls = []

    def chat_completion(self, system_prompt, history, user_message):
        self.calls.append({"system_prompt": system_prompt})
        return f"stub answer #{len(self.calls)}"


def test_language_instruction_known_code():
    from app.services.chat import _language_instruction

    text = _language_instruction("es")
    assert "Spanish" in text
    assert "regardless of what" in text


def test_language_instruction_unknown_code_falls_back_to_raw_code():
    from app.services.chat import _language_instruction

    text = _language_instruction("xx")
    assert "xx" in text


def test_language_instruction_none_is_empty_string():
    from app.services.chat import _language_instruction

    assert _language_instruction(None) == ""


def test_no_language_selected_means_no_instruction_appended():
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-lang-none")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        ask(tenant_id, "hello", None, language=None)

    assert "Respond only in" not in stub.calls[0]["system_prompt"]


def test_language_selected_on_first_turn_appends_instruction_and_persists():
    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-lang-first-turn")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        result = ask(tenant_id, "hola, necesito ayuda", None, language="es")

    assert "Spanish" in stub.calls[0]["system_prompt"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT language FROM conversation WHERE id = %s", (result["conversation_id"],))
        row = cur.fetchone()
    assert row["language"] == "es"


def test_second_turn_without_language_reuses_stored_language():
    """A follow-up request that doesn't resend `language` must still
    get the conversation's already-stored language enforced."""
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-lang-reuse")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        r1 = ask(tenant_id, "first question", None, language="fr")
        conv_id = r1["conversation_id"]
        ask(tenant_id, "follow-up with no language field sent", conv_id, language=None)

    assert "French" in stub.calls[0]["system_prompt"]
    assert "French" in stub.calls[1]["system_prompt"]


def test_switching_language_mid_conversation_updates_going_forward():
    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-lang-switch")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        r1 = ask(tenant_id, "first in english", None, language="en")
        conv_id = r1["conversation_id"]
        ask(tenant_id, "switching to arabic now", conv_id, language="ar")
        ask(tenant_id, "third turn, no language field sent", conv_id, language=None)

    assert "English" in stub.calls[0]["system_prompt"]
    assert "Arabic" in stub.calls[1]["system_prompt"]
    # Third turn didn't resend a language — must keep using the most
    # recently selected one (Arabic), not revert to the first (English).
    assert "Arabic" in stub.calls[2]["system_prompt"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT language FROM conversation WHERE id = %s", (conv_id,))
        row = cur.fetchone()
    assert row["language"] == "ar"


def test_cross_tenant_conversation_id_does_not_leak_language():
    from app.services.chat import ask

    tenant_a = _ensure_tenant("pytest-lang-iso-a")
    tenant_b = _ensure_tenant("pytest-lang-iso-b")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        result_a = ask(tenant_a, "tenant A question", None, language="ja")
        conv_id_a = result_a["conversation_id"]

        # Tenant B reuses tenant A's conversation_id, sends no language.
        ask(tenant_b, "tenant B question", conv_id_a, language=None)

    # Tenant B's call must NOT have picked up tenant A's Japanese
    # selection — the conversation_id gets rejected as cross-tenant,
    # same as history/isolation elsewhere.
    assert "Japanese" not in stub.calls[1]["system_prompt"]
