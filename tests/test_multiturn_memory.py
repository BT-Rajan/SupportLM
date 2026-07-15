"""Tests for Phase 5 — 1.0 Multi-turn Memory: full conversation history
fetched and folded into both retrieval and the answer call. Requires a
reachable, migrated DB — skips cleanly if one isn't configured, same
pattern as test_hybrid_search.py.
"""
import json
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


def _reset_tenant_content(tenant_id: int) -> None:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE tenant_id = %s", (tenant_id,))
        cur.close()


class _StubProvider:
    """Captures exactly what ask() passed to chat_completion, for
    assertions on the history/system_prompt/user_message it received."""

    def __init__(self):
        self.calls = []

    def chat_completion(self, system_prompt, history, user_message):
        self.calls.append({"system_prompt": system_prompt, "history": history, "user_message": user_message})
        return f"stub answer #{len(self.calls)}"


def test_first_turn_has_empty_history():
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-mtm-first-turn")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        ask(tenant_id, "hello, first question", None)

    assert stub.calls[0]["history"] == []


def test_second_turn_includes_first_turn_in_history():
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-mtm-second-turn")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        result1 = ask(tenant_id, "what is your return policy?", None)
        conv_id = result1["conversation_id"]
        ask(tenant_id, "and how long do I have?", conv_id)

    # Second call's history must include the first turn's user question
    # and the (stub) assistant answer that was actually stored.
    second_call_history = stub.calls[1]["history"]
    roles_and_content = [(h["role"], h["content"]) for h in second_call_history]
    assert ("user", "what is your return policy?") in roles_and_content
    assert ("assistant", "stub answer #1") in roles_and_content


def test_history_is_ordered_oldest_first():
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-mtm-order")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        r1 = ask(tenant_id, "first message", None)
        conv_id = r1["conversation_id"]
        ask(tenant_id, "second message", conv_id)
        ask(tenant_id, "third message", conv_id)

    third_call_history = stub.calls[2]["history"]
    user_contents_in_order = [h["content"] for h in third_call_history if h["role"] == "user"]
    assert user_contents_in_order == ["first message", "second message"]


def test_retrieval_query_folds_in_full_transcript():
    """embed_text() must be called with a string that includes prior
    turns, not just the bare latest question, once there's history."""
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-mtm-retrieval-fold")
    stub = _StubProvider()
    captured_embed_calls = []

    def _fake_embed(text):
        captured_embed_calls.append(text)
        return [0.1, 0.2, 0.3]

    with patch("app.services.chat.embed_text", side_effect=_fake_embed), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        r1 = ask(tenant_id, "UNIQUE_MARKER_FIRST_QUESTION", None)
        conv_id = r1["conversation_id"]
        ask(tenant_id, "UNIQUE_MARKER_SECOND_QUESTION", conv_id)

    # First turn: no history yet, so the embedded text is just the
    # question itself (no transcript prefix).
    assert captured_embed_calls[0] == "UNIQUE_MARKER_FIRST_QUESTION"
    # Second turn: the first turn's question AND the stub's first
    # answer must both appear in what got embedded for retrieval.
    assert "UNIQUE_MARKER_FIRST_QUESTION" in captured_embed_calls[1]
    assert "stub answer #1" in captured_embed_calls[1]
    assert "UNIQUE_MARKER_SECOND_QUESTION" in captured_embed_calls[1]


def test_cross_tenant_conversation_id_never_leaks_history():
    """Reusing another tenant's conversation_id must not pull that
    tenant's messages into this tenant's history — same isolation rule
    as every other cross-tenant guard in this codebase."""
    from app.services.chat import ask

    tenant_a = _ensure_tenant("pytest-mtm-iso-a")
    tenant_b = _ensure_tenant("pytest-mtm-iso-b")
    stub = _StubProvider()

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=stub
    ):
        result_a = ask(tenant_a, "tenant A's secret question", None)
        conv_id_a = result_a["conversation_id"]

        # Tenant B reuses tenant A's conversation_id.
        ask(tenant_b, "tenant B's question, reusing A's conversation_id", conv_id_a)

    # The call made "as tenant B" must have empty history — A's
    # conversation_id must have been rejected, not honored.
    tenant_b_call_history = stub.calls[1]["history"]
    assert tenant_b_call_history == []
    assert all("tenant A" not in h["content"] for h in tenant_b_call_history)
