"""Tenant status lifecycle enforcement (WBS 2.2).

Split into two small pieces by design:

  - `enforce_active(status)` is a pure function: given an
    already-known status string, decide whether to block the request.
    No DB access, trivially unit-testable.
  - `get_tenant_status(tenant_id)` does the one-row DB lookup.

Called together, inline, everywhere a request needs to check whether
its tenant is active — `app/core/tenant_scope.py`'s `resolve_tenant()`/
`resolve_tenant_for_admin()` and `app/core/rbac.py`'s `_resolve_api_key()`
all do `enforce_active(get_tenant_status(tenant_id))` directly rather
than through a combining wrapper, since each of those three call sites
needed a different exception type on the "tenant not found" path
(404 in some, a differently-shaped auth failure in others) that a
single generic wrapper couldn't cleanly express for all three at once.
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
