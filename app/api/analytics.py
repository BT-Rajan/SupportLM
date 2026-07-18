"""Analytics & Reporting endpoints (Phase 7 — 1.2, 2.3, 5.1)."""
import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.rbac import require_role
from app.db.pool import get_cursor
from app.services.analytics import get_dashboard_data, get_flagged_questions

router = APIRouter(prefix="/api/tenant/analytics", tags=["analytics"])


@router.get("/dashboard")
def dashboard(days: int = 30, tenant_id: int = Depends(require_role("viewer"))):
    """1.2: viewer+ — read-only reporting, same floor as prompt-
    version's list endpoint, not the admin+ floor live-credential
    surfaces need."""
    return get_dashboard_data(tenant_id, days)


@router.get("/flagged-questions")
def flagged_questions(days: int = 30, tenant_id: int = Depends(require_role("viewer"))):
    """2.3: viewer+, same floor as the dashboard — this is reporting,
    not a live-credential or destructive-action surface."""
    return get_flagged_questions(tenant_id, days)


@router.get("/export.csv")
def export_csv(days: int = 30, tenant_id: int = Depends(require_role("admin"))):
    """5.1: admin+ — raw per-message data (including visitor question/
    answer content) is more sensitive than the aggregated dashboard
    numbers above, so this gets the higher floor. One row per assistant
    message, joining citation/feedback/escalation/usage — the natural
    analytics unit this schema already anchors everything else to."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT m.conversation_id, m.id AS message_id, m.created_at,
                      u.provider, u.model, u.input_tokens, u.output_tokens, u.estimated_cost_usd,
                      m.needs_escalation, f.rating AS feedback_rating
               FROM message m
               LEFT JOIN llm_usage_log u ON u.message_id = m.id
               LEFT JOIN message_feedback f ON f.message_id = m.id
               WHERE m.tenant_id = %s AND m.role = 'assistant'
                     AND m.created_at >= NOW() - INTERVAL %s DAY
               ORDER BY m.created_at ASC""",
            (tenant_id, days),
        )
        rows = cur.fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "conversation_id",
            "message_id",
            "created_at",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "estimated_cost_usd",
            "needs_escalation",
            "feedback_rating",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["conversation_id"],
                row["message_id"],
                row["created_at"],
                row["provider"] or "",
                row["model"] or "",
                row["input_tokens"] if row["input_tokens"] is not None else "",
                row["output_tokens"] if row["output_tokens"] is not None else "",
                row["estimated_cost_usd"] if row["estimated_cost_usd"] is not None else "",
                bool(row["needs_escalation"]),
                row["feedback_rating"] or "",
            ]
        )
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=analytics_export.csv"},
    )
