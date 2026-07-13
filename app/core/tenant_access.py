"""Tenant status lifecycle enforcement (WBS 2.2).

There's no per-request tenant resolution yet — that's 3.1's
request-scoping middleware, which comes after 2.0 in the build order.
So this module is split into two pieces on purpose:

  - `enforce_active(status)` is a pure function: given an
    already-known status string, decide whether to block the request.
    No DB access, trivially unit-testable today.
  - `get_tenant_status(tenant_id)` does the one-row DB lookup.

3.1's middleware will call `get_tenant_status(tenant_id)` then
`enforce_active(...)` on every request once it knows how to resolve
`tenant_id` (from subdomain/path/API key — undecided until 3.1 itself).
Until then, nothing in the app calls this yet; it exists so 3.1 has a
tested primitive to build on rather than inventing status-checking logic
inline in the middleware.
"""
from fastapi import HTTPException, status as http_status

from app.db.pool import get_cursor


class TenantNotFound(Exception):
    """Raised when a tenant_id doesn't correspond to any tenant row."""


def get_tenant_status(tenant_id: int) -> str:
    """Look up a tenant's current status. Raises TenantNotFound if the
    tenant_id doesn't exist (e.g. a stale API key or a deleted tenant)."""
    with get_cursor() as cur:
        cur.execute("SELECT status FROM tenant WHERE id = %s", (tenant_id,))
        row = cur.fetchone()
    if row is None:
        raise TenantNotFound(f"Tenant {tenant_id} does not exist")
    return row["status"]


def enforce_active(status: str) -> None:
    """Raise HTTPException if a tenant in this status should be blocked
    from making requests. 'trial' is allowed — trial tenants can use the
    product. 'suspended' is not. 'active' is obviously fine.

    Raises ValueError for any other value, since that indicates a data
    problem (the ENUM should prevent it, but a caller passing a raw
    string shouldn't silently pass through)."""
    if status == "suspended":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended. Contact support to reactivate it.",
        )
    if status not in ("active", "trial"):
        raise ValueError(f"Unknown tenant status: {status!r}")


def enforce_tenant_active(tenant_id: int) -> None:
    """Convenience wrapper: look up and enforce in one call. Raises 404
    if the tenant doesn't exist, 403 if suspended."""
    try:
        tenant_status = get_tenant_status(tenant_id)
    except TenantNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    enforce_active(tenant_status)
