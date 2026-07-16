"""Service Request generation (Phase 6 — 2.0).

`generate_sr_number()` is the one piece of this file usable on its own
before 3.0's full escalation-completion flow exists — split out so it
can be tested (and, later, called from the completion endpoint)
independently of the email-sending machinery.
"""
from datetime import date

from app.db.pool import get_conn


def generate_sr_number(tenant_id: int) -> str:
    """SR-{YYYYMMDD}-{4-digit, per-tenant-per-day sequence}. The
    INSERT ... ON DUPLICATE KEY UPDATE + read-back is atomic under
    InnoDB row locking — safe under concurrent escalations for the
    same tenant on the same day, unlike a COUNT(*) + 1 against
    service_request (see migration 020's header comment)."""
    today = date.today()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO sr_sequence (tenant_id, seq_date, next_seq) VALUES (%s, %s, 1)
               ON DUPLICATE KEY UPDATE next_seq = next_seq + 1""",
            (tenant_id, today),
        )
        cur.execute(
            "SELECT next_seq FROM sr_sequence WHERE tenant_id = %s AND seq_date = %s",
            (tenant_id, today),
        )
        seq = cur.fetchone()["next_seq"]
        cur.close()
    return f"SR-{today.strftime('%Y%m%d')}-{seq:04d}"
