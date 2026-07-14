"""RBAC role hierarchy and enforcement (Phase 2 WBS 1.0).

Extends the placeholder `tenant_user.role` ('owner'/'admin', Phase 1's
002 migration) into the four tiers 008_rbac_roles.sql adds: owner >
admin > editor > viewer. Role lives on `tenant_user`, not `admin_user`
— deliberately: the same admin_user can be 'owner' on one tenant and
'viewer' on another (Phase 1's 2.1 already made "one admin, multiple
tenants" a real case), so a single account-wide role on `admin_user`
can't express that. `admin_user.role` is legacy from before
multi-tenancy existed and is not read anywhere for authorization
(confirmed: only ever written by `create_admin.py`/`create_tenant.py`)
— left in place rather than dropped, since dropping a column is a
breaking schema change worth its own explicit task, not a side effect
of 1.1.

`require_role(min_role)` returns a FastAPI dependency that does
everything `resolve_tenant_for_admin` does (slug -> tenant_id, active
check, admin-linked-to-tenant check) — by calling it directly as a
plain function, not duplicating its checks — PLUS confirms the linked
role meets `min_role`. This is what replaces the single flat
`require_admin`/`resolve_tenant_for_admin` (any authenticated, linked
admin could do anything) on routes where the master prompt's Phase 2
scope calls for a minimum role instead.

Scope note: this round (1.2) is session-cookie only. 2.3 extends this
same function to also accept an `X-API-Key` header once 2.1/2.2 build
the key store it would check against — same
build-the-piece-before-its-consumer-exists pattern used throughout
this project (e.g. `tenant_scope.py`'s round 6/round 3.1 split).
"""
from fastapi import Depends, HTTPException, status as http_status

from app.core.deps import require_admin
from app.core.tenant_scope import resolve_tenant_for_admin
from app.db.pool import get_cursor

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}


def get_role_for_tenant(tenant_id: int, admin_id: int) -> str | None:
    """This admin's role on this tenant, or None if not linked at all.
    `resolve_tenant_for_admin` already guarantees a linked row exists
    by the time this is called from `require_role` below, but this is
    also usable standalone (e.g. for a future "what can I do here?"
    UI check), so it stays defensive rather than assuming."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT role FROM tenant_user WHERE tenant_id = %s AND admin_id = %s",
            (tenant_id, admin_id),
        )
        row = cur.fetchone()
    return row["role"] if row else None


def require_role(min_role: str):
    """Dependency factory. `min_role` must be a key in ROLE_RANK.

    Fails fast (at import time, not per-request) if `min_role` is a
    typo — every call site is `Depends(require_role("editor"))` at
    router-definition time, so a bad role name should break the app on
    startup, not silently 500 on the first real request."""
    if min_role not in ROLE_RANK:
        raise ValueError(
            f"Unknown role '{min_role}'; must be one of {sorted(ROLE_RANK)}"
        )

    def _dependency(
        tenant_id: int = Depends(resolve_tenant_for_admin),
        admin_id: int = Depends(require_admin),
    ) -> int:
        role = get_role_for_tenant(tenant_id, admin_id)
        if role is None:
            # Shouldn't happen — resolve_tenant_for_admin already 403s
            # if the admin isn't linked — but never assume a role
            # exists just because membership does.
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this tenant.",
            )
        if ROLE_RANK[role] < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{min_role}' role or higher; you have '{role}'.",
            )
        return tenant_id

    return _dependency
