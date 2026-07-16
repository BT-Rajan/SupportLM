"""Service Request generation (Phase 6 — 2.0/3.0).

`generate_sr_number()` is usable on its own; `complete_escalation()` is
the full 3.2 flow — validate, generate the SR, send both notification
emails, then persist the SR row.
"""
import logging
from datetime import date

from app.db.pool import get_conn, get_cursor
from app.services.transcript_email import _looks_like_email, _send_email, build_transcript

logger = logging.getLogger("supportlm.escalation")


class EscalationError(Exception):
    """Raised for any user-facing failure — bad email, message not
    found/not eligible, already escalated, or no support inbox
    configured for this tenant. The endpoint (app/api/chat.py) turns
    this into a 400/404/409 without leaking internals to an anonymous
    caller, same pattern as TranscriptEmailError."""


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


def complete_escalation(tenant_id: int, message_id: int, visitor_email: str) -> dict:
    """The full 3.2 flow. Order matters, deliberately: both emails are
    sent BEFORE the service_request row is inserted, mirroring
    transcript_email.py's "only persist after a successful send"
    philosophy — a failed send must leave a retryable state, not a
    stale/half-created SR blocking every future attempt for the same
    message_id (which is UNIQUE, so once a row exists, it exists for
    good).

    Accepted tradeoff, not silently glossed over: if the company email
    succeeds but the visitor email then fails, the company has already
    received a notification referencing an SR number that never gets
    persisted (since the row insert never happens on this failed
    attempt) — a retry generates a genuinely new SR number and the
    company gets a second, similar email. This is a minor real-world
    imperfection, not a data-loss risk, and is judged an acceptable
    cost for guaranteeing retries never get permanently blocked by a
    transient SMTP hiccup.
    """
    if not _looks_like_email(visitor_email):
        raise EscalationError("Please provide a valid email address.")

    with get_cursor() as cur:
        cur.execute(
            "SELECT conversation_id, role, needs_escalation FROM message WHERE id = %s AND tenant_id = %s",
            (message_id, tenant_id),
        )
        message_row = cur.fetchone()
    if message_row is None:
        raise EscalationError("Message not found.")
    if message_row["role"] != "assistant" or not message_row["needs_escalation"]:
        # Doesn't distinguish "not an assistant message" from "didn't
        # signal escalation" in the error text — neither is a message
        # a legitimate escalation request would ever reference.
        raise EscalationError("This message did not trigger an escalation request.")

    with get_cursor() as cur:
        cur.execute("SELECT id FROM service_request WHERE message_id = %s", (message_id,))
        if cur.fetchone() is not None:
            raise EscalationError("A support request was already created for this conversation.")

    with get_cursor() as cur:
        cur.execute(
            "SELECT support_email FROM tenant_support_config WHERE tenant_id = %s", (tenant_id,)
        )
        support_config = cur.fetchone()
    if support_config is None:
        # Honest, not a fabricated "ticket created!" — per
        # docs/Phase VI WBS.md's 3.2 design note, this must not
        # silently half-succeed.
        raise EscalationError("Human follow-up isn't available for this chat right now.")

    conversation_id = message_row["conversation_id"]
    transcript = build_transcript(tenant_id, conversation_id)
    sr_number = generate_sr_number(tenant_id)

    _send_email(
        support_config["support_email"],
        f"New support request {sr_number}",
        f"A visitor's question could not be fully answered by the assistant.\n\n"
        f"SR number: {sr_number}\nVisitor email: {visitor_email}\n\nTranscript:\n{transcript}",
    )
    _send_email(
        visitor_email,
        f"Your support request {sr_number}",
        f"We've created a support request for your conversation and a team member will "
        f"follow up with you.\n\nSR number: {sr_number}\n\nTranscript:\n{transcript}",
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO service_request (tenant_id, sr_number, conversation_id, message_id, visitor_email)
               VALUES (%s, %s, %s, %s, %s)""",
            (tenant_id, sr_number, conversation_id, message_id, visitor_email),
        )
        cur.close()

    logger.info("Escalation completed: tenant=%s sr_number=%s message_id=%s", tenant_id, sr_number, message_id)
    return {"sr_number": sr_number}
