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

2.3 update: `require_role()` now accepts either the session cookie OR
an `X-API-Key` header on the same tenant-scoped routes. A key is
checked against the tenant named in the URL (`tenant_slug`) and must
not be revoked — mirroring the session path's membership + role check,
but against `api_key` instead of `tenant_user`. Because the two auth
modes resolve tenant + role differently (session: cookie -> admin_id ->
tenant_user row; key: header -> hash lookup -> api_key row directly),
`_dependency` branches on whether `X-API-Key` was sent rather than
composing them through FastAPI's `Depends()` graph — `resolve_tenant_for_admin`
and `require_admin` are called directly as plain functions on the
session branch instead, the same "call it directly, don't duplicate
its checks" pattern `tenant_scope.py` already uses `tenant_id_for_slug()`
for on the key branch.
"""
import hashlib
import secrets

from fastapi import Cookie, Header, HTTPException, Path, status as http_status

from app.core.deps import require_admin
from app.core.tenant_access import enforce_active, get_tenant_status
from app.core.tenant_scope import resolve_tenant_for_admin, tenant_id_for_slug
from app.db.pool import get_cursor

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}

_KEY_PREFIX = "sk_live_"


def generate_api_key() -> str:
    """A fresh raw API key. Returned to the caller exactly once at
    creation time (2.2) — only its hash is ever persisted, so this is
    the only point in the key's lifecycle where the plaintext exists
    outside the requester's own hands."""
    return _KEY_PREFIX + secrets.token_hex(24)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def key_prefix_for_display(raw_key: str) -> str:
    """Enough of the raw key to recognize it in a list view (2.2's
    GET /api-keys) without the hash being reversible to get it back."""
    return raw_key[: len(_KEY_PREFIX) + 6]


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


def _resolve_api_key(tenant_slug: str, raw_key: str) -> tuple[int, str] | None:
    """Look up an active `api_key` for this raw key AND this tenant
    slug. Returns `(tenant_id, role)`, or None if the key doesn't
    exist, is revoked, or belongs to a different tenant than the one
    named in the URL — a key minted for tenant A must not authenticate
    a request to tenant B's routes, the same boundary
    `resolve_tenant_for_admin` enforces for session auth via
    `tenant_user` membership. Checked against the tenant's active
    status too (`enforce_active`), same as every other tenant-scoped
    entry point — a suspended tenant's keys stop working along with
    everything else, not just its admin sessions."""
    tenant_id = tenant_id_for_slug(tenant_slug)
    enforce_active(get_tenant_status(tenant_id))
    key_hash = hash_api_key(raw_key)
    with get_cursor() as cur:
        cur.execute(
            "SELECT role FROM api_key WHERE tenant_id = %s AND key_hash = %s AND revoked_at IS NULL",
            (tenant_id, key_hash),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return tenant_id, row["role"]


def _authenticate(tenant_slug: str, x_api_key: str | None, session: str | None) -> tuple[int, str, int | None]:
    """Shared resolution for both auth modes: `X-API-Key` header if
    present, else the session cookie. Returns `(tenant_id, role,
    admin_id)` — `admin_id` is None for key auth (a key isn't tied to
    an admin at request time, only at mint time via
    `api_key.created_by_admin_id`). Split out from `require_role` so a
    caller that needs more than a pass/fail check — the role itself,
    or which admin is calling — has somewhere to get it without a
    second DB round-trip or duplicating this branch. Currently only
    `require_role_ctx` (below, used by 2.2's key-minting endpoint to
    cap a new key's role at the creating admin's own, and to stamp
    `created_by_admin_id`) needs that; `require_role` itself still only
    returns `tenant_id`, unchanged, so no existing call site in
    `documents.py`/`categories.py` needs updating."""
    if x_api_key is not None:
        resolved = _resolve_api_key(tenant_slug, x_api_key)
        if resolved is None:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API key.",
            )
        tenant_id, role = resolved
        return tenant_id, role, None

    admin_id = require_admin(session)
    tenant_id = resolve_tenant_for_admin(tenant_slug, admin_id)
    role = get_role_for_tenant(tenant_id, admin_id)
    if role is None:
        # Shouldn't happen — resolve_tenant_for_admin already 403s if
        # the admin isn't linked — but never assume a role exists just
        # because membership does.
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant.",
        )
    return tenant_id, role, admin_id


def require_role(min_role: str):
    """Dependency factory. `min_role` must be a key in ROLE_RANK.

    Fails fast (at import time, not per-request) if `min_role` is a
    typo — every call site is `Depends(require_role("editor"))` at
    router-definition time, so a bad role name should break the app on
    startup, not silently 500 on the first real request.

    Auth: `X-API-Key` header if present, else the session cookie —
    never both checked/mixed for one request. A request that sends a
    (bad) key doesn't fall back to session auth; that would let an
    expired/typo'd key silently succeed via whatever cookie happens to
    also be sitting in the browser, which isn't how "provide this
    credential" should behave for a programmatic caller."""
    if min_role not in ROLE_RANK:
        raise ValueError(
            f"Unknown role '{min_role}'; must be one of {sorted(ROLE_RANK)}"
        )

    def _dependency(
        tenant_slug: str = Path(...),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        session: str | None = Cookie(default=None),
    ) -> int:
        tenant_id, role, _admin_id = _authenticate(tenant_slug, x_api_key, session)
        if ROLE_RANK[role] < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{min_role}' role or higher; you have '{role}'.",
            )
        return tenant_id

    return _dependency


def require_role_ctx(min_role: str):
    """Same auth/role-floor check as `require_role`, but returns
    `(tenant_id, role, admin_id)` instead of just `tenant_id` — for the
    one call site (2.2's create-key endpoint) that needs the caller's
    own role and identity, not just confirmation it clears a minimum."""
    if min_role not in ROLE_RANK:
        raise ValueError(
            f"Unknown role '{min_role}'; must be one of {sorted(ROLE_RANK)}"
        )

    def _dependency(
        tenant_slug: str = Path(...),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        session: str | None = Cookie(default=None),
    ) -> tuple[int, str, int | None]:
        tenant_id, role, admin_id = _authenticate(tenant_slug, x_api_key, session)
        if ROLE_RANK[role] < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{min_role}' role or higher; you have '{role}'.",
            )
        return tenant_id, role, admin_id

    return _dependency
