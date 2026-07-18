"""Tests for Phase 7 — 1.1/2.2/3.1/4.1: analytics aggregation service.
Requires a reachable, migrated DB — skips cleanly if one isn't
configured.
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


def _reset_tenant_content(tenant_id: int) -> None:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE tenant_id = %s", (tenant_id,))
        cur.execute("DELETE FROM conversation WHERE tenant_id = %s", (tenant_id,))
        cur.close()


class _NormalProvider:
    PROVIDER_NAME = "deepseek"
    model = "deepseek-chat"

    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "a normal, confident answer", "input_tokens": 1000, "output_tokens": 200}


class _EscalatingProvider:
    PROVIDER_NAME = "deepseek"
    model = "deepseek-chat"

    def chat_completion(self, system_prompt, history, user_message):
        return {"content": "I don't know.\n\n[ESCALATE]", "input_tokens": 500, "output_tokens": 50}


def _ask_normal(tenant_id, question, conversation_id=None):
    from app.services.chat import ask

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_NormalProvider()
    ):
        return ask(tenant_id, question, conversation_id)


def _ask_escalating(tenant_id, question, conversation_id=None):
    from app.services.chat import ask

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_EscalatingProvider()
    ):
        return ask(tenant_id, question, conversation_id)


def test_dashboard_counts_conversations_and_answers():
    from app.services.analytics import get_dashboard_data

    tenant_id = _ensure_tenant("pytest-analytics-counts")
    _reset_tenant_content(tenant_id)

    r1 = _ask_normal(tenant_id, "question one")
    _ask_normal(tenant_id, "question two (follow-up)", r1["conversation_id"])
    _ask_normal(tenant_id, "a completely separate conversation")

    data = get_dashboard_data(tenant_id, days=30)

    assert data["conversation_count"] == 2
    assert data["answer_count"] == 3


def test_dashboard_counts_escalations():
    from app.services.analytics import get_dashboard_data

    tenant_id = _ensure_tenant("pytest-analytics-escalations")
    _reset_tenant_content(tenant_id)

    _ask_normal(tenant_id, "a normal question")
    _ask_escalating(tenant_id, "an unanswerable question")
    _ask_escalating(tenant_id, "another unanswerable question")

    data = get_dashboard_data(tenant_id, days=30)

    assert data["escalation_count"] == 2
    assert data["answer_count"] == 3


def test_dashboard_csat_percentage():
    from app.db.pool import get_conn
    from app.services.analytics import get_dashboard_data

    tenant_id = _ensure_tenant("pytest-analytics-csat")
    _reset_tenant_content(tenant_id)

    r1 = _ask_normal(tenant_id, "q1")
    r2 = _ask_normal(tenant_id, "q2")
    r3 = _ask_normal(tenant_id, "q3")

    with get_conn() as conn:
        cur = conn.cursor()
        for message_id, rating in [(r1["message_id"], "up"), (r2["message_id"], "up"), (r3["message_id"], "down")]:
            cur.execute(
                "INSERT INTO message_feedback (tenant_id, message_id, rating) VALUES (%s, %s, %s)",
                (tenant_id, message_id, rating),
            )
        cur.close()

    data = get_dashboard_data(tenant_id, days=30)

    assert data["csat"]["up"] == 2
    assert data["csat"]["down"] == 1
    assert data["csat"]["percentage"] == pytest.approx(66.7, abs=0.1)


def test_dashboard_csat_percentage_none_when_no_votes():
    from app.services.analytics import get_dashboard_data

    tenant_id = _ensure_tenant("pytest-analytics-csat-empty")
    _reset_tenant_content(tenant_id)

    data = get_dashboard_data(tenant_id, days=30)

    assert data["csat"]["percentage"] is None


def test_dashboard_cost_breakdown_and_total():
    from app.services.analytics import get_dashboard_data

    tenant_id = _ensure_tenant("pytest-analytics-cost")
    _reset_tenant_content(tenant_id)

    _ask_normal(tenant_id, "q1")
    _ask_normal(tenant_id, "q2")

    data = get_dashboard_data(tenant_id, days=30)

    assert len(data["cost"]["by_provider_model"]) == 1
    entry = data["cost"]["by_provider_model"][0]
    assert entry["provider"] == "deepseek"
    assert entry["model"] == "deepseek-chat"
    assert entry["input_tokens"] == 2000
    assert entry["output_tokens"] == 400
    assert float(data["cost"]["total_usd"]) > 0


def test_flagged_questions_tags_escalated_reason():
    from app.services.analytics import get_flagged_questions

    tenant_id = _ensure_tenant("pytest-analytics-flagged-escalated")
    _reset_tenant_content(tenant_id)

    result = _ask_escalating(tenant_id, "an unanswerable question")

    flagged = get_flagged_questions(tenant_id, days=30)
    matching = [f for f in flagged if f["message_id"] == result["message_id"]]
    assert len(matching) == 1
    assert "escalated" in matching[0]["reasons"]


def test_non_escalated_confident_answer_not_flagged():
    from app.services.analytics import get_flagged_questions

    tenant_id = _ensure_tenant("pytest-analytics-not-flagged")
    _reset_tenant_content(tenant_id)

    # High similarity result seeded so this message's best citation
    # similarity is well above the low-confidence threshold.
    from app.db.pool import get_conn

    result = _ask_normal(tenant_id, "a confident, well-answered question")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM citation WHERE message_id = %s", (result["message_id"],)
        )
        # No documents seeded for this tenant, so no citations exist at
        # all — best_similarity is NULL, which must NOT be treated as
        # "below threshold" (NULL < 0.3 is NULL/false in SQL, not true).
        cur.close()

    flagged = get_flagged_questions(tenant_id, days=30)
    matching = [f for f in flagged if f["message_id"] == result["message_id"]]
    assert matching == []


def test_flagged_question_count_matches_list_length():
    from app.services.analytics import get_dashboard_data, get_flagged_questions

    tenant_id = _ensure_tenant("pytest-analytics-flagged-count")
    _reset_tenant_content(tenant_id)

    _ask_normal(tenant_id, "fine")
    _ask_escalating(tenant_id, "not fine")
    _ask_escalating(tenant_id, "also not fine")

    dashboard = get_dashboard_data(tenant_id, days=30)
    flagged = get_flagged_questions(tenant_id, days=30)

    assert dashboard["flagged_question_count"] == len(flagged) == 2


def test_tenant_isolation_in_dashboard_data():
    from app.services.analytics import get_dashboard_data

    tenant_a = _ensure_tenant("pytest-analytics-iso-a")
    tenant_b = _ensure_tenant("pytest-analytics-iso-b")
    _reset_tenant_content(tenant_a)
    _reset_tenant_content(tenant_b)

    _ask_normal(tenant_a, "tenant a question 1")
    _ask_normal(tenant_a, "tenant a question 2")
    _ask_normal(tenant_b, "tenant b question 1")

    data_a = get_dashboard_data(tenant_a, days=30)
    data_b = get_dashboard_data(tenant_b, days=30)

    assert data_a["answer_count"] == 2
    assert data_b["answer_count"] == 1
