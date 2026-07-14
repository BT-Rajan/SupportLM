"""Tenant usage counting and plan-limit enforcement (WBS 5.2/5.3).

Counters are computed on read via COUNT queries rather than a running
counter table. The tenant-scoped indexes added in 1.4 — (tenant_id,
status) on `document`, (tenant_id, conversation_id, created_at) on
`message` — already make these cheap at this phase's scale, and a live
COUNT can never drift from reality the way a maintained counter column
could (e.g. a failed transaction leaving a counter incremented with no
matching row to show for it). A persisted rollup table is what Phase 7
analytics (historical trend data, not "right now" counts) will
actually need — not this.

Enforcement split matches what was confirmed for 5.1/5.2:
  - Document uploads: HARD block once doc_limit is reached.
  - Chat messages: SOFT warn once message_limit is reached for the
    current calendar month — the widget keeps answering; callers just
    get a warning string back to surface to the tenant admin.
Seats have a limit in `plan_tier` but nothing in the app creates
additional `tenant_user` rows yet beyond `create_tenant.py`'s single
owner link (Phase 2 introduces user invites/management), so there's no
enforcement point to wire seats into yet. `count_seats` exists so
Phase 2 has a ready-made check to call rather than reinventing one.
"""
from fastapi import HTTPException, status as http_status

from app.db.pool import get_cursor


def get_tier_limits(tenant_id: int) -> dict:
    """Returns {'slug', 'display_name', 'doc_limit', 'message_limit',
    'seat_limit'} for the tenant's current plan. Any limit is `None` if
    that resource is unlimited on this tier. Raises 404 if the tenant
    doesn't exist."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT pt.slug, pt.display_name, pt.doc_limit, pt.message_limit, pt.seat_limit
               FROM tenant t JOIN plan_tier pt ON pt.slug = t.plan_tier
               WHERE t.id = %s""",
            (tenant_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return row


def count_documents(tenant_id: int) -> int:
    """Every document row for this tenant counts against doc_limit,
    regardless of status (pending/processing/ready/error) — an
    in-flight or failed upload still occupies a document slot until
    it's deleted."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM document WHERE tenant_id = %s", (tenant_id,))
        return cur.fetchone()["n"]


def count_messages_this_period(tenant_id: int) -> int:
    """User-authored messages only (not the paired assistant replies)
    since the start of the current calendar month — "messages/month"
    means questions asked, not total rows in `message`."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n FROM message
               WHERE tenant_id = %s AND role = 'user'
                 AND created_at >= DATE_FORMAT(NOW(), '%%Y-%%m-01')""",
            (tenant_id,),
        )
        return cur.fetchone()["n"]


def count_seats(tenant_id: int) -> int:
    """Not enforced anywhere yet (see module docstring) — exists for
    Phase 2's user-invite flow to call."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tenant_user WHERE tenant_id = %s", (tenant_id,))
        return cur.fetchone()["n"]


def enforce_document_limit(tenant_id: int) -> None:
    """Raise 403 if this tenant is already at its doc_limit. Call this
    BEFORE inserting a new document — a limit of 25 means 25 may
    exist; the 26th upload is rejected."""
    limits = get_tier_limits(tenant_id)
    if limits["doc_limit"] is None:
        return
    if count_documents(tenant_id) >= limits["doc_limit"]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=(
                f"Document limit reached for the {limits['display_name']} plan "
                f"({limits['doc_limit']} documents). Delete a document or upgrade your plan."
            ),
        )


def message_limit_warning(tenant_id: int) -> str | None:
    """Returns a warning string if this tenant has reached or passed
    its message_limit for the current calendar month, else None. Never
    raises and never blocks — chat keeps answering regardless (soft
    warn, not a hard block, per the owner's decision)."""
    limits = get_tier_limits(tenant_id)
    if limits["message_limit"] is None:
        return None
    used = count_messages_this_period(tenant_id)
    if used >= limits["message_limit"]:
        return (
            f"This account has used {used} of {limits['message_limit']} messages "
            f"included in the {limits['display_name']} plan this month."
        )
    return None
