"""Tests for Phase 6 — 1.0 Escalation Detection: the [ESCALATE] marker
is detected, stripped from the visible/stored answer, and surfaced as
`needs_escalation` on ask()'s return dict. Requires a reachable,
migrated DB — skips cleanly if one isn't configured.
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


def test_detect_and_strip_escalation_marker_present():
    from app.services.chat import _detect_and_strip_escalation

    visible, needs = _detect_and_strip_escalation("I don't have that information.\n\n[ESCALATE]")
    assert needs is True
    assert visible == "I don't have that information."
    assert "[ESCALATE]" not in visible


def test_detect_and_strip_escalation_marker_absent():
    from app.services.chat import _detect_and_strip_escalation

    visible, needs = _detect_and_strip_escalation("Here's your answer, all good.")
    assert needs is False
    assert visible == "Here's your answer, all good."


def test_marker_must_be_at_the_very_end():
    """A marker-looking string in the middle of a real answer must NOT
    trigger escalation — only a genuine trailing marker counts."""
    from app.services.chat import _detect_and_strip_escalation

    visible, needs = _detect_and_strip_escalation(
        "The [ESCALATE] button is in the top-right corner of the dashboard."
    )
    assert needs is False
    assert visible == "The [ESCALATE] button is in the top-right corner of the dashboard."


class _EscalatingStubProvider:
    PROVIDER_NAME = "stub"
    model = "stub-model"
    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "I couldn't find anything about that in the documentation.\n\n[ESCALATE]", "input_tokens": 10, "output_tokens": 10}


class _NormalStubProvider:
    PROVIDER_NAME = "stub"
    model = "stub-model"
    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "Here's the answer to your question.", "input_tokens": 10, "output_tokens": 10}


def test_ask_surfaces_needs_escalation_true():
    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-escalation-true")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_EscalatingStubProvider()
    ):
        result = ask(tenant_id, "something totally out of scope", None)

    assert result["needs_escalation"] is True
    assert "[ESCALATE]" not in result["answer"]

    # The marker must never land in the stored message either.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT content FROM message WHERE id = %s", (result["message_id"],))
        row = cur.fetchone()
    assert "[ESCALATE]" not in row["content"]


def test_ask_surfaces_needs_escalation_false():
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-escalation-false")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_NormalStubProvider()
    ):
        result = ask(tenant_id, "a normal question", None)

    assert result["needs_escalation"] is False
    assert result["answer"] == "Here's the answer to your question."


def test_system_prompt_includes_escalation_instruction():
    from app.services.chat import _ESCALATION_MARKER, _ESCALATION_INSTRUCTION

    assert _ESCALATION_MARKER in _ESCALATION_INSTRUCTION


def test_ask_passes_escalation_instruction_to_provider():
    tenant_id = _ensure_tenant("pytest-escalation-instruction")
    captured = {}

    class _CapturingProvider:
        PROVIDER_NAME = "stub"
        model = "stub-model"

        def chat_completion(self, system_prompt, history, user_message):
            captured["system_prompt"] = system_prompt
            return {"content": "an answer", "input_tokens": 10, "output_tokens": 10}

    from app.services.chat import _ESCALATION_MARKER, ask

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_CapturingProvider()
    ):
        ask(tenant_id, "any question", None)

    assert _ESCALATION_MARKER in captured["system_prompt"]
