"""Request-scoped tenant resolution (WBS 3.1).

Decision required by 3.1 itself: how does a request say which tenant it
belongs to — subdomain, path param, or API key? **Path param.**

Why not subdomain: wildcard-subdomain routing needs DNS + reverse-proxy
vhost config in front of the app. That's infra work, and infra work
(Docker/CI-CD/staging/IaC) is explicitly out of scope for this
transformation per `docs/MASTER_PROMPT.md` Section 2.8 — there is no
reverse proxy in this deployment to terminate subdomains at.

Why not API key: a public per-tenant API key system for the anonymous
chat widget is exactly what Phase 2 introduces ("API keys for
programmatic access"). Building one now would duplicate that work under
a different name a phase early.

So: every tenant-scoped route carries `{tenant_slug}` as a path segment,
and this module is the single place that segment gets turned into a
trusted `tenant_id` before a route body runs — rather than each handler
remembering to look it up (and possibly getting it wrong) itself.

Two dependencies, for the two kinds of caller in this app:

  - `resolve_tenant(tenant_slug)` — anonymous routes (the chat widget).
    slug -> tenant_id, 404 if the slug doesn't exist, 403 if the tenant
    is suspended (reuses 2.2's `enforce_active`). No admin auth involved.

  - `resolve_tenant_for_admin(tenant_slug, admin_id)` — admin-session
    routes. Does everything `resolve_tenant` does, PLUS confirms the
    logged-in admin is actually linked to that tenant via `tenant_user`.
    This is the check that stops admin A from reading tenant B's data
    just by typing B's slug into the URL — necessary because 2.1 made
    "one admin owns multiple tenants" a real, valid case, so admin auth
    alone (`require_admin`) can't imply which tenant is meant. 403 if
    the admin isn't linked to the tenant named in the URL.

Scope note: this round builds and validates the resolution mechanism
itself. It is not yet called from any route — wiring it into the actual
routes and auditing every existing query in `app/api/*` /
`app/services/*` to filter by the resolved `tenant_id` is 3.2, which
comes after 3.1 in the WBS's own dependency graph. Same
build-the-piece-before-its-consumer-exists pattern as `tenant_access.py`
in round 6.
"""
from fastapi import Depends, HTTPException, Path, status as http_status

from app.core.deps import require_admin
from app.core.tenant_access import enforce_active, get_tenant_status
from app.db.pool import get_cursor


def _tenant_id_for_slug(tenant_slug: str) -> int:
    """Look up a tenant by slug. 404 if no tenant has this slug."""
    with get_cursor() as cur:
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (tenant_slug,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return row["id"]


def _admin_linked_to_tenant(tenant_id: int, admin_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM tenant_user WHERE tenant_id = %s AND admin_id = %s",
            (tenant_id, admin_id),
        )
        return cur.fetchone() is not None


def resolve_tenant(tenant_slug: str = Path(...)) -> int:
    """Resolve `{tenant_slug}` to a tenant_id for an anonymous,
    tenant-scoped route (the chat widget). 404 unknown slug, 403
    suspended tenant."""
    tenant_id = _tenant_id_for_slug(tenant_slug)
    enforce_active(get_tenant_status(tenant_id))
    return tenant_id


def resolve_tenant_for_admin(
    tenant_slug: str = Path(...),
    admin_id: int = Depends(require_admin),
) -> int:
    """Resolve `{tenant_slug}` to a tenant_id for an admin-session route.
    Same checks as `resolve_tenant`, plus: 403 unless `admin_id` (from
    the session cookie) is linked to this tenant via `tenant_user`."""
    tenant_id = _tenant_id_for_slug(tenant_slug)
    enforce_active(get_tenant_status(tenant_id))
    if not _admin_linked_to_tenant(tenant_id, admin_id):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant.",
        )
    return tenant_id
