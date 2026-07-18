"""Tests for Phase 7 — 0.3/0.4: ask() persists llm_usage_log correctly
end-to-end. Requires a reachable, migrated DB (023 applied) — skips
cleanly if one isn't configured.
"""
from decimal import Decimal
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


class _KnownUsageProvider:
    PROVIDER_NAME = "deepseek"
    model = "deepseek-chat"

    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "an answer", "input_tokens": 1000, "output_tokens": 500}


class _UnknownModelProvider:
    PROVIDER_NAME = "openai"
    model = "some-brand-new-model-not-in-pricing-table"

    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "an answer", "input_tokens": 100, "output_tokens": 50}


def test_ask_persists_usage_log_with_correct_tokens_and_provider():
    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-usage-basic")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_KnownUsageProvider()
    ):
        result = ask(tenant_id, "a question", None)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM llm_usage_log WHERE message_id = %s", (result["message_id"],))
        row = cur.fetchone()

    assert row is not None
    assert row["tenant_id"] == tenant_id
    assert row["provider"] == "deepseek"
    assert row["model"] == "deepseek-chat"
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 500


def test_ask_computes_correct_estimated_cost_for_known_pricing():
    from app.db.pool import get_conn
    from app.core.llm_pricing import PRICING
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-usage-cost")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_KnownUsageProvider()
    ):
        result = ask(tenant_id, "a question", None)

    rates = PRICING["deepseek"]["deepseek-chat"]
    expected_cost = (Decimal(1000) / 1000) * rates["input_per_1k"] + (Decimal(500) / 1000) * rates["output_per_1k"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT estimated_cost_usd FROM llm_usage_log WHERE message_id = %s", (result["message_id"],)
        )
        row = cur.fetchone()

    assert Decimal(row["estimated_cost_usd"]) == expected_cost


def test_ask_records_zero_cost_for_unknown_model_without_crashing():
    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-usage-unknown-model")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_UnknownModelProvider()
    ):
        result = ask(tenant_id, "a question", None)  # must not raise

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT estimated_cost_usd, input_tokens, output_tokens FROM llm_usage_log WHERE message_id = %s",
            (result["message_id"],),
        )
        row = cur.fetchone()

    assert Decimal(row["estimated_cost_usd"]) == Decimal("0")
    # Tokens are still recorded accurately even though cost couldn't be
    # estimated — only the price lookup failed, not the token capture.
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50


def test_usage_log_is_one_row_per_message():
    """Two separate ask() calls (two separate messages) must each get
    their own usage_log row, not share or overwrite one."""
    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-usage-multiple")

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_KnownUsageProvider()
    ):
        r1 = ask(tenant_id, "first question", None)
        r2 = ask(tenant_id, "second question", r1["conversation_id"])

    assert r1["message_id"] != r2["message_id"]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM llm_usage_log WHERE message_id IN (%s, %s)",
            (r1["message_id"], r2["message_id"]),
        )
        count = cur.fetchone()["c"]

    assert count == 2
