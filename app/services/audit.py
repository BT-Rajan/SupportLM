"""Audit logging (Phase 8 — 1.2).

Scoped exactly to what the master prompt names — uploads, edits,
deletes, admin logins — called directly from the handful of endpoints
that perform those actions, not wired in generically.
"""
from fastapi import Request

from app.db.pool import get_conn


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def log_audit_event(
    tenant_id: int,
    admin_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    detail: str | None = None,
    request: Request | None = None,
) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO audit_log (tenant_id, admin_id, action, entity_type, entity_id, detail, ip_address)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (tenant_id, admin_id, action, entity_type, entity_id, detail, _client_ip(request)),
        )
        cur.close()


def get_audit_log(tenant_id: int, days: int = 30) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT al.id, al.action, al.entity_type, al.entity_id, al.detail, al.ip_address,
                      al.created_at, au.email AS admin_email
               FROM audit_log al
               LEFT JOIN admin_user au ON au.id = al.admin_id
               WHERE al.tenant_id = %s AND al.created_at >= NOW() - INTERVAL %s DAY
               ORDER BY al.created_at DESC
               LIMIT 200""",
            (tenant_id, days),
        )
        rows = cur.fetchall()
        cur.close()

    return [
        {
            "id": row["id"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "detail": row["detail"],
            "ip_address": row["ip_address"],
            "created_at": str(row["created_at"]),
            "admin_email": row["admin_email"],  # None if the admin was since deleted
        }
        for row in rows
    ]
