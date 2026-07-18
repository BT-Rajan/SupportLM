"""Analytics aggregation (Phase 7 — 1.1, 2.2, 3.1, 4.1).

Every function here is tenant-scoped and date-range-scoped (`days`
back from now) — no cross-tenant leakage, same isolation discipline as
every other query in this codebase.
"""
from decimal import Decimal

from app.db.pool import get_cursor

# Phase 7 — 2.1: assumed, not separately confirmed at kickoff (flagged
# the same way Phase III's cadence assumption was) — a message whose
# best citation similarity falls below this is "low confidence," a
# category distinct from Phase 6's explicit escalation signal.
LOW_CONFIDENCE_THRESHOLD = 0.3


def get_dashboard_data(tenant_id: int, days: int = 30) -> dict:
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM conversation WHERE tenant_id = %s AND started_at >= NOW() - INTERVAL %s DAY",
            (tenant_id, days),
        )
        conversation_count = cur.fetchone()["c"]

        cur.execute(
            """SELECT COUNT(*) AS c FROM message
               WHERE tenant_id = %s AND role = 'assistant' AND created_at >= NOW() - INTERVAL %s DAY""",
            (tenant_id, days),
        )
        answer_count = cur.fetchone()["c"]

        cur.execute(
            """SELECT COUNT(*) AS c FROM message
               WHERE tenant_id = %s AND role = 'assistant' AND needs_escalation = TRUE
                     AND created_at >= NOW() - INTERVAL %s DAY""",
            (tenant_id, days),
        )
        escalation_count = cur.fetchone()["c"]

        cur.execute(
            """SELECT DATE(created_at) AS day, COUNT(*) AS c FROM message
               WHERE tenant_id = %s AND role = 'assistant' AND created_at >= NOW() - INTERVAL %s DAY
               GROUP BY DATE(created_at) ORDER BY day ASC""",
            (tenant_id, days),
        )
        daily_volume = [{"date": str(row["day"]), "count": row["c"]} for row in cur.fetchall()]

        cur.execute(
            """SELECT rating, COUNT(*) AS c FROM message_feedback
               WHERE tenant_id = %s AND created_at >= NOW() - INTERVAL %s DAY
               GROUP BY rating""",
            (tenant_id, days),
        )
        up = down = 0
        for row in cur.fetchall():
            if row["rating"] == "up":
                up = row["c"]
            else:
                down = row["c"]
        total_votes = up + down
        csat_percentage = round((up / total_votes) * 100, 1) if total_votes else None

        cur.execute(
            """SELECT provider, model, SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok,
                      SUM(estimated_cost_usd) AS cost
               FROM llm_usage_log
               WHERE tenant_id = %s AND created_at >= NOW() - INTERVAL %s DAY
               GROUP BY provider, model
               ORDER BY cost DESC""",
            (tenant_id, days),
        )
        cost_breakdown = [
            {
                "provider": row["provider"],
                "model": row["model"],
                "input_tokens": row["in_tok"],
                "output_tokens": row["out_tok"],
                "estimated_cost_usd": str(row["cost"]),
            }
            for row in cur.fetchall()
        ]
        total_cost = sum((Decimal(r["estimated_cost_usd"]) for r in cost_breakdown), Decimal("0"))

        flagged_count = _count_flagged_questions(cur, tenant_id, days)

    return {
        "days": days,
        "conversation_count": conversation_count,
        "answer_count": answer_count,
        "escalation_count": escalation_count,
        "daily_volume": daily_volume,
        "csat": {"up": up, "down": down, "percentage": csat_percentage},
        "cost": {"total_usd": str(total_cost), "by_provider_model": cost_breakdown},
        "flagged_question_count": flagged_count,
    }


def _flagged_questions_query(cur, tenant_id: int, days: int):
    cur.execute(
        """SELECT m.id AS message_id, m.conversation_id, m.content, m.needs_escalation,
                  m.created_at, best.similarity AS best_similarity
           FROM message m
           LEFT JOIN (
               SELECT message_id, MIN(similarity) AS similarity
               FROM citation WHERE rank = 1 GROUP BY message_id
           ) best ON best.message_id = m.id
           WHERE m.tenant_id = %s AND m.role = 'assistant'
                 AND m.created_at >= NOW() - INTERVAL %s DAY
                 AND (m.needs_escalation = TRUE OR best.similarity < %s)
           ORDER BY m.created_at DESC
           LIMIT 100""",
        (tenant_id, days, LOW_CONFIDENCE_THRESHOLD),
    )
    return cur.fetchall()


def _count_flagged_questions(cur, tenant_id: int, days: int) -> int:
    return len(_flagged_questions_query(cur, tenant_id, days))


def get_flagged_questions(tenant_id: int, days: int = 30) -> list[dict]:
    with get_cursor() as cur:
        rows = _flagged_questions_query(cur, tenant_id, days)

    flagged = []
    for row in rows:
        reasons = []
        if row["needs_escalation"]:
            reasons.append("escalated")
        if row["best_similarity"] is not None and row["best_similarity"] < LOW_CONFIDENCE_THRESHOLD:
            reasons.append("low_confidence")
        flagged.append(
            {
                "message_id": row["message_id"],
                "conversation_id": row["conversation_id"],
                "content": row["content"],
                "reasons": reasons,
                "created_at": str(row["created_at"]),
            }
        )
    return flagged
