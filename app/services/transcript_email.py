"""Anonymous chat transcript email (Phase 2 WBS 4.2).

Builds a plain-text transcript from `message` rows for a conversation
and sends it over SMTP to an address the visitor supplies at the end
of a chat — opt-in, no account, matching the "no SSO, no end-user
login, chats stay fully anonymous" scope decision in
docs/MASTER_PROMPT.md. This is NOT the "email channel" integration
explicitly declined there — a one-way, on-request transcript send at
the visitor's initiative is a different, much narrower thing than
routing live chat through an email inbox.
"""
import re
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.db.pool import get_conn, get_cursor

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TranscriptEmailError(Exception):
    """Raised for any user-facing failure: bad email, conversation not
    found for this tenant, or the deployment not having SMTP
    configured. The endpoint (app/api/chat.py) turns this into a 400
    without leaking SMTP internals to an anonymous caller."""


def _looks_like_email(addr: str) -> bool:
    # Deliberately loose — this rejects obvious garbage before it
    # reaches SMTP, it isn't validating deliverability. A stricter
    # regex or the email-validator package would be a new dependency
    # for marginal benefit here; SMTP's own delivery/bounce is the
    # real validator, same as any signup form.
    return bool(_EMAIL_RE.match(addr))


def build_transcript(tenant_id: int, conversation_id: str) -> str:
    """Plain text, oldest message first. Raises TranscriptEmailError
    if the conversation doesn't belong to this tenant (the same
    cross-tenant boundary `ask()` in app/services/chat.py enforces —
    a conversation_id is an opaque UUID a visitor's browser holds
    onto, and this endpoint is otherwise unauthenticated, so nothing
    stops a caller from guessing/passing an ID that isn't theirs
    except this check) or has no messages yet."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM conversation WHERE id = %s AND tenant_id = %s",
            (conversation_id, tenant_id),
        )
        if cur.fetchone() is None:
            raise TranscriptEmailError("Conversation not found.")

        cur.execute(
            """SELECT role, content, created_at FROM message
               WHERE conversation_id = %s AND tenant_id = %s
               ORDER BY id ASC""",
            (conversation_id, tenant_id),
        )
        rows = cur.fetchall()

    if not rows:
        raise TranscriptEmailError("This conversation has no messages yet.")

    lines = []
    for row in rows:
        speaker = "You" if row["role"] == "user" else "Assistant"
        lines.append(f"{speaker} ({row['created_at']}):\n{row['content']}\n")
    return "\n".join(lines)


def _send_email(to_addr: str, subject: str, body: str) -> None:
    """The one place that talks to SMTP. Split out from
    send_transcript_email() so tests can monkeypatch just this
    function instead of needing a real mail relay reachable from the
    test environment — the same "isolate the one I/O boundary" shape
    as _resolve_api_key() isolating the DB lookup in rbac.py."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_addr
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def send_transcript_email(
    tenant_id: int, conversation_id: str, visitor_email: str, agent_name: str = "Assistant"
) -> None:
    if not _looks_like_email(visitor_email):
        raise TranscriptEmailError("Please provide a valid email address.")

    if not settings.smtp_host:
        # Not configured — fail loudly rather than silently pretend to
        # send. A misconfigured deployment should surface as a clear
        # error to the operator, not a false "sent!" to the visitor.
        raise TranscriptEmailError("Transcript email is not configured for this deployment.")

    transcript = build_transcript(tenant_id, conversation_id)
    subject = f"Your conversation with {agent_name}"
    _send_email(visitor_email, subject, transcript)

    # Opt-in record: only written after a successful send, and only
    # ever set to the address the visitor just typed — never inferred
    # from anything else, never persisted before the email actually
    # goes out (a failed send shouldn't leave a stale opt-in record
    # behind).
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE conversation SET visitor_email = %s WHERE id = %s AND tenant_id = %s",
            (visitor_email, conversation_id, tenant_id),
        )
        cur.close()
