"""Rate limiting & abuse protection on POST /api/chat (Phase 8 — 2.0).

Combined per-IP AND per-tenant limits, owner-confirmed at kickoff — a
single IP can't flood one tenant, and a single tenant's aggregate
traffic is capped independently too. Fixed 1-minute windows, not
sliding.
"""
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from app.db.pool import get_conn

# Phase 8 — 2.2: defaults, not yet admin-configurable — a reasonable
# follow-up, not built this phase to keep scope contained.
IP_LIMIT_PER_MINUTE = 20
TENANT_LIMIT_PER_MINUTE = 100


def _client_ip(request: Request) -> str:
    """Phase 8 — 2.3: assumed, not confirmed at kickoff — prefers the
    first X-Forwarded-For entry if present (common reverse-proxy
    pattern), else the raw connecting client. Whether this app
    actually sits behind a proxy in production affects whether
    X-Forwarded-For is trustworthy at all; flagged the same way
    Phase III's cadence assumption was."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _current_window() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(second=0, microsecond=0, tzinfo=None)


def _increment_and_check(scope_type: str, scope_key: str, limit: int) -> bool:
    """Returns True if the request is allowed (under the limit after
    incrementing), False if it should be rejected."""
    window_start = _current_window()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO rate_limit_bucket (scope_type, scope_key, window_start, request_count)
               VALUES (%s, %s, %s, 1)
               ON DUPLICATE KEY UPDATE request_count = request_count + 1""",
            (scope_type, scope_key, window_start),
        )
        cur.execute(
            """SELECT request_count FROM rate_limit_bucket
               WHERE scope_type = %s AND scope_key = %s AND window_start = %s""",
            (scope_type, scope_key, window_start),
        )
        count = cur.fetchone()["request_count"]
        cur.close()
    return count <= limit


def enforce_rate_limit(tenant_id: int, request: Request) -> None:
    """Raises HTTPException(429) if either the per-IP or per-tenant
    limit is exceeded for the current minute window. Applied only to
    POST /api/chat, per the master prompt's literal scope."""
    ip = _client_ip(request)

    ip_ok = _increment_and_check("ip", ip, IP_LIMIT_PER_MINUTE)
    tenant_ok = _increment_and_check("tenant", str(tenant_id), TENANT_LIMIT_PER_MINUTE)

    if not ip_ok:
        raise HTTPException(status_code=429, detail="Too many requests from this address. Please slow down.")
    if not tenant_ok:
        raise HTTPException(status_code=429, detail="This tenant has exceeded its request limit. Please try again shortly.")
